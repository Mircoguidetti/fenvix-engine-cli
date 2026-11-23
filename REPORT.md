DONE
Customers call fenvix-run explicitly; no hook catches the test step (app `infra/github-app/lib/runner/files/fenvix-job-started:4` only touches a marker; the onboarding setup PR changes only the job's `runs-on`, `github-app/src/onboarding/workflow.ts:4-8`). So after onboarding, a Node customer's `npm test` runs on our machine WITHOUT the engine unless their workflow calls `fenvix-run node` itself.

# Node customers on our machines: vitest, jest, node:test, mocha through `fenvix-run node` (spec 2026-11-23)

Both merged.
- **Engine:** `claude/release-1` = **f67be4a**.
- **App:** PR #24 (https://github.com/Mircoguidetti/fenvix-app/pull/24) merged into `main` = **ccc1170**.
  - A push to `main` is a production deploy (`deploy.yml`), which conflicts with the spec's rule 5. The founder
    confirmed it in this session (option B: PR, checks green, merge, deploy).
  - The PR's first `Tests` run failed in the deploy steps:
    - migration 0018 had no detection probe in `deploy/lib/migrate.mjs`;
    - the migration tests hard-coded 0017 as the newest migration.
  - Fixed in a14bb91 (see the test-change lines below). `Tests` was then green, and the PR was merged.
- **Deploy run 45198260216: success** (14:49 to 14:56 UTC, 2026-11-23):
  - migrations: `applying 0018_node_test_mocha_runners.sql`, step green;
  - CDK: `fenvix-prod-github-app` `UPDATE_COMPLETE` (new Image Builder component, recipe and pipeline; Lambdas
    updated);
  - smoke: `/healthz` 200, `/v1/me` 401, both expected.
- **NOT VERIFIED: runner image 1.0.45688296.** Its build was only started ("30-45 minutes; jobs wait for it"). That
  build is where the new `install.sh` (pinned Node 22.23.5) and `bootstrap.sh install` at f67be4a (wheel + detjs)
  really run on AWS. This session has no AWS access, so its result is not known here. Check it in EC2 Image Builder
  (pipeline `fenvix-prod-runner`).

## Changes to tests, CI steps or thresholds (listed first, rule 3)

- APP DEPLOY TESTS (a14bb91): `deploy/test/database.test.mjs` derives the newest migration (`LAST`) and the numbers
  of the migrations a test writes itself (`nextVersion`) from the files. Before, it hard-coded 0017, 0018 and 0019.
  - "0014-0017 run" became "every migration after 0013".
  - The local-Supabase test title says "the newest migration".
  - No assertion removed or weakened.
- APP DEPLOY TEST, new case: `deploy/test/pipeline-2.test.mjs`, 0018 cut before its last statement stops the deploy
  and records nothing.
- APP DEPLOY CODE: a probe for 0018 in `deploy/lib/migrate.mjs` `PROBES`, like 0011-0017. It needs the
  `ci_projects` and `gh_repositories` runner CHECKs to accept mocha.
- Local result: deploy `npm test` against a scratch Postgres 16 gives 86 pass, 0 fail, 1 skipped (local Supabase
  only). PR #24 `Tests` on a14bb91: success.

- APP TEST PIN (07dfac3): `infra/github-app/test/cache.test.ts:21` pins `engineCliCommit`. It changed from `a20b93d...` to
  `f67be4a...`, together with `cdk.json` and `lib/cache/PROVENANCE.md`, as PROVENANCE.md prescribes. The test's real
  check is unchanged: the vendored `cache_service.py` SHA-256 `2b93cd9a...` stays. `git show f67be4a:python/detpy/cache_service.py
  | sha256sum` gives the same `2b93cd9a...`.

- CI CHANGE (0598ac6): `.github/workflows/release-1.yml`, job `python`: added `actions/setup-node@v4` with
  `{node-version: "24"}` before the test step (same form as the node jobs). Reason: the shared test
  `tests/test_runner_node.py` runs detjs, which needs Node >= 22, and the python job had no setup-node. Founder decision
  D1 = A, 2026-11-23. No step, matrix, threshold or selection was removed or relaxed.

- NEW `tests/test_runner_node.py` (engine), added to `release/python-tests.txt` as `shared`. No existing test is
  changed, skipped or weakened. The CI workflow is not changed.
- App `supabase/tests/run-local.sh` (`npm run test:rls`): migrates the new `0018` twice (like 0014-0017) and runs a
  NEW check, `supabase/tests/runners-check.sql`. Nothing is removed.
- App unit tests: new cases in `github-app/tests/unit/{workflow,detect,results}.test.ts`. Existing cases are unchanged.
  In `workflow.test.ts`, one existing `it(...)` title changed from "knows vitest, jest, go test and npm test" to
  "knows vitest, jest, node --test, mocha, go test and npm test", and its case list gained 7 rows.
- AC2 wording deviation in the new test, stated here and not hidden: the verifier never says NOT PROVEN for the
  entropy fixture. It says DIVERGED with reason `entropy`. See AC2.

## Commits

- engine `claude/node-runner`: 7efa219 (wrapper, bootstrap, tests), ebaa2e7 (reason keys for the App),
  d287443 + 962acfb (gstack /review fixes). Head **962acfb**. Not merged: see "Merge rule".
- app `claude/node-runner`: **47b5308**, pushed. `engineCliCommit` is not changed yet: it waits for the engine merge commit.

## What was built

Engine (only `runner/`, `tests/test_runner_node.py`, `tests/fixtures/runner-node/`, `release/python-tests.txt`):
- `runner/bootstrap.sh`: in development mode, checks `node` >= 22 on PATH before the wheel build. It fails with "node
  not found on PATH: Node 22 or newer is needed ..." or "node v20.18.0 on PATH (...) is too old: detjs needs Node 22
  or newer". It builds detjs with `node node/scripts/build.js` and installs bin/, src/, package.json and the addon
  (the engine artifact's layout) into `$FENVIX_HOME/detjs`, symlinked as `$FENVIX_HOME/bin/detjs`, which is on the
  job PATH (`.env`). **The pinned-artifact mode (`FENVIX_ENGINE_URL`) is unchanged and installs no detjs: Node jobs
  need the development mode** (out of scope).
- `runner/fenvix-run node --project DIR [--runner vitest|jest|node-test|mocha] [--key] [--out] [--cache] [--detjs] -- <runner args>`:
  - The runner comes from package.json (devDependencies vitest/jest/mocha; `scripts.test` running `node --test`).
    None found or more than one: exit 2, naming what was found.
  - Runs `detjs <runner> --det --det-cache=$FENVIX_CACHE_ROOT/<key>-node<major>`, plus receipts, cache summary,
    outcomes and trace into `--out`.
  - Writes `summary.json` and the step summary.
  - Re-runs each failure alone without the cache, and never lowers the exit code.
- `fenvix-run verify --summary S` on a Node summary: a fresh run without the cache at the cache run's epoch, with
  `--det-trace`. Then `detjs verify T1 T2 --json`, mapped to `verify_status` / `verify_exit` / `verify_counts` in
  summary.json and to `verify.json`. Exit = detjs verify's code (0/1/3; 3 is said in the step summary).
- Python path unchanged (AC4).

Single-test re-run commands, exactly as recorded by the tests:
| runner | command |
|---|---|
| vitest | `detjs vitest --det --det-epoch=2026-11-23T00:00:00Z run fail.test.js -t '^fails on demand$'` |
| jest | `detjs jest --det --det-epoch=2026-11-23T00:00:00Z fail.test.js -t '^fails on demand$'` |
| node:test | `detjs node-test --det --det-epoch=2026-11-23T00:00:00Z --test-name-pattern '^fails on demand$' fail.test.js` |
| mocha | `detjs mocha --det --det-epoch=2026-11-23T00:00:00Z fail.test.js --grep '^fail fails on demand$'` |
In each case the test failed again alone, so it was not reported flaky, and the exit code stayed 1.

App (commit 47b5308, branch claude/node-runner): `install.sh` installs Node 22.23.5 as root before bootstrap, from the official
`node-v22.23.5-linux-x64.tar.gz`. The sha256 `c541181...a1a1` is pinned in the script AND must appear in the
release's `SHASUMS256.txt`. Also in that commit:
- migration `0018_node_test_mocha_runners.sql`;
- `TestRunner`/`RUNNERS`/`LANGUAGE_OF` in `detect.ts`, and `workflow.ts`;
- the OpenAPI enum, with `src/api/schema.d.ts` (`npm run api:generate`) and `github-app/src/api/openapi.gen.ts`
  (`node src/api/gen-openapi.ts`) regenerated;
- onboarding detects `node --test` and `mocha` (`npx vitest` and `npx jest` were already matched by `\bvitest\b` /
  `\bjest\b`; now tested);
- `summary.ts` drops `runner_args` before storing, as it drops `pytest_args`: a Node field mapping;
- 4 Node fixtures.
`src/data/types.ts` re-exports `TestRunner` from the generated schema, so it follows the regeneration without an edit.

## Acceptance criteria

The environment for every command below:
- this container, prepared by `FENVIX_HOME=$S/fhome runner/bootstrap.sh install` → exit 0 (1m23s; "node: v22.23.5",
  "engine: detjs fenvix 0.1.0 -> $S/fhome/bin/detjs"; run again after the review fixes → exit 0);
- then `export FENVIX_HOME=$S/fhome PATH=$S/fhome/bin:$PATH` with `FENVIX_DETJS` unset, so the tests use the
  installed detjs;
- `$S` is the session scratchpad.

**AC1: met (wrong reuse 0 for all four).** `python3 -m pytest -q -p no:randomly tests/test_runner_node.py` →
`47 passed in 24.84s` (head 962acfb).

| runner | cold (exit, tests, reused) | warm (exit, reused with receipt) | `fenvix-run verify` (exit, status, wrong) |
|---|---|---|---|
| vitest | 0, 5, 0 | 0, 5 of 5 | **1**, diverged, wrong 0: `entropy.test.js::reads OS entropy` (skipped, reused) diverged "beyond-trace" |
| jest | 0, 5, 0 | 0, 5 of 5 | 0, identical, wrong 0 |
| node:test | 0, 4, 0 | 0, 4 of 4 | **1**, diverged, wrong 0: `fail.test.js::fails on demand`, `pass.test.js::sorts` diverged "beyond-trace" |
| mocha | 0, 5, 0 | 0, 5 of 5 | 0, identical, wrong 0 |

The test asserts `wrong_reuse == 0`, and that every reused test is a row of the verify report
(`reused_checked == reused`, so the check is not vacuous). It does not assert verify exit 0. For vitest and node:test,
`fenvix-run verify` is red on a plain green suite, because of engine findings E-1 and E-2 below. **A Node customer
running the verify step on vitest or node:test would see it fail today.**

**AC2: met for exit codes. The NOT PROVEN wording is not met as written.**
- `FENVIX_FIXTURE_FAIL=1` → exit **1**, the test in `failed` (all four).
- Neither variable → exit **0**, `status failed=0 not_proven=0` (all four).
- No runner in package.json → exit **2** ("no test runner found in .../package.json: none of vitest, jest, mocha in
  devDependencies and no `node --test` in scripts.test ..."). Two runners → exit 2 ("more than one test runner found
  ...: vitest, jest").
- `FENVIX_FIXTURE_ENTROPY=1`, plain run: exit **0**, prints `detjs: status: failed=0 not_proven=0 passed=5
  skipped=0`, and the test passes (all four). **A test that reads real OS entropy is green on a single run.**
- `FENVIX_FIXTURE_ENTROPY=1`, then `fenvix-run verify`: exit **1** (all four). The entropy test is named
  **DIVERGED, reason `entropy`**, not NOT PROVEN.
  - `crates/detpy-core/src/verify.rs` gives NotProven only when the runs' fingerprints agree. Real entropy makes them
    differ.
  - The test therefore asserts exit 1, the test named as NOT PROVEN or as DIVERGED(entropy), and status
    `not_proven|diverged`.
  - Whether the verifier should call this NOT PROVEN is an engine decision (out of scope: `crates/` not touched).

**AC3: met.**
- Each Node fixture loads, and `stackFromSummary` gives `{language: "node", testRunner}` with vitest, jest,
  `node:test` and mocha respectively (`github-app/tests/unit/detect.test.ts`).
- `cd github-app && npm run test:unit` → `tests 151, pass 151, fail 0`; `npx tsc --noEmit` → no output, exit 0.
- Root: `npm run typecheck` → exit 0 ("api: src/api/schema.d.ts matches openapi/fenvix-api.yaml"); `npm run
  test:unit` → `tests 73, pass 73`.
- `infra/github-app`: `npm test` → `tests 142, pass 142` (shellcheck is not installed here, so install.sh got
  `bash -n` only).
- Migration: Docker is installed, but `test:rls` only needs a scratch database, so it was run for real against a
  throwaway Postgres 16 (`initdb` in /tmp, port 55432):
  `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/fenvix_scratch npm run test:rls` → API, CI, CI EXPLORE,
  GH, WARM RLS OK and `RUNNERS CHECK OK`, "done: ...".
- Without 0018 (0001-0017 only), `runners-check.sql` fails: `ERROR: ci_projects.test_runner: runner list is CHECK
  ((test_runner = ANY (ARRAY['pytest'::text, 'vitest'::text, 'jest'::text, 'go test'::text])))`. That also shows the
  constraint name `ci_projects_test_runner_check` is the one the migration replaces.
- install.sh's `install_node`, extracted to a scratch prefix:
  - pinned hash → `node-v22.23.5-linux-x64.tar.gz: OK`, exit 0, `v22.23.5`; run again → "already in", exit 0;
  - wrong hash → `ERROR: SHASUMS256.txt of v22.23.5 does not list sha256 0000... for node-v22.23.5-linux-x64.tar.gz`,
    exit 1, nothing extracted.

**AC4: met (Python path unchanged).**
- `$S/pyvenv/bin/python -m pytest -q -p no:randomly tests/test_runner_wrapper.py` (venv with the bootstrap-built
  wheel) → `1 passed, 1 skipped`, on the branch AND on the trunk e733895 (worktree). The skip is the file's existing
  `_STARTUP_RULE_NOT_PORTED` marker.
- `tests/test_python_tests_classified.py` → passes.
- `runner/local-demo.sh` (pygments, `FENVIX_HOME=$S/fhome`):
  - branch: job 1 exit 0, job 2 exit 0, verify exit 0, rc 0 (4m03s);
  - trunk e733895: the same, exit 0 / 0 / 0, rc 0;
  - both: "tests 5313, reused with proof 0" then "tests 5314, reused with proof 0". Reuse 0 on job 2 is the same
    before and after, so it was not introduced here.
- `git diff e733895 -- runner/fenvix-run` removes only:
  - the `write_step_summary` signature (new `runner_label="pytest"` default);
  - the "Test time spent" line (now None-safe; always a number on the Python path);
  - the "(pytest)" label line;
  - `--project default="."`, which stays "." for the Python run and Python verify.

**AC5: met on the App branch, not yet on `main`.** `engineCliCommit` = **f67be4a** (the engine merge commit) in App
commit 07dfac3. `git merge-base --is-ancestor 81f838c6 f67be4a` → exit 0; `git merge-base --is-ancestor 75816a73
f67be4a` → exit 0. It reaches `main` only with the App merge, which deploys (see "Merge rule").

## Summary fields with no Node source (written as null)

- `test_seconds_run`: null only when detjs writes no `ran_files`. The source is cache-summary.json
  `ran_files[*].duration` per file: the trace has no per-test duration (the spec said "trace durations").
  `test_seconds_saved` = receipts' `duration` of reused file/unit rows.
- `not_proven`, `status`: null when the trace header has no status (the run is then exit 1, see the review fixes).
- `engine_version`: null if `detjs --version` fails.
- `runtime.parts` / `runtime.runner_version`: null when detjs wrote no cache summary or trace header.
- `cache_check_seconds` / `cache_record_seconds` / `epoch_ns`: null when absent from the cache summary.
- `shared_cache`: always null (`fenvix-run node` supports a local cache only; a URL is exit 2).
- `reused_from_shared_cache`: 0 (no shared cache).
- Renamed or new: `runner_args` (for `pytest_args`); `language`, `test_runner`, `engine: "detjs"`, `trace_file`,
  `cache_summary_file`, `reused_files`, `reruns`, `reason_texts`, `detjs_args`; after verify: `verify_status`,
  `verify_exit`, `verify_counts`.
- `not_cached` / `not_reused_reasons` keys are detjs reason texts turned into slugs ("os-entropy",
  "outcome-failed"), because the App refuses keys outside `[A-Za-z0-9_.:-]{1,40}`. The full text is in
  `reason_texts`.

## E4: Node summaries rendered by the App (render.ts / summary.ts)

Fixtures: `github-app/tests/fixtures/runner/node-*.summary.json`, from real `fenvix-run node` runs. Paths were
rewritten to `/home/fenvix/...`. Each scenario is rendered in `results.test.ts`.

Findings:
- **Wrong render 1** (not a field mapping, so not fixed): the check-run text says "Engine: detpy 0.1.0" for every
  Node summary (`render.ts` hard-codes "detpy").
- **Wrong render 2** (not a field mapping, so not fixed): a verify failure renders ✅. The App has no verify fields,
  and `conclusionOf` returns success when the summary's exit is 0, even if GitHub's job conclusion is failure.
- **Fixed, a Node field mapping:** before ebaa2e7 the App REFUSED the node:test and mocha summaries ("summary.not_cached
  has an unexpected key"), so nothing rendered. Keys are now slugs.

vitest, warm, 5 reused:
```
### ✅ fenvix · 5 of 5 tests skipped with proof · under 0.1 min (0.3 s) saved · no failures
| Tests | **5** | Tests run | 0 | Skipped with proof | **5** ([receipts](...)) | Minutes saved | **under 0.1 min (0.3 s)** (100.0% of test time) | Failures | 0 | Flaky, reproducible | 0 |
check run text: "Test time: run under 0.1 min (0.0 s), skipped with proof under 0.1 min (0.3 s). Engine: detpy 0.1.0."
```
jest, cold, "0 reused":
```
### ✅ fenvix · 0 of 5 tests skipped with proof · under 0.1 min (0.0 s) saved · no failures
| Tests | **5** | Tests run | 5 | Skipped with proof | **0** (...) | Minutes saved | under 0.1 min (0.0 s) (0.0%) | Failures | 0 | Flaky | 0 |
check run text: "Why the other tests ran (an input changed, or no entry yet): new 3. ... Engine: detpy 0.1.0."
```
node:test, failed run (warm cache, FAIL=1):
```
### ❌ fenvix · 3 of 4 tests skipped with proof · under 0.1 min (0.0 s) saved · 1 failed
| Tests | **4** | Tests run | 1 | Skipped with proof | **3** | Minutes saved | under 0.1 min (0.0 s) (57.8% of test time) | Failures | 1 | Flaky | 0 |
### Failures
- `fail.test.js::fails on demand`
check run text: "Why the other tests ran: env 1. Not cacheable: outcome-failed 2. ... Engine: detpy 0.1.0."
```
mocha, verify failure (ENTROPY=1; run exit 0; verify_status diverged, verify_exit 1):
```
### ✅ fenvix · 0 of 5 tests skipped with proof · under 0.1 min (0.0 s) saved · no failures      <- WRONG: verify failed
| Tests | **5** | Tests run | 5 | Skipped with proof | **0** | ... | Failures | 0 | Flaky | 0 |
check run text: "Why the other tests ran: new 1. Not cacheable: os-entropy 6. ... Engine: detpy 0.1.0."
```
The full renders, with links, are in `$S/e4-renders.md`.

## Engine findings (in `node/src` / `crates/`, which this task may not touch; reported only)

- **E-1 vitest:** a reused **skipped** test is stored with an empty fingerprint, while a fresh run gives one. So
  `detjs verify` says "diverged (beyond-trace)" with the same outcome, and verify exits 1 on a green suite. Cold vs
  fresh: identical.
- **E-2 node:test:**
  - A skipped test (`{ skip: ... }`) is missing from the trace and from the outcomes. The suite reports 4 tests, not 5.
  - With `--det-cache`, fs events from `<node>` (readdir of `<tmp>/rd-...`) are attributed to the last test of each
    file, so a cache run never matches a run without the cache (verify "diverged: fs").
- **E-3 mocha:** any glob spec (in `.mocharc.json` `spec`, or `'*.test.js'` on the command line) means NOTHING is
  reused ("not cached: reads a clock Level 0 does not virtualize: fs.stat atimeMs"). Explicit file lists reuse. The
  fixture lists its files explicitly, but most customer mocha setups use globs.
- **E-4 verifier:** real OS entropy is DIVERGED(entropy), never NOT PROVEN (see AC2). A plain run that reads entropy
  exits 0.
- **E-5 npm 10.9.9:** `npm install` of vitest 5.1.0 fails with "Cannot read properties of null (reading 'edgesOut')"
  (peer dependencies). The vitest fixture uses `.npmrc legacy-peer-deps=true` and pins `vite` 8.3.8 explicitly.
  Customers on npm 10 may hit this outside fenvix.

## gstack /review (merge rule)

`/review` of `claude/node-runner` vs `claude/release-1`:
- specialists testing, maintainability, security, performance and simplification, plus the red team and the Claude
  adversarial pass;
- Codex not installed, so outside coverage was unavailable;
- 2 fix cycles, converged.

Highest-severity findings:
- red team CRITICAL: "green without proof when outcomes or trace status are missing". **Fixed** (d287443/962acfb,
  tested with a stub detjs).
- red team CRITICAL / adversarial High: "bootstrap install now dies without Node 22 on Python-only hosts".
  **Kept**: the spec requires bootstrap to fail without node >= 22. Founder decision D2 = A, 2026-11-23: keep
  bootstrap failing without Node >= 22.
- re-review High: the first fix's prefix match dropped `--det-cache-verify` / `--det-cache-max-age` /
  `--det-cache-real-clock`, and left `--det-trace FILE`'s value as a runner positional. **Fixed** (exact names,
  value form; tested).
- Final re-review of 962acfb: no material findings.

Unresolved, low: malformed numeric values in detjs output give a traceback, which is exit 1, never green. A suite
whose tests are all skipped exits 0 (as pytest does). The flaky re-run drops values of options given as
`--opt value` unless known (fails safe: reported as failure, not flaky). Unchanged on both points: simplification
advice was not applied.

## CI (merge rule: no new failing job versus the trunk)

Branch: release-1.yml LIGHT, run **45177168265** (workflow_dispatch on claude/node-runner, head 962acfb).
Trunk: LIGHT run **45165824244** (push, head e733895 = this branch's base).

| job | trunk 45165824244 | branch 45177168265 |
|---|---|---|
| build | success | success |
| smoke (python), smoke (node) | success, success | success, success |
| attacks (py 3.13, node 24) | failure | failure |
| node (24, shard 0/4) | failure | failure |
| node (24, shard 1/4), (2/4), (3/4) | success, success, cancelled | cancelled, success, cancelled |
| python (3.13, shard 0/4) | **failure**: `test_packaging.py::test_gate_runs_on_pull_requests_and_trunk_only_and_cancels_only_superseded_pr_runs` (parallel-node.yml has a `push:` trigger), and 2 in `test_py_cache.py` | cancelled (fail-fast) |
| python (3.13, shard 1/4), (2/4) | success, success | success, cancelled |
| python (3.13, shard 3/4) | success | **failure**: the same `test_packaging.py::test_gate_runs_...` (`AssertionError: parallel-node.yml`); `1 failed, 164 passed, 4 skipped` |

- **Job level: no new failing test.** 3 failing jobs on each side. The one that moved is the trunk's own
  `test_packaging` failure: `release/shard.py` splits by size, and adding `tests/test_runner_node.py` to the shared
  list moved `test_packaging.py` from shard 0 to shard 3. `python3 release/shard.py 4 <i> ... --only shared` places
  it in shard 0 on the trunk and shard 3 on the branch. This branch does not touch `.github/workflows/`.
- **Not shown by CI:** `tests/test_runner_node.py` falls in branch shard 0/4. Fail-fast cancelled that shard at
  12:59:56, after 11 min, when shard 3/4 failed. Its log artifact `python-3.13-s0` is 189 bytes (the pytest output
  goes through `tee | tail` and was cut off).
  - So CI gives no result for the new shared test.
  - Whether ubuntu-latest's `node` is >= 22 in the Python job is not known. The test fails, never skips, without
    Node 22 and detjs. It uses `dist/detjs.linux-x64.node` via DETJS_NATIVE.
  - Locally (bootstrap-installed detjs, Node 22.23.5): 47 passed.
- Run 45175492965 (head ebaa2e7, before the review fixes) was cancelled by me after the fixes; its results are not used.

## Merge rule

**Engine: merged.** `git merge --no-ff claude/node-runner` into `claude/release-1` gives **f67be4a**, pushed
(`e733895..f67be4a`). It merged branch head d9792c5; code 962acfb plus the CI change 0598ac6.
`git merge-base --is-ancestor 81f838c6 f67be4a` → exit 0; `... 75816a73 f67be4a` → exit 0.

The gate is founder decision D1 = A (2026-11-23). Each of its three conditions holds:
1. Python shard 0/4 run locally under Node 24.22.3, `pytest $(python3 release/shard.py 4 0 tests 'test_*.py'
   '**/test_*.py' '*_test.py' '**/*_test.py' --only shared release/python-tests.txt)`, with the CI deselect and the
   bootstrap-built wheel:
   - **branch:** `2 failed, 231 passed, 20 skipped in 613.73s`;
   - **trunk e733895:** `3 failed, 210 passed, 15 skipped in 632.43s`;
   - The branch's 2 failures, `test_py_cache.py::test_the_virtual_clocks_own_probe_of_threads_is_not_the_tests_read`
     and `::test_g2214_a_test_that_crashes_its_worker_is_a_record_of_the_merged_trace`, also fail on the trunk. The
     trunk's third, `test_packaging.py::test_gate_runs_...`, is in shard 3 on the branch.
   - `tests/test_runner_node.py` is in branch shard 0 and passed. Alone under Node 24: `47 passed in 30.83s`, which
     also covers `npm ci` of the fixtures with Node 24's npm.
2. LIGHT CI **45182639646** on 0598ac6 (with setup-node 24) fails attacks, node (24, shard 0/4) and python (3.13,
   shard 3/4). Shard 3/4's only failure is `test_packaging.py::test_gate_runs_...` (`1 failed, 164 passed, 4
   skipped`): the trunk's failure, moved by re-sharding. Trunk run 45165824244 fails the same three jobs (python as
   shard 0/4). No new failing job. Python shard 0/4 was again cancelled by fail-fast.
3. /review of the CI change (adversarial pass): no blocking finding. It checked that the `release-1.yml` assertions
   of `test_packaging.py` still hold and that the CI-style detjs lookup passes (47 passed).

**App: not merged into `main`, and nothing deployed.** A push to `main` is a deploy (`deploy.yml`, above).
- Branch `claude/node-runner` head **07dfac3**: 47b5308 plus `engineCliCommit = f67be4a`.
- Tests on 07dfac3:
  - `infra/github-app`: `npm test` → `tests 142, pass 142`;
  - `github-app`: `npm run test:unit` → `tests 151, pass 151`, `tsc --noEmit` exit 0;
  - root: `npm run typecheck` exit 0, `npm run test:unit` → `pass 73, fail 0`.
- The App's CI (`test.yml`) runs on pull requests and inside deploys only. No pull request was opened, so it has
  not run on this branch.

## To unblock

1. Done: push access to fenvix-app was granted, and the App branch is pushed.
2. Done: the engine is merged (f67be4a), and `engineCliCommit` is set on the App branch (07dfac3).
3. **Founder decision:** merge the App into `main`. That push starts `deploy.yml`: migration 0018, the CDK stacks,
   and a runner image with Node 22.23.5 and engine f67be4a. Optionally, first open a pull request so `test.yml` runs
   in the App's own CI.
4. Decide E-1/E-2/E-4 (engine): until then, `fenvix-run verify` is red on green vitest and node:test suites.

Not checked: the AWS image (nothing deployed), real customer repositories, shellcheck on install.sh, and
`release/engine/install.sh` / the pinned-artifact mode for Node.
