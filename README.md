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

| Scenario                      | Backend | Tokens (o200k)    | Ratio | Saved |
|-------------------------------|---------|-------------------|-------|-------|
| Code (argparse.py + ctxdense) | lzma    | 21,659 → 10,726   | 2.02x | 50.5% |
| Code (same sample)            | neural  | 21,659 → 2,538    | 8.53x | **88.3%** |
| Code never seen by the model  | neural  | 3,433 → 472       | 7.27x | **86.3%** |
| JSON (code search, 100 hits)  | lzma    | 15,465 → 1,995    | 7.75x | 87.1% |
| Logs (SRE incident, ~1600 ln) | lzma    | 117,766 → 16,962  | 6.94x | 85.6% |

The neural backend (`--backend neural`, `python3 bench.py --neural`) drives
an integer arithmetic coder with next-token probabilities from
Qwen2.5-Coder-0.5B, NNCP-style batched across segments. The 88.3% figure
benefits from the model having seen Python's stdlib during training; the
86.3% row is this repo's own sources — code that did not exist before
2026-08-08 — and is the honest number for novel code (~0.56 bit/byte).

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
pip install tiktoken                    # lzma backend (default)
pip install torch transformers          # optional: neural backend

python3 ctxdense.py compress  big_context.txt -o payload.ctxd
python3 ctxdense.py compress  src.py -o payload.ctxd --backend neural
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

## Use it in Claude Code / Cursor (MCP)

```bash
# Claude Code
claude mcp add ctxdense -- python3 /path/to/ctxdense/ctxdense_mcp.py

# Cursor (~/.cursor/mcp.json) and other MCP clients
{"mcpServers": {"ctxdense": {"command": "python3", "args": ["/path/to/ctxdense/ctxdense_mcp.py"]}}}
```

Three tools:

- **compress_file(path)** — agent calls this *instead of reading* a large
  log/JSON/dump: gets a preview + dense payload at 2x-8x fewer tokens.
- **compress_text(text)** — same for a big tool output already in hand.
- **expand(payload, start_line, end_line)** — exact original back,
  sha256-verified; line ranges let the agent pay only for the slice it
  needs.

The payload lives in the conversation itself, so exact data survives
context compaction, session export, and moving to another machine — no
local cache, no TTL, nothing to expire.

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
- **Neural backend caveats**: slow (~85 KB of code takes minutes on Apple
  Silicon vs milliseconds for lzma) and requires torch + a ~1 GB model
  download on first use. Reconstruction is bit-exact only when
  decompression runs the same model/software stack as compression — which
  is why `compress(backend="neural")` verifies the full round trip before
  returning and silently falls back to lzma on any mismatch. The 100%
  guarantee never rests on the neural path.

## Roadmap

- Cross-machine determinism for the neural backend (integer/fixed-point
  inference or a mismatch-tolerant coder), so payloads compressed on one
  machine decompress on another.
- Larger/faster models via llama.cpp for better ratios at higher speed.

## Tests

```bash
python3 -m pytest test_ctxdense.py      # fast: lzma backend, 13 tests
python3 -m pytest test_neural.py        # slow (~1 min): real LLM round trips
```

Fast suite: byte-exact round-trips (unicode, CJK, emoji, random bytes,
payload-lookalike inputs), tamper detection, carrier-alphabet density.
Neural suite: single- and multi-segment round trips, no-silent-fallback,
beats-lzma check.
