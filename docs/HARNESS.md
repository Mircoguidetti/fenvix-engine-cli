# Measurement harness

`harness/detpy_harness.py` evaluates Level 0 on two pools of repositories:

* **flaky** (25): projects from the Python section of the IDoFT dataset
  (TestingResearchIllinois/idoft, `py-data.csv`), ordered by number of known
  flaky tests and **checked out at the commit where those tests were
  detected**. `harness/select_flaky.py` builds `harness/flaky_candidates.json`
  (project, commit, known flaky test ids and their IDoFT category: `OD-Vic`,
  `OD-Brit`, `NOD`, `NIO`…). The Python version follows the commit date
  (≤2021 → 3.9/3.10, 2022 → 3.10/3.11, 2023 → 3.11/3.12, later → 3.12/3.13), and
  pytest is limited to `<8` for commits up to 2022. The FlaPy dataset (Gruber et
  al.) is published on Zenodo, which this environment cannot reach, so it is not
  used.
* **popular** (25): well-known projects with large suites, at HEAD, Python 3.13.

Each pool keeps the first 25 candidates that clone, install, collect and whose
first baseline run takes less than `--max-first-run` seconds; every discarded
candidate is listed in the report with the reason.

## Procedure per repository

1. **Prepare**: checkout; `uv venv`; install the project with its test
   dependencies (test extras, test dependency groups, requirement files, then
   fewer sources on failure), plus the detpy wheel, `pytest-randomly` and
   `pytest-xdist`. `pytest --collect-only` must succeed (if it only succeeds
   with `-o addopts=`, that override is used for every run); xdist is used when
   `--collect-only -n 2` works.
2. **Baseline** (realistic): `runs` normal runs, each with a different
   `--randomly-seed` (random order and random reseeding by pytest-randomly) and
   `-n 2` when xdist works.
3. **`--det`**: `runs` runs with `--det` (fixed order, serial: `-n 0`),
   interleaved with the baseline runs.
4. **Exploration** of every test whose outcome is unstable in the baseline:
   * the fixed `--det` order counts as seed 0: a test failing in all `--det`
     runs is reproduced with 0 seeds explored;
   * otherwise `--det --det-seed=s` for `s = 1..--seeds` (one full-suite run per
     seed); when a seed makes a pending test fail, the same seed is run
     `--confirm - 1` more times; the test is **reproduced** if it failed in all
     `--confirm` runs of that seed;
   * the exploration stops when every unstable test is reproduced, after
     `--seeds` seeds, or when the repository exceeds `--repo-budget` seconds.
5. **Analysis**: the Rust verifier compares the `--det` traces
   (coverage) and, for every unstable test, the trace of a passing `--det` run
   with the trace of a failing one (first diverging event).

## Metrics

* **main metric — reproduced**: % of baseline-unstable tests for which some
  `--det-seed` (or the fixed order) makes them fail `confirm`/`confirm` times.
* **seeds needed**: number of seeds explored before the reproducing seed was
  found (0 = fixed order).
* **pass/fail divergence**: reason of the first differing event between the
  fingerprints of a passing and a failing `--det` execution of the test.
* unstable tests that **never fail** under `--det` (Level 0 removed the
  failure cause, e.g. a time- or randomness-dependent failure) vs. those that
  **fail sometimes** (not reproducible: the cause is outside Level 0).
* slowdown of `--det` (serial) relative to the realistic baseline (random,
  parallel); cost of the deterministic bytecode precompilation (first `--det`
  run vs. later ones); behaviour changed by `--det`; fingerprint coverage
  over the fixed-order `--det` runs with the reason of each divergence.
* for the flaky pool: how many IDoFT-known flaky tests are present in the
  collected suite, unstable in our baseline and reproduced.

## Output (`harness/results/<set>/`)

`<repo>.csv`, one row per test:

| column | meaning |
|---|---|
| `nodeid` | pytest node id |
| `idoft_category` | IDoFT category when the test is a known flaky test |
| `baseline_outcomes`, `det_outcomes` | histogram over runs, e.g. `failed=2;passed=8` |
| `baseline_unstable`, `det_stable` | outcome differs between runs (absence counts as an outcome) |
| `became_stable`, `outcome_changed_by_det` | unstable → stable; stable in both modes but different majority outcome |
| `reproduced`, `repro_seed`, `seeds_needed`, `best_attempt` | exploration result (`fixed` = fixed order) |
| `pass_fail_reason`, `pass_fail_divergence` | first diverging event between a passing and a failing `--det` run |
| `fingerprint_covered`, `distinct_fingerprints`, `det_reason`, `det_divergence` | coverage over the fixed-order `--det` runs |

`<repo>_runs.csv`: one row per run (`mode` normal/det/seed, `seed`, `run`,
`duration_s`, `precompile_s`, `exit_code`, `timed_out`, outcome counts).

`REPORT.md` / `summary.json`: aggregates (overall and per pool), per-repo
table, examples, discarded repositories with the reason.
