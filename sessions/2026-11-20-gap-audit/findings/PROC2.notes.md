# PROC2 notes: process gaps, Python "proof" lineage

Audited branch: fenvix-engine-cli `claude/release-1` at 529c1609 (worktree /home/user/audit/engine), wheel
`/home/user/audit/build/dist/detpy-0.1.0-cp39-abi3-linux_x86_64.whl` installed with `--no-deps` in a uv venv
(Python 3.13.18, pytest 9.2.0, pytest-xdist 3.8.0) at /home/user/audit/work/PROC2/venv. Tests were run from a copy of
the tree's `tests/`, `python/`, `runner/` in /home/user/audit/work/PROC2/eng (extension copied into python/detpy as
the release-1 CI does). Nothing was changed in any repository.

## (b) Evidence appendix (commands run, trimmed real output)

### E1. Audit reruns absent on release-1 (PROC2-001, 002, 006)

```
$ cd /home/user/audit/engine
$ grep -rn "det-cache-audit\|det_cache_audit" --include=*.py --include=*.rs --include=*.js --include=*.md . | grep -v "^./target\|^./sessions\|review-input"
(no output)
$ ls crates/detpy-core/src/
backend.rs cache.rs cassette.rs deps.rs distfiles.rs event.rs fingerprint.rs lib.rs node_session.rs order.rs
proof.rs record.rs recorder.rs reexec.rs repro.rs schedule.rs shared.rs trace.rs treehash.rs verify.rs      (no audit.rs)
$ git -C /home/user/fenvix-engine-cli rev-list --count origin/claude/release-1..origin/claude/audit-reruns
46
$ grep -n audit runner/fenvix-run
(no output)
```

### E2. `--det-cache=URL` is silently a local directory (PROC2 shared-cache entries)

```
$ cd /home/user/audit/work/PROC2/urlproj   # one file test_a.py, no service listening anywhere
$ python -m pytest -q -p no:cacheprovider --det --det-cache=http://127.0.0.1:59999/proj test_a.py
reused 0 result(s) with proof, ran 1, recorded 1 ...
receipts: /home/user/audit/work/PROC2/urlproj/http:/127.0.0.1:59999/proj/receipts.jsonl
1 passed in 15.45s
$ find . -maxdepth 4 -not -path "./.detpy/*"
./http:  ./http:/127.0.0.1:59999  ./http:/127.0.0.1:59999/proj  .../proof-cache.json  .../receipts.jsonl  .../quarantine.json ...
$ (third run) reused 1 result(s) with proof, ran 0, recorded 0      # reused from that local directory, no network
$ grep -n "remote_cache\|http" python/detpy/proofcache.py python/detpy/_proof.py python/detpy/plugin.py python/detpy/_level0.py
(no output: the plugin never imports detpy.remote_cache; crates/detpy-core/src/shared.rs has 0 occurrences of "http")
```

### E3. Wrong reuses on the release-1 wheel in classes review R-008 reported "fixed" (runtime identity)

Each case: record with `--det --det-cache=DIR`, change one thing outside the repository, run again with the cache,
then plain pytest (`-p no:detpy`) on the same state. The engine's runtime digest stayed `fd9e861b...` in every case.

```
A  unowned package directory in site-packages (vendored_proc2/__init__.py VALUE 1 -> 2)
   run2 (cache): reused 1 result(s) with proof, ran 0 ... 1 passed      plain: 1 failed
A2 file inside an installed distribution, not in its RECORD (xdist/_proc2_extra.py, other size, later mtime)
   run2 (cache): reused 1 result(s) with proof, ran 0 ... 1 passed      plain: 1 failed
D  CPUs visible (test asserts len(os.sched_getaffinity(0)) >= 2; run 2 under `taskset -c 0`)
   run2 (cache): reused 1 result(s) with proof, ran 0 ... 1 passed      plain taskset: 1 failed
E  module on PYTHONPATH outside site-packages and the root (helper_proc2.py VALUE 1 -> 2)
   run2 (cache): reused 1 result(s) with proof, ran 0 ... 1 passed      (plain: assert 2 == 1 fails)
F  LD_PRELOAD shim replacing getuid() (test asserts os.getuid() == 0)
   run2 (LD_PRELOAD, cache): reused 1 result(s) with proof, ran 0 ... 1 passed      plain LD_PRELOAD: 1 failed
G  PYTHONWARNINGS=error (test calls a function that warns DeprecationWarning)
   run2 (cache): reused 1 result(s) with proof, ran 0 ... 1 passed      plain: 1 failed
```
Scripts: the two shell blocks are reproduced in section (c) "How to re-run E3".

### E4. Reviewer files on the release-1 wheel

```
tests/test_absent_inputs_r019c.py (R-019c E-1..E-4, serial + -n 2)        30 passed in 160.33s
tests/test_review_r020_dep_verdict.py + test_review_r020b_dep_verdict.py  12 passed in 93.02s
tests/test_review_r008d.py with the unconditional skip removed            1 failed, 9 passed in 83.03s
   FAILED test_startup_git_describe_is_an_input: first run "not cacheable: subprocess 1" (the test expects a recorded entry)
tests/test_startup_spawn.py + test_startup_digest.py, skip removed        6 failed, 5 passed, 2 skipped
```

### E5. Order dependence through reuse: a false failure under `--det-cache` (dependency verdict REPORT-2/-3 "Open 2")

```
$ cd /home/user/audit/work/PROC2/idt/O    # state.py: REG = [] ; test_a.py appends to state.REG ; test_b.py asserts state.REG == ["x"]
run1 record:                       reused 0 result(s) with proof, ran 2, recorded 2 ... 2 passed
run2 unchanged:                    reused 2 result(s) with proof, ran 0, recorded 0 ... 2 passed
(edit only test_b.py: a message on the assert and an unused helper)
run3 with the cache:               reused 1 result(s) with proof, ran 1, recorded 0  not reused: code 1  not cacheable: outcome 1   1 failed, 1 passed
run3 truth (fresh --det, no cache): 2 passed
plain pytest:                       2 passed
```
The cache run reports a failure that neither the plain suite nor a full `--det` run has: test_a was reused (not
executed), so the state test_b needs was never created.

### E6. `--det`: the virtual clock after a timed-out wait differs between identical runs (review R-017 "Observations", never looked at)

```
$ cd /home/user/audit/work/PROC2/idt/Q   # test_queue_timeout: queue.Queue().get(timeout=0.5) -> Empty, then time.time()
$ for i in 1 2 3 4; do python -m pytest -q -p no:cacheprovider --det --det-trace=t$i.jsonl test_q.py; done    # 2 passed each
$ python -m detpy verify t1.jsonl t2.jsonl t3.jsonl t4.jsonl
covered by Level 0: 1  not covered: 1  missing: 0  outcome-unstable: 0
reasons: time=1
NOT-COVERED test_q.py::test_queue_timeout  [time] outcomes=passed,passed,passed,passed
    runs 0 vs 1: event #0: time.time @ test_q.py:9 returned different values: "499999262" vs "499999699"
```

### E7. Other runs

```
Python 3.11 + release-1 wheel:  pytest --det --det-cache=DIR test_a.py  => ERROR: --det-cache needs Python 3.12+ (sys.monitoring)
tests/review_r032b + tests/test_r032b_engine.py + tests/review_r032 + tests/test_culprit_keys.py (venv without nose2, zope, django, ward, hypothesis):
   63 passed, 10 skipped, 1 xfailed in 487.00s     (skips: the importorskip of those packages + de_DE locale; xfail: test_pythonwarnings_is_an_input)
wc -l python/detpy/*.py python/detpy/runners/*.py  => 11424 total
```
tests/test_review_r008.py + tests/test_review_r008b.py (release-1 wheel, extension also in python/detpy as in CI):
   12 passed, 5 skipped in 26.51s   (5 skips: "shared-cache Python client not yet ported onto the Rust proof cache")
   -> the 12 identity tests pass against detpy.runtime_id while the same attacks give wrong reuses on the shipped cache (E3)
```

### E8. Runs stopped before they finished (budget stop): partial output only, NOT findings

```
tests/test_review_r023.py + tests/test_review_r023b.py  -k "not test_2b_"   (stopped after 41 tests)
   ...............F.........................          1 F at position 16, name not captured
   The first attempt (all tests, as root) was stopped on purpose before test_2b_* ran: those tests rewrite
   /etc/resolv.conf and /etc/hosts of the shared machine. /etc/resolv.conf and /etc/hosts were checked unchanged.
   The scratch copy lacked harness/parallel_proof when the run started (test_a7 and test_f5v_* import it), so the F is
   probably that import (test_a7 is the 16th test of test_review_r023.py). UNVERIFIED.
tests/test_review_r015.py r015b r017 r017b r009 r009b   (stopped after 16 tests)
   ....F......F....                                    2 F, names not captured; machine load average 25-30. UNVERIFIED
   (test_review_r017.py::test_h2 is the known defective test and was not deselected in this run: one F is probably it).
```

### How to re-run E3 (the wrong reuses in the R-008 classes)

```
. /home/user/audit/work/PROC2/venv/bin/activate          # Python 3.13 + pytest + pytest-xdist + the release-1 wheel (--no-deps)
SP=$(python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")
# A: mkdir $SP/vendored_x; echo "VALUE = 1" > $SP/vendored_x/__init__.py; a test `import vendored_x; assert vendored_x.VALUE == 1`
#    pytest -q -p no:cacheprovider --det --det-cache=../cache ; change VALUE to 2 ; same command ; then `-p no:detpy`
# D: test `assert len(os.sched_getaffinity(0)) >= 2`; second run under `taskset -c 0`
# E: PYTHONPATH=<dir outside the project> with helper.py VALUE = 1 -> 2
# F: gcc -shared -fPIC shim.c (getuid returns 4242); test `assert os.getuid() == 0`; second run with LD_PRELOAD=shim.so
# G: test calls a function that warns DeprecationWarning; second run with PYTHONWARNINGS=error
```
Scratch projects: /home/user/audit/work/PROC2/idt/{A,A2,D,E,F,G,O,Q,R,S}, urlproj, okproj; logs in /home/user/audit/work/PROC2/logs.

## (a) Could not check

* **R-023b on release-1** ("R-023b FAIL (50 tests)" in NOW.md): not established. The run was stopped (see E8). What is
  established by other runs: the 9 absent-input classes through R-019c's file (30 passed, serial and -n 2). Not
  established: test_2a_* (N1), test_2b_* (N2, root only), test_2c_* (N3), test_2d_* (N4), test_2e_* (N5),
  test_3_* of the R-023b file itself (N6), test_f1v/f2v/f3v/f5v (N7-N10), and R-023's 17 tests.
* **R-032b W12 (zope), W13 (Django), W14 (ward), W1 under nose2, and the R-032 nose2 / Django / Hypothesis cases** on
  release-1: a venv with those packages was prepared (/home/user/audit/work/PROC2/venvr) but nothing was run in it.
  Without the packages these cases skip (as they do in the release-1 CI gate, PROC2-109).
* **R-015 F1-F3, R-015b G1-G3, R-017 H1/H3, R-017b F1-F2, R-009, R-009b** reviewer files on release-1: run stopped
  after 16 tests with 2 unexplained F (E8). Not established.
* **R-008 FIX 3 locale categories / locale data** and **R-032 P7** (locale read by C): no `de_DE` locale on this
  machine. By reading, the Rust identity keys the values of TZ/LANG/LC_* and /etc/localtime, not the locale data.
* **R-008b FIX A (sourceless bytecode on an import path) and FIX B (symlinked package directory)** against the shipped
  Rust identity: not probed (only against `detpy.runtime_id`, where the reviewer tests pass).
* **R-008b NOTE 3** (project installed non-editably): listed from the review (PROC2-039), not probed on release-1.
* **R-023b N9 residual** (`request.config.workerinput`) and **N2 residual** (address ordering): listed from the review,
  not probed.
* **Stdlib content not keyed** (PROC2-149): read from the code; not run, because the interpreter's standard library is
  shared with the other agents on this machine.
* **Node side of the same blocks** (detjs shared cache `remote.js`, audit, virtual-day clock): only grepped.
* **fenvix-app**: only `main` was read, and only for the engine pin, the vendored cache service and the audit tables.
* macOS / Windows: no access; from code and CI configuration only.

## Not covered (items of the task not reached; for another session)

Prompts: all nine named prompts were read in full (P-013, P-016, P-018, P-024, P-025, P-028, P-029, P-032, P-033);
P-034 has no file (PROC2-136). Brain documents PRODUCT, ARCHITECTURE, ROADMAP, DECISIONS, NOW, LOG, NUMBERS, COMMON,
REVIEWER: read in full.

Read in full: audit-reruns REPORT, REPORT-2, REPORT-3; review-audit-reruns REPORT; review-shared-cache REPORT;
exact-culprit REPORT-5; review-exact-culprit REPORT-3; dep-verdict REPORT-3; review-dep-verdict REPORT and REPORT-2
(to line 200); parallel-proof REPORT-3; review-parallel-proof REPORT and REPORT-2; review-all-runners REPORT-2 (to
line 144); engine docs/RELEASE-1.md; engine sessions/2026-11-20-release-1/REPORT.md; the head of
origin/claude/all-runners-2 REPORT-2 (to the Jasmine row, plus "Not covered / open").

Only skimmed by keyword (open / not done / UNKNOWN / NOTE / limit), so NOTES and limits in them may be missing from
the gaps file:
* sessions/2026-11-18-review-audit-reruns/REPORT-2.md (R-013b)
* sessions/2026-11-18-shared-cache/REPORT.md, REPORT-2.md, REPORT-3.md, REPORT-4.md, REPORT-5.md
* sessions/2026-11-18-review-shared-cache/REPORT-2.md (R-008b: FIX A, FIX B, ISA section), REPORT-3.md (R-008d: the 7
  proven errors table)
* sessions/2026-11-18-dep-verdict/REPORT.md, REPORT-2.md, INTERMEDIATE-1.md
* sessions/2026-11-18-exact-culprit/REPORT.md, REPORT-2.md, REPORT-3.md, REPORT-4.md, INTERMEDIATE-1.md
* sessions/2026-11-19-review-exact-culprit/REPORT.md (R-019: H1-H5, M6-M8), REPORT-2.md (R-019b: N1-N5 and the
  carried-over rows question, lines 100-150)
* sessions/2026-11-18-rust-hotpaths/REPORT.md, REPORT-2.md, REPORT-3.md, REPORT-R2.md, REPORT-R2b.md, REPORT-R2c.md,
  and the engine's INTERMEDIATE-1.md
* sessions/2026-11-18-review-rust-hotpaths/REPORT.md (R-015), REPORT-2.md (R-015b)
* sessions/2026-11-19-review-rust-r2/REPORT.md (R-017), REPORT-2.md (R-017b)
* sessions/2026-11-19-parallel-proof/REPORT.md, REPORT-2.md (47 KB: the per-repository blocker tables were not read)
* sessions/2026-11-19-all-runners/REPORT.md (per-runner rows), INTERMEDIATE-1.md
* sessions/2026-11-20-review-all-runners/REPORT.md (R-032), REPORT-2.md after line 144
* sessions/2026-11-18-runner-prototype/REPORT.md, INTERMEDIATE-1.md
* sessions/2026-11-18-fable-new-value/REPORT.md (only ideas 1-3 and their validation plans), INTERMEDIATE-1.md
* engine docs/PARALLEL-PROOF-DESIGN.md (68 KB: only the section list and the P6-P8 rows), docs/SHARED-CACHE.md,
  docs/ALL-RUNNERS.md, docs/RUNNER-PROTOTYPE.md (limits sections only), docs/LIMITS.md (ids only)

Not opened at all:
* engine sessions/2026-11-17-cache-proof-step1/REPORT-3.md beyond its headings; brain sessions for cache-proof step 1
  and its reviews R-009 / R-009b (not in the task list, but P-013's fix rounds)
* engine sessions of other lanes present in the tree (go-l0, jvm-l0, review-go, review-jvm): outside this area
* engine tracks/parallel-proof/CI-FACTS.md, tracks/*/ STATUS and gate files, tracks/all-runners-2/gates
* origin/claude/dep-verdict-abjcfw and origin/claude/parallel-proof-3: only their REPORT-3 (identical to the brain
  copy) and the commit lists; tests/test_round4_capture.py of parallel-proof-3 not read
* sessions/2026-11-19-all-runners per-runner documents under engine docs/runners/

Review items not individually traced to a test on release-1 (each needs "is the reviewer's test present, not skipped,
passing"): R-008 FIX 4-6 (service body before auth, token file, empty-input entries: the service file is unchanged
from a20b93d; the client is not ported); R-008b FIX A-B; R-008d errors 1-7 one by one; R-013 defects 1-5 (the code is
absent on release-1); R-015 F1-F4; R-015b G1-G3; R-017 H1-H3; R-017b F1-F2; R-019 H1-H5/M6-M8 and R-019b N1-N5 (finder,
harness tests are outside the gate); R-020 H1-H4/O1 and R-020b N1-N3/O2 (files pass as a whole: 12 passed); R-023
F1-F6 and R-023b N1-N12 (not established, see above); R-032 F1-F8 and R-032b F1-F7 (pytest/unittest/doctest cases
pass; nose2, zope, Django, ward not run).

## (c) For the lead

1. **The largest finding of this area:** blocks recorded CLOSED on pre-Rust branches are not in the release lineage.
   Audit reruns (whole feature), the shared-cache HTTP client, the content-keyed runtime identity of R-008 and the
   R-008c/d start-up rule are absent from release-1, while NUMBERS.md and LOG.md call them closed and
   docs/SHARED-CACHE.md on release-1 still describes them. Six wrong reuses in those classes were reproduced on the
   release-1 wheel (E3).
2. **Reviewer tests that pass without testing the product:** tests/test_review_r008.py / r008b run against
   `detpy.runtime_id`, which the cache key does not use; 15 shared-cache tests and all R-008d / start-up tests are
   unconditionally skipped ("not yet ported"); the release gate installs no Django / nose2 / zope / ward / Hypothesis,
   so those runner tests and reviewer cases skip; one known wrong reuse is a strict xfail (PYTHONWARNINGS).
3. **Claims found false on release-1:** `--det-cache=DIR|URL` (RELEASE-1.md, ALL-RUNNERS.md): a URL becomes a local
   directory (E2). "Same rule for Python, Node and Go" for the virtual-day clock and nightly real-clock run
   (DECISIONS 2026-11-19): Python keys the HEAD commit time and has no real-clock run. NOW.md's "known wrong reuses
   R-019c E-1..E-4 and R-020": fixed on release-1 (30 and 12 reviewer tests pass).
4. **The deployed App pins engine commit a20b93d** (claude/shared-cache, pre-Rust, before the R-008d fix), not
   release-1 (PROC2-021). This overlaps the App area; listed here because it is where the shared cache is "wired".
5. **"Measurement only" blocks counted as product:** exact culprit and dependency verdict have no user-facing
   command, API or App output; both missed their own yes-number (95% / 3 executions; 50%).
6. Two new behaviours reproduced that reports only "stated": a false failure when an earlier test is reused and a
   later one depends on its in-process state (E5), and different traces for two identical `--det` runs after a
   timed-out wait (E6).
7. Entry ids PROC2-001..154 are sequential. Extra fields `prompt` and `block` are set on every entry; `prompt` is
   "none (...)" where no prompt file exists (parallel with proof, Rust port) and "P-034 (missing)" for release-1.
