#!/usr/bin/env python3
"""Reproducible benchmark for ctxdense.

Scenarios mirror typical agent context: source code, tool-output JSON,
and service logs. JSON/log data is generated with a fixed seed; the code
sample is Python's own argparse.py plus this repo's sources, so anyone
can re-run and get comparable numbers.

Usage: python3 bench.py [extra files...]
"""

import argparse as argparse_module
import json
import random
import sys

from ctxdense import compress, decompress, ntok


def code_sample():
    parts = [open(argparse_module.__file__, encoding="utf-8").read(),
             open("ctxdense.py", encoding="utf-8").read()]
    return "\n".join(parts)


def json_sample():
    random.seed(42)
    files = ["src/handlers/auth.py", "src/models/user.py",
             "lib/utils/parse.ts", "core/engine/scan.rs"]
    results = []
    for i in range(100):
        results.append({
            "file_path": random.choice(files),
            "line_number": random.randint(10, 900),
            "match": f"def handle_request_{i}(self, request, context):",
            "score": round(random.random(), 6),
            "repository": "github.com/acme/monorepo",
            "branch": "main",
            "commit_sha": "%040x" % random.getrandbits(160),
            "context_before": ["    # validates incoming payload",
                               "    @traced(span='rpc')"],
            "context_after": ["        payload = request.json()",
                              "        return self.dispatch(payload)"],
        })
    return json.dumps({"total": 100, "results": results}, indent=2)


def log_sample():
    random.seed(42)
    lines = []
    for i in range(1500):
        lines.append(
            f"2026-08-07T12:{i % 60:02d}:{i % 60:02d}.{i % 1000:03d}Z level=INFO "
            f"service=payments-api pod=payments-api-7d9f8b{i % 10} "
            f"trace_id={'%032x' % random.getrandbits(128)} "
            f'msg="request completed" method=POST path=/v1/charge '
            f"status=200 duration_ms={random.randint(5, 900)}")
        if i % 37 == 0:
            lines.append(
                f"2026-08-07T12:{i % 60:02d}:{i % 60:02d}.000Z level=ERROR "
                f'service=payments-api msg="upstream timeout" '
                f'upstream=risk-engine attempt={i % 3 + 1} '
                f'err="context deadline exceeded"')
    return "\n".join(lines)


def run(label, text):
    payload = compress(text)
    assert decompress(payload) == text, f"round-trip failed for {label}"
    o, c = ntok(text), ntok(payload)
    print(f"{label:30} {o:>8} -> {c:>7} tokens  "
          f"{o / c:>5.2f}x  saved {100 * (1 - c / o):.1f}%")
    return o, c


if __name__ == "__main__":
    print(f"{'scenario':30} {'tokens (o200k)':>18}")
    total_o = total_p = 0
    scenarios = [("code (argparse.py + ctxdense)", code_sample()),
                 ("json (code search, 100 hits)", json_sample()),
                 ("log (SRE incident, ~1500 ln)", log_sample())]
    for path in sys.argv[1:]:
        scenarios.append((path, open(path, encoding="utf-8").read()))
    for label, text in scenarios:
        o, c = run(label, text)
        total_o += o
        total_p += c
    print(f"{'TOTAL':30} {total_o:>8} -> {total_p:>7} tokens  "
          f"{total_o / total_p:>5.2f}x  saved {100 * (1 - total_p / total_o):.1f}%")
