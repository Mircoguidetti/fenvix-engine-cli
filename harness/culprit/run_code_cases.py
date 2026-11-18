#!/usr/bin/env python3
"""Run the finder and the git-bisect baseline on code cases (planted regressions; kind a).

For each case: write the green key (``--det`` run of the red test at the green commit) and the red key (same at
the red head); these two runs are the finder's input, as a CI run would leave them, and are not counted as finder
executions. Then the finder, then ``git bisect run`` with plain pytest on the same range.

    run_code_cases.py --cases cases.jsonl --repo DIR --venv DIR --out results.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import checkout, git, git_bisect, run_det  # noqa: E402
from finder import Finder  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--venv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keys-dir", default=None)
    a = ap.parse_args()
    repo, venv = Path(a.repo).resolve(), Path(a.venv).resolve()
    done = set()
    if os.path.exists(a.out):
        done = {json.loads(l)["id"] for l in open(a.out)}
    kdir = Path(a.keys_dir or tempfile.mkdtemp(prefix="keys-")).resolve()
    kdir.mkdir(parents=True, exist_ok=True)
    for line in open(a.cases):
        c = json.loads(line)
        if c["id"] in done:
            continue
        nid = c["red_test"]
        gk, rk = str(kdir / f"{c['id']}-green.json"), str(kdir / f"{c['id']}-red.json")
        checkout(repo, c["green"])
        g = run_det(repo, venv, nid, keys=gk)
        checkout(repo, c["red_head"])
        r = run_det(repo, venv, nid, keys=rk)
        res = {"id": c["id"], "repo": c["repo"], "k": c["k"], "truth": c["planted"], "red_test": nid,
               "green_run": g["outcome"], "red_run": r["outcome"]}
        f = Finder(repo, nid, {"sha": c["green"], "env": {}, "venv": venv, "key": gk},
                   {"sha": c["red_head"], "env": {}, "venv": venv, "key": rk})
        try:
            fr = f.run()
        except Exception as e:  # recorded as a finder failure
            fr = {"culprit": None, "why": f"error: {type(e).__name__}: {e}", "executions": len(f.steps),
                  "steps": f.steps}
        named = (fr.get("culprit") or {}).get("commit")
        res["finder"] = {k: v for k, v in fr.items() if k not in ("nodeid",)}
        res["finder_correct"] = named == c["planted"]
        b = git_bisect(repo, venv, c["green"], c["red_head"], ["--tb=no", "-p", "no:randomly", nid])
        res["bisect"] = b
        res["bisect_correct"] = b["named"] is not None and c["planted"].startswith(b["named"][:12])
        checkout(repo, c["head"])
        with open(a.out, "a") as fh:
            fh.write(json.dumps(res) + "\n")
        fi = res["finder"]
        print(f"{c['id']}: finder {'OK' if res['finder_correct'] else 'WRONG'} exec={fi.get('executions')} "
              f"cands={fi.get('commit_candidates')}/{fi.get('commits_in_range')} wall={fi.get('wall')} | bisect "
              f"{'OK' if res['bisect_correct'] else 'WRONG'} exec={b['executions']} wall={b['wall']:.1f}", flush=True)


if __name__ == "__main__":
    main()
