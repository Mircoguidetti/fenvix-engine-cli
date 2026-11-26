#!/usr/bin/env python3
"""P2 rule 2 across a reboot: classify the fixed-epoch fingerprint differences of a fix against a same-boot control.

When the container rebooted between the baseline fixed runs (F-base1..3) and the fix's fixed runs, correctness.py
rule 2 can report differences that the baseline engine shows as well on the new boot. This reads, for one repository:
  BASE_DIR/<repo>/F-base1..3   the baseline fixed runs (earlier boot)
  CTRL_DIR/<repo>/F-<ctrl>     the baseline engine's fixed run on the fix's boot (control)
  FIX_DIR/<repo>/F-<fix>, F-<repeat>   the fix's fixed run and its repeat
and prints:
  boot_effect: tests stable over F-base1..3 whose control fingerprint differs from F-base1 (same engine, new boot)
  fix_vs_ctrl: tests where both fix runs differ from the control
  of which unstable_in_baseline: those whose fingerprint varied over F-base1..3
  of which fix_matches_baseline: the rest, where both fix runs equal F-base1 (the control is the odd one out)
  unexplained: fix_vs_ctrl tests in neither group (a defect)

Usage: sameboot.py --base DIR --ctrl DIR --fix DIR --repo REPO [--ctrl-label base4] [--fix-labels fix1,fix1r] [--json OUT]
Exit status 0 when unexplained is empty.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import correctness as c  # noqa: E402


def classify(base, ctrl, fix, repo, ctrl_label="base4", fix_labels=("fix1", "fix1r")):
    B = [c._ext(os.path.join(base, repo), f"F-base{i}") for i in (1, 2, 3)]
    k4 = c._ext(os.path.join(ctrl, repo), f"F-{ctrl_label}")
    F = [c._ext(os.path.join(fix, repo), f"F-{x}") for x in fix_labels]
    if any(x is None for x in B + [k4] + F):
        return {"repo": repo, "error": "a fixed extract is missing"}
    fp = lambda d, k: (d.get(k) or {}).get("fingerprint")  # noqa: E731
    keys = [k for k in k4 if k != "_dups"]
    unstable = {k for k in keys if len({fp(b, k) for b in B}) > 1}
    boot = [k for k in keys if k not in unstable and fp(k4, k) != fp(B[0], k)]
    diff = [k for k in keys if all(fp(f, k) != fp(k4, k) for f in F)]
    unst = [k for k in diff if k in unstable]
    match = [k for k in diff if k not in unstable and all(fp(f, k) == fp(B[0], k) for f in F)]
    unexpl = [k for k in diff if k not in unstable and k not in match]
    return {"repo": repo, "tests": len(keys), "boot_effect": len(boot), "fix_vs_ctrl": len(diff),
            "unstable_in_baseline": len(unst), "fix_matches_baseline": match, "unexplained": unexpl}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--ctrl", required=True)
    ap.add_argument("--fix", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--ctrl-label", default="base4")
    ap.add_argument("--fix-labels", default="fix1,fix1r")
    ap.add_argument("--json", default=None)
    o = ap.parse_args(argv)
    r = classify(o.base, o.ctrl, o.fix, o.repo, o.ctrl_label, tuple(o.fix_labels.split(",")))
    if o.json:
        with open(o.json, "w") as fh:
            json.dump(r, fh, indent=1, sort_keys=True)
    if "error" in r:
        print(f"{o.repo}: {r['error']}")
        return 2
    print(f"{o.repo}: tests {r['tests']}, boot effect {r['boot_effect']}, fix vs control {r['fix_vs_ctrl']} "
          f"(unstable in baseline {r['unstable_in_baseline']}, fix matches baseline {len(r['fix_matches_baseline'])}), "
          f"unexplained {len(r['unexplained'])}")
    for k in r["unexplained"]:
        print(f"  unexplained: {k}")
    return 0 if not r["unexplained"] else 1


if __name__ == "__main__":
    sys.exit(main())
