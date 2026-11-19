FIX 4

# Review r021b (last round): `detjs --det-cache` after the r021 fixes

Target: `claude/node-cache-proof` at ea5bba6 (report `sessions/2026-11-18-node-cache-proof/REPORT-2.md`, fix commit
4b376e0, measurement launch cc09727). First review: `claude/review-r021`, `sessions/2026-11-19-review-node-cache/REPORT.md`.
Reviewer branch: `claude/review-r021b`. Environment: Node 22.23.5, Vitest 5.1.0, Jest 30.5.2 (`npm ci` in `node/`),
native core built from the target (`node scripts/build.js`), Python 3.13.18.

## Verdict

**FIX 4.** The nine r021 findings are fixed as the review's tests define them, and the measurement numbers re-derive
exactly. Four new defects remain. Each has a failing test in `node/test/review-r021b.test.js`:

| # | defect | test(s) | Vitest | Jest |
|---|---|---|---|---|
| G1 | F1 fix incomplete: two ways to read Stats fields that skip the proxy's `get` trap | G1a `Object.getOwnPropertyDescriptor(st, 'size').value`, G1b `util.inspect(st)` | wrong reuse | wrong reuse |
| G2 | F1 fix changes outcomes: a proxied Stats object cannot be cloned | G2 `structuredClone(fs.statSync(p))` | fails with the cache, passes without | same |
| G3 | F2 fix incomplete: recursive `readdir` follows links to directories, but `t:` does not | G3a `readdirSync(dir, { recursive: true })`, G3b `fs.promises.readdir` | wrong reuse | wrong reuse |
| G4 | new channel: a preload module (`execArgv: ['--import', …]`) reads a file before the capture is installed | G4 | wrong reuse | n/a |

Run: `cd node && node --test --test-concurrency=1 test/review-r021b.test.js` gives **34 passed, 11 failed** on ea5bba6.
The 11 failures are G1a, G1b, G2, G3a and G3b on both runners, plus G4. All `held` cases pass.

## 1. The review's test file

* `git diff origin/claude/review-r021 HEAD -- node/test/review-r021.test.js` is empty: the file is unchanged.
* `node --test --test-concurrency=1 test/review-r021.test.js` (Vitest and Jest, both runners by default) gives
  **32 passed, 1 skipped, 0 failed**. The skip is F3b under Jest, which the reviewer skipped. `test/r021-fixes.test.js`
  gives 24 passed. Together that is the 56 passed and 1 skipped the report states.

## 2. Findings

Every case has the shape of the first review. Run 1 records and passes. Run 2 must reuse the file. Then one input
changes so that a fresh run fails, and the cached run must not reuse the file. G2 compares a run without the cache
against a capture run.

### G1: Stats fields can be read without the proxy seeing it (F1)

`statProxy` (`node/src/cache/capture.js:822`) only traps `get`. Two common ways to read a field go around it:
* G1a: `Object.getOwnPropertyDescriptor(fs.statSync('data/blob.bin'), 'size').value`. The Proxy has no
  `getOwnPropertyDescriptor` trap, so the call goes to the target and nothing is recorded. The same is true of
  `Object.getOwnPropertyDescriptors` and of any library that copies objects through descriptors.
* G1b: `util.inspect(fs.statSync('data/blob.bin'))`. Node's inspect unwraps proxies and formats the target
  directly (`showProxy: false`). The same happens with `console.log` output that a test asserts on, and with
  inspect-based diffs.

In both cases the file grows by one byte, a fresh run fails, and the cached run reuses the stale pass. This happens
on both runners.

Held: `toMatchObject({ size })` (not reused wrongly after the change),
`{ ...st }` and `JSON.stringify(st)` (every field is read, `mtime` included, so the file is not cacheable),
`FileHandle.stat()`, and `fstat` on a read stream's descriptor.

Fix direction: add `getOwnPropertyDescriptor` (and `ownKeys`, which should count as reading every field) traps that
record like `get`. For `util.inspect`, wrap `util.inspect`/`util.formatWithOptions` so that a proxied Stats object
counts as reading all of its fields (that makes it not cacheable, which is the honest answer). Alternatively, return
a plain `fs.Stats` instance whose fields are accessor properties that record, instead of a Proxy (that also fixes G2).

### G2: the Stats proxy changes test outcomes (F1)

`structuredClone(fs.statSync('data/blob.bin')).size` passes under `detjs --det` and fails under `--det-cache` with
`DataCloneError: #<Stats> could not be cloned.`, on both runners. `v8.serialize`, `postMessage` and
`util.types.isProxy` see the same difference. The cache then records a failure that a plain run does not have.
Nothing wrong is reused, but the capture run is no longer the run it claims to measure, and the failure is reported
to the user as theirs. Fix direction: as in G1, use an object that is not a Proxy.

### G3: recursive listings follow directory links; `t:` does not (F2)

The report says `t:` keys "every path below, with its type, links not followed". Node's recursive `readdir`
(sync, callback and promise) **does** descend into symbolic links to directories. In the fixture of the removed
loop case, `tree/a/up -> ..` yields 41 entries before `ELOOP` stops it. So a listing depends on directories reached
through links, and `t:` does not key them:
* G3a: `tree/link -> ../other` (a project directory). `readdirSync('tree', { recursive: true })` counts one `.json`.
  Adding `other/y.json` changes the result, but `t:` of `tree` is unchanged, so the result is reused.
* G3b: the same with `fs.promises.readdir`.

Both reuse wrongly on both runners. This is an ordinary layout: fixtures that link to shared fixtures, and
workspaces linked into a tree.

Fix direction: make `tree_listing_digest` follow links to directories the way Node does, cutting cycles by device
and inode. `copy_tree_digest` already does this for `c:`. Keep `t:` without following links only for the kinds
whose API does not follow them (none of the current `t:` callers).

### G4: a preload module from `execArgv` runs before the capture (new channel)

Vitest `test: { pool: 'forks', execArgv: ['--import', './pre.mjs'] }`, where `pre.mjs` reads `pre.txt` into
`globalThis.__PRE__`, and the test checks it. Changing `pre.txt` makes a fresh run fail, but the cached run reuses.
The read happens in the worker before detjs installs its wrappers. It is not in the main process's global context
either, because the main process never reads the file. `execArgv` is a documented Vitest option for exactly this
kind of setup (`--import` of an instrumentation or polyfill module). Jest has no per-worker `execArgv`, and
`NODE_OPTIONS` is already part of the environment.

Fix direction: treat every `--import`/`--require`/`--loader`/`--experimental-loader` module named in the
configured `execArgv`, together with every module it loads, as configuration (content-keyed). Alternatively,
install the capture before user preloads by putting detjs' own `--import` first and starting the capture there.

## 3. Attacks that did not get through (`held` tests, both runners unless noted)

* Stats: `expect(st).toMatchObject({ size })`; spread and `JSON.stringify` (not cacheable); `fs.promises.open` +
  `stat()`/`readFile()`; `fstat` of a `createReadStream` descriptor.
* `cpSync` of a tree that contains a link loop: refused reuse (`data: out/<pid> (missing)`), which is sound.
* Snapshot file edited in `__snapshots__`: rerun.
* Dynamic configs: `vitest.config` `define` from a file and from an environment variable; `jest.config.js`
  `globals` from a file and from an environment variable; `moduleNameMapper` built from a file (Jest).
* `globalSetup` that reads a project file into `process.env`; `globalSetup` that lists a directory **outside** the
  project with async `tinyglobby` (F8 in the main process).
* `package.json` `"imports"` map retargeted (`#dep`).
* A dotenv-style read of `.env` through `process.cwd()`.
* A loopback HTTP service whose response changes: not cacheable (`connect`).
* Vitest only: `import.meta.glob` with braces `{a,b}`, with a template-literal pattern, with a negative pattern, in
  a helper module with `query: '?raw'`; and `vi.mock` of a scoped package with `__mocks__/@scope/pkg.js` added.
* Jest only: a custom `testEnvironment` that reads a file in its constructor; `automock: true` with
  `src/__mocks__/dep.js` added.
* Child processes and worker threads are flagged as not cacheable (`capture.js:1118-1173`). A child that runs a
  Node script reading files is therefore covered.

Not tested: `better-sqlite3` (a native addon; installing it needs a prebuilt binary download, and native addons are
a documented limit), tsconfig `paths` (needs a plugin), and Node's off-thread `module.register` loaders inside a
test.

## 4. Numbers re-derived from committed data

All re-derived from `harness/node_cache/results/r6/*.json.gz` with my own script, not only with `aggregate.py`.
Shards are deduplicated by commit index.

* **396,780 verified reuses, 0 mismatches**: docusaurus 129,295 + vue-core 85,112 + TanStack Query 158,515 +
  React Native 22,330 + Lexical 1,528. Correct. They split into **378,866 test results + 17,914 file entries**.
  For every row, `verified` equals `reused_tests + reused_files`. Note: the first review's F9 fix split the r1
  total this way in `REPORT.md`, but REPORT-2 gives 396,780 unsplit. That is not a wrong number, but the split
  should be stated for consistency.
* Run id: Actions run 44485937741 exists, workflow `node-cache-proof`, conclusion `success`, head cc0972701347.
  `git diff cc09727 ea5bba6` outside `results/` and `sessions/` is empty, so the measured engine is the engine
  under review. (The shards' `runner` field, "GitHub Actions 10000105xx", is the runner name, not the run id.)
* Reuse medians and means: docusaurus 85% / 70% (r1: 88% / 73%), vue-core 26% / 32% (r1: the same), TanStack 92% / 62%
  (r5: 91% / 61%), React Native 0% / 1%, Lexical 0% / 0%. All correct. For vue-core (vs r1) and TanStack (vs r5),
  the per-commit `verified` counts and the reused file lists are identical. I checked that this is determinism and
  not copied data: the runner names, timestamps and durations all differ.
* Capture overhead (cold capture / `detjs --det`): docusaurus 1.125-1.232 (**+12.5% to +23.2%**), TanStack
  +9.5% to +15.7%, vue-core +7.6% to +9.8%, Lexical +2.3%, React Native +0.6% to +0.8%. All correct.
* Level 0 over the project's command: docusaurus 2.10-2.13×, vue-core 2.05-2.10×, TanStack 1.76-1.86×, Lexical
  1.89×. Correct. React Native (27.5-30.3×) is left out of that sentence. It is in the table, but the sentence reads as
  the full range.
* Warm reruns (188-189 of 205-207, and so on) and wall times (22 s vs 107 s, and so on) are correct.
* "936 / 468 / 208" not-cacheable entries on docusaurus: these are sums over all 52 verify runs of both shards, so
  commit 25 is counted twice (deduplicated: 918 / 459 / 204). They are also per-run entry counts: 18, 9 and 4 entries
  per run. The label "verify runs, all shards" is literally accurate. These figures are not used in any conclusion.

Labels: no number that the report labels MEASURED fails to re-derive. Hence no label finding this round.

## 5. Shared Rust core and Python

* `cargo test --workspace --exclude detpy-py`: **63 passed** (as reported).
* Python, editable build of ea5bba6 (`pytest tests harness/node_cache/test_review_r021_labels.py`): **178 passed,
  9 skipped, 1 failed**. The failure is `test_review_r008d.py::test_finished_startup_process_that_left_a_daemon_is_not_ignored`.
  On a separate editable build of 495f858 (worktree), that file gives the same failure, so it predates this work.
* Code check: `git diff 495f858 ea5bba6 -- crates python` touches only `detpy-core` (`deps.rs`, `proof.rs`, `lib.rs`)
  and `detpy-node`. In `data_now`, the new branches only match the new prefixes (`m:`, `L:`, `r:`, `e:`, `t:`,
  `c:`). `link_dep` changed its non-link answer from `s:<kind>` to `L:<kind>`, but the Python shell never calls
  `link_dep` and never records `l:` (grep of `python/detpy` and `crates/detpy-py`). Python's semantics are
  unchanged.

## What to fix

1. G1 + G2: replace the Stats Proxy with a real `fs.Stats` (same prototype) whose fields record through accessors,
   or add descriptor/`ownKeys` traps and an inspect hook. Re-run G1a, G1b and G2.
2. G3: make `t:` follow directory links as Node's recursive `readdir` does, with cycle cutting. Re-run G3a and G3b.
3. G4: key `execArgv` preload modules (and what they load) as configuration, or start the capture before them.
4. Optional (not counted): give the 396,780 split, React Native's Level 0 ratio, and the deduplicated not-cacheable
   counts in REPORT-2.
