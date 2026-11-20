"""The job matrix of .github/workflows/node-repro.yml: one job per (repository, shard) of the Node Block 1 flaky set.

    python harness/node_repro/shards.py [--run harness/node_repro/RUN] [--github-output FILE]

Shards per repository, from the Block 1 baseline time of one full run b (seconds) and the number of tests n: a shard
runs the search's 21 full-suite runs once (21 b), then about 6 b per test (minimisation and 10 replays of short
orders, ESTIMATED from harness/node_repro/results of the first 90 tests), within `budget_s` (default 4.5 h).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import flaky_set  # noqa: E402


def plan(run: dict) -> list:
    budget = float(run.get("budget_s", 16200))
    want = set(run.get("repos") or [])
    out = []
    for r in flaky_set.repos():
        if not r["unstable"] or r["runner"] not in ("vitest", "jest"):
            continue
        if want and r["name"] not in want:
            continue
        b = float(r["baseline_mean_s"] or 60)
        per_shard = max(1, int((budget - 21 * b) // (6 * b))) if budget > 24 * b else 1
        n = min(int(run.get("max_shards", 10)), math.ceil(r["unstable"] / per_shard))
        out += [{"repo": r["name"], "shard": k, "nshards": n} for k in range(n)]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=str(HERE / "RUN"))
    ap.add_argument("--github-output", default=None)
    args = ap.parse_args(argv)
    try:
        run = json.loads(Path(args.run).read_text())
    except (OSError, ValueError) as e:
        print("RUN:", e)
        run = {}
    m = plan(run)
    print(json.dumps(m, indent=1), f"\n{len(m)} jobs")
    if args.github_output:
        with open(args.github_output, "a") as f:
            f.write(f"matrix={json.dumps({'include': m})}\n")
            f.write(f"label={run.get('label', 'final')}\n")
            f.write(f"budget={int(float(run.get('budget_s', 16200)))}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
