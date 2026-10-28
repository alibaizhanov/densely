import pytest

from densely.mcp_server import compress_file, compress_text, expand


LOG = "\n".join(
    f'2026-08-08T10:00:{i % 60:02d}Z level=INFO service=api msg="request done" '
    f"status=200 duration_ms={i}" for i in range(300)
)


def _payload_of(result: str) -> str:
    marker = "PAYLOAD (keep in conversation, pass to expand when exact content is needed):\n"
    assert marker in result
    return result.split(marker, 1)[1]


def test_compress_expand_roundtrip():
    result = compress_text(LOG)
    assert "% saved" in result
    assert expand(_payload_of(result)) == LOG


def test_expand_line_range():
    payload = _payload_of(compress_text(LOG))
    out = expand(payload, start_line=10, end_line=12)
    assert out.startswith("lines 10-12 of 300:")
    assert out.count("\n") == 3  # header + 3 lines
    assert "10:00:09Z" in out  # line 10 is i=9


def test_incompressible_returns_original():
    result = compress_text("short")
    assert "not compressible" in result
    assert "short" in result


def test_compress_file(tmp_path):
    p = tmp_path / "big.log"
    p.write_text(LOG)
    result = compress_file(str(p))
    assert str(p) in result
    assert expand(_payload_of(result)) == LOG


def test_expand_rejects_garbage():
    with pytest.raises(ValueError):
        expand("not a payload at all")


def test_large_file_goes_to_sidecar(tmp_path):
    big = "\n".join(
        f'row {i} trace={i*2654435761 % 2**64:016x} status=200' for i in range(20000)
    )
    p = tmp_path / "huge.log"
    p.write_text(big)
    result = compress_file(str(p))
    sidecar = str(p) + ".dense"
    assert sidecar in result and "PAYLOAD" not in result
    assert expand(payload_file=sidecar) == big
    out = expand(payload_file=sidecar, start_line=2, end_line=2)
    assert out.endswith("row 1 trace=000000009e3779b1 status=200")


def test_expand_requires_input():
    with pytest.raises(ValueError):
        expand()


def test_search_in_payload(tmp_path):
    p = tmp_path / "app.log"
    p.write_text(LOG.replace("request done", "request FAILED", 3))
    result = compress_file(str(p))
    from densely.mcp_server import search
    payload = _payload_of(result)
    out = search("FAILED", payload=payload)
    assert out.startswith("3 of 300 lines match")
    assert out.count("\n") == 3


def test_search_no_match():
    from densely.mcp_server import search
    payload = _payload_of(compress_text(LOG))
    assert search("nonexistent_xyz", payload=payload).startswith("0 of 300")


def test_search_uses_decompress_cache():
    from densely import mcp_server
    mcp_server._TEXT_CACHE.clear()
    payload = _payload_of(compress_text(LOG))
    from densely.mcp_server import search
    first = search("status=200", payload=payload)
    assert len(mcp_server._TEXT_CACHE) == 1
    assert search("status=200", payload=payload) == first
    assert len(mcp_server._TEXT_CACHE) == 1


def test_small_file_also_writes_sidecar(tmp_path):
    p = tmp_path / "small.log"
    p.write_text(LOG)
    result = compress_file(str(p))
    sidecar = str(p) + ".dense"
    assert "PAYLOAD" in result and sidecar in result  # inline AND backup
    assert expand(payload_file=sidecar) == LOG


def test_compress_text_sidecar_honours_state_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DENSELY_STATE_DIR", str(tmp_path))
    result = compress_text(LOG)
    sidecar = str(tmp_path / "densely-payload.dense")
    assert sidecar in result
    assert expand(payload_file=sidecar) == LOG


def test_stats_counts_compress_ignores_expand(monkeypatch, tmp_path):
    import json
    import time
    from densely.mcp_server import stats
    monkeypatch.setenv("DENSELY_STATE_DIR", str(tmp_path))
    now = int(time.time())
    rows = [{"ts": now, "saved": 100},
            {"ts": now, "event": "compress", "saved": 50, "orig": 80, "payload": 30},
            {"ts": now, "event": "expand", "tokens": 80, "sliced": False, "source": None}]
    (tmp_path / "ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert stats() == ("densely savings: 150 tokens today, 150 this week, "
                       "150 all-time on this machine. Net after expands: not tracked yet.")


def test_stats_reports_net_after_expands(monkeypatch, tmp_path):
    """Gross savings ignore expands; net subtracts what was pulled back."""
    import json
    import time
    from densely.mcp_server import stats
    monkeypatch.setenv("DENSELY_STATE_DIR", str(tmp_path))
    now = int(time.time())
    rows = [{"ts": now, "event": "compress", "saved": 259, "orig": 4710, "payload": 4451, "shown": 250},
            {"ts": now, "event": "expand", "tokens": 4710, "returned": 4710, "sliced": False}]
    (tmp_path / "ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert stats().endswith("Net after expands: -250 tokens (since previews were recorded).")


def test_sliced_expand_records_returned_size(monkeypatch, tmp_path):
    """A slice costs only itself; charging the full original overstates the loss."""
    import json
    from densely import compress
    from densely.mcp_server import expand
    monkeypatch.setenv("DENSELY_STATE_DIR", str(tmp_path))
    expand(payload=compress(LOG), start_line=1, end_line=5)
    rec = json.loads((tmp_path / "ledger.jsonl").read_text().splitlines()[-1])
    assert rec["sliced"] and 0 < rec["returned"] < rec["tokens"]


def test_stats_empty_ledger(monkeypatch, tmp_path):
    from densely.mcp_server import stats
    monkeypatch.setenv("DENSELY_STATE_DIR", str(tmp_path))
    assert stats() == "densely has not saved anything yet on this machine."


@pytest.mark.parametrize("argv, transport, port", [
    (["densely-mcp"], "stdio", None),
    (["densely-mcp", "--http"], "streamable-http", 8765),
    (["densely-mcp", "--http", "9001"], "streamable-http", 9001),
])
def test_main_transport(argv, transport, port, monkeypatch):
    from densely import mcp_server
    calls = []
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mcp_server.mcp.settings, "port", 8000)
    monkeypatch.setattr(mcp_server.mcp, "run", lambda transport="stdio": calls.append(transport))
    mcp_server.main()
    assert calls == [transport]
    if port:
        assert mcp_server.mcp.settings.port == port
        assert mcp_server.mcp.settings.host == "127.0.0.1"


def test_registered_tools():
    """expand is what every compression result tells the agent to call next."""
    import asyncio
    from densely.mcp_server import mcp
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert names == {"compress_file", "compress_text", "stats", "search", "expand"}
