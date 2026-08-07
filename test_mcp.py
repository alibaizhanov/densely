import pytest

from densely_mcp import compress_file, compress_text, expand


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
