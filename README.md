# ctxdense

**Lossless context compression for LLMs.** Pack any text into 2x–8x fewer
tokens with guaranteed byte-exact reconstruction — verified by sha256 on
every decompress.

An o200k token can carry up to ~17.6 bits of information, but typical code
occupies tokens at only ~5–6 bits each. ctxdense reclaims the difference:

```
text -> lzma -> 16-bit chunks -> 65,536 single-token English words
```

Each carrier word (`" the"`, `" of"`, …) costs exactly **1 token** — the
o200k pre-tokenizer never merges across word boundaries — so every token
in the payload carries 2 bytes of compressed data (16 of the ~17.6
theoretically available bits, 91% of channel capacity).

## Benchmarks

Reproduce with `python3 bench.py` (fixed seeds, stdlib code sample):

| Scenario                      | Tokens (o200k)    | Ratio | Saved |
|-------------------------------|-------------------|-------|-------|
| Code (argparse.py + ctxdense) | 21,338 → 10,584   | 2.02x | 50.4% |
| JSON (code search, 100 hits)  | 15,465 → 1,995    | 7.75x | 87.1% |
| Logs (SRE incident, ~1600 ln) | 117,766 → 16,962  | 6.94x | 85.6% |

For comparison, [Headroom](https://github.com/headroomlabs-ai/headroom)
reports 15–20% savings for coding agents and 60–95% on JSON — achieved by
*dropping* content from context, with originals kept in a local cache with
a TTL. ctxdense keeps the full data in the context itself, restorable
byte-for-byte with no external storage and no expiry.

Lossless compression below the entropy of the data is mathematically
impossible (Shannon; see also [Fundamental Limits of Prompt
Compression](https://arxiv.org/abs/2407.15504)) — within that bound,
ctxdense sits near the practical ceiling for a deterministic, CPU-only
method.

## Usage

```bash
pip install tiktoken

python3 ctxdense.py compress  big_context.txt -o payload.ctxd
python3 ctxdense.py decompress payload.ctxd   -o restored.txt   # byte-identical
python3 ctxdense.py stats     file1.py file2.json                # token savings
```

Library:

```python
from ctxdense import compress, decompress

payload = compress(text)        # ~2x-8x fewer tokens
assert decompress(payload) == text  # always true, sha256-checked
```

`compress` via the CLI self-verifies the round trip before writing output;
`decompress` raises `ValueError` on any corruption or hash mismatch.

## The honest caveats

- **The payload is not readable** — by humans or by the model. It looks
  like a stream of random English words. Use it as a dense carrier for
  exact data (chat history, tool outputs, source files) alongside a
  readable summary; expand it with a tool call when exact content is
  needed.
- Savings depend on redundancy: highly repetitive data (JSON, logs)
  compresses 7x+, dense prose ~1.5–2x, already-compressed or random data
  ~0% (payload is never larger than a few header tokens worse than raw
  input — check `stats` before shipping).
- Token counts are measured with the o200k tokenizer. Other tokenizers
  share the single-token-word property but need their own alphabet scan.

## Roadmap

- Neural compression backend (ts_zip-style LLM + arithmetic coding):
  measured ~1.02 bit/byte on source code vs lzma's ~2.4 — would push code
  savings from ~50% to ~75%. Requires solving bit-exact deterministic
  inference; planned as an optional backend, not the default.

## Tests

```bash
python3 -m pytest test_ctxdense.py
```

13 tests: byte-exact round-trips (unicode, CJK, emoji, random bytes,
payload-lookalike inputs), tamper detection, carrier-alphabet density.
