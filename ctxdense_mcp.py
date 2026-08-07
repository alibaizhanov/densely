#!/usr/bin/env python3
"""ctxdense MCP server: lossless context compression tools for AI agents.

Register with Claude Code:
    claude mcp add ctxdense -- python3 /path/to/ctxdense/ctxdense_mcp.py

Cursor / other MCP clients (mcpServers config):
    {"ctxdense": {"command": "python3", "args": ["/path/to/ctxdense/ctxdense_mcp.py"]}}

Workflow: call compress_file INSTEAD of reading a large file (or
compress_text on a large tool output). Keep the returned payload in the
conversation — it survives context compaction. Call expand when you need
the exact content back; use line ranges to pay only for the part you need.
"""

from mcp.server.fastmcp import FastMCP

from ctxdense import compress, decompress, ntok

mcp = FastMCP("ctxdense")


def _preview(text: str, lines: int = 5) -> str:
    rows = text.split("\n")
    head = "\n".join(rows[:lines])
    return head if len(rows) <= lines else head + f"\n... ({len(rows)} lines total)"


def _compressed(text: str, label: str) -> str:
    payload = compress(text)
    o, c = ntok(text), ntok(payload)
    if c >= o:
        return (f"{label} is not compressible ({o} tokens); returning original:\n\n{text}")
    return (
        f"{label}: {o} -> {c} tokens ({100 * (1 - c / o):.0f}% saved), "
        f"{len(text.split(chr(10)))} lines, byte-exact recovery via expand.\n"
        f"Preview:\n{_preview(text)}\n\n"
        f"PAYLOAD (keep in conversation, pass to expand when exact content is needed):\n"
        f"{payload}"
    )


@mcp.tool()
def compress_file(path: str) -> str:
    """Read a file and return it compressed 2x-8x as a dense payload plus a
    short preview. Use INSTEAD of reading large files (logs, JSON, data
    dumps) you don't need to fully read right now. The payload is
    unreadable but restores the exact bytes via the expand tool."""
    text = open(path, encoding="utf-8").read()
    return _compressed(text, path)


@mcp.tool()
def compress_text(text: str) -> str:
    """Compress a large piece of text (tool output, log excerpt, document)
    into a dense payload 2x-8x smaller in tokens. The payload is unreadable
    but restores the exact bytes via the expand tool."""
    return _compressed(text, "text")


@mcp.tool()
def expand(payload: str, start_line: int = 0, end_line: int = 0) -> str:
    """Restore the exact original text from a ctxdense payload
    (sha256-verified, byte-identical). Pass start_line/end_line (1-based,
    inclusive) to return only that slice and spend fewer tokens; omit both
    for the full text."""
    text = decompress(payload)
    if start_line or end_line:
        rows = text.split("\n")
        lo = max(1, start_line or 1)
        hi = min(len(rows), end_line or len(rows))
        slice_ = "\n".join(rows[lo - 1:hi])
        return f"lines {lo}-{hi} of {len(rows)}:\n{slice_}"
    return text


if __name__ == "__main__":
    mcp.run()
