PARTIAL: mean share of test time reused with proof on dependency-only commits 39% with the prototype (today's engine 20%), over 130 pairs in 10 repositories; 0 wrong over 16,464 verified reuses; 7 of 7 tests that broke were inside the affected set (MEASURED)

# Dependency-update verdict: validation plan of idea 3

Task: prompt P-028 (the validation plan "Idea 3" in `sessions/2026-11-18-fable-new-value/REPORT.md`). Measured only; no product was built. The prototype sits behind a flag (`--det-cache-dists`) and changes nothing when the flag is off.

## Verdict against the bar

| criterion (prompt) | bar | result | label |
|---|---|---|---|
| mean share of test time reused with proof, dependency-only commits | YES ≥ 50%, NO < 25% | **39.1%** mean over 130 pairs; 26.2% mean of the 10 repository means; 14.2% of all pooled test time | MEASURED |
| same with today's engine (one digest of the whole environment) | (comparison) | 20.1% over pairs; 15.2% mean of repository means; 10.0% pooled | MEASURED |
| wrong reuses | 0 over ≥ 5,000 verified | **0 wrong, 0 flaky over 16,464** verified prototype reuses (today: 0 over 6,048). With 0 errors in 16,464, the 95% upper bound on the error rate is 0.018% (rule of three) | MEASURED |
| historically broken tests inside the affected set | 100% | **7 of 7** in our own runs (3 through the distribution identity, 4 because they were never cached). The tests that broke in the projects' own CI after a bump: names UNKNOWN (logs not readable, see step 4) | MEASURED / UNKNOWN |

Why PARTIAL and not NO: the dependency part of the prototype works wherever the engine can already cache the suite (table below: esphome 82%, moto 76%, community.general 58%, against 0%, 63% and 47% today). The mean is low because, in 5 of the 10 repositories, the engine refuses almost every test for reasons that have nothing to do with dependencies. Those repositories score about 0% in both modes. There are also two structural limits of the per-distribution rule (findings 2 and 3 below).

## Numbers

### Step 1: dependency-only commits (MEASURED, unchanged since INTERMEDIATE-1)

The last 30 dependency-only commits per repository (only 20 exist in community.general) are a small share of all commits: 8.5% (prefect), 5.0% (esphome), 2.0% (mlflow), 1.0% (airflow), and 0.4% to 0.5% for the other six (share of first-parent commits in the span they cover). Over the market test's 92 days the share is 0% to 7.2%. The full table, with the rule used and where the files are, is in `INTERMEDIATE-1.md` and `harness/dep_verdict/commits.json`.

### Steps 2 and 3: share reused with proof, today vs prototype (MEASURED)

Method, per pair (P = parent, C = dependency-only commit):
- Install C, then P. Run each sampled test file in its own process at P with the prototype (D0) and with today's engine (T0), both cold.
- Reinstall C. Run D1 and T1 against those caches, then a fresh `--det` run B at the same clock epoch.
- Compare every reused outcome with B. A mismatch gets a second fresh run B2, which tells "wrong" (the reused result differs from two fresh runs) from "flaky".
- Shares are test-time shares over the sampled test files, using durations from the fresh run (sample: the market test's units, capped per repository).
- T runs only when the environment is unchanged, or for the first pair of a job. When the environment changes, T is 0 by construction: the runtime digest differs.

| repository | pairs measured | of which the installed environment changed | D share, mean | T share, mean | D share, env-changed pairs only | test time the cache could serve (cacheable) | D of cacheable time | D of dependency-eligible time (a) | verified D reuses (wrong) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| esphome | 23 | 23 | **82%** | 0% | 82% | 100% | 82% | 82% | 8,030 (0) |
| moto | 21 | 7 | **76%** | 63% | 40% | 94% | 81% | 81% | 3,184 (0) |
| community.general | 20 | 5 | **58%** | 47% | 44% | 62% | 92% | 95% | 3,381 (0) |
| integrations-core | 7 | 1 | 37% | 37% | 0% | 100% | 37% | 80% | 32 (0) |
| pydantic-ai | 21 | 15 | 8% | 4% | 6% | 61% | 17% | 21% | 1,029 (0) |
| transformers | 3 | 0 | 1% | 1% | - | 2% | 66% | 67% | 808 (0) |
| airflow | 4 | 1 | 0% | 0% | 0% | 0% | - | - | 0 |
| litellm | 7 | 4 | 0% | 0% | 0% | 0% | - | - | 0 |
| mlflow | 20 | 15 | 0% | 0% | 0% | 0% | - | - | 0 |
| prefect | 4 | 2 | 0% | 0% | 0% | 0% | - | - | 0 |
| **all** | **130** | **73** | **39.1%** | **20.1%** | **33.8%** (T 0%) | 57.7% | | | **16,464 (0)** |

(a) Among tests the cache would otherwise serve (reused, or missed only because a distribution identity, the pytest configuration or plugins, or the runtime changed): the share the prototype kept. This isolates the dependency effect from engine refusals and from non-dependency misses.

Other cuts (MEASURED):
- On the 57 pairs where the installed environment did not change (for example a commit touching only `docs/requirements.txt`), D = T = 45.8%. On the 73 pairs where it changed, D = 33.8% and T = 0%.
- On the 76 pairs where at least half of the test time is cacheable, D = 62.2% and T = 31.8%.

Pairs not measured: 168 of 298 listed (MEASURED).
- 49 have install failures at old commits:
  - integrations-core 19: before 2023 there is no `agent_requirements.in`; dv1 also had a Python 2-only integration.
  - transformers 15: local runs only; `download.pytorch.org` is blocked by this container's network.
  - moto 8: 2013 to 2019 layouts on Python 3.12.
  - pydantic-ai 7: the extra the spec excludes did not exist yet; fixed for the later runs.
- 24 ran no tests:
  - litellm 19: before 2026-04 it used poetry and tests outside `tests/unit`.
  - integrations-core 4, moto 1.
- The rest were not reached within the runner budget. The Actions run gets about 5 concurrent runners, because other workflows share the account.

What makes the prototype rerun a test, over all measured pairs (MEASURED, D1 miss reasons):
- **"new"**: no result recorded at P because the engine refused the test or the test did not pass. This dominates airflow, litellm, mlflow, prefect and most of transformers. Engine refusal causes, one line each:
  - airflow: `uv` started as a subprocess at plugin import, and it reads the real clock.
  - litellm: `pytest_socket` resolves `localhost` between tests.
  - mlflow: `/proc/meminfo` is read between tests; a `git` subprocess is still running at session end.
  - prefect: the real clock is read in SQL at import (`aiosqlite`).
  - transformers: `ffmpeg` is started as a subprocess at import of a test module.
- **Distribution identity** (the per-test rule working as designed): moto `d/boto3` 349 tests, `d/requests` 131, `d/mock` 117; pydantic-ai `d/genai-prices` 283, `@all` 250, `d/pillow` 158, `d/cuda-toolkit` 158, `d/transformers` 148; community.general `d/setuptools` 113.
- **config** (pytest plugins changed, so every test reruns): esphome `pytest-asyncio` bumps (552 and 228 tests); pydantic-ai `cassetter` (351); transformers 325; integrations-core 30. esphome also showed it on two `platformdirs` bumps (93 and 228 tests); the cause is not investigated, and `platformdirs` is not a pytest plugin.
- **Non-dependency data misses**: directory listings and `/proc/self/fd` (findings 4 to 6).

Prototype cost (MEASURED, per test process):
- Building the distribution index takes 0.077 s (median), 0.39 s at p90.
- A test records a median of 36 identity keys (p90 246).
- 781 of 31,828 recorded tests (2.5%) depend on `@all`, the whole set of distributions.
- The check takes 0.003 s (median) per process.

### Step 4: known breakages

Our own runs (MEASURED): 7 tests passed at P and failed in the fresh run at C. All 7 were rerun by the prototype, so they are inside the affected set.
- moto `6e705a82e3` (setup.cfg, boto3 bump): `test_opsworks/test_layers.py::test_create_layer_response`, `::test_describe_layers` and `test_sqs/test_sqs_integration.py::test_invoke_fake_function_from_sqs_queue` were rerun through `d/boto3`. `test_sqs_integration.py::test_invoke_function_from_sqs_queue` and `::test_invoke_function_from_sqs_fifo_queue` were never cached: they start Docker or Lambda-like subprocesses.
- transformers `579f7a9b9e`: `tests/cli/test_download.py::test_cli_download` and `::test_cli_download_trust_remote` were never cached (network). Whether the bump caused these failures is UNKNOWN: B2 runs only on cache mismatches.

The projects' own CI (MEASURED where stated):
- **Reverts** of a dependency-only commit among the later commits: 0 found in the 10 repositories.
- **Newly failed checks** on C compared with P: 57 of 298 pairs. Their annotations name no test: almost all are infrastructure failures (Dependabot updater errors, missing artifacts, docs deploys, runner losses).
- Test-job failures: airflow `49423f8d65` (Non-DB providers) and `381339d5e7` (Helm); prefect `bf195ab012`, `29241a3aff`, `761de4f26e`, `d672b5e920`; mlflow `074c0fcf4f`, `f6314d0476`; litellm CircleCI jobs on 16 pairs. Their failing test names are UNKNOWN: GitHub job logs of other repositories returned 401 or 410 to the workflow token, and CircleCI is outside our access.
- Pairs we measured from that list (prefect `543767a6e0`, mlflow `074c0fcf4f`, airflow `6b1436e3c4`) had every test refused, so the "inside" check holds there trivially.
- airflow `6b1436e3c4` is followed by "Fix common.ai Anthropic models failing against anthropic 1.x in the CI image (#73511)": a real breakage by its own words.

### Step 5: footprint of the affected tests before and after the bump (MEASURED)

18 pairs had tests rerun through a distribution identity: 2,151 tests in all. For 1,548 of them (72%) the footprint was identical before and after: the same files, the same environment variables, the same distributions. Only the version changed.

Where the footprint changed:
- moto `6e705a82e3` (the pair where tests broke): 176 affected tests. At C they read up to 28 new environment variables (`AWS_REQUEST_CHECKSUM_CALCULATION`, `AWS_RESPONSE_CHECKSUM_VALIDATION`, `BOTOCORE_TCP_KEEPALIVE`, `AWS_BEARER_TOKEN_<SERVICE>` and others). They also load `s3transfer` and two new stdlib modules (`mmap`, `_posixshmem`). The neighbouring pair `474edb083f` shows the same set disappearing.
- moto `b4b873ed4b`: `sure` was replaced by `surer`, and `mock` was dropped.
- community.general: `setuptools` no longer read (113 tests); `opentelemetry-*` and `OTEL_PYTHON_CONTEXT` gone (4 tests).
- New hosts: none observed. Tests that open connections are refused by the engine, so they have no recorded footprint to compare (UNKNOWN for them).

## Findings that matter for the decision

1. **The per-distribution rule is sound in this sample.** 16,464 reuses were verified against a fresh run with 0 wrong. Every test that broke was rerun. On esphome, where every pair changed the environment, it reused 82% of test time where today's engine reuses 0% (MEASURED).
2. **Bumps of a pytest plugin rerun everything.** The configuration identity includes every pytest plugin's version (`config_identity`). This is right by default: a plugin hooks into every test. It accounts for esphome's misses and part of pydantic-ai's (MEASURED).
3. **Distributions imported at session start count for every test.** The loaded-module rule (a distribution loaded before a test counts for it) is what keeps the proof safe. When the project's own package imports the bumped distribution at import time, every test depends on it. pydantic-ai imports `genai_prices`; `pillow`, `torch` and the CUDA libraries are loaded at collection. Escaping this needs an identity finer than "loaded": the functions of the distribution that a test executed, as the engine already does for repository code. Its effect is UNKNOWN; this is the largest gap between the idea's promise ("312 of 9,400 tests") and what the prototype can prove.
4. **A test that lists site-packages misses on every commit, whatever changed.** In pydantic-ai, the project's own editable install has a version that embeds the commit hash (`pydantic_ai-2.9.1.dev3+f1c73056c.dist-info`), so the directory listing changes on every commit (110 to 370 tests per pair; MEASURED). This is the "package metadata that embeds the commit hash" cause already in the brain, now seen through a listing. A fix is to treat a listing of a site directory as the set of installed distributions without the project.
5. **Engine findings unrelated to dependencies** (each MEASURED; for the components):
   - `esphome tests/unit_tests/test_espota2.py` hangs under `--det` until the 900 s unit timeout, in every mode (pytest-timeout does not fire). It is excluded in the spec.
   - `/proc/self/fd` is recorded as an ordinary directory-listing dependency (integrations-core). It changes on every run, so those tests always miss; it should be refused or ignored.
   - Some listings of repository directories differ between P and C runs without any tracked file changing: integrations-core `datadog_checks_base/`, pydantic-ai repository root (20 tests on Actions). Cause UNKNOWN. A minimal project did not reproduce the miss (`.detpy/` created during a run was the suspect). The harness now creates `.detpy/` before every run; this only affected the later local pydantic-ai runs.
6. **Harness artifact, fixed in dv3.** The harness set `CP_TIMES_OUT` to a different path on each run. Tests that read the whole environment then missed on `env: *`: 75 tests in the 7 community.general pairs from dv1 and 21 in esphome's first local pairs, both counted as misses above. dv3 and the later local runs use one path.

## What I decided

- I used the engine branch `claude/dep-verdict-abjcfw`, not `claude/dep-verdict`: the session may push only there. It starts from `claude/cache-proof-step1` (3e41ee0c).
- Identity files are stored as ordinary data dependencies under `<cache>/dist-identity/`, so the Rust checker is unchanged.
- One virtualenv path and the install order C → P → C, so that RECORD digests (which include script shebangs) are comparable.
- Runs were cut down to fit the runners: dv1 was cancelled after its first jobs; dv2 was cancelled at once for the harness bug in finding 6; dv3 has 14 jobs. This container ran the rest (`results/local/`).
- Cutoff at 06:15 UTC. Actions jobs still running then (prefect, litellm, moto, integrations-core, transformers, community.general, esphome) keep committing to `harness/dep_verdict/results/dv3/`. They are not in these numbers. Most are repositories where the engine refuses tests, so the verdict should not move; re-run `analyze.py` to refresh.
- Reported three means: over pairs (the prompt's "mean share"), over repositories, and pooled time. They answer different questions; the first line uses the first.

## What blocks or is missing

- Failing test names from the projects' CI are UNKNOWN. GitHub job logs of other repositories are refused (401/410) with a workflow token; check-run annotations carry no test names; CircleCI logs are outside our access. Getting them needs a token with read access to public Actions logs, or re-running the suspect pairs with the full test job.
- 168 of 298 listed pairs were not measured (installs at old commits, runner budget). The sample is weighted towards recent commits.
- The finer identity in finding 3 (functions executed inside a distribution) is the next measurement worth doing. Without it, a dependency verdict on projects that import their dependencies at package import cannot get much better than today's engine.

## Links

- Engine: `Mircoguidetti/fenvix-engine-cli`, branch `claude/dep-verdict-abjcfw`:
  - prototype + harness: commit 81354c25;
  - prototype tests: 7f353b0f;
  - local results and the cutoff summary: 0b870333.
- Prototype: `python/detpy/distid.py`; flag in `python/detpy/plugin.py`; hooks in `python/detpy/proofcache.py`; tests in `tests/test_dep_verdict_distid.py` (3 new tests pass; existing proof-cache tests 60 passed, 1 skipped, flag off).
- Harness: `harness/dep_verdict/`:
  - scripts: `find_commits.py` (step 1), `pairs.py` (steps 2, 3 and 5), `ci_status.py` and `annotations.py` (step 4), `analyze.py` (tables);
  - data: `commits.json`, `specs/`;
  - workflows: `.github/workflows/dep-verdict.yml`, `dep-verdict-annotations.yml`.
- Results:
  - `harness/dep_verdict/results/dv1/`: Actions run 44427655182, cancelled; includes `ci-status.json` and `annotations.json`.
  - `harness/dep_verdict/results/dv3/`: Actions run 44446439835.
  - `harness/dep_verdict/results/local/`.
  - Summary: `harness/dep_verdict/results/summary-cutoff.json`. Reproduce with `python3 harness/dep_verdict/analyze.py results/dv1 results/dv3 results/local --commits harness/dep_verdict/commits.json --json out.json`.
- Intermediate: `sessions/2026-11-18-dep-verdict/INTERMEDIATE-1.md`.

## Errors or gaps in this brain

- The idea's text says a bump's invalidation "is UNKNOWN" and names one prefect case. Now MEASURED: with today's engine, a bump that changes the installed environment reruns every cached test. T reused 0% wherever it ran on a changed environment (the first pair of each job), and it cannot do otherwise because the runtime digest covers all distributions.
- The cause table "package metadata that embeds the commit hash" should also cover directory listings of site-packages (finding 4), not only metadata reads.
- The account's Actions concurrency (about 5 runners shared with other sessions' workflows) is a planning constraint that is not written anywhere in the brain. A 60-job plan does not fit.
