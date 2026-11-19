import gzip, json, sys
from collections import Counter
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
co, cn = Counter(), Counter()
for sha, (name, p) in new.items():
    if sha not in old or p.get("status") != "ok": continue
    for src, c in ((old[sha][1], co), (p, cn)):
        for u, x in (src.get("per_unit") or {}).items():
            for k, v in (((x.get("D0") or {}).get("cache") or {}).get("not_cached_detail") or {}).items():
                key = k.split(":")[0][:70]
                c[(name, key)] += v
keys = sorted(set(co) | set(cn), key=lambda k: -(cn[k] - co[k]))
for k in keys:
    if cn[k] != co[k]: print(f"{k[0]:18} {co[k]:5} -> {cn[k]:5}  {k[1]}")
