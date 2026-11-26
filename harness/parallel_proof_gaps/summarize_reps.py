#!/usr/bin/env python3
"""Step M of spec parallel-proof-gaps: a point measured with several rounds (REPS=N), judged by the mean.

    summarize_reps.py OUT_DIR OUT_DIR_PREVIOUS   -> JSON on stdout, Markdown table + STOP RULE line on stderr

Founder decision on reading this re-measure (2026-11-26, "misura A"; it replaces the mean reading of D2 = A): per
repository and worker count, speed ratio = parallel wall / serial wall of the same round. STOP RULE: the round-1
(cold) ratio more than 25 % worse (higher) than the same ratio at the previous point (before), or the round-1 proven
share down by more than 25 percentage points. Round 2 is warm (measure.py keeps the engine state between rounds: learned
costs and together-groups), so its ratios, the raw walls and the means are information only (second table and the
"information" line: the mean-wall rule as first decided).
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
    out.append("information only, mean wall rule (D2 = A as first decided): " + ("; ".join(stops) if stops else "not triggered"))
    out.append("")
    out.append("| repository | w | ratio before (par / serial) | ratio round 1 (cold) | change | ratio round 2 (warm, info) | round 1 proven % | before proven % |")
    out.append("|---|---|---|---|---|---|---|---|")
    rstops = []
    serial = {r: {repo: ((t.get(repo) or {}).get("serial") or {}).get("wall_s") for repo in t} for r, t in per_rep.items()}
    for repo, d in cur.items():
        pr = prev.get(repo) or {}
        ps = (pr.get("serial") or {}).get("wall_s")
        for w, v in d["par"].items():
            p = pr.get("par", {}).get(w) or {}
            rb = p.get("wall_s") / ps if p.get("wall_s") and ps else None
            rr = []
            for i, r in enumerate(reps):
                x = v["rounds"][i].get("wall_s"); sw = serial[r].get(repo)
                rr.append(x / sw if x and sw else None)
            ch = 100.0 * (rr[0] - rb) / rb if rr and rr[0] is not None and rb else None
            if ch is not None and ch > 25.0:
                rstops.append(f"{repo} w{w}: ratio {rb:.3f} -> {rr[0]:.3f} ({ch:+.1f} %)")
            p1 = v["rounds"][0].get("proven_share")
            if p1 is not None and p.get("proven_share") is not None and p["proven_share"] - p1 > 25.0:
                rstops.append(f"{repo} w{w}: round-1 proven share {p['proven_share']} % -> {p1} %")
            f = lambda z: f"{z:.3f}" if z is not None else "-"
            out.append(f"| {repo} | {w} | {f(rb)} | {f(rr[0] if rr else None)} | {f'{ch:+.1f} %' if ch is not None else '-'} | "
                       f"{' / '.join(f(z) for z in rr[1:]) or '-'} | {p1} | {p.get('proven_share')} |")
    out.append("")
    out.append("STOP RULE (round-1 speed ratio vs before, misura A): " + ("; ".join(rstops) if rstops else "not triggered"))
    print("\n".join(out), file=sys.stderr)


if __name__ == "__main__":
    main()
