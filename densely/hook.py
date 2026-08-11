#!/usr/bin/env python3
"""PostToolUse hook: auto-compress large tool outputs with densely.

Reads the hook JSON on stdin. If the tool output is large ballast (Bash
output or Read of a non-code file, >= MIN_TOKENS), replaces it with a
short preview + a .dense sidecar path, and records savings in the ledger.
Exits 0 silently (passthrough) in every other case — including any error:
a hook must never break the agent.

Register (absolute path, see README):
  PostToolUse matcher "Read|Bash" -> command: $(which densely-hook)
"""

import json
import os
import sys
import time

MIN_TOKENS = int(os.environ.get("DENSELY_HOOK_MIN_TOKENS", "5000"))
CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".c",
            ".cpp", ".h", ".hpp", ".rb", ".php", ".swift", ".kt", ".scala",
            ".sh", ".zsh", ".sql", ".dense"}
STATE_DIR = os.path.join(os.path.expanduser("~"), ".densely")
LEDGER = os.path.join(STATE_DIR, "ledger.jsonl")


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


def ledger_add(orig, new):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(LEDGER, "a") as fh:
        fh.write(json.dumps({"ts": int(time.time()), "saved": orig - new}) + "\n")


def ledger_total():
    try:
        with open(LEDGER) as fh:
            return sum(json.loads(line)["saved"] for line in fh if line.strip())
    except FileNotFoundError:
        return 0


def main():
    data = json.load(sys.stdin)
    if data.get("hook_event_name") != "PostToolUse":
        return
    tool = data.get("tool_name", "")
    if tool == "Read":
        path = (data.get("tool_input") or {}).get("file_path", "")
        if os.path.splitext(path)[1].lower() in CODE_EXT:
            return
    elif tool != "Bash":
        return

    text = extract_text(data.get("tool_response"))
    if not text or "byte-exact recovery via expand" in text:
        return

    from densely import compress, ntok
    orig_tokens = ntok(text)
    if orig_tokens < MIN_TOKENS:
        return
    payload = compress(text, alphabet=os.environ.get("DENSELY_ALPHABET", "claude1"))
    payload_tokens = ntok(payload)
    if payload_tokens >= orig_tokens:
        return

    os.makedirs(os.path.join(STATE_DIR, "outputs"), exist_ok=True)
    import hashlib
    name = hashlib.sha256(text.encode()).hexdigest()[:16] + ".dense"
    sidecar = os.path.join(STATE_DIR, "outputs", name)
    with open(sidecar, "w", encoding="utf-8") as fh:
        fh.write(payload)

    rows = text.split("\n")
    preview = "\n".join(rows[:10])
    ledger_add(orig_tokens, payload_tokens)
    replacement = (
        f"[densely] output auto-compressed: {orig_tokens} -> {payload_tokens} tokens "
        f"({100 * (1 - payload_tokens / orig_tokens):.0f}% saved; "
        f"total saved on this machine: {ledger_total()}), {len(rows)} lines.\n"
        f"First 10 lines:\n{preview}\n\n"
        f"Exact full content is preserved. Use densely tools with "
        f"payload_file=\"{sidecar}\": search(pattern) to find/count lines, "
        f"expand(start_line, end_line) for exact slices."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": {"type": "text", "content": replacement},
        }
    }))


def entry():
    try:
        main()
    except Exception:
        sys.exit(0)  # never break the agent


if __name__ == "__main__":
    entry()
