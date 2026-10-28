#!/usr/bin/env python3
"""densely MCP server: lossless context compression tools for AI agents.

Register with Claude Code:
    claude mcp add --scope user densely -- "$(which densely-mcp)"

Cursor / other MCP clients (mcpServers config):
    {"densely": {"command": "/absolute/path/to/densely-mcp"}}

One shared server for all clients: run `densely-mcp --http` and point each
client at http://127.0.0.1:8765/mcp instead.

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

# search/expand re-read the same payload across agent turns; cache the
# decompressed text keyed by the header line (contains the sha).
_TEXT_CACHE: dict = {}
_TEXT_CACHE_MAX = 8


def _decompress_cached(payload: str) -> str:
    key = payload.split("\n", 1)[0]
    text = _TEXT_CACHE.get(key)
    if text is None:
        text = decompress(payload)
        if len(_TEXT_CACHE) >= _TEXT_CACHE_MAX:
            _TEXT_CACHE.pop(next(iter(_TEXT_CACHE)))
        _TEXT_CACHE[key] = text
    return text


def _preview(text: str, lines: int = 5) -> str:
    rows = text.split("\n")
    head = "\n".join(rows[:lines])
    return head if len(rows) <= lines else head + f"\n... ({len(rows)} lines total)"


ALPHABET = os.environ.get("DENSELY_ALPHABET", "claude1")


def _compressed(text: str, label: str, sidecar: str, source: str | None = None) -> str:
    payload = compress(text, alphabet=ALPHABET, source=source)
    o, c = ntok(text), ntok(payload)
    if c >= o:
        return (f"{label} is not compressible ({o} tokens); returning original:\n\n{text}")
    stats = (f"{label}: {o} -> {c} tokens ({100 * (1 - c / o):.0f}% saved), "
             f"{len(text.split(chr(10)))} lines, byte-exact recovery via expand.\n"
             f"Preview:\n{_preview(text)}\n\n")
    # sidecar is always written: context compaction may drop inline content,
    # but a file on disk (and its path, carried into any summary) survives
    open(sidecar, "w", encoding="utf-8").write(payload)
    if len(payload) <= INLINE_LIMIT_CHARS:
        return (stats +
                f"Backup copy: {sidecar} (compaction-safe; expand accepts payload_file).\n"
                "PAYLOAD (keep in conversation, pass to expand when exact content is needed):\n"
                + payload)
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
    return _compressed(text, path, sidecar=path + ".dense", source=path)


@mcp.tool()
def compress_text(text: str) -> str:
    """Compress a large piece of text (tool output, log excerpt, document)
    into a dense payload 2x-8x smaller in tokens. The payload is unreadable
    but restores the exact bytes via the expand tool."""
    state_dir = os.environ.get("DENSELY_STATE_DIR")
    if state_dir:
        os.makedirs(state_dir, exist_ok=True)
        sidecar = os.path.join(state_dir, "densely-payload.dense")
    else:
        sidecar = os.path.join(os.path.expanduser("~"), ".densely-payload.dense")
    return _compressed(text, "text", sidecar=sidecar)


@mcp.tool()
def stats() -> str:
    """Show cumulative tokens saved by densely on this machine (from the
    auto-compression hook ledger)."""
    import time
    from densely import ledger
    day = week = total = 0
    seen = False
    now = time.time()
    for rec in ledger.entries():
        seen = True
        saved = rec.get("saved", 0)
        total += saved
        if now - rec["ts"] < 86400:
            day += saved
        if now - rec["ts"] < 7 * 86400:
            week += saved
    if not seen:
        return "densely has not saved anything yet on this machine."
    # The figures above are gross: they ignore expands. Net is what was actually
    # avoided, and only exists for entries that recorded the preview shown.
    s = ledger.summary()
    net = (f"Net after expands: {s['net_saved']} tokens (since previews were recorded)."
           if s["net_tracked"] else "Net after expands: not tracked yet.")
    return (f"densely savings: {day} tokens today, {week} this week, "
            f"{total} all-time on this machine. {net}")


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
    text = _decompress_cached(payload)
    rows = text.split("\n")
    hits = [(i + 1, r) for i, r in enumerate(rows) if re.search(pattern, r)]
    if not hits:
        return f"0 of {len(rows)} lines match {pattern!r}"
    body = "\n".join(f"{n}:{r}" for n, r in hits[:200])
    more = f"\n... ({len(hits) - 200} more matches)" if len(hits) > 200 else ""
    return f"{len(hits)} of {len(rows)} lines match {pattern!r}:\n{body}{more}"


def _stale_banner(status) -> str:
    """Warn, but still hand over the content.

    Refusing would be safer against a misled agent and worse in the case this tool
    exists for: compress a log, the log rotates, and the payload is now the only
    surviving copy of what it said. Refusing there destroys data with no way back,
    whereas an ignored warning leaves us exactly where we are today. The two
    failure modes are not symmetric, so the content always comes through.
    """
    if not status or status["state"] == "ok":
        return ""
    if status["state"] == "gone":
        return (f"NOTE: source {status['path']} no longer exists. This payload may be "
                f"the only remaining copy of that content.\n\n")
    return (f"STALE: source {status['path']} changed after this was captured "
            f"(captured {_ts(status['captured_at'])}, file modified "
            f"{_ts(status.get('modified_at', 0))}). What follows is the content as it "
            f"was then, not as it is now. Re-read the source if you need current "
            f"state.\n\n")


def _ts(epoch: int) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")


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
    text = _decompress_cached(payload)
    returned = text
    if start_line or end_line:
        rows = text.split("\n")
        lo = max(1, start_line or 1)
        hi = min(len(rows), end_line or len(rows))
        returned = f"lines {lo}-{hi} of {len(rows)}:\n" + "\n".join(rows[lo - 1:hi])
    # Record that the payload alone was not enough. Compressions without expands
    # are savings; compressions with expands are savings that cost a round trip,
    # and the ledger cannot tell them apart unless this side is written down too.
    # "tokens" is the full original (it matches the compression's "orig");
    # "returned" is what this call put in context — a slice costs less.
    banner = ""
    try:
        from densely import ledger, ntok, source_status
        status = source_status(payload)
        ledger.add("expand", tokens=ntok(text), returned=ntok(returned),
                   sliced=bool(start_line or end_line), source=(status or {}).get("state"))
        banner = _stale_banner(status)
    except Exception:
        pass
    return banner + returned


def main():
    """densely-mcp [--http [PORT]]: stdio by default; --http serves one shared
    process on 127.0.0.1 (default port 8765) that several clients connect to."""
    import sys
    args = sys.argv[1:]
    if args[:1] == ["--http"]:
        mcp.settings.port = int(args[1]) if len(args) > 1 else 8765
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
