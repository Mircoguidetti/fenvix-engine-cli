MERGE OK: F-01 no, F-02 no, F-03 no. Main blocker: d917b43 gives a wrong IDENTICAL (N1). F-02 is held by N3, a wrong
"REPRODUCED" in the safe direction, which is a one-line fix.

# Review R-054: round 2 on PR #12 (claude/verifier-cli @ 4a30ac4, code 94f41d5) before merge

Reviewer session 2026-11-21. Branch `claude/review-verifier-r054`, cut from 4a30ac4. One commit adds this report and
`tests/test_review_r054_verifier.py`. No product code was changed. Every number is MEASURED (the command is named)
unless it is marked otherwise.

## How it was built and run

- Wheel from 4a30ac4: `maturin build --release --compatibility linux`. It was installed with pytest and pytest-xdist
  in a fresh CPython 3.13.18 venv, and `_core` was copied into `python/detpy`. Node addon: `cargo build -p detpy-node
  --release`, copied to `node/detjs.linux-x64.node`, then `npm ci` (Node 22.23.5).
- Only CPython 3.13 and Node 22 were run here. Full suites were not run, as instructed.

## Earlier tests and the session's tests

| suite | result |
|---|---|
| `tests/test_review_r051_verifier.py` (R1-R4; identical to `claude/review-verifier-r051`, checked with `diff`) + `test_review_r050_verifier.py` (V10) + `test_review_p1_findings.py` | **9 passed** (32.7 s). R4 ran and was not skipped (`-rs`: 4 passed, 0 skipped) |
| `tests/test_fenvix_cli.py` (includes the new explore and NOT REPRODUCIBLE render tests) | **29 passed** (171 s, `-n 8`) |
| `cd node && node --test test/verifier-inputs.test.js` (includes d917b43's new test) | **pass 12, fail 1**. The failing test is `runs differing only in env are divergent and name it`: `stable 2 !== 0`. d917b43 made this older test stale (see New problems 3) |

## Verdict per item

### 1. R-051 follow-up (740856c)

| item | verdict | evidence |
|---|---|---|
| R1 `"inputs": {}` | **FIXED** | `test_r1` passes. `verify.rs:289` treats an empty map as not recorded. From reading the code, an `inputs` value that is not an object (`[]`, `null`) also gives `None` (NOT PROVEN). |
| R2 `urandom` vs `entropy` | **FIXED** | `test_r2` passes. The key is aliased in `run_inputs` (`verify.rs:295`). No producer writes both keys (grep over python/, node/src, go/, jvm/), so a collision cannot hide a difference today. |
| R3 replay of a target that no longer runs | **PARTLY** | `@pytest.mark.skip`: NOT RUN, exit 2 (`test_r3` passes). `pytest.skip()` in the body: `NOT RUN: the test did not run … (the test was skipped…)`, exit 2. **N3:** `@pytest.mark.xfail(run=False)` (a quarantine whose body never runs, here a body that would `raise SystemExit`): `REPRODUCED: failed 2/2 runs, identical fingerprint: True, same fingerprint as the bundle: False`, **exit 0**. Cause: `crates/detpy-core/src/repro.rs:26` `is_fail` is `contains("failed")`, and `"xfailed"` contains it. A fixture error (`RuntimeError('db down')`, so the body never runs) also gives `REPRODUCED … same fingerprint as the bundle: False`, exit 0: `cmd_replay` ignores `matches_bundle`, although the `check:` line promises "exit 0 when every run fails with the bundle's fingerprint". Test `test_n3_…` |
| R4 TLS over `wrap_bio` | **FIXED** | `test_r4` passes (it ran, it was not skipped). My own case: two TLS-over-memory-BIO connections in one frame, with TLS started first on the socket assigned second. Plain run, record and replay all gave `1 passed`. |
| no `replay:` / `rerun:` on NOT REPRODUCIBLE | **FIXED** | End to end: an external counter that fails 1 run in 3, `fenvix repro … --seeds 3 --confirm 6` → `status: NOT REPRODUCIBLE under fenvix: failed 2/6 replays`. Only the `check:` line is printed, with no `replay:` or `rerun:`. |
| entropy hint names the right option | **FIXED** | Python, `--det --det-entropy=observe` twice: `hint [entropy]: … Python controls it by default under --det (--det-entropy=observe leaves it real); Node controls crypto.randomBytes & co. with --det-urandom`, exit 1. Node's option is `--det-urandom` (`node/src/seeds.js:211`). |

### 2. d917b43: Node header declares `env_reads_recorded`: **NOT FIXED (regression: a wrong IDENTICAL)**

`node/src/controls.js:79`: `if (STATE.testId === null || …) return;`. A read made outside a test body is no event,
but the header now says that every read is recorded. A variable that the test's code read and that differs between the
two runs then gives IDENTICAL.

My cases (`tests/test_review_r054_verifier.py::test_n1`). EXAM_V is `1` in run a and `2` in run b, and each test uses
the value it read:

| runner | read at | verify on 4a30ac4 |
|---|---|---|
| node-test, vitest | module scope of the test file (`const V = process.env.EXAM_V`) | **stable (IDENTICAL)** |
| node-test, vitest | `before` / `beforeAll` hook | **stable (IDENTICAL)** |
| node-test, vitest | a dependency in node_modules that reads it at import (`exports.V = process.env.EXAM_V`) | **stable (IDENTICAL)** |
| node-test, vitest | inside the test body, directly or through a dependency function | input-differs (correct) |

These are regressions from d917b43. I took the vitest module-scope traces and removed only `meta.env_reads_recorded`
from both headers: `verdict: INPUT DIFFERS: EXAM_V: 1 of 1 tests read it with a different value`, exit 3. The
unchanged traces give `verdict: IDENTICAL: all 1 tests ran with the same inputs and observed the same events`, exit 0.
Module-scope configuration (`const API = process.env.API_URL`) is the most common way a test file reads its
environment.

**N2 (pre-existing, Python, same class):** a module-level `V = os.environ.get("EXAM_V")` in a test file also gives
`IDENTICAL`, exit 0. The reason is `envobs.py:_note_value`, which returns while `STATE.nodeid is None`. A
session-scoped fixture that reads it is recorded (INPUT DIFFERS). Test `test_n2_…`

Fix direction (ESTIMATED effort: small): reads made while no test runs (import, collection, hooks) should not be
dropped. Record their names in the header (for example `env_read_outside_tests: [names]`). The verifier then counts
those names as read by every test, the same way `read.all` works today but limited to those names. This keeps the
sudo USER/LOGNAME case identical, because no code reads those variables, and it brings back input-differs for module
scope, hooks and imports.

### 3. 94f41d5: explore with collection errors: **FIXED**

- V10 (R-050) passes. The session's test (a finding next to a module that does not import → exit 0, with the error
  named) passes.
- Each of my broken-suite variants gives exit 2, so none reports a clean suite with exit 0 (`fenvix explore
  --budget 0.3 --max-seeds 2`, one good test next to the broken part):
  SyntaxError module → exit 2 "does not collect cleanly … finding nothing does not mean the suite is clean";
  `os._exit(0)` at import → exit 2 "the suite cannot run: collection failed";
  `raise SystemExit(0)` at import → exit 2 "the suite did not run";
  `conftest.py` in a subdirectory with a missing import → exit 2 "does not collect cleanly";
  `addopts = -x` with a broken module → exit 2 "the suite did not run".
- Exit 0 with collection errors needs `failing_tests` to be non-empty. Those failing tests are real findings, and the
  errors are printed to stderr.

### 4. Exam changes, `claude/exam` e4b96b6 (`exam/rows_f.py`)

All three changes still fail a false 'identical'.

| check | change | does a false 'identical' still fail? | caveat |
|---|---|---|---|
| F-03.random | values equal (entropy controlled) → pass only if verify is identical | **yes** (values differ → requires not identical + entropy named; values equal → IDENTICAL is the correct verdict; `None` values are excluded) | The check no longer exercises the *observed* path at all. Suggest a second probe with `--det-entropy=observe` that must be DIVERGENT, naming entropy. I measured that path: DIVERGENT, exit 1, `hint [entropy]`. |
| F-03.thread | race not exercised → pass only if verify rc != 0 | **yes** (IDENTICAL is rc 0 → fail) | It also passes on rc **2**: `fenvix verify` exits 2 for `trace not found` and for `invalid trace: missing header` (measured). If every run crashed before writing a trace, the outcomes are equal and the check passes on the crash. The traces are also not deleted before each run. Suggest requiring rc == 1 and reason `thread` in `--json`. On the real probe, 3 runs gave `DIVERGENT … reasons: thread=1`, exit 1, so the right reason is available. |
| F-03.node-thread | worker values equal → IDENTICAL, or a refusal whose report mentions "thread" | **yes** (values differ → requires not identical; equal values → IDENTICAL is correct) | The substring test is broad but safe: events serialise their thread as `"t"`, so "thread" comes only from reasons and descriptions (checked: an env input-differs report has no "thread"). |

## Failing tests added (all FAIL on 4a30ac4, CPython 3.13.18, Node 22.23.5)

`python -m pytest -q -p no:randomly tests/test_review_r054_verifier.py` → `3 failed in 10.74s`:

- `test_n1_node_env_read_outside_the_test_body_is_never_identical` (F-01/F-03, d917b43): all 6 cases are `stable`.
  It needs the addon and `node/node_modules`, and skips otherwise.
- `test_n2_python_module_level_env_read_is_never_identical` (F-03, pre-existing): IDENTICAL, exit 0.
- `test_n3_replay_of_an_xfail_run_false_target_is_not_reproduced` (F-02, R3 class): REPRODUCED, exit 0.

## MERGE OK

- **F-01: no.** d917b43 was made for exam check F-01.hostname.pinned.node, and it turns module-scope, hook and
  import-time environment reads into a wrong IDENTICAL on Node (N1). R4 and the rest of the F-01 work hold. Fix N1, or
  revert d917b43 and solve the USER/LOGNAME case another way (for example, pin or treat as volatile the variables
  that `sudo` changes).
- **F-02: no, by the rule "a wrong result blocks".** N3 prints "REPRODUCED: failed 2/2 runs" for a body that never
  ran (`xfail(run=False)`), exit 0. Its direction is safe: it never says "fixed" or "clean". If the coordinator blocks
  only false-clean results, F-02 can merge: 94f41d5 and the rest of the R3 work are correct. The fix is one line:
  `is_fail` should not match `xfailed`, and an xfail that did not run should be `not-run`.
- **F-03: no.** The verifier's verdict is the product for F-03, and N1 is a false IDENTICAL, the one result that
  must never pass. N2 has the same cause on Python and existed before this PR. It should be fixed in the same change.

## New problems

1. N1, N2, N3 above. Only N1 and N2 are false IDENTICAL results.
2. `fenvix replay` exits 0 with `same fingerprint as the bundle: False` (fixture-error case). That contradicts its own
   `check:` line ("exit 0 when every run fails with the bundle's fingerprint"). It is a wrong result in the safe
   direction (it claims the defect is present), and it existed before this PR.
3. `node/test/verifier-inputs.test.js` "runs differing only in env are divergent and name it" now fails: no test reads
   `NODE_TRUTH_FLAG`, so after d917b43 both tests are identical, which is correct under design A. The test asserts the
   old behaviour. `release-1.yml:174` runs `test/*.test.js`, so PR #12's Node job is probably red on it (ESTIMATED; I
   did not check GitHub). Update the test so that its body reads the variable, and keep one test where nothing reads
   it.
4. Exam F-03.thread passes on verify exit 2 (crash or missing trace). See item 4.

## Process note

As in R-051, the prompt places this report on `claude/review-verifier-r054` of fenvix-engine-cli. `CLAUDE.md` of
fenvix-brain-cli says that reports go to `sessions/` on brain `main`. I followed the prompt.
