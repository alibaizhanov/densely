#!/usr/bin/env python3
"""Verify the carrier vocabulary against a target tokenizer.

The 16-bits-per-token claim is calibrated on o200k_base. A different
tokenizer may split some carrier words into 2+ tokens — reconstruction
stays byte-exact (decoding is character-level), but density silently
degrades. This tool measures the real cost.

Local tiktoken encodings (exact, full vocabulary):
    python3 tools/calibrate.py --encoding cl100k_base --encoding o200k_base

Anthropic models via the count_tokens API (sampled carrier text;
needs ANTHROPIC_API_KEY):
    python3 tools/calibrate.py --anthropic-model claude-sonnet-5
"""

import argparse
import math
import random

from densely import WORDS


def sample_carrier(n=4000, seed=7):
    rnd = random.Random(seed)
    return "".join(rnd.choice(WORDS) for _ in range(n)), n


def check_tiktoken(name):
    import tiktoken
    enc = tiktoken.get_encoding(name)
    single = sum(1 for w in WORDS if len(enc.encode(w)) == 1)
    carrier, n = sample_carrier()
    per_word = len(enc.encode(carrier)) / n
    print(f"{name}: {single}/{len(WORDS)} words single-token "
          f"({100 * single / len(WORDS):.1f}%), carrier cost {per_word:.3f} tok/word "
          f"-> effective {16 / per_word:.1f} bits/token")


def check_anthropic(model):
    import json
    import os
    import urllib.request
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("set ANTHROPIC_API_KEY to calibrate against Anthropic models")
    carrier, n = sample_carrier()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages/count_tokens",
        data=json.dumps({"model": model,
                         "messages": [{"role": "user", "content": carrier}]}).encode(),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    import ssl
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx) as resp:
        tokens = json.load(resp)["input_tokens"]
    overhead = 8  # rough per-request scaffolding tokens
    per_word = max(tokens - overhead, 1) / n
    print(f"{model}: {tokens} tokens for {n} carrier words "
          f"-> {per_word:.3f} tok/word -> effective {16 / per_word:.1f} bits/token")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--encoding", action="append", default=[],
                   help="tiktoken encoding name (repeatable)")
    p.add_argument("--anthropic-model", action="append", default=[],
                   help="Anthropic model id for count_tokens (repeatable)")
    args = p.parse_args()
    if not args.encoding and not args.anthropic_model:
        args.encoding = ["o200k_base", "cl100k_base"]
    for name in args.encoding:
        check_tiktoken(name)
    for model in args.anthropic_model:
        check_anthropic(model)
