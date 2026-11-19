DONE: **517 of 532 measured cases have a stated culprit (97.2%)**, and every stated culprit is right: **0 confident wrong**. Counting the 3 round-3 cases that today's environment no longer produces as unknown: 517 of 535 = 96.6%. Round 3 stated 391 of 535 (73.1%). Of the 15 unknowns, 11 carry a suspect, and the suspect is the truth in 11 of 11. Cost: median 11 test executions per case (p90 39) and median 10 s wall per case (p90 37 s). Round 3: median 10 executions, p90 27.

# Exact culprit (idea 2): fix round 4, coverage

Session `2026-11-18-exact-culprit`, round 4. The goal is to raise the share of stated culprits from 73% to at least 85–90% while keeping 0 confident wrong answers.

* **Branch:** `claude/exact-culprit`. `claude/rust-hotpaths-2` is merged.
* **Labels:**
  * MEASURED: my runs in this session.
  * ESTIMATED: my arithmetic or a simulation.
  * DECLARED: a source.
  * UNKNOWN.
* **Machine:** one cloud container, 4 cores, CPython 3.13.18 (step 4: 3.9.25).
  * The population runs had 3 to 5 lanes at once, each running up to 4 replays in parallel, so their wall times are NOISY.
  * The clean timing pass in §4 ran alone.
* **Recompute:**
  * `python3 harness/culprit/round4/aggregate4.py harness/culprit/results` prints every number below; `results/summary4.json` is its output.
  * `round2/aggregate2.py` still runs and writes `results/summary.json`.
  * The round-3 rows moved to `results/round3/`.

## 1. Result against the goal

| criterion | target | round 4 (round 3 in brackets) | label |
|---|---|---|---|
| culprits stated | ≥ 85–90% | **517 / 532 = 97.2%** (391 / 535 = 73.1%) | MEASURED |
| confident wrong | 0 | **0** on 532 cases (0 on 535) | MEASURED |
| unknown | | **15** (144). 11 have a suspect, and it is the truth in 11 of 11 (137 of 137). | MEASURED |
| test executions per case | | median **11**, p90 **39**, max 96 (10 / 27 / 43) | MEASURED |
| wall per case, whole finder | | median **10.1 s**, p90 **37 s**, max 239 s | MEASURED, NOISY |
| replay critical path per case | | median **9.2 s**, p90 **33 s** (every replay in sequence; a parallel batch counts as its longest replay) | MEASURED (sum of measured replays) |

**By kind** (every population re-run, not re-scored):

| kind | cases | stated = right | wrong | unknown (suspect = truth) | executions median (p90) | wall s median (p90) | round 3 stated, median executions |
|---|---:|---:|---:|---|---|---|---|
| a2 placed | 196 | 190 | 0 | 6 (6) | 11 (43) | 11.3 (39) | 135, 9 |
| a2 reland | 196 | 196 | 0 | 0 | 9 (34) | 9.9 (38) | 170, 7.5 |
| b real history | 27 | 27 | 0 | 0 | 30 (45) | 24.4 (53) | 9, 11 |
| c no-code | 35 | 31 | 0 | 4 (no suspect) | 4 (25) | 6.9 (26) | 31 of 38, 4 |
| c data edit | 15 | 15 | 0 | 0 | 4 (6) | 5.4 (10) | 15, 4 |
| d step 4 | 63 | 58 | 0 | 5 (5) | 29 (67) | 14.1 (34) | 31, 26 |
| **all** | **532** | **517** | **0** | **15 (11)** | **11 (39)** | **10.1 (37)** | 391 of 535, 10 |

**Transitions from round 3 (same case ids, MEASURED):**
* a2: 305 stated → stated; 81 unknown → stated; 6 unknown → unknown; none the other way.
* b: 9 stated → stated; 18 unknown → stated.
* The git bisect baselines are unchanged rows from round 3 (they do not depend on the finder).

**The 15 unknowns:**
* **11 hit the red-side budget of 64 replays:**
  * a2 placed (6): more-itertools and sqlparse histories of 160 to 200 commits, culprit placed early;
  * step 4 (5): crom ×3, arrow ×2.
  * The suspect is the truth in all 11.
* **2 inexact rebuilds** (toolz env): the green environment was not rebuilt exactly, as in rounds 2 and 3.
* **2 `csock`** (httpx): an uncontrolled source, as in rounds 2 and 3.

**3 cases no longer produced.** Today's environment does not produce three of the round-3 no-code cases: toolz-env-tz and rich-home ×2. Their drivers found no test that only the change breaks, or that `--det` and plain pytest agree on. All three were "unknown" in round 3, so they are left out of the 532. Counted as unknown, the stated share is 517 / 535 = 96.6%.

## 2. What changed

### 2.1 Engine: `claude/rust-hotpaths-2` merged first

* **One conflict, in `python/detpy/proofcache.py`.**
  * The recorder is now Rust (`CacheSession.record`). This branch's `--det-cache-keys` dump read the old Python recorder's local variables.
  * The dump is ported to Rust: `detpy_core::record::record_session_keys` builds every test's inputs next to the record plan, for any outcome and before the cacheability checks.
  * Python writes the same JSON as before.
  * The dump now also carries the engine's own verdict per test (`not_cached`: None, or why its inputs are no proof). The finder uses this verdict in §2.2.
* **N5 (stale bytecode under `--det`) passes**, since the merge brings the hash-checked bytecode fix. Its expected-failure mark in `review_r019b/conftest.py` is removed. MEASURED.
* **Merge regression found and fixed.** The merged engine no longer imported on Python 3.9 (`ast.match_case` in `_codefacts.py`), which broke every step-4 environment. `_BLOCKS` now uses `getattr(ast, "match_case", None)`. MEASURED: 3.9 runs work again.
* **Engine finding, not fixed (UNKNOWN impact on the cache).** The key does not record a failed import (`try: from pkg import optional`) or the import system's directory reads.
  * MEASURED on a toy project: no `pkg/optional.py` entry appears in the key.
  * A later commit that adds such a module could change the outcome without changing any recorded input.
  * The finder guards against this (§2.2).
  * Whether the proof cache would reuse a stale result in that case was not tested.
  * The same holds for the pytest ini file, which is a session-wide digest, not a per-test input.

### 2.2 Finder: red-side check with key validity (`harness/culprit/finder.py`)

The rule is unchanged from round 3: a commit C is named only if C's parent passes, C fails, and **every commit of (C, red] fails**. What changed is how the later commits are decided.

* **Key validity.** A deterministic run is a function of the inputs its key records (this is the proof cache's premise). A later commit j therefore has the outcome of an earlier run R on the same side (environment, distributions, arguments) when every in-repository input R recorded has the same value at j:
  * blob first, then unit, skeleton or hooks digest via `_codefacts`.
  * Runs used: every replay's own key, plus the CI keys of the side where they are valid there.
* **What this covers, which round 3's footprint vector could not:**
  * a failing run's key lists only what it read before failing. Later changes to code it never reached are inferred (test 6 in §3).
  * every replay adds a key, so one replay decides every commit equal to it on that key's inputs.
* **Guards for what the key does not record.** Any difference in these means no inference:
  * the pytest configuration files at the repository root and the key root;
  * every `conftest.py` and `__init__.py` on the test's path;
  * the names in every directory on the path of each input (new module or package shadowing);
  * the mode of every path whose mode any later commit changes.

  There is also no inference from a run whose key flags an uncontrolled source, or that the engine itself does not treat as a proof. Entropy under `--det-urandom` counts as a proof, as the engine says.
* **Soundness fix.** Round 3 compared only inputs that differ between green and red, and assumed commits between candidates keep the candidate's state. A unit equal at green and red but changed and changed back in between (a fix, then its revert) was invisible to it: a confident wrong answer (§3, test 1). Round 4 checks every later commit against full keys.
* **Parallel replays.** Undecided commits are grouped by their values of every recorded input and replayed 4 at a time.
  * Each replay runs in its own copy of the repository, mounted at the repository's own path in a private mount namespace (`unshare -m`; `common.run_det(worktree=...)`, `common.worktrees`).
  * So each replay sees exactly the paths of an in-place replay: editable installs, keys and runtime identity are the same.
  * The engine's xdist parallel-with-proof (`claude/parallel-proof`) parallelises tests within one session, not commits, so it is not used here.
* **Budget:** 64 red-side replays per case over all restarts (round 3: 6, plus undo commits), beyond the commits that undo C.
* **Order:** groups that hold a commit undoing C come first, then newest first. No predictor of "likely to pass" was found in the data, so none is used.
* **Inference is redone after each batch.** The check stops as soon as every later commit is decided.
* **Fallback search** (`_bisect_all`: the key missed an input): same parallel check and budget, but no key-validity inference, because the key is known incomplete there.

### 2.3 Step 4 (`orderdep.py`)

* Same red-side rule as round 3: the footprint is the repository files the pair imports at red and at the named commit, plus test files, conftests and configuration.
* Replays now run 4 at a time in mounted copies.
* The budget is 64 (round 3: 8).
* The git bisect baseline is not re-run (`--attempts 0`): it does not depend on the finder, and the round-3 rows keep it. The truth scan is re-run.
* Step-4 environments are Python 3.9, where proof keys cannot be written, so key validity does not apply. This is the main reason step 4 still costs a median of 29 executions.

## 3. Adversarial tests (`harness/culprit/round4/test_finder_round4.py`, 9 tests)

Truth in every test is the newest transition (a walk back to the newest passing commit), as in R-019b. MEASURED:

| test | what a careless inference does | round-3 finder | round 4 |
|---|---|---|---|
| 1. caller fix, then reverted (unit equal at green and red) | footprint vector ignores the unit | **confident wrong** | names the truth |
| 2. conftest added later fixes the test | red key never saw a conftest | **confident wrong** | not wrong |
| 3. ini option changed later (`getini`) | ini is not a per-test input | **confident wrong** | not wrong |
| 4. package `pkg/m/` added later shadows `pkg/m.py` | import lookups not recorded | **confident wrong** | not wrong |
| 5. file mode changed later (`os.access`) | modes not in the key | right (mode commits were candidates) | not wrong |
| 6. 8 later commits change code the failing run never reached | | 8 replays needed | stated with **0** red-side replays |
| 7. budget runs out | | | unknown with the right suspect at budget 4; stated at 12 |
| 8. parallel replays equal sequential ones (outcomes and recorded inputs) | | | equal |
| 9. `run_from_key` refuses keys that are no proof | | | refuses |

**Each guard is needed (MEASURED).** I removed one guard at a time and re-ran tests 2 to 5:
* without the configuration-file guard, test 3 is a confident wrong answer;
* without the directory-names guard, test 4 is;
* without the mode guard, test 5 is.

Test 2 is caught by two guards (the conftest file and the root directory names).

**Gates:** `pytest -p no:cacheprovider harness/culprit/review_r019 harness/culprit/round2/test_finder_round2.py harness/culprit/review_r019b harness/culprit/round4` gives **26 passed, 3 failed** in 197 s (MEASURED).
* The 3 failures are R-019's stale count assertions (M6, M7, M8), which the reviewer says to exclude. They are the same as in round 3.
* Everything else passes, including N1 to N5 and `test_carried_over`.

**Engine checks:**
* `tests/test_culprit_keys.py`, `test_proofcache.py`, `test_det_stale_bytecode.py` and `test_rust_hotpaths.py`: 42 passed, 1 xfailed (the known strict xfail for PYTHONWARNINGS).
* `cargo test -p detpy-core record`: 4 passed.

## 4. Cost: executions, budget and wall time

* **Inference vs replay (a2 + b, MEASURED).** 3,907 later commits were decided by key validity and 3,618 by replay. Without key validity each of those 3,907 would have needed a replay or stayed undecided.
* **Red-side replays per case:**

  | kind | median | p90 | max |
  |---|---:|---:|---:|
  | a2 | 3 | 23 | 64 |
  | b | 19 | 39 | 46 |
  | d | 9 | 44 | 64 |

* **Stated share by red-side budget, all kinds.** ESTIMATED: simulated from the recorded replays, since the finder replays in the same order at any budget. Only the 64 column is a run.

  | budget | 0 | 4 | 8 | 16 | 24 | 32 | 48 | **64** |
  |---|---:|---:|---:|---:|---:|---:|---:|---:|
  | stated / 532 | 160 | 335 | 375 | 444 | 469 | 487 | 512 | **517** |
  | share | 30% | 63% | 70% | 83% | 88% | 92% | 96% | **97.2%** |

  So 85% needs a budget of about 20 and 90% about 28 (ESTIMATED).
* **Clean timing pass, MEASURED** (`results/timing4/`): kind b, 27 cases, nothing else on the machine, run twice.

  | replays at a time | stated = right | wall per case median | p90 | max | total | executions median |
  |---|---|---:|---:|---:|---:|---:|
  | 4 | 27 / 27 | 16.2 s | 38.7 s | 50.6 s | 488 s | 30 |
  | 1 | 27 / 27 | 30.7 s | 66.2 s | 103.3 s | 920 s | 29 |

  * Same answer in 27 of 27.
  * Speedup per case: median 1.74×, max 2.32×.
  * It is below 4× because bisection, confirmations and the replays before the red-side check stay sequential, and replays contend for 4 cores.
  * With 4 workers the finder ran 692 executions, against 663 with 1 (+4%): a batch can replay a commit that a sequential run would have inferred from the batch's earlier replay.
* **Executions against R-019's target of median ≤ 3:** still not met (median 11). Soundly stating an answer on a non-monotonic history costs one replay per undecided later commit. Parallelism buys wall time, not executions.

## 5. Ideas from the brief, evaluated

| idea | done | effect (MEASURED unless marked) |
|---|---|---|
| infer footprint-equal states, states equal to a replayed one, states differing only in inputs the failing test did not read | yes, unified as key validity (§2.2) | 3,907 later commits decided without replay (a2 + b); test 6 |
| probe later states in parallel, raise the budget when concurrent | yes: 4 at a time in mounted copies; budget 6 → 64 | median wall per case 1.74× faster than sequential (§4); stated 73% → 97% |
| adaptive budget: stop when the rest cannot change the answer | inference redone after every batch; stops at the first pass or when all are decided | part of the above; no further saving found |
| prioritise likely-to-pass states | undo commits first, then newest first (as round 3) | no better predictor found in the rows; not measured separately |
| unit-level digests | yes: a changed file still agrees when every recorded unit, skeleton and hooks digest is equal | part of the 3,907 |
| merge `claude/rust-hotpaths-2` first | yes (§2.1) | N5 passes; a Python 3.9 break found and fixed |

## 6. Limits and open points

* **"0 confident wrong" means on these 532 measured cases plus the 9 new adversarial tests.** It is not a general claim.
* **The new inference rests on the engine's key completeness**, the proof-cache premise, plus the guards in §2.2. The guards are conservative where I know the key is silent (configuration, conftest/`__init__`, directory names, modes).
  * Other unrecorded inputs may exist (UNKNOWN). Example: an optional import of a third-party module provided by a new top-level file outside every input directory. The root directory guard covers the repository root, `src/` and the test directories, but not a new `sys.path` entry.
* **Child processes:** red-side replays and inference use single runs, as round 3 did. The 5× repetition applies to green, red and confirmations.
* **Untracked generated files** in the repository (an install's `_version.py`) are equal at every commit for the replays. They are copied into the parallel copies.
* **Step 4:** the import-time footprint is a file-level approximation, unchanged from round 3.
* **Population drift:**
  * the a2 and b "today" environments were rebuilt from today's repository heads;
  * every green and red key outcome was still pass and fail, except the three no-code cases above.
* **Executions are higher, not lower** (median 10 → 11, p90 27 → 39), because the formerly withheld cases (81 a2, 18 b, 27 step 4) now pay for their full red-side check.
