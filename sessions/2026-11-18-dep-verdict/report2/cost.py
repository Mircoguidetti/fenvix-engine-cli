import gzip, json, sys, statistics as S
from pathlib import Path
def load(paths):
    best = {}
    for f in paths:
        r = json.load(gzip.open(f))
        for p in r["pairs"]:
            if p["sha"] not in best or (best[p["sha"]][1].get("status") != "ok" and p.get("status") == "ok"): best[p["sha"]] = (r["spec"]["name"], p)
    return best
old = load([f for sub in ("dv1","dv3","local") for f in sorted(Path("/tmp/claude-0/cut/harness/dep_verdict/results", sub).glob("*.json.gz"))])
new = load(sorted(Path(sys.argv[1]).glob("results/*/*.json.gz")))
def col(src, mode, key, sub=None):
    out = []
    for sha, (name, p) in src.items():
        if sha not in new or sha not in old or p.get("status") != "ok": continue
        for u, x in (p.get("per_unit") or {}).items():
            c = ((x.get(mode) or {}).get("cache") or {})
            v = c.get(key) if sub is None else (c.get(key) or {}).get(sub)
            if isinstance(v, (int, float)): out.append(v)
    return out
for label, mode, key, sub in (("record s per process (D0)", "D0", "record_seconds", None), ("check s per process (D1)", "D1", "check_seconds", None),
                              ("identity keys per test, mean per process (D0)", "D0", "dists", "recorded_keys_mean"), ("index s (D0)", "D0", "dists", "index_seconds")):
    o, n = col(old, mode, key, sub), col(new, mode, key, sub)
    q = lambda xs: (round(S.median(xs), 3), round(sorted(xs)[int(0.9*len(xs))-1], 3)) if xs else None
    print(f"{label:48} old median/p90 {q(o)}  new {q(n)}  (n {len(o)}/{len(n)})")
