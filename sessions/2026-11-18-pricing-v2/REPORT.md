PARTIAL

**Blocked hosts (session proxy answered 403), read this first:**
* `website.spot.ec2.aws.a2z.com`: today's AWS spot prices. **Spot today is UNKNOWN.** The only AWS-hosted spot file I could reach is dated 2024-05-13; it is used in one scenario, marked STALE.
* `www.ecb.europa.eu`: the EUR/USD rate. Hetzner prices are DECLARED in EUR; the conversion (1.15) is ESTIMATED.
* `docs.hetzner.com`: Hetzner billing details. The hourly billing rule comes from the product page instead.
* `b0.p.awsstatic.com`: the data file behind the AWS pricing page. Worked around: on-demand prices come from AWS's own price list file.

Everything else in the prompt is delivered. PARTIAL only because of the spot price.

# P-020 · Pricing v2: plans against GitHub, Blacksmith and Antithesis

Session 2026-11-18. fenvix-engine-cli branch `claude/pricing-v2`. Model: `pricing/model.py` (`python3 pricing/model.py` rewrites `pricing/data/tables.md` and `results.json`; tables T1 to T17 below are copied from it). Tests: `python3 -m pytest -q pricing/test_model.py`, 7 passed (MEASURED).

## Answer in six lines

1. **Against GitHub, a price exists for every large shape.** The proposed plans sit 57% to 65% below GitHub's list price (ESTIMATED from DECLARED prices).
2. **Against Blacksmith at its list price, a price with a healthy margin (60%) exists only for a large modular Python monorepo with a mean skip of about 75% or more.** Home-assistant-like at the reviewed 82%: yes, 69% margin. Prefect-like (73%, PROVISIONAL): 57% on AWS, 61% on Hetzner. Airflow-like (56%, PROVISIONAL): 32%, thin.
3. **Against Blacksmith at its "2x faster" claim plus its free minutes, no shape has a healthy price today.** Best case 37% margin (home-assistant-like, AWS on-demand). The claim is the vendor's; we have not measured it.
4. **No price exists for the small library, the mid Django service, the JS monorepo and the Go service**, on any machine I could price today. Reasons are in section 2.
5. **Two numbers decide everything:** the mean skip share and the capture overhead. At 1.47x overhead a 56% skip removes only 31% of the minutes.
6. **Blacksmith has started to skip tests itself:** Vitest test selection (early beta, with its own shadow mode) and a Go test cache (off by default). Neither carries a proof (DECLARED, its docs).

## Sources (all read 2026-11-18, each page in full)

| fact | value | source |
|---|---|---|
| GitHub Linux x64 runners, per minute | 2-core $0.006, 4-core $0.012, 8-core $0.022, 16-core $0.042 | docs.github.com/en/billing/reference/actions-runner-pricing |
| GitHub: minutes rounded up per job | to the next whole minute | same page |
| GitHub: included compute per month | Free $12, Team $18, Enterprise Cloud $300 | docs.github.com/en/billing/concepts/product-billing/github-actions |
| GitHub: fee on self-hosted runners | none in force: self-hosted runners "remain free" and do not use the included amount | same page |
| GitHub: cache storage | 10 GB per repository included, then $0.07 per GB-month | same page |
| Blacksmith Linux x64, per minute | 2 vCPU $0.004, 4 vCPU $0.008, 8 vCPU $0.016, 16 vCPU $0.032, 32 vCPU $0.064 | blacksmith.sh/pricing; docs.blacksmith.sh/blacksmith-runners/flex-scheduling |
| Blacksmith free tier | 3,000 x64 2-vCPU minutes per organization per month; a 4-vCPU minute uses 2 | docs.blacksmith.sh/blacksmith-runners/overview |
| Blacksmith speed claim | "We are 2x faster than GitHub's runners"; "twice as fast ... for most CI jobs"; bare-metal gaming CPUs | blacksmith.sh/pricing; runners overview |
| Blacksmith total saving claim | 67%: 2x faster and 33% cheaper per minute | blacksmith.sh/pricing |
| Blacksmith flex scheduling | 40% off for jobs that can wait up to 24 hours | docs.blacksmith.sh/blacksmith-runners/flex-scheduling |
| Blacksmith add-ons | Docker layer cache and sticky disks $0.50 per GB-month; static IP $100 per month | blacksmith.sh/pricing |
| Blacksmith Vitest test selection | early beta; Vitest 5.1+; runs tests that reach a changed file through `import`, `require`, `fs`; a lockfile change runs everything; has `shadow: true` | docs.blacksmith.sh/blacksmith-selective-execution/vitest |
| its stated limits | only the test process is tracked; files read by a child process, `globalSetup` or outside Node are not | same page |
| Blacksmith Go test cache | Go 1.24+; off by default "because caching is only safe for hermetic tests"; Go "cannot see external state like databases, network services, or the clock" | docs.blacksmith.sh/blacksmith-caching/go-build-caching |
| Antithesis Teams (Beta) | $2,999 per month, 2,400 compute hours, $2.50 per extra hour, month to month; 25% off the first month | antithesis.com/pricing |
| Antithesis compute hour | "one CPU core running Antithesis simulations for one hour" | same page |
| Antithesis Enterprise | custom price, annual pool, SSO, optional single tenant | same page |
| AWS on-demand, us-east-1, Linux | m7i.xlarge $0.2016/h, c7i.xlarge $0.1785/h, c8g.xlarge $0.15952/h, m8g.xlarge $0.17952/h | pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-east-1/index.csv, published 2026-11-18 |
| AWS spot, m7i.xlarge us-east-1 | $0.0897/h, **dated 2024-05-13, STALE** | spot-price.s3.amazonaws.com/spot.js |
| AWS disk (gp3) | $0.08 per GB-month | same EC2 price list |
| AWS S3 standard | $0.023 per GB-month (first 50 TB) | .../AmazonS3/current/us-east-1/index.csv |
| AWS egress to the internet | $0.09 per GB (first 10 TB); between zones $0.01 per GB | .../AWSDataTransfer/current/index.csv |
| AWS NAT gateway | $0.045 per hour and $0.045 per GB | EC2 price list |
| Hetzner CCX23 (4 dedicated vCPU, 16 GB, 160 GB NVMe) | EUR 0.1178/h, EUR 73.49 per month, excl. VAT, billed hourly, 20 TB traffic included in the EU | hetzner.com/cloud/general-purpose |
| Hetzner CPX32 (4 shared vCPU, 8 GB) | EUR 0.0489/h | hetzner.com/cloud/regular-performance |
| Hetzner object storage | EUR 6.49 per month with 1 TB storage and 1 TB egress | hetzner.com/storage/object-storage |
| BuildPulse runners | 4 vCPU $0.008 per minute; 3,000 free minutes; claims 2x faster | buildpulse.io/pricing |
| BuildPulse Test Intelligence | $99 per month billed yearly (headline "from $119 a month"), 3M tests | same page |
| Depot runners | $0.006 per 2-vCPU minute, plus a $20 or $200 monthly plan | depot.dev/pricing |
| Namespace | Team $100 per month for 100,000 unit minutes; 4 vCPU / 16 GB = $0.008 prepaid, $0.012 overage | namespace.so/pricing |
| TestMu AI HyperExecute | $103 per parallel per month for Linux, billed annually; free plan 300 minutes | testmuai.com/hyperexecute |

All rows are DECLARED.

## 1. What a run costs us

**Method (ESTIMATED):**
* machine-minutes per run = 1 fixed minute + setup of each machine that has work + executed test minutes;
* executed test minutes = test minutes × ((1 − skip) × capture overhead + skip × 5% audit reruns);
* jobs not covered by a measured skip share run as today;
* all-in rate per machine-minute = (instance price + 80 GB disk) ÷ utilisation × 1.10 for control plane and logs;
* utilisation: 70% on AWS, 50% on Hetzner because it bills whole hours (both ESTIMATED);
* our 4 vCPU are taken as fast as GitHub's 4 vCPU (UNKNOWN, not measured);
* cache storage: 2 GB per large repository on S3, about $0.05 a month. It does not matter. Basis: 31 MB for pygments' 5,300 tests (MEASURED, shared-cache report).
* egress: the cache lives next to the machines, so it is $0. We give machines public addresses and do not use a NAT gateway.

**T1. Our rate per 4-vCPU machine-minute**

| machine | list price | our all-in rate | against GitHub $0.012 | against Blacksmith $0.008 |
|---|---|---:|---:|---:|
| AWS on-demand m7i.xlarge | $0.2016/h (DECLARED) | $0.00551 | 46% | 69% |
| AWS, 80% spot at 2024 prices | $0.0897/h (DECLARED, STALE) | $0.00317 | 26% | 40% |
| Hetzner CCX23 | EUR 0.1178/h (DECLARED), EUR/USD 1.15 (ESTIMATED) | $0.00497 | 41% | 62% |

Our minute on AWS on-demand costs 69% of the price of a Blacksmith minute. Cheap compute is not where the margin is.

**T2. Our cost per run (ESTIMATED)**

| shape | baseline min / run | mean skip | capture | our machine-min / run | AWS on-demand | Hetzner | AWS spot (STALE) |
|---|---:|---:|---:|---:|---:|---:|---:|
| small library (flask-like, 8 Python versions) | 12 | 22% MEASURED | 1.60x PROVISIONAL | 13.6 | $0.075 | $0.068 | $0.043 |
| mid service (Django, saleor-like) | 18 | 13% MEASURED, partial | 1.47x PROVISIONAL | 27.0 | $0.149 | $0.134 | $0.086 |
| large Python monorepo (airflow-like) | 172 | 56% PROVISIONAL | 1.47x PROVISIONAL | 118.6 | $0.653 | $0.589 | $0.375 |
| large JS monorepo (docusaurus-like) | 102 | 81% MEASURED, unit step only | 1.54x MEASURED | 102.8 | $0.566 | $0.511 | $0.325 |
| Go service (prometheus-like) | 78 | 49% MEASURED | 1.3x ESTIMATED | 66.5 | $0.366 | $0.330 | $0.211 |

"Baseline minutes" = 4-vCPU test-job minutes of one run on GitHub with nothing skipped (setup + tests). Run shapes are ESTIMATED from each project's workflows (pricing v1) and from the market test's serial test minutes.

**Where each input comes from:**
* skip 22% small libraries, 81% docusaurus, 49% prometheus: NUMBERS.md, skip study 2 v3.1 and study 1 (MEASURED, reviewed);
* skip 13% saleor: 29 of 50 transitions (MEASURED, partial);
* skip 56% airflow, 73.2% prefect: market test REPORT-2 (PROVISIONAL);
* capture 1.47x: home-assistant cold run against plain pytest, cache-proof step 1 (PROVISIONAL, R-009 answered FIX 5);
* capture 1.60x: median cold / plain of the 12 libraries in the same report (PROVISIONAL);
* capture 1.54x: strace study (MEASURED). Go was not recorded.

**T3. The rule, updated.** Largest share of the customer's GitHub minutes we may spend, for "30% below Blacksmith and 60% margin":

| machine | Blacksmith at list speed | Blacksmith at its 2x claim |
|---|---:|---:|
| AWS on-demand | 41% | 20% |
| AWS, 80% spot (STALE) | 71% | 35% |
| Hetzner CCX23 | 45% | 23% |

Version 1 said 95% against GitHub. Against Blacksmith the bar is 41%, or 20% if its claim holds.

## 2. Five customer shapes, monthly

Runs per month are ESTIMATED. Blacksmith "list" = same minutes at $0.008. "2x + free" = half the minutes, minus $12 of free minutes. Price = 30% below that Blacksmith bill. Margin = (price − our cost) ÷ price. Healthy means 60% or more; thin means 30% to 60%.

**T4. Our machines on AWS on-demand**

| shape | runs | GitHub | Blacksmith list | Blacksmith 2x + free | our cost | price 30% below list (margin) | price 30% below 2x + free (margin) | verdict |
|---|---:|---:|---:|---:|---:|---|---|---|
| small library | 150 | $21.60 | $14.40 | $0.00 | $11.26 | $10.08 (−12%) | $0 | no price |
| mid service | 600 | $130 | $86.40 | $31.20 | $89.29 | $60.48 (−48%) | $21.84 (−309%) | no price |
| large Python monorepo | 1,500 | $3,100 | $2,066 | $1,021 | $980 | $1,446 (32%) | $715 (−37%) | list: thin; 2x: no price |
| large JS monorepo | 1,000 | $1,226 | $818 | $397 | $566 | $572 (1%) | $278 (−104%) | no price |
| Go service | 800 | $749 | $499 | $238 | $293 | $349 (16%) | $166 (−76%) | no price |

**T5. Our machines on Hetzner CCX23**

| shape | our cost | margin at 30% below list | margin at 30% below 2x + free | verdict |
|---|---:|---:|---:|---|
| small library | $10.15 | −1% | n/a | no price |
| mid service | $80.50 | −33% | −269% | no price |
| large Python monorepo | $884 | 39% | −24% | list: thin; 2x: no price |
| large JS monorepo | $511 | 11% | −84% | no price |
| Go service | $264 | 24% | −59% | no price |

**T6. AWS with 80% spot at 2024 prices (STALE, scenario only):** large Python monorepo 61% / 21%, Go service 52% / −1%, JS monorepo 43% / −17%, small library 36% / n/a, mid service 15% / −135%. With spot, one shape reaches a healthy price against Blacksmith list. None does against the 2x claim.

**T7. Large Python monorepo, one row per measured repository (AWS on-demand)**

| repository shape | runs | mean skip | GitHub | Blacksmith list | Blacksmith 2x + free | our cost | margin at 30% below list | at 30% below 2x + free | verdict |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| airflow-like | 1,500 | 56% PROVISIONAL | $3,096 | $2,064 | $1,020 | $979 | 32% | −37% | list: thin |
| prefect-like | 600 | 73.2% PROVISIONAL | $1,822 | $1,214 | $595 | $367 | 57% | 12% | list: thin (Hetzner 61%: a price exists) |
| home-assistant-like, engine | 1,500 | 73% PROVISIONAL | $2,700 | $1,800 | $888 | $562 | 55% | 10% | list: thin (Hetzner 60%) |
| home-assistant-like, study | 1,500 | 82% MEASURED | $2,700 | $1,800 | $888 | $394 | **69%** | 37% | list: a price exists; 2x: thin |
| litellm-like | 1,500 | 23% PROVISIONAL | $12,654 | $8,436 | $4,206 | $6,671 | −13% | −127% | no price |

**Said plainly, shape by shape:**
* **Small library: no price.** Blacksmith's free minutes cover the whole bill, and GitHub Team's $18 covers most of it. Our cost alone ($11) is above what the customer pays.
* **Mid Django service: no price.** Skip is 13%, so the capture overhead makes us spend 150% of the customer's minutes.
* **Large JS monorepo: no price today.** The 81% skip covers a 0.3-minute unit step. 95% of the test-job minutes are e2e and build jobs whose skip share is UNKNOWN (taken as 0).
* **Go service: no price.** 49% skip leaves us at 85% of the customer's minutes. Blacksmith's own Go test cache skips more (60% mean on prometheus, MEASURED by us as "Go's own test cache without proof"). With it on, Blacksmith's bill drops to $346 (T9) and our margin at 30% below is −21%.
* **Large Python monorepo: a price exists against Blacksmith's list price when the mean skip is about 75% or more.** It does not exist against the 2x claim.

**T17. Mean skip a large Python monorepo needs for a 60% margin at 30% below Blacksmith**

| machine | capture overhead | against Blacksmith list | against Blacksmith 2x + free |
|---|---:|---:|---:|
| AWS on-demand | 1.47x | 76% | 90% |
| AWS on-demand | 1.1x | 67% | 87% |
| Hetzner CCX23 | 1.47x | 73% | 88% |
| Hetzner CCX23 | 1.1x | 63% | 84% |
| AWS, 80% spot (STALE) | 1.47x | 54% | 80% |
| AWS, 80% spot (STALE) | 1.1x | 38% | 72% |

Measured means today: home-assistant 82% (reviewed) and 73% (engine, PROVISIONAL), esphome 89%, moto 76%, prefect 73%, pydantic-ai 68% (market test, PROVISIONAL).

## 3. Plan table (proposal)

**How a plan is counted.** Runs differ 20 times in size, so one flat price per run cannot work (version 1 showed this). The plan counts **run units**:
* 1 run unit = 10 baseline minutes;
* a repository's run is worth a fixed number of units, measured once in shadow mode and fixed for the plan period. Example: a 170-minute suite = 17 units per run;
* the customer buys runs. What we skip never changes its bill. Fewer minutes are our margin, as the 2026-11-17 decision asks.

**T10. Plans**

| plan | run units / month | price / month | per unit | above the limit | below GitHub | below Blacksmith list | against Blacksmith at 2x |
|---|---:|---:|---:|---|---:|---:|---:|
| Shadow | everything, 30 days | $0 | - | nothing is skipped; the customer keeps its runner | - | - | - |
| Starter | 2,500 | $129 | $0.0516 | $0.056 per unit | 57% | 36% | 29% dearer |
| Team | 10,000 | $479 | $0.0479 | $0.052 per unit | 60% | 40% | 20% dearer |
| Scale | 30,000 | $1,350 | $0.0450 | $0.049 per unit | 62% | 44% | 12% dearer |
| Monorepo | 100,000 | $4,200 | $0.0420 | $0.046 per unit | 65% | 48% | 5% dearer |

Reference prices per unit (DECLARED): GitHub $0.12, Blacksmith $0.08, Blacksmith at its 2x claim $0.04. Ceilings for "30% below": $0.056 and $0.028.

**One-line reasons:**
* **Shadow, free, 30 days:** we run next to the customer's CI, skip nothing, and show the minutes and the receipts we would have saved. It also measures the run size and our real share of its minutes.
* **Starter $129:** the smallest repository that passes the gate; about 150 runs of a 170-minute suite.
* **Team $479:** about 590 runs of that suite; prefect-sized.
* **Scale $1,350:** about 1,760 runs; airflow or home-assistant-sized.
* **Monorepo $4,200:** about 5,900 runs; the agent-heavy case.
* **Above the limit:** runs keep going at the overage price, which is still 30% below Blacksmith list. No run is ever blocked or slowed.
* **Every price, overage included, is at or under $0.056:** each plan keeps the "30% below Blacksmith list" promise at any usage (tested in `test_model.py`).

**The gate.** We sell a paid plan only when shadow mode shows our machine-minutes at or under 35% of the baseline. Below that share our margin is healthy; above it we would sell at a loss.

**T12. The plans applied to the measured monorepos (AWS on-demand)**

| shape | run units | our share of baseline minutes | passes the gate | cheapest plan | price | our cost | our margin | against GitHub | against Blacksmith list | against Blacksmith 2x + free |
|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| airflow-like | 25,800 | 69% | no | Team + overage | $1,301 | $979 | 25% | 58% below | 37% below | 28% dearer |
| prefect-like | 15,180 | 44% | no | Team + overage | $748 | $367 | 51% | 59% below | 38% below | 26% dearer |
| home-assistant-like, engine | 22,500 | 45% | no | Team + overage | $1,129 | $562 | 50% | 58% below | 37% below | 27% dearer |
| home-assistant-like, study | 22,500 | 32% | yes | Team + overage | $1,129 | $394 | 65% | 58% below | 37% below | 27% dearer |
| litellm-like | 105,450 | 115% | no | Monorepo + overage | $4,451 | $6,671 | −50% | 65% below | 47% below | 6% dearer |

Of the five generic shapes, none passes the gate today (T11 in `tables.md`): their shares are 69% to 150%.

**The choice for the founder.** No price is both 30% below Blacksmith at its 2x claim and healthy for us. Two ways to set the table:
* **A (proposed above): price against Blacksmith's list price.** Healthy on monorepos that pass the gate. If the 2x claim is true on the customer's suite, a Blacksmith customer pays 5% to 29% less there than with us.
* **B: price at $0.028 per unit**, 30% below Blacksmith even at 2x and 77% below GitHub. Margin today: 37% on home-assistant-like at 82% skip, 10% to 14% on prefect-like and the engine's home-assistant number, negative on airflow-like.

I propose A now, and B only after the three levers below move.

**What would open table B (remedies and the next test for each):**
1. **Capture overhead from 1.47x to 1.1x.** Lifts home-assistant-like from 37% to 51% margin against 2x. Test: the cold-run target of cache-proof step 1 (1.25x) is still open.
2. **Machines as fast as Blacksmith's.** Its speed comes from bare-metal gaming CPUs (DECLARED). If we rent the same class, our minutes halve too. Price and speed are UNKNOWN: no dedicated-server price was read today. Test: read Hetzner's dedicated prices, then time one suite on one such machine.
3. **Is the 2x real on test suites?** UNKNOWN. Test at $0: one of our study suites on Blacksmith's free 3,000 minutes. It needs a vendor account, so it needs the founder's yes.
4. **Today's spot price.** With the 2024 spot price the monorepo margin goes from 32% to 61% (T6). Needs the blocked host, or an AWS account.

## 4. Antithesis

**Facts (DECLARED, antithesis.com/pricing, antithesis.com, antithesis.com/product/what_is_antithesis, antithesis.com/blog/2026/plugin-launch):**
* It sells deterministic simulation testing: the customer deploys its whole system (containers, Docker Compose or Kubernetes, x86 only) and declares properties. Antithesis injects faults and explores.
* Price unit: the compute hour, one CPU core for one hour. Teams: $2,999 per month for 2,400 hours, then $2.50 per hour. Enterprise: custom, annual.
* Stated buyers: "engineering teams building mission-critical systems". Listed industries: capital markets, databases, event streaming, blockchains, ledgers, distributed systems. Named users: Jane Street, Confluent, the Ethereum Foundation, etcd.
* It is moving down-market. Teams is self-serve since the 2026-11-16 post "Antithesis is now for everyone": a credit card and a Google login, no sales process. The home page says it is "fast enough to run in CI".
* It says there is no free version: "Antithesis is compute-intensive by nature".

**T16. Price of a CPU core-hour (DECLARED prices)**

| | USD per core-hour | multiple of Blacksmith |
|---|---:|---:|
| Antithesis Teams, included hours | $1.25 | 10.4x |
| Antithesis Teams, extra hours | $2.50 | 20.8x |
| GitHub 4-core runner | $0.18 | 1.5x |
| Blacksmith 4 vCPU | $0.12 | 1.0x |
| fenvix Starter, per baseline core-hour | $0.077 | 0.6x |
| fenvix Monorepo, per baseline core-hour | $0.063 | 0.5x |

**How our offer relates:**
* **Different buyer today.** Antithesis needs a containerised system plus written properties, and starts at $2,999 a month. We take the existing pytest, Vitest or Jest suite with one changed line.
* **Different job.** It searches for unknown bugs with fault injection. We make the suite the team already has reproducible, and skip what is proven unchanged.
* **Same word, and it is coming closer.** Self-serve, agent skills and "in CI" are aimed at everyday verification. A customer may hold both; nothing on its pages offers skip or cheaper CI minutes.
* **What a determinism premium could be.** Antithesis shows buyers pay 7 to 10 times commodity compute for deterministic compute that finds and reproduces bugs.
  * Our plans do the opposite: they charge less than commodity compute.
  * The place for a premium is exploration (nightly orders and seeds), which is deterministic compute bought to find bugs, like theirs.
  * A possible price: $0.40 to $0.60 per core-hour of exploration (ESTIMATED), 3 to 5 times Blacksmith and a third to a half of Antithesis. No evidence yet that anyone pays it: UNKNOWN.
  * It would also be the paid offer for the shapes with no cost price (small library, Django service).

## 5. Risks

**T14. Our margin at a price 30% below Blacksmith (list / 2x + free), AWS on-demand**

| shape | base | skip 20 points lower | capture 1.1x | Blacksmith skips the same share | GitHub and Blacksmith both cut 25% |
|---|---|---|---|---|---|
| airflow-like | 32% / −37% | 4% / −94% | 48% / −5% | −22% / −150% | 10% / −83% |
| prefect-like | 57% / 12% | 29% / −46% | 67% / 32% | −5% / −120% | 42% / −17% |
| home-assistant-like (82%) | 69% / 37% | 40% / −22% | 76% / 51% | 9% / −89% | 58% / 15% |
| Go service | 16% / −76% | 3% / −103% | 21% / −65% | −21% / −160% | −12% / −135% |

Hetzner is better in every cell (T15 in `tables.md`).

* **Skip shares lower than measured.** 20 points lower takes the best shape from 69% to 40% and every other shape to a thin or negative margin.
  * The plan protects us in one way: the gate is measured on the customer's own repository before any paid plan.
  * It does not protect us after signing: the price is per run, so a repository that becomes more coupled costs us, not the customer. Remedy: re-measure the run size and the gate each quarter.
  * The market-test and cache-proof numbers are PROVISIONAL. R-009 found 5 wrong-reuse holes; closing them can lower the skip share.
* **Blacksmith adds safe skipping.** It already ships unsafe skipping for Vitest and Go.
  * If it skips the same share as we do, at its price, no plan survives on cost (column 5).
  * What stays ours: the proof. Our head-to-head measured a files-read rule, the shape Blacksmith's Vitest page describes, at 44% skipped with 257 wrong skips, against 0 wrong for the proof rule (MEASURED on our model of the rule, not on its product). Its Go page itself says its cache cannot see databases, network or the clock.
  * So the answer is to sell "skips you can trust, with receipts" and the reproduction of flaky tests, not minutes alone.
* **GitHub cuts prices.** Our ceiling is Blacksmith's bill, so a GitHub cut alone changes nothing in the table; it shrinks the "below GitHub" figures.
  * Blacksmith prices itself as "33% cheaper than GitHub", so it would probably follow (ESTIMATED). A 25% cut by both takes the best shape from 69% to 58%.
  * A GitHub fee on self-hosted runners is not in force (DECLARED). If it returns at the $0.002 per minute once announced, it is charged on our machine-minutes: $0.007 per run unit at the gate share of 35%, about 15% of the plan price, and $0.02 per unit if we spend as many minutes as the customer did.
* **Whole-minute rounding.** GitHub rounds every job up to a minute (DECLARED). Customers with many short jobs pay more on GitHub than the model says, which helps us slightly. Blacksmith's rounding is not stated on the pages read: UNKNOWN.

## What I decided, and why

* **Blacksmith is modelled twice,** at list speed and at its 2x claim with free minutes. The claim is DECLARED and unmeasured; hiding either case would hide the decision.
* **The base case is AWS on-demand,** the only AWS price read today. Spot is a scenario because its price is stale.
* **The engine's capture overhead (1.47x, PROVISIONAL) replaces version 1's strace overhead (2.06x)** for Python: it is what the product runs.
* **Healthy margin = 60%.** Version 1 used 70%; the prompt says "healthy". Machine cost is the only cost in the model: no staff, support or payment fees.
* **Run units instead of raw runs,** so one table fits a 12-minute and a 200-minute suite.
* **No draft PR opened.** This session's instructions allow a PR only on an explicit request; COMMON.md asks for one. The branch is pushed and ready.

## What blocks or is missing

* Today's AWS spot price (blocked host). Everything that depends on it is marked STALE.
* The EUR/USD rate is ESTIMATED.
* Not measured, taken as assumptions: our utilisation (70%, 50%), the fixed minute per run, the 5% audit share, our machines' speed against GitHub's, runs per month of each shape.
* The run shapes of airflow, prefect and litellm are built from the market test's serial test minutes with an assumed 10-minute shard and 2.5-minute setup. Their real CI job minutes were not read.
* e2e and build jobs of JS monorepos: skip share UNKNOWN. It decides whether that shape is a market.
* AWS public IPv4 and Hetzner dedicated-server prices were not read; both sit inside the 10% allowance or the remedies list.

## Links

* fenvix-engine-cli, branch `claude/pricing-v2` (from `claude/loving-maxwell-58mv2w`).
* `pricing/model.py`, `pricing/test_model.py`, `pricing/data/tables.md` (T1 to T17), `pricing/data/results.json`.
* `pricing/REPORT.md` is version 1, now marked superseded.
* This report: `sessions/2026-11-18-pricing-v2/REPORT.md` on the same branch.

## Errors or gaps found in the brain

* **COMPETITORS.md, Blacksmith:** "it could add a cache and flaky detection" is out of date. It ships Vitest test selection (beta), a Go test cache, Bazel, Turborepo and Nx caches, and test analytics. Its pricing page announces a Series C led by Sequoia at a $1B valuation; NUMBERS.md says "$125M raised".
* **Blacksmith's own pages disagree:** the runners page says "exactly half the cost of GitHub's per minute", the pricing page says 33% cheaper. The prices themselves are consistent ($0.008 against $0.012).
* **NUMBERS.md, BuildPulse:** "runners 50% below equivalent GitHub runners" is now 33% per minute ($0.008 against $0.012); the 50% is its total claim with 2x speed. Flaky-test plans: $99 per month billed yearly.
* **NUMBERS.md, Antithesis:** confirmed on the primary page, no longer "via Fable". Add: Teams is Beta, self-serve since 2026-11-16.
* **NUMBERS.md, GitHub self-hosted fee:** confirmed not in force on the billing page read today.
* **PRODUCT.md** still says "about $8 on GitHub-hosted runners vs well under $1 on our interruptible machines" for 1,000 test-minutes. At today's prices: $12 on GitHub 4-core ($6 on 2-core), $8 on Blacksmith 4 vCPU, $5.51 on our AWS on-demand machines, $3.17 with the stale spot price (T1).
* **PRODUCT.md "How it is delivered"** still says "We do not sell runners"; DECISIONS 2026-11-17 replaced it.
* **NUMBERS.md has no market-test or cache-proof entry yet,** so this report cites the session reports directly.
