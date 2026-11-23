#!/usr/bin/env python3
"""REPORT.md of the control arm from results.jsonl and pairs.jsonl (no run is made here).

Usage: report.py --status DONE|NOT\\ DONE|BLOCKED [--notes notes.md] > REPORT.md
The notes file (hand-written: how runs were made, step 4, per-repository reasons) is inserted after the tables.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import control_arm as CA  # noqa: E402


def fmt(x):
    return "-" if x is None else (f"{x:.1f}" if isinstance(x, float) else str(x))


def per_repo(name, rows, pairs):
    runs = [r for r in rows if r.get("row") == "run" and r["repo"] == name]
    vs = [r for r in rows if r.get("row") == "verdict" and r["repo"] == name]
    ps = [r for r in rows if r.get("row") == "pair_search" and r["repo"] == name]
    pr = [p for p in pairs if p["repo"] == name]
    if not runs:
        return None
    c = {}
    for v in vs:
        k = v["verdict"] + (f"/{v['label']}" if v["label"] else "")
        c[k] = c.get(k, 0) + 1
    par = [r for r in runs if r["kind"] == "P"]
    done_par = [r for r in par if not r["timed_out"] and not r["crashed"]]
    valid = [r for r in par if r.get("valid") == "valid"]
    ser = [r["wall_s"] for r in runs if r["kind"] == "S" and not r["timed_out"] and not r["crashed"]]
    pw = [r["wall_s"] for r in done_par]
    pair_s = ps[0]["pair_search_s"] if ps else 0.0
    nine = sum(r["wall_s"] for r in runs)
    return {
        "repo": name,
        "tests": max((r["tests"] for r in runs if r["kind"] == "S"), default=0),
        "IDENTICAL": c.get("IDENTICAL", 0),
        "DIVERGES": c.get("DIVERGES/order", 0) + c.get("DIVERGES/parallel", 0),
        "div_order": c.get("DIVERGES/order", 0), "div_parallel": c.get("DIVERGES/parallel", 0),
        "order_only": c.get("DIVERGES-order-only", 0),
        "UNDECIDED": sum(v for k, v in c.items() if k.startswith("UNDECIDED")),
        "und_insufficient": c.get("UNDECIDED/insufficient-parallel", 0),
        "und_serial": c.get("UNDECIDED/serial-disagree", 0),
        "und_run": c.get("UNDECIDED/run-failed-or-short", 0),
        "und_seen_div": sum(1 for v in vs if v["verdict"] == "UNDECIDED" and v.get("diverging_runs")),
        "div_one_run": sum(1 for v in vs if v["verdict"] == "DIVERGES" and len(v.get("diverging_runs") or []) == 1),
        "load_failed": sorted({r.get("load_failed_files") for r in runs}, key=lambda x: (x is None, x)),
        "ENV": c.get("ENV", 0),
        "timed_out": [r["run"] for r in runs if r["timed_out"]],
        "crashed": [r["run"] for r in runs if r["crashed"]],
        "short": [f"{r['run']}(-{r['missing_vs_serial']})" for r in runs if r.get("short")],
        "invalid_serial": [r["run"] for r in par if r.get("valid") == "INVALID" and not r["timed_out"] and not r["crashed"]],
        "effective": f"{'yes' if len(valid) == len(par) else 'no' if not valid else 'partly'} ({len(valid)}/{len(par)} valid)",
        "pairs_found": sum(1 for p in pr if p["result"] == "pair found"),
        "pairs_not_found": sum(1 for p in pr if p["result"].startswith("no minimal pair")),
        "alone": sum(1 for p in pr if p["result"] == "no minimal pair (victim file alone reproduces)"),
        "alone_ctl": sum(1 for p in pr if p["result"] == "no minimal pair (victim file alone reproduces)"
                         and p.get("control_seeds")),
        "not_repro": sum(1 for p in pr if p["result"] == "no minimal pair (not reproduced)"),
        "pairs_budget": sum(1 for p in pr if p["result"] == "pair not found (budget)"),
        "victims": len(pr),
        "victims_order": sum(1 for p in pr if p.get("label") == "order"),
        "reproduced": sum(1 for p in pr if any(t.get("triggered") for t in p.get("trials") or [])),
        "serial_median": statistics.median(ser) if ser else None,
        "par_median": statistics.median(pw) if pw else None,
        "par_median_valid": statistics.median([r["wall_s"] for r in valid]) if valid else None,
        "total": round(nine + pair_s, 1), "nine": round(nine, 1), "pair_s": pair_s,
        "searched": bool(ps),
    }


def render(status, notes, rows, pairs):
    out = [status, "", "# Lane D: the no-engine control arm (plain runs only)", ""]
    out += ["Plain runner commands only; the engine (detjs, fenvix) was never run. Data: `results.jsonl` (one row per run "
            "and one per test verdict), `pairs.jsonl` (one row per victim), `data/<repo>/<run>.json` (outcome map, "
            "failure messages, per-file start/end of every run). Code: `control_arm.py`, tests `test_control_arm.py`.", ""]
    reps = [(n, per_repo(n, rows, pairs)) for n in CA.REPOS]
    out += ["## Verdicts per repository", "",
            "| repository | tests (serial) | IDENTICAL | DIVERGES (order / parallel) | of which in 1 parallel run only | "
            "DIVERGES-order-only | UNDECIDED (insufficient parallel / S1≠S2 / run failed or short) | ENV | test files that "
            "did not load (per run; their tests are in no column) |",
            "|---|---|---|---|---|---|---|---|---|"]
    for n, r in reps:
        if not r:
            out.append(f"| {n} | not run (see notes) | | | | | | | |")
            continue
        out.append(f"| {n} | {r['tests']} | {r['IDENTICAL']} | {r['DIVERGES']} ({r['div_order']} / {r['div_parallel']}) | "
                   f"{r['div_one_run']} | {r['order_only']} | {r['UNDECIDED']} ({r['und_insufficient']} / {r['und_serial']} / "
                   f"{r['und_run']}) | {r['ENV']} | {' / '.join(fmt(x) for x in r['load_failed'])} |")
    out += ["", "## Runs and parallelism", "",
            "| repository | timed out | crashed | short (tests missing vs serial) | INVALID (serial in disguise) | "
            "parallel mode effective | UNDECIDED with a divergence seen |", "|---|---|---|---|---|---|---|"]
    for n, r in reps:
        if r:
            out.append(f"| {n} | {', '.join(r['timed_out']) or 0} | {', '.join(r['crashed']) or 0} | "
                       f"{', '.join(r['short']) or 0} | {', '.join(r['invalid_serial']) or 0} | {r['effective']} | {r['und_seen_div']} |")
    out += ["", "## Minimal pairs and wall time", "",
            "| repository | victims searched (of which label order) | divergence reproduced in any trial | pairs found | "
            "not found (victim file alone reproduces, of which with a control seed / not reproduced / other) | over "
            "budget | serial median (s) | parallel run median (s, completed / valid) | 9 runs (s) | pair search (s) | "
            "total (s) |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, r in reps:
        if r:
            out.append(f"| {n} | {(str(r['victims']) + ' (' + str(r['victims_order']) + ')') if r['searched'] else 'not run'} | "
                       f"{r['reproduced']} | {r['pairs_found']} | {r['pairs_not_found']} ({r['alone']}, {r['alone_ctl']} / "
                       f"{r['not_repro']} / {r['pairs_not_found'] - r['alone'] - r['not_repro']}) | "
                       f"{r['pairs_budget']} | {fmt(r['serial_median'])} | {fmt(r['par_median'])} / {fmt(r['par_median_valid'])} | "
                       f"{r['nine']} | {r['pair_s']} | {r['total']} |")
    if notes:
        out += ["", notes.rstrip()]
    out += ["", "## For the 22 Dec comparison", "",
            "Control arm columns measured here; engine columns left empty (filled at the verdict).", "",
            "| repository | control: bugs (confirmed pairs) | control: within-file order dependences reproduced alone "
            "(victims) | control: DIVERGES tests | control: wrong IDENTICAL | control: wall serial median / parallel "
            "median (s) | engine: bugs | engine: wrong identical | engine: wall |",
            "|---|---|---|---|---|---|---|---|---|"]
    for n, r in reps:
        if r:
            out.append(f"| {n} | {r['pairs_found']} | {r['alone']} of {r['victims']} | {r['DIVERGES']} | (at verdict) | "
                       f"{fmt(r['serial_median'])} / {fmt(r['par_median'])} | | | |")
        else:
            out.append(f"| {n} | not run | | | | | | | |")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", required=True, choices=["DONE", "NOT DONE", "BLOCKED"])
    ap.add_argument("--notes")
    o = ap.parse_args()
    notes = open(o.notes).read() if o.notes else ""
    sys.stdout.write(render(o.status, notes, CA.read_jsonl(CA.RESULTS), CA.read_jsonl(CA.PAIRS)))


if __name__ == "__main__":
    main()
