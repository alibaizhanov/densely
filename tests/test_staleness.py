"""A byte-exact payload can still be wrong.

The sha proves expand returns what compress was given. It says nothing about
whether the file still says that, and conflating the two is how an agent ends up
reasoning confidently about a state that no longer exists.
"""
import os
import time

from densely import compress, decompress, source_status
from densely.mcp_server import expand


def _log(tmp_path, name="app.log", body="request handled\n"):
    p = tmp_path / name
    p.write_text(body * 400)
    return str(p)


def test_no_source_means_nothing_to_check():
    assert source_status(compress("plain text " * 200)) is None


def test_unchanged_source_is_ok(tmp_path):
    f = _log(tmp_path)
    assert source_status(compress(open(f).read(), source=f))["state"] == "ok"


def test_changed_source_is_stale(tmp_path):
    f = _log(tmp_path)
    payload = compress(open(f).read(), source=f)
    time.sleep(1.1)                      # mtime has 1s granularity on some filesystems
    with open(f, "a") as fh:
        fh.write("appended after capture\n")
    assert source_status(payload)["state"] == "stale"


def test_touched_but_identical_is_not_stale(tmp_path):
    """A rebuild that rewrites a file byte-identically is not a content change,
    and crying wolf about it would train the agent to ignore the banner."""
    f = _log(tmp_path)
    body = open(f).read()
    payload = compress(body, source=f)
    time.sleep(1.1)
    with open(f, "w") as fh:             # same bytes, new mtime
        fh.write(body)
    assert source_status(payload)["state"] == "ok"


def test_missing_source_is_reported_not_stale(tmp_path):
    f = _log(tmp_path)
    payload = compress(open(f).read(), source=f)
    os.remove(f)
    assert source_status(payload)["state"] == "gone"


def test_stale_content_is_still_returned(tmp_path):
    """The whole point: warn, never withhold. A rotated log leaves the payload as
    the only surviving copy, and refusing to expand it would destroy data."""
    f = _log(tmp_path)
    original = open(f).read()
    payload = compress(original, source=f)
    time.sleep(1.1)
    with open(f, "w") as fh:
        fh.write("rotated, previous content gone\n")

    out = expand(payload=payload)
    assert out.startswith("STALE:")
    assert original in out               # content survives the warning


def test_path_with_spaces_survives_the_header(tmp_path):
    """The header is space-delimited; paths are not."""
    f = _log(tmp_path, name="my log file.log")
    payload = compress(open(f).read(), source=f)
    assert source_status(payload)["path"] == os.path.abspath(f)
    assert decompress(payload) == open(f).read()
