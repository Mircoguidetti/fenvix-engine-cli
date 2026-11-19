import gzip, json, sys, re
from collections import Counter, defaultdict
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
lost, gained = Counter(), Counter()
lost_t, gained_t = defaultdict(float), defaultdict(float)
def cat(why):
    if why.startswith("after an earlier test"): return "refused: an earlier test of the process was refused (prefix rule)"
    if "/dist-identity/l/" in why: return "listing of a site directory (H2)"
    if "/dist-identity/@pth" in why: return ".pth files (H3)"
    if "/dist-identity/" in why: return "distribution identity: " + why.split("/dist-identity/")[1].split(" ")[0][:40]
    k = why.split(":", 1)[0]
    return k + ((": " + why.split(":",1)[1].strip()[:60]) if k in ("data", "env", "code") else "")
for sha, (name, p) in new.items():
    if sha not in old or p.get("status") != "ok": continue
    o = old[sha][1]
    for u, x in (p.get("per_unit") or {}).items():
        ou = (o.get("per_unit") or {}).get(u) or {}
        was, now = set(ou.get("D1_reused", ())), set(x.get("D1_reused", ()))
        times = x.get("times") or {}
        for n in was - now:
            if n not in (x.get("fresh") or {}): continue
            why = (x.get("D1_miss") or {}).get(n, "?")
            if why.startswith("new"):
                nc = "new (not recorded at P)"
                why = nc
            c = cat(why); lost[(name, c)] += 1; lost_t[(name, c)] += times.get(n, 0)
        for n in now - was:
            ow = (ou.get("D1_miss") or {}).get(n, "?")
            c = cat(ow); gained[(name, c)] += 1; gained_t[(name, c)] += times.get(n, 0)
print("LOST (reused in the first report, rerun now):")
for k, v in sorted(lost.items(), key=lambda kv: -kv[1]): print(f"  {v:5} tests {lost_t[k]:8.1f}s  {k[0]:18} {k[1]}")
print("GAINED (rerun in the first report, reused now; reason it missed then):")
for k, v in sorted(gained.items(), key=lambda kv: -kv[1]): print(f"  {v:5} tests {gained_t[k]:8.1f}s  {k[0]:18} {k[1]}")
