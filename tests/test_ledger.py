"""The expand side of the ledger — the half that was missing.

Savings alone cannot distinguish "compression helped" from "compression forced a
round trip nobody wanted". These pin the accounting that tells them apart.
"""
import json
import os
import tempfile

from densely import compress, ledger
from densely.mcp_server import expand


def _isolate(tmp):
    os.environ["DENSELY_STATE_DIR"] = tmp


def test_expand_is_recorded_and_rated():
    with tempfile.TemporaryDirectory() as tmp:
        _isolate(tmp)
        text = "\n".join(f"line {i} of ordinary log output" for i in range(300))
        payload = compress(text)
        ledger.add("compress", saved=1000)
        assert ledger.summary()["expand"] == 0

        assert expand(payload=payload) == text
        s = ledger.summary()
        assert s["expand"] == 1
        assert s["expanded_tokens"] > 0
        assert s["expand_rate"] == 1.0        # one expand per one compression


def test_legacy_entries_count_as_compressions():
    """Entries written before the event field existed were all compressions.
    Dropping them would silently understate the history."""
    with tempfile.TemporaryDirectory() as tmp:
        _isolate(tmp)
        with open(os.path.join(tmp, "ledger.jsonl"), "w") as fh:
            fh.write(json.dumps({"ts": 1, "saved": 500}) + "\n")
        s = ledger.summary()
        assert s["compress"] == 1 and s["saved"] == 500


def test_net_saved_pays_for_expands():
    """The agent sees the preview, and an expand re-pays the original: a compression
    that had to be expanded in full is a loss, not the payload-based "saving"."""
    with tempfile.TemporaryDirectory() as tmp:
        _isolate(tmp)
        ledger.add("compress", saved=900, orig=1000, payload=100)   # legacy: unpriced
        ledger.add("compress", saved=259, orig=4710, payload=4451, shown=250)
        ledger.add("expand", tokens=4710)
        s = ledger.summary()
        assert s["saved"] == 900 + 259
        assert s["net_saved"] == 4710 - 250 - 4710


def test_net_saved_charges_only_the_slice():
    with tempfile.TemporaryDirectory() as tmp:
        _isolate(tmp)
        ledger.add("compress", saved=7000, orig=10000, payload=3000, shown=300)
        ledger.add("expand", tokens=10000, returned=400, sliced=True)
        assert ledger.summary()["net_saved"] == 10000 - 300 - 400


def test_ledger_never_breaks_the_caller():
    """Telemetry that can fail a task is worse than no telemetry."""
    with tempfile.TemporaryDirectory() as tmp:
        _isolate(tmp)
        os.environ["DENSELY_STATE_DIR"] = "/proc/nonexistent-and-unwritable"
        ledger.add("expand", tokens=1)        # must not raise


def test_no_content_reaches_the_ledger():
    """The ledger holds counts, never what the text said."""
    with tempfile.TemporaryDirectory() as tmp:
        _isolate(tmp)
        secret = "SUPERSECRET-TOKEN-a1b2c3 " * 200
        expand(payload=compress(secret))
        assert "SUPERSECRET" not in open(os.path.join(tmp, "ledger.jsonl")).read()
