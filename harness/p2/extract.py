#!/usr/bin/env python3
"""Per-test extract of a detjs trace (P2 spec, "What is committed").

One JSON line per test: nodeid, outcome, fingerprint, worker, the event kinds with counts (`kinds`: event `o` ->
number of recorded events; `counts`: the trace's own per-category counts when present) and, with --events, the
test's recorded event list (fixed-epoch runs). The trace is streamed line by line (traces can exceed memory).

Usage: extract.py TRACE OUT.jsonl.gz [--events]
"""
from __future__ import annotations

import gzip
import json
import sys


def tests_of(trace, events=False):
    """Yield one extract dict per test line of TRACE, in trace order."""
    with open(trace, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.startswith('{"type":"test"'):
                continue
            try:
                t = json.loads(line)
            except ValueError:
                yield {"nodeid": None, "unreadable": line[:200]}
                continue
            kinds = {}
            for e in t.get("events") or []:
                k = e.get("o") if isinstance(e, dict) else None
                kinds[k] = kinds.get(k, 0) + 1
            row = {"nodeid": t.get("nodeid"), "outcome": t.get("outcome"), "fingerprint": t.get("fingerprint"),
                   "worker": t.get("worker"), "kinds": dict(sorted(kinds.items(), key=lambda kv: str(kv[0]))),
                   "counts": t.get("counts")}
            if events:
                row["events"] = t.get("events") or []
            yield row


def write(trace, out, events=False):
    n = 0
    with gzip.open(out, "wt", encoding="utf-8") as g:
        for row in tests_of(trace, events):
            g.write(json.dumps(row, sort_keys=True) + "\n")
            n += 1
    return n


def read(path):
    """nodeid -> extract row (the first occurrence wins; duplicates are counted under `_dups`)."""
    out, dups = {}, 0
    with gzip.open(path, "rt", encoding="utf-8") as g:
        for line in g:
            r = json.loads(line)
            if r.get("nodeid") in out:
                dups += 1
                continue
            out[r.get("nodeid")] = r
    if dups:
        out["_dups"] = dups
    return out


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    if len(a) != 2:
        sys.exit(__doc__)
    print(write(a[0], a[1], "--events" in sys.argv), "tests")
