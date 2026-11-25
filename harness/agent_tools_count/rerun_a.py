#!/usr/bin/env python3
"""Change 2 (§1.9 more than 3 sample misses): re-run every Count A row through the changed rule, offline, by
replaying the committed raw responses (no request). The rows before the change are kept as
results/a_rows_rule1.jsonl; results/a_rows.jsonl is rewritten in the same order with the same bookkeeping fields.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import job as J  # noqa: E402
import pipeline as P  # noqa: E402

KEEP = ("item", "url", "repo", "number", "family", "c2_verdict", "chunk")
TAIL = ("requests", "seconds")


def main() -> None:
    res = HERE / "results"
    old_p, rows_p = res / "a_rows_rule1.jsonl", res / "a_rows.jsonl"
    if not old_p.exists():
        old_p.write_text(rows_p.read_text())
    rows = J.read_jsonl(old_p)
    raw = {r["item"]: r for r in J.raw_records("a")}
    fr = J.frame()
    out_rows = []
    for row in rows:
        out = P.count_a(P.ReplaySource(raw[row["item"]]["responses"]), fr[row["item"]])
        out_rows.append({k: row[k] for k in KEEP} | out | {k: row[k] for k in TAIL})
    rows_p.write_text("".join(json.dumps(r) + "\n" for r in out_rows))
    was = {r["url"] for r in rows if r["result"] == "wasted"}
    now = {r["url"] for r in out_rows if r["result"] == "wasted"}
    changed = sum(1 for a, b in zip(rows, out_rows) if a["result"] != b["result"])
    print(f"rows {len(out_rows)}; result changed {changed}; wasted before {len(was)} now {len(now)}; "
          f"newly wasted {len(now - was)}; no longer wasted {len(was - now)}")


if __name__ == "__main__":
    main()
