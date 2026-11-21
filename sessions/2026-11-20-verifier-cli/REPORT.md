PARTIAL

# F-01 / F-02 / F-03 / F-18: deterministic runs, flaky test to reproducible defect, verifier, one `fenvix` command

Branch `claude/verifier-cli` (cut from `claude/release-1`). PR #4 merged (CI green on `1c4aa01`, release-1 run
44781855441, MEASURED). PR #11 (F-18 complete, design A) open into `claude/release-1`, head `a7fd7e9`.
Every number is labelled MEASURED (from a run named here), ESTIMATED, DECLARED or UNKNOWN.

## Verdict

PARTIAL. All four rows work on real projects. Why not DONE:

- PR #11 is open. It holds F-18 complete and design A for the environment and the CPU count. It has not been
  through the full CI, the exam or the reviewer yet.
- Reviewer p1-verifier findings #5, #8 and #9 are fixed in PR 2. The reviewer's own tests pass, but PR 2 is not open yet:
  - #5: a polluter was named although the replays did not confirm it
  - #8: traces without run inputs were called IDENTICAL
  - #9: replay outside the project root reported the defect as possibly fixed

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
- **G-1523:** an audit DECIDE, not a defect. OS entropy under `--det` is observed and never hidden. A test that reads it
  is reported `[entropy]` with a hint to `--det-urandom`, which controls it. Whether `--det` should control it by
  default is the founder's product decision.

## Local suites before the PR #11 push (MEASURED, this container, head `a7fd7e9` = the branch merged with
release-1 `a996b68`)

- Node 22, 24 and 26: 632/632 each.
- Python 3.12 and 3.13 (full suite):
  - The only failures were the help listing (fixed) and stale local packaging metadata (`detpy-0.1.0` installed
    before the trunk renamed the distribution to `fenvix`).
  - After the fix and a reinstall, the affected files pass: 57 passed, 1 skipped on each.
- Python 3.14 (a local 3.14.6 build without `os.getrandom`):
  - Four failures fail on the trunk `a996b68` itself on this machine: two `test_clock_rust` reference tests and two
    `test_review_r023b::test_2e_os_getrandom_is_entropy` cases.
  - `test_capture_sessions_match_reference` fails only inside the full run and passes alone.
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
  tz, locale, urandom, order, uncontrolled sources), the Rust unit tests in `crates/detpy-core/src/verify.rs`, and
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

- F-01, CPU count:
  - `psutil.cpu_count` is not pinned (planned in PR 2).
  - Child processes see the real count.
  - Class rule: a read of the real CPU count that is not pinned must be recorded as an event (the verifier never
    stays silent about it).
- F-02: narrowing a single-target repro to the tests the target can depend on, from the cache's per-test read and
  write facts (a cross-row design, cache row and F-02). See the timing gap above.
- Python 3.9 projects (the 23 idoft repositories of Block 2): a clean refusal ("Python 3.11+ required") instead of a
  collection crash. The crash is the trunk's `co_qualname` use (`b24770f`), outside these rows.
- Reviewer p1-verifier findings in PR 2: #5, #8, #9.

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
| G-1523 | DECIDE (founder) | Python / det randomness | audit class DECIDE: OS entropy is observed under --det, controlled with --det-urandom; the verifier reports it [entropy] with a hint to --det-urandom (G-2210) |
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
