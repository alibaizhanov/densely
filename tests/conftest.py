"""Point the ledger at a scratch directory for the whole suite.

Without this, any test that calls expand() appends to the developer's own
~/.densely/ledger.jsonl — which is the file whose numbers get reported publicly.
Test runs are not usage and must not show up there.
"""
import os
import tempfile

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolated_ledger():
    with tempfile.TemporaryDirectory() as tmp:
        old = os.environ.get("DENSELY_STATE_DIR")
        os.environ["DENSELY_STATE_DIR"] = tmp
        yield
        if old is None:
            os.environ.pop("DENSELY_STATE_DIR", None)
        else:
            os.environ["DENSELY_STATE_DIR"] = old
