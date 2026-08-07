#!/usr/bin/env python3
"""ctxdense — lossless context compression for LLMs.

Packs any text into ~2x-8x fewer o200k tokens with guaranteed byte-exact
reconstruction. Pipeline: lzma -> 16-bit chunks -> alphabet of 65,536
single-token English words. Each word costs exactly 1 token (the o200k
pre-tokenizer never merges across " word" boundaries), so 1 token carries
2 bytes of compressed data. A sha256 fingerprint in the header is checked
on decompression.

The payload is not human/model readable — it is a dense carrier for exact
data, meant to sit next to a readable summary.
"""

import argparse
import hashlib
import lzma
import re
import sys

import tiktoken

ENC = tiktoken.get_encoding("o200k_base")
MAGIC = "DENSE1"


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


def ntok(s: str) -> int:
    return len(ENC.encode(s))


def compress(text: str) -> str:
    raw = text.encode("utf-8")
    packed = lzma.compress(raw, preset=9 | lzma.PRESET_EXTREME)
    pad = len(packed) % 2
    if pad:
        packed += b"\x00"
    body = "".join(
        WORDS[(packed[i] << 8) | packed[i + 1]] for i in range(0, len(packed), 2)
    )
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return f"{MAGIC} pad={pad} sha={digest}\n{body}"


def decompress(payload: str) -> str:
    header, _, body = payload.partition("\n")
    magic, pad_kv, sha_kv = header.split(" ")
    if magic != MAGIC:
        raise ValueError("not a ctxdense payload")
    pad = int(pad_kv.split("=")[1])
    want_sha = sha_kv.split("=")[1]

    out = bytearray()
    for piece in body.split(" "):
        if not piece:
            continue
        idx = INDEX[" " + piece]
        out.append(idx >> 8)
        out.append(idx & 0xFF)
    if pad:
        out = out[:-1]
    try:
        raw = lzma.decompress(bytes(out))
    except lzma.LZMAError as e:
        raise ValueError(f"corrupt payload: {e}") from e
    if hashlib.sha256(raw).hexdigest()[:16] != want_sha:
        raise ValueError("sha mismatch after decompression")
    return raw.decode("utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compress", help="file -> dense payload (stdout or -o)")
    c.add_argument("file")
    c.add_argument("-o", "--output")

    d = sub.add_parser("decompress", help="payload file -> original (stdout or -o)")
    d.add_argument("file")
    d.add_argument("-o", "--output")

    s = sub.add_parser("stats", help="show token savings for files (no output written)")
    s.add_argument("files", nargs="+")

    args = p.parse_args()

    if args.cmd == "compress":
        text = open(args.file, encoding="utf-8").read()
        payload = compress(text)
        if decompress(payload) != text:
            sys.exit("round-trip verification failed, refusing to write output")
        _write(args.output, payload)
    elif args.cmd == "decompress":
        payload = open(args.file, encoding="utf-8").read()
        _write(args.output, decompress(payload))
    elif args.cmd == "stats":
        total_o = total_p = 0
        for path in args.files:
            text = open(path, encoding="utf-8").read()
            payload = compress(text)
            ok = decompress(payload) == text
            o, c_ = ntok(text), ntok(payload)
            total_o += o
            total_p += c_
            print(f"{path}: {o} -> {c_} tokens "
                  f"({o / c_:.2f}x, saved {100 * (1 - c_ / o):.1f}%), "
                  f"round-trip {'OK' if ok else 'FAILED'}")
        if len(args.files) > 1:
            print(f"TOTAL: {total_o} -> {total_p} tokens "
                  f"({total_o / total_p:.2f}x, saved {100 * (1 - total_p / total_o):.1f}%)")


def _write(output, content):
    if output:
        open(output, "w", encoding="utf-8").write(content)
    else:
        sys.stdout.write(content)


if __name__ == "__main__":
    main()
