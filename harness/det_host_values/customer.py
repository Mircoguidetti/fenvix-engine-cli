#!/usr/bin/env python3
"""Step 3, flips on the customer path: `runner/fenvix-run node --project <repo> --runner vitest --cache <fresh>
--out <dir> --detjs "node <engine>/node/bin/detjs.js"`, one cold run per engine. Count: tests that passed in both
plain runs of `pins.py find` (the branch's find directory: the plain runs do not involve the engine) and failed in
fenvix-run's outcomes; of these, the ones fenvix-run then classed flaky (passed alone) are reported apart.

    python3 harness/det_host_values/customer.py <find dir> <customer dir>   (<customer dir>/<engine>/<repo>/summary.json)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "det_pins"))
sys.path.insert(0, os.path.join(HERE, "..", "parallel_measure"))
from measure import runner_outcomes  # noqa: E402
import pins  # noqa: E402

REPOS = ["ironcurtain", "codex-multi-auth"]


def plain_passed(find_dir, repo):
    cwd = os.path.expandvars(pins.load_spec(repo)["dir"])
    sets = []
    for i in (1, 2):
        oc = runner_outcomes(os.path.join(find_dir, repo, f"plain{i}.runner.json"), cwd)
        sets.append({k for k, v in oc.items() if v == "passed"})
    return sets[0] & sets[1]


def main(find_dir, cdir):
    print("| repository | engine | fenvix-run exit | tests | failed in the suite (of plain-passed) | of which flaky (passed alone) | still failed | wall s |")
    print("|---|---|---|---|---|---|---|---|")
    detail = []
    for repo in REPOS:
        pp = plain_passed(find_dir, repo)
        for eng in ("trunk", "branch"):
            sp = os.path.join(cdir, eng, repo, "summary.json")
            if not os.path.exists(sp):
                print(f"| {repo} | {eng} | (not measured) | | | | | |")
                continue
            s = json.load(open(sp))
            meta = json.load(open(os.path.join(cdir, eng, repo, "run.json")))
            oc = s.get("outcomes", {})
            failed = sorted(k for k, v in oc.items() if v in ("failed", "error") and k in pp)
            flaky = {f["nodeid"] for f in s.get("flaky", [])}
            fl = [k for k in failed if k in flaky]
            print(f"| {repo} | {eng} ({meta['engine_commit'][:8]}) | {meta['exit']} | {len(oc)} | {len(failed)} | {len(fl)} | "
                  f"{len(failed) - len(fl)} | {meta['wall_s']} |")
            detail.append(f"\n{repo} / {eng}: failed in the suite though plain-passed ({len(failed)}); flaky marked *")
            detail += [f"- `{k}`{' *' if k in flaky else ''}" for k in failed]
    print("\n".join(detail))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
