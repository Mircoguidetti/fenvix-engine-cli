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
    if r in ("new", "no-record", "no-result", "network", "go-miss", "cached-failure", "runtime", "env-var"):
        return r
    if r.startswith(("runtime:", "env-var:")):
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


_RECHECK = None

# Re-check verdicts that turn a verification mismatch into "flaky": an explicit allow-list (review R-002 note).
# The label is the verdict text before the first ":". Anything else (including "code-change", "incomplete" or a
# free-text verdict such as "missed dependency") leaves the mismatch counted as a wrong hit.
FLAKY_VERDICTS = frozenset({
    "flaky (plain runs disagree)",                                 # recheck.py
    "not-reproducible",                                            # recheck.py: cached outcome not reproducible
    "not-reproducible (load-sensitive)",                           # recheck.py
    "flaky (same intermittent teardown error at both commits)",    # results/s1/recheck/switchbot-171334-local.json
    "capture-induced flaky failure",                               # results/s1/recheck/knx-163164-local.json
})


def recheck_says_flaky(verdict) -> bool:
    if not isinstance(verdict, str):
        return False
    return verdict.split(":", 1)[0].strip() in FLAKY_VERDICTS


# Display names of the rules in the report tables
RULE_LABEL = {"go-cache": "go test cache (no proof)", "closure": "closure", "strict": "strict"}


def recheck_verdicts():
    """(unit, commit) -> verdict of every re-check of a verification mismatch under results/*/recheck/."""
    global _RECHECK
    if _RECHECK is None:
        _RECHECK = {}
        for p in RES.glob("*/recheck/*.json"):
            try:
                d = json.loads(p.read_text())
            except Exception:
                continue
            v = d.get("verdict")
            if isinstance(v, dict):  # recheck.py: {unit: verdict}
                for u, x in v.items():
                    _RECHECK[(u, d.get("cur"))] = x
            elif isinstance(v, str) and d.get("unit"):
                _RECHECK[(d["unit"], d.get("cur"))] = v
    return _RECHECK


def walk_summary(shards, spec):
    """shards: list of walk results of one repository (same commits, disjoint units)."""
    lang = spec["lang"]
    rules = rules_for(lang)
    frac = spec.get("units", {}).get("sample", 1.0) if lang != "go" else 1.0
    workers = spec.get("ci", {}).get("workers", 4)
    units, by_i = {}, defaultdict(list)
    ovh = []
    # v2 walks did not apply "a cached failure is never reused": approximate it with every unit whose recorded
    # outcome was ever a failure (first run or last record), forced to rerun at every transition (upper bound)
    v2_failing = set()
    has_xverify = any("xverify" in t for sh in shards for t in sh.get("transitions", []))
    v3 = any("cached_fail" in t for sh in shards for t in sh.get("transitions", []))
    for sh in shards:
        units.update({u: c for u, c in (sh.get("units") or {}).items() if c})
        if lang != "go" and not v3:
            v2_failing.update(u for u, c in (sh.get("units") or {}).items() if c and c.get("code") not in (0, 5, None))
            v2_failing.update(u for u, c in (sh.get("unit_info") or {}).items() if c.get("code") not in (0, 5, None))
        for t in sh.get("transitions", []):
            by_i[t["i"]].append(t)
        co = sh.get("capture_overhead") or {}
        if co.get("sum_plain"):
            ovh.append(co["sum_traced"] / co["sum_plain"])
    ratio = statistics.median(ovh) if ovh else None
    if lang != "go":
        # unit cost: test durations, or the unit's wall time minus the fixed process start-up (5th percentile of
        # unit walls), whichever is larger: per-file imports and transforms are paid in CI too
        walls = sorted(c["wall"] for c in units.values() if c.get("wall"))
        base = walls[max(0, int(len(walls) * 0.05) - 1)] if walls else 0.0
        units = {u: dict(c, test=max(c["test"], c.get("wall", 0.0) - base)) for u, c in units.items()}
    per_rule = {r: {"time": [], "count": [], "ttg_after": [], "ttg_after_plain": []} for r in rules}
    ttg_before, inval_all, inval_why, verify = [], 0, Counter(), Counter()
    xverify = {r: Counter() for r in rules}
    closure_ver = Counter()
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
                verdict = classify(v, t)
                verify["checked"] += 1
                # Go: the closure rule's own verified skips are the go-cache hits closure also skipped
                if lang != "go" or v.get("closure_skip", not v.get("potential")):
                    closure_ver["checked"] += 1
                    if verdict:
                        closure_ver[verdict] += 1
                if verdict == "flaky":
                    flaky_v.append({"i": i, **v})
                    verify["flaky"] += 1
                elif verdict == "wrong":
                    wrong.append({"i": i, **v})
                    verify["wrong"] += 1
            for v in t.get("xverify", []):
                verdict = classify(v, t)
                for r in v.get("rules", []):
                    if r in xverify:
                        xverify[r]["checked"] += 1
                        if verdict:
                            xverify[r][verdict] += 1
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
                    "go-cache" if lang == "go" else "closure") or u in v2_failing]
            else:
                must = [u for u in live if (decisions.get(u) or {}).get(r) or u in v2_failing]
            skip_t = tot_t - sum(units[u]["test"] for u in must)
            skip_n = tot_n - sum(units[u]["n"] for u in must)
            per_rule[r]["time"].append(skip_t / tot_t)
            per_rule[r]["count"].append(skip_n / tot_n if tot_n else None)
            k = ratio if (ratio and r not in ("go-cache",) and lang != "go") else 1.0
            w = max(1, round(workers * frac)) if frac < 1 else workers
            per_rule[r]["ttg_after"].append(lpt_makespan([units[u]["test"] * k for u in must], w))
            # the same schedule without the dependency-capture overhead (capture paid only on a sample of runs)
            per_rule[r]["ttg_after_plain"].append(lpt_makespan([units[u]["test"] for u in must], w))
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
           "verify_by_rule": verify_by_rule(lang, rules, verify, closure_ver, xverify, has_xverify),
           "capture": "v3" if v3 else "v2", "v2_failing_forced": len(v2_failing),
           "wrong_hits": wrong[:20], "flaky_in_verify": flaky_v[:20], "rows": rows,
           "commits_per_day": commits_per_day(shards)}
    for r in rules:
        out[r] = {"time": stats(per_rule[r]["time"]), "count": stats(per_rule[r]["count"]),
                  "ttg_after_s": stats(per_rule[r]["ttg_after"]),
                  "ttg_after_plain_s": stats(per_rule[r]["ttg_after_plain"])}
    out["ttg_before_s"] = stats(ttg_before)
    if frac < 1:
        out["ttg_note"] = (f"sample of {frac:.0%} of the test files scheduled on {frac:.0%} of the CI workers "
                           f"(same load per worker as the full suite on {workers} workers)")
    return out


def classify(v, t):
    """None (same outcome), "flaky" or "wrong" for one verification item."""
    if v["same"]:
        return None
    # wrong hit: the fresh outcome differs from the cached one and is reproducible; otherwise the unit is flaky
    reproducible = (v.get("rerun_matches_fresh") == 2) if "rerun_matches_fresh" in v else True
    # a re-check (recheck.py or results/*/recheck/*.json) that reran the unit at the cached commit and found the
    # cached outcome itself not reproducible overrides: flaky, not wrong (accepted verdicts: FLAKY_VERDICTS)
    rc = recheck_verdicts().get((v["unit"], t.get("sha")))
    if v.get("rerun_matches_cache") or not reproducible or recheck_says_flaky(rc):
        return "flaky"
    return "wrong"


def verify_by_rule(lang, rules, verify, closure_ver, xverify, has_xverify):
    """Verified skips per rule: {"checked", "wrong", "flaky"} or None (n/a: the rule's own skips were not compared).

    closure: the random sample of its skips. strict (a subset of closure / go-cache): the same sample. go-cache: its
    sample plus every potential wrong hit. func+guard, func, ~cfg: the closure sample (their skips include every
    closure skip) plus every extra skip, compared in full (``xverify``, walks from version 3 on); n/a before."""
    out = {}
    for r in rules:
        if r == "go-cache" or (r == "strict" and lang == "go"):
            out[r] = dict(verify)
        elif r in ("closure", "strict"):
            out[r] = dict(closure_ver) if lang == "go" else dict(verify)
        elif has_xverify:
            c = Counter(verify)
            c.update(xverify[r])
            out[r] = dict(c, extra=xverify[r].get("checked", 0))
        else:
            out[r] = None
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
    """Reruns of the project's CI test step at one pinned commit.

    A run (one CI group, one attempt) is valid when the step ran tests and its report was read. Per group, the
    *stable failures* are the tests failing in every valid attempt (broken at that commit, not flaky). An attempt
    fails from flakiness when it fails a test outside the stable set (or exits non-zero with no failed test while
    other attempts exit 0)."""
    by_group = defaultdict(list)
    invalid = 0
    for it in items:
        if it.get("status") == "ok" and not it.get("report_error") and it.get("tests"):
            by_group[it["group"]].append(it)
        else:
            invalid += 1
    attempts = sum(len(v) for v in by_group.values())
    flaky_fail, wasted_s, job_s = 0, 0.0, []
    tests = Counter()
    stable_fail = 0
    per_group_rate = {}
    for g, runs in by_group.items():
        job_s += [r["job_s"] for r in runs]
        sets = [set(r.get("failed_tests") or []) for r in runs]
        common = set.intersection(*sets) if sets else set()
        stable_fail = max(stable_fail, len(common))
        n_bad = 0
        for r, fs in zip(runs, sets):
            extra = fs - common
            bad = bool(extra) or (r["exit"] != 0 and not fs and any(x["exit"] == 0 for x in runs))
            if bad:
                n_bad += 1
                wasted_s += r["job_s"]
                tests.update(sorted(extra)[:50])
        flaky_fail += n_bad
        per_group_rate[g] = n_bad / len(runs)
    groups = len(by_group)
    p_run_ok = 1.0
    for g, rate in per_group_rate.items():
        p_run_ok *= 1 - rate
    return {"name": spec["name"], "sha": (items[0].get("sha") if items else None), "groups": groups,
            "ci_groups": spec.get("ci_groups", 1), "attempts": attempts, "invalid_attempts": invalid,
            "min_attempts_per_group": min((len(v) for v in by_group.values()), default=0),
            "tests_per_attempt": statistics.median([r["tests"] for v in by_group.values() for r in v]) if attempts else 0,
            "flaky_failed_attempts": flaky_fail, "stable_failing_tests": stable_fail,
            "always_failing_groups": sum(1 for v in by_group.values() if all(r["exit"] != 0 for r in v)),
            "flaky_job_rate": flaky_fail / attempts if attempts else None,
            "flaky_run_rate": 1 - p_run_ok if groups else None,
            "mean_job_min": statistics.fmean(job_s) / 60 if job_s else None,
            "wasted_min_per_job": wasted_s / 60 / attempts if attempts else None,
            "flaky_tests": tests.most_common(15)}


def main(argv):
    md = "--md" in argv
    argv = [a for a in argv if a != "--md"]
    run_ids = argv or sorted(p.name for p in RES.iterdir() if p.is_dir())
    summary = {"walk": {}, "flaky": {}, "agent": {}, "finer": {}}
    fl_all = defaultdict(list)
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
        for p in sorted((base / "flaky").glob("*.json")) if (base / "flaky").exists() else []:
            d = load(p)
            fl_all[(d["name"], d.get("sha"))].append(d)  # reruns of one commit pooled across runs
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
            pooled = {}
            for r in rules_for(spec["lang"]):
                pooled[r] = stats([row.get(r) for p in prs for row in p["rows"]])
            vbr = {}
            for r in rules_for(spec["lang"]):
                per = [p["verify_by_rule"].get(r) for p in prs]
                vbr[r] = None if any(x is None for x in per) else dict(sum((Counter(
                    {k: n for k, n in x.items() if isinstance(n, int)}) for x in per), Counter()))
            summary["agent"][key] = {"prs": prs, "pooled_time": pooled,
                                     "pushes": sum(len(p["rows"]) for p in prs), "verify_by_rule": vbr,
                                     "verify": dict(sum((Counter(p["verify"]) for p in prs), Counter())),
                                     "wrong": [w for p in prs for w in p["wrong_hits"]]}
        for p in sorted((base / "finer").glob("*.json*")) if (base / "finer").exists() else []:
            d = load(p)
            summary["finer"][d["repo"]] = finer_summary(d)
    for (name, sha), items in fl_all.items():
        spec = json.loads((SPECS / f"{name}.json").read_text())
        fs = flaky_summary(items, spec)
        if fs["attempts"] or name not in summary["flaky"]:
            summary["flaky"][name] = fs
    (RES / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    if md:
        print_md(summary)
    else:
        print_tables(summary)
    return 0


def finer_summary(d):
    s = d["summary"]
    out = {"evaluated": s.get("evaluated"), "config_strict": s.get("config_strict")}
    for key in ("relaxed/closure", "strict/line", "strict/file", "strict/line+guard", "strict/file+guard", "strict/line+nameguard",
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
    for k, ag in s["agent"].items():
        prs = ag["prs"]
        print(f"\n== agent {k}: {len(prs)} PRs, {ag['pushes']} pushes, verify {ag['verify']}")
        for r, st in ag["pooled_time"].items():
            if st:
                print(f"  pooled {r:16s} time median {pct(st['median'])} mean {pct(st['mean'])}")
        for p in prs:
            c = p.get("closure") or {}
            print(f"  PR {p['pr']['number']} commits {p['transitions']} closure time median "
                  f"{pct((c.get('time') or {}).get('median'))} mean {pct((c.get('time') or {}).get('mean'))}")
    for k, f in s["finer"].items():
        print(f"\n== finer {k}: " + json.dumps({kk: (vv["time"] if isinstance(vv, dict) and "time" in vv else vv)
                                                 for kk, vv in f.items()}, default=str)[:900])


def ms(st, nd=0):
    """'median / mean' of a stats dict, in percent."""
    if not st:
        return "n/a"
    return f"{100 * st['median']:.{nd}f}% / {100 * st['mean']:.{nd}f}%"


def print_md(s):
    """Report-ready markdown tables (every number MEASURED on the stated sample)."""
    print("| project | lang | transitions | units (sample) | rule | time skipped median / mean | tests skipped "
          "median / mean | time to green before -> after (after without capture overhead), median / mean | invalidate all (why) | verified skips "
          "(wrong, flaky) |")
    print("|---|---|---:|---|---|---:|---:|---|---|---|")
    for name, w in s["walk"].items():
        if not w["transitions"]:
            continue
        why = ", ".join(f"{k} {n}" for k, n in sorted(w["invalidate_all_why"].items(), key=lambda x: -x[1]))
        inv = f"{w['invalidate_all']}/{w['transitions']} ({why or '-'})"
        tb = w.get("ttg_before_s") or {}
        for r in rules_for(w["lang"]):
            x = w.get(r) or {}
            if not x.get("time"):
                continue
            v = (w.get("verify_by_rule") or {}).get(r, w["verify"]) if "verify_by_rule" in w else w["verify"]
            ver = "n/a" if v is None else f"{v.get('checked', 0)} ({v.get('wrong', 0)}, {v.get('flaky', 0)})"
            ta = x.get("ttg_after_s") or {}
            tp = x.get("ttg_after_plain_s") or {}
            ttg = (f"{tb.get('median', 0):.0f}s -> {ta.get('median', 0):.0f}s ({tp.get('median', 0):.0f}s) / "
                   f"{tb.get('mean', 0):.0f}s -> {ta.get('mean', 0):.0f}s ({tp.get('mean', 0):.0f}s)") if tb else "n/a"
            print(f"| {name} | {w['lang']} | {w['transitions']} | {w['units']} ({w['sample']:.0%}) | {RULE_LABEL.get(r, r)} | "
                  f"{ms(x['time'])} | {ms(x['count'])} | {ttg} | {inv} | {ver} |")
    if s["agent"]:
        print()
        print("| repository : agent | PRs | pushes | rule | time skipped per push median / mean | verified (wrong, flaky) |")
        print("|---|---:|---:|---|---:|---|")
        for k, ag in s["agent"].items():
            for r, st in ag["pooled_time"].items():
                if st:
                    v = ag.get("verify_by_rule", {}).get(r, ag["verify"]) if ag.get("verify_by_rule") else ag["verify"]
                    ver = "n/a" if v is None else f"{v.get('checked', 0)} ({v.get('wrong', 0)}, {v.get('flaky', 0)})"
                    print(f"| {k} | {len(ag['prs'])} | {ag['pushes']} | {RULE_LABEL.get(r, r)} | {ms(st)} | {ver} |")
    if s["flaky"]:
        print()
        print("| suite (commit) | CI groups rerun (of) | tests per group run | attempts (min per group) | "
              "attempts failed by flakiness | tests failing in every attempt | flaky full-run rate | mean job min | "
              "flaky tests |")
        print("|---|---:|---:|---:|---:|---:|---:|---:|---|")
        for name, f in s["flaky"].items():
            ft = ", ".join(f"{t} x{n}" for t, n in f["flaky_tests"][:4])
            print(f"| {name} ({(f.get('sha') or '')[:8]}) | {f['groups']} ({f.get('ci_groups', 1)}) | "
                  f"{f.get('tests_per_attempt', 0):.0f} | {f['attempts']} ({f.get('min_attempts_per_group', 0)}) | "
                  f"{f['flaky_failed_attempts']} | {f.get('stable_failing_tests', 0)} | {pct(f['flaky_run_rate'])} | "
                  f"{f['mean_job_min'] or 0:.1f} | {ft or '-'} |")
    if s["finer"]:
        keys = ["strict/closure", "relaxed/closure", "strict/file+guard", "strict/line+guard", "strict/line+names", "strict/line",
                "relaxed/line+guard", "relaxed/line+names", "relaxed/line"]
        print()
        print("| library | transitions | config (strict) | " + " | ".join(keys) + " |")
        print("|---|---:|---:|" + "---:|" * len(keys))
        agg = {k: ([], []) for k in keys}
        for repo, f in s["finer"].items():
            cells = []
            for k in keys:
                x = f.get(k)
                if not x:
                    cells.append("n/a")
                    continue
                agg[k][0].append(x["time"]["median"])
                agg[k][1].append(x["time"]["mean"])
                bad = f" **{x['outcome_changed']} wrong**" if x["outcome_changed"] else ""
                cells.append(f"{100 * x['time']['median']:.0f}/{100 * x['time']['mean']:.0f}{bad}")
            print(f"| {repo} | {f['evaluated']} | {f['config_strict']} | " + " | ".join(cells) + " |")
        print("| **median of medians / mean of means** | | | " + " | ".join(
            f"{100 * statistics.median(a):.0f}/{100 * statistics.fmean(b):.0f}" if a else "n/a"
            for a, b in agg.values()) + " |")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
