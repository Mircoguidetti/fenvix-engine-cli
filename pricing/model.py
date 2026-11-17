#!/usr/bin/env python3
"""Pricing model: cost of one CI run on GitHub Actions vs on fenvix (AWS + skip-with-proof).

Every input carries a label in a comment: MEASURED / ESTIMATED / DECLARED / UNKNOWN.
Run: python3 pricing/model.py  -> prints the markdown tables used in pricing/REPORT.md
and writes pricing/data/results.json.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

# ---------------------------------------------------------------- prices
# GitHub-hosted runners, USD per minute, private repositories.
# DECLARED (GitHub docs "Actions runner pricing", prices effective 2026-01-01), to be verified:
# web access was blocked in this session.
GH = {
    "linux2": 0.006, "linux4": 0.012, "linux8": 0.022, "linux16": 0.042,
    "win2": 0.010, "win8": 0.042, "mac": 0.062,
}
# DECLARED (same page, prices valid through 2025), to be verified: the old list prices.
GH_2025 = {"linux2": 0.008, "linux4": 0.016, "linux8": 0.032, "linux16": 0.064,
           "win2": 0.016, "win8": 0.064, "mac": 0.08}

# AWS EC2 Linux, us-east-1, USD per hour. DECLARED (AWS EC2 on-demand pricing page, 2025 list), to be verified.
AWS_OD = {"m7i.xlarge": 0.2016, "c7i.xlarge": 0.1785, "c7a.xlarge": 0.20527, "c8g.xlarge": 0.15952,
          "m7i.2xlarge": 0.4032, "c8g.2xlarge": 0.31904}
SPOT_FRACTION = 0.35   # ESTIMATED: spot price ~35% of on-demand for these families (varies by AZ/hour)
SPOT_MIX = 0.8         # ESTIMATED: 80% of minutes on spot, 20% on-demand fallback
UTILISATION = 0.70     # ESTIMATED: billed machine time that runs customer work (warm pool, per-second tails)
INFRA_ADD = 0.15       # ESTIMATED: EBS, S3 cache, egress/NAT, control plane, as a share of compute
FIXED_MIN = 1.0        # ESTIMATED: per run start-up + cache lookup + result upload, machine-minutes


def aws_rate(instance="m7i.xlarge", spot=True):
    """Effective USD per 4-vCPU machine-minute for us."""
    od = AWS_OD[instance] / 60
    raw = SPOT_MIX * od * SPOT_FRACTION + (1 - SPOT_MIX) * od if spot else od
    return raw / UTILISATION * (1 + INFRA_ADD)


# ---------------------------------------------------------------- run shapes
# Minutes are 4-vCPU job minutes (GitHub ubuntu-latest for public repos = 4 vCPU; MEASURED runner in our studies).
# A private repo on the default 2-core runner pays $0.006 for about twice the minutes on CPU-bound suites
# (idle study: median 2.76 busy cores of 4, MEASURED), i.e. about the same money as 4-core at $0.012.
# test jobs: (count, setup_min, test_min, skippable, envs)
#   envs = distinct environments (matrix variants); jobs of one env (shards) can be merged on our side.
#   setup = runner boot + checkout + install; test = the test step. skippable = covered by the measured skip share.
PROJECTS = {
    "large modular monorepo (home-assistant)": dict(
        test_jobs=[(10, 2.2, 7.0, True, 1),    # pytest-full: install 1.2 + test 7.0 MEASURED; +1.0 boot ESTIMATED
                   (12, 3.0, 3.0, True, 12)],   # recorder on 7 MariaDB/MySQL + 3 Postgres + 2 SQLite: ESTIMATED
        other_linux=80.0,                   # prek, pylint x2, mypy, hassfest, builds, coverage...: ESTIMATED
        win=0.0, win8=0.0, mac=0.0, linux8=0.0,
        skip=(0.97, 0.82),                  # closure v3, median / mean: MEASURED (12% sample)
        capture=2.06,                       # strace overhead traced/plain: MEASURED
        note="full run (dev pushes, core changes). HA's own CI already runs only touched integrations on "
             "integration-only PRs, so its real average is lower."),
    "JS monorepo (docusaurus)": dict(
        test_jobs=[(2, 1.8, 0.3, True, 2),     # unit: install+build 0.7 + test 0.3 MEASURED; +1.0 boot ESTIMATED
                   (14, 3.0, 4.0, False, 14)],  # e2e (yarn/npm/pnpm/bun) + swizzle: ESTIMATED; skip UNKNOWN
        other_linux=86.0, linux8=10.0,      # build-perf, builds, lighthouse, lint, codeql...; argos on 8-core: ESTIMATED
        win=0.0, win8=35.0, mac=0.0,        # tests-windows x2 + e2e-windows on windows-8-core: ESTIMATED
        skip=(0.98, 0.81), capture=1.54,    # MEASURED
        note="the measured skip covers only the 0.3 min unit step; e2e jobs are 95% of test minutes"),
    "tightly coupled library (vue-core)": dict(
        test_jobs=[(1, 1.2, 0.5, True, 1),     # unit: install 0.2 + test 0.5 MEASURED; +1.0 boot ESTIMATED
                   (1, 3.0, 3.0, False, 1)],   # e2e (puppeteer/playwright): ESTIMATED
        other_linux=11.0, win=3.0, win8=0.0, mac=0.0, linux8=0.0,
        skip=(0.25, 0.31), capture=1.56,    # MEASURED
        note=""),
    "Go service, small (terraform)": dict(
        test_jobs=[(1, 1.4, 4.8, True, 1),     # unit-tests: install 0.4 + test 4.8 MEASURED; +1.0 boot ESTIMATED
                   (1, 1.5, 7.0, True, 1),     # race-tests: ESTIMATED
                   (1, 1.5, 3.0, False, 1)],   # e2e-tests: ESTIMATED
        other_linux=12.0, win=0.0, win8=0.0, mac=0.0, linux8=0.0,
        skip=(0.25, 0.23), capture=1.3,     # skip MEASURED (closure v3); capture ESTIMATED (not recorded for Go)
        note="PR run; the 36-job release build runs on main pushes only"),
    "Go service, large (prometheus)": dict(
        test_jobs=[(4, 2.0, 10.0, True, 4),    # test_go, test_go_more, test_go_386, test_go_oldest: ESTIMATED
                   (6, 2.0, 3.0, False, 6)],   # version-upgrade x3, test_ui, mixins, compliance: ESTIMATED
        other_linux=54.0, win=25.0, win8=0.0, mac=0.0, linux8=0.0,
        skip=(0.56, 0.49), capture=1.3,     # skip MEASURED (closure v3); capture ESTIMATED
        note=""),
    "Django app (saleor)": dict(
        test_jobs=[(1, 4.0, 14.0, True, 1)],   # one unit_tests job, pytest -n logical: ESTIMATED from 46 CPU-min MEASURED
        other_linux=18.0, win=0.0, win8=0.0, mac=0.0, linux8=0.0,
        skip=(0.0, 0.13), capture=2.63,     # MEASURED (29 transitions, partial)
        note="Django loads every app in every test process"),
    "small library (flask-like)": dict(
        test_jobs=[(8, 1.2, 0.3, True, 8)],    # 8 Linux Python versions: ESTIMATED
        other_linux=3.5, win=2.5, win8=0.0, mac=2.0, linux8=0.0,
        skip=(0.0, 0.22), capture=1.5,      # skip MEASURED (first study, 14 libraries); capture ESTIMATED
        note=""),
}

MACHINE_TARGET_MIN = 10.0  # ESTIMATED: we split executed work into machines of ~10 min wall


def github_cost(p, gh=GH, runner="linux4"):
    """Returns (test-job minutes, cost of test jobs we take over, cost of the whole run)."""
    test_min = sum(n * (s + t) for n, s, t, *_ in p["test_jobs"])
    if runner == "linux4":
        test_cost = test_min * gh["linux4"]
    else:  # bigger runner: setup unchanged, test step scales with Amdahl (85% parallel, ESTIMATED)
        k = {"linux8": 2, "linux16": 4}[runner]
        mins = sum(n * (s + t * (0.15 + 0.85 / k)) for n, s, t, *_ in p["test_jobs"])
        test_cost = mins * gh[runner]
    other = p["other_linux"] * gh["linux4"] + p["linux8"] * gh["linux8"] + p["win"] * gh["win2"] \
        + p["win8"] * gh["win8"] + p["mac"] * gh["mac"]
    return test_min, test_cost, test_cost + other


def fenvix_minutes(p, share, capture=None):
    """Machine-minutes per run on our side. Setup is paid once per environment and per ~10-min machine
    in which at least one unit runs (conservative: every environment is assumed to run something)."""
    capture = p["capture"] if capture is None else capture
    total = FIXED_MIN
    for n, s, t, sk, envs in p["test_jobs"]:
        if not sk:
            total += n * (s + t)            # not covered by the measured skip: run as today
            continue
        executed = n * t * (1 - share) * capture
        if executed <= 0.01:
            continue
        per_env = executed / envs
        machines = envs * math.ceil(per_env / MACHINE_TARGET_MIN)
        total += machines * s + executed
    return total


def band(cost, gh_test, saving, margin=0.70):
    lo = cost / (1 - margin)          # price that keeps our gross margin at `margin`
    hi = gh_test * (1 - saving)       # price that keeps the customer `saving` cheaper on those jobs
    return lo, hi


def row(name, p, which="median", runs=500, capture=None, runner="linux4", rate=None, share=None):
    rate = aws_rate() if rate is None else rate
    s = share if share is not None else p["skip"][0 if which == "median" else 1]
    tmin, gtest, gall = github_cost(p, runner=runner)
    fmin = fenvix_minutes(p, s, capture)
    cost = fmin * rate
    lo30, hi30 = band(cost, gtest, 0.30)
    lo50, hi50 = band(cost, gtest, 0.50)
    return dict(project=name, share=s, gh_test_min=tmin, gh_test_cost=gtest, gh_run_cost=gall,
                fx_min=fmin, fx_cost=cost, runs=runs,
                lo=lo30 * runs, hi30=hi30 * runs, hi50=hi50 * runs,
                gh_test_month=gtest * runs, gh_run_month=gall * runs, fx_month=cost * runs)


def fmt_band(lo, hi):
    return f"${lo:,.0f}-{hi:,.0f}" if lo <= hi else f"none (floor ${lo:,.0f} > ceiling ${hi:,.0f})"


def table(rows, title):
    out = [f"### {title}", "",
           "| project type | skip share | GitHub test-job min / run | GitHub $ test jobs / run | GitHub $ whole run | "
           "fenvix machine-min / run | fenvix AWS $ / run | GitHub $ test jobs / 500 | fenvix AWS $ / 500 | "
           "price band / 500, customer >=30% cheaper | price band / 500, >=50% cheaper |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    for r in rows:
        out.append(f"| {r['project']} | {r['share']:.0%} | {r['gh_test_min']:.0f} | ${r['gh_test_cost']:.2f} | "
                   f"${r['gh_run_cost']:.2f} | {r['fx_min']:.1f} | ${r['fx_cost']:.3f} | ${r['gh_test_month']:,.0f} | "
                   f"${r['fx_month']:,.0f} | {fmt_band(r['lo'], r['hi30'])} | {fmt_band(r['lo'], r['hi50'])} |")
    return "\n".join(out) + "\n"


def main():
    res = {"aws_rate_spotmix_m7i": aws_rate(), "aws_rate_od_m7i": aws_rate(spot=False),
           "aws_rate_spotmix_c8g": aws_rate("c8g.xlarge")}
    md = [f"AWS effective rate per 4-vCPU minute: spot mix m7i.xlarge ${res['aws_rate_spotmix_m7i']:.5f}, "
          f"on-demand m7i.xlarge ${res['aws_rate_od_m7i']:.5f}, spot mix c8g.xlarge "
          f"${res['aws_rate_spotmix_c8g']:.5f} (ESTIMATED from DECLARED list prices). "
          f"GitHub 4-core: ${GH['linux4']:.3f} (DECLARED).\n"]
    scen = {
        "base_median": [row(n, p) for n, p in PROJECTS.items()],
        "mean": [row(n, p, "mean") for n, p in PROJECTS.items()],
        "mean_ondemand": [row(n, p, "mean", rate=aws_rate(spot=False)) for n, p in PROJECTS.items()],
        "mean_capture_1.1": [row(n, p, "mean", capture=1.1) for n, p in PROJECTS.items()],
        "mean_runner8": [row(n, p, "mean", runner="linux8") for n, p in PROJECTS.items()],
        "mean_runner16": [row(n, p, "mean", runner="linux16") for n, p in PROJECTS.items()],
        "mean_2025_prices": [],
        "agents_5x": [row(n, p, "mean", runs=2500) for n, p in PROJECTS.items()],
        "agents_5x_pooled": [row(n, p, "mean", runs=2500, share=min(p["skip"][1], 0.51)) for n, p in PROJECTS.items()],
    }
    for n, p in PROJECTS.items():
        r = row(n, p, "mean")
        _, gtest, gall = github_cost(p, gh=GH_2025)
        r.update(gh_test_cost=gtest, gh_run_cost=gall, gh_test_month=gtest * 500,
                 hi30=gtest * 0.7 * 500, hi50=gtest * 0.5 * 500)
        scen["mean_2025_prices"].append(r)
    titles = {
        "base_median": "Base: median skip share, spot mix, measured capture overhead, 500 runs",
        "mean": "Mean skip share (the right input for a monthly bill)",
        "mean_ondemand": "Mean skip share, AWS on-demand only (no spot)",
        "mean_capture_1.1": "Mean skip share, capture overhead cut to 1.1x (engine target, not measured)",
        "mean_runner8": "Mean skip share, customer on 8-core GitHub runners",
        "mean_runner16": "Mean skip share, customer on 16-core GitHub runners",
        "mean_2025_prices": "Mean skip share, GitHub 2025 list prices",
        "agents_5x": "Agents: 5x runs (2,500 / month), same per-run skip share (project mean)",
        "agents_5x_pooled": "Agents: 5x runs (2,500 / month), skip share = min(project mean, 51% pooled agent-push mean)",
    }
    for k, rows in scen.items():
        md.append(table(rows, titles[k]))
    res["scenarios"] = scen
    out = Path(__file__).resolve().parent
    (out / "data").mkdir(exist_ok=True)
    (out / "data" / "results.json").write_text(json.dumps(res, indent=1))
    (out / "data" / "tables.md").write_text("\n".join(md))
    print("\n".join(md))



def project_tables(path=Path(__file__).resolve().parent / "data" / "results.json"):
    """One table per project type, every scenario as a row (used in REPORT.md)."""
    res = json.loads(Path(path).read_text())
    names = {"base_median": "median skip (base)", "mean": "mean skip", "mean_ondemand": "mean, AWS on-demand only",
             "mean_capture_1.1": "mean, capture overhead 1.1x", "mean_runner8": "mean, customer on 8-core",
             "mean_runner16": "mean, customer on 16-core", "mean_2025_prices": "mean, GitHub 2025 prices",
             "agents_5x": "agents 5x (2,500 runs), mean skip", "agents_5x_pooled": "agents 5x, skip 51% cap"}
    out = []
    for i, proj in enumerate(PROJECTS):
        p = PROJECTS[proj]
        out += [f"### {proj}", "", f"Run shape: {sum(n for n, *_ in p['test_jobs'])} test jobs; "
                f"{(p['note'] or 'PR run').rstrip('.')}.", "",
                "| scenario | skip | GitHub $ test jobs / run | GitHub $ whole run | fenvix min / run | fenvix $ / run "
                "| GitHub $ test jobs / month | fenvix cost / month | price band, >=30% cheaper | price band, >=50% cheaper |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---|---|"]
        for k, label in names.items():
            r = res["scenarios"][k][i]
            out.append(f"| {label} | {r['share']:.0%} | ${r['gh_test_cost']:.2f} | ${r['gh_run_cost']:.2f} | "
                       f"{r['fx_min']:.0f} | ${r['fx_cost']:.3f} | ${r['gh_test_month']:,.0f} | ${r['fx_month']:,.0f} | "
                       f"{fmt_band(r['lo'], r['hi30'])} | {fmt_band(r['lo'], r['hi50'])} |")
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    main()
    (Path(__file__).resolve().parent / "data" / "project_tables.md").write_text(project_tables())
