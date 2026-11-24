#!/usr/bin/env python3
"""AC2/AC4/AC5 consistency check: recompute REPORT.md line 1 from pairs.csv, funding_T.csv, funding_E.csv,
companies.csv and probe/; fail on a mismatch, a missing field, or a control with an agent file by T0 + 272 d.

protects=REPORT line 1 and its counts follow from the CSVs; fails_when=the line or a count differs, a field is
missing, or a control has an agent file; no_claim=that the sample is representative.
Exit 0 when consistent, 1 otherwise (each problem printed)."""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import md_rules as M  # noqa: E402

WIN = (dt.date(2025, 1, 1), dt.date(2026, 11, 24))
PAIR_FIELDS = ["agent_repo", "control_repo", "T0", "agent_WF", "control_WF", "agent_level", "control_level",
               "agent_D0", "agent_D1", "agent_g", "control_D0", "control_D1", "control_g"]


def rd(name: str) -> list[dict]:
    p = HERE / name
    return list(csv.DictReader(open(p))) if p.exists() else []


def compute() -> tuple[dict, list[str]]:
    errs = []
    # Part 1
    search = json.loads((HERE / "probe" / "search.json").read_text())
    blocked = not any(search[f]["form"] for f in search)
    pairs = rd("pairs.csv")
    for i, r in enumerate(pairs):
        for f in PAIR_FIELDS:
            if r.get(f) in (None, ""):
                errs.append(f"pairs.csv row {i + 1}: missing {f}")
    for i, r in enumerate(rd("dropped.csv")):
        if r.get("reason") not in M.DROP_REASONS:
            errs.append(f"dropped.csv row {i + 1}: reason {r.get('reason')!r} not allowed")
    ga = [float(r["agent_g"]) for r in pairs if r.get("agent_g")]
    gc = [float(r["control_g"]) for r in pairs if r.get("control_g")]
    fast = M.faster(ga, gc) if ga and gc else None
    p1 = M.part1_state(len(pairs), blocked, fast)
    # AC4: controls
    checks = {}
    p = HERE / "control_checks.jsonl"
    if p.exists():
        for ln in open(p):
            r = json.loads(ln)
            checks.setdefault((r["agent"], r["repo"]), []).append(r)
    for r in pairs:
        recs = checks.get((r["agent_repo"], r["control_repo"]))
        if not recs:
            errs.append(f"control {r['control_repo']} of {r['agent_repo']}: no record in control_checks.jsonl")
            continue
        for rec in recs:
            if rec.get("until") != M.iso(M.ts(r["T0"]) + dt.timedelta(days=272)):
                errs.append(f"control {r['control_repo']}: until {rec.get('until')} != T0 + 272 d")
            if set(rec.get("paths", {})) != set(M.AGENT_PATHS):
                errs.append(f"control {r['control_repo']}: not all 9 agent paths checked")
            hit = M.agent_file_hit(rec.get("paths", {}))
            if hit:
                errs.append(f"control {r['control_repo']}: agent file {hit} by T0 + 272 d")
    # Part 2
    comps = rd("companies.csv")
    for r in comps:
        if not r.get("class_2_3"):
            errs.append(f"companies.csv {r.get('company')}: no §2.3 result")
        if r["class_2_3"] != "UNVERIFIED" and not r.get("quoted_text"):
            errs.append(f"companies.csv {r.get('company')}: no quoted text")
    seed = [r for r in comps if r["listed"].startswith("seed")]
    unv = sum(1 for r in seed if r["class_2_3"] == "UNVERIFIED")
    cls = {r["company"]: r for r in comps}
    sums = {}
    rows_all = []
    for cat in ("T", "E"):
        tot = 0.0
        for i, r in enumerate(rd(f"funding_{cat}.csv")):
            rows_all.append(r)
            if r.get("summed") != "yes":
                continue
            c = cls.get(r["company"])
            if not c or c["summed_as"] != cat:
                errs.append(f"funding_{cat}.csv row {i + 1}: {r['company']} is not summed as {cat} in companies.csv")
            try:
                d = dt.date.fromisoformat(r["date"])
                if not WIN[0] <= d <= WIN[1]:
                    errs.append(f"funding_{cat}.csv row {i + 1}: date {d} outside the window")
            except ValueError:
                errs.append(f"funding_{cat}.csv row {i + 1}: bad date {r.get('date')!r}")
            for f in ("amount_usd", "source_url", "access_date"):
                if not r.get(f):
                    errs.append(f"funding_{cat}.csv row {i + 1}: missing {f}")
            tot += float(r["amount_usd"] or 0)
        sums[cat] = tot
    web_ok = False
    wp = HERE / "results" / "probe" / "web" / "summary.json"
    if wp.exists():
        web_ok = any(x["status"] == 200 and x["name"].startswith("news") for x in json.loads(wp.read_text()))
    any_source = web_ok and bool(rows_all)
    failed = M.part2_failed(len(seed), unv, any_source)
    r_ = M.ratio(sums["T"], sums["E"])
    p2 = M.part2_state(failed, r_)
    return {"pairs": len(pairs), "faster": fast, "p1": p1, "F_T": sums["T"], "F_E": sums["E"], "R": r_,
            "seed": len(seed), "seed_unverified": unv, "p2": p2, "verdict": M.verdict(p1, p2),
            "median_g_agent": M.median(ga) if ga else None, "median_g_control": M.median(gc) if gc else None}, errs


def fmt_r(r: float) -> str:
    return "infinite" if math.isinf(r) else f"{r:.2f}"


def main() -> int:
    res, errs = compute()
    rep = (HERE / "REPORT.md").read_text().splitlines() if (HERE / "REPORT.md").exists() else []
    if not rep or rep[0].strip() != res["verdict"]:
        errs.append(f"REPORT.md line 1 {rep[0] if rep else None!r} != recomputed {res['verdict']!r}")
    text = "\n".join(rep)
    for key, val in (("Complete pairs", str(res["pairs"])), ("F_T (USD)", f"{res['F_T']:,.0f}"),
                     ("F_E (USD)", f"{res['F_E']:,.0f}"), ("R", fmt_r(res["R"])), ("Part 1", res["p1"]),
                     ("Part 2", res["p2"])):
        if not re.search(rf"^\| {re.escape(key)} \| {re.escape(val)} \|", text, re.M):
            errs.append(f"REPORT.md: row '| {key} | {val} |' not found")
    print(json.dumps({k: (fmt_r(v) if k == "R" else v) for k, v in res.items()}, sort_keys=True))
    for e in errs:
        print("FAIL:", e)
    print("check.py:", "OK" if not errs else f"{len(errs)} problem(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
