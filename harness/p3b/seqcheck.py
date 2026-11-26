#!/usr/bin/env python3
"""P3b step B1: does this repository's Vitest accept `sequence.sequencer` through the harness-only config ladder.py
writes? Two plain runs through ladder.Ctx.plain of two of R's case files: one with Vitest's default order, one with
the reverse of the order the first applied, forced through P3_ORDER. Accepted = both runs wrote the applied order,
the forced run applied exactly the intended order, and both runs reported outcomes.

    export PM_WORK=$HOME/pm-p3b; python3 harness/p3b/seqcheck.py --repo R --find $PM_WORK/find
        -> harness/p3b/data/R/seqcheck.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import classify  # noqa: E402,F401  (first: parallel_measure/ has its own classify.py)
import ladder  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--find", required=True)
    o = ap.parse_args()
    ctx = ladder.Ctx(o)
    files = sorted({ladder.file_of(c["id"]) for c in ctx.cases})
    if len(files) < 2:  # one case file: add the next file of the recorded --det order
        files += [f for f in ladder.file_order(ctx.det_orders[0]) if f not in files][:1]
    files = files[:2]
    vit = json.load(open(os.path.join(ctx.cwd, "node_modules", "vitest", "package.json")))["version"]
    d = ctx.plain("seqcheck.default", files)
    want = list(reversed(d["applied"] or [ladder.split_file(f)[0] for f in files]))
    f = ctx.plain("seqcheck.forced", files, order=want)
    ok = bool(d["applied"]) and f["applied"] == f["intended"] == want and bool(d["outcomes"]) and bool(f["outcomes"])
    out = {"repo": o.repo, "vitest": vit, "files": files, "accepted": ok,
           "default": {k: d[k] for k in ("cmd", "exit", "wall_s", "applied")} | {"n_outcomes": len(d["outcomes"])},
           "forced": {k: f[k] for k in ("cmd", "exit", "wall_s", "applied", "intended")} | {"n_outcomes": len(f["outcomes"])}}
    os.makedirs(os.path.join(ladder.DATA, o.repo), exist_ok=True)
    with open(os.path.join(ladder.DATA, o.repo, "seqcheck.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print(json.dumps({k: out[k] for k in ("repo", "vitest", "files", "accepted")}))


if __name__ == "__main__":
    main()
