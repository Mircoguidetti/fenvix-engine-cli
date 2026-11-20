#!/usr/bin/env python3
"""Review R-032b: re-derive REPORT-2's walk numbers from the committed raw files, independently of aggregate2.py.

Per raw file: transitions (steps/commits after a shard's first), tests verified, mismatches, confirmed wrong, and
consistency checks: Python verify.checked == n_reused (every reused test compared, per test); Node compare.checked
+ n_missing == the skip run's reused tests (summary.reused_tests), and the engine's verify count.
Usage: python3 rederive2.py [--at <git rev>]   (default: the working tree)
"""
import glob
import gzip
import io
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REV = sys.argv[sys.argv.index("--at") + 1] if "--at" in sys.argv else None


def files(pattern):
    if REV is None:
        return sorted(glob.glob(os.path.join(ROOT, pattern)))
    out = subprocess.run(["git", "-C", ROOT, "ls-tree", "-r", "--name-only", REV], capture_output=True, text=True).stdout
    import fnmatch
    return sorted(f for f in out.split() if fnmatch.fnmatch(f, pattern))


def load(p):
    if REV is None:
        return json.load(gzip.open(p))
    raw = subprocess.run(["git", "-C", ROOT, "show", f"{REV}:{p}"], capture_output=True).stdout
    return json.load(gzip.open(io.BytesIO(raw)))


tot = {"python": [0, 0, 0], "node": [0, 0, 0]}
issues = []
print(f"{'lang':6} {'file':55} {'trans':>5} {'verified':>8} {'mism':>4} {'wrong':>5} {'missing':>7} finished")
for p in files("tracks/all-runners-python/results/ar2-py-*/*.json.gz"):
    d = load(p)
    tr = ver = mm = wr = 0
    for s in d.get("steps", [])[1:]:
        tr += 1
        v = s.get("verify") or {}
        ver += v.get("checked", 0) or 0
        m = v.get("mismatches") or []
        mm += len(m)
        wr += sum(1 for x in m if x.get("verdict") == "wrong")
        if (v.get("checked") or 0) != (s.get("n_reused") or 0):
            issues.append(f"{p} step {s.get('i')}: checked {v.get('checked')} != n_reused {s.get('n_reused')}")
        if s.get("status") not in ("ok", None):
            issues.append(f"{p} step {s.get('i')}: status {s.get('status')}")
    tot["python"][0] += ver; tot["python"][1] += mm; tot["python"][2] += wr
    print(f"{'py':6} {os.path.relpath(p, ROOT) if REV is None else p:55.55} {tr:5} {ver:8} {mm:4} {wr:5} {'-':>7} {bool(d.get('finished'))}")
for p in files("harness/node_cache/results/ar2-node-*/*.json.gz"):
    d = load(p)
    tr = ver = mm = wr = miss = 0
    for c in d.get("commits", []):
        cm = c.get("compare")
        if cm is None:
            continue
        tr += 1
        ver += cm.get("checked", 0)
        mm += len(cm.get("mismatches") or [])
        wr += cm.get("confirmed_wrong", 0)
        miss += cm.get("n_missing", 0)
        rs = ((c.get("skip") or {}).get("summary") or {}).get("reused_tests")
        if rs is not None and cm.get("checked", 0) + cm.get("n_missing", 0) != rs:
            issues.append(f"{p} commit {c.get('i')}: checked {cm.get('checked')} + missing {cm.get('n_missing')} != skip reused_tests {rs}")
        vs = (c.get("verify") or {}).get("summary") or {}
        if vs.get("verified_tests") is not None and vs.get("verified_tests") != cm.get("checked", 0) + cm.get("n_missing", 0):
            issues.append(f"{p} commit {c.get('i')}: engine verified_tests {vs.get('verified_tests')} != compared {cm.get('checked', 0) + cm.get('n_missing', 0)}")
        if (c.get("fresh") or {}).get("n", 1) == 0:
            issues.append(f"{p} commit {c.get('i')}: fresh run reported 0 tests (rc {(c.get('fresh') or {}).get('rc')})")
    tot["node"][0] += ver; tot["node"][1] += mm; tot["node"][2] += wr
    print(f"{'node':6} {os.path.relpath(p, ROOT) if REV is None else p:55.55} {tr:5} {ver:8} {mm:4} {wr:5} {miss:7} -")
print()
for k, (v, m, w) in tot.items():
    print(f"TOTAL {k}: verified {v}, mismatches {m}, confirmed wrong {w}")
print(f"TOTAL: verified {tot['python'][0] + tot['node'][0]}")
print(f"\nconsistency issues: {len(issues)}")
for i in issues[:60]:
    print("  " + i)
