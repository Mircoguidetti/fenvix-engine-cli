# Measurement harness

`harness/detpy_harness.py` evaluates Level 0 on public repositories listed in
`harness/repos.json`.

## Procedure

1. **Prepare** (in parallel): `git clone --depth 1`; `uv venv` with the
   harness interpreter (Python 3.13); install the project in editable mode with
   its test dependencies, detected in this order: optional-dependency extras
   whose name contains `test`, dependency groups whose name contains `test`
   (else `dev`), well-known requirement files (`requirements/tests.txt`,
   `test-requirements.txt`, …), plus per-repo `install` extras from
   `repos.json`. Failed attempts fall back to fewer sources. The detpy wheel is
   (re)installed in every venv. `pytest --collect-only` must succeed; if it
   only succeeds with `-o addopts=` (e.g. flags of plugins that are not
   installed) that override is used for *both* modes.
2. **Measure**: for `i in 0..N`: one normal run, then one `--det` run
   (interleaving cancels slow drifts of the machine). Both modes use
   `-p no:cacheprovider` and `--det-outcomes` to collect the outcome of every
   test. Wall time is measured around the subprocess, so it includes the
   interpreter re-exec done by `--det`. Repositories whose first normal run
   exceeds `--max-first-run` seconds are dropped (and replaced, with `--limit`).
3. **Analyse**: the `--det` traces are compared with the Rust verifier.

## Definitions

* **unstable** (per mode): the test does not have the same outcome in every
  completed run of that mode (absence from a run counts as an outcome, e.g.
  parametrisation ids that change between runs).
* **became stable**: unstable without `--det`, stable with it.
* **outcome changed by det**: stable in both modes but the majority outcome
  differs (typically: a test that needs the network or real time passes
  normally and fails consistently under `--det`). This is a *cost* of Level 0.
* **covered by Level 0**: identical fingerprint in every `--det` run.
  **not covered**: at least two runs differ; `reason` is the class of the first
  diverging event (`time`, `random`, `fs`, `net`, `entropy`, `thread`,
  `outcome-only` = same observed events but different outcome, `beyond-trace`,
  `missing`).

## Output (`harness/results/<set>/`)

`<repo>.csv` (one row per test):

| column | meaning |
|---|---|
| `nodeid` | pytest node id |
| `normal_outcomes`, `det_outcomes` | histogram over runs, e.g. `failed=2;passed=8` |
| `normal_stable`, `det_stable` | see above |
| `became_stable`, `became_unstable`, `outcome_changed_by_det` | see above |
| `normal_majority`, `det_majority` | most frequent outcome |
| `fingerprint_covered` | identical fingerprint in every `--det` run |
| `distinct_fingerprints` | number of different fingerprints over the `--det` runs |
| `reason`, `divergence` | classification and description of the first divergence |

`<repo>_runs.csv`: one row per run (`mode, run, duration_s, exit_code,
timed_out, tests, passed, failed, error, skipped, other`).

`REPORT.md` and `summary.json`: aggregates, per-repo table, examples and the
list of excluded repositories with the reason.
