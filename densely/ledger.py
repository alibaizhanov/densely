"""Local usage ledger: what was compressed, and what had to be expanded again.

Recording savings alone answers "how many tokens did this avoid" and nothing else.
The question that actually matters — whether a compressed payload was *enough*, or
whether the agent had to go back for the original — needs the other half of the
story, so expands are recorded too.

The ratio of expands to compressions is the honest measure of whether compression is
helping or getting in the way. Near zero means the preview carried the task. High
means we are trading an extra tool call for savings nobody needed.

Nothing here leaves the machine. The ledger holds counts and timestamps, never
content: an entry says "1,412 tokens were expanded", never what they said.
"""
import json
import os
import time

STATE_DIR = os.path.join(os.path.expanduser("~"), ".densely")
LEDGER = os.path.join(STATE_DIR, "ledger.jsonl")


def _paths():
    """Resolve the ledger location at call time, honouring DENSELY_STATE_DIR.

    Resolved per call rather than at import so a test suite — or anyone running
    against a scratch directory — can redirect it without the real ledger picking
    up entries that never came from real use. The first version of this module
    read the path once at import, and running the tests silently appended six
    expands to the author's own ledger, which is exactly the number the ledger
    exists to report honestly.
    """
    root = os.environ.get("DENSELY_STATE_DIR") or STATE_DIR
    return root, os.path.join(root, "ledger.jsonl")


def add(event, **fields):
    """Append one entry. Failures are swallowed: telemetry must never break a task."""
    try:
        root, path = _paths()
        os.makedirs(root, exist_ok=True)
        with open(path, "a") as fh:
            fh.write(json.dumps({"ts": int(time.time()), "event": event, **fields}) + "\n")
    except OSError:
        pass


def entries():
    try:
        with open(_paths()[1]) as fh:
            for line in fh:
                if line.strip():
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue
    except FileNotFoundError:
        return


def summary():
    """Counts, savings, and the expand rate. Entries written before this module
    existed carry no "event" key; they were all compressions, so treat them as such
    rather than dropping them and understating history."""
    out = {"compress": 0, "expand": 0, "saved": 0, "expanded_tokens": 0}
    for e in entries():
        kind = e.get("event", "compress")
        if kind == "compress":
            out["compress"] += 1
            out["saved"] += e.get("saved", 0)
        elif kind == "expand":
            out["expand"] += 1
            out["expanded_tokens"] += e.get("tokens", 0)
    out["expand_rate"] = out["expand"] / out["compress"] if out["compress"] else None
    return out


def total_saved():
    return summary()["saved"]


def format_summary():
    s = summary()
    lines = [
        f"compressions   {s['compress']:>8}",
        f"tokens saved   {s['saved']:>8,}",
        f"expands        {s['expand']:>8}",
    ]
    if s["expand_rate"] is None:
        lines.append("expand rate         n/a  (nothing compressed yet)")
    else:
        lines.append(f"expand rate       {s['expand_rate']:>6.0%}  "
                     f"(how often the payload alone was not enough)")
    if not s["expand"] and s["compress"]:
        lines.append("")
        lines.append("No expands recorded. Either the previews carried every task, or")
        lines.append("nothing has needed the originals yet — a small sample cannot tell")
        lines.append("those apart, so read it as 'no evidence of harm', not 'no harm'.")
    return "\n".join(lines)
