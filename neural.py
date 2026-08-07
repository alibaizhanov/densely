"""Neural backend for ctxdense: LLM + arithmetic coding.

Qwen2.5-Coder-0.5B predicts next-token probabilities; an integer
arithmetic coder turns them into bits. The decoder runs the exact same
sequence of forwards (same tensor shapes, same device), reproducing the
same probabilities, so reconstruction is bit-exact on the machine that
compressed. ctxdense.compress() verifies the full round trip and falls
back to the lzma backend on any mismatch, so the 100% guarantee never
rests on this module.

Input is split into equal-length segments (last one padded with EOS)
processed as one batch — one forward per step yields one token per
segment, the NNCP-style trick that makes small-model coding usable.
"""

import sys

import numpy as np
import torch

MODEL_ID = "Qwen/Qwen2.5-Coder-0.5B"
SEG = 1536
T_BITS = 24
T = 1 << T_BITS

_state = None


def _load():
    global _state
    if _state is None:
        from transformers import AutoTokenizer, AutoModelForCausalLM
        tok = AutoTokenizer.from_pretrained(MODEL_ID)
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        model = AutoModelForCausalLM.from_pretrained(MODEL_ID, dtype=torch.float32).to(device)
        model.eval()
        _state = (tok, model, device)
    return _state


class _BitWriter:
    def __init__(self):
        self.bits = []
        self.pending = 0

    def emit(self, b):
        self.bits.append(b)
        self.bits.extend([1 - b] * self.pending)
        self.pending = 0

    def to_bytes(self):
        bits = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(
            sum(bit << (7 - j) for j, bit in enumerate(bits[i:i + 8]))
            for i in range(0, len(bits), 8)
        )


class _BitReader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def read(self):
        i, j = divmod(self.pos, 8)
        self.pos += 1
        return (self.data[i] >> (7 - j)) & 1 if i < len(self.data) else 0


_HALF = 1 << 31
_Q1 = 1 << 30
_Q3 = 3 << 30
_MASK = (1 << 32) - 1


class _Encoder:
    def __init__(self):
        self.low, self.high = 0, _MASK
        self.out = _BitWriter()

    def encode(self, c_lo, c_hi):
        r = self.high - self.low + 1
        self.high = self.low + r * c_hi // T - 1
        self.low = self.low + r * c_lo // T
        while True:
            if self.high < _HALF:
                self.out.emit(0)
            elif self.low >= _HALF:
                self.out.emit(1)
                self.low -= _HALF
                self.high -= _HALF
            elif self.low >= _Q1 and self.high < _Q3:
                self.out.pending += 1
                self.low -= _Q1
                self.high -= _Q1
            else:
                break
            self.low = (self.low << 1) & _MASK
            self.high = ((self.high << 1) | 1) & _MASK

    def finish(self):
        self.out.pending += 1
        self.out.emit(0 if self.low < _Q1 else 1)
        return self.out.to_bytes()


class _Decoder:
    def __init__(self, data):
        self.inp = _BitReader(data)
        self.low, self.high = 0, _MASK
        self.code = 0
        for _ in range(32):
            self.code = (self.code << 1) | self.inp.read()

    def target(self):
        r = self.high - self.low + 1
        return ((self.code - self.low + 1) * T - 1) // r

    def consume(self, c_lo, c_hi):
        r = self.high - self.low + 1
        self.high = self.low + r * c_hi // T - 1
        self.low = self.low + r * c_lo // T
        while True:
            if self.high < _HALF:
                pass
            elif self.low >= _HALF:
                self.low -= _HALF
                self.high -= _HALF
                self.code -= _HALF
            elif self.low >= _Q1 and self.high < _Q3:
                self.low -= _Q1
                self.high -= _Q1
                self.code -= _Q1
            else:
                break
            self.low = (self.low << 1) & _MASK
            self.high = ((self.high << 1) | 1) & _MASK
            self.code = ((self.code << 1) | self.inp.read()) & _MASK


def _cdfs(logits_cpu):
    """(B, V) float32 logits -> per-row quantized cumulative freq (B, V+1) int64."""
    x = logits_cpu.numpy().astype(np.float64)
    x -= x.max(axis=1, keepdims=True)
    p = np.exp(x)
    p /= p.sum(axis=1, keepdims=True)
    v = p.shape[1]
    f = 1 + np.floor(p * (T - v)).astype(np.int64)
    deficit = T - f.sum(axis=1)
    f[np.arange(len(f)), p.argmax(axis=1)] += deficit
    cum = np.zeros((len(f), v + 1), dtype=np.int64)
    np.cumsum(f, axis=1, out=cum[:, 1:])
    return cum


def _layout(n):
    """n tokens -> (n_segments, segment_length); last segment is EOS-padded."""
    b = max(1, -(-n // SEG))
    return b, -(-n // b)


def _step(model, device, tokens_col, past):
    with torch.no_grad():
        out = model(torch.tensor(tokens_col, device=device).unsqueeze(1),
                    past_key_values=past, use_cache=True)
    return out.logits[:, -1, :].to("cpu"), out.past_key_values


def encode(text: str):
    """text -> (payload bytes, n_tokens). Raises on tokenizer round-trip failure."""
    tok, model, device = _load()
    ids = tok.encode(text)
    if tok.decode(ids) != text:
        raise ValueError("tokenizer round-trip failed")
    b, s = _layout(len(ids))
    pad = tok.eos_token_id
    padded = ids + [pad] * (b * s - len(ids))
    segs = [padded[i * s:(i + 1) * s] for i in range(b)]
    enc = _Encoder()
    cur = [pad] * b  # BOS column
    past = None
    for step in range(s):
        logits, past = _step(model, device, cur, past)
        cum = _cdfs(logits)
        for row in range(b):
            sym = segs[row][step]
            enc.encode(int(cum[row, sym]), int(cum[row, sym + 1]))
        cur = [segs[row][step] for row in range(b)]
        if step % 64 == 0:
            print(f"  encode {step}/{s} (batch {b})", file=sys.stderr, end="\r")
    return enc.finish(), len(ids)


def decode(data: bytes, n_tokens: int) -> str:
    tok, model, device = _load()
    b, s = _layout(n_tokens)
    dec = _Decoder(data)
    pad = tok.eos_token_id
    segs = [[] for _ in range(b)]
    cur = [pad] * b
    past = None
    for step in range(s):
        logits, past = _step(model, device, cur, past)
        cum = _cdfs(logits)
        for row in range(b):
            sym = int(np.searchsorted(cum[row], dec.target(), side="right")) - 1
            dec.consume(int(cum[row, sym]), int(cum[row, sym + 1]))
            segs[row].append(sym)
        cur = [segs[row][step] for row in range(b)]
        if step % 64 == 0:
            print(f"  decode {step}/{s} (batch {b})", file=sys.stderr, end="\r")
    flat = [t for seg in segs for t in seg][:n_tokens]
    return tok.decode(flat)
