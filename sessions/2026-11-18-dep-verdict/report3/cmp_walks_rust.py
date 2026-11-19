"""Reused share on ordinary commits on the Rust engine: claude/parallel-proof-3 bac3317 ("bac") against this branch
("new": prefix rule, importable digest, compaction, A1-A4), plus the review's pre-Rust walks for reference (before
the prefix rule 96f4bd1, after it 9019c6d). Same method as the review's cmp.py: per transition, test time of reused
results / test time of all tests, over the transitions every walk completed."""
import gzip
import json
import os
import statistics as S

HERE = os.path.dirname(os.path.abspath(__file__))
REV = os.path.join(HERE, "..", "..", "2026-11-19-review-dep-verdict", "o1-walks")
for p in ("click", "pygments"):
    rows = {}
    for v, path in (("96f4bd1", f"{REV}/{p}-before.json.gz"), ("9019c6d", f"{REV}/{p}-after.json.gz"),
                    ("bac3317", f"{HERE}/walks-rust/{p}-bac.json.gz"), ("new", f"{HERE}/walks-rust/{p}-new.json.gz")):
        if os.path.exists(path):
            rows[v] = {s["i"]: s for s in json.load(gzip.open(path))["steps"] if s.get("status") == "ok"}
    common = sorted(set.intersection(*(set(r) for r in rows.values())) - {0})
    print(f"{p}: transitions {len(common)}")
    for v, r in rows.items():
        sh = [(r[i].get("time_reused") or 0) / (r[i].get("time_total") or 1) for i in common]
        pooled = sum(r[i].get("time_reused") or 0 for i in common) / sum(r[i].get("time_total") or 0 for i in common)
        chk = sum(r[i]["verify"]["checked"] for i in common)
        wrong = sum(1 for i in common for m in r[i]["verify"]["mismatches"] if m.get("verdict") == "wrong")
        m = lambda k: S.median(r[i]["A"].get(k) or 0 for i in common)  # noqa: E731
        print(f"  {v:8s} mean {100 * S.mean(sh):.1f}% pooled {100 * pooled:.1f}% commits>=5% "
              f"{sum(x >= 0.05 for x in sh)}; verified {chk} wrong {wrong}; median A wall {m('wall'):.1f}s "
              f"(B {S.median(r[i]['B']['wall'] for i in common):.1f}s), record {m('record_seconds'):.2f}s, "
              f"check {m('check_seconds'):.2f}s")
    if "bac3317" in rows and "new" in rows:
        for i in common:
            a, b = rows["bac3317"][i], rows["new"][i]
            x = (a["time_reused"] or 0) / (a["time_total"] or 1)
            y = (b["time_reused"] or 0) / (b["time_total"] or 1)
            if abs(x - y) > 0.05:
                print(f"    {i} {b['sha'][:10]} bac {100 * x:.0f}% new {100 * y:.0f}% miss {b['A'].get('miss_reasons')}")
