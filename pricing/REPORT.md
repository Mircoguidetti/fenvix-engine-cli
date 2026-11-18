> Superseded on 2026-11-18 by `sessions/2026-11-18-pricing-v2/REPORT.md` (prices read from the vendors' pages; `model.py` rewritten). The numbers below are version 1, from memory.

# Pricing study: what one CI run costs on GitHub Actions, and on fenvix

Status: 2026-11-17, version 1. Model: `pricing/model.py` (run `python3 pricing/model.py`; it writes
`pricing/data/results.json`, `tables.md` and `project_tables.md`). Working notes: `pricing/data/notes.md`.

Labels: **MEASURED** (our GitHub Actions studies), **ESTIMATED** (inferred, method stated), **DECLARED** (vendor list
price, source named), **UNKNOWN**.

**Web access was blocked in this session** (docs.github.com and aws.amazon.com were refused by the proxy, api.github.com
returned 403). Every price below is from memory, labelled DECLARED with its source, and **must be verified** before
it reaches a customer.

## Answer in four lines

1. A typical full CI run costs a private-repo team **$0.25 to $5 on GitHub** (whole run), of which the **test jobs are
   $0.09 to $1.97** (ESTIMATED shapes, DECLARED prices). For 500 runs: **$46 to $984 of test jobs** a month.
2. On our AWS machines the same test jobs, after skip-with-proof, cost us **$0.02 to $0.27 per run** (ESTIMATED).
3. With a 70% gross margin, a price that leaves the customer **at least 30% cheaper exists only where skipping removes
   a lot of minutes**: the large modular monorepo (home-assistant type, **$366-689 per 500 runs**, 50% cheaper:
   **$366-492**) and the large Go service (prometheus type, **$289-328**). For the other five types there is no such
   price at today's measured skip shares and capture overhead.
4. The rule behind it (ESTIMATED, spot-mix rate): our machine-minutes per run must be **at most 95% of the customer's
   GitHub test-job minutes** for "30% cheaper + 70% margin", and **at most 68%** for "50% cheaper + 70% margin".
   With AWS on-demand only, 46% and 33%. Cheap compute alone (4.5x cheaper per minute than GitHub) caps the customer
   saving at 26%: the rest has to come from skipping.

## Main table (500 runs / month, customer on GitHub 4-core-equivalent runners)

Skip share median / mean from `harness/skip_study2` (MEASURED). Run shapes ESTIMATED from each project's
`.github/workflows` (see "Run shapes"). "Band" = prices per 500 runs between our 70%-margin floor and the customer's
ceiling, computed with the **mean** skip share (the mean, not the median, sets a monthly bill).

| project type (example) | skip median / mean | GitHub test-job min / run | GitHub $ / run: test jobs (whole run) | GitHub $ test jobs / 500 | fenvix machine-min / run, median / mean | fenvix AWS $ / run, median / mean | band / 500, customer >=30% cheaper | band / 500, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---|---|
| large modular monorepo (home-assistant) | 97% / 82% | 164 | $1.97 ($2.93) | $984 | 46 / 83 | $0.12 / $0.22 | **$366-689** | **$366-492** |
| JS monorepo (docusaurus) | 98% / 81% | 102 | $1.23 ($3.95) | $613 | 103 / 103 | $0.27 / $0.27 | none (floor $454 > $429) | none |
| tightly coupled (vue-core) | 25% / 31% | 8 | $0.09 ($0.25) | $46 | 9 / 9 | $0.02 / $0.02 | none (floor $39 > $32) | none |
| Go service, small (terraform) | 25% / 23% | 19 | $0.23 ($0.37) | $115 | 20 / 20 | $0.05 / $0.05 | none (floor $89 > $81) | none |
| Go service, large (prometheus) | 56% / 49% | 78 | $0.94 ($1.83) | $468 | 62 / 66 | $0.16 / $0.17 | **$289-328** | none (floor $289 > $234) |
| Django app (saleor) | 0% / 13% | 18 | $0.22 ($0.43) | $108 | 54 / 49 | $0.14 / $0.13 | none (floor $217 > $76) | none |
| small library (flask-like) | 0% / 22% | 12 | $0.14 ($0.34) | $72 | 14 / 13 | $0.04 / $0.04 | none (floor $59 > $50) | none |

Labels: skip MEASURED (saleor partial: 29 transitions; small library = first study, 14 libraries); minutes ESTIMATED
(built on MEASURED test-step times where we have them, see below); $ = ESTIMATED from DECLARED prices.

What the table says:

* **Where we win, we win big.** home-assistant type: our cost is 11% of the GitHub test-job bill at the mean skip, 6%
  at the median. That pays a 70% margin and still halves the customer's bill.
* **docusaurus type: the measured 98% skip is worth almost nothing in money.** It covers the unit-test step, which is
  0.3 min per job (MEASURED). 95% of the test-job minutes are e2e and build-a-site jobs that our study did not cover
  (skip share UNKNOWN, modelled as 0). If e2e jobs could be skipped with proof at the same share, this type would move
  into the HA column (ESTIMATED, not measured).
* **Capture overhead eats small and coupled projects.** The strace capture makes each executed test 1.5x to 2.6x
  slower (MEASURED: vitest 1.54-1.56, HA 2.06, saleor 2.63). saleor skips 0% at the median, so we spend **3x** its
  GitHub minutes (54 vs 18). Even at 1.1x overhead saleor has no band (floor $99 > ceiling $76).
* **Small libraries:** the per-job setup (runner boot, install) dominates, not the tests, and each Python version is its
  own environment, so skipping cannot remove much. Also, GitHub Team includes 3,000 minutes / month (DECLARED, GitHub
  plans page), which already covers half of such a team's 500 runs (6,000 min).

## Per-run price: one flat "per run" price does not work

Runs differ 20x in size: 8 test-job minutes (vue-core) vs 164 (home-assistant). A flat $/run that is profitable on
an HA-type run ($0.73 at our floor) is 8x the GitHub cost of a vue-core run. Express the plan in runs, but **set the
plan price from the customer's baseline size** (GitHub-equivalent test-job minutes per run, measured in a free trial):

| project type | our floor, $ per baseline test-minute (mean skip) | customer ceiling, 30% cheaper | 50% cheaper |
|---|---:|---:|---:|
| large modular monorepo | $0.0045 | $0.0084 | $0.0060 |
| large Go service | $0.0074 | $0.0084 | $0.0060 |
| all other types | $0.0089 to $0.0241 | $0.0084 | $0.0060 |

(ESTIMATED; ceiling = 70% or 50% of GitHub's DECLARED $0.012 per 4-core minute.)

**Suggested starting price (ESTIMATED): about $0.0060-0.0080 per baseline test-minute**, i.e. a "500 runs" plan at
**~$450 for an HA-sized repo** (164 min/run: customer ~54% cheaper on test jobs, our margin ~76%) and **~$320 for a
prometheus-sized repo** (78 min/run: customer ~32% cheaper, margin ~73%). Sell first to large modular monorepos and
to large Go services; do not sell on cost to small libraries, coupled apps or Django monoliths (sell determinism there,
or wait for a cheaper capture).

## Sensitivity (mean skip share unless stated; full tables per type below)

| what changes | effect |
|---|---|
| mean instead of median skip | HA cost per run x1.8 ($0.12 -> $0.22); floor per 500 rises $202 -> $366; band survives. prometheus floor $273 -> $289. Others unchanged (no band either way). |
| AWS on-demand only, no spot | our cost x2.1. **No band for any type** at 30% (HA floor $763 > ceiling $689). Spot (or Savings Plans) is a requirement. |
| capture overhead cut to 1.1x (engine target, not measured) | HA floor $366 -> $276; terraform reaches break-even ($81 = $81); saleor floor $217 -> $99, still no band. |
| customer on 8-core runners ($0.022/min DECLARED) | the customer pays ~20-70% more for the same test jobs (setup minutes billed at the higher rate; test step scales with an 85%-parallel Amdahl ESTIMATE). Bands open at 30% for docusaurus ($454-602), vue-core ($39-48), terraform ($89-99), small library ($59-85); prometheus also at 50% ($289-293). |
| customer on 16-core runners ($0.042/min DECLARED) | every type except saleor has a band, at 30% and at 50%. |
| GitHub 2025 list prices ($0.016 for 4-core, DECLARED) | ceilings +33%: 30% bands open for docusaurus, vue-core, terraform, small library. |
| agents: 5x runs (2,500 / month), same skip share | everything scales x5: HA band $1,831-3,444 (30%), $1,831-2,460 (50%); prometheus $1,447-1,638. Per-run economics do not change. |
| agents: 5x runs, skip share 51% (pooled agent-push mean, MEASURED, 170 pushes, v2 capture) | HA loses its band (floor $3,568 > ceiling $3,444). But HA's own agent pushes measured 98% / 55% (Codex) and 97% / 93% (Copilot) (MEASURED, upper bounds): the 51% pool is dominated by github-mcp-server (101 of 170 pushes). |

## Prices used (all to be verified)

GitHub-hosted runners, private repositories, USD per minute. DECLARED, source: GitHub docs "Actions runner pricing",
prices effective 2026-01-01 (from memory; the 2025 list in brackets):

| runner | $/min |
|---|---:|
| Linux 2-core (default for private repos) | 0.006 (0.008) |
| Linux 4-core | 0.012 (0.016) |
| Linux 8-core | 0.022 (0.032) |
| Linux 16-core | 0.042 (0.064) |
| Windows 2-core | 0.010 (0.016) |
| Windows 8-core | 0.042 (0.064) |
| macOS (3/4-core) | 0.062 (0.08) |

Public repositories get standard runners free (DECLARED), so the open-source projects used here pay $0 today; the
model prices them as if private. A private repo on the default 2-core runner pays $0.006 for about twice the minutes of
our 4-vCPU measurements (suites are CPU-bound: median 2.76 busy cores of 4, MEASURED in `harness/idle_study`), i.e.
about the same money as the 4-core price we use.

AWS EC2 Linux, us-east-1, on-demand USD per hour. DECLARED, source: AWS EC2 on-demand pricing page (2025 list, from
memory):

| instance | vCPU / GiB | $/h | $/min |
|---|---|---:|---:|
| m7i.xlarge (used in the model: same 4 vCPU / 16 GiB as GitHub 4-core) | 4 / 16 | 0.2016 | 0.00336 |
| c7i.xlarge | 4 / 8 | 0.1785 | 0.00298 |
| c7a.xlarge | 4 / 8 | 0.2053 | 0.00342 |
| c8g.xlarge (Graviton4, arm64) | 4 / 8 | 0.1595 | 0.00266 |

Spot: ~35% of on-demand for these families (ESTIMATED; varies by zone and hour; UNKNOWN today).

Our effective rate per 4-vCPU machine-minute (ESTIMATED): 80% spot / 20% on-demand, 70% utilisation (warm pool,
idle tails), +15% for EBS, S3 cache, egress and control plane:
**m7i spot mix $0.00265**, m7i on-demand $0.00552, c8g spot mix $0.00210 (arm64 only where every native dependency
builds). GitHub 4-core is $0.012, i.e. **4.5x** our spot-mix rate.

## Run shapes (ESTIMATED from `.github/workflows`, sparse-cloned 2026-11-17)

Minutes are 4-vCPU job minutes. "Setup" = runner boot + checkout + install; "test" = the test step. Only the test
jobs are priced as fenvix's market; lint, type-check, build, release and Windows/macOS jobs stay on GitHub (in "whole
run" only).

| type | test jobs per PR / full run | other jobs | source of the test minutes |
|---|---|---|---|
| home-assistant | 10 pytest groups (setup 2.2, test 7.0 min) + 12 recorder DB jobs (7 MariaDB/MySQL, 3 Postgres, 2 SQLite; 3 + 3 min) | ~18 jobs, ~80 min (prek, pylint x2, mypy, hassfest, builds, coverage) | test 7.0 and install 1.2 min per group MEASURED (16 runs); boot +1.0 and DB jobs ESTIMATED |
| docusaurus | 2 unit (Node versions; 1.8 + 0.3) + 14 e2e/swizzle (3 + 4) | ~86 min Linux, 10 min Linux 8-core (Argos), 35 min Windows 8-core | unit MEASURED (20 runs); e2e ESTIMATED |
| vue-core | 1 unit (1.2 + 0.5) + 1 e2e (3 + 3) | 11 min Linux, 3 min Windows | unit MEASURED (10 runs) |
| terraform | unit (1.4 + 4.8), race (1.5 + 7), e2e (1.5 + 3) | 12 min (consistency, changelog, equivalence) | unit MEASURED (10 runs); the 36-job release build runs on main pushes only, excluded |
| prometheus | 4 Go test jobs (2 + 10) + 6 others (upgrade x3, UI, mixins, compliance; 2 + 3) | 54 min Linux (build x3, golangci, codeql, fuzzing), 25 min Windows | ESTIMATED (our go package walls sum to 8.3 min serial, MEASURED) |
| saleor | 1 unit_tests job, pytest -n logical (4 + 14) | 18 min (linters, migrations, licenses, graphql) | ESTIMATED from 46 CPU-min of test durations (15% sample scaled, MEASURED) |
| small library | 8 Python-version jobs (1.2 + 0.3) | 3.5 min Linux, 2.5 Windows, 2 macOS | ESTIMATED (flask workflow) |

**home-assistant caveat:** its CI already runs only the touched integrations on integration-only PRs (path filter in
`ci.yaml`), and the full suite on `dev` pushes and core changes. Our 97% median is measured against full runs, so it
overstates what HA itself would save; a team without such a path filter gets the full benefit.

## How fenvix's cost per run is computed (ESTIMATED)

`machine-minutes = 1 fixed (start-up, cache lookup, upload) + for each covered test environment with work left:
setup per ~10-min machine + executed test minutes x capture overhead + uncovered test jobs as today`

* executed test minutes = test minutes x (1 - skip share);
* jobs that are shards of one environment (HA's 10 pytest groups) are merged; matrix variants (Python versions, DB
  engines, Node versions) each keep their own setup, and each is assumed to run something (conservative: at a 97% skip
  many runs would skip a whole environment);
* capture overhead = MEASURED strace ratio traced / plain per project; Go not recorded, 1.3 ESTIMATED;
* margin = (price - AWS cost) / price; floor = cost / 0.3.

## Per project type: every scenario

### large modular monorepo (home-assistant)

Run shape: 22 test jobs; full run (dev pushes, core changes). HA's own CI already runs only touched integrations on integration-only PRs, so its real average is lower.

| scenario | skip | GitHub $ test jobs / run | GitHub $ whole run | fenvix min / run | fenvix $ / run | GitHub $ test jobs / month | fenvix cost / month | price band, >=30% cheaper | price band, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| median skip (base) | 97% | $1.97 | $2.93 | 46 | $0.121 | $984 | $61 | $202-689 | $202-492 |
| mean skip | 82% | $1.97 | $2.93 | 83 | $0.220 | $984 | $110 | $366-689 | $366-492 |
| mean, AWS on-demand only | 82% | $1.97 | $2.93 | 83 | $0.458 | $984 | $229 | none (floor $763 > ceiling $689) | none (floor $763 > ceiling $492) |
| mean, capture overhead 1.1x | 82% | $1.97 | $2.93 | 62 | $0.165 | $984 | $83 | $276-689 | $276-492 |
| mean, customer on 8-core | 82% | $2.62 | $3.58 | 83 | $0.220 | $1,308 | $110 | $366-916 | $366-654 |
| mean, customer on 16-core | 82% | $4.05 | $5.01 | 83 | $0.220 | $2,025 | $110 | $366-1,417 | $366-1,012 |
| mean, GitHub 2025 prices | 82% | $2.62 | $3.90 | 83 | $0.220 | $1,312 | $110 | $366-918 | $366-656 |
| agents 5x (2,500 runs), mean skip | 82% | $1.97 | $2.93 | 83 | $0.220 | $4,920 | $549 | $1,831-3,444 | $1,831-2,460 |
| agents 5x, skip 51% cap | 51% | $1.97 | $2.93 | 162 | $0.428 | $4,920 | $1,070 | none (floor $3,568 > ceiling $3,444) | none (floor $3,568 > ceiling $2,460) |

### JS monorepo (docusaurus)

Run shape: 16 test jobs; the measured skip covers only the 0.3 min unit step; e2e jobs are 95% of test minutes.

| scenario | skip | GitHub $ test jobs / run | GitHub $ whole run | fenvix min / run | fenvix $ / run | GitHub $ test jobs / month | fenvix cost / month | price band, >=30% cheaper | price band, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| median skip (base) | 98% | $1.23 | $3.95 | 103 | $0.272 | $613 | $136 | none (floor $453 > ceiling $429) | none (floor $453 > ceiling $307) |
| mean skip | 81% | $1.23 | $3.95 | 103 | $0.272 | $613 | $136 | none (floor $454 > ceiling $429) | none (floor $454 > ceiling $307) |
| mean, AWS on-demand only | 81% | $1.23 | $3.95 | 103 | $0.567 | $613 | $284 | none (floor $946 > ceiling $429) | none (floor $946 > ceiling $307) |
| mean, capture overhead 1.1x | 81% | $1.23 | $3.95 | 103 | $0.272 | $613 | $136 | none (floor $454 > ceiling $429) | none (floor $454 > ceiling $307) |
| mean, customer on 8-core | 81% | $1.72 | $4.44 | 103 | $0.272 | $860 | $136 | $454-602 | none (floor $454 > ceiling $430) |
| mean, customer on 16-core | 81% | $2.78 | $5.50 | 103 | $0.272 | $1,388 | $136 | $454-972 | $454-694 |
| mean, GitHub 2025 prices | 81% | $1.64 | $5.57 | 103 | $0.272 | $818 | $136 | $454-572 | none (floor $454 > ceiling $409) |
| agents 5x (2,500 runs), mean skip | 81% | $1.23 | $3.95 | 103 | $0.272 | $3,066 | $681 | none (floor $2,269 > ceiling $2,146) | none (floor $2,269 > ceiling $1,533) |
| agents 5x, skip 51% cap | 51% | $1.23 | $3.95 | 103 | $0.273 | $3,066 | $683 | none (floor $2,275 > ceiling $2,146) | none (floor $2,275 > ceiling $1,533) |

### tightly coupled library (vue-core)

Run shape: 2 test jobs; PR run.

| scenario | skip | GitHub $ test jobs / run | GitHub $ whole run | fenvix min / run | fenvix $ / run | GitHub $ test jobs / month | fenvix cost / month | price band, >=30% cheaper | price band, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| median skip (base) | 25% | $0.09 | $0.25 | 9 | $0.023 | $46 | $12 | none (floor $39 > ceiling $32) | none (floor $39 > ceiling $23) |
| mean skip | 31% | $0.09 | $0.25 | 9 | $0.023 | $46 | $12 | none (floor $39 > ceiling $32) | none (floor $39 > ceiling $23) |
| mean, AWS on-demand only | 31% | $0.09 | $0.25 | 9 | $0.048 | $46 | $24 | none (floor $80 > ceiling $32) | none (floor $80 > ceiling $23) |
| mean, capture overhead 1.1x | 31% | $0.09 | $0.25 | 9 | $0.023 | $46 | $11 | none (floor $38 > ceiling $32) | none (floor $38 > ceiling $23) |
| mean, customer on 8-core | 31% | $0.14 | $0.30 | 9 | $0.023 | $68 | $12 | $39-48 | none (floor $39 > ceiling $34) |
| mean, customer on 16-core | 31% | $0.23 | $0.39 | 9 | $0.023 | $115 | $12 | $39-80 | $39-57 |
| mean, GitHub 2025 prices | 31% | $0.12 | $0.35 | 9 | $0.023 | $62 | $12 | $39-43 | none (floor $39 > ceiling $31) |
| agents 5x (2,500 runs), mean skip | 31% | $0.09 | $0.25 | 9 | $0.023 | $231 | $58 | none (floor $193 > ceiling $162) | none (floor $193 > ceiling $116) |
| agents 5x, skip 51% cap | 31% | $0.09 | $0.25 | 9 | $0.023 | $231 | $58 | none (floor $193 > ceiling $162) | none (floor $193 > ceiling $116) |

### Go service, small (terraform)

Run shape: 3 test jobs; PR run; the 36-job release build runs on main pushes only.

| scenario | skip | GitHub $ test jobs / run | GitHub $ whole run | fenvix min / run | fenvix $ / run | GitHub $ test jobs / month | fenvix cost / month | price band, >=30% cheaper | price band, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| median skip (base) | 25% | $0.23 | $0.37 | 20 | $0.053 | $115 | $26 | none (floor $88 > ceiling $81) | none (floor $88 > ceiling $58) |
| mean skip | 23% | $0.23 | $0.37 | 20 | $0.054 | $115 | $27 | none (floor $89 > ceiling $81) | none (floor $89 > ceiling $58) |
| mean, AWS on-demand only | 23% | $0.23 | $0.37 | 20 | $0.112 | $115 | $56 | none (floor $186 > ceiling $81) | none (floor $186 > ceiling $58) |
| mean, capture overhead 1.1x | 23% | $0.23 | $0.37 | 18 | $0.049 | $115 | $24 | none (floor $81 > ceiling $81) | none (floor $81 > ceiling $58) |
| mean, customer on 8-core | 23% | $0.28 | $0.43 | 20 | $0.054 | $142 | $27 | $89-99 | none (floor $89 > ceiling $71) |
| mean, customer on 16-core | 23% | $0.41 | $0.55 | 20 | $0.054 | $205 | $27 | $89-144 | $89-103 |
| mean, GitHub 2025 prices | 23% | $0.31 | $0.50 | 20 | $0.054 | $154 | $27 | $89-108 | none (floor $89 > ceiling $77) |
| agents 5x (2,500 runs), mean skip | 23% | $0.23 | $0.37 | 20 | $0.054 | $576 | $134 | none (floor $446 > ceiling $403) | none (floor $446 > ceiling $288) |
| agents 5x, skip 51% cap | 23% | $0.23 | $0.37 | 20 | $0.054 | $576 | $134 | none (floor $446 > ceiling $403) | none (floor $446 > ceiling $288) |

### Go service, large (prometheus)

Run shape: 10 test jobs; PR run.

| scenario | skip | GitHub $ test jobs / run | GitHub $ whole run | fenvix min / run | fenvix $ / run | GitHub $ test jobs / month | fenvix cost / month | price band, >=30% cheaper | price band, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| median skip (base) | 56% | $0.94 | $1.83 | 62 | $0.164 | $468 | $82 | $273-328 | none (floor $273 > ceiling $234) |
| mean skip | 49% | $0.94 | $1.83 | 66 | $0.174 | $468 | $87 | $289-328 | none (floor $289 > ceiling $234) |
| mean, AWS on-demand only | 49% | $0.94 | $1.83 | 66 | $0.362 | $468 | $181 | none (floor $603 > ceiling $328) | none (floor $603 > ceiling $234) |
| mean, capture overhead 1.1x | 49% | $0.94 | $1.83 | 61 | $0.163 | $468 | $81 | $271-328 | none (floor $271 > ceiling $234) |
| mean, customer on 8-core | 49% | $1.17 | $2.07 | 66 | $0.174 | $587 | $87 | $289-411 | $289-293 |
| mean, customer on 16-core | 49% | $1.72 | $2.62 | 66 | $0.174 | $862 | $87 | $289-603 | $289-431 |
| mean, GitHub 2025 prices | 49% | $1.25 | $2.51 | 66 | $0.174 | $624 | $87 | $289-437 | $289-312 |
| agents 5x (2,500 runs), mean skip | 49% | $0.94 | $1.83 | 66 | $0.174 | $2,340 | $434 | $1,447-1,638 | none (floor $1,447 > ceiling $1,170) |
| agents 5x, skip 51% cap | 49% | $0.94 | $1.83 | 66 | $0.174 | $2,340 | $434 | $1,447-1,638 | none (floor $1,447 > ceiling $1,170) |

### Django app (saleor)

Run shape: 1 test jobs; Django loads every app in every test process.

| scenario | skip | GitHub $ test jobs / run | GitHub $ whole run | fenvix min / run | fenvix $ / run | GitHub $ test jobs / month | fenvix cost / month | price band, >=30% cheaper | price band, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| median skip (base) | 0% | $0.22 | $0.43 | 54 | $0.143 | $108 | $71 | none (floor $238 > ceiling $76) | none (floor $238 > ceiling $54) |
| mean skip | 13% | $0.22 | $0.43 | 49 | $0.130 | $108 | $65 | none (floor $217 > ceiling $76) | none (floor $217 > ceiling $54) |
| mean, AWS on-demand only | 13% | $0.22 | $0.43 | 49 | $0.271 | $108 | $135 | none (floor $451 > ceiling $76) | none (floor $451 > ceiling $54) |
| mean, capture overhead 1.1x | 13% | $0.22 | $0.43 | 22 | $0.059 | $108 | $30 | none (floor $99 > ceiling $76) | none (floor $99 > ceiling $54) |
| mean, customer on 8-core | 13% | $0.27 | $0.48 | 49 | $0.130 | $133 | $65 | none (floor $217 > ceiling $93) | none (floor $217 > ceiling $66) |
| mean, customer on 16-core | 13% | $0.38 | $0.60 | 49 | $0.130 | $191 | $65 | none (floor $217 > ceiling $133) | none (floor $217 > ceiling $95) |
| mean, GitHub 2025 prices | 13% | $0.29 | $0.58 | 49 | $0.130 | $144 | $65 | none (floor $217 > ceiling $101) | none (floor $217 > ceiling $72) |
| agents 5x (2,500 runs), mean skip | 13% | $0.22 | $0.43 | 49 | $0.130 | $540 | $325 | none (floor $1,083 > ceiling $378) | none (floor $1,083 > ceiling $270) |
| agents 5x, skip 51% cap | 13% | $0.22 | $0.43 | 49 | $0.130 | $540 | $325 | none (floor $1,083 > ceiling $378) | none (floor $1,083 > ceiling $270) |

### small library (flask-like)

Run shape: 8 test jobs; PR run.

| scenario | skip | GitHub $ test jobs / run | GitHub $ whole run | fenvix min / run | fenvix $ / run | GitHub $ test jobs / month | fenvix cost / month | price band, >=30% cheaper | price band, >=50% cheaper |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| median skip (base) | 0% | $0.14 | $0.34 | 14 | $0.038 | $72 | $19 | none (floor $63 > ceiling $50) | none (floor $63 > ceiling $36) |
| mean skip | 22% | $0.14 | $0.34 | 13 | $0.036 | $72 | $18 | none (floor $59 > ceiling $50) | none (floor $59 > ceiling $36) |
| mean, AWS on-demand only | 22% | $0.14 | $0.34 | 13 | $0.074 | $72 | $37 | none (floor $123 > ceiling $50) | none (floor $123 > ceiling $36) |
| mean, capture overhead 1.1x | 22% | $0.14 | $0.34 | 13 | $0.034 | $72 | $17 | none (floor $56 > ceiling $50) | none (floor $56 > ceiling $36) |
| mean, customer on 8-core | 22% | $0.24 | $0.43 | 13 | $0.036 | $121 | $18 | $59-85 | $59-60 |
| mean, customer on 16-core | 22% | $0.44 | $0.63 | 13 | $0.036 | $220 | $18 | $59-154 | $59-110 |
| mean, GitHub 2025 prices | 22% | $0.19 | $0.45 | 13 | $0.036 | $96 | $18 | $59-67 | none (floor $59 > ceiling $48) |
| agents 5x (2,500 runs), mean skip | 22% | $0.14 | $0.34 | 13 | $0.036 | $360 | $89 | none (floor $296 > ceiling $252) | none (floor $296 > ceiling $180) |
| agents 5x, skip 51% cap | 22% | $0.14 | $0.34 | 13 | $0.036 | $360 | $89 | none (floor $296 > ceiling $252) | none (floor $296 > ceiling $180) |
## Open items

* Verify all DECLARED prices (GitHub runner pricing page, AWS on-demand and spot history) once web access is allowed.
* Measure real job durations of these projects' CI (GitHub API job timings were not reachable: 403). Our shapes are
  ESTIMATED except the test steps listed as MEASURED.
* Measure the skip share of **e2e / build-a-site jobs** (docusaurus type): it decides whether JS monorepos are a cost
  market at all.
* Measure the fixed per-run overhead (1 min ESTIMATED) and the production capture overhead (strace 1.5-2.6x MEASURED;
  the model shows how much a 1.1x capture is worth).
* saleor skip share is partial (29 of 50 transitions).
