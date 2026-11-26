#!/usr/bin/env python3
"""P2 rule 1 explanations from the baseline engine's own variability (no hand-written lines).

correctness.py rule 1 compares a test's verify class set over the fix's 3 rounds with the baseline's 3 rounds; a test
with one class in the baseline but another set at the fix is a change, and a change needs a one-line explanation.
This writes an explanation only where the evidence is in the committed data: the baseline engine itself showed every
class the fix shows for that test and worker count, over all its rounds on both boots (BASE_DIRS, e.g. the Phase A
baseline and the same-boot re-run), and showed more than one class there (the test's class varies with the baseline
engine). A change it cannot explain this way is left out and stays a defect in correctness.py.

Usage: explain_rule1.py --repo REPO --cmp-base DIR --fix DIR --base-dirs DIR1,DIR2 --out FILE.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import correctness as c  # noqa: E402


def explain(repo, cmp_base, fix, base_dirs):
    out, unexplained = {}, []
    for n in c.WORKERS:
        r = c.rule1(os.path.join(cmp_base, repo), os.path.join(fix, repo), n)
        union = {}
        for d in base_dirs:
            sets, _ = c.class_sets(os.path.join(d, repo), n)
            for k, s in sets.items():
                union.setdefault(k, set()).update(s)
        for ch in r["changes"]:
            k, fs = ch["nodeid"], set(ch["fix"])
            u = union.get(k, set())
            if len(u) > 1 and fs <= u:
                line = (f"w{n}: varies with the baseline engine: classes {sorted(u)} over its rounds in "
                        f"{', '.join(os.path.basename(x.rstrip('/')) for x in base_dirs)}; the fix showed {sorted(fs)}")
                out[k] = (out[k] + " | " + line) if k in out else line
            else:
                unexplained.append({"nodeid": k, "w": n, "fix": sorted(fs), "baseline_engine_union": sorted(u)})
    # a nodeid explained for one worker count but not the other stays unexplained: drop its line
    for u in unexplained:
        out.pop(u["nodeid"], None)
    return out, unexplained


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--cmp-base", required=True)
    ap.add_argument("--fix", required=True)
    ap.add_argument("--base-dirs", required=True)
    ap.add_argument("--out", required=True)
    o = ap.parse_args(argv)
    ex, un = explain(o.repo, o.cmp_base, o.fix, o.base_dirs.split(","))
    with open(o.out, "w") as fh:
        json.dump(ex, fh, indent=1, sort_keys=True)
    print(f"{o.repo}: explained {len(ex)}, unexplained {len(un)}")
    for u in un:
        print(f"  unexplained w{u['w']}: {u['nodeid']} fix {u['fix']} baseline-engine {u['baseline_engine_union']}")
    return 0 if not un else 1


if __name__ == "__main__":
    sys.exit(main())
