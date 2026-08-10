#!/usr/bin/env python3
"""Empirically harvest a carrier alphabet for a closed tokenizer.

We can't scan Anthropic's vocabulary, but count_tokens tells us the cost
of any text. Strategy: batch candidate words into carrier strings; keep a
batch only when its measured cost equals exactly one token per word (after
subtracting per-request overhead) — which simultaneously proves every word
in it is single-token AND that adjacent words don't merge. Mixed batches
are discarded wholesale; candidates are plentiful.

Usage:
    ANTHROPIC_API_KEY=... python3 tools/build_alphabet.py \
        --model claude-sonnet-5 --target 16384 --out densely/alphabets/claude1.txt
"""

import argparse
import json
import os
import ssl
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from densely import WORDS  # noqa: E402

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    CTX = ssl.create_default_context()

KEY = os.environ.get("ANTHROPIC_API_KEY") or sys.exit("need ANTHROPIC_API_KEY")


def count(model, text):
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages/count_tokens",
        data=json.dumps({"model": model,
                         "messages": [{"role": "user", "content": text}]}).encode(),
        headers={"x-api-key": KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, context=CTX, timeout=30) as resp:
                return json.load(resp)["input_tokens"]
        except urllib.error.HTTPError as e:
            if e.code in (429, 529):
                time.sleep(min(1.5 ** attempt, 10))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1)
            continue
    raise RuntimeError("rate limited repeatedly")


def candidates():
    """Frequency-ordered pool: lower BPE rank = merged earlier = more common.
    Common English words are the ones most likely to be single-token in any
    tokenizer, so they go first."""
    import re
    import tiktoken
    enc = tiktoken.get_encoding("o200k_base")
    ranked = []
    for b, rank in enc._mergeable_ranks.items():
        try:
            w = b.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if re.fullmatch(r" [A-Za-z]+", w):
            ranked.append((rank, w))
    ranked.sort()
    return [w for _, w in ranked]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--target", type=int, default=16384)
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--out", required=True)
    p.add_argument("--pool-file", help="candidate words file (one per line, no leading space)")
    p.add_argument("--skip-file", help="words already tested (one per line), excluded from pool")
    args = p.parse_args()

    # per-request overhead, calibrated on a chain of known single-token words:
    # "the the ... the" costs exactly 1/word in any sane BPE (verified by probe)
    chain = "the" + " the" * 49
    overhead = count(args.model, chain) - 50
    sanity = count(args.model, "the") - overhead
    print(f"request overhead: {overhead} tokens (sanity 'the' -> {sanity} token)")
    if sanity != 1:
        raise SystemExit("overhead calibration failed; aborting")

    import threading
    from concurrent.futures import ThreadPoolExecutor

    kept, lock = [], threading.Lock()
    stats = {"req": 0}

    def measure(batch):
        with lock:
            stats["req"] += 1
            if stats["req"] % 200 == 0:
                print(f"  {stats['req']} req, kept {len(kept)}", flush=True)
        text = batch[0][1:] + "".join(batch[1:])  # no leading space at start
        return count(args.model, text) - overhead

    ckpt_path = args.out + ".partial"
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    ckpt = open(ckpt_path, "a")

    def harvest(batch):
        """Return words that are single-token AND don't merge with neighbors."""
        if not batch:
            return []
        t = measure(batch)
        if t == len(batch):
            with lock:
                for w in batch:
                    ckpt.write(w[1:] + "\n")
                ckpt.flush()
            return batch
        if len(batch) == 1:
            return []
        mid = len(batch) // 2
        return harvest(batch[:mid]) + harvest(batch[mid:])

    if args.pool_file:
        pool = [" " + w.strip() for w in open(args.pool_file) if w.strip()]
    else:
        pool = candidates()
    if args.skip_file:
        skip = set(" " + w.strip() for w in open(args.skip_file) if w.strip())
        pool = [w for w in pool if w not in skip]
    print(f"candidate pool: {len(pool)} words")
    batches = [pool[i:i + args.batch] for i in range(0, len(pool), args.batch)]
    with ThreadPoolExecutor(max_workers=4) as ex:
        for n, good in enumerate(ex.map(harvest, batches)):
            kept.extend(good)
            if n % 40 == 0:
                print(f"  {stats['req']} req, batch {n}/{len(batches)}, kept {len(kept)}", flush=True)
            if len(kept) >= args.target:
                ex.shutdown(wait=False, cancel_futures=True)
                break
    requests = stats["req"]

    if len(kept) < args.target:
        print(f"WARNING: only {len(kept)} words harvested (target {args.target})")
    result = kept[:args.target]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        fh.write("\n".join(w[1:] for w in result) + "\n")  # store without leading space
    print(f"wrote {len(result)} words -> {args.out} ({requests} requests)")


if __name__ == "__main__":
    main()
