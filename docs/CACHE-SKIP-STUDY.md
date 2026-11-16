# Cache-skip study: how much CI test time can be skipped *with proof*?

Date: 2026-11-16. Branch `claude/loving-maxwell-58mv2w`. Scripts: `harness/cache_skip/`.
Results: `harness/cache_skip/results/` (one JSON per repository, plus `summary.json`).

**Question.** Between two consecutive commits of a real project, what share of
the test suite's time could be skipped by reusing a test's previous result,
*only* when nothing that test depends on has changed (and the test is
deterministic under `--det`)? The answer decides whether a "deterministic test
runner that removes CI minutes" is a viable product.

Label legend: **MEASURED** (computed in this study on the stated sample),
**ESTIMATED** (reasoned from measured data, not measured directly),
**DECLARED** (claimed by a third party), **UNKNOWN**.

## 1. Answer in numbers

The sample: 14 Python repositories, 50 consecutive default-branch commits
each, and 690 commit-to-commit transitions evaluated. Another 10 transitions
could not be evaluated because a commit was broken. "Time" means the sum of
per-test durations (setup + call + teardown) in a plain serial run at the new
commit. Medians and means are taken across transitions. The overall figure is
the median (or mean) of the 14 per-repository values.

| rule for "nothing it depends on changed" | is it a proof? | median share of test time skippable per commit | mean | spread of per-repo means |
|---|---|---:|---:|---:|
| **file level + import-time guard** (`file+guard`) | yes, at the Python level (see 2.3) | **0%** MEASURED | **22%** MEASURED | 1% – 43% |
| **line level + import-time guard** (`line+guard`) | yes, at the Python level | **0%** MEASURED | **26%** MEASURED | 1% – 43% |
| line level + name-level guard (`line+nameguard`) | near-proof: assumes no reflection on module namespaces | 0% MEASURED | 30% MEASURED | 3% – 49% |
| file level, coverage only (`file`, pytest-testmon style) | **no** (misses module-level data, see 3.2) | 11% MEASURED | 36% MEASURED | 15% – 84% |
| line level, coverage only (`line`) | **no** | 60% MEASURED | 48% MEASURED | 22% – 87% |
| any change to any loaded module (`closure`, Ekstazi style) | yes, coarse | 0% MEASURED | 17% MEASURED | 1% – 38% |

Pooled over all 690 transitions (MEASURED), the share of all test time saved
is: `file+guard` 16%, `line+guard` 23%, `line+nameguard` 26%. The
coverage-only rules save more: `file` 31%, `line` 43%.

**Why the proof-grade median is 0%.** Commits fall into three classes (pooled,
MEASURED):

| commit class | share of transitions | `line+guard` median / mean | coverage-only `line` median / mean |
|---|---:|---:|---:|
| touches a config file (strict rule: lockfile, requirements, pyproject.toml, setup.*, conftest.py, pytest.ini, tox.ini, CI files) | 207 / 690 = **30%** | 0% / 0% (everything invalidated by definition) | 0% / 0% |
| touches no Python file (docs, data, changelog) | 90 / 690 = **13%** | 99% / 93% | 99% / 93% |
| touches Python code | 393 / 690 = **57%** | **0% / 24%** | 72% / 64% |

On commits that change Python code, the proof-grade rule leaves less than 5%
of test time skippable in **249 of 393** transitions (63%, MEASURED). Almost
every source commit changes something at module level: an assignment, a class
attribute, a decorator, an annotation, a new method, a `__version__` bump. The
changed module is one that every test loaded at collection time, and coverage
cannot tell which tests actually read the changed value.

**Sensitivity to the config rule.** Edits to CI files alone account for 75 of
the 207 config transitions. Only 16 of the 690 transitions change the
installed environment, a pytest configuration section or a `conftest.py`
(this is the *relaxed* rule, MEASURED). Under the relaxed rule (all MEASURED,
median of repo medians / mean of repo means):

* `line+guard`: median 65%, mean 47%;
* `file+guard`: median 41%, mean 43%;
* coverage-only `line`: median 86%, mean 71%.

The strict rule, as specified, gives the headline numbers. The relaxed rule
shows what a product would face if it hashed the resolved environment and the
pytest configuration instead of whole files.

**Share of CI wall time.** Collection, interpreter start-up and plugin set-up
are never skipped. Measured against the plain run's wall time, `line+guard`
saves a mean of 17% per commit (median 0%), and coverage-only `line` saves 31%
(median 25%) (MEASURED). The share of a whole CI job is lower still, because a
job also checks out the code, sets up Python, installs dependencies and runs
a matrix of Python versions. That share is **UNKNOWN**: the GitHub API was
not reachable from this session. For suites of 1–23 s like these, test
execution is very likely a minority of the job (ESTIMATED).

**Cost of dependency capture.** Running the suite under coverage.py with
per-test dynamic contexts plus the audit hook took a median **+107%** wall
time over the plain run (MEASURED). The quartiles are +61% / +150%. Per-repo
medians range from +31% (werkzeug) to +416% (more-itertools) and +465%
(toolz). These figures are noisy: 3 jobs shared a 4-CPU container.

## 2. Method

### 2.1 Repositories and commits

* 14 repositories from the `popular` pool of the mixed round
  (`harness/results/mixed/`), all with a first baseline run under 60 s:
  arrow, attrs, boltons, click, flask, isort, jinja, marshmallow, more-itertools, pygments, sqlparse, structlog, toolz, werkzeug.
* For each one, the last **51 first-parent commits** of the default branch
  (HEAD as of 2026-11-16), i.e. **50 transitions** (commit *i-1* → commit
  *i*). First-parent means each merged pull request counts as one step, which
  is what a CI pipeline on the default branch sees. Pull-request CI (one push
  at a time on a branch) has smaller diffs and would skip more; this study does
  not measure it.
* Python 3.13, pytest 9.2, coverage.py 7.17, one `uv` virtualenv per repository, installed at the oldest
  commit with the same install logic as the detpy harness and **reinstalled
  whenever a dependency spec file changed** (pyproject.toml, setup.py,
  setup.cfg, requirements, lockfiles, tox.ini).

### 2.2 What is run at every commit (no sampling, no stale data)

At **every** one of the 51 commits (`harness/cache_skip/run_repo.py`):

1. **plain run**: `pytest -p no:randomly -n 0 -p no:cacheprovider`, serial,
   collection order, `PYTHONHASHSEED=0`, no coverage. Gives per-test duration
   (setup + call + teardown, from pytest's own reports), outcome and wall time.
2. **capture run**: the same command under `coverage run` (coverage.py
   7.17, default C tracer, `concurrency = thread`) with the plugin
   `harness/cache_skip/capture_plugin.py`, which switches the coverage
   *dynamic context* so that every executed line is attributed to
   * the test (`t|nodeid`: setup, call, teardown, function-scoped fixtures),
   * a wider-scoped fixture (`f|scope|baseid|name`), credited to every test
     that requests it (otherwise a session fixture's code would be credited
     only to the first test that triggers it),
   * the collection of the test file (`c|file`: module import,
     parametrisation), credited to every test of that file,
   * the session (startup, between tests).

   A `sys.addaudithook` hook records, with the same attribution, data files
   below the repository root that are opened (non-Python inputs), directories
   listed (excluding the import system's own directory scans), subprocesses
   spawned and inet sockets connected. After each test the plugin scans
   `sys.modules` to know when every repository module was first loaded.
3. **determinism check** at commits 0, 10, 20, 30, 40, 50: two runs under
   `--det` (detpy wheel built from this branch) whose per-test fingerprints are
   compared; used only for tests missing from the round CSV (renamed or
   removed tests).

Because the map is captured at every commit, the skip decision for
transition *i-1 → i* uses the map of commit *i-1* (a **fresh** map: what a
tool that re-records the tests it runs would have), and the results at
commit *i* are the ground truth to check it against.

### 2.3 When a test is skippable with proof

`harness/cache_skip/analyze.py`. A test of commit *i* must run when **any** of
these holds; otherwise its result from commit *i-1* is reused.

Shared rules (all variants):

* it did not exist at *i-1* (new or renamed);
* it is not deterministic under `--det`: `fingerprint_covered` is not `True`
  in `harness/results/mixed/<repo>.csv` (10 `--det` runs at HEAD); tests
  missing from the CSV use the 2-run check of 2.2; unknown = must run;
* it spawned a subprocess or opened an inet socket (coverage cannot see the
  other side);
* **configuration changed** (strict rule, as specified): any change to a
  lockfile, requirements file, `pyproject.toml`, `setup.py`, `setup.cfg`,
  any `conftest.py`, `pytest.ini`, `tox.ini`, `noxfile.py` or a CI file
  (`.github/workflows/*` etc.) invalidates every test;
* a data file it opened changed, or a directory it listed gained or lost an
  entry.

Python source dependencies, five variants from coarsest to finest:

| variant | a changed Python file F forces the test to run when |
|---|---|
| `closure` | F was loaded (`sys.modules`) before or during the test, or the test executed F (Ekstazi-style, module granularity) |
| `file` | the test executed at least one line of F (coverage, file level) |
| `line` | a changed line of F maps to a statement the test executed (coverage, line level). Changed lines are mapped to the start line of every statement whose span contains them. For an insertion, the lines that must have run to reach the new code count as changed: the previous and next code lines (blank and comment lines skipped) and the first line of every statement that encloses the previous code line |
| `file+guard` | `file`, **plus** the import-time guard below |
| `line+guard` | `line`, **plus** the import-time guard below |
| `line+nameguard` | `line`, plus a finer *name-level* guard (below) |

**Import-time guard.** Coverage records the lines a test *executes*, not
the module-level objects it *reads*. A test that uses a constant, a class
attribute, a default argument, a decorator's effect or a regex table (every
Pygments lexer is one) executes no line of the module that defines it at test
time: those lines ran once, at import. The guard therefore forces a test to
run when a module it had loaded has a **module-level change**: the module's
AST with all function bodies removed (keeping docstrings, signatures,
defaults, decorators, class bodies, assignments) differs, or a changed line
was executed at import or collection time. Only lines inside function bodies count for the second
condition, because module-level code is already compared structurally. This
is what makes the decision a proof at the Python level. Without it, `file` and
`line` are what coverage-based test selection tools (pytest-testmon style) do.

**Name-level guard** (`line+nameguard`). This guard compares the module
structure name by name instead of as one block.

* Changes that are always *hard* (every test that had loaded the module must
  run):
  * statements in a module or class body (assignments, imports, class
    attributes, `__all__`);
  * class headers;
  * decorators and annotations;
  * added decorated functions;
  * added methods;
  * added module-level functions whose name the old module already
    referenced.
* A change to only a function's argument list or default values affects the
  tests that executed that function's body.
* A docstring change affects the doctests of that file.
* An added plain function affects nothing.

This rule assumes that no test uses reflection over namespaces (section 4).

**Test modules.** pytest imports every test module at collection, but only
two kinds of tests can depend on one: the tests in that module, and tests in
files that import it. Importers are found with `git grep` on import lines.
The guards scope changes to a test file accordingly.

### 2.4 Outputs and checks

Per transition: share of test **count** and of test **time** (sum of
per-test durations of the plain run at commit *i*) that is skippable, per
variant and config rule; also the share of the plain run's **wall** time
(which includes interpreter start and collection, never skippable).

Safety checks against the ground truth at commit *i*:

* **outcome changed although skipped**: a skipped test whose outcome at *i*
  differs from *i-1*;
* **executed path changed although skipped**: a skipped test whose executed
  lines at *i* differ from those at *i-1* (moved to *i*'s line numbers). The
  noise floor of this check is measured on `closure`-skipped tests (none of
  their loaded modules changed, so any difference is run-to-run variation:
  unseeded randomness, caches warmed by another test, timing);
* **stale map**: the same decisions made with the map captured at the last
  refresh point (commits 0, 10, 20, 30, 40; age 1–9 commits), lines moved
  forward with the diff; *unsafe* = the stale map skips a test that the fresh
  map says must run.

## 3. Results per repository

### 3.1 Share of test time skippable per commit (strict config rule)

Median / mean across the 50 transitions of each repository (MEASURED).

| repo | tests | commits evaluated | config commits (strict / relaxed) | closure median / mean | file median / mean | line median / mean | file+guard median / mean | line+guard median / mean | line+nameguard median / mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| arrow | 1904 | 50/50 | 19 / 3 | 0% / 10% | 13% / 25% | 49% / 51% | 0% / 11% | 0% / 12% | 0% / 15% |
| attrs | 1412 | 50/50 | 25 / 1 | 0% / 19% | 0% / 25% | 0% / 31% | 0% / 20% | 0% / 21% | 0% / 27% |
| boltons | 621 | 50/50 | 4 / 0 | 0% / 6% | 79% / 70% | 79% / 71% | 77% / 43% | 77% / 43% | 78% / 49% |
| click | 2653 | 50/50 | 11 / 0 | 0% / 10% | 25% / 34% | 62% / 47% | 0% / 15% | 0% / 17% | 0% / 22% |
| flask | 494 | 46/50 | 13 / 1 | 0% / 28% | 47% / 49% | 97% / 65% | 0% / 31% | 0% / 31% | 0% / 46% |
| isort | 794 | 50/50 | 8 / 0 | 0% / 7% | 9% / 17% | 29% / 26% | 9% / 15% | 20% / 22% | 26% / 23% |
| jinja | 911 | 50/50 | 34 / 2 | 0% / 22% | 0% / 29% | 0% / 30% | 0% / 22% | 0% / 22% | 0% / 22% |
| marshmallow | 1192 | 50/50 | 28 / 0 | 0% / 28% | 0% / 30% | 0% / 39% | 0% / 29% | 0% / 34% | 0% / 36% |
| more-itertools | 771 | 50/50 | 6 / 0 | 0% / 11% | 7% / 15% | 61% / 53% | 3% / 14% | 42% / 36% | 61% / 47% |
| pygments | 5346 | 50/50 | 0 / 0 | 0% / 12% | 85% / 84% | 85% / 87% | 0% / 21% | 0% / 23% | 0% / 23% |
| sqlparse | 540 | 50/50 | 7 / 4 | 0% / 22% | 2% / 37% | 86% / 57% | 0% / 27% | 0% / 31% | 0% / 33% |
| structlog | 921 | 50/50 | 20 / 0 | 0% / 38% | 42% / 45% | 65% / 52% | 0% / 41% | 0% / 41% | 0% / 43% |
| toolz | 193 | 44/50 | 21 / 3 | 0% / 20% | 3% / 30% | 59% / 48% | 0% / 22% | 0% / 31% | 0% / 37% |
| werkzeug | 1015 | 50/50 | 11 / 2 | 0% / 1% | 28% / 19% | 29% / 22% | 0% / 1% | 0% / 1% | 0% / 3% |
| **median of repo values** | | | | **0% / 17%** | **11% / 36%** | **60% / 48%** | **0% / 22%** | **0% / 26%** | **0% / 30%** |
| **pooled (all commits)** | | | | 0% / 16% | 13% / 36% | 61% / 48% | 0% / 22% | 0% / 26% | 0% / 30% |

Share of test **count**, and the relaxed config rule (MEASURED):

| repo | count: file / line (median, mean) | count: file+guard / line+guard (median, mean) | relaxed config: file / line+guard time (median, mean) | wall share line+guard (mean) |
|---|---:|---:|---:|---:|
| arrow | 13%, 32% / 86%, 54% | 0%, 13% / 0%, 14% | 37%, 53% / 0%, 42% | 7% |
| attrs | 2%, 36% / 3%, 44% | 0%, 28% / 0%, 29% | 71%, 58% / 71%, 54% | 19% |
| boltons | 94%, 84% / 95%, 84% | 80%, 51% / 80%, 51% | 79%, 75% / 78%, 48% | 33% |
| click | 24%, 39% / 79%, 56% | 0%, 18% / 0%, 20% | 32%, 45% / 0%, 26% | 7% |
| flask | 46%, 51% / 97%, 65% | 0%, 31% / 0%, 31% | 100%, 73% / 90%, 53% | 6% |
| isort | 32%, 36% / 74%, 56% | 27%, 31% / 56%, 47% | 11%, 26% / 34%, 31% | 19% |
| jinja | 0%, 29% / 0%, 30% | 0%, 22% / 0%, 22% | 100%, 79% / 100%, 70% | 13% |
| marshmallow | 0%, 32% / 0%, 40% | 0%, 30% / 0%, 34% | 100%, 82% / 100%, 86% | 12% |
| more-itertools | 18%, 21% / 19%, 26% | 17%, 18% / 19%, 20% | 7%, 22% / 58%, 42% | 34% |
| pygments | 54%, 60% / 54%, 62% | 0%, 18% / 0%, 20% | 85%, 84% / 0%, 23% | 17% |
| sqlparse | 15%, 44% / 81%, 59% | 0%, 32% / 0%, 33% | 3%, 41% / 0%, 35% | 22% |
| structlog | 50%, 48% / 80%, 54% | 0%, 42% / 0%, 42% | 99%, 85% / 99%, 80% | 21% |
| toolz | 41%, 40% / 72%, 47% | 0%, 28% / 0%, 31% | 95%, 65% / 97%, 62% | 21% |
| werkzeug | 55%, 45% / 70%, 60% | 0%, 5% / 0%, 5% | 28%, 25% / 0%, 4% | 1% |

By commit class (MEASURED):

| repo | config / no-python / python commits | python commits: file / line / file+guard / line+guard / line+nameguard time share (median, mean) | config commits under relaxed rule: line / line+guard (mean) |
|---|---:|---:|---:|
| arrow | 19 / 4 / 27 | 14%, 32% / 97%, 80% / 0%, 6% / 0%, 7% / 0%, 14% | 80% / 79% |
| attrs | 25 / 10 / 15 | 46%, 35% / 71%, 57% / 0%, 17% / 0%, 23% / 66%, 42% | 67% / 67% |
| boltons | 4 / 2 / 44 | 79%, 76% / 79%, 77% / 77%, 45% / 77%, 45% / 78%, 53% | 62% / 62% |
| click | 11 / 3 / 36 | 29%, 41% / 67%, 59% / 0%, 15% / 0%, 16% / 0%, 24% | 53% / 43% |
| flask | 13 / 8 / 25 | 83%, 59% / 98%, 87% / 0%, 25% / 0%, 25% / 83%, 53% | 85% / 77% |
| isort | 8 / 2 / 40 | 10%, 18% / 31%, 29% / 9%, 15% / 29%, 25% / 30%, 26% | 57% / 57% |
| jinja | 34 / 8 / 8 | 98%, 82% / 99%, 86% / 0%, 38% / 0%, 38% / 0%, 38% | 78% / 70% |
| marshmallow | 28 / 12 / 10 | 12%, 30% / 75%, 76% / 10%, 25% / 65%, 49% / 69%, 59% | 97% / 93% |
| more-itertools | 6 / 5 / 39 | 7%, 7% / 61%, 56% / 3%, 5% / 54%, 34% / 61%, 48% | 69% / 48% |
| pygments | 0 / 4 / 46 | 85%, 82% / 85%, 86% / 0%, 14% / 0%, 16% / 0%, 16% | n/a / n/a |
| sqlparse | 7 / 9 / 34 | 1%, 28% / 80%, 58% / 0%, 14% / 0%, 21% / 0%, 23% | 39% / 28% |
| structlog | 20 / 16 / 14 | 58%, 49% / 76%, 72% / 10%, 32% / 10%, 32% / 40%, 39% | 98% / 98% |
| toolz | 21 / 6 / 17 | 40%, 44% / 97%, 89% / 6%, 21% / 47%, 46% / 78%, 62% | 83% / 65% |
| werkzeug | 11 / 1 / 38 | 28%, 24% / 30%, 28% / 0%, 1% / 0%, 1% / 0%, 3% | 25% / 12% |

| commit class (pooled) | transitions | closure (median, mean) | file (median, mean) | line (median, mean) | file+guard (median, mean) | line+guard (median, mean) | line+nameguard (median, mean) |
|---|---:|---:|---:|---:|---:|---:|---:|
| config (strict config rule) | 207 | 0%, 0% | 0%, 0% | 0%, 0% | 0%, 0% | 0%, 0% | 0%, 0% |
| config (relaxed config rule) | 207 | 97%, 67% | 98%, 72% | 98%, 75% | 97%, 68% | 98%, 69% | 98%, 70% |
| no-python (strict config rule) | 90 | 99%, 93% | 99%, 93% | 99%, 93% | 99%, 93% | 99%, 93% | 99%, 93% |
| no-python (relaxed config rule) | 90 | 99%, 93% | 99%, 93% | 99%, 93% | 99%, 93% | 99%, 93% | 99%, 93% |
| python (strict config rule) | 393 | 0%, 8% | 30%, 43% | 72%, 64% | 0%, 17% | 0%, 24% | 0%, 32% |
| python (relaxed config rule) | 393 | 0%, 8% | 30%, 43% | 72%, 64% | 0%, 17% | 0%, 24% | 0%, 32% |

### 3.2 Safety checks: is a skip really safe?

| repo | plain serial run (median s) | capture overhead (median) | skipped tests (line+guard, all commits) | outcome changed although skipped (file / line / line+guard / line+nameguard) | executed path changed although skipped, noisy tests excluded (noisy tests / file / line / line+guard / line+nameguard) | stale map (age 1-9): unsafe skips file / line / line+guard / line+nameguard | transitions with an unsafe stale skip (line) |
|---|---:|---:|---:|---:|---:|---:|---:|
| arrow | 2.6 | 117% | 12781 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 / 0 | 2 / 456 / 0 / 0 | 2/45 |
| attrs | 8.9 | 69% | 20560 | 0 / 0 / 0 / 0 | 18 / 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0/45 |
| boltons | 1.9 | 50% | 12038 | 0 / 0 / 0 / 0 | 0 / 2 / 2 / 0 / 1 | 0 / 116 / 0 / 80 | 6/45 |
| click | 3.9 | 95% | 19131 | 0 / 0 / 0 / 0 | 0 / 0 / 2 / 0 / 0 | 0 / 121 / 0 / 0 | 2/45 |
| flask | 1.1 | 82% | 6426 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 / 0 | 910 / 7 / 0 / 0 | 2/41 |
| isort | 22.8 | 47% | 17950 | 0 / 0 / 0 / 0 | 17 / 5 / 6 / 5 / 5 | 0 / 499 / 360 / 491 | 8/45 |
| jinja | 1.6 | 124% | 9615 | 0 / 0 / 0 / 0 | 2 / 0 / 2 / 0 / 0 | 34 / 34 / 910 / 910 | 1/45 |
| marshmallow | 1.0 | 135% | 20299 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0/45 |
| more-itertools | 9.4 | 416% | 7747 | 0 / 0 / 0 / 0 | 1 / 0 / 0 / 0 / 0 | 0 / 3 / 3 / 3 | 1/45 |
| pygments | 11.6 | 149% | 53653 | 1 / 1 / 0 / 0 | 424 / 24 / 32 / 11 / 11 | 0 / 0 / 0 / 0 | 0/45 |
| sqlparse | 1.3 | 166% | 8241 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0/45 |
| structlog | 1.3 | 113% | 19276 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0/45 |
| toolz | 1.7 | 465% | 2753 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 / 0 | 6 / 13 / 0 / 4 | 4/39 |
| werkzeug | 6.6 | 31% | 2756 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 / 0 | 199 / 206 / 0 / 0 | 6/45 |

* **Outcome changed although skipped** (MEASURED). Across all 690
  transitions, exactly one skipped test changed outcome, and only under the
  coverage-only rules.
  * The commit was pygments `7c196150` ("fix more unwanted string
    concatenations"). It edited the token tables of four lexer modules
    (class-body attributes in `pygments/lexers/ml.py` and others).
  * At that commit the golden test `tests/examplefiles/fstar/example.fst::`
    went from passed to **failed**.
  * No line of `ml.py` runs during that test, because the regex tables are
    compiled by `pygments/lexer.py`. Coverage-based selection at file *and*
    line level would therefore have skipped the test and reported a stale
    "passed", hiding a real regression. The import-time guard ran it.
  * This is the concrete reason why the coverage-only numbers are not a proof.
* **Executed path changed although skipped** (MEASURED). This check compares,
  for every skipped test, the lines it ran at the new commit with the lines it
  ran at the old commit (renumbered to the new commit). Only lines executed
  while the test itself runs are compared: test and fixture contexts, not
  collection.
  * Some tests also change path when *none* of their loaded modules changed.
    That is run-to-run noise: unseeded randomness in the plain run, hypothesis,
    threads. These tests are excluded: 424 in pygments
    (`test_random_input[...]`), 17 in isort (hypothesis), 18 in attrs.
  * What remains is at noise level for every variant: at most 32 test-commit
    pairs per repository, mostly the same randomised tests.
  * This check found a real hole in the first version of the line rule. In
    isort `f060ea22`, code was inserted right after a nested block, and about
    520 skipped tests per commit really took a different path. The rule was
    fixed (2.3); all numbers above are after the fix.
* **Stale map** (MEASURED). This simulates refreshing the dependency map only
  every 10 commits (map age 1–9) instead of using the previous commit's map.
  An *unsafe* skip is one where the stale map skips a test that the fresh map
  says must run.
  * Coverage-only line rule: unsafe skips in 9 of 14 repositories (up to 499
    test-commit pairs in isort, 456 in arrow, 206 in werkzeug).
  * `line+guard`: unsafe skips in 3 of 14 repositories (910 in jinja, 360 in
    isort, 3 in more-itertools). In jinja, a module added after the refresh
    point and loaded at collection is unknown to the stale map.
  * `line+nameguard`: unsafe skips in 5 of 14 repositories.
  * Conclusion: **a stale map is wrong often enough that it must not be
    used**. The product must re-record the dependencies of every test it runs,
    at every run. This is natural: tests that run are recorded, and tests that
    are skipped keep a map that is still valid because nothing they depend on
    changed.

### 3.3 What limits the skippable share even when nothing changed

These are the shares of all test time that the shared rules alone exclude
(MEASURED, pooled):

* Tests that spawn a subprocess or open an inet socket: 13.8%. Highest are
  isort 30.7%, attrs 24.6% and click 18.3%, mostly CLI tests that run the tool
  as a subprocess.
* Tests not deterministic under `--det`: 12.2%. Highest are werkzeug 68.6%
  (live dev-server tests), boltons 19.2% and isort 12.5%.
* New or renamed tests: 0.2%.

So even a commit that changes nothing leaves about 26% of the test time to run
with the current engine (ESTIMATED from these pooled shares). A syscall-level
backend would recover part of the subprocess share.

### 3.4 Why the guard fires (name-level analysis)

On Python commits, some changed files could not be confined to the callers of
a function. The reasons (MEASURED, each file counted once per reason):

* module or class body statement changed: 522 (assignments, imports, class
  attributes, `__all__`, version strings);
* decorator or annotation changed: 124;
* method added to a class: 94 (it can override an inherited method);
* decorated function added: 79 (a decorator can register it);
* class added or removed: 34;
* class header changed: 6.

## 4. What makes these numbers optimistic or pessimistic

Optimistic (the true proof-grade share is lower):

* **Python-level proof only.** Dependencies outside the Python interpreter are
  not captured:
  * reads done by C extensions;
  * environment variables;
  * files outside the repository (only files below the repository root are
    tracked);
  * changes to installed packages between config changes. Environment drift is
    assumed to be zero: there is one virtualenv per repository, reinstalled
    only when a dependency spec file changed;
  * the Python version and the OS.
* **Determinism is sampled, not proven.** `fingerprint_covered` comes from 10
  `--det` runs at HEAD (round CSV). Tests that no longer exist at HEAD use two
  `--det` runs at commits 0/10/20/30/40/50 (19,134 test-commit decisions; 43
  were unknown and counted as must-run). Rare non-determinism is invisible to
  10 runs.
* **The coverage-only rules are demonstrably unsafe** (3.2). They are an upper
  bound of what can be skipped, not an achievable proof-grade number.
* **The name-level guard rests on assumptions.** It assumes no reflection on
  module or class namespaces: no `dir()`, no `getattr` with computed names, no
  `inspect.getmembers`, no registries filled by `__init_subclass__` of an
  undecorated new class. It also assumes that a function's signature and
  defaults are observable only by its callers.
* **Thread attribution.** Lines run by background threads are credited to the
  test running at that moment (detpy limit P2).
* **Tests that spawn subprocesses** are always run here. A real product that
  could not observe them would have to do the same.

Pessimistic (the true proof-grade share is higher):

* **Strict config rule.** A CI-file edit or a `pyproject.toml` metadata edit
  invalidates everything, which happens on 30% of transitions. Hashing the
  resolved environment and the pytest configuration instead raises the guarded
  median from 0% to 65% (relaxed rule, section 1).
* **First-parent commits of the default branch** are whole merged pull
  requests. CI on pull-request pushes sees smaller diffs, often a single file
  or a test-only change, so more is skippable there (ESTIMATED direction, not
  measured).
* **The guard is coarse.** A module-level change invalidates every test that
  had loaded the module, and most suites import the whole package at
  collection. A finer record of the data each test reads would recover part
  of the gap between the proof-grade line rule (median 0%) and the
  coverage-only one (median 60%). Such a record could, for example, track
  attribute reads on repository modules and classes. The gap itself is the
  upper bound of that prize (ESTIMATED).
* **Small, fast, single-package suites** (1–23 s serial). Large suites in
  monorepos with many independent packages would skip a much larger share,
  because a change in one package is not loaded by the other packages' tests
  (ESTIMATED). boltons is the closest case in the sample: a collection of
  independent modules, with a 77% median under the guard.
* **Collection is never skipped** in this accounting, and neither is plugin
  set-up. A product could cache collection too.

## 5. What this means for the product

* **No, a deterministic runner cannot promise "minutes removed" on the
  typical default-branch commit of a typical Python library.**
  * With a sound rule (`line+guard`), the median commit skips nothing in 11 of
    14 repositories. The exceptions are boltons 77%, more-itertools 42% and
    isort 20% (MEASURED).
  * The average saving is about a quarter of the test time (22–26%, MEASURED).
  * Most of that saving comes from commits that touch no Python code at all,
    and a free path filter in the CI workflow (`paths-ignore`) already skips
    those.
* **Coverage-based selection tools use the coverage-only rule, and this study
  shows a concrete case where that rule hides a real failure** (pygments
  `7c196150`). No vendor claims were checked for this study.
  * The coverage-only line rule reaches median 60% / mean 48%. The
    proof-grade rule reaches median 0% / mean 26%.
  * The gap between the two is exactly the barrier. Closing it soundly needs
    data-dependency tracking below coverage: attribute reads on module and
    class objects, and environment and config hashed at the level the test
    observes.
  * That gap is the prize, and it is measured here: up to about 60 percentage
    points of test time on the median commit, and about 22 points on the mean.
* **Re-record on every run.** Stale maps produce unsafe skips in most
  repositories (3.2), so dependency capture must be part of every run.
  * With coverage.py's C tracer this costs about +107% on the runs that
    execute tests (MEASURED).
  * A cheaper capture (sys.monitoring, per code object instead of per line)
    is therefore a requirement, not an optimisation (ESTIMATED).
* **Configuration handling is worth as much as source analysis.** 30% of
  default-branch transitions touch a config or CI file. Hashing what the test
  process actually sees (resolved environment, pytest options, conftest files)
  instead of whole files moves the proof-grade mean from 26% to 47%
  (MEASURED).

## 6. Reproduce

```
# build the detpy wheel (determinism check for tests missing from the round CSV)
maturin build --release --compatibility linux -o dist
# collection (clone, walk 51 first-parent commits, plain + capture run per commit) and analysis
PY=python3 WORK=/path/to/work OUT=harness/cache_skip/results WHEEL=dist/detpy-*.whl JOBS=3 \
  harness/cache_skip/run_all.sh pygments attrs werkzeug flask click jinja marshmallow arrow \
  structlog more-itertools sqlparse isort toolz boltons
python harness/cache_skip/aggregate.py harness/cache_skip/results   # tables of this report
```

The driver needs `coverage` (to read the coverage data) and `uv`.

* Where it ran: locally on a 4-CPU container, 3 repositories at a time.
  Collection took about 2 hours in total (MEASURED).
* Clean-up: the clones and captures (1.1 GB) were deleted after the analysis.

Repository heads:

| repository | head |
|---|---|
| arrow | `2224255c4acc` |
| attrs | `2a1fb86d4481` |
| boltons | `d31d821d56c8` |
| click | `08b803cf32ce` |
| flask | `49943b5a9441` |
| isort | `eb62da318ea5` |
| jinja | `5ef70112a1ff` |
| marshmallow | `777ff66039fd` |
| more-itertools | `ceafee8ce96f` |
| pygments | `156d85fdd18d` |
| sqlparse | `09dbe1eec31e` |
| structlog | `81779f0abe59` |
| toolz | `451af60dec59` |
| werkzeug | `0f43c6ebd426` |

Deviations from the requested method, and why:

* The dependency map is captured at **every** commit, not every 10. It was
  cheap enough, and it gives the ground truth for the safety checks. The
  every-10 refresh is simulated from it (3.2).
* 51 commits per repository, so that there are 50 transitions.
* Tests absent from the round CSV get their determinism check from 2 `--det`
  runs at every 10th commit. Some of those runs hung (isort at commits 20 and
  50, attrs at 20) on a test waiting on the virtual clock. They were stopped
  after 180 s, and their unfinished tests counted as not deterministic.
* werkzeug: `tests/test_serving.py::test_reloader_sys_path[watchdog]` is
  deselected. It hangs until the timeout in a serial run, and it is not
  deterministic under `--det` either. All suites run with `--timeout=120`
  when pytest-timeout is installed.
* Broken commits:
  * click commits 0–7 have a collection error in `tests/test_basic.py`, a bug
    in the project itself with the current pytest. They are run with
    `--continue-on-collection-errors`, so those tests count as new when they
    reappear.
  * flask commit 13 fails to install (its dependency spec points to a local
    `./werkzeug` checkout), and commit 33 fails at import with a `NameError`.
    4 flask transitions are not evaluated.
  * toolz commits 4–8 fail to install, because an old `setup.py` uses
    `configparser.SafeConfigParser`, which Python 3.12 removed. 6 toolz
    transitions are not evaluated.
* Added beyond the request, because the requested file/line coverage rules
  turned out not to be a proof:
  * the import-time guard and the name-level guard;
  * the `closure` variant;
  * the relaxed config rule;
  * the commit-class breakdown;
  * the two ground-truth safety checks.

## 7. Notes for the coordinator

* The Rust `cache` module (`CacheKey`, `CachePolicy`) assumes a "code digest"
  per test. This study shows that a digest of the files a test *executes* is
  not sufficient (3.2). The digest must also cover the module-level state of
  every module the test had loaded, or a finer record of what the test reads.
* `harness/repos.json` is unchanged. Study-only pytest arguments live in
  `harness/cache_skip/run_repo.py` (`EXTRA_ARGS`).
