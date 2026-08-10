# densely

**Lossless context compression for LLMs.** Pack any text into 2x–8x fewer
tokens with guaranteed byte-exact reconstruction — verified by sha256 on
every decompress.

![demo](assets/demo.gif)

An o200k token can carry up to ~17.6 bits of information, but typical code
occupies tokens at only ~5–6 bits each. densely reclaims the difference:

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
| Code (argparse.py + densely) | lzma    | 21,659 → 10,726   | 2.02x | 50.5% |
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
a TTL. densely keeps the full data in the context itself, restorable
byte-for-byte with no external storage and no expiry.

Lossless compression below the entropy of the data is mathematically
impossible (Shannon; see also [Fundamental Limits of Prompt
Compression](https://arxiv.org/abs/2407.15504)) — within that bound,
densely sits near the practical ceiling for a deterministic, CPU-only
method.

## Usage

```bash
pip install "densely[mcp]"
# extras: [neural] for the neural backend (torch + transformers)

densely compress  big_context.txt -o payload.dense
densely compress  src.py -o payload.dense --backend neural
densely decompress payload.dense   -o restored.txt   # byte-identical
densely stats     file1.py file2.json                # token savings
```

Library:

```python
from densely import compress, decompress

payload = compress(text)        # ~2x-8x fewer tokens
assert decompress(payload) == text  # always true, sha256-checked
```

`compress` via the CLI self-verifies the round trip before writing output;
`decompress` raises `ValueError` on any corruption or hash mismatch.

## Use it in Claude Code / Cursor (MCP)

```bash
# Claude Code
claude mcp add --scope user densely -- "$(which densely-mcp)"

# Cursor (~/.cursor/mcp.json) and other MCP clients
{"mcpServers": {"densely": {"command": "/absolute/path/to/densely-mcp"}}}
```

Three tools:

- **compress_file(path)** — agent calls this *instead of reading* a large
  log/JSON/dump: gets a preview + dense payload at 2x-8x fewer tokens.
- **compress_text(text)** — same for a big tool output already in hand.
- **expand(payload | payload_file, start_line, end_line)** — exact
  original back, sha256-verified; line ranges let the agent pay only for
  the slice it needs.

Every compression also writes a `.dense` sidecar file next to the
original — a plain text file you can commit, ship, or archive; no cache,
no TTL, nothing to expire. Small payloads are additionally returned
inline. This matters for context compaction: a compaction summary
replaces old conversation content, so an inline payload alone could be
summarized away — but the sidecar on disk (and its path, which carries
into summaries) cannot. If you use the Anthropic compaction API beta
directly, add this to your `instructions` so payload references survive
verbatim:

> Preserve any densely payload references (paths ending in .dense, or
> lines starting with DENSE1/DENSE2) verbatim in the summary. Do not
> call any tools while writing this summary.

## Automatic mode (hook)

Zero-effort savings: a PostToolUse hook compresses every large tool
output (Bash output, Read of non-code files, >= 5,000 tokens) on the
fly — the agent sees a preview + stats, exact content stays available
via search/expand, and every replacement is recorded in a savings
ledger (`stats` tool, or the running total shown in each replacement).

Add to `~/.claude/settings.json` (absolute paths — hooks run outside
your shell PATH):

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Read|Bash",
      "hooks": [{
        "type": "command",
        "command": "/absolute/path/to/densely-hook",
        "timeout": 30
      }]
    }]
  }
}
```

(`which densely-hook` after install gives the absolute path — hooks run
outside your shell PATH, so absolute paths only.)

Tune with `DENSELY_HOOK_MIN_TOKENS` (default 5000). Code files the agent
is editing are never touched.

## When it saves tokens (and when it doesn't)

Agent sessions resend the whole history to the API on every turn, so
anything sitting in context is paid for again and again. What densely
does to each kind of content:

| Content in context | Savings | Why |
|---|---|---|
| Code the agent is *actively editing* | **none — don't compress it** | the agent must read it; payloads are unreadable |
| Reference code (read once, kept "just in case") | 20–40% | exact copy stays cheap; `expand` a line range when needed |
| Tool outputs: logs, JSON, dumps | **78–87%** | the agent never needed all 1,500 lines — preview + targeted expand covers it |
| Anything that must survive compaction | indirect | payloads pass through compaction verbatim; summaries don't |

Note on prompt caching: cached history is cheaper, but the context
*window* stays the same size — densely primarily buys you room, then
money.

## vs. the field

The main players make different trade-offs (numbers from each project's
own published benchmarks):

|  | densely | [Headroom](https://github.com/headroomlabs-ai/headroom) | [claw-compactor](https://github.com/open-compress/claw-compactor) |
|---|---|---|---|
| Approach | entropy coding -> single-token carrier | lossy selection, model-readable output | 14 readable transform stages (2 lossy) |
| Exact recovery | **always: sha256-verified, in-conversation** | TTL cache, retrieval on demand | LRU "RewindStore", no verification documented |
| Logs | **85.6%** | ~92% (lossy) | 24.1% |
| JSON | 87.1% (lossless) | 60–95% (lossy) | 81.9% (via lossy sampling) |
| Code (active use) | none — by design | 15–20% (AST skeletons) | 25% |
| Model reads output | no (search/expand tools) | yes | yes |
| Agent integrations | MCP + hook + skill (Claude Code, Cursor) | proxy + wrap + MCP | CLI only |

Different philosophies: *maximum savings with silent degradation* vs.
*exactness or nothing*. Readable-lossy tools win on content the model
must keep reading; densely wins when the data must never be wrong and
must survive compaction, export, and machine moves. Use both.

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
- Token counts are measured with the o200k tokenizer, and the
  16-bits-per-token guarantee is o200k-specific. On other tokenizers
  reconstruction stays byte-exact but density degrades (measured:
  cl100k keeps only 54.5% of carrier words single-token — effective
  ~10.5 bits/token). Verify against your target with
  `python3 tools/calibrate.py` (supports tiktoken encodings and the
  Anthropic count_tokens API). Per-tokenizer alphabets are the fix and
  are on the roadmap — the o200k∩cl100k intersection already yields a
  15-bits/token alphabet valid on both.
- **Neural backend caveats**: slow (~85 KB of code takes minutes on Apple
  Silicon vs milliseconds for lzma) and requires torch + a ~1 GB model
  download on first use. Reconstruction is bit-exact only when
  decompression runs the same model/software stack as compression — which
  is why `compress(backend="neural")` verifies the full round trip before
  returning and silently falls back to lzma on any mismatch. The 100%
  guarantee never rests on the neural path.

## Densely Pro (coming)

The library is MIT and stays free. We're building a managed tier for
teams running agents in production:

- **Cloud neural compression** — 86% on code without a local GPU
- **Managed proxy** — savings with zero code changes
- **Team dashboard** — token savings per agent, per day, in dollars
- **Cross-machine payloads** — compress in CI, expand anywhere

**[Join the waitlist →](https://tally.so/r/Xx77V4)** (early access +
founding-user pricing)

## Roadmap

- Cross-machine determinism for the neural backend (integer/fixed-point
  inference or a mismatch-tolerant coder), so payloads compressed on one
  machine decompress on another.
- Larger/faster models via llama.cpp for better ratios at higher speed.

## Tests

```bash
python3 -m pytest tests/test_core.py tests/test_mcp.py   # fast suites
python3 -m pytest tests/test_neural.py                   # slow (~1 min): real LLM round trips
```

Fast suite: byte-exact round-trips (unicode, CJK, emoji, random bytes,
payload-lookalike inputs), tamper detection, carrier-alphabet density.
Neural suite: single- and multi-segment round trips, no-silent-fallback,
beats-lzma check.
