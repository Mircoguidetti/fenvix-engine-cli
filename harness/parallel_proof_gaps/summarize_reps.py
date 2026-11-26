#!/usr/bin/env python3
"""Step M of spec parallel-proof-gaps: a point measured with several rounds (REPS=N), judged by the mean.

    summarize_reps.py OUT_DIR OUT_DIR_PREVIOUS   -> JSON on stdout, Markdown table + STOP RULE line on stderr

Founder decision D2 = A (2026-11-26): the stop rule judges the mean of the rounds per repository and worker count,
against the previous point (before, one round). Best worker count = the lowest mean parallel wall time. Stop rule:
best-worker mean wall time up by more than 25 % against the previous point's best-worker wall time, or mean proven
share down by more than 25 percentage points at a worker count. The table gives each round's numbers as well.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from summarize import rows  # noqa: E402


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def main():
    out_dir, prev_dir = sys.argv[1], sys.argv[2]
    reps = sorted({json.loads(l)["rep"] for l in open(os.path.join(out_dir, "results.jsonl")) if l.strip()})
    per_rep = {r: rows(out_dir, r) for r in reps}
    prev = rows(prev_dir)
    cur = {}
    for repo in sorted({k for t in per_rep.values() for k in t}):
        ws = sorted({w for t in per_rep.values() for w in (t.get(repo) or {}).get("par", {})})
        d = {"par": {}}
        for w in ws:
            rr = [(per_rep[r].get(repo) or {}).get("par", {}).get(w) or {} for r in reps]
            d["par"][w] = {"rounds": rr, "wall_s": mean([x.get("wall_s") for x in rr]),
                           "proven_share": mean([x.get("proven_share") for x in rr])}
        walls = {w: v["wall_s"] for w, v in d["par"].items() if v["wall_s"] is not None}
        d["best_workers"] = min(walls, key=walls.get) if walls else None
        cur[repo] = d
    print(json.dumps(cur, indent=1))
    out = ["| repository | w | mean wall s | wall s per round | hazards per round | files re-run per round | mean proven % | vs before |",
           "|---|---|---|---|---|---|---|---|"]
    stops = []
    for repo, d in cur.items():
        best = d["best_workers"]
        pr = prev.get(repo) or {}
        for w, v in d["par"].items():
            rr = v["rounds"]
            p = pr.get("par", {}).get(w)
            delta = ""
            if p and p.get("wall_s") and v["wall_s"] is not None:
                delta = f"wall {100.0 * (v['wall_s'] - p['wall_s']) / p['wall_s']:+.1f} %"
                if p.get("proven_share") is not None and v["proven_share"] is not None:
                    dp = v["proven_share"] - p["proven_share"]
                    delta += f", proven {dp:+.1f} pp"
                    if dp < -25.0:
                        stops.append(f"{repo} w{w}: mean proven share {p['proven_share']} % -> {v['proven_share']} %")
            if w == best:
                pb = pr.get("best_workers")
                pp = pr.get("par", {}).get(pb) if pb else None
                if pp and pp.get("wall_s"):
                    dw = 100.0 * (v["wall_s"] - pp["wall_s"]) / pp["wall_s"]
                    delta += f"; best vs best {dw:+.1f} %"
                    if dw > 25.0:
                        stops.append(f"{repo}: best-worker wall {pp['wall_s']} s (w{pb}) -> mean {v['wall_s']} s (w{w}; rounds "
                                     f"{', '.join(str(x.get('wall_s')) for x in rr)}), {dw:+.1f} %")
            out.append(f"| {repo} | {w}{' (best)' if w == best else ''} | {v['wall_s']} | {' / '.join(str(x.get('wall_s')) for x in rr)} | "
                       f"{' / '.join(str(x.get('hazards')) for x in rr)} | {' / '.join(str(x.get('rerun_files')) for x in rr)} | "
                       f"{v['proven_share']} | {delta} |")
    out.append("")
    out.append("STOP RULE (mean of rounds vs before): " + ("; ".join(stops) if stops else "not triggered"))
    print("\n".join(out), file=sys.stderr)


if __name__ == "__main__":
    main()
