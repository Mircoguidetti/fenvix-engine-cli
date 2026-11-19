"""Reused share on ordinary commits: review R-020b's walks (before = 96f4bd1, no prefix rule; after = 9019c6d, prefix
rule) and this report's walks (r3 = the R-020b fixes, which add existence checks to the default cache).
Same method as sessions/2026-11-19-review-dep-verdict/o1-walks/cmp.py: per transition, test time of reused results
/ test time of all tests, over the transitions every walk completed."""
import gzip
import json
import os
import statistics as S
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REV = os.path.join(HERE, "..", "..", "2026-11-19-review-dep-verdict", "o1-walks")
for p in ("click", "pygments"):
    rows = {}
    for v, path in (("before", f"{REV}/{p}-before.json.gz"), ("after", f"{REV}/{p}-after.json.gz"),
                    ("r3", f"{HERE}/walks/{p}-r3.json.gz")):
        try:
            d = json.load(gzip.open(path))
        except Exception as e:
            print(p, v, "missing", e)
            continue
        rows[v] = {s["i"]: s for s in d["steps"] if s.get("status") == "ok"}
    common = sorted(set.intersection(*(set(r) for r in rows.values())) - {0})
    print(f"{p}: transitions {len(common)}")
    for v, r in rows.items():
        sh = [(r[i].get("time_reused") or 0) / (r[i].get("time_total") or 1) for i in common]
        pooled = sum(r[i].get("time_reused") or 0 for i in common) / sum(r[i].get("time_total") or 0 for i in common)
        chk = sum(r[i]["verify"]["checked"] for i in common)
        wrong = sum(1 for i in common for m in r[i]["verify"]["mismatches"] if m.get("verdict") == "wrong")
        nc = {}
        for i in common:
            for k, n in (r[i]["A"].get("not_cached") or {}).items():
                nc[k] = nc.get(k, 0) + n
        wa = S.median(r[i]["A"]["wall"] for i in common)
        wb = S.median(r[i]["B"]["wall"] for i in common)
        print(f"  {v:6s} mean {100 * S.mean(sh):.1f}% pooled {100 * pooled:.1f}% commits>=5% "
              f"{sum(x >= 0.05 for x in sh)}; verified {chk} wrong {wrong}; wall A/B {wa:.1f}/{wb:.1f}s; "
              f"not cached (sum) { {k: v_ for k, v_ in sorted(nc.items()) if k != 'outcome'} }")
