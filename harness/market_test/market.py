#!/usr/bin/env python3
"""Market test tables: per repository, the share of test time skippable with proof (closure v3), the commits that
invalidate everything and why, verified skips, the full suite's test time and the minutes saved per month.

    python3 harness/market_test/market.py RUN_ID [RUN_ID ...] [--json out.json] [--md]

Two views of the share:
  * ``all units``: every sampled test file, as in harness/skip_study2 (a unit whose cached outcome is a failure
    always reruns, so a file that fails at every commit counts as never skippable);
  * ``env-ok units`` (main number): test files that failed at the first commit's plain baseline run are left out.
    These fail in our runner for reasons outside the commit walk (a missing service, extra or credential that the
    project's CI provides in a separate job); their count is printed.

Minutes saved per month (ESTIMATED) = default-branch commits per month (MEASURED over the walked window) x full
suite test minutes (sample cost / sample share, ESTIMATED when sampled) x mean share skipped. One CI run per
default-branch commit; pull request runs are not counted.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import aggregate  # noqa: E402

RES = HERE / "results"

# default-branch first-parent commits from 2026-08-17 to 2026-11-17 (92 days), MEASURED with
# git rev-list --first-parent --count --since=2026-08-17T00:00:00Z HEAD on a full clone, 2026-11-17
COMMITS_92D = {"airflow": 2749, "integrations-core": 728, "moto": 269, "transformers": 1216, "mlflow": 1500,
               "pydantic-ai": 2610, "prefect": 596, "esphome": 3320, "litellm": 4788, "community-general": 287,
               "haystack": 833, "mlflow-dev": 1500, "mlflow-dev-late": 1500, "litellm-late": 4788, "litellm-mid": 4788, "integrations-core-late": 728, "home-assistant": 9027}
DAYS = 92


def shards_of(run_ids):
    out = {}
    for rid in run_ids:
        d = RES / rid / "walk"
        walk = defaultdict(list)
        for p in sorted(d.glob("*.json*")) if d.exists() else []:
            x = aggregate.load(p)
            walk[x["spec"]["name"]].append(x)
        out.update(walk)  # a later run replaces an earlier one
    return out


def baseline_failing(shards):
    bad = set()
    for sh in shards:
        for u, c in (sh.get("units") or {}).items():
            if c and not c.get("est") and c.get("code") not in (0, 5):
                bad.add(u)
    return bad


def drop_units(shards, bad):
    out = []
    for sh in shards:
        sh = dict(sh)
        sh["units"] = {u: c for u, c in (sh.get("units") or {}).items() if u not in bad}
        out.append(sh)
    return out


def blockers(shards, bad=frozenset(), top=12):
    """Why closure reran units, by path of the first reason, counted over unit-transitions (all shards)."""
    by_i = defaultdict(list)
    for sh in shards:
        for t in sh.get("transitions", []):
            by_i[t["i"]].append(t)
    paths, kinds = Counter(), Counter()
    for i, ts in by_i.items():
        if len(ts) != len(shards):
            continue
        for t in ts:
            for u, d in (t.get("decisions") or {}).items():
                if u in bad:
                    continue
                r = (d or {}).get("closure")
                if r:
                    kinds[r] += 1
            for k, n in (t.get("why_paths") or {}).items():
                paths[k] += n  # includes baseline-failing units (why_paths is not per unit)
    return kinds.most_common(top), paths.most_common(top)


def inval_detail(shards, bad, frac_threshold=0.01):
    """Per commit that invalidates (almost) all env-ok units: the most common first-reason path."""
    by_i = defaultdict(list)
    for sh in shards:
        for t in sh.get("transitions", []):
            by_i[t["i"]].append(t)
    out = []
    for i, ts in sorted(by_i.items()):
        if len(ts) != len(shards):
            continue
        c = Counter()
        for t in ts:
            for k, n in (t.get("why_paths") or {}).items():
                c[k] += n
        out.append({"i": i, "sha": ts[0]["sha"], "top": c.most_common(3)})
    return {x["i"]: x for x in out}


def full_suite_s(summary_units, frac):
    return sum(c["test"] for c in summary_units.values()) / frac


def summarize(name, shards):
    spec = shards[0]["spec"]
    frac = spec.get("units", {}).get("sample", 1.0)
    nsh = shards[0].get("nshards", 1)
    bad = baseline_failing(shards)
    s_all = aggregate.walk_summary(shards, spec)
    s_ok = aggregate.walk_summary(drop_units(shards, bad), spec)
    units = {}
    for sh in shards:
        units.update({u: c for u, c in (sh.get("units") or {}).items() if c})
    walls = sorted(c["wall"] for c in units.values() if c.get("wall"))
    base = walls[max(0, int(len(walls) * 0.05) - 1)] if walls else 0.0
    cost = {u: max(c["test"], c.get("wall", 0.0) - base) for u, c in units.items()}
    full_all = sum(cost.values()) / frac
    full_ok = sum(v for u, v in cost.items() if u not in bad) / frac
    wall_all = sum(c.get("wall", 0) for c in units.values()) / frac
    cpd = s_all.get("commits_per_day")
    kinds, paths = blockers(shards, bad)
    inv = inval_detail(shards, bad)
    inval_commits = [r["i"] for r in s_ok["rows"] if r["closure"] < 0.01]
    inval_paths = Counter()
    for i in inval_commits:
        top = inv.get(i, {}).get("top") or []
        if top:
            inval_paths[top[0][0]] += 1
    shas = {t["i"]: t["sha"] for sh in shards for t in sh.get("transitions", [])}
    for rows_ in (s_ok["rows"], s_all["rows"]):
        for r in rows_:
            r["sha"] = shas.get(r["i"])
    out_rows_all = s_all["rows"]
    cl_ok, cl_all = s_ok["closure"]["time"], s_all["closure"]["time"]
    vr = s_all["verify"]
    out = {
        "name": name, "url": spec["url"], "sample": frac, "shards": nsh, "transitions": s_ok["transitions"],
        "units_sampled": len(units), "units_baseline_failing": len(bad), "tests_sampled": s_all["tests"],
        "skip_time_ok": cl_ok, "skip_time_all": cl_all, "skip_count_ok": s_ok["closure"]["count"],
        "invalidate_all_ok": len(inval_commits), "invalidate_all_why_kind": s_ok["invalidate_all_why"],
        "invalidate_all_why_path": dict(inval_paths.most_common(8)),
        "verified": vr.get("checked", 0), "wrong": vr.get("wrong", 0), "flaky": vr.get("flaky", 0),
        "wrong_hits": s_all["wrong_hits"], "flaky_in_verify": s_all["flaky_in_verify"],
        "full_suite_test_s": full_all, "full_suite_test_s_ok": full_ok, "full_suite_unit_wall_s": wall_all,
        "commits_per_day": cpd, "capture_overhead": s_all["capture_overhead_ratio"],
        "rerun_kinds": kinds, "rerun_paths": paths, "rows": s_ok["rows"], "rows_all": out_rows_all,
    }
    if name in COMMITS_92D:
        cpd = COMMITS_92D[name] / DAYS  # the 92-day rate, not the 50-commit window (too noisy)
    out["commits_per_day"], out["commits_per_day_window"] = cpd, s_all.get("commits_per_day")
    if cpd and cl_ok:
        per_month = cpd * 30.44
        out["commits_per_month"] = per_month
        out["full_suite_min_month"] = per_month * full_ok / 60
        out["saved_min_month"] = per_month * full_ok / 60 * cl_ok["mean"]
    return out


def merge_late(early, late):
    """Early window (the 51-commit walk, stopped by the time budget) + late window (the newest commits, walked
    from a fresh baseline): transitions of the late window whose commit the early window already reached are
    dropped. Verified skips add up (they are separate fresh reruns)."""
    seen = {r["sha"] for r in early["rows"]}
    rows = early["rows"] + [r for r in late["rows"] if r["sha"] not in seen]
    seen_all = {r["sha"] for r in early["rows_all"]}
    rows_all = early["rows_all"] + [r for r in late["rows_all"] if r["sha"] not in seen_all]
    m = dict(early)
    m["rows"], m["rows_all"], m["transitions"] = rows, rows_all, len(rows)
    m["windows"] = (early.get("windows", f"early {len(early['rows'])}") +
                    f" + {late['name'].rsplit('-', 1)[-1]} {len(rows) - len(early['rows'])}")
    m["skip_time_ok"] = aggregate.stats([r["closure"] for r in rows])
    m["skip_time_all"] = aggregate.stats([r["closure"] for r in rows_all])
    m["invalidate_all_ok"] = sum(1 for r in rows if r["closure"] < 0.01)
    for k in ("verified", "wrong", "flaky"):
        m[k] = early[k] + late[k]
    m["wrong_hits"] = early["wrong_hits"] + late["wrong_hits"]
    m["flaky_in_verify"] = early["flaky_in_verify"] + late["flaky_in_verify"]
    m["rerun_kinds"] = (Counter(dict(early["rerun_kinds"])) + Counter(dict(late["rerun_kinds"]))).most_common(12)
    m["rerun_paths"] = (Counter(dict(early["rerun_paths"])) + Counter(dict(late["rerun_paths"]))).most_common(12)
    ip = Counter(early["invalidate_all_why_path"]) + Counter(late["invalidate_all_why_path"])
    m["invalidate_all_why_path"] = dict(ip.most_common(8))
    if m.get("full_suite_min_month") is not None:
        m["saved_min_month"] = m["full_suite_min_month"] * m["skip_time_ok"]["mean"]
    return m


def pct(x):
    return "-" if x is None else f"{100 * x:.0f}%"


def print_md(rows):
    print("| repository | transitions | sample (units) | baseline-failing units | time skipped median / mean "
          "(env-ok) | same, all units | invalidate all (top cause) | verified skips (wrong, flaky) | full suite "
          "test min per run | commits per month | min saved per month |")
    print("|---|---:|---|---:|---:|---:|---|---|---:|---:|---:|")
    for r in rows:
        ok, al = r["skip_time_ok"] or {}, r["skip_time_all"] or {}
        why = ", ".join(f"{k} {v}" for k, v in list(r["invalidate_all_why_path"].items())[:3]) or "-"
        print(f"| {r['name']} | {r['transitions']} | {r['sample']:.0%} ({r['units_sampled']}) | "
              f"{r['units_baseline_failing']} | {pct(ok.get('median'))} / {pct(ok.get('mean'))} | "
              f"{pct(al.get('median'))} / {pct(al.get('mean'))} | {r['invalidate_all_ok']}/{r['transitions']} ({why}) | "
              f"{r['verified']} ({r['wrong']}, {r['flaky']}) | {r['full_suite_test_s_ok'] / 60:.0f} | "
              f"{r.get('commits_per_month', 0):.0f} | {r.get('saved_min_month', 0):.0f} |")


def main(argv):
    run_ids = [a for a in argv if not a.startswith("--")]
    js = argv[argv.index("--json") + 1] if "--json" in argv else None
    if js:
        run_ids.remove(js)
    rows = []
    for name, shards in sorted(shards_of(run_ids).items()):
        nsh = shards[0].get("nshards", 1)
        if len(shards) != nsh:
            print(f"warning: {name}: {len(shards)}/{nsh} shards", file=sys.stderr)
        try:
            rows.append(summarize(name, shards))
        except Exception as e:  # noqa: BLE001
            print(f"{name}: {type(e).__name__}: {e}", file=sys.stderr)
    by = {r["name"]: r for r in rows}
    extra = [r for r in rows if r["name"].rsplit("-", 1)[-1] in ("mid", "late")
             and r["name"].rsplit("-", 1)[0] in by]
    for r in sorted(extra, key=lambda r: r["name"].endswith("-late")):  # mid before late
        base = r["name"].rsplit("-", 1)[0]
        by[base] = merge_late(by[base], r)
    rows = [by[r["name"]] for r in rows if r not in extra]
    if js:
        Path(js).write_text(json.dumps(rows, indent=1, default=str))
    print_md(rows)
    for r in rows:
        print(f"\n{r['name']}: rerun reasons {r['rerun_kinds'][:6]}")
        print(f"  top paths {r['rerun_paths'][:6]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
