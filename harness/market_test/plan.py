#!/usr/bin/env python3
"""Reads harness/market_test/run.json and prints the job matrices for the workflow (GITHUB_OUTPUT).

run.json:
  {"run_id": "r1",
   "walk":  [{"spec": "home-assistant", "shards": 4, "budget_min": 320}, ...],
   "flaky": [{"spec": "vue-core", "reps": 10}, ...]}   ("rep_start": k resumes at repetition k)
"""

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def entry(spec_name, extra):
    spec_path = HERE / "specs" / f"{spec_name}.json"
    if not spec_path.exists():
        spec_path = HERE / "specs" / "generated" / f"{spec_name}.json"
    spec = json.loads(spec_path.read_text())
    e = {"name": spec["name"], "spec": str(spec_path.relative_to(HERE.parent.parent)), "lang": spec["lang"],
         "node": spec.get("node", ""), "apt": " ".join(spec.get("apt", [])),
         "services": " ".join(spec.get("services", []))}
    e.update(extra)
    return e


def main():
    run = json.loads((HERE / "run.json").read_text())
    walk, flaky = [], []
    for w in run.get("walk", []):
        n = w.get("shards", 1)
        for s in w.get("only", range(n)):  # market test: re-run selected shards only
            walk.append(entry(w["spec"], {"shard": f"{s}/{n}", "budget": str(w.get("budget_min", 320))}))
    for f in run.get("flaky", []):
        spec = json.loads((HERE / "specs" / f"{f['spec']}.json").read_text())
        sha = f.get("sha") or subprocess.run(["git", "ls-remote", spec["url"], "HEAD"], capture_output=True,
                                             text=True).stdout.split()[0]
        groups = f.get("groups", spec.get("ci_groups", 1))
        for rep in range(f.get("rep_start", 0), f.get("reps", 10)):
            for g in [x - 1 for x in f.get("only_groups", range(1, groups + 1))]:
                flaky.append(entry(f["spec"], {"rep": rep, "group": f"{g + 1}/{groups}", "sha": sha,
                                               "budget": str(f.get("budget_min", 200))}))
    finer = [{"name": f["repo"], "sha": f["sha"]} for f in run.get("finer", [])]
    agent = []
    for g in run.get("agent", []):
        e = entry(g["spec"], {"query": g["query"], "label": g["label"], "max_prs": str(g.get("max_prs", 8)),
                              "sample": str(g.get("sample", "")), "budget": str(g.get("budget_min", 330))})
        agent.append(e)
    recheck = []
    for k, r in enumerate(run.get("recheck", [])):
        recheck.append(entry(r["spec"], {"idx": str(k), "pr": str(r.get("pr", "")), "rec": r["rec"], "cur": r["cur"],
                                         "units": " ".join(r["units"])}))
    out = {"run_id": run["run_id"], "recheck": json.dumps(recheck or [{"name": "none"}]),
           "has_recheck": str(bool(recheck)).lower(), "finer": json.dumps(finer or [{"name": "none"}]),
           "agent": json.dumps(agent or [{"name": "none"}]), "has_agent": str(bool(agent)).lower(),
           "has_finer": str(bool(finer)).lower(), "walk": json.dumps(walk or [{"name": "none"}]),
           "flaky": json.dumps(flaky or [{"name": "none"}]), "has_walk": str(bool(walk)).lower(),
           "has_flaky": str(bool(flaky)).lower()}
    for k, v in out.items():
        print(f"{k}={v}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            for k, v in out.items():
                fh.write(f"{k}={v}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
