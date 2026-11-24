#!/usr/bin/env python3
"""Step 2 timer count (spec det-host-values): the 48 codex-multi-auth flips that reproduced at V0 on the trunk
(harness/det_pins/results.jsonl, status "reproduced"), re-run at V0 with the branch engine
(`pins.py variants --repo codex-multi-auth --variants V0 --out <dir>`, a fresh <dir> holding only the trunk's
flips.json). Cleared = passed in both runs. Prints the table and every row from the raw outcome files.

    python3 harness/det_host_values/timers.py <dir>
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "det_pins"))
import pins  # noqa: E402

REPO = "codex-multi-auth"


def main(d):
    out = os.path.join(d, REPO)
    picked = json.load(open(os.path.join(out, "sample.json")))["sample"]
    groups = sorted({pins.split_id(t) for t in picked})
    rows = [json.loads(x) for x in open(os.path.join(HERE, "..", "det_pins", "results.jsonl"))]
    trunk = {r["test_id"]: r for r in rows if r["repo"] == REPO}
    reproduced = [t for t in picked if trunk[t]["status"] == "reproduced"]
    res = []
    for t in reproduced:
        gi = groups.index(pins.split_id(t))
        oc, ex = [], []
        for rep in (1, 2):
            o, e = pins.det_outcomes(os.path.join(out, "variants", f"g{gi:02d}.V0.r{rep}.outcomes.json"))
            oc.append(o.get(t, "absent"))
            ex.append(pins.first_line(e.get(t)))
        cleared = all(x == "passed" for x in oc)
        res.append((t, oc, cleared, ex[0] or ""))
    n = len(res)
    c = sum(1 for r in res if r[2])
    print(f"engine: {open(os.path.join(d, 'engine.commit')).read().strip()}")
    print(f"reproduced at V0 on the trunk (det_pins results.jsonl): {n}")
    print(f"cleared at V0 with the branch engine (passed in both runs): {c} of {n} (threshold 35)")
    print()
    print("| test | branch V0 runs | cleared | first failure line (run 1) |")
    print("|---|---|---|---|")
    for t, oc, cl, ex in res:
        print(f"| `{t[:120]}` | {'/'.join(oc)} | {'yes' if cl else 'no'} | `{ex[:140]}` |")


if __name__ == "__main__":
    main(sys.argv[1])
