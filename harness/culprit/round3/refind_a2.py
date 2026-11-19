#!/usr/bin/env python3
"""Fix round 3 (review R-019b): re-run the fixed finder on the committed kind-a2 cases.

For each committed case (``results/cases/a-NAME.jsonl``) the replayed history is rebuilt exactly as ``placed.py``
built it (same commits, same mutation, dates copied: the commit ids must equal the recorded ``range``, else the
case is recorded as not rebuilt). The green and red keys are written again (``--det`` at the green commit and at the
red head, round-2 checkout with fresh stamps), then the finder runs. The truth (plain walk) and the git bisect
baseline of the committed row are kept: neither depends on the finder. A case whose green or red key run no longer
gives pass / fail (today's environment) is kept with those outcomes and left out by ``aggregate2.py`` as before.

    refind_a2.py --name NAME --repo DIR --venv DIR --results-dir harness/culprit/results --out rows.jsonl --keys-dir DIR
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "round2"))
from common import checkout, git, run_det  # noqa: E402
from finder import Finder  # noqa: E402
from placed import rebuild  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--venv", required=True)
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keys-dir", required=True)
    a = ap.parse_args()
    repo, venv = Path(a.repo).resolve(), Path(a.venv).resolve()
    rd = Path(a.results_dir)
    cases = {c["id"]: c for c in map(json.loads, open(rd / "cases" / f"a-{a.name}.jsonl"))}
    old = [json.loads(l) for l in open(rd / f"a-{a.name}.jsonl") if l.strip()]
    done = {json.loads(l)["id"] for l in open(a.out)} if os.path.exists(a.out) else set()
    kdir = Path(a.keys_dir)
    kdir.mkdir(parents=True, exist_ok=True)
    for r in old:
        if r["id"] in done:
            continue
        c = cases[r["id"]]
        shape = c["shape"]
        pos = c["positions"]
        k = c["k"]
        fp = git(repo, "rev-list", "--first-parent", "--reverse", c["head"]).split()
        i = fp.index(c["green"])
        later = fp[i + 1: i + 1 + k]
        if shape == "placed":
            mutated = set(range(pos["p"], k + 1))
        else:
            mutated = set(range(pos["p1"], pos["p2"])) | set(range(pos["p3"], k + 1))
        shas = rebuild(repo, c["green"], later, mutated, c["file"], c["old"], c["new"], f"refs/culprit3/{c['id']}")
        row = dict(r)
        row["finder_round2"] = {x: (r.get("finder") or {}).get(x) for x in ("culprit", "status", "why", "executions")}
        row["finder_correct_round2"] = r.get("finder_correct")
        row["round"] = 3
        if shas != c["range"]:
            row["finder"] = {"culprit": None, "status": "not rebuilt", "why": "history not rebuilt exactly",
                             "executions": 0, "steps": []}
            row["rebuilt"] = False
            row["finder_correct"] = False
        else:
            row["rebuilt"] = True
            nid = r["red_test"]
            gk, rk = str(kdir / f"{r['id']}-green.json"), str(kdir / f"{r['id']}-red.json")
            checkout(repo, c["green"])
            g = run_det(repo, venv, nid, keys=gk)
            checkout(repo, c["red_head"])
            rr = run_det(repo, venv, nid, keys=rk)
            row["green_run_round2"], row["red_run_round2"] = r.get("green_run"), r.get("red_run")
            row["green_run"], row["red_run"] = g["outcome"], rr["outcome"]
            f = Finder(repo, nid, {"sha": c["green"], "env": {}, "venv": venv, "key": gk},
                       {"sha": c["red_head"], "env": {}, "venv": venv, "key": rk})
            try:
                fr = f.run()
            except Exception as e:  # recorded as a finder failure
                fr = {"culprit": None, "status": "error", "why": f"error: {type(e).__name__}: {e}",
                      "executions": len(f.steps), "steps": f.steps}
            row["finder"] = {x: v for x, v in fr.items() if x != "nodeid"}
            row["finder_correct"] = (fr.get("culprit") or {}).get("commit") == r["truth"]
        with open(a.out, "a") as fh:
            fh.write(json.dumps(row) + "\n")
        named = (row["finder"].get("culprit") or {}).get("commit")
        print(f"{r['id']}: {'OK' if row['finder_correct'] else 'UNKNOWN' if named is None else 'WRONG'} "
              f"exec={row['finder'].get('executions')} (round 2: {row['finder_round2'].get('executions')}, "
              f"{'OK' if r.get('finder_correct') else 'not OK'}) runs={row.get('green_run')}/{row.get('red_run')}",
              flush=True)
    checkout(repo, next(iter(cases.values()))["head"])


if __name__ == "__main__":
    main()
