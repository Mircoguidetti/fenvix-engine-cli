#!/usr/bin/env python3
"""Review R-020: re-derive the verdict table of the dependency-update report from the committed pair rows,
without importing harness/dep_verdict/analyze.py.

    git archive 0b87033 harness/dep_verdict | tar -x -C /tmp/cut      # the cutoff state the report used
    python3 rederive.py /tmp/cut/harness/dep_verdict
"""
import gzip
import json
import statistics as S
import sys
from collections import defaultdict
from pathlib import Path

OK = ("passed", "skipped", "xfailed")
base = Path(sys.argv[1])
commits = json.loads((base / "commits.json").read_text())
runs = defaultdict(list)
for sub in ("dv1", "dv3", "local"):
    for f in sorted((base / "results" / sub).glob("*.json.gz")):
        r = json.load(gzip.open(f))
        runs[r["spec"]["name"]].append(r)

rows = defaultdict(list)
broken = []
null_reuses = 0  # a rule that reuses every recorded result, whatever changed
informative = []  # recorded at P and outcome at C differs: the only reuses that could have been wrong
tot = defaultdict(int)
for name, rs in sorted(runs.items()):
    best = {}
    for r in rs:
        for p in r["pairs"]:
            if p["sha"] not in best or (best[p["sha"]].get("status") != "ok" and p.get("status") == "ok"):
                best[p["sha"]] = p
    repo = rs[0]["spec"].get("repo", name)
    for c in commits[repo]["dep_commits"]:
        p = best.get(c["sha"])
        if not p or p.get("status") != "ok":
            continue
        T = Dt = Tt = cache = 0.0
        dchk = dwrong = dflaky = 0
        for u in (p.get("per_unit") or {}).values():
            fresh, times = u.get("fresh") or {}, u.get("times") or {}
            if not fresh:
                continue
            dre, tre = set(u.get("D1_reused", ())), set(u.get("T1_reused", ()))
            mm = {(m["mode"], m["nodeid"]): m["verdict"] for m in u.get("mismatches") or []}
            for n in fresh:
                t = times.get(n, 0.0)
                T += t
                if n in dre:
                    Dt += t
                    dchk += 1
                    v = mm.get(("D1", n))
                    dwrong += v == "wrong"
                    dflaky += v is not None and v != "wrong"
                    cache += t
                else:
                    why = (u.get("D1_miss") or {}).get(n)
                    if why is not None and why.split(":", 1)[0] not in ("new", "failed-before"):
                        cache += t
                if n in tre:
                    Tt += t
                    tot["T_checked"] += 1
                    tot["T_wrong"] += mm.get(("T1", n)) == "wrong"
                po = (u.get("outcomes_P") or {}).get(n)
                why0 = (u.get("D1_miss") or {}).get(n) or ""
                recorded = n in dre or (why0 and why0.split(":", 1)[0] not in ("new", "failed-before"))
                null_reuses += bool(recorded)
                if recorded and po is not None and po != fresh[n]:
                    informative.append((name, p["sha"][:10], n, po, fresh[n], n in dre, why0[:90]))
                if po == "passed" and fresh[n] not in OK:
                    broken.append((name, p["sha"][:10], n, n in dre, (u.get("D1_miss") or {}).get(n)))
        if T <= 0:
            continue
        tfull = p.get("T_mode", "full") == "full"
        rows[name].append({"D": 100 * Dt / T, "T": 100 * Tt / T if tfull else 0.0, "time": T, "Dt": Dt,
                           "Tt": Tt if tfull else 0.0, "env": bool(p.get("env_changed")), "cache": 100 * cache / T,
                           "tfull": tfull})
        tot["D_checked"] += dchk
        tot["D_wrong"] += dwrong
        tot["D_flaky"] += dflaky

allr = [x for v in rows.values() for x in v]
m = lambda xs: S.mean(xs) if xs else float("nan")  # noqa: E731
print(f"{'repo':20} pairs env  D%   T%   D%env cache%")
for n, v in rows.items():
    print(f"{n:20} {len(v):5} {sum(x['env'] for x in v):3} {m([x['D'] for x in v]):4.0f} {m([x['T'] for x in v]):4.0f}"
          f" {m([x['D'] for x in v if x['env']]):5.0f} {m([x['cache'] for x in v]):5.0f}")
print("pairs", len(allr), "env-changed", sum(x["env"] for x in allr))
print("mean over pairs D %.1f T %.1f" % (m([x["D"] for x in allr]), m([x["T"] for x in allr])))
print("mean of repo means D %.1f T %.1f" % (m([m([x["D"] for x in v]) for v in rows.values()]),
                                            m([m([x["T"] for x in v]) for v in rows.values()])))
print("pooled D %.1f T %.1f" % (100 * sum(x["Dt"] for x in allr) / sum(x["time"] for x in allr),
                                100 * sum(x["Tt"] for x in allr) / sum(x["time"] for x in allr)))
e, ne = [x for x in allr if x["env"]], [x for x in allr if not x["env"]]
print("env changed: n %d D %.1f T %.1f | unchanged: n %d D %.1f T %.1f" % (
    len(e), m([x["D"] for x in e]), m([x["T"] for x in e]), len(ne), m([x["D"] for x in ne]), m([x["T"] for x in ne])))
h = [x for x in allr if x["cache"] >= 50]
print("cacheable>=50%%: n %d D %.1f T %.1f; cacheable mean over pairs %.1f" % (
    len(h), m([x["D"] for x in h]), m([x["T"] for x in h]), m([x["cache"] for x in allr])))
print("T measured only partially (T forced to 0):", sum(not x["tfull"] for x in allr),
      "of which env unchanged:", sum((not x["tfull"]) and not x["env"] for x in allr))
print("verified:", dict(tot), "rule-of-three bound %.4f%%" % (300 / tot["D_checked"]))
print("broken (passed at P, not OK at C):", len(broken))
for b in broken:
    print("  ", b)
print("tests with a recorded result at P whose fresh outcome at C differs (could expose a wrong reuse):",
      len(informative))
for b in informative:
    print("  ", b)
print("null rule (reuse every recorded result, no dependency check): %d reuses, %d wrong (%.3f%%)" % (
    null_reuses, len(informative), 100 * len(informative) / null_reuses))
