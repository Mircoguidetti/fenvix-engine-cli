#!/usr/bin/env python3
"""Tables of the dependency-update verdict validation from the pairs.py results (and ci_status.py, reverts).

    python3 harness/dep_verdict/analyze.py harness/dep_verdict/results/dv1 --commits harness/dep_verdict/commits.json \\
        --repos /path/to/clones --json harness/dep_verdict/results/dv1/summary.json
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import statistics
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

OK = ("passed", "skipped", "xfailed")
IDENT = "dist-identity/"


def load(d: Path):
    out = defaultdict(list)
    for f in sorted(d.glob("*.json.gz")):
        with gzip.open(f) as fh:
            r = json.load(fh)
        out[r["spec"]["name"]].append(r)
    return out


def ident_key(why: str) -> str | None:
    if IDENT not in why:
        return None
    return why.split(IDENT, 1)[1].split(" ", 1)[0]


def pair_stats(st):
    """Per pair: test time, reused time for D (prototype) and T (today), verification counts."""
    tot = cache_t = 0.0
    res = {m: {"time": 0.0, "n": 0, "checked": 0, "wrong": 0, "flaky": 0, "unverified": 0} for m in ("D", "T")}
    tests = 0
    cacheable = 0
    miss = Counter()
    miss_ident = Counter()
    broken = []          # passed at P (D0), failed at C (fresh B, confirmed by D1 run or B2)
    broken_inside = 0
    not_run_units = 0
    for u, r in (st.get("per_unit") or {}).items():
        fresh = r.get("fresh") or {}
        times = r.get("times") or {}
        if not fresh:
            not_run_units += 1
            continue
        mism = {(m["mode"], m["nodeid"]): m for m in r.get("mismatches", [])}
        dre, tre = set(r.get("D1_reused", ())), set(r.get("T1_reused", ()))
        for n, o in fresh.items():
            t = times.get(n, 0.0)
            tests += 1
            tot += t
        for mode, ids in (("D", dre), ("T", tre)):
            for n in ids:
                res[mode]["n"] += 1
                if n not in fresh:
                    res[mode]["unverified"] += 1
                    continue
                res[mode]["time"] += times.get(n, 0.0)
                res[mode]["checked"] += 1
                m = mism.get(("D1" if mode == "D" else "T1", n))
                if m is not None:
                    res[mode]["wrong" if m["verdict"] == "wrong" else "flaky"] += 1
        # cacheable at P: recorded (D1 found an entry: reused, or missed for a reason other than "new"/"failed")
        for n in fresh:
            why = (r.get("D1_miss") or {}).get(n)
            if n in dre:
                cacheable += 1
                cache_t += times.get(n, 0.0)
                continue
            if why is None:
                continue
            k = why.split(":", 1)[0]
            miss[k] += 1
            if k not in ("new", "failed-before"):
                cacheable += 1
                cache_t += times.get(n, 0.0)
            ik = ident_key(why)
            if ik:
                miss_ident[ik] += 1
        po = r.get("outcomes_P") or {}
        for n, o in fresh.items():
            if po.get(n) in ("passed",) and o not in OK:
                inside = n not in dre
                broken.append({"nodeid": n, "P": po.get(n), "C": o, "inside_affected": inside,
                               "why": (r.get("D1_miss") or {}).get(n)})
                broken_inside += inside
    return {"tests": tests, "time": tot, "cacheable": cacheable, "cacheable_time": cache_t, "D": res["D"],
            "T": res["T"], "miss": miss, "miss_ident": miss_ident, "broken": broken, "units_not_run": not_run_units}


def find_reverts(repo: Path, pairs, head: str):
    """Later first-parent commits that revert a dependency-only commit (subject or hash)."""
    if not repo.exists():
        return {}
    log = subprocess.run(["git", "log", "--first-parent", "--format=%H%x00%s%x00%b%x01", "-n", "20000", head],
                         cwd=repo, capture_output=True, text=True, errors="replace").stdout
    commits = [c.split("\0") for c in log.split("\x01") if c.strip()]
    out = {}
    for pc in pairs:
        subj = pc["subject"].strip()
        sha = pc["sha"]
        hits = []
        for c in commits:
            if len(c) < 3:
                continue
            h, s, b = c[0].strip(), c[1], c[2]
            if h == sha:
                break  # only later commits (log is newest first)
            if s.lower().startswith("revert") and (subj[:50] in s or sha[:10] in b or sha[:7] in s):
                hits.append({"sha": h, "subject": s[:160]})
        if hits:
            out[sha] = hits
    return out


def pct(a, b):
    return 100.0 * a / b if b else float("nan")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--commits", required=True)
    ap.add_argument("--repos", default="")
    ap.add_argument("--ci", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)
    commits = json.loads(Path(a.commits).read_text())
    runs = defaultdict(list)
    for d in a.dirs:
        for k, v in load(Path(d)).items():
            runs[k] += v
    ci = json.loads(Path(a.ci).read_text()) if a.ci else {}
    summary = {}
    tot = {"D_checked": 0, "D_wrong": 0, "D_flaky": 0, "T_checked": 0, "T_wrong": 0, "T_flaky": 0}
    all_broken = []
    print("| repository | pairs measured / listed | env changed | tests per pair | share reused D (prototype), mean / median "
          "| share reused T (today), mean / median | D of cacheable time, mean | verified reuses D (wrong, flaky) |")
    print("|---|---|---|---|---|---|---|---|")
    for name in sorted(runs):
        by_sha = {}
        for r in runs[name]:
            for st in r["pairs"]:
                prev = by_sha.get(st["sha"])
                if prev is None or (prev.get("status") != "ok" and st.get("status") == "ok"):
                    by_sha[st["sha"]] = st
        spec_repo = runs[name][0]["spec"].get("repo", name)
        listed = commits[spec_repo]["dep_commits"]
        rows = []
        statuses = Counter(st.get("status") for st in by_sha.values())
        for pc in listed:
            st = by_sha.get(pc["sha"])
            if not st or st.get("status") != "ok":
                continue
            ps = pair_stats(st)
            if not ps["tests"] or ps["time"] <= 0:
                statuses["no-tests-ran"] += 1
                continue
            t_mode = st.get("T_mode", "full")
            t_share = pct(ps["T"]["time"], ps["time"]) if t_mode == "full" else 0.0
            rows.append({"sha": st["sha"], "subject": st["subject"], "env_changed": st.get("env_changed", []),
                         "tests": ps["tests"], "time": ps["time"], "D_share": pct(ps["D"]["time"], ps["time"]),
                         "T_share": t_share, "T_measured": t_mode == "full",
                         "D_of_cacheable": pct(ps["D"]["time"], ps["cacheable_time"]) if ps["cacheable_time"] else None,
                         "cacheable_share": pct(ps["cacheable_time"], ps["time"]),
                         "D": ps["D"], "T": ps["T"], "miss": dict(ps["miss"]), "miss_ident": dict(ps["miss_ident"]),
                         "broken": ps["broken"], "units_not_run": ps["units_not_run"]})
            for m in ("D", "T"):
                tot[f"{m}_checked"] += ps[m]["checked"]
                tot[f"{m}_wrong"] += ps[m]["wrong"]
                tot[f"{m}_flaky"] += ps[m]["flaky"]
            all_broken += [dict(b, repo=name, sha=st["sha"]) for b in ps["broken"]]
        reverts = find_reverts(Path(a.repos) / spec_repo, listed, commits[spec_repo]["head"]) if a.repos else {}
        ds = [x["D_share"] for x in rows]
        ts = [x["T_share"] for x in rows]
        dc = [x["D_of_cacheable"] for x in rows if x["D_of_cacheable"] is not None]
        summary[name] = {"listed": len(listed), "measured": len(rows), "statuses": dict(statuses),
                         "env_changed_pairs": sum(1 for x in rows if x["env_changed"]),
                         "D_mean": statistics.mean(ds) if ds else None, "D_median": statistics.median(ds) if ds else None,
                         "T_mean": statistics.mean(ts) if ts else None, "T_median": statistics.median(ts) if ts else None,
                         "D_of_cacheable_mean": statistics.mean(dc) if dc else None,
                         "cacheable_mean": statistics.mean([x["cacheable_share"] for x in rows]) if rows else None,
                         "D_checked": sum(x["D"]["checked"] for x in rows), "D_wrong": sum(x["D"]["wrong"] for x in rows),
                         "D_flaky": sum(x["D"]["flaky"] for x in rows), "reverts": reverts, "ci": ci.get(spec_repo, []),
                         "rows": rows}
        s = summary[name]
        f = lambda v: "-" if v is None else f"{v:.0f}%"  # noqa: E731
        print(f"| {name} | {len(rows)} / {len(listed)} | {s['env_changed_pairs']} | "
              f"{statistics.mean([x['tests'] for x in rows]) if rows else 0:.0f} | {f(s['D_mean'])} / {f(s['D_median'])} | "
              f"{f(s['T_mean'])} / {f(s['T_median'])} | {f(s['D_of_cacheable_mean'])} | "
              f"{s['D_checked']:,} ({s['D_wrong']}, {s['D_flaky']}) |")
    allD = [x["D_share"] for s in summary.values() for x in s["rows"]]
    allT = [x["T_share"] for s in summary.values() for x in s["rows"]]
    repoD = [s["D_mean"] for s in summary.values() if s["D_mean"] is not None]
    print()
    print(f"pairs measured: {len(allD)}; mean over pairs D {statistics.mean(allD) if allD else float('nan'):.1f}% "
          f"T {statistics.mean(allT) if allT else float('nan'):.1f}%; mean of repository means D "
          f"{statistics.mean(repoD) if repoD else float('nan'):.1f}%")
    print(f"verified reuses D {tot['D_checked']:,} (wrong {tot['D_wrong']}, flaky {tot['D_flaky']}); "
          f"T {tot['T_checked']:,} (wrong {tot['T_wrong']}, flaky {tot['T_flaky']})")
    inside = sum(1 for b in all_broken if b["inside_affected"])
    print(f"tests that broke (pass at P, fail at C, our runs): {len(all_broken)}, inside the affected set {inside}")
    if a.json:
        Path(a.json).write_text(json.dumps({"summary": summary, "totals": tot, "broken": all_broken}, indent=1,
                                           default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
