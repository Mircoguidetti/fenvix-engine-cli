PARTIAL

# F-01 / F-02 / F-03 / F-18: deterministic runs, flaky test to reproducible defect, verifier, one `fenvix` command

Branch `claude/verifier-cli` (cut from `claude/release-1`). PR #4 merged (CI green on `1c4aa01`, release-1 run
44781855441, MEASURED). PR #11 (F-18 complete, design A, the exam-round fixes) open into `claude/release-1`; its code head is the commit
before this report.
Every number is labelled MEASURED (from a run named here), ESTIMATED, DECLARED or UNKNOWN.

## Verdict

PARTIAL. All four rows work on real projects. Why not DONE:

- PR #11 is open. It holds F-18 complete, design A for the environment and the CPU count, and the fixes from a
  local run of the frozen exam (`claude/exam` `a6d8824`). It has not been through the CI on its head, the CI exam or
  the reviewer yet.
- Exam checks not passing locally in these rows (see "Exam rows run locally"), each for a reason of this container:
  `cassette-redact` (it resolves a real host: no network here) and `F-01.probe.replay-clients` (its Deno leg: no
  deno installed here; httpx, aiohttp, sendmsg, h2 and Bun pass). `F-01.probe.service-host` needs Docker. The CI
  exam decides these three.
- Reviewer p1-verifier findings #5, #8 and #9 and R-050's V10 are fixed in this push (`f1a12f5`). The reviewer's
  tests (`tests/test_review_p1_findings.py`) and R-050's (`tests/test_review_r050_verifier.py`) are in the branch,
  unchanged, and pass locally:
  - #5: a polluter was named although the replays did not confirm it. Now a cause is claimed only for a reproduced
    bundle; otherwise it is "not established", and the tests it ran with are not named.
  - #8: traces without run inputs were called IDENTICAL. Now they are "NOT PROVEN" (exit 1).
  - #9: replay outside the project root reported the defect as possibly fixed. Now it exits 2 and says the test did
    not run; the bundle records its project root.
  - V10 (#10, the rest): with a broken module next to good ones, explore reported a clean suite. Now it explores the
    tests that collect, then exits 2 naming the collection errors (plain pytest cannot run that suite).

Status by row:

- **F-01, F-03:** design A (founder decision after exam run 44790428974) is in PR #11. Under `--det`:
  - CI-volatile variables are pinned (run and attempt ids, job and runner names, host name) or never inputs (temp
    and workspace paths, per-step files, tokens; `FENVIX_VOLATILE_ENV` adds a project's own).
  - The CPU count is 2 for every Python and Node API that answers it, while the engine's own planning uses the
    machine.
  - A variable a test read with a different value is `INPUT DIFFERS: NAME` (exit 3), not divergent.
- **F-18:** in PR #11:
  - `fenvix --help` names every command on its own line.
  - `replay:` is the failing run as a product command.
  - explore exits 2 when the suite cannot run (reviewer #10).
  - Collection errors and a missing `--python` are clear one-line errors (reviewer #12).
- **G-1523, decided:** OS entropy is CONTROLLED by default under `--det` (`os.urandom`, `os.getrandom`,
  `secrets`, `ssl.RAND_bytes`, `/dev/urandom` reads). `--det-entropy=observe` is the opt-out: entropy is then real,
  each read is an `[entropy]` event, and the verifier reports it with a hint. `--det-urandom` is kept as an alias of
  the default. The reviewer's tests were updated to assert both modes, not weakened:
  `tests/test_review_r023b.py` (getrandom, RAND_bytes: reused by default, not reused under observe) and the
  `urandom` case of `tests/test_verifier_truth.py::test_runs_differing_in_one_source_are_divergent_and_name_it`
  (identical by default, divergent and named under observe).

## Exam rows run locally (MEASURED, frozen exam `claude/exam` `a6d8824`, `exam/run.py --rows F-01,F-02,F-03,F-18`, this container)

First pass on the branch before this round: F-01 17/34, F-02 8/17, F-03 11/18, F-18 5/5 checks passed. On the trunk
without this branch, F-01 passed 3/33. Fixed in this round, each as a class with a regression test:

- **CPU count** (F-01): `os.cpu_count`, `os.process_cpu_count`, `os.sched_getaffinity`, `multiprocessing.cpu_count`
  and Node `os.cpus`/`availableParallelism` answer 2 under `--det`. The engine keeps the real count (`detpy._machine`,
  `volatile.realParallelism()`), and `-n auto` is sized on the real machine
  (`test_cpu_count_is_pinned_and_the_engine_keeps_the_real_one`, `test_n_auto_is_sized_on_the_real_machine_under_det`).
- **Proxy and sudo variables** (F-01/F-03): when the network is closed, `HTTP(S)_PROXY`, `ALL_PROXY` and `NO_PROXY`
  are set by the engine and are never run inputs. `SUDO_USER/UID/GID/COMMAND/HOME` are CI-volatile and kept (Python
  and Node; the volatile cases of `test_ci_volatile_variables_are_pinned_or_never_inputs` and
  `node/test/verifier-inputs.test.js`).
- **OS input text** (F-03): the `os` input named the run's temporary directory (`fenvix-det.1` when another run held
  `fenvix-det`), so two concurrent runs on one machine were INPUT DIFFERS. It now names the control ("temporary
  directory: fresh per run") (`test_two_concurrent_runs_on_one_machine_are_identical`).
- **Timed waits** (F-01): `select.select` with nothing ready, socket operations that time out, and `timeit` now
  advance the virtual clock by their timeout or measured time
  (`test_waits_that_time_out_and_timeit_follow_the_virtual_clock`).
- **Entropy default** (G-1523, above).
- **F-18**: explore exits 2 on a suite that cannot run; repro shows the collection error; a missing `--python` is one
  line.
- **The entropy run input named the device** (F-02, exam `numpy-repro`, interim CI exam run 44891607359): the
  input was `urandom`, so every bundle's provenance of a numpy test said "urandom". It is now `entropy`, the name of
  the option and of the verify reason (Python and Node headers). Verify reading `urandom` in older traces as the
  same input did not hold for the run-input comparison in `57d76c4` (R-051 R2); fixed in the follow-up. `F-02.probe.numpy-repro` and `F-03.probe.numpy` PASS locally after it (MEASURED).
- **A configuration that did not run the target was counted as searched** (F-02, exam `py-autodoc`). Cause
  (MEASURED, the exam's own project venv): two of the project's modules do not import (`requests` is not installed),
  so pytest interrupted every `--det` session with 0 tests run, while `--collect-only` still listed the target.
  repro searched 51 configurations in which the target never ran and reported "passed ... not-found". Fix:
  - a configuration counts as searched only if the target ran in it; if none ran it, the status is `not-run` with
    the runner's error lines, and `fenvix repro` exits 2
  - search, minimisation and replay runs pass `--continue-on-collection-errors`, and the bundle and the printed
    replay command carry it
  - tests: `tests/test_fenvix_cli.py::test_a_module_that_does_not_import_does_not_hide_the_target`,
    `::test_a_target_that_never_ran_is_not_run_not_searched`,
    `::test_a_runner_that_stops_before_any_test_is_not_run_with_its_error`. The reference spec of the Rust port
    (`tests/rust_hotpaths_ref/_ref_repro.py`) follows the same rule, and `tests/test_repro_rust.py` still holds.
  - after the fix, `F-02.py-repro.idoft-py-autodoc` and `F-02.py-replay.idoft-py-autodoc` PASS (MEASURED, frozen exam,
    local): repro exit 0, replay 10/10 failed with one fingerprint.

Targeted rerun after the fixes (MEASURED): PASS for `random.pinned` (Python, Node), `network.pinned` (Python,
Node), `hostname.pinned.python`, and the F-02 mdutils/krllint repro and replay checks. Not re-run locally after
their last fix: the timed-wait and `timeit` checks and `numpy-repro` (the CI exam measures them).

Still failing locally, with owner:

| check | why | owner |
|---|---|---|
| `cassette-redact` | needs the network; this container has none | runs in the CI exam |
| `hostname.pinned.node` (locale), tz/luxon, fake-timers, node clock sources, node vm, timer consistency, mtime node | Node controls | Node session |
| F-02/F-03 Node checks | Node adapters | Node session |

### Checks added to the frozen exam on 2026-11-21 (MEASURED, `claude/exam` `f6bbcdf`, local, merged build)

| check | result | cause / what is missing |
|---|---|---|
| `F-03.probe.realm-failure` | PASS | |
| `F-01.probe.service-host` | not run here | needs Docker (none in this container); the CI exam decides |
| `F-03.probe.multi-project` | FAIL, then PASS after the fix | Vitest test ids carried no project name, so the node and jsdom parts of one file merged into one test (verify saw 1 of 2) |
| `F-01.probe.cassette` | FAIL (Python), then PASS (Python and Node) after the fix | requests keeps the connection alive: test b's request went over the socket test a opened and was recorded under a, so b replayed alone found no recording |
| `F-01.probe.replay-clients` | FAIL (httpx, aiohttp), then httpx and aiohttp PASS after the fix; the check stays FAIL here on its Deno leg (deno not installed) | asyncio's and anyio's TLS run over `SSLContext.wrap_bio`, which the network control did not intercept: the cassette held ciphertext and the random handshake never matched, so replay refused |

Fixed in this round, each as a class with a regression test:

- **Vitest projects** (F-03, `1100f69`, `d74d033`): a test of a named project is `file@@project::name`, the form the
  cache already uses for its keys. The project name is used whenever the project has one, not only when the
  workspace has several: a `--project` filter changes the count, and the ids must not change with it. The cache's
  `testKey` (JS and Rust) and the repro's `fileOfId` accept an id that already carries its project.
  Test: `node/test/projects.test.js` ("both parts are in the trace and each is compared").
- **Connections kept alive across tests** (F-01, `1d6d16b`): the first send of a later test on a kept connection
  continues it under that test (`Cassette::continue_in`). A replayed connection stays open after its last segment
  unless the recording read the server's end of file, and the next request is answered from the running test's
  recording. Cassettes written before this keep their end of file after the last segment. The reference spec of
  the Rust network port follows the same rules. Test:
  `tests/test_network_gaps.py::test_a_connection_kept_alive_across_tests_replays_each_test_alone_and_in_any_order`
  (full run, test b alone, reversed order).
- **TLS over memory BIOs** (F-01, `ca23d6a`): under `--det` record and replay, `SSLContext.sslobject_class` is a
  `DetSSLObject`. It finds the socket it runs over in its caller (asyncio's transport socket, a stream's raw socket,
  a socket local), records the plaintext with the handshake's details, and on replay is the identity over the
  plaintext stream. Test: `tests/test_network_gaps.py::test_tls_over_memory_bios_is_recorded_as_plaintext_and_replayed`
  (asyncio, and the anyio shape used by httpx).

### Follow-up after R-051 (prepared locally on `followup-r051`, pushed after PR #11 merges)

R-051 found four non-blocking defects in `57d76c4`; its tests (`tests/test_review_r051_verifier.py`, unchanged) pass
after these fixes (MEASURED, Python 3.13, local):

- R1 (F-03): traces whose `inputs` object is empty were IDENTICAL (exit 0). An empty `inputs` is now no record of
  the inputs: NOT PROVEN, exit 1.
- R2 (F-03): an older trace's `urandom` input was not the same input as `entropy` when the run inputs were compared
  (the earlier claim in this report did not hold). `run_inputs` now reads `urandom` as `entropy`.
- R3 (F-02): replay of a target that is now skipped said "fixed, or ...". A replay in which the test body did not
  run (skipped, or not collected) exits 2 and says the test did not run.
- R4 (F-01): TLS over memory BIOs was bound to the first socket in the caller. With several sockets there, the
  replay binds to the one whose recording was made above TLS, and the recording binds, once the handshake is done,
  to the socket that sent the ClientHello (its handshake ciphertext is dropped from the recording).
- A NOT REPRODUCIBLE bundle no longer prints `replay:` or `rerun:` lines (no command reproduces it); the `[entropy]`
  hint names `--det-entropy=observe` for Python and `--det-urandom` for Node.

### After PR #11 merged (exam run 44902718930 on `57d76c4`, results `claude/exam` `f303716`)

F-18 5/5, F-01 32/33, F-02 16/17, F-03 15/18 (MEASURED, that run). The five failing checks, each run locally:

| check | cause | status |
|---|---|---|
| `F-01.hostname.pinned.node` | the Node header did not say that the tests' environment reads are recorded, so verify counted every differing variable as read: the second run (under sudo: other `USER`, `LOGNAME`) was INPUT DIFFERS although no test read them | fixed (`d917b43`): the header carries `env_reads_recorded` (not for Bun and Deno, whose own environment APIs are not recorded); PASS locally |
| `F-02.py-explore.idoft-py-autodoc` | V10 (R-050) made explore exit 2 whenever the suite did not collect cleanly, also when it found the flaky test | fixed (`94f41d5`): findings exit 0 with the collection errors named; finding nothing in such a suite exits 2; PASS locally, V10 still passes |
| `F-03.random` | the check expects two `--det` runs reading `os.urandom` to diverge; under the founder's decision OS entropy is controlled by default, so the values are equal and verify is IDENTICAL, which is correct | not an engine defect: a conflict between the frozen check and the decision (the Node check `F-03.node-random` accepts "values equal: controlled") |
| `F-03.thread` | INCONCLUSIVE: the race never happens on this interpreter, with or without `--det` (plain pytest 3/3 passed, `--det` 3/3 passed, CPython 3.13.18, MEASURED); verify reports the test NOT COVERED [thread] as required | harness limit, not an engine defect |
| `F-03.node-thread` | the worker's `Math.random` is controlled (equal values) but every test that starts a worker gets `uncontrolled.thread` (node/src/children.js: worker interleaving is not controlled), so verify never says identical; the check wants identical when the values are equal | open: needs a decision (relax for one worker without shared memory, or keep "never identical") |

### R-054 (round 2 on PR #12, `4a30ac4`): fixed, tests in `tests/test_review_r054_verifier.py` (unchanged)

- N1 (regression from `d917b43`, Node): with `env_reads_recorded` declared, a read made outside a test body (module
  scope, a before/beforeAll hook, a dependency at import) was no event, so a differing variable read there gave
  IDENTICAL. Such reads now go to the header (`env_read_outside_tests`) and verify counts them as read by every test.
  The sudo case stays identical: nobody reads `USER`/`LOGNAME` (`F-01.hostname.pinned.node` PASS locally, MEASURED).
- N2 (Python, same class): a module-level `os.environ` read is listed the same way (reads before the trace opens:
  test modules, conftest, plugins at import; xdist workers send theirs to the controller).
- N3: `is_fail` matched `xfailed`, so an `xfail(run=False)` target replayed as REPRODUCED. An expected failure is no
  failure (core and the reference spec), and a replay of an xfail target is not run (exit 2).
- `fenvix replay` exits 0 only when every run fails with the bundle's fingerprint (its own `check:` line); a failure
  with another fingerprint says so.
- `node/test/verifier-inputs.test.js` "runs differing only in env": its tests now read the variable; the case where
  nothing reads it is the test added in `d917b43`.

### Every input channel of a test (founder decision, `2023045`)

`docs/VERIFY-INPUTS.md` lists every way a Python or Node test can read its environment and inputs (environment
variables through every API and at every point: test body, module scope, conftest and setup files, hooks and fixtures
of every scope, the runner's configuration, dependencies at import and in the test, threads, child processes; files
in and outside the project; time, entropy, host, CPU, time zone, locale; network), the rule verify applies to each,
and one attack test per channel: `tests/test_verify_inputs_attacks.py` (27 cases) and
`node/test/verify-inputs-attacks.test.js` (22 cases). Each changes one channel between two runs and checks that verify
says IDENTICAL only if the test observed the same value. All pass locally (MEASURED, Python 3.13, Node 22).

The attacks found five channels where verify said IDENTICAL although the test observed different values; fixed:
`posix.environ` and ctypes `getenv` (Python), live endpoints the closed network lets through (Python:
`uncontrolled.net` unless the test's own listener), the runner configuration's env reads in the Node main process,
and Node reads of project files. The remaining gaps (C `getenv` in extensions, Python reads after the trace opened,
the Node configuration's dependencies, Deno/Bun untested here, `sys.argv`/cwd on Python) are listed in the document.

### R-055 (full review of `688e4fe`): every defect fixed

R-055 found 26 wrong IDENTICAL verdicts in 16 channels (F-01 no, F-03 no), and E1, D1, D3. Its tests
(`tests/test_review_r055_verifier.py`, 19; `node/test/review-r055.test.js`, 8) are in the branch unchanged, and its
section of `docs/VERIFY-INPUTS.md` is copied in, with the status of each channel. After the fixes (MEASURED, local,
Python 3.13, Node 22): 18 of 19 Python cases and 8 of 8 Node cases pass. The one left, V14 (`getrusage`), fails on its
own precondition here: the two runs' `ru_maxrss` were equal on this machine, so the attack changed nothing the test saw;
the engine records the real counters as an event (my test `test_cpu_time_clocks_are_virtual` shows the divergence).

What changed, as rules (docs/VERIFY-INPUTS.md, "Status of the R-055 channels"):
- reading a CI-volatile kept variable or a closed network's proxy variable: `uncontrolled.env`, never identical (V1, V2)
- files read outside any test: run inputs `file:<path>`; reads after the header: the trace footer (`late`) (V3, V12)
- run inputs `code`, `deps` and `argv` (V4, V5, V10); an input `<random>` never equal (V13)
- `os.stat`/`lstat` and Node `existsSync`/`statSync`/`lstatSync`: events with what the caller asked (V6)
- sqlite database files read like files; ctypes libraries: `uncontrolled.native` (V7, V15)
- UDP and unix-socket live endpoints: `uncontrolled.net` from the frame that used them (V8, V9)
- `os.environ._data`/`posix.environ`: one recording mapping (V11); `process.loadEnvFile` read like a file (V16)
- explore exits 1 when seeds crashed with no result (E1); NOT PROVEN headline for uncontrolled-only differences (D1);
  repro counts a test that kills the process as a failure (D3)

Changed expectations in my own earlier tests, each because a stricter event is now the first difference:
`test_fingerprint.py::test_control_flow_divergence` (the existence check before the clock read),
`::test_outcome_only_divergence` (`fs.stat` or `fs.read`), `test_f01_gaps.py::test_cpu_time_clocks_are_virtual`
(getrusage's real counters are an event). No reviewer's test was changed.

## Local suites before the PR #11 push (MEASURED, this container, editable installs, the code head of this push: the branch merged with release-1 `cec096c`)

- Node 22, 24 and 26: 858/858 each.
- Python 3.12 (full suite): 1096 passed, 94 skipped, 1 xfailed, 0 failed.
- Python 3.13 (full suite): 1099 passed, 1 failed: `test_level0_seeds_fsorder_rust::test_rust_stand_ins_are_faster_than_the_reference`,
  a timing comparison run while the Node suite and a local exam run shared the CPU; it passes alone.
- Python 3.14 (full suite, a local 3.14.6 build without `os.getrandom`): 1092 passed, 5 failed. Four fail on the
  trunk on this machine too: two `test_clock_rust` reference tests and the two
  `test_review_r023b::test_2e_os_getrandom_is_entropy` cases (the probe test calls `os.getrandom`, which this build
  lacks; the CI's 3.14 has it). `test_capture_rust::test_capture_sessions_match_reference` fails only inside the full
  run and passes alone.
- Rust (`cargo test -p detpy-core`): 153 passed.
- This report is a separate `[skip ci]` commit containing only this file.

## F-01 deterministic runs

**True.** Every control has a test that makes two real `pytest --det` runs on a machine that differs in the
controlled source, and checks that the code saw the same values and that `fenvix verify` says IDENTICAL. These run on
CPython 3.12, 3.13 and 3.14 in the release-1 gate (`tests/test_controls_f01.py`):

| control | test |
|---|---|
| clock | `test_clock` |
| randomness | `test_randomness` |
| hash seed | `test_hash_seed` |
| test order | `test_test_order` |
| network | `test_network` |
| fs order | `test_fs_order` |
| time zone | `test_time_zone` (new control: `--det-tz`, default UTC) |
| locale | `test_locale` (new control: `--det-locale`, default C.UTF-8) |
| environment | `test_environment` (observed: every `os.environ` read is an event naming the variable at its site) |
| bytecode | `tests/test_det_stale_bytecode.py` |

Closed in this branch, each with a test in `tests/test_f01_gaps.py` or `tests/test_network_gaps.py`.

Clock:
- the asyncio loop runs on virtual time
- `process_time`, `thread_time`, `os.times` and `getrusage` CPU times are virtual
- files a test writes carry the virtual time of the write
- the header says `sleep=real` when the time control is off

Randomness:
- `uuid1` is deterministic
- numpy is seeded when imported lazily, and unseeded generators get derived seeds
- torch, TensorFlow and Faker are seeded
- seeds share 8 hash seeds (`FENVIX_HASHSEEDS`), so an exploration precompiles at most 8 times

Network:
- a replayed request that differs from the recording is refused, and the run says so
- secret headers are masked in the cassette and in the comparison
- `sendmsg`/`recvmsg` are recorded
- asyncio clients are recorded and replayed
- UDP is recorded and replayed
- TLS replay answers the negotiated version, cipher, ALPN and certificate
- recordings carry a date, and `--det-cassette-max-age` refuses old ones
- children get proxy variables pointing at a closed port
- reverse DNS is guarded
- `fenvix cassette list|rename|drop`

First use (G-0168):
- a first run after a checkout or an edit runs itself again from the rewrite cache before any test, and `.detpy` is
  created before the test process starts, so `id()`-dependent behaviour (the order of a set of plain objects) is the
  same as in every later run. MEASURED: before, the first run's order differed from later runs; after, identical
  over 3 runs, a fresh `.detpy` and 2 edits.
- in a `-n` run the workers cannot run again: cold workers are a run input (`bytecode`), so verify never calls such
  a run identical to a warm one.
- `--det-*` options without `--det` are errors
- `.detpy/.gitignore` is written
- a line appears before the first precompile, and old bytecode caches are evicted
- the runner shells list the `--det` options and name a missing runner or a misspelled option
- `[tool.fenvix]` or `FENVIX_DET=1` turns `--det` on

**Not true / not controlled here.**
- Thread and asyncio scheduling: moved to PY-07. Such tests are marked `uncontrolled.thread` or `uncontrolled.io`
  and are never reported identical.
- Native network clients and children that ignore proxy variables: these need the syscall backend. Such tests are
  marked `uncontrolled.native` or `uncontrolled.child` and are never reported identical.


## F-02 flaky test to reproducible defect (Python, and the CLI shape Node reuses)

**True.**
- `fenvix repro TEST` reruns the test's whole recorded run, minimises the tests it depends on, and confirms with N
  replays that give one fingerprint. It prints the status, the cause (the polluter or the first divergent event),
  the seed, the order, the error, and the `fenvix replay` command.
- It works for pytest and, through the shells (`--runner NAME`), for unittest, Django, nose2, ward, zope.testrunner
  and doctest.
- A failure seen under `-n` is searched in its worker's list (`--plan`).
- `fenvix explore` has `--resume`, `--changed-since` and `--only-unstable`.
- Bundles are self-contained: commit, interpreter, distributions, run inputs, and a relative failure location.
- `replay:` is the failing run itself as a product command (`fenvix pytest --det --det-order=...`): it fails
  (exit 1) when the defect reproduces; `check: fenvix replay BUNDLE` replays it N times.
- Tests: `tests/test_fenvix_cli.py`.

**Block 2 re-measured with the product command** (`fenvix explore --targets FILE`: one seed search of the whole suite shared by the Block 1 targets, as the 364/388 baseline did, then `fenvix repro`'s minimisation, bundle and replays per target; workflow `block2.yml`, tool `fenvix`, 50 seeds, 10 replays per reproduced test). The first attempt ran `fenvix repro` once per target, re-searching the suite for every target: 16 anyio targets did not fit the 5-hour budget (MEASURED, run 44743585438: 5 targets in 2h15m), so it was cancelled. Result (MEASURED, run 44781862684 on `1c4aa01`, `harness/results/block2-fenvix-cli/`):

| repository (Python 3.13, in scope) | targets | reproduced | cause named | replay 10/10, one fingerprint | wall time of the repository (s) |
|---|---:|---:|---:|---:|---:|
| anyio | 16 | 11 (4 not found, 1 not minimised: run budget) | 11 | 11 | 12,446.6 |
| arrow | 2 | 2 | 2 | 2 | 490.1 |
| jsonschema | 2 | 2 | 2 | 2 | 544.3 |
| packaging | 1 | 1 | 1 | 1 | 2,648.8 |
| rich | 5 | 5 | 5 | 5 | 410.6 |
| **total** | **26** | **21** | **21** | **21** | |

Baseline on the same 26 targets (`detpy repro`, standalone): 22/26, all with one fingerprint. The product command
reproduces 21/26: one anyio target fewer, all 21 with the cause named (test order), the replay command printed and
10/10 replays with one fingerprint. Every reproduced target replays; no target is reported reproduced without it.

The 23 idoft repositories (362 targets) run on Python 3.9 and are out of go-live scope: every seed collected 0 tests
(pytest exit 2: the `co_qualname` attribute, Python 3.11+, used since trunk `b24770f`), so nothing was explored. On
that engine `fenvix explore` still exited 0 there; the F-18 fix in this branch (reviewer #10) makes it exit 2 with
the runner's error lines.

**Cost of one `fenvix repro TARGET`** (MEASURED, Block 2 run 44743585438, one `fenvix repro` per target, 50 seeds,
10 replays, GitHub Actions ubuntu-latest, from the job logs):

| repository (Python 3.13) | suite tests | targets run | reproduced | seconds per target (min / median / max) |
|---|---:|---:|---:|---|
| anyio | 4,857 | 5 of 16 | 4 (1 not found) | 569.7 / 1,862.2 / 2,589.3 |
| packaging | 64,196 | 1 | 1 | 680.4 |
| arrow | 1,904 | 2 | 2 | 103.6 / 116.6 / 129.6 |
| jsonschema | 8,529 | 2 | 2 | 74.9 / 82.5 / 90.1 |
| rich | 981 | 5 | 5 | 27.2 / 27.6 / 55.7 |

What the search runs: for each configuration (fixed order, then seeds 1..N), only the tests ordered before the target
in that configuration, plus the next one (`prefix_through`): on average half the suite under a shuffled order, the
whole suite never. Minimisation then runs subsets of that prefix.

**Gap (explicit, F-02): single-target repro time on large suites.** Narrowing the search further, to the tests the
target can depend on, needs dependency facts: which earlier tests write state the target reads. The prefix is the
smallest set that is sound without them, because any earlier test can pollute shared state. The cache with proof
records per-test reads and writes and could supply them, but that is a cross-row design (cache row and F-02) and not
done here. Until then, `fenvix explore --targets` is the batch path: one search shared by every target, which is
what Block 2 measures below. A developer with one flaky test on anyio waits about 10–45 minutes (MEASURED above).

**Not true.** Node adapters for repro, explore and replay belong to the Node session (branch `claude/node`).
`docs/CLI.md` fixes their interface. The vitest, jest and playwright adapters are registered and refuse with a clear
message until then.

## F-03 verifier

**True.**
- The trace header records every run input as text: runtime, runner, seed, hash seed, clock, time zone, locale,
  each environment variable as a digest, network and cassette digest, fs, entropy, bytecode, ASLR and order.
- `fenvix verify` reports runs whose inputs differ as DIVERGENT, naming the first differing input.
- It compares the tests that ran before each test (order).
- It never reports identical a test that used an uncontrolled source: thread, child, I/O readiness, native client.
- An empty run verifies nothing (exit 1). A missing trace exits 2.
- `--ignore-env` declares variables irrelevant and lists them.
- Each reason prints a hint. The Node shell records the same inputs.
- Tests: `tests/test_verifier_truth.py` (one per input in the family: clock, seed, hash seed, network, fs, env,
  tz, locale, entropy, order, uncontrolled sources), the Rust unit tests in `crates/detpy-core/src/verify.rs`, and
  `node/test/verifier-inputs.test.js`.

## F-18 one `fenvix` command

**True.**
- The `fenvix` console script has these commands:
  - `pytest`, `python`, and every Python runner shell
  - the JS runners through detjs
  - `repro`, `explore`, `replay` and `verify`
  - `cassette`, `doctor`, `detect` and `version`
- `docs/CLI.md` describes each command and the runner-adapter interface.
- `fenvix --help` (and the image's `release/fenvix --help`, which prints it) names every command at the start of
  its own line, the release-1 names (`python`, `python-runner`, `node`) included.
- A suite that cannot run is an error, not an empty success:
  - `fenvix explore` exits 2 and prints the runner's error lines.
  - `fenvix repro` reports `not collected: the suite did not collect cleanly` with them.
  - A missing `--python` is one line (reviewer #10, #12).
- Tests: `tests/test_fenvix_cli.py`.

## Fixes made to get CI green, outside the four rows (found failing on the trunk too)

- `test_repro_rust::test_prefix_through_matches_reference` failed on 3.14: the `list.index` message changed. The Rust
  path now raises Python's own error.
- Node 26 cache: Node 26's `fs.promises.readdir(recursive, withFileTypes)` follows links, which gave a WRONG REUSE.
  Whether the runtime follows links is now probed, and the listing is keyed as following until the probe answers.
  `r021b-fixes` was updated for Node 26, including the fact that Stats objects now carry own symbol fields.
- `test_child_own_temporary_files_are_not_inputs` failed on CI only: on the Ubuntu 24.04 image `cat` statx's the file it reads, which counted as reading the real clock. Programs whose output never depends on file times (cat, head, wc, grep, sort, checksums...) are exempt like rm/mkdir already were, and `diff`, `test`, `find`, `ls`, `stat`, `cp` and `tar` are not. The reason now names the program (`tests/test_follow_rust.py` case `cat-exempt`).
- The release-1 node step now prints its log when it fails.

## Next round (explicit gaps, not done here)

- TLS over memory BIOs: the socket is found in the caller's frames. A library that hides its socket deeper than
  that (no socket, no stream with `extra_attributes` within 8 frames) is recorded as ciphertext and refused on
  replay, as before this round.

- F-01, CPU count:
  - `psutil.cpu_count` is not pinned (it reads `/proc` and `sched_getaffinity` natively).
  - Child processes see the real count.
  - Class rule: a read of the real CPU count that is not pinned must be recorded as an event (the verifier never
    stays silent about it).
- F-02: narrowing a single-target repro to the tests the target can depend on, from the cache's per-test read and
  write facts (a cross-row design, cache row and F-02). See the timing gap above.
- Python 3.9 projects (the 23 idoft repositories of Block 2): a clean refusal ("Python 3.11+ required") instead of a
  collection crash. The crash is the trunk's `co_qualname` use (`b24770f`), outside these rows.

## Gaps of the audit in these rows

| gap | status | area | regression test / evidence / what is missing |
|---|---|---|---|
| G-0041 | OUT OF SCOPE | Go / fingerprints | Go/JVM/Windows (go-live scope) |
| G-0054 | OUT OF SCOPE | JVM / det verifier | Go/JVM/Windows (go-live scope) |
| G-0135 | OTHER ROW | Node / det time | Node clock control (process.uptime): Node F-01 row; with this branch the Node header records inputs but uptime is still not an event |
| G-0139 | FIXED | Node / det time | node/test/verifier-inputs.test.js (TZ, env and seed differences are divergent and named). Verifier part only: Node does not pin TZ (Node F-01 row) |
| G-0140 | FIXED | Node / det time | node/test/verifier-inputs.test.js (locale recorded as input). Verifier part only: Node does not pin the locale |
| G-0165 | FIXED | Python / det network | tests/test_network_gaps.py::test_sendmsg_and_recvmsg_are_recorded_and_replayed |
| G-0166 | FIXED | Python / det network | tests/test_network_gaps.py::test_secrets_are_masked_and_a_different_request_is_refused; tests/test_network_rust.py::test_replayed_socket_matches_reference |
| G-0167 | FIXED | Python / det network | tests/test_network_gaps.py::test_secrets_are_masked_and_a_different_request_is_refused; cassette.rs redact_masks_secret_headers_keeping_the_length |
| G-0168 | FIXED | Python / first use | tests/test_f01_gaps.py::test_first_run_after_a_checkout_or_an_edit_is_laid_out_like_later_runs (fresh checkout and edit: same set order as every later run, verify IDENTICAL), ::test_cold_workers_of_a_parallel_run_are_a_run_input (-n: cold workers are a run input, never identical) |
| G-0177 | FIXED | Python / repro | tests/test_f01_gaps.py::test_repro_of_a_seed_dependent_numpy_failure_is_reproduced |
| G-0178 | FIXED | Python / repro | tests/test_fenvix_cli.py::test_repro_prints_cause_seed_order_and_replay_command (bundle divergence = order, names the polluter) |
| G-0179 | FIXED | Python / verifier | tests/test_f01_gaps.py::test_numpy_imported_lazily_and_unseeded_generators (numpy in conftest: no entropy event) |
| G-0180 | FIXED | Python / verifier | tests/test_verifier_truth.py::test_uncontrolled_sources_are_never_identical (thread, executor race, child, io); verify.rs uncontrolled_sources_are_never_identical |
| G-0234 | FIXED | CLI | tests/test_fenvix_cli.py::test_help_lists_the_product_commands_and_version_flags, ::test_repro_prints_cause_seed_order_and_replay_command |
| G-0260 | FIXED | Docs missing / repro guide (flaky test to reproducible defec | docs/CLI.md "Flaky test to reproducible defect" |
| G-0272 | FIXED | Engine docs / help text: fenvix | tests/test_fenvix_cli.py::test_help_lists_the_product_commands_and_version_flags |
| G-0389 | OUT OF SCOPE | Limits / GO.md no record/replay | Go/JVM/Windows (go-live scope) |
| G-0418 | OUT OF SCOPE | Limits / RELEASE-1.md repro/explore Go | Go/JVM/Windows (go-live scope) |
| G-0419 | OUT OF SCOPE | Limits / RELEASE-1.md repro/explore JVM | Go/JVM/Windows (go-live scope) |
| G-0420 | NODE SESSION | Limits / RELEASE-1.md repro/explore Node | Node repro/explore/replay adapters: branch claude/node; the interface is fixed in docs/CLI.md and the adapters are registered (vitest, jest, playwright) with a clear refusal |
| G-0424 | OTHER ROW | Limits / runners/bun.md no record/replay | Node runner record/replay (Bun): Node network row |
| G-0425 | OTHER ROW | Limits / runners/deno.md no record/replay | Node runner record/replay (Deno): Node network row |
| G-0448 | NODE SESSION | Node / repro | Python part done (fenvix repro/explore/replay); Node adapters: branch claude/node |
| G-0514 | FIXED | Python / det environment | tests/test_controls_f01.py::test_environment; tests/test_verifier_truth.py::test_runs_differing_in_one_source_are_divergent_and_name_it[env], [env-unread] |
| G-0515 | FIXED | Python / det locale | tests/test_controls_f01.py::test_locale; tests/test_verifier_truth.py::...[locale-pinned], [locale-kept] |
| G-0516 | FIXED | Python / det network | tests/test_network_gaps.py::test_asyncio_clients_are_recorded_and_replayed |
| G-0517 | MOVED TO PY-07 | Python / det scheduling | scheduling (asyncio, threads) is Level 1; meanwhile the verifier marks such tests uncontrolled.thread / uncontrolled.io and never reports them identical |
| G-0518 | MOVED TO PY-07 | Python / det scheduling | same as G-0517 |
| G-0519 | FIXED | Python / det timezone | tests/test_controls_f01.py::test_time_zone; tests/test_verifier_truth.py::...[tz-pinned], [tz-kept]; tests/test_review_r009.py::test_pinned_timezone_makes_the_machine_zone_irrelevant; tests/runners_cases.py case timezone_pinned (every runner) |
| G-0520 | MOVED TO PY-07 / L2 | Python / levels | L2 deterministic VM: no code in this row |
| G-0532 | FIXED | Python / repro | tests/test_fenvix_cli.py::test_repro_and_replay_work_for_the_unittest_shell (one adapter for unittest, django, nose2, ward, zope-testrunner, doctest) |
| G-0533 | MOVED TO PY-07 | Python / repro | scheduling-flaky tests: fenvix repro now says NOT REPRODUCIBLE and names the uncontrolled source |
| G-0540 | FIXED | Python / runner unittest | tests/test_fenvix_cli.py::test_repro_and_replay_work_for_the_unittest_shell |
| G-0541 | OTHER ROW (runners) | Python / runner unittest-parallel | unittest-parallel shell |
| G-0637 | OTHER ROW (service) | State between jobs / replay bundles | bundle upload route of the service; bundles are self-contained now (G-1556) and docs/EXPLORE.md uploads them as CI artifacts |
| G-0697 | FIXED | CLI | tests/test_fenvix_cli.py::test_detect_names_runners_and_subprojects (first-level subprojects) |
| G-0698 | FIXED | CLI | tests/test_fenvix_cli.py::test_detect_names_runners_and_subprojects (requirements.txt, manage.py, ...) |
| G-0699 | FIXED | CLI | tests/test_fenvix_cli.py::test_detect_names_runners_and_subprojects (runner per project) |
| G-0700 | FIXED | CLI | tests/test_fenvix_cli.py::test_doctor_checks_the_machine |
| G-0772 | FIXED | Docs missing / network record and replay (cassettes) | docs/NETWORK.md |
| G-0786 | FIXED | Docs missing / replay guide and bundle format | docs/BUNDLE.md (replaying, from CI to a laptop) |
| G-0795 | FIXED | Docs missing / verifier and trace format | docs/TRACE.md (trace format, header, inputs, test line, event encoding) |
| G-0964 | FIXED | Engine docs / detpy CLI | docs/CLI.md (fenvix repro: every option); no runtime behaviour |
| G-0965 | FIXED | Engine docs / detpy CLI | docs/CLI.md (fenvix explore) |
| G-0966 | FIXED | Engine docs / detpy CLI | docs/CLI.md (fenvix replay) |
| G-0967 | FIXED | Engine docs / detpy CLI | docs/TRACE.md (detpy backends) |
| G-0968 | FIXED | Engine docs / detpy CLI | docs/CLI.md (fenvix verify: --json, --show-stable, --ignore-env, exit codes) |
| G-0969 | FIXED | Engine docs / detpy CLI | docs/BUNDLE.md |
| G-0980 | OUT OF SCOPE | Engine docs / help text: fenvix-agent.jar | Go/JVM/Windows (go-live scope) |
| G-0981 | OUT OF SCOPE | Engine docs / help text: fenvix-go | Go/JVM/Windows (go-live scope) |
| G-0983 | FIXED | Engine docs / help text: python -m detpy | tests/test_f01_gaps.py::test_runner_shells_list_the_det_options[unittest] |
| G-0991 | FIXED | Engine docs / output text: detpy repro, replay, verify | tests/test_fenvix_cli.py::test_repro_prints_cause_seed_order_and_replay_command |
| G-0992 | FIXED | Engine docs / output text: detpy repro, replay, verify | docs/BUNDLE.md (local address vs .fenvix/defects/<id>) |
| G-1514 | FIXED | Python / det clock | tests/test_f01_gaps.py::test_asyncio_loop_time_is_virtual |
| G-1515 | FIXED | Python / det clock | tests/test_f01_gaps.py::test_cpu_time_clocks_are_virtual |
| G-1516 | FIXED | Python / det clock | tests/test_f01_gaps.py::test_times_of_files_the_test_wrote_are_virtual |
| G-1517 | FIXED | Python / det environment | tests/test_verifier_truth.py::test_env_read_names_the_variable_and_the_site |
| G-1518 | FIXED | Python / det network | tests/test_network_gaps.py::test_udp_is_recorded_and_replayed |
| G-1519 | FIXED | Python / det network | tests/test_network_gaps.py::test_old_recordings_are_not_replayed_past_max_age |
| G-1520 | FIXED | Python / det network | tests/test_network_gaps.py::test_child_processes_meet_the_closed_network (children that honour proxy variables; others are uncontrolled.child, never identical) |
| G-1521 | FIXED | Python / det network | tests/test_network_gaps.py::test_native_network_clients_are_never_identical (marked uncontrolled.native, never identical; blocking/recording them needs the syscall backend) |
| G-1522 | FIXED | Python / det network | tests/test_network_gaps.py::test_tls_replay_answers_what_the_handshake_negotiated |
| G-1523 | FIXED (founder decision) | Python / det randomness | OS entropy controlled by default under --det, opt-out --det-entropy=observe: tests/test_review_r023b.py, tests/test_verifier_truth.py (urandom case), tests/test_proofcache.py::test_os_entropy_is_cached_only_when_controlled |
| G-1524 | FIXED | Python / det randomness | tests/test_f01_gaps.py::test_uuid1_is_deterministic |
| G-1525 | FIXED | Python / det randomness | tests/test_f01_gaps.py::test_numpy_imported_lazily_and_unseeded_generators (real numpy, pip-installed by the test) |
| G-1526 | FIXED | Python / det randomness | tests/test_f01_gaps.py::test_numpy_imported_lazily_and_unseeded_generators |
| G-1527 | FIXED | Python / det randomness | tests/test_f01_gaps.py::test_faker_torch_tensorflow_are_seeded (real Faker; torch/TensorFlow stand-ins) |
| G-1529 | FIXED | Python / explore | tests/test_fenvix_cli.py::test_explore_resumes_and_selects; docs/EXPLORE.md (nightly workflow template) |
| G-1530 | FIXED | Python / explore | tests/test_fenvix_cli.py::test_explore_resumes_and_selects (--only-unstable, --changed-since) |
| G-1531 | FIXED | Python / first use | tests/test_f01_gaps.py::test_seeds_share_a_few_hash_seeds, ::test_first_precompile_says_so_and_old_caches_are_evicted |
| G-1532 | FIXED | Python / first use | tests/test_f01_gaps.py::test_det_options_without_det_are_errors |
| G-1533 | FIXED | Python / first use | tests/test_f01_gaps.py::test_det_options_without_det_are_errors[--det-isolate] |
| G-1534 | FIXED | Python / first use | tests/test_fenvix_cli.py::test_console_script_is_declared |
| G-1535 | FIXED | Python / first use | tests/test_f01_gaps.py::test_runner_shells_list_the_det_options |
| G-1536 | FIXED | Python / first use | tests/test_f01_gaps.py::test_det_turned_on_by_configuration |
| G-1537 | OTHER ROW (cache with proof) | Python / first use | uncacheable-after-entropy rule of the cache |
| G-1538 | FIXED | Python / first use | tests/test_verifier_truth.py::test_detpy_verify_agrees_and_empty_runs_verify_nothing; verify.rs empty_runs_verify_nothing |
| G-1540 | MOVED TO PY-07 / L2 | Python / levels | syscall backend: no code in this row; native clients and children are marked uncontrolled meanwhile (G-1521, G-1520) |
| G-1541 | MOVED TO PY-07 / L2 | Python / levels | escalation needs a next level |
| G-1554 | FIXED | Python / replay | tests/test_fenvix_cli.py::test_pytest_entry_adds_det_and_prints_the_repro_command |
| G-1555 | FIXED | Python / replay | tests/test_fenvix_cli.py::test_help_lists_the_product_commands_and_version_flags; docs/CLI.md |
| G-1556 | FIXED | Python / repro | tests/test_fenvix_cli.py::test_bundle_is_self_contained_and_work_files_are_removed (upload: service row) |
| G-1557 | FIXED | Python / repro | tests/test_fenvix_cli.py::test_repro_from_a_parallel_plan_searches_the_workers_list |
| G-1563 | OTHER ROW (cache with proof) | Python / runner unittest | same rule in the unittest shell |
| G-1564 | OTHER ROW (runners) | Python / runner unittest | plain python -m unittest in place (sitecustomize hook); FENVIX_DET=1 covers pytest and the shells (G-1536) |
| G-1565 | OTHER ROW (runners / parallel) | Python / runner unittest | parallel mode of the unittest shell |
| G-1566 | OTHER ROW (runners / parallel) | Python / runner unittest | --det-isolate for the unittest shell |
| G-1567 | OTHER ROW (cache with proof, DECIDE) | Python / runner unittest | unit of reuse in the unittest shell: audit class DECIDE |
| G-1573 | NOT A WRONG RESULT | Python / verifier / fs order | the directory content really differed between the runs (the first run had written its trace into the listed directory): the divergence is true; the default trace location .detpy/ is never listed by the test; docs/TRACE.md [fs] row says so |
| G-1861 | FIXED | CLI | tests/test_fenvix_cli.py::test_help_lists_the_product_commands_and_version_flags |
| G-1862 | FIXED | CLI | tests/test_fenvix_cli.py::test_zope_alias_and_python_runner_compat (fenvix zope and fenvix zope-testrunner) |
| G-1863 | FIXED | CLI | tests/test_fenvix_cli.py::test_detect_names_runners_and_subprojects |
| G-1864 | OUT OF SCOPE | CLI | Go/JVM/Windows (go-live scope) |
| G-1869 | OUT OF SCOPE | Code marker / detjs replay socket on Windows | Go/JVM/Windows (go-live scope) |
| G-1968 | FIXED | Engine docs / help text: fenvix | tests/test_fenvix_cli.py::test_help_lists_the_product_commands_and_version_flags (help rewritten for the user) |
| G-1969 | FIXED | Engine docs / help text: fenvix | tests/test_fenvix_cli.py::test_help_lists_the_product_commands_and_version_flags (help names zope-testrunner) |
| G-1970 | FIXED | Engine docs / help text: fenvix | tests/test_fenvix_cli.py::test_help_lists_the_product_commands_and_version_flags |
| G-1971 | OUT OF SCOPE | Engine docs / help text: fenvix | versions of fenvix-go and fenvix-skip (Go/JVM components) |
| G-1972 | OUT OF SCOPE | Engine docs / help text: fenvix | Go/JVM/Windows (go-live scope) |
| G-1973 | FIXED | Engine docs / help text: fenvix | tests/test_fenvix_cli.py::test_detect_names_runners_and_subprojects |
| G-1974 | OUT OF SCOPE | Engine docs / help text: fenvix-agent.jar | Go/JVM/Windows (go-live scope) |
| G-1975 | OUT OF SCOPE | Engine docs / help text: fenvix-agent.jar | Go/JVM/Windows (go-live scope) |
| G-1976 | OUT OF SCOPE | Engine docs / help text: fenvix-agent.jar | Go/JVM/Windows (go-live scope) |
| G-1977 | OUT OF SCOPE | Engine docs / help text: fenvix-agent.jar | Go/JVM/Windows (go-live scope) |
| G-1978 | OUT OF SCOPE | Engine docs / help text: fenvix-go | Go/JVM/Windows (go-live scope) |
| G-1979 | OUT OF SCOPE | Engine docs / help text: fenvix-go | Go/JVM/Windows (go-live scope) |
| G-1980 | OUT OF SCOPE | Engine docs / help text: fenvix-go | Go/JVM/Windows (go-live scope) |
| G-1981 | OUT OF SCOPE | Engine docs / help text: fenvix-go | Go/JVM/Windows (go-live scope) |
| G-1982 | OUT OF SCOPE | Engine docs / help text: fenvix-skip | Go/JVM/Windows (go-live scope) |
| G-1994 | FIXED | Engine docs / help text: python -m detpy | tests/test_f01_gaps.py::test_detpy_help_describes_the_runners |
| G-1995 | FIXED | Engine docs / help text: python -m detpy | tests/test_fenvix_cli.py::test_help_lists_the_product_commands_and_version_flags (python -m detpy --version) |
| G-1996 | FIXED | Engine docs / help text: python -m detpy | detpy verify --show-stable and fenvix verify --show-stable have help text (help test above) |
| G-1997 | FIXED | Engine docs / help text: python -m detpy | tests/test_fenvix_cli.py::test_help_lists_the_product_commands_and_version_flags (fenvix explore --help describes every option) |
| G-1998 | FIXED | Engine docs / help text: python -m detpy | tests/test_fenvix_cli.py::test_help_lists_the_product_commands_and_version_flags (fenvix replay --help) |
| G-1999 | FIXED | Engine docs / help text: python -m detpy | tests/test_fenvix_cli.py::test_help_lists_the_product_commands_and_version_flags (fenvix repro --help: example, output) |
| G-2000 | FIXED | Engine docs / help text: python -m detpy | tests/test_f01_gaps.py::test_runner_shells_list_the_det_options[doctest] |
| G-2001 | FIXED | Engine docs / help text: python -m detpy | tests/test_f01_gaps.py::test_missing_runner_and_misspelled_option_are_one_line (django) |
| G-2002 | FIXED | Engine docs / help text: python -m detpy | tests/test_f01_gaps.py::test_missing_runner_and_misspelled_option_are_one_line (nose2) |
| G-2003 | FIXED | Engine docs / help text: python -m detpy | tests/test_f01_gaps.py::test_missing_runner_and_misspelled_option_are_one_line (ward) |
| G-2004 | FIXED | Engine docs / help text: python -m detpy | tests/test_f01_gaps.py::test_missing_runner_and_misspelled_option_are_one_line (zope) |
| G-2005 | FIXED | Engine docs / help text: python -m detpy | tests/test_f01_gaps.py::test_detpy_help_describes_the_runners |
| G-2019 | FIXED | Engine docs / output text: detpy repro, replay, verify | verify prints a plain verdict line and one hint per reason; docs/TRACE.md explains every word (tests/test_verifier_truth.py asserts the verdict lines) |
| G-2020 | FIXED | Engine docs / output text: detpy repro, replay, verify | tests/test_fenvix_cli.py::test_repro_prints_cause_seed_order_and_replay_command (replay prints a sentence) |
| G-2021 | FIXED | Engine docs / output text: detpy repro, replay, verify | tests/test_fenvix_cli.py::test_bundle_is_self_contained_and_work_files_are_removed |
| G-2022 | FIXED | Engine docs / output text: detpy repro, replay, verify | docs/BUNDLE.md (every field) |
| G-2198 | FIXED | Python / det clock | tests/test_f01_gaps.py::test_sleep_label_says_real_when_the_time_control_is_off |
| G-2199 | FIXED | Python / det network | tests/test_network_gaps.py::test_reverse_lookups_are_guarded |
| G-2200 | FIXED | Python / det network | tests/test_network_gaps.py::test_cassette_command_lists_renames_and_drops |
| G-2201 | FIXED | Python / det network | docs/NETWORK.md (matching, merging, what is stored, review with fenvix cassette list) |
| G-2202 | FIXED | Python / first use | tests/test_f01_gaps.py::test_first_precompile_says_so_and_old_caches_are_evicted |
| G-2203 | FIXED | Python / first use | tests/test_fenvix_cli.py::test_help_lists_the_product_commands_and_version_flags |
| G-2204 | FIXED | Python / first use | tests/test_verifier_truth.py::test_detpy_verify_agrees_and_empty_runs_verify_nothing |
| G-2205 | FIXED | Python / first use | tests/test_fenvix_cli.py::test_replay_of_a_non_bundle_is_one_line |
| G-2206 | FIXED | Python / first use | tests/test_f01_gaps.py::test_missing_runner_and_misspelled_option_are_one_line (did you mean --det-seed) |
| G-2207 | FIXED | Python / first use | tests/test_f01_gaps.py::test_state_directory_ignores_itself_but_the_cassette |
| G-2208 | OTHER ROW (cache with proof) | Python / first use | receipt wording of the cache |
| G-2209 | FIXED | Python / first use | tests/test_fenvix_cli.py::test_repro_of_an_unknown_test_says_so |
| G-2210 | FIXED | Python / first use | tests/test_f01_gaps.py::test_entropy_divergence_hints_at_det_urandom |
| G-2218 | FIXED | Python / verifier | tests/test_verifier_truth.py::test_same_inputs_are_identical (runtime, runtime_version, inputs in the header) |
