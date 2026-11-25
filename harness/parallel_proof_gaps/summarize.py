#!/usr/bin/env python3
"""Step M of spec parallel-proof-gaps: one table per measurement point from measure.py output.

    summarize.py OUT_DIR [OUT_DIR_PREVIOUS]   -> JSON rows on stdout, and a Markdown table (with deltas against the
                                                 previous point, and the stop rule applied) on stderr

Per repository and worker count (rows of OUT_DIR/results.jsonl, round 1): the parallel run's exit and wall time, the
hazards of its trace header by kind (meta.parallel.hazards), the files the one-lane re-run took
(meta.hazard_rerun.files), and the proven share from `fenvix verify S1 P1wN` (summary.identical / summary.tests).
The best worker count of a repository is the one with the lowest parallel wall time. Stop rule (spec, gate note 2):
best-worker wall time up by more than 25 %, or proven share down by more than 25 percentage points, against the
previous point.
"""
from __future__ import annotations

import gzip
import json
import os
import sys


def header(path):
    op = gzip.open if path.endswith(".gz") else open
    for p in (path, path + ".gz"):
        if os.path.exists(p):
            with (gzip.open if p.endswith(".gz") else open)(p, "rt") as f:
                return json.loads(f.readline())
    return None


def rows(out):
    res = os.path.join(out, "results.jsonl")
    if not os.path.exists(res):
        return {}
    by = {}
    for line in open(res):
        if not line.strip():
            continue
        j = json.loads(line)
        if j.get("rep") != 1:
            continue
        by.setdefault(j["repo"], []).append(j)
    table = {}
    for repo, rs in sorted(by.items()):
        per = {}
        for r in rs:
            n = r.get("workers")
            if r["kind"] == "par":
                h = header(os.path.join(out, repo, f"P1w{n}.jsonl")) or {}
                meta = h.get("meta") or {}
                hz = ((meta.get("parallel") or {}).get("hazards")) or []
                kinds = {}
                for x in hz:
                    kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
                hr = meta.get("hazard_rerun") or {}
                per.setdefault(n, {}).update({
                    "exit": r["exit"], "wall_s": r["wall_s"], "noisy": r.get("noisy"), "tests": r.get("tests"),
                    "hazards": len(hz), "hazard_kinds": kinds, "rerun_files": len(hr.get("files") or []),
                    "rerun_complete": hr.get("complete"), "skip_dirs_ignored": len((meta.get("parallel") or {}).get("skip_dirs_ignored") or []),
                })
            elif r["kind"] == "verify":
                s = r.get("summary") or {}
                t = s.get("tests") or 0
                per.setdefault(n, {}).update({"verify_tests": t, "proven": s.get("identical"), "not_proven": s.get("not_proven"),
                                              "proven_share": round(100.0 * (s.get("identical") or 0) / t, 1) if t else None})
            elif r["kind"] == "serial":
                table.setdefault(repo, {})["serial"] = {"exit": r["exit"], "wall_s": r["wall_s"], "tests": r.get("tests")}
        table.setdefault(repo, {})["par"] = {str(k): v for k, v in sorted(per.items())}
        walls = {k: v["wall_s"] for k, v in per.items() if "wall_s" in v}
        table[repo]["best_workers"] = str(min(walls, key=walls.get)) if walls else None
    return table


def main():
    cur = rows(sys.argv[1])
    prev = rows(sys.argv[2]) if len(sys.argv) > 2 else {}
    print(json.dumps(cur, indent=1))
    out = ["| repository | w | exit | wall s | hazards (by kind) | files re-run | proven / tests | proven % | vs previous point |",
           "|---|---|---|---|---|---|---|---|---|"]
    stops = []
    for repo, d in cur.items():
        best = d.get("best_workers")
        for w, v in d.get("par", {}).items():
            kinds = ", ".join(f"{k} {n}" for k, n in sorted(v.get("hazard_kinds", {}).items())) or "-"
            delta = ""
            p = (prev.get(repo) or {}).get("par", {}).get(w)
            if p and p.get("wall_s") and v.get("wall_s") is not None:
                dw = 100.0 * (v["wall_s"] - p["wall_s"]) / p["wall_s"]
                dp = (v.get("proven_share") or 0) - (p.get("proven_share") or 0) if v.get("proven_share") is not None and p.get("proven_share") is not None else None
                delta = f"wall {dw:+.1f} %" + (f", proven {dp:+.1f} pp" if dp is not None else "")
            if w == best and p:
                pb = (prev.get(repo) or {}).get("best_workers")
                pp = (prev.get(repo) or {}).get("par", {}).get(pb) if pb else None
                if pp and pp.get("wall_s"):
                    dw = 100.0 * (v["wall_s"] - pp["wall_s"]) / pp["wall_s"]
                    if dw > 25.0:
                        stops.append(f"{repo}: best-worker wall {pp['wall_s']} s (w{pb}) -> {v['wall_s']} s (w{w}), {dw:+.1f} %")
            if p and v.get("proven_share") is not None and p.get("proven_share") is not None and p["proven_share"] - v["proven_share"] > 25.0:
                stops.append(f"{repo} w{w}: proven share {p['proven_share']} % -> {v['proven_share']} %")
            out.append(f"| {repo} | {w}{' (best)' if w == best else ''} | {v.get('exit')} | {v.get('wall_s')}{' NOISY' if v.get('noisy') else ''} | "
                       f"{v.get('hazards')} ({kinds}) | {v.get('rerun_files')} | {v.get('proven')} / {v.get('verify_tests')} | {v.get('proven_share')} | {delta} |")
    out.append("")
    out.append("STOP RULE: " + ("; ".join(stops) if stops else "not triggered" if prev else "no previous point"))
    print("\n".join(out), file=sys.stderr)


if __name__ == "__main__":
    main()
