#!/usr/bin/env python3
"""Aggregate skip study 2 results into harness/skip_study2/results/summary.json (and print tables).

    python harness/skip_study2/aggregate.py [run_id ...]
"""

from __future__ import annotations

import gzip
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
SPECS = HERE / "specs"


def load(p: Path):
    b = p.read_bytes()
    if p.suffix == ".gz":
        b = gzip.decompress(b)
    return json.loads(b)


def stats(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return {"median": statistics.median(xs), "mean": statistics.fmean(xs), "n": len(xs),
            "p25": statistics.quantiles(xs, n=4)[0] if len(xs) > 3 else min(xs),
            "p75": statistics.quantiles(xs, n=4)[2] if len(xs) > 3 else max(xs)}


def reason_class(r: str) -> str:
    if r is None:
        return "skip"
    if r in ("new", "no-record", "no-result", "network", "go-miss"):
        return r
    if ":" in r:
        kind, what = r.split(":", 1)
        return f"{kind}:{what}"
    return r


def rules_for(lang):
    if lang == "pytest":
        return ["closure", "closure~cfg", "func+guard", "func+guard~cfg", "func", "strict"]
    if lang == "go":
        return ["go-cache", "closure", "strict"]
    return ["closure", "strict"]


def lpt_makespan(costs, workers):
    """Longest-processing-time-first schedule of independent units on ``workers`` identical workers."""
    if not costs:
        return 0.0
    loads = [0.0] * workers
    for c in sorted(costs, reverse=True):
        k = min(range(workers), key=loads.__getitem__)
        loads[k] += c
    return max(loads)


def walk_summary(shards, spec):
    """shards: list of walk results of one repository (same commits, disjoint units)."""
    lang = spec["lang"]
    rules = rules_for(lang)
    frac = spec.get("units", {}).get("sample", 1.0) if lang != "go" else 1.0
    workers = spec.get("ci", {}).get("workers", 4)
    units, by_i = {}, defaultdict(list)
    ovh = []
    for sh in shards:
        units.update({u: c for u, c in (sh.get("units") or {}).items() if c})
        for t in sh.get("transitions", []):
            by_i[t["i"]].append(t)
        co = sh.get("capture_overhead") or {}
        if co.get("sum_plain"):
            ovh.append(co["sum_traced"] / co["sum_plain"])
    ratio = statistics.median(ovh) if ovh else None
    per_rule = {r: {"time": [], "count": [], "ttg_after": []} for r in rules}
    ttg_before, inval_all, inval_why, verify = [], 0, Counter(), Counter()
    wrong, flaky_v = [], []
    rows = []
    n_full = 0
    for i in sorted(by_i):
        ts = by_i[i]
        if len(ts) != len(shards):
            continue  # a shard did not reach this commit
        n_full += 1
        all_units = {}
        decisions = {}
        strict = any(t["strict_config"] for t in ts)
        for t in ts:
            all_units.update(t["tests"])
            decisions.update(t["decisions"])
            for v in t.get("verify", []):
                verify["checked"] += 1
                if not v["same"]:
                    # wrong hit: the fresh outcome differs from the cached one and is reproducible; otherwise the
                    # unit is flaky at this commit
                    reproducible = (v.get("rerun_matches_fresh") == 2) if "rerun_matches_fresh" in v else True
                    if v.get("rerun_matches_cache") or not reproducible:
                        flaky_v.append({"i": i, **v})
                        verify["flaky"] += 1
                    else:
                        wrong.append({"i": i, **v})
                        verify["wrong"] += 1
        live = [u for u in all_units if (units.get(u) or {}).get("n", all_units[u]) and u in units]
        tot_t = sum(units[u]["test"] for u in live)
        tot_n = sum(units[u]["n"] for u in live)
        if not live or tot_t <= 0:
            continue
        before = lpt_makespan([units[u]["test"] / 1.0 for u in live], max(1, round(workers * frac))) if frac < 1 \
            else lpt_makespan([units[u]["test"] for u in live], workers)
        ttg_before.append(before)
        row = {"i": i, "units": len(live), "strict_config": strict}
        for r in rules:
            if r == "strict":
                must = live if strict else [u for u in live if (decisions.get(u) or {}).get(
                    "go-cache" if lang == "go" else "closure")]
            else:
                must = [u for u in live if (decisions.get(u) or {}).get(r)]
            skip_t = tot_t - sum(units[u]["test"] for u in must)
            skip_n = tot_n - sum(units[u]["n"] for u in must)
            per_rule[r]["time"].append(skip_t / tot_t)
            per_rule[r]["count"].append(skip_n / tot_n if tot_n else None)
            k = ratio if (ratio and r not in ("go-cache",) and lang != "go") else 1.0
            w = max(1, round(workers * frac)) if frac < 1 else workers
            per_rule[r]["ttg_after"].append(lpt_makespan([units[u]["test"] * k for u in must], w))
            row[r] = round(skip_t / tot_t, 4)
        main = "go-cache" if lang == "go" else "closure"
        if row[main] < 0.01:
            inval_all += 1
            c = Counter(reason_class((decisions.get(u) or {}).get(main)) for u in live)
            inval_why[c.most_common(1)[0][0]] += 1
        rows.append(row)
    out = {"name": spec["name"], "lang": lang, "sample": frac, "units": len(units),
           "tests": sum(c.get("n", 0) for c in units.values()), "transitions": n_full,
           "capture_overhead_ratio": ratio, "ci_workers": workers,
           "invalidate_all": inval_all, "invalidate_all_why": dict(inval_why), "verify": dict(verify),
           "wrong_hits": wrong[:20], "flaky_in_verify": flaky_v[:20], "rows": rows,
           "commits_per_day": commits_per_day(shards)}
    for r in rules:
        out[r] = {"time": stats(per_rule[r]["time"]), "count": stats(per_rule[r]["count"]),
                  "ttg_after_s": stats(per_rule[r]["ttg_after"])}
    out["ttg_before_s"] = stats(ttg_before)
    if frac < 1:
        out["ttg_note"] = (f"sample of {frac:.0%} of the test files scheduled on {frac:.0%} of the CI workers "
                           f"(same load per worker as the full suite on {workers} workers)")
    return out


def commits_per_day(shards):
    from datetime import datetime
    dates = sorted({c.get("date") for sh in shards for c in sh.get("commits", []) if c.get("date")})
    if len(dates) < 2:
        return None
    a, b = datetime.fromisoformat(dates[0]), datetime.fromisoformat(dates[-1])
    days = max((b - a).total_seconds() / 86400, 0.01)
    return (len(dates) - 1) / days


def flaky_summary(items, spec):
    by_group = defaultdict(list)
    for it in items:
        if it.get("status") == "ok":
            by_group[it["group"]].append(it)
    attempts = sum(len(v) for v in by_group.values())
    flaky_fail, broken, wasted_s, job_s = 0, 0, 0.0, []
    tests = Counter()
    for g, runs in by_group.items():
        oks = [r for r in runs if r["exit"] == 0]
        fails = [r for r in runs if r["exit"] != 0]
        job_s += [r["job_s"] for r in runs]
        if fails and oks:
            flaky_fail += len(fails)
            wasted_s += sum(r["job_s"] for r in fails)
            for r in fails:
                tests.update(r.get("failed_tests", [])[:50])
        elif fails and not oks:
            broken += 1
            # tests failing in only some attempts of an always-failing group are flaky too
            common = set.intersection(*[set(r.get("failed_tests", [])) for r in fails]) if fails else set()
            for r in fails:
                tests.update(t for t in r.get("failed_tests", []) if t not in common)
    groups = len(by_group)
    # a workflow run fails if any group fails: P(run fails flakily) from per-group attempt rates
    per_group_rate = {g: sum(1 for r in v if r["exit"] != 0) / len(v) for g, v in by_group.items()
                      if any(r["exit"] == 0 for r in v)}
    p_run_ok = 1.0
    for g, v in by_group.items():
        if g in per_group_rate:
            p_run_ok *= 1 - per_group_rate[g]
    return {"name": spec["name"], "groups": groups, "attempts": attempts, "flaky_failed_attempts": flaky_fail,
            "always_failing_groups": broken, "flaky_job_rate": flaky_fail / attempts if attempts else None,
            "flaky_run_rate": 1 - p_run_ok if groups else None,
            "mean_job_min": statistics.fmean(job_s) / 60 if job_s else None,
            "wasted_min_per_job": wasted_s / 60 / attempts if attempts else None,
            "flaky_tests": tests.most_common(15)}


def main(argv):
    run_ids = argv or sorted(p.name for p in RES.iterdir() if p.is_dir())
    summary = {"walk": {}, "flaky": {}, "agent": {}, "finer": {}}
    for rid in run_ids:
        base = RES / rid
        walk = defaultdict(list)
        for p in sorted((base / "walk").glob("*.json*")) if (base / "walk").exists() else []:
            d = load(p)
            walk[d["spec"]["name"]].append(d)
        for name, shards in walk.items():
            spec = shards[0]["spec"]
            nsh = shards[0].get("nshards", 1)
            if len(shards) != nsh:
                print(f"warning: {name}: {len(shards)}/{nsh} shards")
            summary["walk"][name] = walk_summary(shards, spec)
        fl = defaultdict(list)
        for p in sorted((base / "flaky").glob("*.json")) if (base / "flaky").exists() else []:
            d = load(p)
            fl[d["name"]].append(d)
        for name, items in fl.items():
            spec = json.loads((SPECS / f"{name}.json").read_text())
            summary["flaky"][name] = flaky_summary(items, spec)
        for p in sorted((base / "agent").glob("*.json*")) if (base / "agent").exists() else []:
            d = load(p)
            key = f"{d['spec']}:{d['label']}"
            spec = json.loads((SPECS / f"{d['spec']}.json").read_text())
            prs = []
            for pr in d["prs"]:
                r = pr["result"]
                if "transitions" not in r:
                    continue
                r["spec"] = spec
                s = walk_summary([r], dict(spec, units=dict(spec.get("units", {}), sample=1.0)))
                s["pr"] = pr["pr"]
                prs.append(s)
            summary["agent"][key] = prs
        for p in sorted((base / "finer").glob("*.json*")) if (base / "finer").exists() else []:
            d = load(p)
            summary["finer"][d["repo"]] = finer_summary(d)
    (RES / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print_tables(summary)
    return 0


def finer_summary(d):
    s = d["summary"]
    out = {"evaluated": s.get("evaluated"), "config_strict": s.get("config_strict")}
    for key in ("strict/line", "strict/file", "strict/line+guard", "strict/file+guard", "strict/line+nameguard",
                "strict/line+names", "relaxed/line+names", "relaxed/line+guard", "relaxed/line", "strict/closure"):
        if key in s:
            out[key] = {"time": s[key]["share_time"], "count": s[key]["share_count"],
                        "outcome_changed": s[key]["outcome_changed"], "path_changed": s[key].get("path_changed"),
                        "path_checked": s[key].get("path_checked")}
    ok = [t for t in d["transitions"] if t.get("status") == "ok"]
    out["names_reasons"] = dict(Counter(r for t in ok for r, n in
                                        t["results"]["strict/line+names"]["reasons"].items() for _ in range(1)))
    out["names_hard_files"] = Counter(w.split(" ")[0] for t in ok for f, ws in (t.get("names") or {}).get(
        "file_hard", {}).items() for w in ws[:1]).most_common(10)
    oc = [(t["sha"][:10], t["results"]["strict/line+names"]["outcome_changed_examples"]) for t in ok
          if t["results"]["strict/line+names"]["outcome_changed"]]
    out["names_outcome_changed"] = oc
    return out


def pct(x):
    return "n/a" if x is None else f"{100 * x:.0f}%"


def print_tables(s):
    for name, w in s["walk"].items():
        print(f"\n== {name} ({w['lang']}, sample {w['sample']}, {w['units']} units, {w['tests']} tests, "
              f"{w['transitions']} transitions, overhead x{w['capture_overhead_ratio']})")
        for r in rules_for(w["lang"]):
            if w.get(r) and w[r]["time"]:
                print(f"  {r:16s} time median {pct(w[r]['time']['median'])} mean {pct(w[r]['time']['mean'])}  "
                      f"count median {pct((w[r]['count'] or {}).get('median'))} mean {pct((w[r]['count'] or {}).get('mean'))}"
                      f"  ttg after median {w[r]['ttg_after_s']['median']:.0f}s mean {w[r]['ttg_after_s']['mean']:.0f}s")
        if w.get("ttg_before_s"):
            print(f"  ttg before median {w['ttg_before_s']['median']:.0f}s mean {w['ttg_before_s']['mean']:.0f}s")
        print(f"  invalidate all: {w['invalidate_all']} {w['invalidate_all_why']}  verify {w['verify']}")
    for name, f in s["flaky"].items():
        print(f"\n== reruns {name}: {f}")
    for k, prs in s["agent"].items():
        print(f"\n== agent {k}: {len(prs)} PRs")
        for p in prs:
            c = p.get("closure") or {}
            print(f"  PR {p['pr']['number']} commits {p['transitions']} closure time median "
                  f"{pct((c.get('time') or {}).get('median'))} mean {pct((c.get('time') or {}).get('mean'))}")
    for k, f in s["finer"].items():
        print(f"\n== finer {k}: " + json.dumps({kk: (vv["time"] if isinstance(vv, dict) and "time" in vv else vv)
                                                 for kk, vv in f.items()}, default=str)[:900])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
