#!/usr/bin/env python3
"""R-010 fix 1 re-verification: which units of a repository read the checkout's .git, and does the proof rule now
rerun a unit whose result depends on the commit?

``--probe SHA``: run every sampled unit once under capture at SHA and record its git key (``deps["git"]``: the
resolved HEAD and the .git paths it read), or None when the unit never read .git.
``--case UNIT,REC,CUR``: record UNIT at REC, decide at CUR with the fixed rule, run it fresh at CUR and compare.

    python3 gitkey.py --spec specs/prefect.json --work /tmp/w --out results/r010/gitkey/prefect.json \
        --probe <sha> --case tests/utilities/test_dockerutils.py,<rec>,<cur>
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import walk  # noqa: E402


def at(w, sha):
    w.checkout(sha)
    dh = w.dep_hash()
    if dh != w._last_dep:
        ok, why = w.install()
        if not ok:
            raise RuntimeError("install failed: " + why[-800:])
        w._last_dep = dh
    if not w.build():
        raise RuntimeError("build failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--probe", action="append", default=[])
    ap.add_argument("--case", action="append", default=[])
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text())
    w = walk.Walker(spec, a.work, Path(a.work) / "gitkey.json", 0, 1, 600, "gitkey")
    w.push = False
    w.commits()  # clone
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    res = {"spec": spec["name"], "probes": [], "cases": []}
    for c in a.case:
        unit, rec_sha, cur_sha = c.split(",")
        walk.git(w.src, "fetch", "--quiet", "--filter=blob:none", "origin", rec_sha, cur_sha, check=False)
        at(w, rec_sha)
        rec = w.run_unit(unit)
        rec["sha"] = rec_sha
        at(w, cur_sha)
        decision, info = w.decide(unit, rec, cur_sha, [rec_sha, cur_sha])
        fresh = w.run_unit(unit, traced_run=False, tag="fresh")
        a_, b_ = walk.outcome_summary(rec.get("tests") or {}), walk.outcome_summary(fresh.get("tests") or {})
        item = {"unit": unit, "rec": rec_sha, "cur": cur_sha, "rec_code": rec["code"], "fresh_code": fresh["code"],
                "git": (rec.get("deps") or {}).get("git"), "closure": decision["closure"], "why": info.get("why"),
                "fresh_same_as_cached": a_ == b_ and (rec["code"] == 0) == (fresh["code"] == 0),
                "n_ids_changed": len([k for k in set(a_) | set(b_) if a_.get(k) != b_.get(k)])}
        walk.log(f"case {unit} {rec_sha[:10]} -> {cur_sha[:10]}: closure {item['closure']} "
                 f"fresh same {item['fresh_same_as_cached']}")
        res["cases"].append(item)
        out.write_text(json.dumps(res, indent=1))
    for sha in a.probe:
        walk.git(w.src, "fetch", "--quiet", "--filter=blob:none", "origin", sha, check=False)
        at(w, sha)
        units, total = w.discover()
        walk.log(f"probe {sha[:10]}: {len(units)} units")

        def job(u):
            r = w.run_unit(u)
            d = r.get("deps") or {}
            return u, {"code": r["code"], "git": d.get("git"), "error": d.get("error")}
        with ThreadPoolExecutor(a.workers) as ex:
            per = dict(ex.map(job, units))
        gu = sorted(u for u, x in per.items() if x["git"])
        res["probes"].append({"sha": sha, "units": len(units), "units_total": total, "git_units": gu, "per_unit": per})
        walk.log(f"probe {sha[:10]}: {len(gu)} of {len(units)} units read .git: {gu[:10]}")
        out.write_text(json.dumps(res, indent=1))
    res["git_units"] = sorted({u for p in res["probes"] for u in p["git_units"]})
    out.write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
