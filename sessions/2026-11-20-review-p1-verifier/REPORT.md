FIX 12

# Review P1: F-01 deterministic execution, F-02 flaky test → defect (engine), F-03 verifier, F-18 CLI

Reviewer session 2026-11-20. Independent review: no product code changed. Engine under review: `claude/release-1` @ 71f8081
(merge of PR #4). The implementing session's report (`claude/verifier-cli:sessions/2026-11-20-verifier-cli/REPORT.md`)
had not appeared when this review finished (`git ls-tree -r origin/claude/verifier-cli` lists no such file), so none of
its claims could be checked.

Labels: MEASURED (with the command), ESTIMATED, DECLARED, UNKNOWN.

## How the engine was built and run

As `.github/workflows/release-1.yml` does:

```
pip install "maturin>=1.5,<2" && maturin build --release --compatibility linux -o dist      # dist/detpy-0.1.0-cp39-abi3-linux_x86_64.whl
cargo build -p detpy-node --release && cp target/release/libdetpy_node.so dist/detjs.linux-x64.node
cp dist/detjs.linux-x64.node node/ && (cd node && npm ci)
pip install --no-deps dist/detpy-*.whl          # in three venvs: CPython 3.12.3, 3.13.18, 3.14.6 (+ pytest 9.2.0, xdist 3.8.0)
cargo build -p fenvix-go --release && (cd go && CGO_ENABLED=1 go build -o ../dist/fenvix-go ./cmd/fenvix-go)   # for G-0041 only
```

`fenvix` reaches detjs through `FENVIX_HOME=<dir>` with `<dir>/node -> node/`.

Versions run: CPython 3.12.3, 3.13.18, 3.14.6; Node 22.23.5, 24.22.3; Vitest 5.1.0, Jest 30, node:test; Go 1.24.7
(fenvix-go). **Not run**: Node 26 (downloading the Node 26 binary was refused in this environment: UNKNOWN); the real
public projects of `harness/` (cloning worked; installing and running them was refused in this environment: UNKNOWN).
All results come from small projects written for this review.

Failing tests (all fail on 71f8081):

- `tests/test_review_p1_verifier.py`: 7 tests. MEASURED: `python -m pytest -q -p no:randomly
  tests/test_review_p1_verifier.py` → 3.12: `7 failed`, 3.13: `7 failed`, 3.14: `7 failed` (final version).
- `node/test/review-p1-verifier.test.js`: 4 tests. MEASURED: `FENVIX_PYTHON=<venv python> node --test
  --test-concurrency=1 test/review-p1-verifier.test.js` → Node 22: `# pass 0 # fail 4`; Node 24: `# pass 0 # fail 4`.

## Per row

### F-01 deterministic execution: FIX

Tried: the same suite twice (or 8 times) under `fenvix pytest --det` / `fenvix vitest|jest|node-test --det` with
identical inputs, comparing the values each test printed; Python under `TZ=Asia/Tokyo LANG=de_DE.UTF-8`; Node under
the same; multiprocessing (fork server) on 3.14; threads.

Works (MEASURED, 3.12/3.13/3.14): virtual `time.*` incl. `CLOCK_MONOTONIC_RAW`, `CLOCK_BOOTTIME`, `thread_time`,
`process_time`; `random.Random()` instances; `uuid1`; file mtimes; host name and CPU count; Python TZ and locale are
pinned (`time.strftime('%z')` → `+0000` and `locale.getlocale()` → `('C','UTF-8')` under `TZ=Asia/Tokyo
LANG=de_DE.UTF-8`).

Leaks (MEASURED): Python: PID, `tempfile` names, `/dev/urandom` read as a file, `/proc/uptime`, thread interleaving
(findings 3, 4). Node: `process.uptime`, `performance.timeOrigin`, `performance.mark`, `crypto.randomFill` (async),
`crypto.randomInt` (callback), `vm` contexts, `worker_threads`, child processes, `/dev/urandom`, `process.pid`,
WebCrypto keys, concurrent I/O completion order (findings 1, 2); Node time zone and locale are not pinned (finding 7).

Confidence that the row gives no wrong result: **low**. Basis: 3 Python versions × 2 runs × 14 probe tests, 8 runs ×
2 flip tests; Node 22 and 24 × Vitest/Jest/node:test × 2 runs × 5–19 probe tests; 6 runs of an I/O race. 8 identical
`--det` runs gave 2–3 different results (finding 4).

### F-02 flaky test → defect (engine): FIX

Tried: `fenvix repro` on an order-dependent victim (polluter in another file) and a seed-dependent test on 3.12 and
3.14: both REPRODUCED 10/10 with one fingerprint, correct cause (polluter named; seed 5), `rerun` command reproduces
(`pytest --det --det-order=.../order.txt` → `1 failed, 1 passed`), `fenvix replay` → `REPRODUCED 3/3`, exit 0;
`fenvix explore --budget 2 --max-seeds 12` found both and wrote bundles (3.13, with numpy installed). Then failures
whose cause is outside the process, replay from another directory, Node runners.

Wrong results: a cause that is not the cause (finding 5); a replay that says "fixed" when it ran nothing (finding 9);
nothing at all for Node (finding 6, G-0448 open).

Confidence that the row gives no wrong result: **low** for Python outside the order/seed classes, **none** for Node
(the commands do not exist). Basis: 5 repro runs, 3 replay runs, 2 explore runs on Python 3.12/3.13/3.14; 4 Node runner
names tried.

### F-03 verifier: FIX

Tried: `fenvix verify` on the pairs/sets of traces above (Python and Node, and fenvix-go), with `--show-stable` and
`--json`; differing TZ/locale/env inputs on Python and Node.

Works (MEASURED): differing run inputs are named first (Node `tz:` / `locale:` / `env:`; Python env); a test that
starts a `threading.Thread` the normal way, a child via `subprocess`, or an event loop that waits on I/O is never
reported identical; numpy projects are no longer falsely divergent (G-0179: a numpy test pair → `IDENTICAL: all 5
tests`).

Wrong results: "identical" for runs whose observed values differ: Node (findings 1, 2) — the verdict line itself reads
`verdict: IDENTICAL: all 19 tests ran with the same inputs and observed the same events`, exit 0 — and Python
(findings 3, 4); "IDENTICAL ... same inputs" for traces with no inputs (finding 8).

Confidence that the row gives no wrong result: **low**. Basis: about 30 distinct probe tests, 2–6 runs each, on 3
Python and 2 Node versions; 16 of 19 Node probes and 7 of 14 Python probes differed while reported identical.

### F-18 CLI: FIX

Tried: `fenvix --version`, `pytest`, `vitest|jest|node-test` (with `--det` added), `verify` (missing file, one
trace), `repro` (unknown id, broken file, Node runners, `node-test`/`mocha`), `explore` (broken suite, missing path,
missing interpreter), `replay` (bundle elsewhere), detjs missing.

Works (MEASURED): one command for Python and Node runs; failing suites exit non-zero through `exec`; `fenvix verify`
exit 2 on a missing trace; `fenvix repro` exit 1 on an unknown id; detjs missing → clear message, exit 127.

Wrong results: `fenvix explore` exit 0 with "0 flaky failing tests" for a suite that cannot run (finding 10); unclear
errors (finding 12). Confidence that the row never exits 0 on failure: **low** (explore does). Basis: ~15 invocations.

## Gaps

| gap | status | evidence |
|---|---|---|
| G-0139 (Node TZ, verify identical) | verifier part FIXED (TZ, locale and env are run inputs and named; regression test `node/test/verifier-inputs.test.js`, not run against the old commit); control part OPEN: TZ/locale not pinned under `--det` | finding 7 |
| G-0180 (Python thread race "covered") | OPEN for `_thread.start_new_thread` and for pools whose threads were started before the test; fixed for `threading.Thread.start` inside the test (`tests/test_verifier_truth.py::test_uncontrolled_sources_are_never_identical` passes and covers only that path) | finding 3 |
| G-0041 (Go identical fingerprints for differing inputs) | OPEN (out of go-live scope) | finding 8 |
| G-0054 (JVM identical while interleaving differs) | OPEN (out of go-live scope). READ: `jvm/rt/.../Lifecycle.java:45 metaJson` writes no `inputs` and the agent writes no `uncontrolled.*` event; same verifier path as finding 8. Not run on a JVM | finding 8 |
| G-0448 (Node repro) | OPEN | finding 6 |
| Same family, Node: G-0124, G-0125 (child), G-0132, G-0133, G-0134 (random), G-0135, G-0136, G-0137 (time), G-0150 (I/O order), G-0152 (workers) | OPEN: each still reported identical | findings 1, 2 |
| G-0126 (Node env not recorded) | PARTLY FIXED: env values are run inputs, but `VITEST_*`, `JEST_WORKER*`, `DETJS_*` are left out (`node/src/session.js:178`); a test reading `VITEST_PROBE=1` vs `2` is reported identical | finding 1 |
| G-0140 (Node locale) | as G-0139: recorded and named, not pinned | finding 7 |
| G-0514, G-0515, G-0519 (Python env, locale, TZ) | FIXED as far as tested (pinned TZ/locale; env reads are events and every variable is a run input) | F-01 above |
| G-0179 (numpy false divergence) | FIXED as far as tested (one numpy project, 2 runs, 3.13) | F-03 above |
| G-0178 (repro names an unrelated event) | numpy case not re-run; a new instance of the same class | finding 5 |
| G-0177 | not re-run: UNKNOWN | |
| G-0168 (first run after checkout) | serial case fixed by the PR; parallel case: the PR's own regression test fails | finding 11 |

## Findings (most severe first)

### 1. F-03/F-01 Node: `verify` says IDENTICAL (exit 0) for runs whose observed values differ

Same suite, same inputs, run twice under `fenvix vitest run` (Node 22.23.5 and 24.22.3), each test appending its value
to a file:

```
differing values: uptime timeOrigin mark pid osuptime cpu rfill rint vm worker child devu envv subtle kp file
verdict: IDENTICAL: all 19 tests ran with the same inputs and observed the same events
run inputs: identical in every run
covered by Level 0: 19  not covered: 0  missing: 0  outcome-unstable: 0
vrc=0
```

(`envv`: `VITEST_PROBE=1` vs `2`, an excluded prefix; `file`: a file outside the project, `A` vs `B`.) Jest and
node:test, Node 22: `jest differing: uptime rfill vm worker child` / `verdict: IDENTICAL: all 5 tests`; same for
node-test. Node never marks a test that used a worker, a child process, a vm context or async crypto as uncontrolled
(the Python side does, `python/detpy/uncontrolled.py`; there is no Node equivalent). Test:
`node/test/review-p1-verifier.test.js` "F-03: no test whose observed value differs ..." (Node 24: 11 of 11 probes
listed as differing yet identical).

### 2. F-03 Node: concurrent I/O completion order differs in every run, `verify` says identical (G-0150)

`fenvix vitest run t/race.test.js` × 6 (8 concurrent `fs.promises.readFile`): 6 different orders (`01346275`,
`01346725`, `01347625`, `01362574`, `01462375`, `03164725`), `fenvix verify r1..r6` → `verdict: IDENTICAL: all 1
tests`. Test: "F-03: a concurrent fs.readFile completion order ...".

### 3. F-03 Python: thread races still reported identical (G-0180 open)

`tests/test_threads3.py` (two threads from `_thread.start_new_thread`; four tasks on a `ThreadPoolExecutor` whose
threads were started at import), 3 runs on 3.13: `RAWRACE 82e979b6 / 3fb97eae / 1ca6f42d`, `POOLRACE 123b0e4b /
eb5ee8cb / 266d409c`; `fenvix verify r1 r2 r3` → `covered by Level 0: 2 not covered: 0`, `STABLE` both, exit 0. Same
on 3.12 and 3.14. Only `threading.Thread.start` during the test is marked; a pool created by a fixture or at import
(the common shape of servers and executors in suites) is not. Tests: `test_f03_a_test_that_uses_threads_is_never_reported_identical`
(deterministic), `test_f03_no_test_whose_value_differs_is_reported_identical`.

### 4. F-01/F-03 Python: the PID, tempfile names, `/dev/urandom`, `/proc/uptime` and files outside the project leak; results flip between identical `--det` runs

Two runs of `tests/test_leaks.py`, 3.12/3.13/3.14: `PID 624` vs other, `TMP tmp5y6106xa` vs other, `DEVU 3989cf0a` vs
other, `UPT 291.15` vs other; `fenvix verify` → `STABLE` for each, `run inputs: identical`. A file outside the project
read by the test (`A` vs `B`): `STABLE`. Eight identical runs of
`assert os.getpid() % 2 == 0` and `assert open('/dev/urandom','rb').read(1)[0] < 128` under `--det`: MEASURED 3.13
`{'1 failed, 1 passed', '2 failed', '2 passed'}`, 3.12 `{'1 failed, 1 passed', '2 passed'}`, 3.14 three outcomes. The
verifier then names `outcome-only` (honest), but F-01's promise (same result every run) does not hold. Tests:
`test_f01_det_result_does_not_depend_on_the_pid_or_os_entropy`, `test_f03_no_test_whose_value_differs_is_reported_identical`.

### 5. F-02 `fenvix repro` declares a polluter that is not the cause

`tests/test_flaky_leak.py::test_devurandom` (fails when `/dev/urandom`'s first byte ≥ 128; no other test touches
anything), 3.13:

```
status:  NOT REPRODUCIBLE under fenvix: failed 6/10 replays, identical fingerprint: False
cause:   test order: it fails when run after tests/test_flaky_leak.py::test_tempname (state left behind by that test)
rerun:   pytest --det --det-seed=5 --det-order=.../order.txt
```

bundle: `kind: order`, `polluters: [test_tempname]`. Deterministic version (external counter: every other run of the
test fails): `cause: test order: it fails when run after tests/test_a.py::test_noop (state left behind by that test)`
on 3.12, 3.13 and 3.14. The cause line is printed even when the status says the defect is not reproducible, and the
`rerun` command is built on it. Test: `test_f02_repro_does_not_name_a_polluter_that_is_not_the_cause`.

### 6. F-02 Node: no `repro`, `explore` or `replay` (G-0448 open)

```
fenvix repro "t/tz.test.js::local hour" --runner vitest   → exit 2: repro / explore / replay are not available for vitest in this version ... the vitest adapter is not built yet
fenvix explore --budget 1 --runner jest                   → exit 2 (same, jest)
fenvix repro x --runner node-test                          → exit 1: unknown runner 'node-test' (known: pytest, ..., vitest, jest, playwright)
fenvix repro x --runner mocha                              → exit 1: unknown runner 'mocha'
node node/bin/detjs.js repro                               → usage: detjs vitest|jest|... verify ... (no repro)
```

Without `--runner`, a Vitest id is refused: `'t/tz.test.js::local hour' could be a test of pytest, vitest, jest`.
Test: "F-02: fenvix repro works for a Vitest, Jest and node:test test".

### 7. F-01 Node: time zone and locale are recorded but not controlled (G-0139/G-0140 control part)

`new Date(0).getHours() === 0` and `(1234.5).toLocaleString() === '1,234.5'` under `fenvix vitest run`: default
environment `Tests 2 passed`; `TZ=Asia/Tokyo LC_ALL=de_DE.UTF-8` → `Tests 2 failed`, exit 1. The verifier names it
(`tz: "UTC offset=0 TZ=<unset> (not pinned)" vs "Asia/Tokyo offset=-540 ..."`), so the verifier part of G-0139 is
fixed; but F-01 says the time zone and locale are controlled under `--det`, and on Node they are not (Python pins them).
Test: "F-01: --det pins the time zone and the locale".

### 8. F-03: traces without run inputs are "IDENTICAL ... ran with the same inputs" (G-0041, G-0054 open)

fenvix-go, Go 1.24.7, one test writing `time.Unix(0,0).Local()` and `$FOO`: default → `1970-01-01 00:00:00 +0000 UTC`;
`TZ=Asia/Tokyo FOO=bar` → `1970-01-01 09:00:00 +0900 JST bar`. `fenvix verify a.jsonl b.jsonl`:

```
verdict: IDENTICAL: all 1 tests ran with the same inputs and observed the same events
run inputs: NOT RECORDED in every trace (time zone, locale, environment, seed, ... cannot be compared; ...)
rc=0
```

The verdict line contradicts the line below it, and the exit code is 0. fenvix-go and the JVM agent write no
`meta.inputs` (`jvm/rt/src/main/java/dev/fenvix/rt/Lifecycle.java:45`). Go and JVM are out of go-live scope; the
false sentence is printed by the in-scope `fenvix verify`. Test: `test_f03_traces_without_run_inputs_are_not_called_identical`.

### 9. F-02 `fenvix replay` outside the project root reports the defect as possibly fixed

Bundle of a REPRODUCED victim (`fenvix replay <bundle>` from the project → `REPRODUCED: failed 3/3`). From an empty
directory or from the project's `tests/`:

```
fenvix replay: tests/test_b.py::test_victim: NOT REPRODUCED: failed 0/2 runs, identical fingerprint: False, same fingerprint as the bundle: False
  the defect no longer fails the same way: fixed, or it depends on something the bundle does not hold ...
exit 1
```

No test was collected; the command should say so (exit 2), not suggest a fix. From `/` it ran pytest over the whole
filesystem (still running after 120 s, stopped). `repro.replay` uses `Path.cwd()` (`python/detpy/repro.py:343`).
Test: `test_f02_replay_outside_the_project_is_an_error_not_a_fix`.

### 10. F-18 `fenvix explore` exits 0 with "0 flaky failing tests" when the suite cannot run

```
tests/test_broken.py: "def test_ok(:"
fenvix explore --budget 0.3 --max-seeds 3   → fenvix explore: 3 seeds in 3.54 s; 0 flaky failing tests (0 always failing, not flaky); 0 replay bundles ...   rc=0
fenvix explore ... -- tests/nope.py          → ... 0 flaky failing tests ...   rc=0
```

A nightly exploration that ran no test reports a clean night. `cmd_explore` always returns 0
(`python/detpy/fenvix.py:494`). Test: `test_f18_explore_does_not_exit_0_when_the_suite_cannot_run`.

### 11. F-01 G-0168: the PR's own gate test fails: the first `-n` run is "cold", every test divergent

`python -m pytest tests/test_verifier_truth.py` → `1 failed, 18 passed` (3.13); `test_parallel_trace_records_inputs`
fails on 3.12, 3.13 and 3.14: `input_differences: [{'name': 'bytecode', 'value_a': 'precompiled', ...}]`. By hand
(3.13): serial run, then `-n 2` twice:

```
verify ser par:  bytecode: "precompiled" vs "precompiled; test modules rewritten from source in this run (cold rewrite cache: 12)"   covered 0, not covered 5
verify par par2: bytecode: "precompiled; ... (cold rewrite cache: 12)" vs "precompiled"
```

The verifier is truthful about it (the runs did differ), but the prewarm of PR #4 does not reach xdist workers, so a
serial-vs-parallel comparison and the first parallel run after any serial run are always fully divergent, and the CI
python job (which runs `tests/`) should be red on this test. Not a "same" lie; listed because it is a gate test of
this row that fails.

### 12. F-18 unclear errors

- `fenvix repro tests/test_broken.py::test_ok` (file with a syntax error) → `not collected: no test has this id. Use an
  id as the runner prints it ...`, exit 1: the collection error is hidden.
- `fenvix explore --python /nonexistent/python` → a Python traceback ending `FileNotFoundError: [Errno 2] No such file
  or directory: '/nonexistent/python'`, exit 1.

Also observed, not counted: a test that starts four processes through the 3.14 fork server is reported `[io]
uncontrolled.io @ <event loop>` (truthfully not identical, but the named first event is the event loop, not the
children: no `uncontrolled.child` event for `multiprocessing` fork-server/spawn starts).
