"""Final table of the l1-threads-fix rounds: per suite, calm and seed slowdown vs --det,
broken tests and broken runs, hangs. Usage: RESULTS_DIR ROUNDS(comma, later wins) [OUT_JSON]."""
import json, glob, statistics, sys
base = sys.argv[1]  # results dir
rounds = sys.argv[2].split(",")  # later rounds override earlier ones per suite
S = {}
for rd in rounds:
    for f in glob.glob(f"{base}/{rd}/*.suite.json"):
        r = json.load(open(f)); r["_round"] = rd; S[r["name"]] = r
heavy = ["anyio", "more-itertools", "networkx", "structlog", "requests"]
rows = []
tot = {"l1": 0}
for name in sorted(S):
    r = S[name]
    if r.get("status") != "ok":
        print(name, r.get("status")); continue
    by = {}
    for t in r["timing"]:
        by.setdefault(t["mode"], []).append(t)
    med = lambda m: statistics.median([t["duration_s"] for t in by.get(m, []) if not t["timed_out"]]) if any(not t["timed_out"] for t in by.get(m, [])) else None
    d, l = med("det"), med("l1")
    seeds = r.get("suite_seeds", [1])
    st = [t["stats"] for t in by.get("l1", []) if t.get("stats")]
    row = dict(name=name, round=r["_round"], runs=len(by.get("l1", [])), plain=med("plain"), det=d, l1=l,
               l1_vs_det=round(100*(l/d-1), 1) if d and l else None,
               broken_det=r["broken_by_det"].get("n_broken", 0),
               broken_l1=r["broken_by_l1"].get("n_broken", 0), some_l1=r["broken_by_l1"].get("n_sometimes", 0),
               seeds=seeds,
               broken_seeds={s: r.get(f"broken_by_l1_s{s}", {}).get("n_broken", 0) for s in seeds},
               some_seeds={s: r.get(f"broken_by_l1_s{s}", {}).get("n_sometimes", 0) for s in seeds},
               seed_vs_det={s: (round(100*(med(f"l1-s{s}")/d-1), 1) if d and med(f"l1-s{s}") else None) for s in seeds},
               hung={m: sum(t["timed_out"] for t in v) for m, v in by.items() if any(t["timed_out"] for t in v)},
               nruns={m: len(v) for m, v in by.items()},
               managed=max((s["managed"] for s in st), default=None), escapes=max((s["escapes"] for s in st), default=None),
               deadlocks=max((s["deadlocks"] for s in st), default=None),
               broken_runs={k[len("broken_by_"):]: r[k].get("n_broken_runs") for k in r if k.startswith("broken_by_")})
    rows.append(row)
json.dump(rows, open(sys.argv[3] if len(sys.argv) > 3 else "final-table.json", "w"), indent=1)
for r in rows:
    print(r["name"], r["round"], r["runs"], r["det"], r["l1"], r["l1_vs_det"], "brk", r["broken_det"], r["broken_l1"], r["some_l1"], r["broken_seeds"], r["some_seeds"], "hung", r["hung"], r["managed"], r["escapes"], r["deadlocks"], r["seed_vs_det"], "broken runs", r["broken_runs"])
h = [r for r in rows if r["name"] in heavy]
v = [r["l1_vs_det"] for r in h if r["l1_vs_det"] is not None]
print("heavy:", [(r["name"], r["l1_vs_det"], r["managed"]) for r in h], "median", statistics.median(v) if v else None, "worst", max(v) if v else None)
# One value per suite (review R-007 FIX 2: pooling counted anyio and requests 3 times
# each): the median over that suite's seeds.
sv = [statistics.median(xs) for r in h if (xs := [x for x in r["seed_vs_det"].values() if x is not None])]
print("heavy seeds (one value per suite):", [(r["name"], r["seed_vs_det"]) for r in h],
      "median", statistics.median(sv) if sv else None, "worst", max(sv) if sv else None)
print("by managed:", sorted([(r["managed"] or 0, r["name"]) for r in rows], reverse=True)[:7])
