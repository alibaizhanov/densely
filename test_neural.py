"""Neural backend tests. Slow (~1-2 min): loads Qwen2.5-Coder-0.5B and
runs real LLM+arithmetic-coding round trips. Run explicitly:

    python3 -m pytest test_neural.py -q
"""

import neural
from densely import MAGIC_NEURAL, compress, decompress

SMALL_CODE = open("densely.py", encoding="utf-8").read()[:800]


def test_single_segment_roundtrip():
    payload = compress(SMALL_CODE, backend="neural")
    assert payload.startswith(MAGIC_NEURAL)
    assert decompress(payload) == SMALL_CODE


def test_multi_segment_roundtrip(monkeypatch):
    monkeypatch.setattr(neural, "SEG", 64)  # force batched multi-segment path
    data, n = neural.encode(SMALL_CODE)
    assert n > 64 * 2  # actually exercises >2 segments
    assert neural.decode(data, n) == SMALL_CODE


def test_beats_lzma_on_code():
    from densely import ntok
    dense = compress(SMALL_CODE, backend="neural")
    plain = compress(SMALL_CODE)
    assert dense.startswith(MAGIC_NEURAL)  # did not silently fall back
    assert ntok(dense) < ntok(plain)
