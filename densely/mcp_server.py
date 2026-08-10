#!/usr/bin/env python3
"""densely MCP server: lossless context compression tools for AI agents.

Register with Claude Code:
    claude mcp add --scope user densely -- "$(which densely-mcp)"

Cursor / other MCP clients (mcpServers config):
    {"densely": {"command": "/absolute/path/to/densely-mcp"}}

Workflow: call compress_file INSTEAD of reading a large file (or
compress_text on a large tool output). Keep the returned payload in the
conversation — it survives context compaction. Call expand when you need
the exact content back; use line ranges to pay only for the part you need.
"""

import os

from mcp.server.fastmcp import FastMCP

from densely import compress, decompress, ntok

mcp = FastMCP("densely")

# Larger payloads overflow MCP tool-output limits and get dumped to a
# client-side file, losing the in-conversation property — write our own
# .dense sidecar instead and return its path.
INLINE_LIMIT_CHARS = 30_000


def _preview(text: str, lines: int = 5) -> str:
    rows = text.split("\n")
    head = "\n".join(rows[:lines])
    return head if len(rows) <= lines else head + f"\n... ({len(rows)} lines total)"


def _compressed(text: str, label: str, sidecar: str) -> str:
    payload = compress(text)
    o, c = ntok(text), ntok(payload)
    if c >= o:
        return (f"{label} is not compressible ({o} tokens); returning original:\n\n{text}")
    stats = (f"{label}: {o} -> {c} tokens ({100 * (1 - c / o):.0f}% saved), "
             f"{len(text.split(chr(10)))} lines, byte-exact recovery via expand.\n"
             f"Preview:\n{_preview(text)}\n\n")
    if len(payload) <= INLINE_LIMIT_CHARS:
        return (stats +
                "PAYLOAD (keep in conversation, pass to expand when exact content is needed):\n"
                + payload)
    open(sidecar, "w", encoding="utf-8").write(payload)
    return (stats +
            f"Payload written to {sidecar} (too large to inline). "
            f"Call expand with payload_file=\"{sidecar}\" and a line range "
            f"to retrieve exact content without reading the original.")


@mcp.tool()
def compress_file(path: str) -> str:
    """Read a file and return it compressed 2x-8x as a dense payload plus a
    short preview. Use INSTEAD of reading large files (logs, JSON, data
    dumps) you don't need to fully read right now. The payload is
    unreadable but restores the exact bytes via the expand tool.
    Do NOT compress files you are actively editing or need to understand —
    read those normally; compress reference material and bulky data."""
    text = open(path, encoding="utf-8").read()
    return _compressed(text, path, sidecar=path + ".dense")


@mcp.tool()
def compress_text(text: str) -> str:
    """Compress a large piece of text (tool output, log excerpt, document)
    into a dense payload 2x-8x smaller in tokens. The payload is unreadable
    but restores the exact bytes via the expand tool."""
    sidecar = os.path.join(os.path.expanduser("~"), ".densely-payload.dense")
    return _compressed(text, "text", sidecar=sidecar)


@mcp.tool()
def stats() -> str:
    """Show cumulative tokens saved by densely on this machine (from the
    auto-compression hook ledger)."""
    import time
    from densely.hook import LEDGER
    import json as _json
    day = week = total = 0
    now = time.time()
    try:
        with open(LEDGER) as fh:
            for line in fh:
                rec = _json.loads(line)
                total += rec["saved"]
                if now - rec["ts"] < 86400:
                    day += rec["saved"]
                if now - rec["ts"] < 7 * 86400:
                    week += rec["saved"]
    except FileNotFoundError:
        return "densely has not saved anything yet on this machine."
    return (f"densely savings: {day} tokens today, {week} this week, "
            f"{total} all-time on this machine.")


@mcp.tool()
def search(pattern: str, payload: str = "", payload_file: str = "") -> str:
    """Search inside a densely payload WITHOUT expanding it into context:
    decompression happens server-side, only matching lines return. Use this
    to count/find/filter (errors, ids, keywords) — it costs tokens only for
    the matches, never for the whole content. Pattern is a Python regex."""
    import re
    if not payload and not payload_file:
        raise ValueError("pass payload or payload_file")
    if payload_file:
        payload = open(payload_file, encoding="utf-8").read()
    text = decompress(payload)
    rows = text.split("\n")
    hits = [(i + 1, r) for i, r in enumerate(rows) if re.search(pattern, r)]
    if not hits:
        return f"0 of {len(rows)} lines match {pattern!r}"
    body = "\n".join(f"{n}:{r}" for n, r in hits[:200])
    more = f"\n... ({len(hits) - 200} more matches)" if len(hits) > 200 else ""
    return f"{len(hits)} of {len(rows)} lines match {pattern!r}:\n{body}{more}"


@mcp.tool()
def expand(payload: str = "", payload_file: str = "",
           start_line: int = 0, end_line: int = 0) -> str:
    """Restore the exact original text from a densely payload
    (sha256-verified, byte-identical). Pass the payload string itself OR
    payload_file (path to a .dense file written by compress_file). Pass
    start_line/end_line (1-based, inclusive) to return only that slice and
    spend fewer tokens; omit both for the full text."""
    if not payload and not payload_file:
        raise ValueError("pass payload or payload_file")
    if payload_file:
        payload = open(payload_file, encoding="utf-8").read()
    text = decompress(payload)
    if start_line or end_line:
        rows = text.split("\n")
        lo = max(1, start_line or 1)
        hi = min(len(rows), end_line or len(rows))
        slice_ = "\n".join(rows[lo - 1:hi])
        return f"lines {lo}-{hi} of {len(rows)}:\n{slice_}"
    return text


def main():
    mcp.run()


if __name__ == "__main__":
    main()
