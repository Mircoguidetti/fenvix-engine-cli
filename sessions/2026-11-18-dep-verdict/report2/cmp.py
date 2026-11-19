import gzip, json, sys
from pathlib import Path
from collections import defaultdict
old_base = Path("/tmp/claude-0/cut/harness/dep_verdict/results")
def load(paths):
    best = {}
    for f in paths:
        try: r = json.load(gzip.open(f))
        except Exception: continue
        for p in r["pairs"]:
            if p["sha"] not in best or (best[p["sha"]][1].get("status") != "ok" and p.get("status") == "ok"): best[p["sha"]] = (r["spec"]["name"], p)
    return best
old = load([f for sub in ("dv1","dv3","local") for f in sorted((old_base/sub).glob("*.json.gz"))])
new = load([Path(x) for x in sys.argv[1:]])
def share(p, key):
    T = R = 0.0; wrong = 0; chk = 0
    for u in (p.get("per_unit") or {}).values():
        fresh, times = u.get("fresh") or {}, u.get("times") or {}
        re_ = set(u.get(key) or ())
        mm = {(m["mode"], m["nodeid"]): m["verdict"] for m in u.get("mismatches") or []}
        for n in fresh:
            t = times.get(n, 0.0); T += t
            if n in re_: R += t; chk += 1; wrong += mm.get((key[:2], n)) == "wrong"
    return (100*R/T if T else float("nan")), chk, wrong
for sha, (name, p) in new.items():
    if p.get("status") != "ok": print(name, sha[:10], p.get("status")); continue
    o = old.get(sha, (None, {}))[1]
    d1, c1, w1 = share(p, "D1_reused"); d0, c0, w0 = share(o, "D1_reused") if o else (float("nan"), 0, 0)
    print(f"{name:18} {sha[:10]} D new {d1:5.1f}% ({c1} reuses, {w1} wrong)  old {d0:5.1f}% ({c0})")
