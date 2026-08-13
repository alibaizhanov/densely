#!/usr/bin/env python3
"""Does the agent still get the right answer after the content is compressed?

Compression ratio measures how many tokens were avoided. It says nothing about
whether the task still succeeds, and those can come apart badly: a payload the agent
never expands is a payload whose contents might as well not exist.

Each scenario is built so that a *plausible wrong answer sits in the preview* while
the true value is buried where only expand() reaches. An agent that skips the expand
does not fail loudly — it answers confidently from the preview and is wrong. That is
the failure this benchmark is for, and no compression-ratio number can see it.

    DENSELY_STATE_DIR=/tmp/scratch python3 bench_recall.py generate --out /tmp/recall
    # run an agent per scenario, write its answer to <out>/answers/NN.txt
    python3 bench_recall.py score --dir /tmp/recall

Scored per scenario:
  correct     the exact buried value
  preview     the distractor — answered without expanding, the failure mode
  other       neither; usually a fabrication
  expanded    whether the agent actually decompressed (an extra tool call)
"""
import argparse
import json
import os
import random
import re
import sys

# Never let a benchmark run touch the real usage ledger: these are experiments, not
# use, and that file's numbers get quoted publicly.
os.environ.setdefault("DENSELY_STATE_DIR", "/tmp/densely-bench-state")

from densely import compress  # noqa: E402

RNG = random.Random(20260813)


def _noise(n, svc):
    out = []
    for i in range(n):
        out.append(f"2026-08-13T{9 + i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}Z "
                   f"INFO  {svc} handled /v1/{RNG.choice(['orders', 'users', 'items'])} "
                   f"status=200 latency={RNG.randint(8, 90)}ms")
    return out


def scenarios():
    """Each returns (name, text, question, correct, distractor).

    The distractor always lands in the first five lines, because that is exactly what
    the preview shows. The true value goes deep enough that only expand reaches it.
    """
    s = []

    # 1. Config value, one digit apart from a healthy earlier reading.
    body = ([
        "2026-08-13T09:00:00Z INFO  payment-svc startup complete",
        "2026-08-13T09:00:01Z INFO  payment-svc pool healthy PG_POOL_MAX=70 idle=64",
        "2026-08-13T09:00:02Z INFO  payment-svc listening on :8080",
        "2026-08-13T09:00:03Z INFO  payment-svc health check ok",
        "2026-08-13T09:00:04Z INFO  payment-svc ready",
    ] + _noise(1400, "payment-svc") + [
        "2026-08-13T11:40:00Z INFO  payment-svc deploy applied PG_POOL_MAX=7 (was 70) commit=a91f4c2",
        "2026-08-13T11:40:11Z ERROR payment-svc pool exhausted, 0 idle connections",
    ] + _noise(600, "payment-svc"))
    s.append(("pool_config", "\n".join(body),
              "What was PG_POOL_MAX set to by the deploy that preceded the pool "
              "exhaustion error? Answer with the number only.",
              "7", "70"))

    # 2. Request id, differing from a nearby one in the last two characters.
    body = ([
        "2026-08-13T09:00:00Z INFO  api gateway started",
        "2026-08-13T09:00:01Z INFO  api request accepted request_id=req-7f3a91c4e2 status=200",
        "2026-08-13T09:00:02Z INFO  api warm cache primed",
        "2026-08-13T09:00:03Z INFO  api ready",
        "2026-08-13T09:00:04Z INFO  api health ok",
    ] + _noise(1200, "api") + [
        "2026-08-13T12:15:44Z ERROR api unhandled exception request_id=req-7f3a91c4e9 "
        "status=500 route=/v1/checkout",
    ] + _noise(500, "api"))
    s.append(("request_id", "\n".join(body),
              "What is the request_id of the request that returned status 500? "
              "Answer with the id only.",
              "req-7f3a91c4e9", "req-7f3a91c4e2"))

    # 3. Version string; the rollback target differs from the version in the banner.
    body = ([
        "2026-08-13T09:00:00Z INFO  worker booting image=worker:4.2.1",
        "2026-08-13T09:00:01Z INFO  worker config loaded",
        "2026-08-13T09:00:02Z INFO  worker queue connected",
        "2026-08-13T09:00:03Z INFO  worker ready",
        "2026-08-13T09:00:04Z INFO  worker heartbeat ok",
    ] + _noise(1500, "worker") + [
        "2026-08-13T13:02:19Z WARN  worker crash loop detected, rolling back to image=worker:3.9.4",
    ] + _noise(400, "worker"))
    s.append(("rollback_version", "\n".join(body),
              "Which image version was the worker rolled back TO? Answer with the "
              "version string only.",
              "3.9.4", "4.2.1"))

    # 4. A threshold, where an earlier similar-looking number is the wrong answer.
    body = ([
        "2026-08-13T09:00:00Z INFO  ingest limits loaded max_batch=5000",
        "2026-08-13T09:00:01Z INFO  ingest workers=8",
        "2026-08-13T09:00:02Z INFO  ingest ready",
        "2026-08-13T09:00:03Z INFO  ingest heartbeat",
        "2026-08-13T09:00:04Z INFO  ingest heartbeat",
    ] + _noise(1300, "ingest") + [
        "2026-08-13T14:20:00Z ERROR ingest batch rejected: size 9000 exceeds max_batch=8500",
    ] + _noise(450, "ingest"))
    s.append(("threshold", "\n".join(body),
              "What was the max_batch value at the time the batch was rejected? "
              "Answer with the number only.",
              "8500", "5000"))

    # 5. Hostname, one character apart from the node in the banner.
    body = ([
        "2026-08-13T09:00:00Z INFO  scheduler leader elected node=kv-a1",
        "2026-08-13T09:00:01Z INFO  scheduler peers=3",
        "2026-08-13T09:00:02Z INFO  scheduler ready",
        "2026-08-13T09:00:03Z INFO  scheduler heartbeat",
        "2026-08-13T09:00:04Z INFO  scheduler heartbeat",
    ] + _noise(1100, "scheduler") + [
        "2026-08-13T15:44:02Z FATAL scheduler node=kv-a7 disk failure, evicting",
    ] + _noise(500, "scheduler"))
    s.append(("hostname", "\n".join(body),
              "Which node had the disk failure? Answer with the node name only.",
              "kv-a7", "kv-a1"))

    # 6. Nothing to find. An honest agent says so; a fabricating one invents an id.
    body = _noise(1800, "billing")
    s.append(("absent", "\n".join(body),
              "What is the request_id of the request that returned status 500? "
              "If no request returned 500, say exactly: NOT PRESENT.",
              "NOT PRESENT", None))
    return s


def generate(out):
    os.makedirs(os.path.join(out, "answers"), exist_ok=True)
    truth = {}
    for i, (name, text, question, correct, distractor) in enumerate(scenarios(), 1):
        tag = f"{i:02d}"
        payload = compress(text, alphabet=os.environ.get("DENSELY_ALPHABET", "claude1"))
        rows = text.split("\n")
        preview = "\n".join(rows[:5]) + f"\n... ({len(rows)} lines total)"
        with open(os.path.join(out, f"{tag}.dense"), "w") as fh:
            fh.write(payload)
        with open(os.path.join(out, f"{tag}_task.txt"), "w") as fh:
            fh.write(
                f"A large log was compressed to save context. Here is what you have.\n\n"
                f"{len(rows)} lines, byte-exact recovery available.\n"
                f"Preview:\n{preview}\n\n"
                f"Full contents: {os.path.join(out, tag + '.dense')}\n"
                f"To read them, run:\n"
                f"  DENSELY_STATE_DIR=/tmp/densely-bench-state python3 -c "
                f"\"from densely import decompress;"
                f"print(decompress(open('{os.path.join(out, tag + '.dense')}').read()))\"\n\n"
                f"QUESTION: {question}\n")
        truth[tag] = {"name": name, "correct": correct, "distractor": distractor,
                      "question": question, "lines": len(rows)}
    with open(os.path.join(out, "truth.json"), "w") as fh:
        json.dump(truth, fh, indent=2)
    print(f"{len(truth)} scenarios -> {out}")
    print(f"answers go in {os.path.join(out, 'answers')}/NN.txt")


def _classify(answer, correct, distractor):
    a = answer.strip().lower()
    if not a:
        return "empty"
    if re.search(rf"(?<![\w.-]){re.escape(correct.lower())}(?![\w.-])", a):
        return "correct"
    if distractor and re.search(rf"(?<![\w.-]){re.escape(distractor.lower())}(?![\w.-])", a):
        return "preview"
    return "other"


def score(d):
    truth = json.load(open(os.path.join(d, "truth.json")))
    rows, counts = [], {"correct": 0, "preview": 0, "other": 0, "empty": 0, "missing": 0}
    expanded = 0
    for tag, t in sorted(truth.items()):
        path = os.path.join(d, "answers", f"{tag}.txt")
        if not os.path.exists(path):
            counts["missing"] += 1
            rows.append((tag, t["name"], "missing", ""))
            continue
        raw = open(path).read()
        verdict = _classify(raw, t["correct"], t["distractor"])
        counts[verdict] += 1
        # A run that never decompressed cannot have seen the buried value; the
        # marker is written by the runner, not inferred from the answer.
        if "EXPANDED=yes" in raw:
            expanded += 1
        rows.append((tag, t["name"], verdict, raw.strip().splitlines()[0][:48] if raw.strip() else ""))

    n = len(truth)
    print(f"{'scenario':<20}{'verdict':<10}answer")
    for tag, name, verdict, first in rows:
        print(f"{tag} {name:<17}{verdict:<10}{first}")
    print(f"\ncorrect            {counts['correct']}/{n}")
    print(f"answered from preview  {counts['preview']}/{n}   <- compression cost the answer")
    print(f"other / fabricated {counts['other']}/{n}")
    if counts["missing"]:
        print(f"missing            {counts['missing']}/{n}")
    print(f"expanded           {expanded}/{n}   <- extra tool call the compression forced")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--out", default="/tmp/recall")
    s = sub.add_parser("score")
    s.add_argument("--dir", default="/tmp/recall")
    a = p.parse_args()
    if a.cmd == "generate":
        generate(a.out)
    else:
        score(a.dir)


if __name__ == "__main__":
    sys.exit(main())
