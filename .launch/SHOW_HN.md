# Show HN draft (not part of the library — delete before/after posting)

**Title options (HN limit 80 chars):**

1. Show HN: Densely – lossless context compression for LLMs (86% on code)
2. Show HN: Fit 5x more exact data in your agent's context window
3. Show HN: I compressed LLM context 7x with byte-exact reconstruction

**Post text:**

Hi HN! I built densely after a simple frustration: when my coding agent's
context fills up, compaction summarizes away the exact things I need later —
config values, stack traces, file contents. Existing tools (like Headroom)
drop content from context and keep originals in a local cache with a TTL;
if the cache is gone, so is your data.

densely takes the opposite approach: the exact data stays *in the context*,
just denser. An o200k token can carry ~17.6 bits, but typical code occupies
tokens at ~5-6 bits. So: lzma → 16-bit chunks → an alphabet of 65,536
English words that each encode to exactly 1 token. Every payload token
carries 2 bytes of compressed data, and sha256 is verified on every expand.

Numbers (reproducible, `python3 bench.py`):
- code: 2.02x (50%) with the default lzma backend
- JSON tool outputs: 7.75x (87%)
- logs: 6.94x (86%)
- code with the optional neural backend (Qwen2.5-Coder-0.5B + arithmetic
  coding): 7.27x (86%) on code the model has never seen — slow, but it's
  the densest lossless figure I know of for LLM context

Site: https://densely.dev

There's an MCP server (works in Claude Code and Cursor today) and an
automatic mode: a PostToolUse hook compresses every large tool output on
the fly and keeps a savings ledger — tokens saved today/this week, so
the effect on your usage cap is a number, not vibes. In manual mode: the
agent compresses a 100k-token log to ~15k, keeps the payload in
conversation (survives compaction), and expands exact line ranges on
demand.

Honest limits: the payload is unreadable by the model (it's a dense
carrier, not a summary — pair it with one); savings depend on redundancy
(random data ≈ 0%); the neural backend needs the same machine/stack to
decode, so it falls back to lzma unless the round trip verifies.

MIT licensed. Would love feedback on the approach and what integration
you'd want next.

**Checklist before posting:**
- [x] Repo public: github.com/alibaizhanov/densely
- [x] Landing live: https://densely.dev
- [x] Waitlist live: https://tally.so/r/Xx77V4 (Pro section in README): managed
      proxy, savings dashboard, cross-machine neural determinism, team cache
- [ ] GIF demo in README: agent compressing a log + expanding a line range
- [ ] Post Tue-Thu, 8-10am US Eastern; reply to every comment fast
