import random
import string

import pytest

from ctxdense import ENC, WORDS, compress, decompress, ntok


CASES = {
    "empty": "",
    "single_char": "a",
    "ascii_code": "def handler(request):\n    return request.json()\n" * 40,
    "cjk": "微软雅黑控制台" * 100,
    "emoji_mixed": "status: ✅ done 🚀\n" * 50,
    "backslashes": "path\\to\\file \\n literal \\\\ stuff\n" * 20,
    "payload_lookalike": "DENSE1 pad=0 sha=deadbeefdeadbeef\n the of and\n" * 5,
}


@pytest.mark.parametrize("name", CASES)
def test_roundtrip_exact(name):
    text = CASES[name]
    assert decompress(compress(text)) == text


def test_roundtrip_random_printable():
    random.seed(7)
    text = "".join(random.choice(string.printable) for _ in range(5000))
    assert decompress(compress(text)) == text


def test_roundtrip_random_unicode():
    random.seed(7)
    text = "".join(chr(random.randint(1, 0x2FFF)) for _ in range(3000))
    assert decompress(compress(text)) == text


def test_tampered_payload_rejected():
    payload = compress("important exact data " * 100)
    header, _, body = payload.partition("\n")
    words = body.split(" ")
    words[5], words[6] = words[6], words[5]  # swap two carrier words
    with pytest.raises(ValueError):
        decompress(header + "\n" + " ".join(words))


def test_wrong_magic_rejected():
    with pytest.raises(ValueError):
        decompress("NOPE1 pad=0 sha=0000000000000000\n the of")


def test_alphabet_density():
    # every carrier word must cost exactly 1 token, alone and concatenated
    random.seed(1)
    seq = "".join(random.choice(WORDS) for _ in range(2000))
    assert len(ENC.encode(seq)) == 2000


def test_compresses_redundant_text():
    text = '{"file": "src/app.py", "line": 42, "match": "def main():"}\n' * 200
    payload = compress(text)
    assert ntok(payload) < ntok(text) / 4
