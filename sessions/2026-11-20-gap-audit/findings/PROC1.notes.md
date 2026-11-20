# PROC1 notes: process gaps of the early blocks

Agent PROC1. Scope: Block 1 (Level 0 Python + harness), Node Level 0 track, L1 asyncio study, Block 2 (repro +
explore), Block 3 (L1 threads), cache with proof step 1, market test, head-to-head, plus ROADMAP / NOW / LOG claims.
172 entries in `PROC1.gaps.jsonl` (23 RAN, 83 READ, 66 DOC). Every entry carries `prompt` and `block`.

Repositories: "brain" = `/home/user/fenvix-brain-cli` (main); "engine@release-1" = `/home/user/audit/engine`;
side branches read through `/home/user/fenvix-engine-cli` (`origin/<name>`). Everything run used the built wheel
`/home/user/audit/build/dist/detpy-0.1.0-cp39-abi3-linux_x86_64.whl` in venvs under `/home/user/audit/work/PROC1/`.

## (c) What the lead should know first

1. **Block 3 is CLOSED in the plan and absent from the audited branch.** `--det-threads` and the asyncio scheduler
   (`--det-async`) exist only on `origin/claude/l1-threads-fix` (169 commits not in release-1) and
   `origin/claude/l1-asyncio-study` (20 commits). ROADMAP.md:52, DECISIONS.md:42 and NUMBERS.md present Block 3 as
   done. release-1's own docs (docs/RELEASE-1.md feature table) never mention Level 1 for Python. PROC1-001, -005.
2. **`pytest --det` is broken on Python 3.9 and 3.10 on release-1** (collection crash, `co_qualname`), while
   docs/RELEASE-1.md:58,:113 say "Python 3.9-3.11: Level 0 only" / "3.9+ for --det" and pyproject says `>=3.9`.
   The release gate runs 3.12 and 3.13 only. Block 1's IDoFT pool was measured on 3.9. PROC1-028, -029.
3. **Block 2 was built for pytest only and never extended.** `repro` / `explore` / `replay` / `--det-order` exist as
   `python -m detpy ...` for pytest. Not for the other Python runners, Node, Go or JVM, and not in the single `fenvix`
   CLI. PROC1-098, -107, -108, -109, -110.
4. **Root causes in the process itself** (PROC1-168, -169, -170, -171): a block closes on "report + reviewer PASS",
   with no merge step into the release line; the reviewer template checks the prompt's "Done means", never the product
   promise; several contracts were never saved in `prompts/`; two reviews ran without the brief.
5. **Numbers quoted as product facts that the shipped engine has not reproduced:** the market test (7 of 10) and the
   head-to-head (41%, 0 wrong) come from a harness model that is not on release-1; the engine's own walks on the same
   repositories are far lower (LOG.md:8). The home-assistant 76% / 94% predates the last fix round. PROC1-149, -126,
   -158.
6. **New false failures found by running release-1** (each one is a note from an early report that was never closed):
   trio (PROC1-010), pytest-order (PROC1-042), `timeit.autorange` hang (PROC1-051).
7. **Cross-job reuse** (PROC1-123): one changed CI variable (`GITHUB_RUN_ID`) made 3 of 3 tests rerun, including a
   test that never touches the environment. The step 1 report asked for a founder decision; none is recorded.

### Contradictions between documents and code

| claim | where | what the code says |
|---|---|---|
| Block 3 CLOSED: `--det --det-threads` breaks 0 tests ... | brain ROADMAP.md:52, DECISIONS.md:42, NUMBERS.md "Block 3, L1 threads, final" | flag unknown on release-1 (PROC1-001) |
| "L1, runtime (asyncio prototype built ... see fenvix-engine-cli docs/L1-ASYNCIO.md)" | brain ARCHITECTURE.md:8 | file does not exist on release-1 (PROC1-026) |
| "cache vocabulary (not wired)" / "Not wired into the plugin yet" | brain ARCHITECTURE.md:14; engine docs/ARCHITECTURE.md | `--det-cache` is wired; both documents are from 2026-11-16 |
| "Header meta, required: runtime, runtime_version" | brain ARCHITECTURE.md:40 | Python header has neither (PROC1-032) |
| "the test escalates to the next level" | brain ARCHITECTURE.md:10 | no escalation code (PROC1-025) |
| "Python 3.9-3.11: Level 0 only" | engine docs/RELEASE-1.md:58 | 3.9 and 3.10 crash under `--det` (PROC1-028) |
| "We do not sell runners" | brain PRODUCT.md:34 | replaced by DECISIONS 2026-11-17 (PROC1-172) |
| virtual-day clock "Same rule for Python, Node and Go" | brain DECISIONS.md:17 | only Go has it (PROC1-146, -147) |
| "every prompt handed to a session is saved here" | brain prompts/README.md | PROC1-170 |

### Notes that I checked and found fixed or sound on release-1 (NOT gaps, listed so nobody re-checks)

* Reviewer N6 (pytest-django database-first ordering undone): fixed (`tests/test_django_order.py`,
  `python/detpy/_django.py`, LIMITS O2).
* R-001 FIX 1-4, recheck N3-N5, R-003 E4 and E6 (non-binding stand-ins, standalone repro names the setter): tests
  present on release-1 (`tests/test_review_lock_type.py`, `test_review_plugin_options.py`,
  `test_review_b1_randomly_options.py`, `test_review_b4_p005_rule.py`, `test_review_t1_extra.py`,
  `test_nonbinding_generic.py`, `tests/test_repro.py:91`). The two commits of `claude/gracious-rubin-eyswxd` that are
  not in release-1 (4f1d88c3, ee1768b6) are result files only.
* R-007 FIX 4 class (engine frames visible to stack inspection) under plain `--det`: a sleeping thread's stack shows
  no detpy frame on release-1 (ran: 1 passed plain and under `--det`).
* R-010 N-b (git worktree / gitdir file outside the root): the engine keys in-process `.git` reads through a
  worktree's gitdir. Ran in a normal checkout and in a worktree: after an empty commit both give
  `not reused: data 1` and the fresh failure.
* R-009 F1-F5 and R-009b R1-R4: reviewer tests are on release-1 (`tests/test_review_r009.py`,
  `tests/test_review_r009b.py`); not re-run here (other agents own the cache).
* `detpy repro` / `explore` on release-1 work for pytest (ran both, see PROC1-114).
* NUMBERS.md already carries the head-to-head median and per-change form the reviewer asked for; the "6 libraries"
  error in the brain summary was corrected to 5.

## (a) Could not check

* **jinja mtime leak (PROC1-015) and the more-itertools lock convoy (PROC1-016):** not re-run (would need the
  projects' suites twice under `--det`). Both are DOC: the threads report says they "remain".
* **pytest-dependency** (named with pytest-order by the reviewer): not run. It does not reorder by itself; under
  `--det-seed` a dependent test can run before its dependency and be skipped. Suspected, not proven.
* **Side effects of skipped tests (PROC1-135):** DOC only. The reports call it UNKNOWN; I did not construct a case
  against the carried-set rule of the later rounds.
* **Engine child following and daemons left behind (PROC1-154):** the wait was measured in the market-test harness,
  not in the engine's `follow`; not tested here.
* **ASLR under Docker's default seccomp profile (PROC1-068):** LIMITS R3 says the personality call "fails silently
  under seccomp profiles that forbid it". In this sandbox the header shows `aslr_disabled: true`; I had no container
  with Docker's default profile to confirm the silent failure.
* **Node items** (PROC1-076 to -106): read from docs/NODE.md, the Node sources and the reports. I ran no JavaScript
  project; the Node agents own those runs.
* **Side-branch claims** (threads slowdown, coverage on Python < 3.12, exploration cost): read from the reports, not
  re-measured, since the code is not on the audited branch.
* **macOS / Windows:** from docs and CI configuration only.
* **fenvix-app** was searched only for an MCP server and a GitHub Action (none). The PR comment exists in
  `github-app/src/results/render.ts`; its content was not audited here.
* The brain reviewer reports for R-005, R-006, R-007 and R-009 have no saved prompt, so their own "Done means" could
  not be compared with the promise.

## (b) Evidence appendix (commands and trimmed real outputs)

Set-up: `uv venv -p 3.13 venv; uv pip install -p venv/bin/python <wheel> pytest` (also `venv3.9`, `venv3.10`,
`venv3.11`). `P` = that venv's python. All runs under `timeout`.

### PROC1-001, PROC1-005 (flags absent)

```
$ P -m pytest --det --det-threads -q
python -m pytest: error: unrecognized arguments: --det-threads
$ P -m pytest --det --det-async -q
python -m pytest: error: unrecognized arguments: --det-async
$ git -C /home/user/fenvix-engine-cli merge-base --is-ancestor origin/claude/l1-threads-fix origin/claude/release-1   # false
claude/l1-threads-fix   7a08b31b NOT-ancestor ahead-of-release1=169 mb=1573079b
claude/l1-asyncio-study f3e8be4e NOT-ancestor ahead-of-release1=20  mb=227c1610
claude/gracious-rubin-eyswxd ee1768b6 NOT-ancestor ahead-of-release1=2 (4f1d88c3, ee1768b6: result files)
claude/node-l0, claude/cache-proof-step1, claude/rust-hotpaths-2: ANCESTOR
claude/market-test, claude/sweet-mendel-rtdg7f, claude/loving-maxwell-58mv2w: NOT-ancestor
$ ls python/detpy/aio.py python/detpy/threads.py python/detpy/frames.py docs/L1-ASYNCIO.md docs/L1-THREADS.md
ls: cannot access ...: No such file or directory   (all five)
```

`pytest --help` on release-1 lists these `--det*` options only: `--det, --det-seed, --det-order, --det-trace,
--det-compare, --det-record, --det-cassette, --det-allow-host, --det-epoch, --det-tick, --det-tick-adapt,
--det-sleep, --det-disable, --det-urandom, --det-keep-aslr, --det-no-reexec, --det-max-events, --det-outcomes,
--det-cache, --det-cache-verify, --det-cache-dists, --det-cache-no-follow, --det-cache-max-age,
--det-cache-epoch-window, --det-cache-shared, --det-cache-keys, --det-cache-receipts, --det-plan,
--det-plan-worker, --det-isolate`.

### PROC1-002 (thread interleaving)

Test: 4 threads, each 3,000 appends and a `time.time()` every 50 iterations, `sys.setswitchinterval(1e-6)`.
6 runs of `P -m pytest --det test_thr2.py --det-trace=thN.jsonl`, then:

```
$ P -m detpy verify th1.jsonl ... th6.jsonl
covered by Level 0: 0  not covered: 1  missing: 0  outcome-unstable: 0
reasons: thread=1
NOT-COVERED test_thr2.py::test_threads_interleave  [thread] outcomes=passed,passed,passed,passed,passed,passed
    runs 0 vs 1: event #61: [time] time.time @ test_thr2.py:9 = 838000 (thread 2)  <>  [time] time.time @ test_thr2.py:9 = 838000 (thread 3)
```

### PROC1-006 (asyncio keeps real time)

```
test_asyncio_sleep_3s: asyncio.run(asyncio.sleep(3))   -> "1 passed in 3.02s", wall 4.60 s
test_time_sleep_3s:    time.sleep(3)                    -> "1 passed in 0.02s", wall 1.39 s
grep -c '"s":"sched"' .detpy/trace.jsonl -> 0
```

### PROC1-010 (trio)

```
$ P -m pytest -q test_trio.py            -> 3 passed in 0.94s
$ P -m pytest -q --det test_trio.py
    |     assert self.lock.__class__.__module__ == "_thread"
    | AssertionError
trio.TrioInternalError: internal error in Trio - please file a bug!
FAILED test_trio.py::test_trio_timeout - trio.TrioInternalError: internal err...
FAILED test_trio.py::test_trio_nursery - trio.TrioInternalError: internal err...
3 failed in 0.55s        (trio 0.35.0, Python 3.13.18)
```

### PROC1-028, PROC1-124 (Python versions)

```
py3.9  $ pytest --det -q
../venv3.9/lib/python3.9/site-packages/detpy/plugin.py:567: in code
    return (f"code({co.co_qualname}|{co.co_argcount},...
E   AttributeError: 'code' object has no attribute 'co_qualname'
ERROR test_b.py - AttributeError: 'code' object has no attribute 'co_qualname'
py3.9  $ python -m detpy repro test_b.py::test_victim   -> "detpy repro: ...: not-collected"
py3.10 $ pytest --det -q                               -> same AttributeError, 1 error
py3.11 $ pytest --det -q                               -> runs (2 failed, 1 passed as expected); repro works
py3.9 / py3.11 $ pytest --det --det-cache=DIR          -> ERROR: --det-cache needs Python 3.12+ (sys.monitoring)
```

### PROC1-032, -033, -034, -035 (what a failing `--det` run prints and stores)

Project: `test_polluter` appends to a module list, `test_victim` asserts it is empty, `test_fail_time` asserts
`time.time() < 0`.

```
$ P -m pytest --det -q
... (pytest's own failure sections) ...
=============================== detpy (Level 0) ================================
trace: /home/user/audit/work/PROC1/t2/.detpy/trace.jsonl  order digest: 3961983e0fdb1e4fd0c7c1f827baaf2b  seed: 0
=========================== short test summary info ============================
FAILED test_b.py::test_victim - AssertionError: polluted
2 failed, 1 passed in 0.03s
header keys:      encoding, format, meta, order, type, version
header meta keys: adjustments, aslr_disabled, bytecode, controls, detpy, disabled_plugins, epoch_ns, epoch_source,
                  hashseed, implementation, network, order_digest, platform, precompile_s, pytest, python,
                  rebound_references, reexec, runner, seed, shuffle, sleep, tick_adapt, tick_ns, urandom_controlled
test line keys:   checkpoints, counts, events, fingerprint, index, n_events, nodeid, outcome, truncated, type
```

No `runtime`, `runtime_version`, argv, rootdir, commit, dependency or cassette digest; no exception in the test
record; no replay command in the output.

### PROC1-114, PROC1-120 (`detpy repro` and its bundle)

```
$ P -m detpy repro test_b.py::test_victim --seeds 5 --confirm 10 -- -p no:cacheprovider
detpy repro: test_b.py::test_victim: reproduced
  found with fixed order; order minimised from 2 to 2 test(s)
  polluter(s): test_b.py::test_polluter
  replay: 10/10 failed, identical fingerprint: True
  first diverging event vs a passing run: outcome-only: identical observed events, different outcome (passed vs failed): the cause is a source Level 0 does not observe
  replay: pytest --det --det-order=.detpy/repro/test_victim-755636af/order.txt -p no:cacheprovider
  12 pytest runs, 10.26 s
bundle.json keys: bundle, command, config, configs_searched, controls, detpy, divergence, exception, kind,
  minimal_length, order, outcome, polluters, prefix_length, pytest_args, python, replay, replay_command, runs,
  seconds, seed, setters, status, test
"exception": ["AssertionError", "call", "AssertionError: polluted", "/home/user/audit/work/PROC1/t2/test_b.py:6"]
$ P -m detpy explore --budget 1 --max-seeds 3 -- -p no:cacheprovider
detpy explore: 3 seeds in 34.75 s; 1 flaky failing tests (1 always failing, not flaky); 1 replay bundles; ...
```

### PROC1-042 (pytest-order)

`test_needs_setup` (asserts a flag) is defined before `test_setup` (`@pytest.mark.order(1)`, sets the flag).

```
$ P -m pytest -q test_order.py          -> 2 passed
$ P -m pytest -q --det test_order.py    -> FAILED test_order.py::test_needs_setup - AssertionError: pytest-order should have run test_setup first
```

### PROC1-051 (`timeit.autorange`)

```
test: n, t = timeit.Timer("pass").autorange()
$ P -m pytest -q test_timeit.py                   -> 1 passed in 0.44s (wall 1.16 s)
$ timeout 60 P -m pytest -q --det test_timeit.py  -> Terminated, exit=143, wall=60.02 s
```

### PROC1-059, PROC1-060 (time zone, environment)

```
test: assert time.localtime(0).tm_hour == 0
$ TZ=UTC        P -m pytest -q --det test_tz.py   -> 1 passed
$ TZ=Asia/Tokyo P -m pytest -q --det test_tz.py   -> 1 failed
test: assert os.environ.get("CI_VAR", "x") == "x"
$ CI_VAR=y P -m pytest -q --det test_env.py       -> 1 failed
```

### PROC1-056 (syscall backend)

```
$ P -m detpy backends
[{"capabilities": {...}, "implemented": true, "name": "python-hooks"},
 {"capabilities": {... "controls_scheduling": true, "sees_native_code": true ...}, "implemented": false, "name": "syscall"}]
```

### PROC1-074 (unpinned pool)

`harness/repos.json` keys: `_comment, validate, flaky_candidates, flaky_overrides, popular`;
`popular[0] = {'name': 'pygments', 'url': 'https://github.com/pygments/pygments', 'install': ['wcag-contrast-ratio']}`.

### PROC1-123 (reuse across CI jobs)

Three tests: `subprocess.run(["true"])`; `dict(os.environ)`; `assert 1 + 1 == 2`.

```
$ GITHUB_RUN_ID=1 P -m pytest --det --det-cache=.cache -q   -> reused 0 ... not reused: new 3
$ GITHUB_RUN_ID=1 P -m pytest --det --det-cache=.cache -q   -> reused 3 result(s) with proof, ran 0
$ GITHUB_RUN_ID=2 P -m pytest --det --det-cache=.cache -q --det-cache-receipts=r.jsonl
reused 0 result(s) with proof, ran 3, recorded 3 ...
not reused: env 3
{"nodeid": "test_env.py::test_child_inherits_env", "reused": false, "why": "env: environment variable *"}
{"nodeid": "test_env.py::test_copies_env", "reused": false, "why": "env: environment variable *"}
{"nodeid": "test_env.py::test_plain", "reused": false, "why": "env: environment variable *"}
```

Control: a project with only the plain test is reused after the same change (`reused 1 result(s) with proof`).

### PROC1-140 (HEAD reader) and the worktree check

Test parses `.git/HEAD` in process (through the gitdir file in a worktree) and compares with `pin.txt`.

```
normal checkout: run 1 "1 passed, recorded 1"; after `git commit --allow-empty`: fresh "1 failed"; with cache "not reused: data 1 ... 1 failed"
git worktree:    same three results
```

### PROC1-145 (receipt)

```
{"nodeid": "test_p.py::test_plain", "reused": true, "key": "c2bd2e2e0b29f4393a85472e8a72f4a4", "run": "20261120T084051-31101",
 "outcome": "passed", "fingerprint": "6f4fa739f384298aeb6c6bd625235c18", "duration": 0.0013929, "config": "607ce734...",
 "runtime": "5707d5f5...", "epoch": null, "n_units": 1, "n_skeleton": 1, "n_hooks": 0, "n_content": 0, "n_data": 14,
 "n_env": 0, "n_changed_files_proven": 0}
```

### Code reads used by several entries

```
node/bin/detjs.js:13     usage: detjs vitest|jest|node-test|mocha|bun-test|deno-test|tap|ava|jasmine|uvu [--det options] [runner args]
node/src/vitest/cli.js:114-116   fileParallelism: false, maxWorkers: 1, maxConcurrency: 1
node/src/config.js:7     const DEFAULT_EPOCH = '2025-01-01T00:00:00Z';
go/cmd/fenvix-go/main.go:36-45   case "test": ... case "verify": ...
jvm/agent/.../cli/Main.java:36-64   case "run": ... case "verify": ... usage: fenvix-jvm run [--det] ...
python/detpy/repro.py:88  cmd = [self.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--det", ...]
crates/detpy-py/src/repro.rs:425,441-448   next: 1 ... next_seed(): counts up to max_seeds, no persisted state
.github/workflows/release-1.yml:63   python: ["3.12", "3.13"];  :101 node-version: "22";  :219 os: [macos-14, ubuntu-24.04-arm]
grep -n 'schedule\|cron' .github/workflows/*.yml -> go-nightly-real-clock.yml:15-16 only
grep -rn 'det-outcomes\|det-order' node/src node/bin -> no match
grep -rn escalat crates python node/src go jvm/agent -> no match
find engine fenvix-app -name action.yml -o -name action.yaml -> none
ls prompts/ -> COMMON, P-001..P-033, P-035, P-036, R-001, R-010, README, REVIEWER (no P-034, no other R-*)
```

## How the entries were built

* Part A ("Done means" versus the promise): one entry per place where the prompt or the ROADMAP exit asked for less
  than the promise needs (Python only, pytest only, Linux only, serial only, on a branch, measured with a model,
  target lowered). Examples: PROC1-001, -003, -029 to -031, -076, -082, -083, -098, -107 to -112, -149.
* Part B (notes never closed): every "not done", "known limit", UNKNOWN, reviewer NOTE and FIX item in the reports
  listed in the task was traced to release-1. Those fixed are in the list above ("NOT gaps"); the others are entries.
* A limit documented in docs/LIMITS.md or docs/NODE.md with no entry in brain DECISIONS.md is listed as a gap. The
  only exclusions found in DECISIONS.md that touch these blocks are: "sell as debugger, not finder" (Block 2 claims
  withdrawn), "Blacksmith side-by-side later" and "engine on the customer's CI: option later" (PROC1-161, DECIDE).
