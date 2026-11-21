MERGE OK: F-01 no, F-02 yes, F-03 no. 23 wrong IDENTICAL results in 16 channels (V1-V16), each with a failing test.
Explore also has one wrong exit 0 (E1).

# Review R-055: full review of Block 1 (Verifier), PR #12 (claude/verifier-cli @ 688e4fe, code 2023045)

This is an independent reviewer session from 2026-11-21. Branch `claude/review-verifier-r055` was cut from 688e4fe and
has one commit. That commit adds this report, `tests/test_review_r055_verifier.py`, `node/test/review-r055.test.js`
and a new section at the end of `docs/VERIFY-INPUTS.md`. No product code was changed. Every number is MEASURED (the
command is named) unless it is marked otherwise.

## How it was built and run

- Wheel from 688e4fe: `maturin build --release --compatibility linux` gave `fenvix-0.1.0-cp312-abi3-linux_x86_64.whl`.
  It was installed with pytest and pytest-xdist in a fresh CPython 3.13.18 venv, and `_core` was copied into
  `python/detpy`, as the CI `python` job does. Node addon: `cargo build -p detpy-node --release`, copied to
  `node/detjs.linux-x64.node`, then `npm ci` (Node 22.23.5).
- Only CPython 3.13 and Node 22 were run here. The full suites were not run, as instructed.
- Baseline (MEASURED): `pytest -n 8 tests/test_verify_inputs_attacks.py` gave **27 passed**.
  `pytest tests/test_review_r051_verifier.py tests/test_review_r054_verifier.py` gave **7 passed** (R1-R4 and N1-N3
  hold). `node --test test/verify-inputs-attacks.test.js test/verifier-inputs.test.js` gave **pass 35, fail 0**. Every
  channel that 688e4fe lists and tests holds. The defects below are channels the list misses, or listed channels
  whose rule does not hold.

## The failing tests

```bash
python -m pytest -q -p no:randomly -n 4 tests/test_review_r055_verifier.py
```
Result: `19 failed in ~15 s`. Each verify case fails with
`AssertionError: <case>: IDENTICAL (exit 0) although the test observed [<a>, <b>]`, and the explore case fails with
`explore exit 0 although 3 of 4 seeds crashed with no test result`.

```bash
cd node && node --test --test-concurrency=4 test/review-r055.test.js
```
Result: `# pass 0  # fail 8`. Each case fails with `<case>: IDENTICAL although the test observed [<a>,<b>]`.

Each verify case runs one project twice under `pytest --det` (or `detjs node-test --det`) and changes only one channel
between the two runs. The test writes the value it observed to a file. The case asserts two things: the two values
differ, so the attack worked, and `fenvix verify` (Node: `native.verify`) does not report IDENTICAL. The harness is
the same as in `tests/test_verify_inputs_attacks.py`.

## Defects, ranked (wrong IDENTICAL first, the most common in real suites first)

Every V row is a wrong IDENTICAL, exit 0: the verdict is `IDENTICAL: all 1 tests ran with the same inputs and observed
the same events`, while the test saw two different values. This is the worst class of defect under promise 1.

| # | channel | Python case → observed values | Node case → observed values | cause (from the code) |
|---|---|---|---|---|
| V3 | **A file read outside any test**: module scope of a test file, `conftest.py` at import, a project data file at import (fixtures loaded at import, `.env` or config files, generated data) | `V3-file-at-module-scope` `'v0'`/`'v1'`; `V3-file-in-conftest-import` `'v0'`/`'v1'`; `V3-project-file-at-module-scope` `'v0'`/`'v1'` | `file read at module scope` `"v0"`/`"v1"`; `project file read at module scope` same | File reads are events only while a test runs. Files have nothing like `env_read_outside_tests`. This is the same class as R-054 N1/N2, which was fixed only for env. |
| V5 | **Installed dependencies changed** (site-packages, node_modules) between the two runs | `V5-installed-dependency-changed` `'v0'`/`'v1'` | `a dependency in node_modules changes` `"v0"`/`"v1"` | No run input covers the installed packages (Python's `run_inputs` has runtime, runner, env… but no lockfile or installed-distribution digest). The `replay` text itself names "dependencies changed" as a cause, and verify cannot see it. |
| V4 | **The code under test changed**: an uncommitted edit in a git checkout (same HEAD) | `V4-test-code-changed-dirty-tree` `'v0'`/`'v1'` | not run (same cause, ESTIMATED) | The header has no source digest. A committed change moves the git-HEAD epoch, so the clock input differs (ESTIMATED from `epoch_source: git HEAD commit time`). A dirty tree does not move it. |
| V1 | **A CI-volatile variable the test reads** (`TMPDIR`, `PWD`, `GITHUB_WORKSPACE`, `RUNNER_TEMP`, `GITHUB_EVENT_PATH`… all of `VOLATILE_KEPT`) | `V1-volatile-env-TMPDIR` `…/ta`/`…/tb` (`GITHUB_WORKSPACE` `/a`/`/b` also measured) | `volatile TMPDIR through process.env` | Design A makes these never inputs, and their reads record no value. `docs/VERIFY-INPUTS.md` does not list this as a gap. The invariant at the top of that page ("IDENTICAL only if the test observed the same value") is false for these variables by design. Fix direction: a read of a KEPT variable in a test marks the test as not provable (or records the value), instead of passing silently. |
| V2 | **A proxy variable read while the network is closed** (`HTTPS_PROXY` & co.) | `V2-proxy-env-closed-network` `http://a:1`/`http://b:2` | `proxy variable while the network is closed` | `run_inputs` skips `PROXY_ENV` because "children get the discard port". The test process itself keeps the real value and reads it. |
| V6 | **File metadata**: existence, mtime | `V6-file-exists` `True`/`False`; `V6-file-mtime` `1000.0`/`1001.0` | `fs.existsSync` `true`/`false` (Node `statSync().mtimeMs` is recorded and passes) | `os.stat`, `os.path.exists` and `fs.existsSync` produce no event. |
| V9 | **A unix socket to another process's server**. The doc table says it is marked `uncontrolled.net`. | `V9-unix-socket` `b'v0'`/`b'v1'` | passes | Python: a listed rule that does not hold. |
| V8 | **UDP to localhost** | `V8-udp-localhost` `b'v0'`/`b'v1'` | `udp to localhost` `"v0"`/`"v1"` | Neither marked nor recorded. Only TCP connect is covered. |
| V16 | **`process.loadEnvFile('.env')`** (C++ reads the file and sets process.env at module scope) | n/a | `process.loadEnvFile (.env read in C++)` `"v0"`/`"v1"` | The env inputs are taken before the file is loaded. The read of `.env` is no fs event. |
| V7 | **A file read by C code** (sqlite3 database outside the project) | `V7-sqlite-file` `('v0',)`/`('v1',)` | not run | Only Python-level opens are recorded. |
| V15 | **C code that calls `getenv` itself** (listed gap, no test until now) | `V15-native-getenv-in-C` `b'1'`/`b'2'` (a 2-line C library built with `cc`) | not run | Listed gap, confirmed. |
| V10 | **The command line** (listed gap): one runner option differs (`--tb=short`) | `V10-runner-options` `[]`/`['--tb=short']` | passes (`cli_args`) | Listed gap, confirmed. |
| V12 | **A read after the header** (`pytest_sessionfinish`, listed gap) | `V12-pytest_sessionfinish` `'1'`/`'2'` | Node `process.on('exit')` passes | Listed gap, confirmed. Note: the header shows `env:ATK_V` differing, and the verdict is still IDENTICAL. |
| V11 | **`os.environ._data`** | `V11-os.environ._data` `b'1'`/`b'2'` | n/a | Same output shape as V12 ("run inputs: DIFFER … env:ATK_V", then IDENTICAL). It is rare in real code. |
| V13 | **`str` hash without the re-exec** (`--det-no-reexec`, or a machine where the re-exec is not possible) | `V13-hash-without-reexec` two different `hash('abc')` | n/a | Both headers say `hashseed: "<random>"`, which compares equal. A random seed should never compare equal. |
| V14 | **Resource usage** (`resource.getrusage().ru_maxrss`) | `V14-rusage` `43076`/`42996` | Node `memoryUsage`/`cpuUsage` are controlled and pass | Not controlled and not observed. It is rare in assertions. |

Counted: 16 channels, 23 failing cases. Python has 17 verify cases (V1-V15, where V3 has 3 cases and V6 has 2) plus
the explore case E1. Node has 8.

### Other defects

| # | promise | defect | evidence |
|---|---|---|---|
| E1 | 4 (exit code vs what is printed), and the nightly purpose | **`fenvix explore` reports a crashing suite as clean.** A test calls `os._exit(1)` when it runs after another test (an order-dependent crash). Plain pytest in the fixed order passes. | `fenvix explore --budget 1 --max-seeds 4` → `seeds_log`: seed 1 `tests: 3, exit 0`; seeds 2, 3, 4 `tests: 0, exit 1`. It prints `4 seeds …; 0 flaky failing tests (0 always failing, not flaky); 0 replay bundles` and exits **0**. With `os._exit(0)`, 4 of 6 seeds ran 0 tests and the result was the same. Test `test_r055_explore_does_not_report_clean_when_seeds_crashed`. Exploration is the feature that "finds hidden bugs before production", and this is the hidden bug it should find. |
| D1 | 3 (lesser: no false DIVERGENT on unchanged runs) | **Unchanged runs of a test that uses a thread pool or a child process are headlined `DIVERGENT`.** | `ThreadPoolExecutor` summing `range(10)`, two unchanged runs: `verdict: DIVERGENT: 1 of 1 tests are not identical`, exit 1. The detail line is honest (`NOT-COVERED … [thread]`). `subprocess.run(['echo','x'])`: same. This follows the documented rule ("never identical"), but the headline word should be NOT PROVEN, not DIVERGENT. Not added as a test: it is by design. |
| D2 | 3 (lesser) | **Two `--det` runs started at the same time on one machine get different `tmp_path`** (`/tmp/fenvix-det/…` and `/tmp/fenvix-det.1/…`, lock-based). | Measured in the parallel driver. Sequential runs give the same path. Low. Not added as a test. |
| D3 | 2 (honest, not false) | `fenvix repro` on the crashing test of E1: `not reproduced: it passed in all 2 configuration(s) in which it ran …; 4 more did not run it and are not counted`, exit 1. | It makes no false claim, but a crash under 4 configurations is the defect. It should count as a failure ("the process died while running it"). |

### F-02 checks that hold

- R-054 N3 (`xfail(run=False)`): `NOT RUN`, exit 2. Replay with another fingerprint: `NOT REPRODUCED … it still fails, but not as recorded`, exit 1. Measured by `test_review_r054_verifier.py`, which passes.
- The R-051 R1-R4 tests pass.
- No REPRODUCED or "fixed" claim was false in any case I ran.

## MERGE OK

- **F-01: no.** F-01 covers files, network and environment. Files read outside tests (V3), UDP and unix sockets
  (V8, V9) and the volatile and proxy variables (V1, V2) leave what the test sees uncontrolled, and the run says
  nothing about it.
- **F-02: yes.** repro and replay made no false claim in the checks above (D3 is honest). E1 belongs to explore. If
  explore counts as part of F-02, then E1 blocks F-02 too, because it is an exit 0 for a suite that crashes under
  3 of 4 seeds.
- **F-03: no.** V1-V16 are wrong IDENTICAL verdicts. V3 (files at import), V5 (dependencies) and V4 (code) are common
  in real suites. Fix direction (ESTIMATED effort: medium):
  1. Record file reads outside tests the way env reads are recorded (`files_read_outside_tests` in the header, with
     path and digest; verify counts them for every test).
  2. Add run inputs for the code (a digest of the tracked and dirty files, or `git status`) and for the installed
     packages (a digest of the installed distributions / the `node_modules` lock).
  3. A test that reads a volatile or proxy variable is NOT PROVEN, not IDENTICAL.
  4. Mark UDP and unix sockets like TCP.
  5. Make `"<random>"` never compare equal.

## Channels added to docs/VERIFY-INPUTS.md

The new section is "Channels added by review R-055", rows V1-V16:

- volatile env (V1)
- proxy env (V2)
- files read outside tests (V3)
- code under test (V4)
- installed dependencies (V5)
- file metadata (V6)
- C-level file reads (V7)
- UDP (V8)
- unix socket, Python (V9)
- command line (V10)
- `os.environ._data` (V11)
- reads after the header (V12)
- hash without re-exec (V13)
- resource usage (V14)
- C `getenv` (V15)
- `process.loadEnvFile` (V16)

The same section lists about 30 channels I checked that hold, so that nobody re-checks them.

## Listed gaps checked

| listed gap | result |
|---|---|
| C `getenv` | Confirmed: V15 is a wrong IDENTICAL, now with a test. |
| `pytest_sessionfinish` | Confirmed: V12. |
| argv | Confirmed on Python: V10. On Node, `process.argv` did not change with my extra runner argument, so it could not be measured. |
| Deno/Bun | Not testable here (not installed). |
| Node runner-config dependencies | Not run. |
| Python live endpoint "marked, not compared" | Holds for TCP. It does not hold for unix sockets (V9) or UDP (V8). |

## Process note

Like R-051 and R-054, this report goes where the prompt says: `claude/review-verifier-r055` of fenvix-engine-cli. The
brain's `CLAUDE.md` says that reports go to `sessions/` on brain `main`. The coordinator may want to align the two.
