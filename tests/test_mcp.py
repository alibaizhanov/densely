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
