Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

Tradeoff: These guidelines bias toward caution over speed. For trivial tasks, use judgment.

1. Think Before Coding
Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

State your assumptions explicitly. If uncertain, ask.
If multiple interpretations exist, present them - don't pick silently.
If a simpler approach exists, say so. Push back when warranted.
If something is unclear, stop. Name what's confusing. Ask.

2. Simplicity First
Minimum code that solves the problem. Nothing speculative.

No features beyond what was asked.
No abstractions for single-use code.
No "flexibility" or "configurability" that wasn't requested.
No error handling for impossible scenarios.
If you write 200 lines and it could be 50, rewrite it.
Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

3. Surgical Changes
Touch only what you must. Clean up only your own mess.

When editing existing code:

Don't "improve" adjacent code, comments, or formatting.
Don't refactor things that aren't broken.
Match existing style, even if you'd do it differently.
If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

Remove imports/variables/functions that YOUR changes made unused.
Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

4. Goal-Driven Execution
Define success criteria. Loop until verified.

Transform tasks into verifiable goals:

"Add validation" → "Write tests for invalid inputs, then make them pass"
"Fix the bug" → "Write a test that reproduces it, then make it pass"
"Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

These guidelines are working if: fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## Project notes

**Never run densely by hand without redirecting the ledger.** Any manual
`expand()` or `compress_file()` appends to `~/.densely/ledger.jsonl`, which is the
file whose numbers get quoted publicly. Test runs and experiments are not usage:

    DENSELY_STATE_DIR=/tmp/scratch python3 -c "..."

The pytest suite already isolates itself via `tests/conftest.py`. Ad-hoc commands
do not, and this has silently polluted the real ledger twice.

**Byte-exact is not the same as correct.** The `sha` in a payload header proves
`expand` returns what `compress` was given. It says nothing about whether the source
still says that. `source_status()` answers the second question for payloads that
carry a `src` field.

**On staleness, warn — never withhold.** A rotated log leaves the payload as the
only surviving copy of what it said, so refusing to expand destroys data with no way
back, while an ignored warning leaves things exactly where they were. The two
failure modes are not symmetric.
