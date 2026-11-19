YES: 302 of 303 culprits correct (99.7%), median 3 test executions per case, 14 of 14 no-code reds attributed to the right input, green environment rebuilt exactly in 33 of 36 cases that needed it. One gap: real-history cases (step 1b) gave 0 reproducible pass-to-fail transitions.

# Exact culprit (idea 2): validation

Session `2026-11-18-exact-culprit`, prompt P-029. Measurement only. The prototype finder sits behind a flag; the engine's default behaviour is unchanged.

* Engine: fenvix-engine-cli, branch `claude/exact-culprit` (from `claude/cache-proof-step1`), commit 3c2e796 (also pushed as `claude/exact-culprit-n98yc2`). Code and result rows: `harness/culprit/` (README there).
* Machine: one cloud container, 4 cores, Linux, CPython 3.13.18, Node 26.13.1.
* Labels: MEASURED (my runs), DECLARED (a source), ESTIMATED (my arithmetic or judgement), UNKNOWN.
* Timing: the main runs had 4 to 6 jobs on 4 cores (load 5 to 8), so their wall times are **NOISY**. Clean timings come from a separate pass on an idle host (18 cases, one at a time).

## Against "the number that says yes"

| criterion | target | result | label |
|---|---|---|---|
| correct culprits | >= 95% over >= 300 cases | **302 / 303 = 99.7%** | MEASURED |
| test executions per case | median <= 3 | **median 3** (mean 5.9; p90 17) | MEASURED |
| no-code reds attributed to the right input | 14 / 14 | **14 / 14** (plus 26 / 26 with a decoy) | MEASURED |
| NO: correct share | under 85% | 99.7% | MEASURED |
| NO: old environment not rebuildable | over 20% of cases | **3 / 36 = 8%** not exact; the cause is an artifact of the test project, not a missing package (see "Rebuild") | MEASURED |

The overall median of 3 comes mostly from kind a (200 of 303 cases). The flaky kind is far more expensive: **median 17** executions (step 4 below). Kinds a, b and c alone: median 3, p90 5, max 7.

## Results by kind (all MEASURED)

| kind | cases | finder correct | finder executions: median / p90 / max | git bisect correct | git bisect executions, median |
|---|---:|---:|---|---:|---:|
| a. planted regressions, 10 libraries x 20 | 200 | **200** | 3 / 5 / 7 | 200 | 5 |
| b. real history (cache-proof and market-test walks) | 0 | - | - | - | - |
| c. no-code reds, alone (14) and with a decoy (26) | 40 | **40** | 2 / 2 / 3 | 20 | 3 |
| d. order-dependent defects (step 4) | 63 | **62** | 17 / 21 / 30 | 10 attempts each: **548 of 630 attempts wrong** | 4 |
| total | 303 | **302** | 3 / 17 / 30 | | |

### a. Planted regressions

* **Libraries:** attrs, boltons, cachetools, click, jinja, marshmallow, more-itertools, sqlparse, structlog, toolz. arrow was planned, but it yielded 0 cases: all 43 tried mutants were rejected because plain pytest and `--det` disagreed on the red test (its tests read the real clock). cachetools replaced it.
* **Case shape:** a one-token mutation (comparison, boolean, ±1, `is None`, index) in a function body, committed k commits back.
  * Every later first-parent commit is replayed on top of it with the mutation kept: new commits, same trees, same messages and dates.
  * The red test passes at green and fails at the planted commit and at the red head, under both plain pytest and `--det` (checked).
* **Distance k:** 5 to 200, median 28.5. 84 cases have k ≤ 20, 57 have 21-60, 31 have 61-120, 28 have 121-200. The target was a spread from 5 to 200. The old end is thin because **today's environment cannot run old code** (MEASURED, generation logs): at the green commit the suite failed to collect 132 times for click, 42 for toolz and 30 for structlog. Distances ≤ 90 filled the gap.
* **Finder executions by k (median):**

  | k | finder | git bisect | commit candidates after pruning |
  |---|---:|---:|---:|
  | 5-20 | 2 | 3 | 5 |
  | 21-60 | 3 | 5 | 13 |
  | 61-120 | 5 | 6 | 23 |
  | 121-200 | 5.5 | 7 | 55 |

* **Pruning:** a commit is a candidate only if it changes the digest of a differing input of the test (per function, skeleton, conftest hook or file). Share of commits left, per library (median): structlog and attrs 16%, marshmallow 18%, boltons 32%, jinja 34%, cachetools 40%, sqlparse 56%, more-itertools 61%, click 68%, toolz 82%. Pruning is weak where every commit touches the package code that every test loads.
* **Two refinements tried offline on 51 cases, no gain (MEASURED):**
  * keep only inputs of the red key: 0 fewer candidates;
  * weighted bisection (commits that change a function the red run executed weigh 20x a skeleton-only change): median 3 → 3.
* **Clean timing** (idle host, 18 cases, one at a time):
  * per case: finder median **3.9 s**, git bisect median **1.3 s**;
  * per execution: a `--det` replay (re-exec, Level 0, key dump) median 1.3 s, a plain pytest step 0.36 s;
  * the finder's key diff and pruning: median 0.7 s per case.

  On code regressions with a deterministic test, plain bisect is just as correct and faster in wall time. The finder saves executions (median 3 vs 5), not seconds.

### c. No-code reds

* **Source:** the 16 realistic CI changes of the head-to-head (engine branch `claude/sweet-mendel-rtdg7f`, `harness/skip_study2/headtohead/changes.json`; the 14 that break a test are listed in NUMBERS.md).
* **Window:** each change uses its head-to-head window (green = w[2], red = w[10], 7 real commits in between).
* **Environments:**
  * before and after = the head-to-head's frozen environments (`freeze` 0 and 1) where recorded;
  * otherwise resolved once at the green commit and frozen (both sides the same).
* **How each change lands:** a data edit is a commit of its own, replayed into the later commits. An environment-variable or package change is not a commit ("nobody changed the code").
* **Decoys:** a second change that lands together with the real one and is checked not to break the red test:
  * TZ=Asia/Kolkata in the red job, which enters every test's configuration;
  * pluggy 1.7.0 → 1.6.0, loaded by every pytest run.

  The Node project (docusaurus) has the TZ decoy only.
* **Excluded:** click (PYTHONWARNINGS) and vue-core (NODE_ENV) break nothing, so they have no red test.

| change | right answer | finder (alone) | executions alone / +TZ / +pluggy | git bisect (red environment) |
|---|---|---|---|---|
| flask: pytest 8.4.2 → 9.1.1 | `dist:pytest` | right | 1 / 2 / 2 | wrong commit |
| structlog: rich 13.0.0 appears | `dist:rich` | right | 1 / 2 / 2 | wrong commit |
| sqlparse, boltons, pygments, toolz: PYTHONWARNINGS=error | `env:PYTHONWARNINGS` | right (4 of 4) | 1 / 2 / 2 | wrong commit (4 of 4) |
| docusaurus: NODE_ENV=production | `env:NODE_ENV` | right | 0 / 1 / - | wrong commit |
| flask, jinja, werkzeug, sqlparse, pygments, home-assistant, docusaurus: fixture edit | the edit commit | right (7 of 7) | 0-2 / 1-3 / 1-3 | right |

* **What git bisect does:** it finds the data edits, which are commits. For every environment change it names the first commit of the range. Every commit is red in today's environment, so it cannot name an input; 20 of the 40 cases are wrong this way.
* **How the finder names the input:** it diffs the keys (variables read, distributions, interpreter start-up settings, time zone and locale), prunes, then replays "red code in the green environment" and splits the remaining inputs.
* **Node (docusaurus):** the Node engine never stores a failing test and has no key-dump flag. The finder runs in *green-key-only* mode there: each input of the green entry is re-evaluated on the red side (the red job's variables, the red tree, the red run's runtime parts). 4 of 4 right.

### d. Order-dependent defects (step 4)

* **Victims:** from the mixed round's order-only set (`harness/order_only_targets.json`), which fail 10 of 10 under one `--det` order. 23 repositories eligible; anyio, jsonschema and packaging were left out because they are too large.
* **Finder:** one deterministic run per step.
  1. Full suite in the red order.
  2. The victim alone.
  3. Binary split of the tests that ran before the victim, until one polluter remains.
  4. The pair (polluter, victim) at older first-parent commits: distances 1, 2, 4, ... until it passes, then a binary search.
* **Truth:** walk back from red one commit at a time, running the pair deterministically, down to the first pass. The truth is the newest fail whose parent passes (median 23 runs per case).
* **Independent check:** in all 63 cases the named commit adds or edits the polluter's or the victim's test file.
* **Usable cases:** 118 victims tried, 63 usable. Not usable:
  * 22 brittle: the victim fails alone, so it needs a state-setter, not a polluter;
  * 13 need more than one polluter;
  * 11 have no passing commit within 512 first-parent commits, or older commits cannot run;
  * 9 no longer reproduce on this machine.
* **Concentration:** the 63 cases are 15 repositories, **24 distinct polluters and 19 distinct culprit commits**. Many victims share one cause, so the cases are not 63 independent defects.
* **Finder result:** 62 of 63 right. Executions: median 17 (polluter search 8, commit search 10). The miss, idoft-pykicad: the pair's history is not monotonic (a test disappears and comes back), and the exponential step jumped over the newest transition onto an older one.
* **Baseline:** `git bisect run`, plain pytest, full suite, random order (pytest-randomly, a new seed every run, as CI does). It gets the same good commit as the finder, which is generous to it; 10 attempts per case.
  * **548 of 630 attempts named the wrong commit (87%)**;
  * in 55 of 63 cases most attempts were wrong; in 40 cases all 10 were wrong;
  * median 4 executions per attempt.

### b. Real history (gap)

The aim was every pass-to-fail transition in the market-test and cache-proof walks, with the project's own revert or fix as the truth. **No transition gave a usable case** (MEASURED):

* **Cache-proof walks** (the walks store failure counts per step, not test ids, so each transition had to be reproduced locally):
  * pygments step 8 and step 13, arrow step 6 and step 28: 0 pass-to-fail tests locally. The extra failure is either absent here, or already red at the green commit (arrow `test_anchorage_dst`: tzdata differs from the GitHub runner);
  * jinja step 20: 19 *new* tests failing (the commit added trio-based tests), none that passed before;
  * pylint step 8: the full `--det` run at the green commit had not finished after 43 CPU-minutes; stopped;
  * home-assistant shards: the cache-proof counts show new failing tests (miss reason `new`) at the jumps; not reproduced.
* **Market-test walks:**
  * litellm c25c669 (0 → 35 failing test files, "decide key and JWT authentication in a Rust core"), prefect 0e40ace, mlflow 6c4a198, pydantic-ai 4b389e1 and transformers 65c782b: no later revert or fix names them;
  * prefect at both commits: 167 setup errors (the tests need services this machine lacks);
  * pydantic-ai's commit only edits a workflow file, so its +1 is noise.

**Conclusion:** the walks are the wrong source for true regressions. They record counts, not test ids, and their failures are mostly machine-specific or new tests. Proposed next test: take merged pull requests that the project itself reverted (`git log --grep='^Revert'` in the 10 market-test repositories), rebuild the red at the reverted commit, and run the finder; ESTIMATED at 1 to 2 session-days.

## Rebuild of the green environment

* **Scope:** kinds b and c, plus all Node cases. The finder never reuses the green job's virtualenv, since the CI machine is gone. It rebuilds it from the green key's distribution list (exact versions, `uv`, the same detpy wheel, the project editable) and compares the replay's runtime digest with the green key's. Kind a and step 4 use one fixed environment for every commit, so no rebuild is needed (runtime equal in 200 of 200).
* **Result:** 36 cases needed a rebuild; **33 were exact** (MEASURED).
* **The 3 misses** are toolz at a commit installed with legacy `setup.py develop`. Its own `toolz.egg-info` in the working tree is listed by detpy as an installed third-party distribution, and a checkout plus `git clean` removes it. Rebuilt by hand, the same environment is exact. Third-party packages were not the problem.
* **Precondition: rebuild at the original path.** Console scripts embed the virtualenv path in their shebang, and the shebang is in RECORD, so the runtime identity changes with the path. A venv rebuilt anywhere else **never** matches (MEASURED: same versions, different RECORD digests for pytest, pygments and detpy). Rebuilding at the green job's path (free, since its machine is gone) was exact.
* **Not tested here:** this study did not rebuild environments of old commits, k up to 200 commits back. In kind a, today's environment could not run old commits for click, toolz and structlog (above). That is where "the old environment cannot be rebuilt" would really be decided.

## What I decided, and why

1. **The red key is needed, so the flag records failures.** The cache never stores a failure. The finder needs the red run's inputs, so `--det-cache-keys=PATH` writes every test's inputs for every outcome, resolved to names and digests, together with the runtime and configuration parts, the installed distributions, the distributions loaded in the process, and the interpreter's start-up settings (below). It is opt-in and a volatile option, so it changes no cache key (tested).
2. **Single-culprit search, one replay per step.** When there are both commit and input candidates, the first step is "red code, green environment". Then a binary search over candidate commits (the last candidate is known red, so one candidate costs 0 executions), or a binary split over input candidates. No confirmation run: correctness is measured against ground truth instead. A product would add one or two replays to emit the before/after replay commands (ESTIMATED: +1 to +2 per case).
3. **Consequences are folded into their cause, using only the two job definitions:**
   * a variable both jobs set to the same value is not a candidate, even when only one run read it;
   * a file outside the repository that only one run read, whose recorded value still holds on disk, is not a candidate;
   * TZ heads its zone files, `tzlocale` twin and `/etc/localtime`;
   * pytest's ini and options follow a pytest or plugin distribution change.

   Before these rules, toolz's PYTHONWARNINGS case cost 7 executions: a `git` child of the red run read about 35 system files. After them it cost 1.
4. **Distribution pruning:** a package change is a candidate only if the test's process loaded it, or it is pytest or a plugin.
5. **detpy's own files** (bytecode cache, the run's cache directory) are ignored as data inputs: they derive from inputs.
6. **Node runs in green-key-only mode.** The Node engine cannot dump keys or record failures, so the finder re-evaluates each green input on the red side. Its digests match detpy's (`env_value_digest` checked on real values).

## What blocks or is missing

* **Real-history cases (1b): 0.** See above, with the proposed next test.
* **Wall time:** the finder is slower than git bisect on deterministic code regressions (3.9 s vs 1.3 s median, clean). Each `--det` replay costs about 3.6 times a plain pytest start; the gain is in executions, correctness on flaky reds, and naming inputs.
* **Flaky defects are expensive:** median 17 executions, of which 8 to find the polluter.
  * Footprints cannot help on Python 3.9 (`--det-cache` needs `sys.monitoring`), and 61 of 63 cases are on 3.9.
  * The step-4 finder replays the plain pair and uses no key.
  * Next options: prune polluter candidates with the footprint (only tests that write state the victim reads) on 3.12+, and start the commit search from the polluter test's introduction (`git log` on its file) instead of exponential back-off.
* **Concentration:** the 63 step-4 cases contain 24 distinct polluters.
* **Not measured:** two inputs needed together (an interaction), and decoys a test actually depends on.
  * The decoys were chosen not to break the test.
  * Each scenario has a single true culprit.
* **Engine test suite** (`pytest tests`): 150 passed, 7 skipped, 1 xfailed (the new strict xfail below), 1 failed. The failure, `test_proofcache.py::test_module_level_change_reruns_every_test_that_had_the_module_loaded`, came in one of two full-suite runs under load. It passes 5 of 5 alone and passed in the other full run. The cache-proof report already lists one unidentified one-off failure, so I count it as pre-existing flakiness (UNKNOWN cause). New tests: `tests/test_culprit_keys.py`, 3 passing and 1 strict xfail.

## Errors or gaps found

**In the engine (for the coordinator):**

1. **Proven error in the cache with proof (engine default).** The interpreter's start-up settings are in neither the configuration digest nor the runtime digest. They include `PYTHONWARNINGS`, `PYTHONDEVMODE`, `-W` and `-X` options, and `sys.flags`, all read by C at start-up, not through `os.environ`. So a pass recorded without `PYTHONWARNINGS` is **reused** with `PYTHONWARNINGS=error`, while a fresh run fails. Failing test: `tests/test_culprit_keys.py::test_pythonwarnings_is_an_input`, marked strict xfail so the suite stays green.

   This is the same change the head-to-head used in 5 of its 16 scenarios. The head-to-head's proof rule C caught it because that rule is the walk's closure, not detpy's key. Remedy: put `sys.warnoptions`, `sys._xoptions`, `sys.flags` and the `PYTHON*` variables into `config_identity`. The key dump already records them.
2. **The runtime identity depends on the virtualenv path** (console-script shebangs inside RECORD). A cache shared across machines whose venv paths differ never reuses anything because of `runtime`. Remedy: hash RECORD without the `bin/` script entries, or hash the dist's files minus scripts.
3. **A project installed with legacy `setup.py develop`** (no `direct_url.json`) counts as a third-party distribution in the runtime identity. Its egg-info in the working tree also comes and goes with `git clean`.
4. **Data inputs include detpy's own bytecode cache** (`~/.cache/detpy/pyc/...`). This is redundant: the sources are already inputs.

**In this brain:**

5. NUMBERS.md names "16 realistic CI changes" but does not list them. The list lives in the engine branch `claude/sweet-mendel-rtdg7f` (`harness/skip_study2/headtohead/changes.json`); worth a pointer.
6. The cache-proof and market-test result files keep failure counts per step, not failing test ids, so "every pass-to-fail transition" cannot be read from them.

## Links

* Engine branch `claude/exact-culprit`, commit 3c2e796: `python/detpy/proofcache.py` (`_dump_keys`), `python/detpy/plugin.py` (`--det-cache-keys`), `tests/test_culprit_keys.py`, `harness/culprit/` (finder, case drivers, `results/*.jsonl`, `results/summary.json`).
* Numbers recompute with plain Python: `python3 harness/culprit/aggregate.py harness/culprit/results` (prints the totals above; `results/summary.json` is its full output).
* Node engine used: branch `claude/node-cache-proof` (detjs), unchanged.
