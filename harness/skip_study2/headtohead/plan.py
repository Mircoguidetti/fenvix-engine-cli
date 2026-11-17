#!/usr/bin/env python3
"""Job matrix for the head-to-head walks, from harness/skip_study2/headtohead/run.json (GITHUB_OUTPUT).

run.json: {"run_id": "h1", "jobs": [{"spec": "home-assistant", "shards": 8, "only_shards": [0, 1],
                                      "arms": ["main"], "max_commits": 0, "budget_min": 300}, ...]}
Each job runs its arms one after the other ("main" = the full commit window in one environment; "env" / "runtime" =
the environment-change measurement on the first ``arm_commits`` commits).
"""

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main():
    run = json.loads((HERE / "run.json").read_text())
    jobs = []
    for j in run["jobs"]:
        sp = HERE / "specs" / f"{j['spec']}.json"
        spec = json.loads(sp.read_text())
        n = j.get("shards", 1)
        for s in j.get("only_shards", range(n)):
            arms = j.get("arms", ["main"])
            jobs.append({"name": spec["name"], "spec": str(sp.relative_to(ROOT)), "lang": spec["lang"],
                         "node": spec.get("node", ""), "apt": " ".join(spec.get("apt", [])),
                         "services": " ".join(spec.get("services", [])), "shard": f"{s}/{n}",
                         "arms": " ".join(arms), "tag": f"{'-'.join(arms)}-{s}o{n}",
                         "budget": str(j.get("budget_min", 300)), "arm_budget": str(j.get("arm_budget_min", 60)),
                         "arm_commits": str(j.get("arm_commits", 11))})
    out = {"run_id": run["run_id"], "h2h": json.dumps(jobs or [{"name": "none"}]), "has_h2h": str(bool(jobs)).lower()}
    for k, v in out.items():
        print(f"{k}={v}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            for k, v in out.items():
                fh.write(f"{k}={v}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
