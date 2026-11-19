# Build summary: node-b (tap, AVA, Jasmine, uvu)

Branch `ar-node-b` (based on `claude/node-cache-proof`). Labels: **MEASURED** (local, this container, 4 shared CPUs:
NOISY), **UNKNOWN** (not yet run on GitHub Actions). Per-runner documents: `docs/runners/{tap,ava,jasmine,uvu}.md`.

## Shared design used (no per-runner copies)

* `node/src/runners/common.js` (new): runner-neutral glue. Main side `runShell(spec, argv)`: options
  (`session.parseArgs`), `session.prepare`, `ProofSession` (unchanged), discovery by the runner itself in list mode
  (`listChild`), order (sorted / `shuffle_indices`), `pc.decide`, launch with `NODE_OPTIONS=--require preload.js`,
  `pc.finish`, `session.finish` (trace merge). Child side: `child()` (Level 0 `installProcess`/`installRealm`, capture
  `install({role: 'worker'})`), `ChildFile` (trace part via `controls.openFile`, per-test `STATE.beginTest/endTest`,
  `CAPTURE.testEnd`, capture file written at the file's end, rewritten as failed on a non-zero exit), `markFailed`
  (runner-reported failures).
* `node/src/runners/preload.js` (new): dispatch by `DETJS_RUNNER` / `DETJS_RUNNER_ROLE` (`runner`, `list`, `child`,
  `single`; `nested` for processes a test starts, which also get the user's NODE_OPTIONS back).
* Adapters (thin): `node/src/runners/{tap,ava,jasmine,uvu}.js` (discovery, order, lifecycle hooks, config parts).

## Per runner

### tap (node-tap 18+, built against 21.8)

| support | det + skip (file unit; process per file, as tap) |
|---|---|
| control tests | `two --det runs give identical fingerprints; clock, seeds and closed network active in tests`; `seeded shuffle: the same seed gives the same order, another seed another order` (file order; tap's within-file order is declaration order, see tap.md) |
| adversarial tests | 32 shared cases (`runner-b-cases.js`: content, module, FileHandle, F1a stat size, stat mode, stat mtime (never cached), F1b realpath, F1c lstat, listing, F2a recursive, F2b withFileTypes, existence probe, O_EXCL create, mkdir without recursive, F5 caught require, F3a openAsBlob, F3b loadEnvFile, F3c node:sqlite, F4 cpSync, F8 outside glob library, held fs.globSync, held after-all hook read, env read, env enumeration, TZ, child process, loopback socket, /dev/shm, file written by another test file, new test file, failure never reused, verify mode) + 9 tap cases (`.taprc` test-env, node-arg setup module, snapshot file `tap-snapshots/`, `t.testdir`, `t.mockRequire`, tsx loader + tsconfig paths, `--grep` filter, `before` script never cached, plugin set) |
| pass counts | see the table at the end (MEASURED, local) |
| would fail on a naive adapter | O_EXCL create and mkdir (wrong reuse before the capture's prior-state inputs); seeded order (tap's own order follows `stat` completion); every ESM test that uses `t.mockImport` (synchronous loader hooks dead-lock it: timeouts on isaacs/minimatch); control test (tap fails a run with no coverage: detjs adds `--disable-coverage` with `--det-cache` only) |
| walk specs | `tap-minimatch` (isaacs/minimatch, 26 first-parent commits up to 2026-11-16), `tap-dotenv` (motdotla/dotenv, 26 up to 2026-11-08) |
| local mini-walk | motdotla/dotenv, commits 22..25 (4 commits, 3 transitions), MEASURED local NOISY: test time skipped median 0% / mean 5% (5 of 10 files spawn processes: never cached; package.json changes), 78 reuses verified, **0 wrong**; warm rerun reused 5/10 files; plain 31.83 s, detjs --det 57.42 s, cold capture 53.98 s; commit 23 fails one test of tests/test-cli.js in verify and skip runs alike. Raw: `harness/node_cache/results/local-node-b/tap-dotenv-0.json.gz`. Found and fixed with it: the user's `--disable-coverage` was dropped, and `--save` kept stale coverage (exit 1 with all tests passing) |
| not covered | tap 16 and older (refused); within-file shuffle (tap starts subtests on declaration); `before`/`after` scripts (uncacheable) |

### AVA (6+, built against 8.4)

| support | det + skip (file unit; worker threads by default, worker processes if configured) |
|---|---|
| control tests | same two control tests (file order and within-file task order shuffled) |
| adversarial tests | 33 shared cases (the 32 + F5 with a caught dynamic `import()`) + 7 AVA cases (`ava.config.mjs` environmentVariables, `require` setup file, snapshot file `snapshots/*.snap`, tsx via `nodeArguments` + tsconfig paths, `--match` filter, worker processes (`--no-worker-threads`), a worker thread started by a test never cached) |
| would fail on a naive adapter | F5 caught require and F3c node:sqlite once the capture uses asynchronous loader hooks (wrong reuse before CommonJS resolution failures and node:sqlite were hooked in that mode); seeded/fixed order (AVA runs the files that failed last time first) |
| walk specs | `ava-globby` (sindresorhus/globby, 26 up to 2026-08-19), `ava-shelljs` (shelljs/shelljs, 26 up to 2026-10-25) |
| local mini-walk | sindresorhus/globby, commits 22..25 (4 commits, 3 transitions), MEASURED local NOISY: 0% of test time skipped (every transition changes the root package.json, a configuration file of every test file; most files run `git init`: never cached; temp names shared between files: `rw`), **0 wrong**; warm rerun at the same commit reused 1/10 files; plain `ava` 11.86 s, detjs --det 17.03 s, cold capture 22.47 s. Raw: `harness/node_cache/results/local-node-b/ava-globby-0.json.gz` |
| not covered | AVA 5 and older; shared workers (`ava/plugin`: never cached); watch mode |

### Jasmine (jasmine 5-7, built against 7.0)

| support | det (one process) + skip (a fresh process per spec file under `--det-cache`) |
|---|---|
| control tests | same two (shared shuffle through Jasmine's `orderChildren`) |
| adversarial tests | 32 shared cases + 6 Jasmine cases (`jasmine.json` env option, helper file content, a new helper file, `--filter`, `random: true` replaced by declaration order, cross-file state under per-file processes reported and never reused) |
| would fail on a naive adapter | new test file (the configured spec glob listed in every process made every file rerun: lost reuse, not wrong); helpers that `clearReporters()` (cordova-android: 0 tests bracketed; now the reporter is added after the helpers and a run whose end detjs did not see is never a pass); cross-file state (a single-process cache would reuse A and run B in a context that never existed) |
| walk specs | `jasmine-cordova-android` (apache/cordova-android unit specs, 26 up to 2026-11-03), `jasmine-xregexp` (slevithan/xregexp, 21 up to 2026-09-24: Jasmine 5+ only there) |
| local mini-walk | slevithan/xregexp, commits 17..20 (4 commits, 3 transitions), MEASURED local NOISY: test time skipped median 0% / mean 33% (two transitions change package.json), 430 reuses verified, **0 wrong**; warm rerun 0.67 s (5/5 files reused) vs plain 1.24 s; cold capture 2.86 s (one process per spec file). Raw: `harness/node_cache/results/local-node-b/jasmine-xregexp-0.json.gz`. Also run by hand on apache/cordova-android (20 spec files): second run reused 16 files / 267 tests (MEASURED, local) |
| not covered | `--parallel` (removed under --det); jasmine-browser-runner (browser, Level 2) |

### uvu (0.5)

| support | det (one process) + skip (a fresh process per file under `--det-cache`) |
|---|---|
| control tests | same two (suites of a file and tests of a suite shuffled with the seed) |
| adversarial tests | 32 shared cases + 5 uvu cases (`-r` module content, `-r` dropped from the command line, `-r tsx/cjs` + tsconfig paths, named suite input, cross-file state under per-file processes) |
| would fail on a naive adapter | new test file (uvu's `parse` lists the test directory in every process); O_EXCL / mkdir (before the capture change); uvu's runner source not hooked through CommonJS loaders (`tsx/cjs`: tests unbracketed) |
| walk specs | `uvu-autoprefixer` (postcss/autoprefixer, 26 up to 2026-11-18), `uvu-browserslist` (browserslist/browserslist, 26 up to 2026-11-16, NODE_ENV=test) |
| local mini-walk | postcss/autoprefixer, commits 21..25 of the spec's list (5 commits, 4 transitions), MEASURED local NOISY: test time skipped with proof median 45% / mean 51%, tests reused median 61%, 731 reuses verified, **0 wrong**, 0 flaky; wall skip run median 4 s vs verify run 9 s; warm rerun at the same commit 0.51 s (15/15 cacheable files reused); plain `uvu` 3.16 s, detjs --det 3.01 s, cold capture 8.19 s (16 processes). Raw: `harness/node_cache/results/local-node-b/uvu-autoprefixer-0.json.gz` |
| not covered | test files run without the CLI (`node test/x.js`); `-r esm` (broken on Node 22 regardless of detjs) |

## Changes to shared files (for the merge)

* `node/bin/detjs.js`: `tap|ava|jasmine|uvu` dispatch to `src/runners/<name>.js` (+ usage line).
* `node/src/cache/capture.js`:
  * `DETJS_DRIVER` includes `src/runners/` (detjs' own driver code);
  * `INFRA` + `tap|@tapjs|tap-parser|tap-yaml|tcompare|async-hook-domain|ava|@ava|emittery|p-map|currently-unhandled|jasmine|jasmine-core|@jasminejs|uvu|sade|kleur`;
  * prior state of writes that depend on it, in test processes (R-009 O_EXCL creates): exclusive creates (`wx`,
    `O_EXCL`, `writeFile` with flag `wx`), `mkdir` without `recursive`, `unlink`, `rm` without `force`, `rmdir`
    (listing) record the path's prior state as an input (own outputs skipped as before; the main process unchanged);
  * tsx's watch IPC pipe (`$TMPDIR/tsx-<uid>/<pid>.pipe`) is not a test socket;
  * `DETJS_CAPTURE_LOADER=register` (opt-in, set by the runner shells only): ES module loads and failed resolutions
    through `module.register` hooks (`src/cache/loader-hooks.mjs`, new) posting to the test thread, `flushLoader`
    in `scanModules`; CommonJS failed resolutions (`Module._resolveFilename`) and `node:sqlite` (`Module._load`).
    Default (Vitest, Jest) unchanged: `module.registerHooks`.
* `node/src/sites.js`: the same runner packages in `INFRA` (their timers and clock reads stay real).
* `harness/node_cache/walk.py`: `report_args(runner, report)` (Vitest/Jest JSON report options; none for the runner
  shells), `outcomes_of(..., repo)` reads detjs' `ran_files` for the runner shells, spec `env`, spec
  `no_file_args`. Vitest/Jest branches unchanged.
* New: `harness/node_cache/specs/{tap-minimatch,tap-dotenv,ava-globby,ava-shelljs,jasmine-cordova-android,
  jasmine-xregexp,uvu-autoprefixer,uvu-browserslist}.json`, `harness/node_cache/commits/<same>-commits.json`,
  `harness/node_cache/RUN-node-b`, `.github/workflows/all-runners-node-b.yml` (not pushed).

## Test results (MEASURED, local, Node 22.23.5, runners installed from npm at the pinned versions)

Command: `cd node && DETJS_RUNNERS_B_DEPS=<dir with the pinned runners, optional> node --test --test-concurrency=1
test/runner-<name>.test.js` (without DETJS_RUNNERS_B_DEPS the tests `npm install` tap@21.8.1 ava@8.4.0
jasmine@7.0.0 uvu@0.5.6 tsx@4.23.15 tinyglobby@0.2.15 into node/test/.tmp/runners-b-deps).

| suite | tests | pass | fail | last full run |
|---|---:|---:|---:|---|
| `test/runner-tap.test.js` | 43 | 43 | 0 | after the last tap change |
| `test/runner-ava.test.js` | 43 | 43 | 0 | 42/42 full run + the added unhandled-rejection test run alone |
| `test/runner-jasmine.test.js` | 41 | 41 | 0 | after the last Jasmine change |
| `test/runner-uvu.test.js` | 39 | 39 | 0 | full run |
| shared: `test/cache.test.js test/review-r021.test.js test/r021-fixes.test.js` (Vitest 5.1, Jest 30.5) | 102 | 101 | 0 | 1 skipped by design (F3b on Jest); after the capture changes |

Flaky seen once (not reproduced on rerun): Jasmine `held: fs.globSync` missed reuse with "runtime changed" while
other processes used the shared runner install (the runtime identity hashes it): a lost reuse, not a wrong one.
