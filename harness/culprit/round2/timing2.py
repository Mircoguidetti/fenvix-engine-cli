#!/usr/bin/env python3
"""Clean timing (idle host, one case at a time): the round-2 finder (from the saved keys) and git bisect on a
sample of kind-a2 cases. Wall times of the main runs are noisy (4 to 9 jobs on 4 cores).

    timing2.py --sample N --out timing.jsonl     (paths of the session machine)
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import checkout, git_bisect  # noqa: E402
from finder import Finder  # noqa: E402

W = Path("/home/user/work")
LIBS = ["attrs", "boltons", "cachetools", "click", "jinja", "marshmallow", "more-itertools", "sqlparse", "structlog",
        "toolz"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-lib", type=int, default=2)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rng = random.Random("timing2")
    for n in LIBS:
        cases = {c["id"]: c for c in map(json.loads, open(W / f"cases2/a2-{n}.jsonl"))}
        rows = [json.loads(l) for l in open(W / f"results3/a-{n}.jsonl")]
        rows = [r for r in rows if r.get("green_run") == "pass" and r.get("red_run") == "fail"]
        for r in rng.sample(rows, min(a.per_lib, len(rows))):
            c = cases[r["id"]]
            repo, venv = W / "repos" / n, W / "venvs" / n
            gk, rk = (str(W / "keys2" / n / f"{r['id']}-{s}.json") for s in ("green", "red"))
            t0 = time.perf_counter()
            fr = Finder(repo, r["red_test"], {"sha": c["green"], "env": {}, "venv": venv, "key": gk},
                        {"sha": c["red_head"], "env": {}, "venv": venv, "key": rk}).run()
            tf = time.perf_counter() - t0
            b = git_bisect(repo, venv, c["green"], c["red_head"], ["--tb=no", "-p", "no:randomly", r["red_test"]])
            checkout(repo, c["head"])
            named = (fr.get("culprit") or {}).get("commit")
            row = {"id": r["id"], "finder_wall": round(tf, 2), "finder_executions": fr["executions"],
                   "finder_correct": named == r["truth"], "finder_status": fr["status"],
                   "replay_walls": [s["wall"] for s in fr["steps"]], "bisect_wall": round(b["wall"], 2),
                   "bisect_executions": b["executions"]}
            with open(a.out, "a") as fh:
                fh.write(json.dumps(row) + "\n")
            print(row, flush=True)


if __name__ == "__main__":
    main()
