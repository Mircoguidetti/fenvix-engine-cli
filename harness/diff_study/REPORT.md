# Execution diff study: base vs head of merged PRs under `--det`

Question: run the base and the head of real merged pull requests under `--det`
(same seed, same order), compare the per-test traces. Is the result clean
enough to be the center of a product ("execution diff", Move 1 of
`sessions/2026-11-16-fable-olix-moves/REPORT.md` in the brain repository)?

Engine: detpy `0aef0ae` (branch `claude/gracious-rubin-eyswxd`), wheel built in
the workflow. All runs on GitHub Actions (`ubuntu-latest`, Python 3.12),
workflow `.github/workflows/diff-study.yml`, runs 2 (PRs, mutants), 3 (survivor
re-check) and 4 (more PRs, see Caveats). Raw data: `results/prs/*.json.gz`,
`results/mutants/*.json.gz`; aggregate: `results/summary.json` from
`analyze.py`. Every number is MEASURED on these runs unless labelled otherwise.

## Verdict: NO-GO as the product center on today's trace

The diff is clean, and it is clean for the reason that makes it blind. detpy's
trace records what a test *consumes from the environment* (clock, random,
entropy, file system, threads), not what the code *does*. Only 2.52% of tests
carry any event beyond the outcome and the end-of-test random-state digest.
"Identical trace" therefore mostly means "nothing to compare", not "this change
provably did not alter what the test executes", which is the promise of Move 1.

* 30,461 tests executed code their PR changed. With a stable site identity
  (function + ordinal), **0** of them show a stable divergence whose first event
  is in a changed file.
* 192 mutants in covered code survive the suite. The trace diff flags **2**
  (1.0%), and both are thread-interleaving noise in an unrelated test: **0**
  real catches. A prototype return-value event flags **31** (16.1%).
* On the PRs, the same return-value event shows a stable change in 1,049 tests;
  all 1,049 have an identical detpy trace.

What works, and is worth keeping:

1. **Stable site identity is a must and is cheap.** Line shifts (`path:line`)
   cause 335 of the 416 stable divergences (80.5%); function + call ordinal
   removes all 335 and nothing real is lost.
2. **The noise floor is low.** 99.36% of tests are identical base vs base;
   no-op controls flagged 0 trace changes in 6 of 6 repositories.
3. **Environment drift is caught and located.** The only PR with stable
   divergence after the site fix (isort-2731, "Small cleanup before release")
   changed `uv.lock`; the diff showed 81 tests whose first diverging event is a
   `time.perf_counter` call inside `site-packages/hypothesis`, i.e. a dependency
   upgrade changed what the tests execute. That is a correct, useful verdict.

Recommendation: keep "execution diff" as a feature (dependency/environment
drift, and "certified: fails on head, passes on base, same seed" for red tests,
which this study did not need to test), not as the center. Re-open it as a
center only after the engine records behaviour events (return values, project
call sequence) with function + ordinal sites and a no-op-control noise floor;
then re-run this study (`run.json`, one push). Bar for GO (ESTIMATED, my
proposal): at least 30% of surviving mutants flagged with 0 control flags, and
at least 12 of 15 refactor PRs with zero stable divergence.

## Headline numbers (42 PRs, 17 repositories, 120,811 common tests)

| # | Question | Result |
|---|---|---|
| a | base vs base: identical fingerprints | 119,737/120,510 = **99.36%** (tests with informative events: 2,487/3,008 = 82.68%) |
| b | base vs head: identical fingerprints, `path:line` sites | 120,099/120,811 = **99.41%**; per-PR median 99.88%, worst PR 76.96% |
| b | same, function + ordinal sites | 120,434/120,811 = **99.69%**; per-PR median 99.89%, worst 80.57% |
| c | diverging tests whose first diverging event is in a PR-changed file | all divergences 356/712 = **50.0%**; stable divergences 335/416 = **80.5%**, all 335 line shifts only; with function + ordinal 0/81 |
| d | refactor PRs with zero divergence | raw **1/15**; zero *stable* divergence: 10/15 (`path:line`), **14/15** (function + ordinal) |
| e | surviving mutants flagged by the trace diff | **2/192 = 1.0%**, both noise (0 real); return-value probe 31/192 = 16.1% |
| - | tests whose trace has any event beyond outcome + end random state | 3,039/120,811 = **2.52%** |
| - | tests that ran PR-changed code / of them diverging stably after the site fix in a changed file | 30,461 / **0** |

## Results

### (a) base vs base

Two `--det` runs of the base commit: 119,737 of 120,510 tests (99.36%) have the
same fingerprint. The 773 that differ are concentrated: attrs 646 (Hypothesis
property tests), structlog 76, werkzeug 17, click 13, others 5 or fewer. Their
traces contain random and time events (random + time 402 tests, random only
252, entropy + random 106, file-system 5). Among the 3,008 tests whose trace
holds anything beyond outcome and end random state, 82.68% are identical: the
noise is small in count because most traces are nearly empty, not because
every recorded source is controlled. Outcome changed base vs head: 0 tests.

### (b) base vs head, and site identity

| site identity | identical base1 vs head1 | stable change (both pairs self-consistent) | tests noisy in either pair |
|---|---|---|---|
| `path:line` (detpy today) | 120,099 (99.41%) | 416 | 1,779 |
| function + ordinal | 120,434 (99.69%) | 81 | 1,779 |
| function only | 120,434 (99.69%) | 81 | 1,779 |
| no site | 120,438 (99.69%) | 81 | 1,769 |

13 of 42 PRs show zero divergence under any identity; 31 of 42 show zero
stable divergence under `path:line`. One PR (packaging-1542, 63,809 tests)
holds 53% of all common tests; the per-PR medians above are the fairer view.
Function + ordinal is as good as dropping the site entirely on this sample and
keeps a usable location for the reader, so it is the identity to adopt.

### (c) Where the first diverging event is

Of 712 tests diverging base1 vs head1 (`path:line`):

| location of first diverging event | all (712) | stable (416) | noisy (296) |
|---|---|---|---|
| PR-changed file | 356 | 335 | 21 |
| end-of-test random-state digest | 203 | 74 | 129 |
| unchanged source file | 71 | 0 | 71 |
| `site-packages` | 52 | 7 | 45 |
| unchanged test file | 28 | 0 | 28 |
| stdlib | 2 | 0 | 2 |

Event source of the first diverging event: time 396, random 190, entropy 114,
file system 12. Every one of the 335 stable "changed-file" divergences is a
call-site line shift with the same event value (for example `time.time` at
`src/click/_termui_impl.py:120` on base and `:106` on head, value 1000 on both).
With function + ordinal the stable divergences are 81, all in one PR
(isort-2731: 74 end random state, 7 `site-packages/hypothesis`), caused by the
dependency upgrade in `uv.lock`. So the "50% in changed files" of the raw
diff is the line-number artefact, not behaviour.

### (d) Refactor PRs

15 PRs flagged as refactors by title (attrs 2, click 3, jinja 1, marshmallow 3,
structlog 2, more-itertools 3, isort 1; no repository used a refactor label).

| | zero divergence | zero stable divergence |
|---|---|---|
| `path:line` | 1/15 | 10/15 |
| function + ordinal | 1/15 | 14/15 |
| return-value probe | - | 9/15 |
| call-sequence probe | - | 9/15 |

Raw zero-divergence is 1/15 because base-vs-base noise (attrs Hypothesis tests,
structlog, click thread test) shows up in almost every PR: a product must
subtract a measured noise floor (two runs per side, or no-op controls). After
that and the site fix, the trace calls 14 of 15 refactors clean; the exception
is isort-2731 (dependency upgrade, a real change). The return-value probe sees
behaviour moving in 6 of 15 "refactors"; some are intended (click-3767
"Refactor pager stream handling": 83 tests; more-itertools-1261
"Fix/simplify"), so for a behaviour event the refactor number is a lower bound
of cleanliness.

### (e) Surviving mutants

Mutation pass (run 2): 6 repositories with results (arrow, boltons, click,
marshmallow, sqlparse, toolz) plus structlog; line-preserving operator and
constant flips on covered lines, 200 per repository. Status: killed 1,102,
survived 192, timeout 5, incomplete 51 (all structlog), one shard install
failure. Re-check (run 3): each of the 192 survivors re-run on a fresh runner
next to 3 no-op controls (same file touched, content unchanged); all 192
survived again and all 18 controls survived.

| signal (beyond the controls' noise floor) | survivors flagged | raw, before the noise floor |
|---|---|---|
| detpy trace fingerprint | **2/192 = 1.0%** (both noise) | 2 (run 2: 19) |
| prototype: return values of project functions | **31/192 = 16.1%** | 76 |
| prototype: sequence of project functions called | 22/192 = 11.5% | 22 |
| prototype: set of project files executed | 3/192 = 1.6% | 3 |
| any prototype signal | 31/192 = 16.1% | - |

Per repository (survivors; trace / return-value flags): arrow 27 (0/0), boltons
52 (2/7), click 45 (0/7), marshmallow 16 (0/4), sqlparse 30 (0/11), toolz 22
(0/2). The 2 trace flags are `tests/test_socketutils.py::test_socketutils_netstring_timeout`
in boltons for mutants in `listutils.py` and `strutils.py`: the first
diverging event is a `time.time` call whose thread index swaps (thread 1 at
`socketutils.py:459` vs thread 0 at `socketutils.py:389`), unrelated to the
mutated file; in run 2 the same pattern produced 3 boltons flags and 16 click
flags (`test_tempdir_isolation_is_thread_safe`, `os.scandir` thread index).
Thread interleaving is the remaining source of noise in the L1 trace.

Which event types would raise it: none of the event types detpy records today
(time, random, entropy, file system) moved for a real mutant. A return-value
event would have raised 31; the call sequence adds nothing beyond it on this
sample (every call-flagged survivor is also return-flagged). The return-value
probe has its own noise: base vs base it differs on 1,018 of 120,811 PR tests
(0.84%, vs 0.64% for the trace), and the boltons controls flagged 4 tests, so
it needs the same two-runs-or-controls floor.

## Method

1. **PR selection** (`select_prs.py`, GitHub API). From the fast suites of the
   mixed round, 17 Python repositories (attrs, click, flask, jinja, werkzeug,
   marshmallow, arrow, structlog, more-itertools, sqlparse, isort, toolz,
   boltons, pygments, packaging, jsonschema, rich): merged PRs since
   2024-01-01, human authors, changing at least one non-test `.py` file
   outside docs. Refactors flagged by label or title keyword (refactor,
   cleanup, simplify, tidy, restructure, rewrite, "move ... to"). Order:
   refactors first (at most 20), then round-robin by repository, newest
   first; 80 candidates saved in `results/prs.json`. `analyze.py --n 50` uses
   the first 50 successful PRs by that order.
2. **Per PR** (`run_pr.py`). Base = first parent of the merge commit, or the
   commit before a squash/rebase whose diff equals the PR's file list; head =
   the merged commit. Fresh venv per commit, project installed with the detpy
   wheel. `pytest --det` (seed 0, collection order) at base twice and head
   twice on the same runner. Per test: the four outcomes and the four
   fingerprints as an equivalence pattern (`AAAA`, `AABB`, ...). For every test
   with base1 != head1, the first diverging event (detpy's verifier rule: first
   index where the event lists differ) and its location. "Stable" change:
   base1 = base2, head1 = head2, base != head.
3. **Site identity, offline** (`common.py`). Each event's `path:line` is
   mapped with that commit's AST to function qualname + ordinal of the call in
   the function, function only, or dropped; fingerprints recomputed from the
   stored events. No engine change.
4. **Prototype probe** (`probe/diffprobe.py`, loaded with `-p diffprobe` next
   to `--det`, `sys.monitoring`; not part of detpy). Per test: `calls`
   (sequence of project functions entered, by qualname), `rets` (sequence of
   function + summary of the returned value: type, length, short hash of a
   repr with memory addresses removed), `files` (set of project files
   executed). Used to know which tests ran PR-changed code and to estimate
   what a behaviour event type would add.
5. **Mutants** (`mutate.py`). Per repository at a pinned commit: line coverage
   once; line-preserving mutants on covered lines of non-test files
   (`<`/`<=`, `+`/`-`, `==`/`!=`, `and`/`or`, `True`/`False`, small numeric
   constants), shuffled with a fixed seed, 4 shards of 50. Each mutant: one
   `--det -x` run against two unmutated `--det` baselines. Killed: a
   baseline-passing test fails. Survived: every test keeps its outcome; then
   flagged if a test whose fingerprint (or probe digest) was identical in
   both baselines changes. Re-check: survivors re-run with 3 no-op controls;
   a flag counts only on tests no control flagged.

## Caveats

* **42 PRs, not 50.** Run 2 ran for 3 hours and was cancelled with 43 of
  its 80 candidates done (42 ok, 1 collection error on flask-5799). Run 4
  re-runs 16 more candidates from the saved list; at the time of writing 6 of
  its 16 jobs had finished and the other 10 had been queued for over 40
  minutes with no runner (every workflow in the repository was queued). When
  run 4 publishes, `python3 analyze.py` picks the first 50 by priority and
  rewrites `summary.json`; the coordinator can check whether the headline
  numbers move. With 30,461 tests running changed code and 0 stable real
  divergences, 8 more PRs cannot turn the verdict (ESTIMATED).
* **Sample.** Small and medium pure-Python libraries with fast suites: no
  services, little I/O, no TypeScript. Suites with more I/O would carry more
  events and could look both richer and noisier (UNKNOWN).
* **Refactors by title only**; several change behaviour on purpose.
* **Equivalent mutants.** Some survivors cannot be detected by any diff. The
  share is commonly put at 5 to 25% of survivors (ESTIMATED, literature, not
  measured here), so 16.1% is a floor for the return-value event, and 1.0%
  for the trace is not explained by it.
* **Mutant coverage of repositories:** jinja gave 0 candidates (coverage did
  not map the installed package's files) and structlog 0 survivors (51
  "incomplete": a stable test missing from the mutant run). 192 survivors
  from 6 repositories, above the 100 the task asked for.
* **Machines.** base and head of a PR ran on one runner; the survivor
  re-check on a different runner from the first pass. Cross-machine noise of
  a single comparison is not measured.

## Files

* `select_prs.py`, `run_pr.py`, `mutate.py`, `common.py`, `probe/diffprobe.py`:
  the study.
* `plan.py`, `run.json`, `.github/workflows/diff-study.yml`: the runs (a push
  that changes `run.json` starts one; `prs.reuse` + `prs.indices` re-run
  chosen candidates; `mutants.recheck` re-checks survivors with controls).
* `analyze.py`: aggregate; `python3 analyze.py` rewrites `results/summary.json`.
