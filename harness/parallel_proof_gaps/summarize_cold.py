#!/usr/bin/env python3
"""Step M of spec parallel-proof-gaps: cold rounds, each its own measurement point (founder decision 2026-11-26,
alakajam A, step 2: a fresh engine state per round, fresh dirs).

    summarize_cold.py BEFORE_DIR ROUND_DIR [ROUND_DIR ...]   -> Markdown on stdout

Per repository and worker count: speed ratio = parallel wall / serial wall of the same round (misura A), for each
cold round and their mean, against the same ratio at before. STOP RULE: the mean cold ratio more than 25 % worse
than before (each round's change is shown too), or a round's proven share down by more than 25 percentage points.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from summarize import rows  # noqa: E402


def ratio(t, repo, w):
    d = t.get(repo) or {}
    s = (d.get("serial") or {}).get("wall_s")
    p = (d.get("par", {}).get(w) or {}).get("wall_s")
    return (p / s if p and s else None), p, s


def main():
    before = rows(sys.argv[1])
    rounds = [rows(d) for d in sys.argv[2:]]
    repos = sorted({r for t in rounds for r in t})
    out = ["| repository | w | ratio before (par s / serial s) | cold rounds: ratio (par s / serial s) | mean ratio | change | hazards per round | re-run complete per round | proven % per round (before) |",
           "|---|---|---|---|---|---|---|---|---|"]
    stops = []
    f = lambda z: f"{z:.3f}" if z is not None else "-"
    for repo in repos:
        for w in sorted({w for t in rounds for w in (t.get(repo) or {}).get("par", {})}, key=int):
            rb, pb, sb = ratio(before, repo, w)
            rr = [ratio(t, repo, w) for t in rounds]
            vals = [x[0] for x in rr if x[0] is not None]
            m = sum(vals) / len(vals) if vals else None
            ch = 100.0 * (m - rb) / rb if m is not None and rb else None
            per = [((t.get(repo) or {}).get("par", {}).get(w) or {}) for t in rounds]
            bp = ((before.get(repo) or {}).get("par", {}).get(w) or {}).get("proven_share")
            for x in per:
                if bp is not None and x.get("proven_share") is not None and bp - x["proven_share"] > 25.0:
                    stops.append(f"{repo} w{w}: proven share {bp} % -> {x['proven_share']} %")
            if ch is not None and ch > 25.0:
                stops.append(f"{repo} w{w}: mean cold ratio {rb:.3f} -> {m:.3f} ({ch:+.1f} %; rounds {', '.join(f(x[0]) for x in rr)})")
            out.append(f"| {repo} | {w} | {f(rb)} ({pb} / {sb}) | {'; '.join(f'{f(x[0])} ({x[1]} / {x[2]})' for x in rr)} | {f(m)} | "
                       f"{f'{ch:+.1f} %' if ch is not None else '-'} | {' / '.join(str(x.get('hazards')) for x in per)} | "
                       f"{' / '.join(str(x.get('rerun_complete')) for x in per)} | {' / '.join(str(x.get('proven_share')) for x in per)} ({bp}) |")
    out.append("")
    out.append("STOP RULE (mean cold ratio vs before, misura A): " + ("; ".join(stops) if stops else "not triggered"))
    print("\n".join(out))


if __name__ == "__main__":
    main()
