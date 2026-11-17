#!/usr/bin/env python3
"""Re-check a verification mismatch ("wrong hit") of a walk.

A verified skip is a mismatch when the fresh outcome of a unit at commit ``cur`` differs from the outcome cached at
commit ``rec`` (the unit's last real run). This script reruns the unit at ``rec`` and at ``cur`` in a fresh
environment, plainly (``--reps`` times), traced alone once, and traced under load (``--load`` traced copies at
once, as in the walk, where every unit of a commit runs in parallel under strace). Verdict per test:

* ``code-change``: ``rec`` and ``cur`` give stable and different outcomes: a real wrong hit;
* ``not-reproducible``: ``rec`` now gives the fresh outcome of ``cur`` (the cached outcome does not reproduce);
* ``load-sensitive``: outcomes differ between plain and loaded runs at the same commit (flaky under load).

    python recheck.py --spec specs/home-assistant.json --pr 171334 --rec <sha> --cur <sha> \
        --unit tests/components/switchbot/test_init.py --work /tmp/r --out results/x/recheck/a.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import walk  # noqa: E402


def summ(r):
    return {"code": r["code"], "wall": round(r["wall"], 2),
            "tests": walk.outcome_summary(r.get("tests") or {}),
            "tail": (r.get("tail") or "")[-600:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--pr", type=int, default=None)
    ap.add_argument("--rec", required=True)
    ap.add_argument("--cur", required=True)
    ap.add_argument("--unit", action="append", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--load", type=int, default=4)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text())
    spec["seq"] = {"kind": "list", "commits": [a.rec, a.cur]}
    w = walk.Walker(spec, a.work, Path(a.work) / "recheck.json", 0, 1, 300, "recheck")
    w.push = False
    w.commits()  # clone
    if a.pr:
        walk.git(w.src, "fetch", "--quiet", "--filter=blob:none", "origin", f"pull/{a.pr}/head:refs/s2/pr{a.pr}")
    res = {"spec": spec["name"], "pr": a.pr, "rec": a.rec, "cur": a.cur, "units": a.unit, "runs": {}}
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for tag, sha in (("rec", a.rec), ("cur", a.cur), ("rec2", a.rec)):
        w.checkout(sha)
        dh = w.dep_hash()
        if dh != w._last_dep:
            ok, why = w.install()
            if not ok:
                res["runs"][tag] = {"error": "install failed: " + why[-500:]}
                continue
            w._last_dep = dh
        if not w.build():
            res["runs"][tag] = {"error": "build failed"}
            continue
        reps = a.reps if tag != "rec2" else 1
        per = {}
        for u in a.unit:
            plain = [summ(w.run_unit(u, traced_run=False, tag=f"{tag}p{k}")) for k in range(reps)]
            alone = summ(w.run_unit(u, traced_run=True, tag=f"{tag}t"))
            with ThreadPoolExecutor(a.load) as ex:
                loaded = [summ(r) for r in ex.map(lambda k: w.run_unit(u, traced_run=True, tag=f"{tag}l{k}"),
                                                    range(a.load))] if tag != "rec2" else []
            per[u] = {"plain": plain, "traced": alone, "loaded": loaded}
            walk.log(f"{tag} {sha[:10]} {u}: plain {[p['code'] for p in plain]} traced {alone['code']} "
                     f"loaded {[x['code'] for x in loaded]}")
        res["runs"][tag] = {"sha": sha, "units": per}
        out.write_text(json.dumps(res, indent=1))
    # verdicts
    verdict = {}
    for u in a.unit:
        try:
            r, c = res["runs"]["rec"]["units"][u], res["runs"]["cur"]["units"][u]
        except KeyError:
            verdict[u] = "incomplete"
            continue
        def stable(xs):
            ts = [json.dumps(x["tests"], sort_keys=True) for x in xs]
            return ts[0] if len(set(ts)) == 1 else None
        rp, cp = stable(r["plain"]), stable(c["plain"])
        all_rec = stable(r["plain"] + [r["traced"]] + r["loaded"])
        all_cur = stable(c["plain"] + [c["traced"]] + c["loaded"])
        if rp and cp and rp != cp:
            verdict[u] = "code-change" if (all_rec and all_cur) else "code-change (plus load-sensitive)"
        elif rp and cp and rp == cp:
            verdict[u] = "not-reproducible" + ("" if (all_rec and all_cur) else " (load-sensitive)")
        else:
            verdict[u] = "flaky (plain runs disagree)"
    res["verdict"] = verdict
    out.write_text(json.dumps(res, indent=1))
    walk.log(f"verdict {verdict}")
    if os.environ.get("S2_COMMIT"):
        walk.commit_results([out], f"Skip study 2 (recheck): {spec['name']} {a.cur[:10]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
