#!/usr/bin/env python3
"""AC3 agentsys wall time over every round (coordinator, 2026-11-24, D2 = A): per round the --det parallel wall time
of the trunk and the branch (`kind: par` rows of measure.py, run back to back by proof_run.sh), the per-round ratio
branch/trunk, the median of the ratios and the verdict (met only when the median ratio is <= 1.10).

    python3 harness/det_host_values/wall_rounds.py harness/det_host_values/data/agentsys-rounds
    (<dir>/r<N>/{trunk,branch}.results.jsonl, <dir>/r<N>/proof_run.log)
"""
import json
import os
import re
import statistics
import sys

BOUND = 1.10


def par(path):
    rows = [json.loads(x) for x in open(path) if x.strip()]
    return next(r for r in rows if r["kind"] == "par")


def main(d):
    rounds = sorted((int(m.group(1)), n) for n in os.listdir(d) if (m := re.fullmatch(r"r(\d+)", n)))
    print("| round | trunk commit | branch commit | trunk s | branch s | ratio | exit trunk / branch | tests |")
    print("|---|---|---|---|---|---|---|---|")
    ratios, ts, bs = [], [], []
    for i, n in rounds:
        t, b = par(os.path.join(d, n, "trunk.results.jsonl")), par(os.path.join(d, n, "branch.results.jsonl"))
        r = b["wall_s"] / t["wall_s"]
        ratios.append(r); ts.append(t["wall_s"]); bs.append(b["wall_s"])
        print(f"| {i} | {t['engine_commit'][:8]} | {b['engine_commit'][:8]} | {t['wall_s']} | {b['wall_s']} | {r:.3f} | "
              f"{t['exit']} / {b['exit']} | {t['tests']} / {b['tests']} |")
    med = statistics.median(ratios)
    print(f"\nrounds: {len(ratios)}; median per-round ratio: **{med:.3f}** (bound {BOUND}); "
          f"median wall s trunk {statistics.median(ts)}, branch {statistics.median(bs)}; "
          f"ratios min {min(ratios):.3f}, max {max(ratios):.3f}")
    print(f"\nAC3 agentsys wall time: **{'met' if med <= BOUND else 'NOT DONE'}**")


if __name__ == "__main__":
    main(sys.argv[1])
