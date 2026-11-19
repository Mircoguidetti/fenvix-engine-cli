#!/usr/bin/env python3
"""Fix round 3 (review R-019b): re-run the fixed finder on the committed kind-b cases (real history).

* reverts (``cases/rh-*.jsonl``): the project's own commits, nothing rewritten; the case's environment is the
  project's environment of today or a period environment (dependencies as of the commit's date, rebuilt with
  ``realrevert.period_venv``, the same resolver cut-off);
* regression fixes (``cases/fix-*.jsonl``): the history (green, red] is replayed with the fix's test files overlaid,
  exactly as ``realfix.py`` built it (same trees, messages and dates); the rebuilt commit ids must equal the recorded
  ``green`` and ``range``, else the case is recorded as not rebuilt.

The keys are written again, then the finder runs; the truth (plain walk) and the git bisect baseline of the committed
row are kept.

    refind_b.py --project NAME --repo DIR --venv DIR --period DIR --results-dir DIR --out rows.jsonl --keys-dir DIR
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
from common import checkout, git, git_out, run_det  # noqa: E402
from finder import Finder  # noqa: E402
from mutants import commit  # noqa: E402


def rebuild_fix(repo, c) -> bool:
    from realfix import TESTFILE, tree_overlaid
    fix = c["fix"]
    # the overlaid files, chosen as realfix.py chose them
    files = git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--first-parent", fix).split()
    tests = sorted(f for f in files if TESTFILE.search(f) and not f.endswith("conftest.py")
                   and git(repo, "ls-tree", fix, "--", f))
    fp = git(repo, "rev-list", "--first-parent", "--reverse", c["head"]).split()
    pos = {s: i for i, s in enumerate(fp)}
    ti = pos[c["truth_original"]]
    gi = ti - c["truth_position"]
    green = fp[gi]
    g2 = commit(repo, tree_overlaid(repo, green, fix, tests), fp[gi - 1] if gi else green,
                git_out(repo, "log", "-1", "--format=%B", green), green)
    prev, shas = g2, []
    for sha in fp[gi + 1: gi + 1 + c["k"]]:
        prev = commit(repo, tree_overlaid(repo, sha, fix, tests), prev, git_out(repo, "log", "-1", "--format=%B", sha),
                      sha)
        shas.append(prev)
    git(repo, "update-ref", f"refs/culprit3/{c['id']}", prev)
    return g2 == c["green"] and shas == c["range"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--venv", required=True, help="the project's environment of today (fix cases, plain reverts)")
    ap.add_argument("--period", required=True, help="directory for period virtualenvs")
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keys-dir", required=True)
    a = ap.parse_args()
    repo, venv0 = Path(a.repo).resolve(), Path(a.venv).resolve()
    rd = Path(a.results_dir)
    name = "pytest-fx" if a.project == "pytest" else a.project
    rows_f = rd / f"b-{name}.jsonl"
    cases = {}
    for f in (rd / "cases" / f"rh-{a.project}.jsonl", rd / "cases" / f"fix-{a.project}.jsonl"):
        if f.exists():
            cases.update({c["id"]: c for c in map(json.loads, open(f))})
    done = {json.loads(l)["id"] for l in open(a.out)} if os.path.exists(a.out) else set()
    kdir = Path(a.keys_dir).resolve()
    kdir.mkdir(parents=True, exist_ok=True)
    for r in [json.loads(l) for l in open(rows_f) if l.strip()]:
        if r["id"] in done:
            continue
        c = cases[r["id"]]
        row = dict(r)
        row["finder_round2"] = {x: (r.get("finder") or {}).get(x) for x in ("culprit", "status", "why", "executions")}
        row["finder_correct_round2"] = r.get("finder_correct")
        row["round"] = 3
        venv = venv0
        if c.get("kind") == "b-fix":
            ok = rebuild_fix(repo, c)
        else:
            ok = True
            if c.get("venv") and "/periodv/" in c["venv"]:
                from realrevert import period_venv
                pv, info = period_venv(repo, c["fx"], a.project, Path(a.period).resolve())
                venv = pv
                ok = pv is not None
        row["rebuilt"] = ok
        if not ok:
            row["finder"] = {"culprit": None, "status": "not rebuilt", "why": "history or environment not rebuilt",
                             "executions": 0, "steps": []}
            row["finder_correct"] = False
        else:
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
            except Exception as e:
                fr = {"culprit": None, "status": "error", "why": f"error: {type(e).__name__}: {e}",
                      "executions": len(f.steps), "steps": f.steps}
            row["finder"] = {x: v for x, v in fr.items() if x != "nodeid"}
            row["finder_correct"] = (fr.get("culprit") or {}).get("commit") == r["truth"]
        with open(a.out, "a") as fh:
            fh.write(json.dumps(row) + "\n")
        named = (row["finder"].get("culprit") or {}).get("commit")
        print(f"{r['id']}: {'OK' if row['finder_correct'] else 'UNKNOWN' if named is None else 'WRONG'} "
              f"exec={row['finder'].get('executions')} (round 2: {row['finder_round2'].get('executions')}) "
              f"rebuilt={ok} runs={row.get('green_run')}/{row.get('red_run')}", flush=True)
    checkout(repo, next(iter(cases.values()))["head"])


if __name__ == "__main__":
    main()
