#!/usr/bin/env python3
"""Before/after table for the repositories re-measured after the Level 0 fixes.

    python harness/before_after.py --before harness/results/mixed --after harness/results/after-fixes

Writes <before>/before-after.json (rendered by the round's REPORT.md) and prints it.
Counts per repository (definitions in detpy_harness.csv_metrics):
broken by --det, tests missing under --det, unstable in the baseline (ids stable), reproduced.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import detpy_harness as H  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--run-url", default="")
    args = ap.parse_args()
    before, after = Path(args.before), Path(args.after)
    rows = []
    for summ in sorted(after.glob("*.summary.json")):
        name = json.loads(summ.read_text())["name"]
        b = H.csv_metrics(before, name)["counts"]
        a = H.csv_metrics(after, name)["counts"]
        rows.append({"repo": name,
                     **{f"{k}_before": b.get(k, 0) for k in ("broken", "missing_under_det", "unstable_strict",
                                                              "reproduced_strict")},
                     **{f"{k}_after": a.get(k, 0) for k in ("broken", "missing_under_det", "unstable_strict",
                                                             "reproduced_strict")}})
    totals = {k: sum(r[k] for r in rows) for k in rows[0] if k != "repo"} if rows else {}
    out = {"run": args.run_url, "rows": rows, "totals": totals}
    (before / "before-after.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(totals, indent=1))


if __name__ == "__main__":
    main()
