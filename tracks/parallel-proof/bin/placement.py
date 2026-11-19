"""Three-way fingerprint analysis: serial noise, parallel noise, placement.

usage: placement.py OUTDIR [serA serB parA parB]
  serial traces: OUTDIR/<serA>.jsonl, OUTDIR/<serB>.jsonl; parallel per-worker traces OUTDIR/<parX>.gw*.jsonl and
  OUTDIR/<parX>.gw*.ran.json (written by the xd_pertrace shim)."""
import collections, glob, json, os, sys

def load(pattern):
    recs = {}
    for f in sorted(glob.glob(pattern)):
        if f.endswith(".ran.json"):
            continue
        for line in open(f):
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") == "test":
                recs[o["nodeid"]] = o
    return recs

def placement_of(prefix):
    where = {}
    for f in sorted(glob.glob(prefix + ".gw*.ran.json")):
        d = json.load(open(f))
        for i, n in enumerate(d["ran"]):
            where[n] = (d["worker"], i)
    return where

def first(a, b):
    for x, y in zip(a.get("events", []), b.get("events", [])):
        if x != y:
            return x.get("s", "?")
    return "count" if a["n_events"] != b["n_events"] else "beyond-stored"

o = sys.argv[1]
sa, sb, pa, pb = (sys.argv[2:6] if len(sys.argv) >= 6 else ("ser-a", "ser-b", "n4-a", "n4-b"))
SA, SB = load(f"{o}/{sa}.jsonl"), load(f"{o}/{sb}.jsonl")
PA, PB = load(f"{o}/{pa}.gw*.jsonl"), load(f"{o}/{pb}.gw*.jsonl")
WA, WB = placement_of(f"{o}/{pa}"), placement_of(f"{o}/{pb}")
ids = sorted(set(SA) & set(SB) & set(PA) & set(PB))
d = lambda X, Y, n: X[n]["fingerprint"] != Y[n]["fingerprint"]
ser_noise = {n for n in ids if d(SA, SB, n)}
par_noise = {n for n in ids if d(PA, PB, n)}
sp = {n for n in ids if d(SA, PA, n) or d(SA, PB, n)}
placement = sp - ser_noise
stable_placement = {n for n in placement if d(SA, PA, n) and d(SA, PB, n) and d(SB, PA, n) and d(SB, PB, n)}
moved = {n for n in ids if WA.get(n, (None,))[0] != WB.get(n, (None,))[0]}
out = {
    "tests": len(ids),
    "serial_noise (serA != serB)": len(ser_noise),
    "serial_noise_first_event": dict(collections.Counter(first(SA[n], SB[n]) for n in ser_noise)),
    "parallel_noise (parA != parB)": len(par_noise),
    "serial_vs_parallel_differs (either parallel run)": len(sp),
    "placement (differs from serial, serial runs agree)": len(placement),
    "placement_in_both_parallel_runs": len(stable_placement),
    "placement_first_event": dict(collections.Counter(first(SA[n], PA[n] if d(SA, PA, n) else PB[n]) for n in placement)),
    "placement_outcome_flips": [(n, SA[n]["outcome"], PA[n]["outcome"], PB[n]["outcome"]) for n in placement
                                if len({SA[n]["outcome"], PA[n]["outcome"], PB[n]["outcome"]}) > 1],
    "placement_top_files": collections.Counter(n.split("::")[0] for n in placement).most_common(10),
    "tests_on_another_worker_between_parallel_runs": len(moved),
    "workers_A": dict(collections.Counter(w for w, _ in WA.values())),
    "workers_B": dict(collections.Counter(w for w, _ in WB.values())),
    "outcomes_differ_serial_vs_parallel": [(n, SA[n]["outcome"], PA[n]["outcome"]) for n in ids
                                           if SA[n]["outcome"] != PA[n]["outcome"]][:20],
    "placement_examples": sorted(placement)[:15],
}
print(json.dumps(out, indent=1))
