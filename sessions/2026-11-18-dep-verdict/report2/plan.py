import gzip, json, sys
from collections import defaultdict
from pathlib import Path
base = Path(sys.argv[1])
commits = json.loads((base / "commits.json").read_text())
runs = defaultdict(list)
for sub in ("dv1", "dv3", "local"):
    for f in sorted((base / "results" / sub).glob("*.json.gz")):
        r = json.load(gzip.open(f)); r["_f"] = f"{sub}/{f.name}"
        runs[r["spec"]["name"]].append(r)
plan = {}
tot = defaultdict(float)
for name, rs in sorted(runs.items()):
    best = {}
    for r in rs:
        for p in r["pairs"]:
            if p["sha"] not in best or (best[p["sha"]][0].get("status") != "ok" and p.get("status") == "ok"):
                best[p["sha"]] = (p, r["_f"], r.get("cpus"))
    repo = rs[0]["spec"].get("repo", name)
    for i, c in enumerate(commits[repo]["dep_commits"]):
        b = best.get(c["sha"])
        if not b or b[0].get("status") != "ok": continue
        p, f, cpus = b
        T = sum(sum((u.get("times") or {}).values()) for u in (p.get("per_unit") or {}).values())
        if T <= 0: continue
        plan.setdefault(name, []).append({"index": i, "sha": c["sha"], "units": p["units"], "src": f, "elapsed": p.get("elapsed"), "cpus": cpus})
        tot[name] += p.get("elapsed") or 0
n = 0
for k, v in plan.items():
    n += len(v)
    print(k, len(v), "elapsed h %.1f" % (tot[k] / 3600), sorted({x["src"] for x in v}), "units/pair", sum(len(x["units"]) for x in v) / len(v))
print(n, "total h %.1f" % (sum(tot.values()) / 3600))
json.dump(plan, open(sys.argv[2], "w"), indent=1)
