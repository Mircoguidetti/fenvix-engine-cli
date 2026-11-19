#!/usr/bin/env python3
"""Tables for the node cache-with-proof walks: harness/node_cache/results/<label>/<repo>-<shard>.json.gz.

Per transition (commit i-1 -> i, measured at commit i):
  * share of test time skipped with proof = time of the files detjs would reuse / time of all files, both priced with
    the verify run's own per-file durations (collection + set-up + environment + tests, serial Level 0);
  * wrong = a reused result that differs from the fresh result at the same commit (verify mode compares every one);
    a mismatch whose file is not reproducible on 3 re-runs is reported as flaky, not wrong;
  * wall time of the skip run vs the full verify run;
  * Nx: files whose project `nx show projects --affected` leaves out, priced the same way; Nx "misses" = a file whose
    fresh outcome changed at the transition although its project was not affected.
Overhead (commits with plain / det runs): cold capture = verify run with an empty cache; det = serial Level 0 without
cache; plain = the project's own command; warm = rerun at the same commit right after recording.

Usage: python3 harness/node_cache/aggregate.py LABEL [--md]
"""
from __future__ import annotations

import glob
import gzip
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


NXONLY = {}


def load(label):
    by = {}
    for p in sorted(glob.glob(os.path.join(HERE, "results", "nx", "nx-*.json.gz"))):
        d = json.load(gzip.open(p))
        NXONLY[d["spec"]["name"]] = {t["sha"]: t for t in d.get("transitions", [])}
    for p in sorted(glob.glob(os.path.join(HERE, "results", label, "*.json.gz"))):
        d = json.load(gzip.open(p))
        if d.get("mode") == "nx-only":
            continue
        name = d["spec"]["name"]
        by.setdefault(name, []).append(d)
    return by


def pct(x):
    return f"{100 * x:.0f}%" if x is not None else "n/a"


def med(xs):
    return statistics.median(xs) if xs else None


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def project_of(path, roots):
    best = None
    for name, root in roots.items():
        if root in (None, ".", ""):
            continue
        r = root.rstrip("/") + "/"
        if path.startswith(r) and (best is None or len(r) > len(best[1])):
            best = (name, r)
    return best[0] if best else None


def analyse(name, shards):
    commits = {}
    for d in shards:
        for c in d["commits"]:
            commits.setdefault(c["i"], c)
    order = sorted(commits)
    rows = []
    over = []
    prev_ok = None
    for i in order:
        c = commits[i]
        v = c.get("verify") or {}
        s = v.get("summary") or {}
        files = s.get("ran_files") or {}
        # the runner's durations come from the worker's clock: tests that move it backwards (Lexical's @lexical/y)
        # report negative times; those count as 0 s (they make Nx's share approximate there)
        files = {k: {**f, "duration": max(0.0, f["duration"])} for k, f in files.items()}
        total = sum(f["duration"] for f in files.values())
        reused = set(s.get("reused_files_list") or [])
        ok_now = {k: f["ok"] for k, f in files.items()}
        if not v.get("cold") and total > 0:
            skipped = sum(f["duration"] for k, f in files.items() if k in reused)
            tests_total = sum(f["tests"] for f in files.values())
            tests_reused = sum(f["tests"] for k, f in files.items() if k in reused)
            mism = s.get("verify_mismatches") or []
            flaky = wrong = 0
            if mism:
                rc = c.get("recheck") or {}
                for m in mism:
                    f = m["nodeid"].split("::", 1)[0].split("@@", 1)[0]
                    runs = rc.get(f) or []
                    oks = {any(o.get("ok") for o in (r.get("outcomes") or {}).values()) for r in runs}
                    if len(oks) > 1 or (runs and m["cached"] == "passed" and any(r["rc"] == 0 for r in runs)):
                        flaky += 1
                    else:
                        wrong += 1
            row = {"i": i, "sha": c["sha"][:10], "share": skipped / total, "tests_share": tests_reused / tests_total if tests_total else None,
                   "files": len(files), "reused_files": len(reused), "verified": s.get("verified", 0), "mismatch": len(mism),
                   "flaky": flaky, "wrong": wrong, "verify_s": v.get("seconds"), "skip_s": (c.get("skip") or {}).get("seconds"),
                   "skip_rc": (c.get("skip") or {}).get("rc"), "verify_rc": v.get("rc"),
                   "miss_reasons": s.get("miss_reasons") or {}, "changed": len(c.get("changed_files") or [])}
            nx = c.get("nx") or {}
            if nx.get("affected") is None and c["sha"] in NXONLY.get(name, {}):
                nx = NXONLY[name][c["sha"]]
            if nx.get("affected") is not None and nx.get("roots"):
                aff = set(nx["affected"])
                roots = nx["roots"]
                nx_skip = 0.0
                nx_miss = 0
                for k, f in files.items():
                    p = project_of(k.split("@@", 1)[0], roots)
                    if p is not None and p not in aff:
                        nx_skip += f["duration"]
                        if prev_ok is not None and k in prev_ok and prev_ok[k] != ok_now.get(k):
                            nx_miss += 1
                row["nx_share"] = nx_skip / total
                row["nx_miss"] = nx_miss
                row["nx_affected"] = len(aff)
                row["nx_projects"] = len(nx.get("all") or [])
            else:
                row["nx_share"] = None
                row["nx_error"] = (nx.get("error") or "")[:200] if nx else "not run"
            rows.append(row)
        if c.get("det_nocache") or c.get("plain"):
            over.append({"i": i, "plain_s": (c.get("plain") or {}).get("seconds"), "det_s": (c.get("det_nocache") or {}).get("seconds"),
                         "capture_s": v.get("seconds"), "cold": v.get("cold"), "warm_s": (c.get("warm") or {}).get("seconds"),
                         "warm_reused": ((c.get("warm") or {}).get("summary") or {}).get("reused_files"),
                         "files": len(files), "identity_s": s.get("identity_seconds"), "record_s": s.get("record_seconds"),
                         "packages": s.get("packages")})
        prev_ok = ok_now
    return rows, over, len(order)


def main():
    label = sys.argv[1]
    md = "--md" in sys.argv
    by = load(label)
    out = {}
    lines = []
    lines.append("| project | transitions | skip with proof: test time, median / mean | tests reused, median | verified reuses | wrong | flaky mismatches | Nx affected: time skipped, median / mean | Nx misses |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name in sorted(by):
        rows, over, ncommits = analyse(name, by[name])
        sh = [r["share"] for r in rows]
        ts = [r["tests_share"] for r in rows if r["tests_share"] is not None]
        nx = [r["nx_share"] for r in rows if r.get("nx_share") is not None]
        out[name] = {"rows": rows, "overhead": over, "commits": ncommits}
        lines.append(f"| {name} | {len(rows)} | {pct(med(sh))} / {pct(mean(sh))} | {pct(med(ts))} | {sum(r['verified'] for r in rows)} | "
                     f"{sum(r['wrong'] for r in rows)} | {sum(r['flaky'] for r in rows)} | "
                     f"{pct(med(nx)) if nx else 'n/a'} / {pct(mean(nx)) if nx else 'n/a'} ({len(nx)} transitions) | {sum(r.get('nx_miss', 0) for r in rows)} |")
    lines.append("")
    lines.append("| project | commit | plain (project's command) s | detjs --det (serial, no cache) s | cold capture s | warm rerun s (files reused) | identity s |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for name in sorted(out):
        for o in out[name]["overhead"]:
            lines.append(f"| {name} | {o['i']}{' (cold)' if o['cold'] else ''} | {o['plain_s']} | {o['det_s']} | {o['capture_s']} | {o['warm_s']} ({o['warm_reused']}/{o['files']}) | {o['identity_s']} |")
    lines.append("")
    lines.append("| project | wall: verify (full) run, median s | wall: skip run, median s | ratio |")
    lines.append("|---|---:|---:|---:|")
    for name in sorted(out):
        rows = out[name]["rows"]
        vs = [r["verify_s"] for r in rows if r["verify_s"]]
        ss = [r["skip_s"] for r in rows if r["skip_s"]]
        if vs and ss:
            lines.append(f"| {name} | {med(vs):.0f} | {med(ss):.0f} | {med(ss) / med(vs):.2f} |")
    text = "\n".join(lines)
    print(text)
    with open(os.path.join(HERE, "results", label, "aggregate.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    if md:
        with open(os.path.join(HERE, "results", label, "TABLES.md"), "w") as fh:
            fh.write(text + "\n")


if __name__ == "__main__":
    main()
