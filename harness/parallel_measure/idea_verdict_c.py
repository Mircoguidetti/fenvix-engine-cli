#!/usr/bin/env python3
"""Session C: the founder's 'idea verdict' per repository from existing raw data (coordinator, 2026-11-22); no runs.

  (a) the repository's own parallel mode, no engine (kind plain_par), best of workers 2/4 by median, is >= 2x faster
      than its plain serial median (kind plain)
  (b) at least one THEIRS test in classification.json (reproduced without the engine, not ENV)
  idea verdict = yes when (a) and (b). Engine defects (OURS / UNDECIDED) do not enter.

Usage: idea_verdict_c.py results.jsonl   (classification.json read from <dir of results>/<repo>/)
"""
import json, os, statistics, sys

rows = [json.loads(x) for x in open(sys.argv[1]) if x.strip()]
base = os.path.dirname(os.path.abspath(sys.argv[1]))
repos = list(dict.fromkeys(r["repo"] for r in rows))
print("| repo | plain serial median s | own parallel best median s (workers) | (a) ratio, >= 2x | THEIRS (b) | idea verdict |")
print("|---|---|---|---|---|---|")
for n in repos:
    ok = lambda k, w=None: [r["wall_s"] for r in rows if r["repo"] == n and r["kind"] == k and r["exit"] != 124
                             and not r.get("invalid") and (w is None or r["workers"] == w)]
    ps = ok("plain")
    par = {w: statistics.median(ok("plain_par", w)) for w in (2, 4) if ok("plain_par", w)}
    if not ps or not par:
        print(f"| {n} | - | - | UNKNOWN (no plain/plain_par rows) | - | UNKNOWN |")
        continue
    s = statistics.median(ps)
    w, p = min(par.items(), key=lambda kv: kv[1])
    a = s / p >= 2.0
    try:
        th = json.load(open(os.path.join(base, n, "classification.json")))["summary"]["boxes"].get("THEIRS", 0)
        b = th > 0
        bt = f"{th} ({'yes' if b else 'no'})"
    except (OSError, ValueError, KeyError):
        b, bt = None, "not classified"
    v = "yes" if (a and b) else ("no" if (not a or b is False) else "UNKNOWN")
    print(f"| {n} | {s:.2f} | {p:.2f} (w{w}) | {s / p:.2f}x ({'yes' if a else 'no'}) | {bt} | {v} |")
