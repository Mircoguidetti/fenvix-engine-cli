#!/usr/bin/env python3
"""Merge every leg's output into exam/results.json.

    python3 exam/aggregate.py --in exam-out-all --legs exam/legs.json --gaps exam/gap_map.json --out exam/results.json

A row is PASS only when every leg the row names reported, and every check of every leg passed. A gap is closed only
when every check that covers it ran and passed on every leg it ran on.
"""
from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import os
import re
from collections import defaultdict


def leg_key(leg: dict) -> str:
    parts = [leg.get("platform", "")]
    if leg.get("python"):
        parts.append(f"py{leg['python']}")
    if leg.get("node"):
        parts.append(f"node{leg['node']}")
    if leg.get("variant"):
        parts.append(leg["variant"])
    return "/".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--legs", required=True)
    ap.add_argument("--gaps", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID"))
    ap.add_argument("--jobs", default="", help="JSON file: job name -> job id (from the Actions API)")
    ap.add_argument("--base", default="", help="outputs of a base run: rows not rerun here are taken from it")
    ap.add_argument("--base-run", default="")
    a = ap.parse_args()

    legs = json.load(open(a.legs))["legs"]
    gm = json.load(open(a.gaps))
    jobs = json.load(open(a.jobs)) if a.jobs and os.path.exists(a.jobs) else {}
    def load(dirn):
        res = []
        for p in sorted(glob.glob(os.path.join(dirn, "**", "*.json"), recursive=True)):
            try:
                d = json.load(open(p))
            except ValueError:
                continue
            if isinstance(d, dict) and "results" in d and "leg" in d:
                res.append(d)
        return res
    planned = {leg_key(lg) for lg in legs}
    outs = [o for o in load(a.inp) if leg_key(o["leg"]) in planned]
    rerun = {r for o in outs for r in o["rows"]}
    base_used = []
    if a.base and os.path.isdir(a.base):
        for o in load(a.base):
            if leg_key(o["leg"]) in planned and not set(o["rows"]) & rerun:
                o.setdefault("run_id", a.base_run)
                outs.append(o)
                base_used.append(o.get("job"))

    expected = defaultdict(set)   # row -> leg keys the plan names
    for lg in legs:
        for r in lg["rows"]:
            expected[r].add(leg_key(lg))
    installs = {}
    rows = {r: {"status": None, "legs": {}, "checks": [], "failed": []} for r in expected}
    for o in outs:
        lk = leg_key(o["leg"])
        installs[lk] = o.get("install", {})
        for r in o["rows"]:
            rows.setdefault(r, {"status": None, "legs": {}, "checks": [], "failed": []})
            rows[r]["legs"][lk] = {"job": o.get("job"), "job_id": jobs.get(o.get("job") or ""), "run_id": o.get("run_id"),
                                   "seconds": o.get("seconds"), "install_ok": o.get("install", {}).get("ok"),
                                   "runner": o.get("runner")}
        for c in o["results"]:
            rec = {"id": c["id"], "leg": lk, "ok": c["ok"], "expected": c["expected"], "observed": c["observed"],
                   "run_id": o.get("run_id"), "job": o.get("job")}
            if c.get("gaps"):
                rec["gaps"] = c["gaps"]
            rows.setdefault(c["row"], {"status": None, "legs": {}, "checks": [], "failed": []})["checks"].append(rec)

    for r, v in rows.items():
        missing_legs = sorted(expected.get(r, set()) - set(v["legs"]))
        v["missing_legs"] = missing_legs
        v["failed"] = sorted({f"{c['id']} @ {c['leg']}" for c in v["checks"] if not c["ok"]})
        v["n_checks"] = len(v["checks"])
        v["n_passed"] = sum(c["ok"] for c in v["checks"])
        v["status"] = "PASS" if v["checks"] and not v["failed"] and not missing_legs else "FAIL"

    # gaps: match each gap's check id (with <placeholders> as wildcards) against the check ids that ran
    def matches(pattern, cid):
        pat = re.sub(r"<[^>]+>", "*", pattern).replace(" ", "")
        return fnmatch.fnmatch(cid, pat) or fnmatch.fnmatch(cid, pat + ".*") or cid == pattern
    gaps_out, unassigned, out_scope, other = {}, {}, {}, {}
    for g, info in gm["gaps"].items():
        if "other_row" in info:
            other[g] = {"row": info["other_row"], "note": info.get("note")}
            continue
        if "out_of_scope" in info:
            out_scope[g] = info["out_of_scope"]
            continue
        if "unassignable" in info:
            unassigned[g] = info["unassignable"]
            continue
        row, chk = info["row"], info["check"]
        cs = [c for c in rows.get(row, {}).get("checks", []) if matches(chk, c["id"]) or g in c.get("gaps", [])]
        st = "NO-CHECK-RAN" if not cs else ("CLOSED" if all(c["ok"] for c in cs) else "OPEN")
        gaps_out[g] = {"row": row, "check": chk, "status": st, "severity": info.get("severity"),
                       "checks": sorted({f"{c['id']} @ {c['leg']}" for c in cs})[:12]}
    for r, v in rows.items():
        gs = [g for g, x in gaps_out.items() if x["row"] == r]
        v["gaps"] = {"total": len(gs), "closed": sum(gaps_out[g]["status"] == "CLOSED" for g in gs),
                     "open": sum(gaps_out[g]["status"] == "OPEN" for g in gs),
                     "no_check_ran": sum(gaps_out[g]["status"] == "NO-CHECK-RAN" for g in gs)}
        if v["gaps"]["open"] or v["gaps"]["no_check_ran"]:
            v["status"] = "FAIL"

    res = {
        "exam": "go-live acceptance exam (exam/PLAN.md)",
        "run_id": a.run_id,
        "base_run": a.base_run or None,
        "rows_rerun_in_run_id": sorted(rerun) if a.base_run else None,
        "installed": installs,
        "decisions": gm.get("decisions", []),
        "summary": {"rows": len(rows), "pass": sum(v["status"] == "PASS" for v in rows.values()),
                    "fail": sum(v["status"] == "FAIL" for v in rows.values()),
                    "checks": sum(v["n_checks"] for v in rows.values()),
                    "checks_passed": sum(v["n_passed"] for v in rows.values()),
                    "gaps_in_scope": len(gaps_out), "gaps_closed": sum(x["status"] == "CLOSED" for x in gaps_out.values()),
                    "gaps_out_of_scope": len(out_scope), "gaps_unassignable": len(unassigned),
                    "gaps_other_row_F14": len(other)},
        "rows": {r: rows[r] for r in sorted(rows)},
        "gaps": gaps_out,
        "unassigned_gaps": unassigned,
        "out_of_scope_gaps": out_scope,
        "other_row_gaps": other,
    }
    with open(a.out, "w") as fh:
        json.dump(res, fh, indent=1)
    print(json.dumps(res["summary"], indent=1))
    for r in sorted(rows):
        v = rows[r]
        print(f"{r}: {v['status']}  {v['n_passed']}/{v['n_checks']} checks, legs {len(v['legs'])} (missing {len(v['missing_legs'])}), gaps {v['gaps']}")


if __name__ == "__main__":
    main()
