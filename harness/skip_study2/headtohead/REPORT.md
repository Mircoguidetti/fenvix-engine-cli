# Head-to-head: competitor-style skip rules vs the fenvix proof rule

**Status: FINAL DRAFT (2026-11-17, numbers being filled in).** See "Runs" for what is in and what is pending.

## The sentence (for the founder)

> **Competitor-style method (coverage, Datadog / Codecov shape): {A_TIME} of test time skipped, {A_WRONG} wrong.
> fenvix proof rule: {C_TIME}, 0 wrong.**

* "Test time skipped" is MEASURED on the real commit history, in a fixed environment. It is the mean over the
  {N_PROJ} projects of each project's mean share per commit: Home Assistant (a 12% sample of its test files), docusaurus,
  vue-core and the 14 libraries of the first study.
* "Wrong" is MEASURED over every arm. Each one is a test file that really fails at that commit while the rule reported
  the cached pass: a stale pass. It is counted as (test file × commit) and confirmed twice at the head and twice at
  the cached commit. They come from:
  * {A_FILES} distinct test files across {A_PROJ} projects;
  * almost all after realistic CI changes that do not touch code (a lockfile bump, a fixture edit, a CI variable),
    plus a root container runner (HOME=/root).
* In a fixed environment with only code changing, the competitor rule made 0 wrong skips (MEASURED). The difference
  between the rules shows only when something outside the code changes.
* The files-read shape (Nx Ultracache) sits in between: {B_TIME} skipped, {B_WRONG} wrong. It sees lockfile bumps and
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

{MAIN_TABLE}

* Every rule made 0 wrong skips on real code changes except **Af on pygments** (MEASURED, h3), one incident:
  * pygments commit 7c19615 ("fix more unwanted string concatenations") edits token tables in lexer class bodies,
    i.e. data at import time, not code inside a function.
  * The fstar golden test (`tests/examplefiles`) starts failing at that commit.
  * Af reported it as passing for 3 commits; every other rule reran it.
  * Function-level coverage cannot see class- or module-level data.
* The competitor shapes skip as much as C or more. A fixed environment cannot tell a proof from a guess apart:
  * A: {A_TIME} vs C: {C_TIME};
  * the per-test coverage variants skip more still (Ae {AE_TIME}, Af {AF_TIME}) on the 15 Python projects.
* flask: the walks of h1 / h3 installed pytest 9.2.0. It removed `_pytest.monkeypatch.notset`, which flask's conftest
  used until July 2026, so 25 of 37 units failed at commits 0-34 and every rule reran them. {FLASK_NOTE}

## Measurement 2: environment changed at every commit (arms `env`, `runtime`, `home-root`; 10 transitions)

The environment alternates between two profiles at every commit:
* `env`: HOME, TZ and LANG;
* `runtime`: another patch release of Python or Node;
* `home-root`: HOME=/root, as on a root container runner.

{ENV_TABLES}

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

| arm | project | change |
|---|---|---|
{SCENARIOS}

**Probe finding (MEASURED, 14 libraries at their first walked commit, each test file in its own process):** the CI
variables that teams commonly set change no test verdict anywhere:
* FORCE_COLOR=1, NO_COLOR=1, TZ=Asia/Kolkata, LANG=C (with LC_ALL=C) and COLUMNS=200: 0 flips.
* PYTHONWARNINGS=error flips files in 5 of 14 libraries: toolz 10 of 14, boltons 3, click 1, pygments 1, sqlparse 1.
* The dependency versions tried flip tests only for flask (the pytest bump) and structlog (rich 13.0):
  * no flips for werkzeug 3.1.0, click 8.1.8 or jinja2 3.1.2 under flask;
  * no flips for markupsafe 2.0 / 2.1 under jinja;
  * no flips for python-dateutil 2.7, tzdata 2022.1, hypothesis 6.80, simplejson 3.17, watchdog 2.3 or freezegun 1.2.

{CI_TABLE}

Cells: broken test files the rule reported as passing / stale passes (test file × commit). The last column is the
share of test time C still skipped at the landing commit.

* **A, Ae, Af (coverage shapes) miss every one of these changes.** A dependency, a data file and a CI variable are
  not code. The broken test files stay green until a code change happens to make the rule rerun them.
* **B (files read) sees lockfile bumps and fixture edits**, because the changed package files and fixtures are read.
  It misses:
  * a CI variable (PYTHONWARNINGS);
  * a package that was absent and appears (structlog: rich 13.0 enters the environment; the test had only tried to
    import it).
* **B+** also catches the appearing package, but still misses the CI variable.
* **C: 0 wrong.** On a fixture edit it reruns only the tests that read the fixture, so it still skips most of the suite
  at the landing commit. On a CI variable or a dependency change it reruns every unit that read it, which is close to
  everything.

## Wrong skips, all of them

{WRONG_LIST}

## Runs

| run | where | what |
|---|---|---|
| h1 | Actions 44123885253 (branch loving-maxwell) | main (50 commits), env, runtime |
| h2 | Actions 44136144219 | home-root |
| h3 | Actions 44150209225 | main re-walk of the 15 Python projects with Ae / Af (replaces h1 main for them) |
| h4 | Actions (branch sweet-mendel), queued | ci arms of flask, docusaurus, vue-core, Home Assistant shards 0-1; flask main with pytest 8.4.2 |
| h5 | Actions (branch sweet-mendel), queued | ci-env PYTHONWARNINGS=error on toolz, boltons, sqlparse, pygments |
| l1 | this session's container (4 CPUs, root, HOME=/root) | the library ci arms, docusaurus / vue-core ci arms, flask main with pytest 8.4.2, walked while h4 / h5 waited for runners. Same walker and specs. |

{RUNS_NOTE}

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
* **Home Assistant** is a 12% sample of test files. The CI change arm runs on 2 of its 8 shards (the ones that hold
  the tests of the changed fixture's integration).
* **Local run l1** runs as root with HOME=/root. docusaurus snapshot tests render the home path; in l1 they run under
  /root in both profiles, so they fail in both and every rule reruns them.
* Not covered by any rule here: wall-clock time (only `detpy --det` covers it), services on loopback, and
  environment variables read from C code.

## Reproduce

```
python3 harness/skip_study2/headtohead/headline.py h1 h2 h3 h4 h5 l1           # the sentence
python3 harness/skip_study2/headtohead/report_tables.py --compact h1 h2 h3 h4 h5 l1
python3 harness/skip_study2/headtohead/h2h_walk.py --spec harness/skip_study2/headtohead/specs/flask.json \
    --work /tmp/w --out /tmp/flask-ci-dep.json.gz --arm ci-dep --max-commits 11     # one CI change arm
```
