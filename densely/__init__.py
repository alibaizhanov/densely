#!/usr/bin/env python3
"""densely — lossless context compression for LLMs.

Packs any text into ~2x-8x fewer o200k tokens with guaranteed byte-exact
reconstruction. Pipeline: lzma -> 16-bit chunks -> alphabet of 65,536
single-token English words. Each word costs exactly 1 token (the o200k
pre-tokenizer never merges across " word" boundaries), so 1 token carries
2 bytes of compressed data. A sha256 fingerprint in the header is checked
on decompression.

The payload is not human/model readable — it is a dense carrier for exact
data, meant to sit next to a readable summary.
"""

import hashlib
import lzma
import re
import sys

import tiktoken

ENC = tiktoken.get_encoding("o200k_base")
MAGIC = "DENSE1"
MAGIC_NEURAL = "DENSE2"


def _alphabet():
    words = []
    for b, tid in ENC._mergeable_ranks.items():
        try:
            s = b.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if re.fullmatch(r" [A-Za-z]+", s) and ENC.encode(s) == [tid]:
            words.append(s)
    words.sort(key=lambda w: (len(w), w))  # deterministic order, shortest first
    return words[:65536]


WORDS = _alphabet()
INDEX = {w: i for i, w in enumerate(WORDS)}
assert len(WORDS) == 65536

# альтернативные алфавиты (напр. эмпирически откалиброванные под закрытые
# токенизаторы, см. tools/build_alphabet.py) лежат в densely/alphabets/*.txt
import math
import os

_ALPHABETS = {"o200k": (WORDS, 16, INDEX)}


def _get_alphabet(name: str):
    if name not in _ALPHABETS:
        path = os.path.join(os.path.dirname(__file__), "alphabets", name + ".txt")
        words = [" " + w for w in open(path, encoding="utf-8").read().split()]
        bits = int(math.log2(len(words)))
        words = words[: 1 << bits]
        _ALPHABETS[name] = (words, bits, {w: i for i, w in enumerate(words)})
    return _ALPHABETS[name]


def _pack_bits(data: bytes, bits: int):
    acc = nacc = 0
    out = []
    mask = (1 << bits) - 1
    for byte in data:
        acc = (acc << 8) | byte
        nacc += 8
        while nacc >= bits:
            nacc -= bits
            out.append((acc >> nacc) & mask)
    if nacc:
        out.append((acc << (bits - nacc)) & mask)
    return out


def _unpack_bits(indices, bits: int, nbytes: int) -> bytes:
    acc = nacc = 0
    out = bytearray()
    for idx in indices:
        acc = (acc << bits) | idx
        nacc += bits
        while nacc >= 8:
            nacc -= 8
            out.append((acc >> nacc) & 0xFF)
    return bytes(out[:nbytes])


def ntok(s: str) -> int:
    return len(ENC.encode(s))


def _pack_words(packed: bytes):
    pad = len(packed) % 2
    if pad:
        packed += b"\x00"
    body = "".join(
        WORDS[(packed[i] << 8) | packed[i + 1]] for i in range(0, len(packed), 2)
    )
    return body, pad


FAST_PRESET_THRESHOLD = 2_000_000  # bytes; above this lzma -9e gets slow


def compress(text: str, backend: str = "lzma", preset: int | None = None,
             alphabet: str = "o200k") -> str:
    if backend == "neural":
        try:
            payload = _compress_neural(text)
            if decompress(payload) == text:
                return payload
            print("neural round-trip mismatch, falling back to lzma", file=sys.stderr)
        except Exception as e:
            print(f"neural backend failed ({e}), falling back to lzma", file=sys.stderr)
    raw = text.encode("utf-8")
    if preset is None:
        preset = 6 if len(raw) > FAST_PRESET_THRESHOLD else 9 | lzma.PRESET_EXTREME
    packed = lzma.compress(raw, preset=preset)
    digest = hashlib.sha256(raw).hexdigest()[:16]
    if alphabet != "o200k":
        words, bits, _ = _get_alphabet(alphabet)
        body = "".join(words[i] for i in _pack_bits(packed, bits))
        return f"{MAGIC} alph={alphabet} len={len(packed)} sha={digest}\n{body}"
    body, pad = _pack_words(packed)
    return f"{MAGIC} pad={pad} sha={digest}\n{body}"


def _compress_neural(text: str) -> str:
    from . import neural
    data, n_tokens = neural.encode(text)
    body, pad = _pack_words(data)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{MAGIC_NEURAL} pad={pad} sha={digest} n={n_tokens}\n{body}"


def decompress(payload: str) -> str:
    header, _, body = payload.partition("\n")
    fields = header.split(" ")
    magic = fields[0]
    if magic not in (MAGIC, MAGIC_NEURAL):
        raise ValueError("not a densely payload")
    kv = dict(f.split("=", 1) for f in fields[1:] if "=" in f)
    want_sha = kv["sha"]
    if "alph" in kv:
        words, bits, index = _get_alphabet(kv["alph"])
        indices = [index[" " + piece] for piece in body.split(" ") if piece]
        packed = _unpack_bits(indices, bits, int(kv["len"]))
        try:
            raw = lzma.decompress(packed)
        except lzma.LZMAError as e:
            raise ValueError(f"corrupt payload: {e}") from e
        if hashlib.sha256(raw).hexdigest()[:16] != want_sha:
            raise ValueError("sha mismatch after decompression")
        return raw.decode("utf-8")
    pad = int(kv["pad"])

    out = bytearray()
    for piece in body.split(" "):
        if not piece:
            continue
        idx = INDEX[" " + piece]
        out.append(idx >> 8)
        out.append(idx & 0xFF)
    if pad:
        out = out[:-1]
    if magic == MAGIC_NEURAL:
        from . import neural
        n_tokens = int(fields[3].split("=")[1])
        text = neural.decode(bytes(out), n_tokens)
        if hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] != want_sha:
            raise ValueError("sha mismatch after decompression")
        return text
    try:
        raw = lzma.decompress(bytes(out))
    except lzma.LZMAError as e:
        raise ValueError(f"corrupt payload: {e}") from e
    if hashlib.sha256(raw).hexdigest()[:16] != want_sha:
        raise ValueError("sha mismatch after decompression")
    return raw.decode("utf-8")


__version__ = "0.2.0"
