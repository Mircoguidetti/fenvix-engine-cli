#!/usr/bin/env python3
"""Review R-025b: numbers of REPORT-2 (claude/go-l0 at 05a7dfa) re-derived from
the committed raw files. Prints one line per check; exits 1 when a finding
holds.

The review's version appended N4, N5 and S1 unconditionally (it exited 1 on
any tree). After the fixes (REPORT-3) each check verifies the corrected
statement: REPORT-3 states the data's number and label (N4, N5), the
aggregate no longer mislabels a --det timeout (N5), and the newest walk has
no test broken by skip mode (S1). The computations are the review's.

    python3 harness/go/review_r025b_check.py
"""

import collections
import glob
import gzip
import json
import os
import statistics as st
import sys

ROOT = os.path.join(os.path.dirname(__file__), "results")
findings = []
R3 = os.path.join(os.path.dirname(__file__), "..", "..", "sessions", "2026-11-18-go-l0", "REPORT-3.md")
REPORT3 = open(R3).read() if os.path.exists(R3) else ""
AGG = open(os.path.join(os.path.dirname(__file__), "aggregate.py")).read()


def walk(rnd, name):
    return [json.load(gzip.open(f, "rt")) for f in sorted(glob.glob(f"{ROOT}/{rnd}/{name}-*.json.gz"))]


def rows(shards):
    for s in shards:
        for c in s["commits"]:
            if c.get("status") != "ok" or c["i"] == 0:
                continue
            for t in c["tests"]:
                if t["fresh"] not in ("", "skipped"):
                    yield s, c, t


def flaky(d):
    out = {}
    for f in glob.glob(f"{ROOT}/{d}/*.json"):
        r = json.load(open(f))
        if "spec" in r:
            out[r["spec"]["name"]] = r
    return out


# N4: telegraf r5/r6 cover 5 of 6 shards; share of the suite's test time they cover (skip-r4, all 6 shards)
tot = collections.Counter()
for f in sorted(glob.glob(f"{ROOT}/skip-r4/telegraf-*.json.gz")):
    sh = f.split("-")[-3]
    for _, _, t in rows([json.load(gzip.open(f, "rt"))]):
        tot[sh] += t["elapsed"] or 0
share5 = tot["5"] / sum(tot.values())
print(f"N4  telegraf shard 5 (missing in skip-r5/r6) = {100 * share5:.1f}% of telegraf's test time in skip-r4; "
      f"the r5/r6 rows cover {100 * (1 - share5):.1f}%")
if f"{100 * (1 - share5):.1f}%" not in REPORT3:
    findings.append("N4")

# N5: flaky-r8 coverage like for like
F, R = flaky("flaky-final"), flaky("flaky-r8")
same = lambda v: len(v) >= 2 and len({x[1] for x in v}) == 1
n = a = b = 0
for p in R:
    df, dr = F[p].get("det0", {}), R[p].get("det0", {})
    for k in set(df) & set(dr):
        if len(df[k]) >= 2 and len(dr[k]) >= 2:
            n, a, b = n + 1, a + same(df[k]), b + same(dr[k])
q8, qf = R["quic-go"], F["quic-go"]
print(f"N5  coverage on the {n} tests with a --det result in both rounds: flaky-final {100 * a / n:.1f}% -> flaky-r8 "
      f"{100 * b / n:.1f}% (REPORT-2: 56.0% -> 70.0%); quic-go tests with a --det result {len(qf['det0'])} -> "
      f"{len(q8['det0'])}; quic-go timing plain {q8['timing']['plain']} det {q8['timing']['det']} "
      f"(REPORT-2: 'both arms stopped by the timeout')")
if not (f"{100 * a / n:.1f}%" in REPORT3 and f"{100 * b / n:.1f}%" in REPORT3 and "the --det arm stopped" in AGG):
    findings.append("N5")

# S1: tests broken by skip mode's virtual-day clock (fresh fenvix run fails; plain reruns pass)
def fails(rnd, name):
    Fc, Nc = collections.Counter(), collections.Counter()
    for _, _, t in rows(walk(rnd, name)):
        k = (t["pkg"], t["test"])
        Nc[k] += 1
        Fc[k] += t["fresh"] in ("failed", "interrupted")
    return Fc, Nc
broken = []
for name in ("prometheus", "telegraf", "terraform"):
    f4, n4 = fails("skip-r4", name)
    f5, n5 = fails("skip-r5", name)
    for k in f5:
        if f5[k] >= 10 and f4.get(k, 0) <= 2:
            broken.append((name, k[1], f"{f4.get(k, 0)}/{n4.get(k, 0)} -> {f5[k]}/{n5[k]}"))
print(f"S1  tests failing in fenvix's fresh run in >=10 commits of skip-r5 and <=2 of skip-r4 ({len(broken)}):")
for x in sorted(broken):
    print("      ", x)
# after the fixes: the same 8 tests and any other test in the newest walk
# (skip-r8), failing under fenvix in >= 10 commits while plain go test passes
latest = "skip-r8"
now_broken = []
names = sorted({os.path.basename(f).split("-")[0] for f in glob.glob(f"{ROOT}/{latest}/*.json.gz")})
for name in names:
    fl, nl = fails(latest, name)
    plain_ok = collections.Counter()
    for _, _, t in rows(walk(latest, name)):
        if t.get("plain") == "passed":
            plain_ok[(t["pkg"], t["test"])] += 1
    for k in fl:
        if fl[k] >= 10 and plain_ok.get(k, 0) >= 10:
            now_broken.append((name, k[1], f"{fl[k]}/{nl[k]}"))
s8 = {k[1] for k in broken}
seen = {(t["test"]) for name in names for _, _, t in rows(walk(latest, name)) if t["test"] in s8}
print(f"S1  {latest} ({', '.join(names) or 'no data'}): broken by skip mode (fresh fenvix failed, plain passed, "
      f">= 10 commits): {len(now_broken)} {now_broken[:8]}; of the 8, present in {latest}: {len(seen)}")
if not names or now_broken or f"broken by skip mode: {len(now_broken)}" not in REPORT3:
    findings.append("S1")

# Q3: /proc/1/stat upper bound (skip-r6, telegraf, 5 of 6 shards)
per = collections.defaultdict(collections.Counter)
for _, c, t in rows(walk("skip-r6", "telegraf")):
    p = per[c["i"]]
    el = t["elapsed"] or 0
    p["all"] += el
    if t["reuse"]:
        p["fen"] += el
    elif (t["why"] or "") == "volatile:/proc/1/stat":
        p["proc"] += el
ix = [i for i in sorted(per) if per[i]["all"]]
fen = [per[i]["fen"] / per[i]["all"] for i in ix]
up = [(per[i]["fen"] + per[i]["proc"]) / per[i]["all"] for i in ix]
print(f"Q3  telegraf skip-r6: fenvix {100 * st.median(fen):.0f}% / {100 * st.mean(fen):.0f}%; upper bound if "
      f"/proc/1/stat were virtualised (tests whose first reason it is, reused) {100 * st.median(up):.0f}% / "
      f"{100 * st.mean(up):.0f}% (ESTIMATED; 5 of 6 shards)")

print("findings:", ", ".join(findings))
sys.exit(1 if findings else 0)
