DONE

# All runners (P-032): every Python and Node/JS/TS test runner on one engine — report

Branch `claude/all-runners` (fenvix-engine-cli), built from `claude/rust-hotpaths-2` with `claude/node-cache-proof`
merged. Labels: **MEASURED** (GitHub Actions run id or raw file), **ESTIMATED** (derivation), **DECLARED** (source),
**UNKNOWN**. Ranking: [INTERMEDIATE-1.md](INTERMEDIATE-1.md). Design: `docs/ALL-RUNNERS.md`; one document per runner
in `docs/runners/`; builder summaries `docs/runners/BUILD-{python,node-a,node-b,node-c}.md`.

## Answer

* **14 runners, all det + skip with proof.** Python: `unittest`, Django `manage.py test`, nose2, `python -m doctest`,
  zope.testrunner, ward, plus Hypothesis under every runner and pytest. Node/JS/TS: `node --test`, Mocha, tap, AVA,
  Jasmine, uvu, `bun test`, `deno test`. TypeScript runs through tsx, ts-node, `--experimental-strip-types`,
  esbuild-register and @swc-node/register; each loader has adversarial tests under the runners that take loaders.
* **0 wrong reuses in 153,483 verified reuses** on GitHub Actions walks: 30 real repositories (2 per runner, plus 2
  for the TypeScript loaders), 3 to 30 transitions each (MEASURED, runs below). Every would-be reuse was compared with a fresh run of the same commit.
* **Every runner meets the prompt's bar** (adapter for `--det` and `--det-cache`, control tests, adversarial tests,
  walks on 2 real repositories, 0 wrong reuses). The open items are listed with their numbers:
  * ward: two walks (ward 3 transitions, thoughtspot_tml 20) with 0 wrong reuses but **0 reuses**: a start-up
    metadata probe of `pyproject.toml` makes every test rerun after any checkout (row below). ward is 0 of 1,000
    popular Python repositories and 2.6 k downloads a month (MEASURED / DECLARED, INTERMEDIATE-1).
  * **False failures under `--det`** (determinism holds; tests break): hexo (Mocha + ts-node) 58 failing tests
    under `--det` vs 4 under its plain command, back to 4 with `--det-disable=time` (MEASURED local, both window
    ends): the virtual clock against real file modification times is the probable cause, not confirmed. yargs:
    3 `commandDir` tests expect the file system's listing order, which Level 0 sorts. Failed tests are never
    reused, so this costs reuse, not soundness.
  * Karma was not built. It is still used (3.7% of popular JS/TS repositories, MEASURED), but it runs tests in a
    browser, which is Level 2 (P-030).
  * No independent review yet.
* **Shared design held.** Every runner uses the same Rust proof core (store, keys, reuse check, receipts), the
  same fingerprint recorder and the same Level 0 controls. Python runners go through one driver
  (`python/detpy/runners/driver.py`) over the same `CacheSession` as pytest. Node runners go through
  `node/src/session.js`, `ProofSession` and `capture.js`, with thin adapters. Bun and Deno load the same napi
  addon and capture modules.
* **Holes found in the shipped paths and fixed here** (pytest, Vitest, Jest had them too; each fix has a test that
  failed before):
  * Python: path probes (`os.stat`, `exists`, `isdir`, `getsize`, `getmtime`, `access`, `readlink`, `realpath`)
    were not inputs.
  * Python: an optional module appearing was not an input.
  * Python: the Django cached template loader (a template changed but a later renderer was reused; also under
    pytest-django).
  * Python: unittest `TestCase` classes run by pytest are now reused as a whole class.
  * Python: `shutil.rmtree` removals through directory descriptors were taken as writes of project files (lost
    reuse, not wrong).
  * Python: an in-tree `*.egg-info` was counted as an installed distribution, so every version bump reran
    everything (lost reuse).
  * Node: the prior state of exclusive creates, non-recursive `mkdir`, `unlink`, `rm` and `rmdir` was not an input.
  * Node: an optional module appearing in a directory that did not exist was not an input.
  * Node: `process.binding` and the real clocks Level 0 does not virtualize (`process.uptime`, `timeOrigin`, Intl
    "now") did not make a test uncacheable.

## Per-runner tables

Walk columns: transitions = consecutive commit pairs. Skipped = share of test time reused with proof, priced with
each test's duration in the verify run (median / mean over transitions). Verified = would-be reuses compared with a
fresh run. Wrong = reused result different from the fresh one, confirmed by a recheck. All walk numbers are
MEASURED on GitHub Actions (ubuntu-latest, 4 vCPU).

### Python (driver `python -m detpy <runner> --det [--det-cache=DIR]`)

Python walks: run **44568533635** (ar-py-3, after harness fixes) and 44561203094 (ar-py-2, the second doctest
repository); raw `tracks/all-runners-python/results/ar-py-3/`, tables `TABLES.md` there. The earlier run
44560783983 (ar-py-1, also 0 wrong) found harness and capture problems fixed before ar-py-3 (below). Tests:
`tests/test_runners_<runner>.py`, run locally: 204 passed, 1 skipped (MEASURED). Engine suite after integration
(`python -m pytest tests --ignore=tests/rust_hotpaths_ref -p no:randomly`, local, commit 640387f0): 781 passed, 1 failed
(`test_h2_report…`, fails on `claude/rust-hotpaths-2` too), 46 skipped (MEASURED).

| runner | support | control tests | adversarial tests | walk (repository: transitions, skipped median / mean, verified, wrong) | not covered, and why |
|---|---|---|---|---|---|
| `unittest` | det + skip; unit = the `TestCase` class (methods share class state) | 6 pass: two `--det` runs identical fingerprints; same seed same order, other seed other order; clock, seeds, closed network inside tests | 27 shared cases (content, size, mtime, mode, symlink target, realpath, listings incl. recursive, existence probes, optional module appearing, env read and enumeration, child process, socket, TZ, `.git` read, O_EXCL create, sqlite schema clock and `file:` URI, `/dev/shm`, a file another test wrote, failure never reused, verify) + 8 runner cases (class state unit, `setUpClass`/`setUpModule` reads, `load_tests` reads, `-p` change, `-b`, new module, `tearDownClass` error, file written by another test). Fail on a naive adapter (MEASURED): class state, `tearDownClass` error | jc: 20, 0% / 25%, 7,655, **0**; icecream: 20, 0% / 10%, 106, **0** | import-time side effects of one test module on another module's tests (same rule as the pytest plugin) |
| Django | det + skip; DiscoverRunner groups kept; `--parallel` forced to 1 under `--det` | 3 pass | 26 shared (TZ skipped: Django sets TZ from settings) + 4: settings module, migration, JSON fixture, template through the cached loader | django-debug-toolbar: 20, 100% / 80%, 6,014, **0**; django-healthchecks: 20, 16% / 42%, 13,288, **0** | every test depends on the whole environment (`wsgiref` reads all of it at import, as under pytest-django) |
| nose2 | det + skip | 3 pass | 27 shared + 3: configuration file, plugin module change, multiprocess plugin refused | nose2: 20, 21% / 13% (tests 76% / 46%), 3,031, **0**; howdoi: 19, 0% / 0%, 16, **0** (11 tests start processes; the rest are one class) | `layers` and `mp` plugins (refused, exit 4) |
| `python -m doctest` | det + skip (one test per docstring) | 3 pass | 27 shared + 3: text file change, docstring change, option change (configuration) | autopep8: 20, 100% / 85%, 17, **0**; python-nameparser (`python -m doctest README.rst`): 20, 0% / 30%, 6, **0** | — |
| zope.testrunner | det + skip; layers as fixture contexts; `-j` forced to 1 | 3 pass | 27 shared + 3: layer set-up read (and a reused layer is not set up), `test_suite` function reads, `-j` forced to 1 | DateTime: 20, 0% / 36%, 370, **0**; irclog2html: 20, 0% / 40%, 725, **0** | layers resumed in a subprocess (not wired: they run, never reused) |
| ward | det + skip | 3 pass | 27 shared + 1: module-scoped fixture read (fails on a naive adapter, MEASURED) | ward: 3, 0% / 0%, 0 verified, **0** wrong; thoughtspot_tml: 20, 0% / 0%, 0 verified, **0** wrong (run 44593226338, ar-py-4) | **no reuse across commits**: ward's CLI checks `pyproject.toml` with `click.Path` at start-up, so its modification time is an input of every test, and a checkout changes it at every commit (sound, coarse; within one commit 73 of 73 thoughtspot_tml tests are reused, MEASURED local). Proposal: a probe made by the runner's own argument checking keys existence and kind only (needs its own adversarial test). ward's window on its own repository is 4 commits (older ward does not run on Python 3.12+). ward's run loop is a copy of ward 0.68's |
| Hypothesis (all runners + pytest) | seed from the test id; no example database, no storage, no local constants under `--det` | covered by each runner's control tests | — | — (no dedicated walk) | under `--det` the example database and Hypothesis's local storage are off (failures saved by earlier runs are not replayed; details in `docs/runners/hypothesis.md`) |

Python misses explained (ar-py-3, miss reasons per transition): jc and icecream change a module every test loads
at most commits (`code`); DateTime and irclog2html commits are more than 30 days apart, so the designed epoch rule
moves the virtual clock (`clock`); howdoi's 11 process tests are never cached and its other tests form one class
(`unit`).

### Node/JS/TS (`detjs <runner> --det [--det-cache=DIR]`)

Walks: `node --test` + Mocha run **44566685425** (ar-node-1), tap/AVA/Jasmine/uvu run **44566685382** (nb1), Bun/Deno
run **44553242420** (node-c-r1); raw `harness/node_cache/results/<label>/`, tables `TABLES.md` there. Test suites
on the integrated tree, run locally on Node 22.23.5 (MEASURED): cache 45/45, review-r021 32 + 1 skipped, r021-fixes
24/24, controls 16/16, regressions 7/7, unchanged 2/2, jsdom 1/1, projects 1/1, and the runner suites below. Each
workflow's `tests` job also passed on Actions.

| runner | support | control tests | adversarial tests | walk (repository: transitions, skipped median / mean, verified, wrong) | not covered, and why |
|---|---|---|---|---|---|
| `node --test` | det + skip; process per file; `--test-isolation=none`: one process under `--det`, one per file under `--det-cache`; type stripping, tsx, ts-node, `mock.module`, snapshots | 6 pass (identical fingerprints and order, seeds, Level 0 inside, isolation change counted, verify, reporters) | 45 pass: every R-021 F1–F8 + held cases, env, TZ, process, socket, O_EXCL, mkdir, exit-time read, `.git`, sqlite `file:`, unwrapped `fs` from a NODE_OPTIONS preload, real clocks, `/dev/shm`, `process.binding`, `--require`/`--import` setup, `--test-name-pattern`, `--env-file`, `--conditions`, loaders + tsconfig paths, `mock.module`, snapshot, new file. 4 fail on a naive adapter (MEASURED) | commander: 30, 90% / 58%, 22,548, **0**; simple-statistics (isolation=none): 30, 0% / 23%, 3,213, **0** | tests that never begin (filtered/skipped) have no trace line; `--test-global-setup` runs uncached |
| Mocha | det (one process) + skip (fresh process per spec file, events replayed into the user's reporter) | 6 pass (incl. single vs per-file: 1 outcome change counted) | 41 pass: same set + `.mocharc`, `package.json` `mocha`, `--file`, root hooks, `--grep`, new spec, ts-node, tsx, @swc-node, esbuild-register. 3 fail on a naive adapter | dependency-cruiser: 30, 17% / 12% (tests 64%), 28,838, **0**; yargs: 30, 23% / 21%, 7,428, **0** | reporters Mocha refuses in `--parallel` may misbehave under `--det-cache`; one process per file costs ~0.8 s per spec file (dependency-cruiser cold 190 s vs 15 s, MEASURED local NOISY) |
| tap | det + skip (process per file) | 2 pass | 32 shared + 9: `.taprc`, node-arg setup, snapshots, `t.testdir`, `t.mockRequire`, tsx + tsconfig, `--grep`, `before` script, plugins | minimatch: 25, 2% / 20%, 854, **0**; dotenv: 25, 0% / 7%, 750, **0** | tap < 18 refused; within-file order not shuffled (tap starts subtests on declaration) |
| AVA | det + skip (worker thread or process per file; Level 0 and capture in each worker realm) | 2 pass | 33 shared + 7: `ava.config`, `require` setup, snapshots, tsx via `nodeArguments`, `--match`, worker processes, a worker started by a test | globby: 25, 0% / 1%, 235, **0**; shelljs: 25, 0% / 1%, 456, **0** | shared workers never cached; AVA < 6. Low reuse: every globby commit changes the root `package.json` and most files run `git init`; shelljs tests spawn processes |
| Jasmine | det (one process) + skip (process per spec file) | 2 pass | 32 shared + 6: `jasmine.json`, helpers, new helper, `--filter`, `random` replaced, cross-file state | cordova-android: 25, 86% / 69%, 5,860, **0**; xregexp: 20, 0% / 25%, 2,126, **0** | `--parallel` removed under `--det`; jasmine-browser-runner is Level 2 |
| uvu | det (one process) + skip (process per file) | 2 pass | 32 shared + 5: `-r` module, `-r` dropped, `-r tsx/cjs` + tsconfig, named suite, cross-file state | autoprefixer: 25, 15% / 21%, 1,844, **0**; browserslist: 25, 1% / 11%, 1,222, **0** | files run without the uvu CLI; `-r esm` is broken on Node 22 regardless of detjs |
| `bun test` | det + skip (process per file); Bun-native APIs make a file uncacheable unless captured; module graph from Bun's transpiler | 3 pass | 38 pass (Bun.file/write/spawn/Glob/$/env, bun:sqlite, JSON/TOML imports, bunfig, `mock.module`, import map, lockfile, ...); 17 of 41 fail without the Bun capture (10 wrong reuses) | wouter: 20, 25% / 47%, 2,602, **0**; json-schema-faker: 20, 1% / 15%, 1,284, **0** | `BunFile#lastModified` read by a library that never names `Bun.file`; `Bun.env` through an alias the scan misses; `--det-record` refused |
| `deno test` | det + skip (process per file); Deno's permission audit as a completeness check; module graph from `deno info --json` | 3 pass | 33 pass (Deno.readTextFile/stat/readDir/realPath/Command/env/openKv, JSON imports, import map, jsr/npm specifiers, lockfile, ...); 20 of 36 fail without the Deno capture (12 wrong reuses) | std (10 packages, 203 files): 20, 65% / 54%, 22,787, **0**; oak: 20, 34% / 38%, 1,151, **0** | a non-literal dynamic `import()` makes the file uncacheable; `--det-record` refused |
| TS loaders (tsx, ts-node, strip-types, esbuild-register, @swc-node) | through each runner above | — | loader package version and config (tsconfig `paths`, `strict`) are keyed; a changed tsconfig reruns (tests in node-test, Mocha, tap, AVA, uvu suites) | ink (`node --env-file=test/test.env --import=tsx --test`, 106 `.ts/.tsx` files): 30, 22% / 21%, 15,371, **0**; hexo (Mocha + `--require ts-node/register`, 120 `.ts` files): 30, 6% / 6%, 3,686, **0** (run 44596076577, ar-node-2). hexo with the cache is slower than its plain run (warm rerun 324-346 s vs 24-28 s plain: one ts-node process per file, MEASURED Actions) | tsx's first transform starts esbuild's worker thread: that first run is not cached, the next is |
| Karma | none | — | — | — | browser runner: Level 2 (P-030) |

## Timing (MEASURED, Actions; ratio = skip run wall / full verify run wall, median)

commander 0.09 (1 s vs 12 s), Jasmine cordova-android 0.16, Deno std 0.23 (12 s vs 52 s), django-debug-toolbar
0.54, Mocha yargs 0.73, wouter 0.75, uvu autoprefixer 0.79, dependency-cruiser 0.83; AVA, tap and simple-statistics
about 1.0 (little reuse). Cost of the per-file process model where the runner used one process: dependency-cruiser
cold capture 190 s vs 15 s for `--det` (MEASURED local, NOISY); Deno std `--det` 38 s vs 12-15 s plain
`deno test --parallel` (MEASURED, Actions). The capture overhead of the Python driver is +16% to +82% on suites
under 1 s, where start-up dominates (ar-py-3 TABLES.md).

## What I decided, and why

* **Unit of reuse.** A Python `unittest.TestCase` class is reused whole or not at all, because its methods share
  class state; a Node test file is the unit. Runners that put every file in one process (Mocha, Jasmine, uvu,
  `bun test`, `node --test` with isolation none) run each file in its own process under `--det-cache`: skipping
  file A would otherwise change the context file B runs in. The control tests count outcomes that change under
  per-file isolation (1 in each synthetic control; 0 on simple-statistics's real 378 tests).
* **No switch that drops an input.** The Python builder had added `DETPY_CACHE_PROBES=0` for an equivalence test;
  it is replaced by a test-only plugin (`tests/rust_hotpaths_ref/_capref.py`), so the engine has no knob that
  leaves path probes out.
* **Merge of `claude/node-cache-proof`.** Python side kept from `claude/rust-hotpaths-2` (the Rust port). The core
  `proof.rs` keeps every check from both sides (node's `l:`/`p:`/`g:`/`m:`/`r:`/`e:`/`t:`/`c:` kinds and start-up
  digest, the Rust port's memoised checker and `observed`).

## What blocks or is missing

* ward: reuse across commits (the start-up `pyproject.toml` probe, above).
* The per-file process model under `--det-cache` is expensive where the runner used one process and a loader
  compiles each file (hexo, above; dependency-cruiser). A pre-warmed process pool that forks a clean process per
  file is the next step; not built here.
* hexo's `--det` false failures (above) need their cause confirmed and a fix in the shared clock.
* **The shared-cache Python client (`claude/shared-cache`: `remote_cache.py`, R-008c/d start-up rules) is not on
  `claude/rust-hotpaths-2`**, so it is not on this branch either: the node branch's Python tests for it are skipped
  with that reason (15 tests + 3 files). Node's shared cache (`remote.js`) works. The port onto the Rust proof cache
  is a task of its own.
* Python engine suite: the 1 failure that remains also fails on `claude/rust-hotpaths-2` before this work
  (`test_h2_report…`, its recorded results file); `test_rust_clock_is_faster_than_the_reference` (timing) failed in
  2 of 3 earlier runs here and on the base.
* nose 1.x (0.4% of the sample) not built (not on the prompt's list).
* Not run: an independent review.

## Links

* Repository Mircoguidetti/fenvix-engine-cli, branch `claude/all-runners`, last engine code commit 0fb046a2 (merged at 640387f0);
  walk results and this report follow it on the same branch.
* Actions runs: 44536402831 (download statistics), 44553242420 (Bun, Deno), 44560783983 / 44561203094 /
  44568533635 / 44593226338 (Python), 44566685425 (`node --test`, Mocha), 44566685382 (tap, AVA, Jasmine, uvu),
  44596076577 (TypeScript loaders: ink, hexo).
* Main files: `python/detpy/runners/`, `python/detpy/_level0.py`, `python/detpy/_proof.py`, `python/detpy/_django.py`,
  `node/src/{nodetest,mocha}/`, `node/src/runners/`, `node/src/cache/capture.js`, `crates/detpy-core/src/proof.rs`,
  `harness/cache_proof/walk.py`, `harness/node_cache/walk.py`, `.github/workflows/all-runners-*.yml`.

## Errors or gaps in the brain

* `NOW.md` says the shared cache across machines is DONE. It is not on the latest Python engine
  (`claude/rust-hotpaths-2`), only on `claude/shared-cache` / `claude/node-cache-proof` (see above).
* `ARCHITECTURE.md` "Header meta, required: runner (`pytest`, `vitest`, `jest`)": the runner list now also has
  `unittest`, `django`, `nose2`, `doctest`, `zope-testrunner`, `ward`, `node-test`, `mocha`, `tap`, `ava`,
  `jasmine`, `uvu`, `bun-test`, `deno-test`.
