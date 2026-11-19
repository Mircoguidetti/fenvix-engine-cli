#!/usr/bin/env python3
"""Review R-025: re-derive P-021's headline numbers from the committed data and
check the Rust boundary. Exits 1 when a check fails (each failure is a finding
of sessions/2026-11-19-review-go/REPORT.md in fenvix-brain-cli).

    python3 harness/go/review_r025_check.py

Data: harness/go/results/skip-r3 (skip walk) and harness/go/results/flaky-final
(flaky round), as committed on claude/go-l0 (c22b02f; later commits only add
hugo shard 1 data: N1a's count is 66,908 at c22b02f and 67,616 at the branch head,
no verdict changes).
"""

from __future__ import annotations

import collections
import glob
import gzip
import json
import os
import re
import statistics
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
SKIP = os.path.join(ROOT, "harness", "go", "results", "skip-r3")
FLAKY = os.path.join(ROOT, "harness", "go", "results", "flaky-final")
failures: list[str] = []


def check(ok: bool, name: str, detail: str) -> None:
    print(("ok   " if ok else "FAIL ") + name + ": " + detail)
    if not ok:
        failures.append(name)


def walk_rows():
    for f in sorted(glob.glob(os.path.join(SKIP, "*.json.gz"))):
        repo = os.path.basename(f).split("-")[0]
        d = json.load(gzip.open(f, "rt"))
        for row in d.get("commits", []):
            if row.get("status") == "ok" and row["i"] > 0:
                yield repo, row


# N1. "The gap [to Go's cache] is the network rule: 61,389 test-transitions rerun because the test (or one
# before it) connected outside the machine." (REPORT 5b, reading)
net = 0
gap = collections.defaultdict(collections.Counter)  # repo -> first own reason -> seconds (go reused, fenvix not)
total = collections.Counter()
for repo, row in walk_rows():
    for t in row["tests"]:
        el = t.get("elapsed") or 0.0
        if t["fresh"] not in ("", "skipped"):
            total[repo] += el
        if t["why"] == "network":
            net += 1
        if t["go_cached"] and not t["reuse"] and t["fresh"] not in ("", "skipped"):
            w = t.get("why_own") or ("prefix:" + t["why"])
            if "/.config/go/telemetry/" in w:
                w = "telemetry"
            elif w.startswith("prefix:") and "/.config/go/telemetry/" in w:
                w = "prefix:telemetry"
            elif w.startswith("file:"):
                w = "file"
            gap[repo][w] += el
check(net == 61389, "N1a network reruns", f"data {net:,} test-transitions with reason network, report 61,389")
tf = gap["terraform"]
tf_gap = sum(tf.values())
tf_net = tf["network"] + tf["prefix:network"]
tf_tel = tf["telemetry"] + tf["prefix:telemetry"]
check(tf_net > tf_gap / 2, "N1b terraform gap = network rule",
      f"of the test time Go's cache reused and fenvix did not ({100 * tf_gap / total['terraform']:.1f}% of all), "
      f"network explains {100 * tf_net / total['terraform']:.1f} points, the Go telemetry counters "
      f"{100 * tf_tel / total['terraform']:.1f} points")

# N1c. share with telemetry-only reruns counted as reused (the report's own upper-bound method, applied to every repo)
for name in ("terraform", "caddy"):
    per = collections.defaultdict(collections.Counter)
    shards = [json.load(gzip.open(f, "rt")) for f in sorted(glob.glob(os.path.join(SKIP, f"{name}-*.json.gz")))]
    walked = min(len([c for c in s["commits"] if c.get("status") == "ok"]) for s in shards)
    for s in shards:
        for c in s["commits"]:
            if c.get("status") != "ok" or c["i"] == 0:
                continue
            for t in c["tests"]:
                if t["fresh"] in ("", "skipped"):
                    continue
                el = t["elapsed"] or 0.0
                per[c["i"]]["all"] += el
                per[c["i"]]["fen"] += el if t["reuse"] else 0
                per[c["i"]]["fix"] += el if (t["reuse"] or "/.config/go/telemetry/" in t["why"]) else 0
    idx = [i for i in sorted(per) if i < walked and per[i]["all"] > 0]
    fen = [per[i]["fen"] / per[i]["all"] for i in idx]
    fix = [per[i]["fix"] / per[i]["all"] for i in idx]
    mm = lambda v: f"{100 * statistics.median(v):.0f}% / {100 * statistics.mean(v):.0f}%"
    changed = round(100 * statistics.median(fix)) != round(100 * statistics.median(fen)) or \
        round(100 * statistics.mean(fix)) != round(100 * statistics.mean(fen))
    check(not changed, f"N1c {name} unaffected by the telemetry defect",
          f"published {mm(fen)}, with telemetry-only reruns counted as reused (upper bound) {mm(fix)}")

# N2. "tests 4099 ... broken by --det 0; fingerprint coverage 38.9%" (REPORT 5a)
base_n = det_n = missing = notall = 0
per_proj = {}
for f in sorted(glob.glob(os.path.join(FLAKY, "*.json"))):
    r = json.load(open(f))
    if "spec" not in r:
        continue
    base, det = r.get("baseline", {}), r.get("det0", {})
    allpass = [k for k, v in base.items() if v and all(x == "passed" for x in v) and "::Example" not in k]
    miss = [k for k in allpass if k not in det]
    na = [k for k in allpass if k in det and any((x or [None])[0] != "passed" for x in det[k])]
    base_n += len(base)
    det_n += len(det)
    missing += len(miss)
    notall += len(na)
    if miss or na:
        per_proj[r["spec"]["name"]] = (len(miss), len(na))
check(missing == 0, "N2 tests without a --det result",
      f"{base_n:,} tests in the plain baseline, {det_n:,} with a --det seed-0 result; {missing:,} tests that passed "
      f"10/10 plain have no --det result and {notall} pass 10/10 plain but not 3/3 under --det; both groups are in "
      f"no column (per project: {per_proj})")

# N3. "median +2.1% over 23 projects" (REPORT 5a): both timing arms must have run the same tests to completion
slow, bad = {}, {}
for f in sorted(glob.glob(os.path.join(FLAKY, "*.json"))):
    r = json.load(open(f))
    if r.get("slowdown") is None:
        continue
    name = r["spec"]["name"]
    slow[name] = r["slowdown"]
    tm = r.get("timing", {})
    timeout = float(re.sub(r"m$", "", str(r["spec"].get("timeout", "10m")))) * 60
    if min(tm.get("plain", [0])) >= timeout - 1 or min(tm.get("det", [0])) >= timeout - 1:
        bad[name] = "both arms stopped by the 10-minute go test timeout"
    elif len(r.get("det0", {})) < 0.5 * len(r.get("baseline", {})):
        bad[name] = f"--det ran {len(r['det0'])} of {len(r['baseline'])} tests"
valid = [v for k, v in slow.items() if k not in bad]
check(not bad, "N3 slowdown comparisons valid",
      f"median {100 * statistics.median(slow.values()):+.1f}% over {len(slow)}; invalid: {bad}; median over the "
      f"{len(valid)} valid comparisons {100 * statistics.median(valid):+.1f}%")

# R1. Rust boundary (DECISIONS 2026-11-18: engine logic in Rust, shells keep thin shims): the skip decision
skip_go = open(os.path.join(ROOT, "go", "internal", "skip", "skip.go")).read()
strace_go = open(os.path.join(ROOT, "go", "internal", "strace", "strace.go")).read()
in_go = [n for n, pat in (("decider Entry.Why", r"func \(e \*Entry\) Why\("),
                          ("key composition MakeEntry/Absorb", r"func MakeEntry\("),
                          ("key digest (sha256, not the core's BLAKE3)", r"crypto/sha256"),
                          ("strace dependency rules", r"func Parse\("),
                          ("path filter", r"func \(f \*Filter\) Keep\(")) if re.search(pat, skip_go + strace_go)]
check(not in_go, "R1 skip decision in Rust", f"implemented in Go: {in_go}")

print()
print("failed:", ", ".join(failures) if failures else "none")
sys.exit(1 if failures else 0)
