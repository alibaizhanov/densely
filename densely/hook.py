#!/usr/bin/env python3
"""PostToolUse hook: auto-compress large tool outputs with densely.

Reads the hook JSON on stdin. If the tool output is large ballast (Bash,
PowerShell or Grep output, or Read of a non-code file, >= MIN_TOKENS),
replaces it with a short preview + a .dense sidecar path, and records
savings in the ledger. Exits 0 silently (passthrough) in every other case —
including any error: a hook must never break the agent.

Cursor hooks cannot replace a built-in tool's output, so for Cursor the same
command answers preToolUse on Shell instead: it rewrites the command to send
its output through densely-filter, which prints it as-is or compressed.

Register (absolute path, see README):
  Claude Code: PostToolUse matcher "Read|Bash|PowerShell|Grep" -> command: $(which densely-hook)
  Cursor:      preToolUse matcher "Shell" -> command: $(which densely-hook)
"""

import json
import os
import re
import sys
import time

MIN_TOKENS = int(os.environ.get("DENSELY_HOOK_MIN_TOKENS", "2000"))
# The output is replaced by a 10-line preview, so whenever the agent needs the
# whole text it pays preview + expand — more than the original. That is only
# worth risking for a big win: a 5% saving on a diff cost 2x in practice.
MIN_SAVING = float(os.environ.get("DENSELY_HOOK_MIN_SAVING", "0.4"))
# Diffs are read in full (reviews, commits), so a preview never carries the task.
DIFF_CMD = re.compile(r"\b(git\s+diff|gh\s+pr\s+diff)\b")
CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".c",
            ".cpp", ".h", ".hpp", ".rb", ".php", ".swift", ".kt", ".scala",
            ".sh", ".zsh", ".sql", ".dense"}
# Tools whose output has no source file to go stale against
OUTPUT_TOOLS = {"Bash", "PowerShell", "Grep"}
# Claude Code cuts shell output to this many chars before the hook sees it
# (no marker). A sidecar of the cut text would pass for the full output, so
# such output is left alone: Claude Code persists the full one to a file.
SHELL_TOOLS = {"Bash", "PowerShell"}
SHELL_MAX_OUTPUT = int(os.environ.get("BASH_MAX_OUTPUT_LENGTH") or 30000)
STATE_DIR = os.path.join(os.path.expanduser("~"), ".densely")
FILTER = os.path.join(os.path.dirname(sys.executable), "densely-filter")
# The wrapped command runs in the agent's own shell: an exit or exec in it would
# end that shell before densely-filter prints anything, losing the output.
SKIP_WRAP = re.compile(r"\b(exit|exec)\b")


def extract_text(resp):
    """Tolerant extraction of the text content from tool_response."""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        for key in ("output", "stdout", "content", "text"):
            v = resp.get(key)
            if isinstance(v, str) and v:
                return v
        f = resp.get("file")
        if isinstance(f, dict) and isinstance(f.get("content"), str):
            return f["content"]
    return None


def replace_text(resp, text):
    """Copy of tool_response with the field extract_text read swapped for text.

    Claude Code validates updatedToolOutput against the tool's own output
    schema and silently keeps the original output when it doesn't match.
    """
    if isinstance(resp, str):
        return text
    resp = dict(resp)
    for key in ("output", "stdout", "content", "text"):
        v = resp.get(key)
        if isinstance(v, str) and v:
            resp[key] = text
            return resp
    f = dict(resp["file"])
    f["content"] = text
    f["numLines"] = text.count("\n") + 1
    resp["file"] = f
    return resp


def ledger_add(orig, new, shown):
    from densely import ledger
    ledger.add("compress", saved=orig - new, orig=orig, payload=new, shown=shown)


def ledger_total():
    from densely import ledger
    return ledger.summary()["net_saved"]


def shrink(text, path=""):
    """Preview + .dense sidecar path replacing text, or None to keep text as-is."""
    from densely import compress, ntok
    orig_tokens = ntok(text)
    if orig_tokens < MIN_TOKENS:
        return None
    # Command/search output has no source file to go stale against; a Read does.
    payload = compress(text, alphabet=os.environ.get("DENSELY_ALPHABET", "claude1"),
                       source=path or None)
    payload_tokens = ntok(payload)
    if payload_tokens > orig_tokens * (1 - MIN_SAVING):
        return None

    outputs = os.path.join(os.environ.get("DENSELY_STATE_DIR") or STATE_DIR, "outputs")
    os.makedirs(outputs, exist_ok=True)
    import hashlib
    name = hashlib.sha256(text.encode()).hexdigest()[:16] + ".dense"
    sidecar = os.path.join(outputs, name)
    with open(sidecar, "w", encoding="utf-8") as fh:
        fh.write(payload)

    rows = text.split("\n")
    preview = "\n".join(rows[:10])
    replacement = (
        f"[densely] output auto-compressed: {orig_tokens} -> {payload_tokens} tokens "
        f"({100 * (1 - payload_tokens / orig_tokens):.0f}% saved; "
        f"net saved on this machine after expands: {ledger_total()}), {len(rows)} lines.\n"
        f"First 10 lines:\n{preview}\n\n"
        f"Exact full content is preserved. Use densely tools with "
        f"payload_file=\"{sidecar}\": search(pattern) to find/count lines, "
        f"expand(start_line, end_line) for exact slices. Do NOT Read the .dense "
        f"file: it is encoded, unreadable, and costs as much as the original."
    )
    ledger_add(orig_tokens, payload_tokens, ntok(replacement))
    return replacement


def cursor_pre_tool_use(data):
    if data.get("tool_name") != "Shell":
        return
    tool_input = data.get("tool_input") or {}
    cmd = tool_input.get("command") or ""
    if (not cmd.strip() or "densely-filter" in cmd or SKIP_WRAP.search(cmd)
            or DIFF_CMD.search(cmd)):
        return
    # Newlines around cmd keep a trailing "&" or "# comment" from eating the "}".
    wrapped = (f'__densely_out=$(mktemp); {{\n{cmd}\n}} >"$__densely_out" 2>&1; '
               f'__densely_rc=$?; "{FILTER}" "$__densely_out"; rm -f "$__densely_out"; '
               f'(exit $__densely_rc)')
    print(json.dumps({"updated_input": {**tool_input, "command": wrapped}}))


def main():
    data = json.load(sys.stdin)
    if data.get("hook_event_name") == "preToolUse":
        return cursor_pre_tool_use(data)
    if data.get("hook_event_name") != "PostToolUse":
        return
    tool = data.get("tool_name", "")
    path = ""
    if tool == "Read":
        path = (data.get("tool_input") or {}).get("file_path", "")
        if os.path.splitext(path)[1].lower() in CODE_EXT:
            return
    elif tool not in OUTPUT_TOOLS:
        return
    elif DIFF_CMD.search((data.get("tool_input") or {}).get("command") or ""):
        return

    resp = data.get("tool_response")
    text = extract_text(resp)
    if not text or "byte-exact recovery via expand" in text:
        return
    if tool in SHELL_TOOLS and len(text) >= SHELL_MAX_OUTPUT:
        return

    replacement = shrink(text, path)
    if replacement is None:
        return
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": replace_text(resp, replacement),
        }
    }))


def entry():
    try:
        main()
    except Exception:
        sys.exit(0)  # never break the agent


def filter_entry():
    """densely-filter FILE: print FILE as-is, or compressed when it is large."""
    with open(sys.argv[1], "rb") as fh:
        raw = fh.read()
    try:
        replacement = shrink(raw.decode("utf-8"))
    except Exception:
        replacement = None  # the command's output must always come through
    if replacement is None:
        sys.stdout.buffer.write(raw)
    else:
        sys.stdout.write(replacement + "\n")


if __name__ == "__main__":
    entry()
