# Head-to-head: competitor-style skip rules vs the fenvix proof rule

**Status: FINAL (2026-11-18).** Numbers from runs h1, h2, h3, l1. See "Runs" for what is in and what is pending.

## The sentence (for the founder)

> **Competitor-style method (coverage, Datadog / Codecov shape): 51% of test time skipped, 375 wrong.
> fenvix proof rule: 41%, 0 wrong.**

* "Test time skipped" is MEASURED on the real commit history, in a fixed environment. It is the mean over the
  17 projects of each project's mean share per commit: Home Assistant (a 12% sample of its test files), docusaurus,
  vue-core and the 14 libraries of the first study.
* "Wrong" is MEASURED over every arm. Each one is a test file that really fails at that commit while the rule reported
  the cached pass: a stale pass. It is counted as (test file × commit) and confirmed twice at the head and twice at
  the cached commit. They come from:
  * 73 test files (each counted once per arm) across 10 projects;
  * almost all after realistic CI changes that do not touch code (a lockfile bump, a fixture edit, a CI variable),
    plus a root container runner (HOME=/root).
* Counted per change instead of per stale pass: 14 of the 16 CI changes walked broke at least one test file (MEASURED). Changes each rule missed (it kept reporting a broken test file as passing): A 14 of 14, Ae 12 of 12, Af 12 of 12, B 6 of 14, B+ 5 of 14, C 0 of 14 (Ae and Af run on the Python projects only).
* The count depends on how many test files a change breaks and for how many commits it stays: one change (docusaurus, NODE_ENV=production, 25 test files x 8 commits) gives 200 of A's 375. Without it A has 175 wrong.
* In a fixed environment with only code changing, A, Ae, B and B+ made 0 wrong skips (MEASURED). Af (function
  level) made 25 in two incidents, both code at class or module level (see measurement 1). Otherwise the difference
  between the rules shows only when something outside the code changes.
* The files-read shape (Nx Ultracache) sits in between: 44% skipped, 257 wrong. It sees lockfile bumps and
  fixture edits; it misses CI variables, a newly installed package and HOME.

## Rules compared

All rules run on the same commits and the same machine. Each rule keeps its own cache: the record of the last run
it asked for. Every rule reruns new units and never reuses a cached failure. A unit is one test file run in its own
process.

| rule | shape | reruns a unit only when |
|---|---|---|
| **A** | Datadog Test Impact Analysis / Codecov ATS, file level (DECLARED by the vendors' docs, coordinator's notes) | a repository source-code file it loaded changed. It does not see installed packages, data files, config, environment variables, runtime or network. |
| **Ae** | per-test coverage, file level (Python) | a changed `.py` file is the unit's own file, or one in which it executed a function |
| **Af** | Codecov ATS, function level (Python) | its own file changed, or the definition of a function it executed changed |
| **B** | Nx Ultracache, literal "files read" | a file it opened read-only changed (repository, virtualenv, node_modules). It does not see environment variables, read-write opens, network, runtime, stats, missing paths or listings. |
| **B+** | Nx, generous | B plus stats, missing paths, directory listings and Python import resolution |
| **C** | **fenvix closure v3** (proof rule, `walk.Walker.decide` unchanged) | anything in its closure changed: files read (also read-write), stats, missing paths, listings, imports, environment variables read, runtime identity. A unit that connected to a non-loopback address is never skipped. |

## Measurement 1: fixed environment, real history (arm `main`)

Cells: share of test time skipped per commit, median / mean (MEASURED); bold = confirmed stale passes.

| project | commits | A | Ae | Af | B | B+ | C |
|---|---:|---:|---:|---:|---:|---:|---:|
| home-assistant | 50 | 100% / 92% | 100% / 98% | 100% / 98% | 100% / 90% | 98% / 82% | 98% / 82% |
| docusaurus | 50 | 100% / 92% | n/a | n/a | 98% / 81% | 98% / 81% | 98% / 81% |
| vue-core | 50 | 25% / 51% | n/a | n/a | 25% / 31% | 25% / 31% | 25% / 31% |
| arrow | 50 | 0% / 35% | 0% / 40% | 77% / 73% | 0% / 29% | 0% / 29% | 0% / 29% |
| attrs | 50 | 100% / 72% | 100% / 74% | 100% / 80% | 0% / 46% | 0% / 46% | 0% / 46% |
| boltons | 50 | 97% / 85% | 97% / 93% | 97% / 95% | 97% / 85% | 95% / 84% | 95% / 84% |
| click | 50 | 0% / 37% | 10% / 40% | 86% / 58% | 0% / 30% | 0% / 30% | 0% / 30% |
| flask | 49 | 0% / 45% | 1% / 46% | 97% / 72% **(22 wrong, 22 files)** | 0% / 37% | 0% / 37% | 0% / 37% |
| isort | 50 | 1% / 27% | 7% / 35% | 64% / 58% | 1% / 27% | 0% / 7% | 0% / 1% |
| jinja | 50 | 77% / 62% | 77% / 69% | 78% / 75% | 77% / 58% | 77% / 56% | 77% / 56% |
| marshmallow | 50 | 86% / 69% | 86% / 69% | 86% / 74% | 86% / 59% | 86% / 58% | 86% / 58% |
| more-itertools | 50 | 0% / 17% | 0% / 19% | 69% / 65% | 0% / 15% | 0% / 15% | 0% / 15% |
| pygments | 50 | 17% / 32% | 29% / 46% | 100% / 94% **(3 wrong, 1 files)** | 17% / 32% | 17% / 32% | 17% / 32% |
| sqlparse | 50 | 0% / 33% | 28% / 49% | 96% / 68% | 0% / 25% | 0% / 23% | 0% / 23% |
| structlog | 50 | 76% / 61% | 76% / 64% | 76% / 68% | 76% / 47% | 76% / 47% | 76% / 47% |
| toolz | 45 | 80% / 50% | 80% / 61% | 82% / 81% | 0% / 38% | 0% / 34% | 0% / 34% |
| werkzeug | 50 | 0% / 16% | 0% / 29% | 61% / 56% | 0% / 13% | 0% / 8% | 0% / 8% |

* Every rule made 0 wrong skips on real code changes except **Af on pygments** (MEASURED, h3), one incident:
  * pygments commit 7c19615 ("fix more unwanted string concatenations") edits token tables in lexer class bodies,
    i.e. data at import time, not code inside a function.
  * The fstar golden test (`tests/examplefiles`) starts failing at that commit.
  * Af reported it as passing for 3 commits; every other rule reran it.
  * Function-level coverage cannot see class- or module-level data.
* The competitor shapes skip as much as C or more. A fixed environment cannot tell a proof from a guess apart:
  * A: 51% vs C: 41%;
  * the per-test coverage variants skip more still (Ae 55%, Af 74%) on the 15 Python projects.
* flask: the walks of h1 / h3 installed pytest 9.2.0. It removed `_pytest.monkeypatch.notset`, which flask's conftest
  used until July 2026, so 25 of 37 units failed at commits 0-34 and every rule reran them. flask was therefore re-walked with pytest pinned to 8.4.2 (`make_specs.py` EXTRA; run l1); the l1 walk replaces the h1 / h3 flask walks in every number here.

## Measurement 2: environment changed at every commit (arms `env`, `runtime`, `home-root`; 10 transitions)

The environment alternates between two profiles at every commit:
* `env`: HOME, TZ and LANG;
* `runtime`: another patch release of Python or Node;
* `home-root`: HOME=/root, as on a root container runner.

**arm `env`** (time skipped median / mean per commit; bold = confirmed stale passes)

| project | commits | A | Ae | Af | B | B+ | C |
|---|---:|---:|---:|---:|---:|---:|---:|
| home-assistant | 10 | 100% | n/a | n/a | 100% | 85% | 0% |
| docusaurus | 10 | 99% | n/a | n/a | 99% | 99% | 0% |
| vue-core | 10 | 29% | n/a | n/a | 29% | 29% | 0% |
| arrow | 10 | 15% | n/a | n/a | 8% | 8% | 0% |
| attrs | 10 | 80% | n/a | n/a | 60% | 59% | 0% |
| boltons | 10 | 77% | n/a | n/a | 77% | 75% | 0% |
| click | 10 | 29% | n/a | n/a | 29% | 29% | 0% |
| flask | 10 | 0% | n/a | n/a | 0% | 0% | 0% |
| isort | 10 | 30% | n/a | n/a | 30% | 9% | 0% |
| jinja | 10 | 54% | n/a | n/a | 53% | 53% | 0% |
| marshmallow | 10 | 88% | n/a | n/a | 80% | 80% | 0% |
| more-itertools | 10 | 0% | n/a | n/a | 0% | 0% | 0% |
| pygments | 10 | 48% | n/a | n/a | 48% | 48% | 0% |
| sqlparse | 10 | 50% | n/a | n/a | 50% | 43% | 0% |
| structlog | 10 | 47% | n/a | n/a | 33% | 33% | 0% |
| toolz | 5 | 56% | n/a | n/a | 56% | 41% | 0% |
| werkzeug | 10 | 10% | n/a | n/a | 10% | 6% | 0% |

**arm `runtime`** (time skipped median / mean per commit; bold = confirmed stale passes)

| project | commits | A | Ae | Af | B | B+ | C |
|---|---:|---:|---:|---:|---:|---:|---:|
| home-assistant | 10 | 100% | n/a | n/a | 0% | 0% | 0% |
| docusaurus | 10 | 99% | n/a | n/a | 99% | 99% | 0% |
| vue-core | 10 | 30% | n/a | n/a | 30% | 30% | 0% |
| arrow | 10 | 15% | n/a | n/a | 0% | 0% | 0% |
| attrs | 10 | 80% | n/a | n/a | 0% | 0% | 0% |
| boltons | 10 | 78% | n/a | n/a | 0% | 0% | 0% |
| click | 10 | 29% | n/a | n/a | 0% | 0% | 0% |
| flask | 10 | 0% | n/a | n/a | 0% | 0% | 0% |
| isort | 10 | 30% | n/a | n/a | 0% | 0% | 0% |
| jinja | 10 | 54% | n/a | n/a | 0% | 0% | 0% |
| marshmallow | 10 | 89% | n/a | n/a | 0% | 0% | 0% |
| more-itertools | 10 | 0% | n/a | n/a | 0% | 0% | 0% |
| pygments | 10 | 48% | n/a | n/a | 0% | 0% | 0% |
| sqlparse | 10 | 50% | n/a | n/a | 0% | 0% | 0% |
| structlog | 10 | 51% | n/a | n/a | 0% | 0% | 0% |
| toolz | 5 | 56% | n/a | n/a | 0% | 0% | 0% |
| werkzeug | 10 | 10% | n/a | n/a | 0% | 0% | 0% |

**arm `home-root`** (time skipped median / mean per commit; bold = confirmed stale passes)

| project | commits | A | Ae | Af | B | B+ | C |
|---|---:|---:|---:|---:|---:|---:|---:|
| home-assistant | 10 | 100% | n/a | n/a | 100% | 84% | 0% |
| docusaurus | 10 | 99% **(15 wrong, 3 files)** | n/a | n/a | 99% **(15 wrong, 3 files)** | 99% **(15 wrong, 3 files)** | 0% |
| vue-core | 10 | 30% | n/a | n/a | 30% | 30% | 0% |
| arrow | 10 | 15% | n/a | n/a | 7% | 7% | 0% |
| attrs | 10 | 80% | n/a | n/a | 60% | 60% | 0% |
| boltons | 10 | 77% | n/a | n/a | 77% | 75% | 75% |
| click | 10 | 29% | n/a | n/a | 29% | 29% | 24% |
| flask | 10 | 0% | n/a | n/a | 0% | 0% | 0% |
| isort | 10 | 30% | n/a | n/a | 30% | 6% | 0% |
| jinja | 10 | 55% | n/a | n/a | 55% | 55% | 55% |
| marshmallow | 10 | 89% | n/a | n/a | 80% | 80% | 0% |
| more-itertools | 10 | 0% | n/a | n/a | 0% | 0% | 0% |
| pygments | 10 | 48% | n/a | n/a | 48% | 48% | 48% |
| sqlparse | 10 | 50% | n/a | n/a | 50% | 44% | 44% |
| structlog | 10 | 52% | n/a | n/a | 37% | 37% | 0% |
| toolz | 5 | 54% | n/a | n/a | 54% | 40% | 30% |
| werkzeug | 10 | 10% | n/a | n/a | 10% | 6% | 6% |

* `env` and `runtime`: 0 wrong for every rule (MEASURED). No test outcome depended on those variables or patch
  releases.
* `home-root`, docusaurus: A, B and B+ reused 3 stale passes (15 test file × commit, each confirmed at both commits).
  The snapshots render `/root/...` paths. C reran those units.
* **Cost of the proof (MEASURED):** when the environment changes at every commit, C reruns every unit whose process
  read a changed variable or runtime, so close to everything (0% skipped). The competitor rules keep skipping, and
  here they were right except on docusaurus `home-root`.
  * For the product this means: keep the CI environment stable (our own runners, `runs-on: fenvix`), and the proof
    costs nothing (measurement 1).

## Measurement 3: realistic CI changes that do not touch the code (arms `ci-dep`, `ci-data`, `ci-env`)

**Design.**
* A change from `changes.json` lands at commit 3 of an 11-commit window **as a commit of its own**: the previous
  commit's code plus only the change, as a Dependabot lockfile bump or a fixture-only commit lands. It then stays for
  the rest of the window.
* Every unit runs fresh at every commit (verification 100%), so every skip of every rule is checked.
* A stale pass counts only when it is confirmed: the head re-runs fail twice, and the cached commit, re-run in the
  cached profile, passes twice.
* The scenarios were chosen because they change test behaviour (local probes, `probes/PROBES.txt`). The question is
  not how often such changes happen, but whether each rule notices when one does.

**Scenarios (each DECLARED realistic by this study; each probed to flip at least one test file):**

| arm | project | change | test files it broke (MEASURED) |
|---|---|---|---:|
| ci-dep | flask | lockfile bump of the test runner: pytest 8.4.2 -> 9.1.1 (pytest 9.1 removed _pytest.monkeypatch.notset, which flask's conftest used until July 2026) | 21 |
| ci-dep | structlog | a dependency resolution change adds rich 13.0.0 to the test environment (it was absent; e.g. another dev tool pulls it in with an upper bound); structlog's dev console renderer uses rich when it can import it, and rich 13.0 lacks newer keywords (rich 15.0 passes) | 1 |
| ci-data | docusaurus | blog content fixture (website/blog/2018-12-14-Happy-First-Birthday-Slash.md): post title reworded | 1 |
| ci-data | flask | shared template fixture tests/templates/simple_template.html: <h1> -> <h2> | 2 |
| ci-data | home-assistant | shared integration fixture tests/components/bring/fixtures/items.json: the first item's 'urgent' flag true -> false | 1 |
| ci-data | jinja | shared template fixture tests/res/templates/test.html: BAR -> BAZ | 1 |
| ci-data | pygments | example input tests/examplefiles/awk/test.awk: a comment is reworded, its golden .output is not regenerated | 1 |
| ci-data | sqlparse | shared SQL fixture tests/files/begintag.sql gains a statement | 1 |
| ci-data | werkzeug | recorded HTTP request fixture tests/multipart/firefox3-2png1txt/request.http: the text field 'example text' -> 'example text v2' | 1 |
| ci-env | boltons | the CI job turns warnings into errors: PYTHONWARNINGS=error | 3 |
| ci-env | click | the CI job turns warnings into errors: PYTHONWARNINGS=error | 0 |
| ci-env | docusaurus | NODE_ENV=production exported by the CI job (e.g. for a build step) and inherited by the test step | 25 |
| ci-env | pygments | the CI job turns warnings into errors: PYTHONWARNINGS=error | 1 |
| ci-env | sqlparse | the CI job turns warnings into errors: PYTHONWARNINGS=error | 1 |
| ci-env | toolz | the CI job turns warnings into errors: PYTHONWARNINGS=error | 10 |
| ci-env | vue-core | NODE_ENV=production exported by the CI job (e.g. for a build step) and inherited by the test step | 0 |

**Probe finding (MEASURED, 14 libraries at their first walked commit, each test file in its own process):** the CI
variables that teams commonly set change no test verdict anywhere:
* FORCE_COLOR=1, NO_COLOR=1, TZ=Asia/Kolkata, LANG=C (with LC_ALL=C) and COLUMNS=200: 0 flips.
* PYTHONWARNINGS=error flips files in 5 of 14 libraries: toolz 10 of 14, boltons 3, click 1, pygments 1, sqlparse 1.
* The dependency versions tried flip tests only for flask (the pytest bump) and structlog (rich 13.0):
  * no flips for werkzeug 3.1.0, click 8.1.8 or jinja2 3.1.2 under flask;
  * no flips for markupsafe 2.0 / 2.1 under jinja;
  * no flips for python-dateutil 2.7, tzdata 2022.1, hypothesis 6.80, simplejson 3.17, watchdog 2.3 or freezegun 1.2.

| change | project | test files broken | A | Ae | Af | B | B+ | C | C: time skipped at landing |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| dep | flask | 21 | **21 / 84** | **21 / 88** | **21 / 140** | 0 | 0 | 0 | 0% |
| dep | structlog | 1 | **1 / 1** | **1 / 1** | **1 / 1** | **1 / 1** | 0 | 0 | 0% |
| data | docusaurus | 1 | **1 / 8** | n/a | n/a | 0 | 0 | 0 | 97% |
| data | flask | 2 | **2 / 8** | **2 / 8** | **2 / 9** | 0 | 0 | 0 | 88% |
| data | home-assistant | 1 | **1 / 8** | **1 / 8** | **1 / 8** | 0 | 0 | 0 | 92% |
| data | jinja | 1 | **1 / 5** | **1 / 5** | **1 / 6** | 0 | 0 | 0 | 74% |
| data | pygments | 1 | **1 / 2** | **1 / 2** | **1 / 2** | 0 | 0 | 0 | 60% |
| data | sqlparse | 1 | **1 / 1** | **1 / 3** | **1 / 6** | 0 | 0 | 0 | 92% |
| data | werkzeug | 1 | **1 / 2** | **1 / 2** | **1 / 2** | 0 | 0 | 0 | 59% |
| env | boltons | 3 | **3 / 18** | **3 / 24** | **3 / 24** | **3 / 18** | **3 / 18** | 0 | 0% |
| env | click | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0% |
| env | docusaurus | 25 | **25 / 200** | n/a | n/a | **25 / 200** | **25 / 200** | 0 | 0% |
| env | pygments | 1 | **1 / 2** | **1 / 2** | **1 / 2** | **1 / 2** | **1 / 2** | 0 | 0% |
| env | sqlparse | 1 | **1 / 1** | **1 / 1** | **1 / 1** | **1 / 1** | **1 / 1** | 0 | 0% |
| env | toolz | 10 | **10 / 20** | **10 / 20** | **10 / 21** | **10 / 20** | **10 / 10** | 0 | 0% |
| env | vue-core | 0 | 0 | n/a | n/a | 0 | 0 | 0 | 0% |

Cells: broken test files the rule reported as passing / stale passes (test file × commit). The last column is the
share of test time C still skipped at the landing commit.

* **A, Ae, Af (coverage shapes) miss every one of these changes.** A dependency, a data file and a CI variable are
  not code. The broken test files stay green until a code change happens to make the rule rerun them.
* **B (files read) sees lockfile bumps and fixture edits**, because the changed package files and fixtures are read.
  It misses:
  * a CI variable (PYTHONWARNINGS, NODE_ENV);
  * a package that was absent and appears (structlog: rich 13.0 enters the environment; the test had only tried to
    import it).
* **B+** also catches the appearing package, but still misses the CI variable.
* **C: 0 wrong.** On a fixture edit it reruns only the tests that read the fixture, so it still skips most of the suite
  at the landing commit. On a CI variable or a dependency change it reruns every unit that read it, which is close to
  everything.
  After the landing commit C goes back to skipping: over the commits after it, C skipped 39% of test time on average across the 16 changes (A 58%, B 51%; MEASURED). Part of A's extra share is the stale passes themselves; a test file that stays broken is rerun at every commit by every rule that saw it fail, because no rule reuses a failure.

## Wrong skips, all of them

| arm | project | rules that reported a stale pass (test files / test file x commit) | rules that reran | cause |
|---|---|---|---|---|
| main | flask | Af 22 files / 22 | A, Ae, B, B+, C | commit 954f568 (2026-05-18): a class-level NameError in `src/flask/cli.py` breaks the import of flask, so every test file errors at collection; Af saw no executed function change |
| main | pygments | Af 1 files / 3 | A, Ae, B, B+, C | commit 7c19615: token tables in lexer class bodies changed; the fstar golden test fails |
| home-root | docusaurus | A 3 files / 15, B 3 files / 15, B+ 3 files / 15 | C | HOME=/root: snapshot and path tests render the home directory |
| ci-dep | flask | A 21 files / 84, Ae 21 files / 88, Af 21 files / 140 | B, B+, C | lockfile bump of the test runner: pytest 8.4.2 -> 9.1.1 (pytest 9.1 removed _pytest.monkeypatch.notset, which flask's conftest used until July 2026) |
| ci-dep | structlog | A 1 files / 1, Ae 1 files / 1, Af 1 files / 1, B 1 files / 1 | B+, C | a dependency resolution change adds rich 13.0.0 to the test environment (it was absent; e.g. another dev tool pulls it in with an upper bound); structlog's dev console renderer uses rich when it can import it, and rich 13.0 lacks newer keywords (rich 15.0 passes) |
| ci-data | docusaurus | A 1 files / 8 | B, B+, C | blog content fixture (website/blog/2018-12-14-Happy-First-Birthday-Slash.md): post title reworded |
| ci-data | flask | A 2 files / 8, Ae 2 files / 8, Af 2 files / 9 | B, B+, C | shared template fixture tests/templates/simple_template.html: <h1> -> <h2> |
| ci-data | home-assistant | A 1 files / 8, Ae 1 files / 8, Af 1 files / 8 | B, B+, C | shared integration fixture tests/components/bring/fixtures/items.json: the first item's 'urgent' flag true -> false |
| ci-data | jinja | A 1 files / 5, Ae 1 files / 5, Af 1 files / 6 | B, B+, C | shared template fixture tests/res/templates/test.html: BAR -> BAZ |
| ci-data | pygments | A 1 files / 2, Ae 1 files / 2, Af 1 files / 2 | B, B+, C | example input tests/examplefiles/awk/test.awk: a comment is reworded, its golden .output is not regenerated |
| ci-data | sqlparse | A 1 files / 1, Ae 1 files / 3, Af 1 files / 6 | B, B+, C | shared SQL fixture tests/files/begintag.sql gains a statement |
| ci-data | werkzeug | A 1 files / 2, Ae 1 files / 2, Af 1 files / 2 | B, B+, C | recorded HTTP request fixture tests/multipart/firefox3-2png1txt/request.http: the text field 'example text' -> 'example text v2' |
| ci-env | boltons | A 3 files / 18, Ae 3 files / 24, Af 3 files / 24, B 3 files / 18, B+ 3 files / 18 | C | the CI job turns warnings into errors: PYTHONWARNINGS=error |
| ci-env | docusaurus | A 25 files / 200, B 25 files / 200, B+ 25 files / 200 | C | NODE_ENV=production: 19 React component test files (.tsx) and 6 others (blog and pages plugins, theme utils, emitUtils, route codegen) fail; the root cause inside React or the test setup was not investigated |
| ci-env | pygments | A 1 files / 2, Ae 1 files / 2, Af 1 files / 2, B 1 files / 2, B+ 1 files / 2 | C | the CI job turns warnings into errors: PYTHONWARNINGS=error |
| ci-env | sqlparse | A 1 files / 1, Ae 1 files / 1, Af 1 files / 1, B 1 files / 1, B+ 1 files / 1 | C | the CI job turns warnings into errors: PYTHONWARNINGS=error |
| ci-env | toolz | A 10 files / 20, Ae 10 files / 20, Af 10 files / 21, B 10 files / 20, B+ 10 files / 10 | C | the CI job turns warnings into errors: PYTHONWARNINGS=error |

## Runs

| run | where | what |
|---|---|---|
| h1 | Actions 44123885253 (branch loving-maxwell) | main (50 commits), env, runtime |
| h2 | Actions 44136144219 | home-root |
| h3 | Actions 44150209225 (branch loving-maxwell), completed | main re-walk of the 15 Python projects with Ae / Af (replaces h1 main for them); all 8 Home Assistant shards, 50 commits |
| h4 | Actions 44185950625 (branch sweet-mendel), started at about 01:00 UTC, still running when this report was written | the same ci arms as l1 on GitHub-hosted runners (non-root). Used as a replication, not in the numbers. |
| h5 | Actions 44186036349 (branch sweet-mendel), queued when this report was written | ci-env PYTHONWARNINGS=error on toolz, boltons, sqlparse, pygments (also in l1). Not used. |
| l1 | this session's container (4 CPUs, root, HOME=/root) | every ci arm in this report (15 arms + Home Assistant shards 0-1), and flask main with pytest 8.4.2. Same walker and specs as the Actions runs. |

**Replication (MEASURED).** h4 and h5 waited in the Actions queue for about three hours behind other sessions' jobs
(the account's concurrent-runner cap), so every CI arm was walked in l1, this session's container, instead. h4 started
at about 01:00 UTC. When this report was written, 7 of its CI arms had finished on GitHub-hosted (non-root) runners:
flask ci-dep, structlog ci-dep, and the ci-data arms of docusaurus, jinja, pygments, sqlparse and werkzeug.

On all 7, every rule missed exactly the same broken test files, with the same stale-pass counts, as in l1. C's time
skipped at landing differs by at most 3 points. The rest of h4 and h5 are not in the numbers. `headline.py` takes a
later run id over an earlier one for the same (project, arm), so put l1 last if h4 / h5 are added.

## Caveats

* **Scenario selection.** Each change was picked because it flips at least one test. Measurement 3 says what each
  rule does when such a change lands, not how often one lands. The probe finding says that most common CI variables
  flip nothing: there the competitor shapes would have been right, and C would have rerun for nothing.
* **Competitor configurations.** A team might set its tool to run everything when a lockfile changes, where the tool
  allows it (not checked against the vendors' docs; UNKNOWN). With that setting, A would catch the flask lockfile bump
  at the cost of rerunning 100% of the suite on every lockfile change. It would still miss:
  * unpinned dependency drift;
  * the CI variable;
  * fixture edits that are not listed.
* **Shapes, not products.** A, Ae, Af, B and B+ follow what the vendors document, not their code. A takes every
  repository source file a unit's process opened, so it skips at most what a coverage tool would skip. Ae and Af
  approximate per-test coverage with function entries (sys.monitoring PY_START).
* **Home Assistant** is a 12% sample of test files. Its CI change arm (l1) runs on 2 of its 8 shards, the ones that
  hold the tests of the changed fixture's integration.
* **Local run l1** runs as root with HOME=/root. docusaurus snapshot tests render the home path; in l1 they run under
  /root in both profiles, so they fail in both and every rule reruns them.
* Not covered by any rule here: wall-clock time (only `detpy --det` covers it), services on loopback, and
  environment variables read from C code.

## Reproduce

```
python3 harness/skip_study2/headtohead/headline.py h1 h2 h3 l1                 # the sentence
python3 harness/skip_study2/headtohead/report_tables.py --compact h1 h2 h3 l1
python3 harness/skip_study2/headtohead/report_tables.py --compact h4          # the replication
python3 harness/skip_study2/headtohead/h2h_walk.py --spec harness/skip_study2/headtohead/specs/flask.json \
    --work /tmp/w --out /tmp/flask-ci-dep.json.gz --arm ci-dep --max-commits 11     # one CI change arm
```
