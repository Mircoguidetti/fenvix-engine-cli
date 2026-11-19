import json, sys, statistics as S
import gzip, os
W = os.path.dirname(os.path.abspath(__file__))
for p in ("click", "pygments"):
    rows = {}
    for v in ("before", "after"):
        try:
            d = json.load(gzip.open(f"{W}/{p}-{v}.json.gz"))
        except Exception as e:
            print(p, v, "missing", e); continue
        rows[v] = {s["i"]: s for s in d["steps"] if s.get("status") == "ok"}
    if len(rows) < 2: continue
    common = sorted(set(rows["before"]) & set(rows["after"]) - {0})
    sh = {v: [] for v in rows}
    chk = {v: [0, 0] for v in rows}
    lost = []
    for i in common:
        for v in rows:
            s = rows[v][i]
            sh[v].append((s.get("time_reused") or 0) / (s.get("time_total") or 1))
            chk[v][0] += s["verify"]["checked"]
            chk[v][1] += sum(1 for m in s["verify"]["mismatches"] if m.get("verdict") == "wrong")
        b, a = sh["before"][-1], sh["after"][-1]
        if b - a > 0.05:
            lost.append((i, rows["after"][i]["sha"][:10], round(100 * b), round(100 * a),
                         rows["after"][i]["A"].get("miss_reasons")))
    tb = sum(rows["before"][i]["time_total"] or 0 for i in common)
    pooled = {v: sum(rows[v][i].get("time_reused") or 0 for i in common) / sum(rows[v][i].get("time_total") or 0 for i in common) for v in rows}
    print(f"{p}: transitions {len(common)}")
    for v in ("before", "after"):
        print(f"  {v}: mean {100*S.mean(sh[v]):.1f}% median {100*S.median(sh[v]):.1f}% pooled {100*pooled[v]:.1f}%  "
              f"commits >=5% reused {sum(x >= 0.05 for x in sh[v])}; verified {chk[v][0]} wrong {chk[v][1]}")
    print("  commits losing >5 points:", len(lost))
    for l in lost: print("   ", l)
print()
for p in ("click", "pygments"):
    for v in ("before", "after"):
        try: d = json.load(gzip.open(f"{W}/{p}-{v}.json.gz"))
        except Exception: continue
        st = [s for s in d["steps"] if s.get("status") == "ok"]
        nc = [ (s["A"].get("not_cached") or {}).get("after an earlier test or fixture of this process", 0) for s in st]
        nt = [s.get("n_tests") or 0 for s in st]
        aw = [s["A"]["wall"] for s in st]; bw = [s["B"]["wall"] for s in st]
        print(f"{p} {v}: steps {len(st)}; tests refused by the prefix rule per commit: median {S.median(nc)} of {S.median(nt)}; A/B wall median {S.median(aw):.1f}/{S.median(bw):.1f}s")
