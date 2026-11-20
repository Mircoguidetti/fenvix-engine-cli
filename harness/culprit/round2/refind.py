#!/usr/bin/env python3
"""Re-run the finder (only) on result rows of run_code_cases.py, from the keys it saved; the keys and the git bisect
baseline are kept. Used after the round-2 finder change (undo detection, withheld answer beyond the re-touch cap).

    refind.py --results rows.jsonl --repo DIR --venv DIR --keys-dir DIR --out rows2.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import checkout  # noqa: E402
from finder import Finder  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--venv", required=True)
    ap.add_argument("--keys-dir", required=True)
    ap.add_argument("--cases", required=True, help="the case file (green and red commits, per-case venv)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    repo = Path(a.repo).resolve()
    cases = {c["id"]: c for c in map(json.loads, open(a.cases))}
    done = {json.loads(l)["id"] for l in open(a.out)} if os.path.exists(a.out) else set()
    for line in open(a.results):
        r = json.loads(line)
        if r["id"] in done:
            continue
        c = cases[r["id"]]
        venv = Path(c.get("venv") or a.venv).resolve()
        gk, rk = (str(Path(a.keys_dir) / f"{r['id']}-{s}.json") for s in ("green", "red"))
        r_old = r["finder"]
        f = Finder(repo, r["red_test"], {"sha": c["green"], "env": {}, "venv": venv, "key": gk},
                   {"sha": c["red_head"], "env": {}, "venv": venv, "key": rk})
        try:
            fr = f.run()
        except Exception as e:
            fr = {"culprit": None, "status": "error", "why": f"error: {type(e).__name__}: {e}",
                  "executions": len(f.steps), "steps": f.steps}
        named = (fr.get("culprit") or {}).get("commit")
        r["finder_round2a"] = {k: r_old.get(k) for k in ("culprit", "status", "why", "executions")}
        r["finder"] = {k: v for k, v in fr.items() if k != "nodeid"}
        r["finder_correct"] = named == r["truth"]
        with open(a.out, "a") as fh:
            fh.write(json.dumps(r) + "\n")
        print(f"{r['id']}: {'OK' if r['finder_correct'] else 'UNKNOWN' if named is None else 'WRONG'} "
              f"exec={fr.get('executions')} (before: {r_old.get('executions')})", flush=True)
    if cases:
        checkout(repo, next(iter(cases.values()))["head"])


if __name__ == "__main__":
    main()
