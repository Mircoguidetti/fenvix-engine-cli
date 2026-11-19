PARTIAL: mean share of test time reused with proof on dependency-only commits {D}% with the fixed prototype (today's engine {T}%), over the same 130 pairs; mean of repository means {DR}%, pooled test time {DP}%; 0 wrong over {VD} verified reuses, 2 of which could have exposed a wrong reuse; historically broken tests UNKNOWN (MEASURED unless marked)

# Dependency-update verdict, second report: review R-020 fixed and the measurement re-run

Follows `REPORT.md` (P-028, PARTIAL 39%) and review R-020 (`claude/review-r020`,
`sessions/2026-11-19-review-dep-verdict/REPORT.md`, FIX 5). The prototype stays behind `--det-cache-dists`, except for
one fix the review found outside the flag (O1), which changes the engine's default cache. That change is described
under "What changed in the default engine".

## Verdict against the bar (P-028)

| criterion | bar | result | label |
|---|---|---|---|
| mean share of test time reused with proof, dependency-only commits | YES ≥ 50%, NO < 25% | **{D}%** mean over 130 pairs; {DR}% mean of the 10 repository means; {DP}% of all pooled test time | MEASURED |
| same with today's engine (one digest of the whole environment) | (comparison) | {T}% over pairs; {TR}% mean of repository means; {TP}% pooled | MEASURED |
| wrong reuses | 0 over ≥ 5,000 verified | **0 wrong, 0 flaky over {VD}** verified prototype reuses (today's engine: 0 over {VT}). **2 informative cases** (see below). | MEASURED, 2 informative cases |
| historically broken tests inside the affected set | 100% | **UNKNOWN**: not met, not failed. The tests that broke in the projects' own CI after a bump are not known (logs unreadable, see `REPORT.md` step 4). In our own runs, {BR} of {BR} tests that passed at P and failed at C were rerun, but this is true by construction once 0 reuses are wrong. | UNKNOWN |

Why PARTIAL: the per-pair mean sits between the NO line (25%) and the YES line (50%). The other two means do not:
- the mean of repository means is {DR}%, near the NO line;
- the pooled share is {DP}%, under it.

The per-pair mean gives most weight to the repositories whose old commits still install (esphome, moto, community.general).
In 5 of the 10 repositories the engine refuses almost every test for reasons unrelated to dependencies: the share is
about 0% in both modes (airflow, litellm, mlflow, prefect, transformers).

What the 0-wrong row is worth (review M1, re-derived with `rederive.py` on the new rows):
- Only **2** of the verified reuses could have exposed a wrong reuse. These are the tests with a recorded result at P
  whose fresh outcome at C differs: the moto `6e705a82e3` boto3 tests (`test_opsworks/test_layers.py`, 2 tests). The
  first report had a third, `test_sqs_integration.py::test_invoke_fake_function_from_sqs_queue`; in this run it was
  not recorded at P (refused after an earlier Docker test in its process, see the prefix rule below).
- A rule with no dependency check at all ("reuse every recorded result") would make {NULLN} reuses here with 2 wrong
  ({NULLP}%). The rule-of-three bound ({R3}%) is therefore a property of how rarely bumps change outcomes in this
  sample, not of the per-distribution rule. It is dropped from the verdict.
- The evidence that the rule itself is sound is the review's 4 cases and the tests below: each one fails on the
  prototype of the first report and passes now. That is evidence about known holes, not a bound on unknown ones.

## What R-020 found and what changed

| # | wrong reuse (review) | fix | its test (fails before the fix, passes after) |
|---|---|---|---|
| H1 | `lib`'s version, memoised by `helper` during `test_a`, used by `test_b` without any event | **prefix rule**: every input of a test, fixture or collection that ran earlier in the same process is an input of every later test | `test_version_answer_memoised_by_an_earlier_test` |
| O1 | the same with a repository data file, without the flag (in the engine's default cache) | same rule, in both modes | `test_repository_file_memoised_by_an_earlier_test` |
| H2 | `ns.extra` added to a namespace package by a distribution the test never loaded | a submodule lookup under a site directory depends on the listing of each directory of its parent's `__path__` (`l/` identity files, rewritten from the directory at every session start). A listing of a directory under a site directory depends on the listing itself, not on the distribution that owns its other files. | `test_namespace_subpackage_added_by_a_bump` |
| H3 | `.pth` startup code of a distribution no test imports | every test depends on the `.pth` files of the site directories (`@pth`: name and content digest, in the order `site.py` runs them) | `test_pth_startup_code_of_a_distribution_no_test_imports` |
| H4 | a library `dlopen()`ed from C during a test | `/proc/self/maps` is read after every test, not only after a load Python can see | `test_native_library_dlopened_lazily_by_an_extension` |

The review's test file and `rederive.py` are copied unchanged (`tests/test_review_r020_dep_verdict.py`,
`sessions/2026-11-19-review-dep-verdict/rederive.py`). I checked each test against its own fix: with only that fix
reverted, it fails, and with all fixes it passes. For H1 and O1 the shared fix is the prefix rule.

The prefix rule covers every kind of input, not only the two the review tested. Same principle: whatever an earlier
test read can sit in memory. Extra tests in `tests/test_dep_verdict_r020_fixes.py`, each failing without its fix:
- `test_code_memoised_by_an_earlier_test`: the O1 hole with a code change. `test_b` never executes the changed function;
  `test_a` executed it and memoised its result.
- `test_environment_variable_memoised_by_an_earlier_test`.
- `test_refusal_of_an_earlier_test_is_carried`: an earlier test read `/proc` (an input the engine refuses to record) and
  memoised it. The later test cannot be proven either, so it is not cached.
- `test_listing_of_a_directory_another_distribution_fills`: H2 through `os.listdir`. The listed directory belongs to one
  distribution; a second one adds a file to it.
- `test_a_file_an_earlier_test_wrote_and_read_back_does_not_refuse_later_tests`: guards against an over-refusal I found
  while measuring (below).
- Two more tests check the rule's boundaries: only tests that ran *before* are carried; identity files follow the
  environment.

Suite: 164 passed, 6 skipped (MEASURED, this container, Python 3.13).

### What changed in the default engine (O1), and what it costs

O1 is a wrong reuse in the engine's default cache. Fixing it changes the default behaviour, which P-028 had asked not
to touch. This task asks for every wrong reuse to be fixed, so the change is in, in its own commits (`8896c36`,
`a4f35f0`, `9e0d005`). What it means:
- A test now reruns when anything a test before it in the same process depended on changed.
- 12 existing proof-cache tests asserted the opposite: a test that ran *after* a changed or refused test in the same
  process was still reused. Each was rewritten to keep its original check, with the unrelated test placed before the
  changed one, and each now also asserts that a later test reruns.

Cost on these 130 pairs: small (next section), because a dependency-only commit changes no repository code. Cost on
ordinary commits: **UNKNOWN**, and probably much larger:
- An edit to one function reruns every later test of the process that ran after the first test that executed it.
- An edit to the module body of a test file reruns every test of the process: test modules are imported at collection,
  before every test.
- How far this moves the market test's skip share depends on how many tests share a process (per test file in the
  harnesses, the whole suite in a plain `pytest` run). It needs a re-run of the market test before any number on
  ordinary commits is used again.

Recorded entries also grow with the position of a test in its process: it carries the inputs of every test before
it. In the harness (one process per test file), the measured costs per test process, median / p90 over the same
pairs:
- identity keys per test (mean per process): 42 / 269 → {KEYS}
- record time per process: 0.095 / 1.41 s → {REC}
- check time per process: 0.003 / 0.010 s → {CHK}
- distribution index and identity files at session start: 0.105 / 0.41 s → 0.140 / 0.47 s

These runs mix Actions runners and this container, both before and after, on the same pairs (MEASURED).
The check stays in milliseconds; the recording cost is up by about 45% at the median.

For a whole suite in one process, entry size grows quadratically with the number of tests: ESTIMATED, not measured.

## Numbers

Same 130 pairs, same sampled test files (replayed from the first report's rows with `pairs.py --plan
harness/dep_verdict/plan-report2.json`), same verification:
- every reuse is compared with a fresh run;
- a mismatch is run once more to tell wrong from flaky.

Where the pairs ran:
- Actions run dv6 (66 pairs);
- Actions run dv7 (esphome, 23 pairs);
- this container (moto and community.general, 41 pairs, `results/local5/`).

Engine `9e0d005`. dv4 and dv5 were cancelled while queued. One dv5 job had already committed one mlflow pair
(`results/dv5/`); dv6 measured the same pairs, and dv5 is not used.

{TABLE}

Other cuts (MEASURED):
- On the {NE} pairs where the installed environment did not change: D = T = {DNE}%. On the {NC} pairs where it
  changed: D = {DC}%, T = 0%.
- On the {N50} pairs where at least half of the test time is cacheable: D = {D50}%, T = {T50}%.

### Against the first report, pair by pair (same rows)

Reuses lost or gained against the first report, with the reason (MEASURED, `report2/delta.py` on the same pairs and test files):

{DELTA}

- **Lost** (all through the prefix rule). An earlier test in the same process was refused, so later tests are not
  recorded:
  - transformers: `/proc/mounts` and a `g++` subprocess from `torch._inductor`;
  - pydantic-ai: a `git` subprocess from `logfire`, a loopback connection;
  - esphome: `/proc/<pid>/cgroup`;
  - moto: `/proc/self/task/.../children`, the Docker socket;
  - community.general: a connection.

  This is the rule working as intended: a memoised answer from that read would be an input nobody recorded. In test
  time the loss is small (seconds per repository).
- **Gained**: not from the fixes. The first report's rows still carried the two harness effects it described itself:
  - the per-run `CP_TIMES_OUT` path in dv1 (`env: *` misses: community.general, esphome);
  - the `.detpy/` listing in the pydantic-ai repository root.
- **Fixed during the measurement**:
  - Problem: the first version of the prefix rule (`8896c36` + `a4f35f0`, run dv4 locally, results not used) also carried
    "reads a file another test wrote" refusals. A test that writes a file in the repository and reads it back refused
    every test after it: 90 tests in one community.general pair.
  - Why the refusal is not needed for a carried read: the writers of such a file ran before the later test, and
    their inputs are carried too.
  - Fix: carried reads are credited to the earlier contexts (`9e0d005`, with a test). dv4 and the local runs were
    restarted with it.

## Label corrections from the review (applied here)

- **0 wrong**: "MEASURED, 2 informative cases" (the first report's row should read "MEASURED, 3 informative
  cases"). The rule-of-three bound is dropped from the verdict; it is shown above next to the null rule's error rate.
- **100% of historically broken tests**: UNKNOWN, not met and not failed. "7 of 7 inside" in the first report was
  true by construction:
  - "inside" was computed as "not reused";
  - 4 of the 7 were never cached;
  - 2 were network failures not tied to the bump.

  This run has 5 such tests, the same kind.
- **Finding 1 of the first report** ("the per-distribution rule is sound in this sample") is withdrawn. The sample
  could not show a wrong reuse: only 3 cases in it could, and a rule with no dependency check would have scored 0.014%.
  The rule had 4 holes (H1 to H4) that the sample did not exercise. They are closed now. What remains is listed below.
- **Pairs listed**: `commits.json` lists **288** pairs, not 298:
  - 9 repositories × 30, plus community.general 20 and pydantic-ai 28;
  - not measured: **158**, not 168;
  - "not reached within the runner budget": 85, not 95.

## What is still not proven (design analysis; frequency UNKNOWN)

A confident wrong reuse is still possible in these cases. Each is outside what a Python-level recorder can see, or a
property of reuse itself:
1. **Order dependence through reuse.** A reused test does not run, so it leaves no state for the tests after it. Suppose
   test b depends on a side effect of an earlier test a, and b reran alone while a was reused. b's new result then
   holds for "a did not run", while a fresh full run has a run before b. Pre-existing; the same as LIMITS O4 (order
   dependencies).
2. **C code that opens files or libraries and closes them within one test.**
   - `fopen()` from C raises no audit event: this is the S1 limit, and it is pre-existing for every file.
   - A library `dlopen()`ed and `dlclose()`d before the end of the test leaves no trace in `/proc/self/maps`.

   Both need a syscall-level view of the test process itself. Children are already followed with strace.
3. **`/proc` reads in global contexts** (startup, between tests, import time) are still tolerated, as before. The
   prefix rule carries a test's `/proc` refusal, but this pre-existing global exception is unchanged.

## What I decided

- The prefix rule applies to every input kind and to collection and import-time contexts too. A narrower rule (data
  only, or test contexts only) would leave the code and import-time forms of O1 open. The tests above show they are
  real.
- H4: read `/proc/self/maps` after every test (the review's suggestion). Its cost is inside the record-time figure
  above.
- H2: exact directory listings, not ownership by RECORD: the import system and `os.listdir` see listings.
  - `__pycache__` is left out: no installer writes it.
  - A site directory's own root is still the whole set of distributions (`@all`), as before.
- esphome moved twice between this container and Actions because of runner congestion. All 23 of its pairs in
  these numbers ran on Actions (dv7). The two pairs finished in this container before the move are not used.

## Links

- Branch `claude/dep-verdict-abjcfw`:
  - fixes `8896c36`, `a4f35f0`, `9e0d005`;
  - review tests and `rederive.py` copied from `claude/review-r020` (`1cd0db8`).
- Results:
  - `harness/dep_verdict/results/dv6/` (Actions run 44487509172);
  - `harness/dep_verdict/results/dv7/` (Actions run 44501032668);
  - `harness/dep_verdict/results/local5/`.
- Plan of the re-measurement: `harness/dep_verdict/plan-report2.json`.
- Reproduce:
  - `python3 harness/dep_verdict/analyze.py harness/dep_verdict/results/dv6 harness/dep_verdict/results/dv7 harness/dep_verdict/results/local5 --commits harness/dep_verdict/commits.json`;
  - `rederive.py` on a directory with `results/dv3` = dv6 + dv7 and `results/local` = local5;
  - `sessions/2026-11-18-dep-verdict/report2/`: the scripts behind this report (`mkbase.sh` builds that
    directory, `fill.py` fills the numbers, `delta.py`, `nc.py` and `cost.py` compare with the first report's
    rows at `0b87033`, `cmp.py` gives pair by pair); their paths point into the session container: `/tmp/claude-0/cut` is
    `git archive 0b87033 harness/dep_verdict`).
