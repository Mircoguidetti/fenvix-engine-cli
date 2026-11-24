#!/usr/bin/env python3
"""Builds pairs.csv, dropped.csv and control_checks.jsonl (copy) from results/, and REPORT.md from all tables.
Usage: build.py [--report]"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
import math
import random
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check  # noqa: E402
import md_rules as M  # noqa: E402

RES = HERE / "results"


def jl(p: Path) -> list[dict]:
    return [json.loads(x) for x in open(p) if x.strip()] if p.exists() else []


def tables() -> dict:
    rows = jl(RES / "agents.jsonl")
    pairs, dropped = [], []
    for r in sorted(rows, key=lambda x: x["idx"]):
        if r.get("status") == "pair":
            a, c = r["agent"], r["control"]
            pairs.append({"order": len(pairs) + 1, "idx": r["idx"], "agent_repo": a["repo"],
                          "control_repo": c["repo"], "T0": a["T0"], "agent_language": a["language"],
                          "agent_stars": a["stars"], "control_stars": c["stars"],
                          "agent_WF": a["WF"], "agent_job": a["job_key"], "control_WF": c["WF"],
                          "control_job": c["job_key"], "agent_level": a["level"], "control_level": c["level"],
                          "agent_D0": a["D0"], "agent_D1": a["D1"], "agent_g": round(a["g"], 6),
                          "control_D0": c["D0"], "control_D1": c["D1"], "control_g": round(c["g"], 6),
                          "controls_tested": r["controls_tested"],
                          "agent_eval_setup": (r.get("eval_agent") or {}).get("eval_setup"),
                          "control_eval_setup": (r.get("eval_control") or {}).get("eval_setup"),
                          "calls": r["calls"], "read_at": r["read_at"]})
        else:
            dropped.append({"idx": r["idx"], "repo": r["repo"], "reason": r["reason"],
                            "detail": (r.get("detail") or "")[:300], "calls": r.get("calls"),
                            "read_at": r["read_at"]})
    for name, data in (("pairs.csv", pairs), ("dropped.csv", dropped)):
        with open(HERE / name, "w", newline="") as f:
            cols = list(data[0]) if data else (["agent_repo"] + check.PAIR_FIELDS[1:] if name == "pairs.csv"
                                               else ["idx", "repo", "reason", "detail", "calls", "read_at"])
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(data)
    if (RES / "control_checks.jsonl").exists():
        shutil.copy(RES / "control_checks.jsonl", HERE / "control_checks.jsonl")
    elif not (HERE / "control_checks.jsonl").exists():
        (HERE / "control_checks.jsonl").write_text("")
    return {"rows": rows, "pairs": pairs, "dropped": dropped}


def fmt(x, nd=2):
    return "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def report(t: dict, extra: dict) -> None:
    res, errs = check.compute()
    pairs, dropped = t["pairs"], t["dropped"]
    reasons = collections.Counter(d["reason"] for d in dropped)
    ga = [float(p["agent_g"]) for p in pairs]
    gc = [float(p["control_g"]) for p in pairs]
    ci = M.bootstrap(list(zip(ga, gc))) if len(pairs) >= 2 else (None, None)
    lv = collections.Counter((p["agent_level"], p["control_level"]) for p in pairs)
    ea = [p["agent_eval_setup"] for p in pairs if p["agent_eval_setup"] is not None]
    ec = [p["control_eval_setup"] for p in pairs if p["control_eval_setup"] is not None]
    L = [res["verdict"], "", "# Market direction check: REPORT", ""]
    L += extra.get("changes", [])
    L += ["## Numbers", "", "| Item | Value |", "|---|---|",
          f"| Part 1 | {res['p1']} |", f"| Part 2 | {res['p2']} |",
          f"| Complete pairs | {res['pairs']} |",
          f"| Agent candidates read | {len(t['rows'])} |",
          f"| Median g agent | {fmt(res['median_g_agent'], 4)} |",
          f"| Median g control | {fmt(res['median_g_control'], 4)} |",
          f"| Difference of medians, 95% bootstrap (information) | {fmt(ci[0], 4)} .. {fmt(ci[1], 4)} |",
          f"| Level (agent, control) | {dict(lv) or '-'} |",
          f"| Eval setup share agent / control (information) | "
          f"{(f'{sum(ea)}/{len(ea)}' if ea else '-')} / {(f'{sum(ec)}/{len(ec)}' if ec else '-')} |",
          f"| F_T (USD) | {res['F_T']:,.0f} |", f"| F_E (USD) | {res['F_E']:,.0f} |",
          f"| R | {check.fmt_r(res['R'])} |",
          f"| Sensitivity (information): R without the largest round per category | {extra.get('sens', {}).get('no_largest', '-')} |",
          f"| Sensitivity (information): R with borderline counted as E | {extra.get('sens', {}).get('border_E', '-')} |",
          f"| Sensitivity (information): R with borderline counted as T | {extra.get('sens', {}).get('border_T', '-')} |",
          f"| Seed companies UNVERIFIED | {res['seed_unverified']} of {res['seed']} |",
          "| T0_MIN | 2026-04-01 |", ""]
    if extra.get("sens_sentence"):
        L += [extra["sens_sentence"], ""]
    L += ["## Dropped agent candidates by reason", "", "| Reason | Count |", "|---|---|"]
    L += [f"| {k} | {reasons.get(k, 0)} |" for k in M.DROP_REASONS] + [""]
    L += extra.get("body", [])
    if errs:
        L += ["## check.py problems at build time", ""] + [f"- {e}" for e in errs] + [""]
    (HERE / "REPORT.md").write_text("\n".join(L) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--extra", help="JSON file with {changes: [lines], body: [lines]}")
    a = ap.parse_args()
    t = tables()
    print(f"pairs {len(t['pairs'])}, dropped {len(t['dropped'])}")
    if a.report:
        extra = json.loads(Path(a.extra).read_text()) if a.extra else {}
        report(t, extra)
    return 0


if __name__ == "__main__":
    sys.exit(main())
