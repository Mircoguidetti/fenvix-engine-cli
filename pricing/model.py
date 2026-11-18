#!/usr/bin/env python3
"""Pricing model v2: monthly plans by CI runs, priced against GitHub-hosted runners and Blacksmith.

Every input carries a label in a comment: MEASURED / ESTIMATED / DECLARED (source, date) / UNKNOWN,
plus PROVISIONAL where the source report is still under review.

Run:  python3 pricing/model.py
Writes pricing/data/results.json and pricing/data/tables.md (every table of sessions/2026-11-18-pricing-v2/REPORT.md).
Test: python3 -m pytest -q pricing/test_model.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

READ = "2026-11-18"  # the day every vendor page below was read

# ------------------------------------------------------------------ vendor prices (all DECLARED, read 2026-11-18)
# GitHub-hosted runners, USD per minute. docs.github.com/en/billing/reference/actions-runner-pricing
GH = {"linux2": 0.006, "linux4": 0.012, "linux8": 0.022, "linux16": 0.042}
# Included compute per month. docs.github.com/en/billing/concepts/product-billing/github-actions
GH_INCLUDED = {"free": 12.0, "team": 18.0, "enterprise": 300.0}
GH_SELF_HOSTED_FEE = 0.0  # same page: self-hosted runners "remain free"; no per-minute platform fee in force

# Blacksmith, Linux x64, USD per minute. blacksmith.sh/pricing + docs.blacksmith.sh/blacksmith-runners/flex-scheduling
BS = {"linux2": 0.004, "linux4": 0.008, "linux8": 0.016, "linux16": 0.032}
BS_FREE_CREDIT = 3000 * BS["linux2"]  # 3,000 free x64 2-vCPU minutes per organization per month = $12 of list price
BS_SPEEDUP_CLAIM = 2.0                # "We are 2x faster than GitHub's runners" (vendor claim, not verified by us)
BS_FLEX_DISCOUNT = 0.40               # jobs that can wait up to 24 h

# Other runner vendors, 4 vCPU / 16 GB Linux x64, USD per minute (context only)
OTHERS = {
    "BuildPulse": 0.008,          # buildpulse.io/pricing; 3,000 free minutes; claims 2x faster
    "Depot": 0.012,               # depot.dev/pricing: $0.006 per 2-vCPU minute, plus a $20 or $200 monthly plan
    "Namespace (prepaid)": 0.008, # namespace.so/pricing: 8 unit-minutes at $0.001; overage $0.012
}

# AWS EC2 Linux on-demand, us-east-1, USD per hour.
# pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-east-1/index.csv, published 2026-11-18
AWS_OD = {"m7i.xlarge": 0.2016, "c7i.xlarge": 0.1785, "c7a.xlarge": 0.20528, "c8g.xlarge": 0.15952,
          "m8g.xlarge": 0.17952, "m7a.xlarge": 0.23184}
# AWS spot: today's prices UNKNOWN (website.spot.ec2.aws.a2z.com refused by the session proxy).
# The only AWS-hosted file reachable (spot-price.s3.amazonaws.com/spot.js) is dated 2024-05-13: STALE, scenario only.
AWS_SPOT_STALE = {"m7i.xlarge": 0.0897, "c7i.xlarge": 0.0839}
AWS_EBS_GP3_GB_MONTH = 0.08      # same EC2 price list
AWS_S3_GB_MONTH = 0.023          # .../AmazonS3/current/us-east-1/index.csv (first 50 TB)
AWS_EGRESS_GB = 0.09             # .../AWSDataTransfer/current/index.csv (first 10 TB out to the internet)
AWS_NAT_GB = 0.045               # EC2 price list; we avoid NAT gateways (see report)

# Hetzner Cloud, EUR per hour excl. VAT, billed hourly. hetzner.com/cloud/general-purpose, /regular-performance
HETZNER_EUR_H = {"CCX23": 0.1178,   # 4 dedicated vCPU, 16 GB, 160 GB NVMe, 20 TB traffic included (EU)
                 "CPX32": 0.0489}   # 4 shared vCPU, 8 GB
EURUSD = 1.15  # ESTIMATED: no primary FX source reachable (www.ecb.europa.eu refused by the proxy)

# Antithesis Teams. antithesis.com/pricing
ANTITHESIS = {"monthly": 2999.0, "included_core_hours": 2400, "extra_core_hour": 2.50}

# ------------------------------------------------------------------ our operating assumptions (all ESTIMATED)
UTILISATION = {"aws": 0.70, "hetzner": 0.50}  # billed machine time that runs customer work; Hetzner bills whole hours
DISK_GB = 80            # root disk per machine, as on a GitHub or Blacksmith 4-vCPU runner
OTHER_ADD = 0.10        # control plane, logs, public IPv4, result upload: share of compute
SPOT_MIX = 0.80         # share of minutes on spot in the spot scenario
FIXED_MIN = 1.0         # per run: start-up, cache pull and push, result upload (machine-minutes)
AUDIT_SHARE = 0.05      # share of skipped test time re-run fresh as a standing audit
SPEED_VS_GITHUB = 1.0   # our 4 vCPU against GitHub's 4 vCPU: UNKNOWN, taken as equal
MACHINE_TARGET_MIN = 10.0
CACHE_GB = {"small": 0.1, "large": 2.0}  # ESTIMATED from 31 MB for pygments' 5,300 tests (MEASURED, shared-cache report)

TARGET_SAVING = 0.30    # the customer must pay at least 30% less than on Blacksmith
HEALTHY_MARGIN = 0.60   # gross margin we call healthy
THIN_MARGIN = 0.30


def our_rate(infra="aws_od"):
    """USD per 4-vCPU machine-minute, all in."""
    if infra == "aws_od":
        base = AWS_OD["m7i.xlarge"] / 60
        util = UTILISATION["aws"]
    elif infra == "aws_spot_stale":
        od = AWS_OD["m7i.xlarge"] / 60
        base = SPOT_MIX * AWS_SPOT_STALE["m7i.xlarge"] / 60 + (1 - SPOT_MIX) * od
        util = UTILISATION["aws"]
    elif infra == "hetzner":
        return HETZNER_EUR_H["CCX23"] * EURUSD / 60 / UTILISATION["hetzner"] * (1 + OTHER_ADD)
    else:
        raise ValueError(infra)
    disk = DISK_GB * AWS_EBS_GP3_GB_MONTH / (730 * 60)
    return (base + disk) / util * (1 + OTHER_ADD)


INFRAS = {"aws_od": "AWS on-demand m7i.xlarge", "aws_spot_stale": "AWS 80% spot (2024 prices, STALE)",
          "hetzner": "Hetzner CCX23"}

# ------------------------------------------------------------------ customer shapes
# test_jobs: (count, setup_min, test_min, covered, envs). Minutes are 4-vCPU job minutes on GitHub-hosted runners.
#   covered = the measured skip share applies to this job's test step; envs = distinct environments (shards merge).
# skip = mean share of test time skipped with proof per commit (the mean, not the median, sets a monthly bill).
# capture = cost of an executed test under the engine, relative to plain.
SHAPES = {
    "small library": dict(
        like="flask-like, 8 Python versions",
        test_jobs=[(8, 1.2, 0.3, True, 8)],     # ESTIMATED from the flask workflow (pricing v1)
        runs=150,                               # ESTIMATED
        skip=0.22,                              # MEASURED, reviewed (first skip study, 14 libraries: mean 22%)
        skip_label="MEASURED",
        capture=1.60,                           # PROVISIONAL: median cold/plain of 12 libraries (cache-proof step 1, R-009 open)
        cache="small"),
    "mid service": dict(
        like="Django app, saleor-like",
        test_jobs=[(1, 4.0, 14.0, True, 1)],    # ESTIMATED from 46 CPU-min of test durations (MEASURED sample)
        runs=600,                               # ESTIMATED
        skip=0.13,                              # MEASURED, partial (29 of 50 transitions): Django loads every app
        skip_label="MEASURED (partial)",
        capture=1.47,                           # PROVISIONAL: home-assistant cold/plain (R-009 open)
        cache="large"),
    "large Python monorepo": dict(
        like="airflow-like",
        test_jobs=[(14, 2.5, 9.8, True, 1)],    # 137 serial test min per run ESTIMATED (market test, 6% sample) in 14 shards; setup ESTIMATED
        runs=1500,                              # ESTIMATED; airflow has 910 default-branch commits a month (MEASURED) before PR pushes
        skip=0.56,                              # PROVISIONAL: market test REPORT-2, airflow env-ok mean
        skip_label="PROVISIONAL",
        capture=1.47, cache="large"),
    "large JS monorepo": dict(
        like="docusaurus-like",
        test_jobs=[(2, 1.8, 0.3, True, 2),      # unit step MEASURED (20 runs); +1.0 boot ESTIMATED
                   (14, 3.0, 4.0, False, 14)],  # e2e and build-a-site jobs ESTIMATED; skip share UNKNOWN, taken as 0
        runs=1000,                              # ESTIMATED
        skip=0.81,                              # MEASURED, reviewed (skip study 2 v3.1), unit tests only
        skip_label="MEASURED (unit step only)",
        capture=1.54,                           # MEASURED (strace study)
        cache="large"),
    "Go service": dict(
        like="prometheus-like",
        test_jobs=[(4, 2.0, 10.0, True, 4),     # ESTIMATED (package walls sum to 8.3 min serial, MEASURED)
                   (6, 2.0, 3.0, False, 6)],    # upgrade, UI, mixins, compliance jobs: ESTIMATED
        runs=800,                               # ESTIMATED
        skip=0.49,                              # MEASURED, reviewed (skip study 2 v3.1, proof rule)
        skip_label="MEASURED",
        capture=1.3,                            # ESTIMATED: not recorded for Go
        cache="large",
        rival_skip=0.60),                       # MEASURED: Go's own test cache without proof skips 60% (mean) on prometheus
}

# Variants of the large Python monorepo: one row per measured repository.
MONOREPO_VARIANTS = {
    "airflow-like": dict(test_min=137, runs=1500, skip=0.56, skip_label="PROVISIONAL"),
    "prefect-like": dict(test_min=203, runs=600, skip=0.732, skip_label="PROVISIONAL"),
    "home-assistant-like (engine)": dict(test_min=120, runs=1500, skip=0.73, skip_label="PROVISIONAL"),
    "home-assistant-like (study)": dict(test_min=120, runs=1500, skip=0.82, skip_label="MEASURED"),
    "litellm-like (low skip)": dict(test_min=563, runs=1500, skip=0.23, skip_label="PROVISIONAL"),
}


def monorepo(test_min, runs, skip, skip_label):
    shards = max(1, round(test_min / 10))
    return dict(like="", test_jobs=[(shards, 2.5, test_min / shards, True, 1)], runs=runs, skip=skip,
                skip_label=skip_label, capture=1.47, cache="large")


# ------------------------------------------------------------------ the model
def baseline_minutes(p):
    """4-vCPU test-job minutes of one run on GitHub-hosted runners (setup + test)."""
    return sum(n * (s + t) for n, s, t, *_ in p["test_jobs"])


def github_cost(p, included=0.0):
    return max(0.0, baseline_minutes(p) * GH["linux4"] * p["runs"] - included)


def blacksmith_cost(p, speedup=1.0, free=False, rival_skip=0.0, flex=False):
    """Monthly Blacksmith bill for the same test jobs. speedup divides every minute; rival_skip removes that
    share of the covered test steps (Blacksmith's own Go test cache or Vitest selection, no proof)."""
    mins = 0.0
    for n, s, t, covered, _ in p["test_jobs"]:
        mins += n * (s + t * (1 - (rival_skip if covered else 0.0)))
    price = BS["linux4"] * (1 - BS_FLEX_DISCOUNT if flex else 1)
    return max(0.0, mins / speedup * price * p["runs"] - (BS_FREE_CREDIT if free else 0.0))


def our_minutes(p, skip=None, capture=None):
    """Machine-minutes of one run on our side."""
    skip = p["skip"] if skip is None else skip
    capture = p["capture"] if capture is None else capture
    total = FIXED_MIN
    for n, s, t, covered, envs in p["test_jobs"]:
        if not covered:
            total += n * (s + t) / SPEED_VS_GITHUB
            continue
        executed = n * t * ((1 - skip) * capture + skip * AUDIT_SHARE) / SPEED_VS_GITHUB
        if executed <= 0.01:
            continue
        machines = envs * math.ceil(executed / envs / MACHINE_TARGET_MIN)
        total += machines * s + executed
    return total


def our_cost(p, infra="aws_od", skip=None, capture=None):
    """Monthly cost for us: machines plus cache storage."""
    return our_minutes(p, skip, capture) * our_rate(infra) * p["runs"] + CACHE_GB[p["cache"]] * AWS_S3_GB_MONTH


def verdict(margin):
    if margin >= HEALTHY_MARGIN:
        return "healthy"
    if margin >= THIN_MARGIN:
        return "thin"
    return "none"


def evaluate(name, p, infra="aws_od", skip=None, capture=None, rival_skip=0.0):
    gh = github_cost(p)
    bs_list = blacksmith_cost(p, rival_skip=rival_skip)
    bs_best = blacksmith_cost(p, speedup=BS_SPEEDUP_CLAIM, free=True, rival_skip=rival_skip)
    cost = our_cost(p, infra, skip, capture)
    out = dict(shape=name, like=p.get("like", ""), runs=p["runs"], skip=p["skip"] if skip is None else skip,
               skip_label=p["skip_label"], baseline_min=baseline_minutes(p), our_min=our_minutes(p, skip, capture),
               github=gh, github_team=github_cost(p, GH_INCLUDED["team"]),
               bs_list=bs_list, bs_free=blacksmith_cost(p, free=True, rival_skip=rival_skip),
               bs_2x=blacksmith_cost(p, speedup=BS_SPEEDUP_CLAIM, rival_skip=rival_skip), bs_best=bs_best,
               cost=cost, cost_per_run=cost / p["runs"], infra=infra)
    for key, ref in (("list", bs_list), ("best", bs_best)):
        price = ref * (1 - TARGET_SAVING)
        margin = 1 - cost / price if price > 0 else float("-inf")
        out[f"price_{key}"] = price
        out[f"margin_{key}"] = margin
        out[f"verdict_{key}"] = verdict(margin)
    out["floor"] = cost / (1 - HEALTHY_MARGIN)  # lowest price with a healthy margin
    return out


def max_ratio(infra, speedup, margin=HEALTHY_MARGIN):
    """Our machine-minutes per customer GitHub minute that still allow TARGET_SAVING below Blacksmith at `margin`."""
    return BS["linux4"] / speedup * (1 - TARGET_SAVING) * (1 - margin) / our_rate(infra)


# ------------------------------------------------------------------ plans
# One "run unit" = RUN_UNIT_MIN baseline minutes: the 4-vCPU test-job minutes one run takes on GitHub-hosted
# runners with nothing skipped, measured per repository in the shadow trial and fixed for the plan period.
RUN_UNIT_MIN = 10
UNIT_CEILING_LIST = BS["linux4"] * RUN_UNIT_MIN * (1 - TARGET_SAVING)                  # 30% below Blacksmith at list speed
UNIT_CEILING_2X = BS["linux4"] * RUN_UNIT_MIN / BS_SPEEDUP_CLAIM * (1 - TARGET_SAVING)  # 30% below Blacksmith at its 2x claim
PLANS = [               # (name, run units per month, monthly price, overage per unit)
    ("Shadow", 0, 0, None),
    ("Starter", 2_500, 129, 0.056),
    ("Team", 10_000, 479, 0.052),
    ("Scale", 30_000, 1_350, 0.049),
    ("Monorepo", 100_000, 4_200, 0.046),
]
MAX_OUR_SHARE = 0.35    # gate: we sell a paid plan only if shadow mode shows our machine-minutes at or under this share


def plan_for(units):
    """Cheapest paid plan for a monthly usage, overage included."""
    best = None
    for name, cap, price, over in PLANS[1:]:
        total = price + max(0.0, units - cap) * over
        label = name if units <= cap else name + " + overage"
        if best is None or total < best[1]:
            best = (label, total)
    return best


def plan_checks(infra="aws_od", shapes=None):
    rows = []
    for name, p in (shapes or SHAPES).items():
        units = baseline_minutes(p) * p["runs"] / RUN_UNIT_MIN
        plan, price = plan_for(units)
        e = evaluate(name, p, infra)
        share = e["our_min"] / e["baseline_min"]
        rows.append(dict(shape=name, units=units, plan=plan, price=price, cost=e["cost"],
                         margin=1 - e["cost"] / price, share=share, gate=share <= MAX_OUR_SHARE,
                         vs_github=1 - price / e["github"],
                         vs_bs_list=1 - price / e["bs_list"],
                         vs_bs_best=(1 - price / e["bs_best"]) if e["bs_best"] > 0 else float("-inf")))
    return rows


# ------------------------------------------------------------------ output
def usd(x):
    return f"${x:,.0f}" if abs(x) >= 100 else f"${x:,.2f}"


def pct(x):
    return "n/a" if x == float("-inf") else f"{x:+.0%}" if x < 0 else f"{x:.0%}"


def t_rates():
    out = ["| machine | list price | our all-in rate per 4-vCPU minute | against GitHub $0.012 | against Blacksmith $0.008 |",
           "|---|---|---:|---:|---:|"]
    lists = {"aws_od": f"${AWS_OD['m7i.xlarge']}/h (DECLARED)",
             "aws_spot_stale": f"${AWS_SPOT_STALE['m7i.xlarge']}/h spot (DECLARED, dated 2024-05-13: STALE)",
             "hetzner": f"EUR {HETZNER_EUR_H['CCX23']}/h (DECLARED), EUR/USD {EURUSD} (ESTIMATED)"}
    for k, label in INFRAS.items():
        r = our_rate(k)
        out.append(f"| {label} | {lists[k]} | ${r:.5f} | {r / GH['linux4']:.0%} | {r / BS['linux4']:.0%} |")
    return "\n".join(out)


def t_cost_per_run(infra="aws_od"):
    out = ["| shape | baseline min / run | skip (mean) | capture | our machine-min / run | our cost / run, AWS on-demand | Hetzner | AWS spot (STALE) |",
           "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, p in SHAPES.items():
        e = {k: evaluate(name, p, k) for k in INFRAS}
        a = e["aws_od"]
        out.append(f"| {name} ({p['like']}) | {a['baseline_min']:.0f} | {p['skip']:.0%} {p['skip_label']} | {p['capture']:.2f}x | "
                   f"{a['our_min']:.1f} | ${a['cost_per_run']:.3f} | ${e['hetzner']['cost_per_run']:.3f} | "
                   f"${e['aws_spot_stale']['cost_per_run']:.3f} |")
    return "\n".join(out)


def t_shapes(infra, shapes=None, rival=False):
    out = ["| shape | runs / month | GitHub | Blacksmith, list | Blacksmith, 2x claim + free minutes | our cost | "
           "price 30% below Blacksmith list (our margin) | price 30% below Blacksmith 2x + free (our margin) | verdict |",
           "|---|---:|---:|---:|---:|---:|---|---|---|"]
    for name, p in (shapes or SHAPES).items():
        e = evaluate(name, p, infra, rival_skip=p.get("rival_skip", 0.0) if rival else 0.0)
        v = {"healthy": "a price exists", "thin": "thin margin", "none": "no price"}
        out.append(f"| {name} | {e['runs']:,} | {usd(e['github'])} | {usd(e['bs_list'])} | {usd(e['bs_best'])} | {usd(e['cost'])} | "
                   f"{usd(e['price_list'])} ({pct(e['margin_list'])}) | {usd(e['price_best'])} ({pct(e['margin_best'])}) | "
                   f"list: {v[e['verdict_list']]}; 2x: {v[e['verdict_best']]} |")
    return "\n".join(out)


def t_ratio():
    out = ["| machine | Blacksmith at list speed | Blacksmith at its 2x claim |", "|---|---:|---:|"]
    for k, label in INFRAS.items():
        out.append(f"| {label} | {max_ratio(k, 1.0):.0%} | {max_ratio(k, 2.0):.0%} |")
    return "\n".join(out)


def t_plans():
    out = ["| plan | run units / month | price / month | per unit | above the limit | below GitHub | below Blacksmith list | below Blacksmith at 2x |",
           "|---|---:|---:|---:|---|---:|---:|---:|"]
    gh_unit, bs_unit = GH["linux4"] * RUN_UNIT_MIN, BS["linux4"] * RUN_UNIT_MIN
    for name, cap, price, over in PLANS:
        if cap == 0:
            out.append(f"| {name} | everything, 30 days | $0 | - | nothing is skipped; the customer keeps its runner | - | - | - |")
        else:
            u = price / cap
            out.append(f"| {name} | {cap:,} | ${price:,} | ${u:.4f} | ${over:.3f} per unit | {pct(1 - u / gh_unit)} | "
                       f"{pct(1 - u / bs_unit)} | {pct(1 - u / (bs_unit / BS_SPEEDUP_CLAIM))} |")
    return "\n".join(out)


def t_plan_checks(infra, shapes=None):
    out = ["| shape | run units / month | our share of baseline minutes | passes the gate | plan | price | our cost | our margin | "
           "saving against GitHub | against Blacksmith list | against Blacksmith 2x + free |",
           "|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in plan_checks(infra, shapes):
        out.append(f"| {r['shape']} | {r['units']:,.0f} | {r['share']:.0%} | {'yes' if r['gate'] else 'no'} | {r['plan']} | "
                   f"{usd(r['price'])} | {usd(r['cost'])} | {pct(r['margin'])} | "
                   f"{pct(r['vs_github'])} | {pct(r['vs_bs_list'])} | {pct(r['vs_bs_best'])} |")
    return "\n".join(out)


def t_risks(infra="aws_od"):
    variants = {k: monorepo(**v) for k, v in MONOREPO_VARIANTS.items()}
    cases = [("large Python monorepo", SHAPES["large Python monorepo"]),
             ("prefect-like", variants["prefect-like"]),
             ("home-assistant-like (study)", variants["home-assistant-like (study)"]),
             ("Go service", SHAPES["Go service"])]
    out = ["| shape | base: margin at 30% below Blacksmith list / 2x + free | skip 20 points lower | capture overhead 1.1x | "
           "Blacksmith skips the same share (no proof) | GitHub and Blacksmith both cut 25% |", "|---|---|---|---|---|---|"]
    for name, p in cases:
        base = evaluate(name, p, infra)
        low = evaluate(name, p, infra, skip=max(0.0, p["skip"] - 0.20))
        cap = evaluate(name, p, infra, capture=1.1)
        riv = evaluate(name, p, infra, rival_skip=p.get("rival_skip", p["skip"]))
        cut = {k: 1 - base["cost"] / (base[f"price_{k}"] * 0.75) if base[f"price_{k}"] > 0 else float("-inf")
               for k in ("list", "best")}
        f = lambda e: f"{pct(e['margin_list'])} / {pct(e['margin_best'])}"
        out.append(f"| {name} | {f(base)} | {f(low)} | {f(cap)} | {f(riv)} | {pct(cut['list'])} / {pct(cut['best'])} |")
    return "\n".join(out)


def t_antithesis():
    a = ANTITHESIS
    inc = a["monthly"] / a["included_core_hours"]
    rows = [("Antithesis Teams, included hours", inc), ("Antithesis Teams, extra hours", a["extra_core_hour"]),
            ("GitHub 4-core runner", GH["linux4"] * 60 / 4), ("Blacksmith 4 vCPU", BS["linux4"] * 60 / 4),
            ("fenvix Starter plan, per baseline core-hour", PLANS[1][2] / PLANS[1][1] / RUN_UNIT_MIN * 60 / 4),
            ("fenvix Monorepo plan, per baseline core-hour", PLANS[-1][2] / PLANS[-1][1] / RUN_UNIT_MIN * 60 / 4)]
    out = ["| | USD per CPU core-hour | multiple of Blacksmith |", "|---|---:|---:|"]
    for label, v in rows:
        out.append(f"| {label} | ${v:.3f} | {v / (BS['linux4'] * 60 / 4):.1f}x |")
    return "\n".join(out)


def required_skip(infra, speedup, capture, margin=HEALTHY_MARGIN):
    """Lowest mean skip share at which an airflow-sized monorepo reaches `margin` at 30% below Blacksmith."""
    for i in range(0, 1001):
        skip = i / 1000
        p = monorepo(137, 1500, skip, "")
        ref = blacksmith_cost(p, speedup=speedup, free=speedup > 1)
        if 1 - our_cost(p, infra, capture=capture) / (ref * (1 - TARGET_SAVING)) >= margin:
            return skip
    return None


def t_required():
    out = ["| machine | capture overhead | against Blacksmith list | against Blacksmith 2x + free |", "|---|---:|---:|---:|"]
    f = lambda v: "not reachable" if v is None else f"{v:.0%}"
    for k, label in INFRAS.items():
        for cap in (1.47, 1.1):
            out.append(f"| {label} | {cap}x | {f(required_skip(k, 1.0, cap))} | {f(required_skip(k, 2.0, cap))} |")
    return "\n".join(out)


def build():
    variants = {k: monorepo(**v) for k, v in MONOREPO_VARIANTS.items()}
    md = ["# Pricing v2 tables (generated by pricing/model.py; do not edit by hand)", ""]
    sections = [
        ("T1. Our all-in rate per 4-vCPU machine-minute (ESTIMATED from DECLARED list prices)", t_rates()),
        ("T2. Our cost per run, per shape (ESTIMATED)", t_cost_per_run()),
        ("T3. Largest share of the customer's GitHub minutes we may spend (30% below Blacksmith, 60% margin)", t_ratio()),
        ("T4. Monthly bill per shape, our machines on AWS on-demand", t_shapes("aws_od")),
        ("T5. Same, our machines on Hetzner CCX23", t_shapes("hetzner")),
        ("T6. Same, AWS with 80% spot at 2024 prices (STALE, scenario only)", t_shapes("aws_spot_stale")),
        ("T7. Large Python monorepo, one row per measured repository, AWS on-demand", t_shapes("aws_od", variants)),
        ("T8. Same on Hetzner CCX23", t_shapes("hetzner", variants)),
        ("T9. Go service when the customer turns on Blacksmith's Go test cache (60% skipped, no proof), AWS on-demand",
         t_shapes("aws_od", {"Go service": SHAPES["Go service"]}, rival=True)),
        ("T10. Plans (1 run unit = 10 baseline minutes; ceilings: $%.3f per unit against Blacksmith list, $%.3f against its 2x claim)" % (UNIT_CEILING_LIST, UNIT_CEILING_2X), t_plans()),
        ("T11. The plans applied to the five shapes, AWS on-demand", t_plan_checks("aws_od")),
        ("T12. The plans applied to the monorepo variants, AWS on-demand", t_plan_checks("aws_od", variants)),
        ("T13. The plans applied to the five shapes, Hetzner CCX23", t_plan_checks("hetzner")),
        ("T14. Risks: our margin at a price 30% below Blacksmith, AWS on-demand", t_risks("aws_od")),
        ("T15. Same on Hetzner CCX23", t_risks("hetzner")),
        ("T16. Antithesis against CI compute, per CPU core-hour (DECLARED prices)", t_antithesis()),
        ("T17. Mean skip share a large Python monorepo needs for a 60% margin at 30% below Blacksmith", t_required()),
    ]
    for title, body in sections:
        md += [f"## {title}", "", body, ""]
    res = dict(read=READ, rates={k: our_rate(k) for k in INFRAS},
               shapes={k: {n: evaluate(n, p, k) for n, p in SHAPES.items()} for k in INFRAS},
               variants={k: {n: evaluate(n, p, k) for n, p in variants.items()} for k in INFRAS},
               plan_checks={k: plan_checks(k) for k in INFRAS},
               plans=PLANS, unit_ceiling=dict(list=UNIT_CEILING_LIST, claim_2x=UNIT_CEILING_2X),
               max_ratio={k: {"list": max_ratio(k, 1.0), "claim_2x": max_ratio(k, 2.0)} for k in INFRAS})
    return "\n".join(md), res


def main():
    md, res = build()
    out = Path(__file__).resolve().parent / "data"
    out.mkdir(exist_ok=True)
    (out / "tables.md").write_text(md)
    (out / "results.json").write_text(json.dumps(res, indent=1, default=str))
    print(md)


if __name__ == "__main__":
    main()
