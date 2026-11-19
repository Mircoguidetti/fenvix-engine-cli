PARTIAL

# Skip with proof for JS/TS (`detjs --det-cache`): fixes of review r021b (report 3)

Branch `claude/node-cache-proof`. Review: `sessions/2026-11-19-review-node-cache/REPORT-2.md` (verdict FIX 4), merged
from `claude/review-r021b` (7aa8540) with `node/test/review-r021b.test.js` unchanged. Fix commit a27d565, measurement
launch d299d5f (Actions run 44580359261). Labels: **MEASURED** (command or run id), **ESTIMATED**, **DECLARED**,
**UNKNOWN**.

STATUS: r7 is still running (R7_PENDING below). This file is rewritten when its shards land.

## Findings G1-G4

Before = the reviewer's run on ea5bba6 (34 passed, 11 failed, MEASURED by the reviewer). After = this branch,
MEASURED here (Node 22.23.5, Vitest 5.1.0, Jest 30.5.2) with `cd node && node --test --test-concurrency=1 <file>`,
and in the `tests` job of run 44580359261 (184 passed, 1 skipped, 0 failed: cache, review-r021, r021-fixes,
review-r021b, r021b-fixes, both runners).

| # | fix | tests | result |
|---|---|---|---|
| G1 | No more Stats Proxy. `stat*`, `lstat*`, `fstat*` and `FileHandle.stat` return the **real** `fs.Stats` / BigIntStats object. It has the same prototype and keeps the key order. Its own data fields become accessors that record the read (`capture.js` `recordingStats`). `Object.getOwnPropertyDescriptor(s)` and `Reflect.getOwnPropertyDescriptor` are patched in every realm tests run in: the main realm, and each Jest test context through `installReflection`. They count as a read and return the same data descriptor as without the cache. `util.inspect` and `console.log` go through a custom inspection on the Stats prototype. It reads every field and formats a plain copy, so the output is byte-identical. `is*()` methods read the kind from a private view: it is keyed by `s:`/`L:`, not as a `mode` read. **Volatile fields** (times, inode, device, owner, nlink, blocks) are now keyed by their exact value with a new kind `V:<follow>:<field>` in the Rust core (`deps.rs` `stat_field_digest`; `data_now` memo keyed per field). Before, they were "not cacheable". This is what G1b requires: run 2 must reuse `util.inspect(st)`, and keying the values is sound. Runner and transpiler reads are still ignored. | review G1a, G1b; r021b-fixes: `getOwnPropertyDescriptors`, `Reflect.getOwnPropertyDescriptor`, `util.format('%o')`+`console.log`, mtime set by `utimes`, `lstat` inode of a link, keeps: `isFile()` | G1a/G1b wrong reuse → pass, both runners |
| G2 | The same change: not a Proxy, so `structuredClone`, `v8.serialize` and `postMessage` read the fields through the getters (counted as reads) and succeed as without the cache. `util.types.isProxy` is false. Every other proxied object in the capture had the same class of hole. There was one: **`process.env`**. It stays a Proxy (a missing variable must be recordable), but its target is now a stand-in that only holds a custom inspection. `util.inspect`/`console.log` record `*` and format the real environment. `structuredClone`, `v8.serialize`, `Serializer#writeValue` and `MessagePort`/`BroadcastChannel#postMessage` are retried with the real environment in place of the Proxy (deep replacement; it records `*`), so they succeed or fail exactly as without the cache. `util.types.isProxy(process.env)` answers for the real object. | review G2; r021b-fixes: "same:" Stats test (prototype, instanceof, isProxy, inspect incl. `showHidden`, keys, descriptor, clone, serialize, write-then-read, BigInt), env inspect / clone / isProxy / descriptor (Vitest; Jest's own env copy is not cloneable with or without the cache) | G2 outcome differed → same outcome |
| G3 | `t:` (`deps.rs` `tree_listing_digest`) descends into links to directories exactly where Node does (`readdirSync`, callback `readdir`, `fs.promises.readdir` without `withFileTypes`). Links are tagged (`l>d`, `l>f`, `l>dangling`). Cycles are cut by device+inode against the ancestor chain, and the cycle records which ancestor it closes on. A tree with a cycle also keys its absolute path, because Node's `ELOOP` cut-off depends on it. A new kind `u:` (`tree_listing_nofollow_digest`) covers the two APIs that do not follow links: `fs.promises.readdir` with `withFileTypes`, and recursive `opendir` (MEASURED: 245 vs 4 entries on a loop fixture). | review G3a, G3b; r021b-fixes: callback readdir, readdirSync withFileTypes, link retargeted, cycle with a new entry, keeps: promises+withFileTypes does not follow; `cargo test` `tree_listing_follows_directory_links_like_node` | G3a/G3b wrong reuse → pass |
| G4 | `node/src/cache/early.js` starts the capture **before any user code of a test process**. It is put first in every Vitest project's `execArgv` (and `poolOptions.*.execArgv` on Vitest < 4) after the configuration digest, so its absolute path is not keyed. When `NODE_OPTIONS` or the command line has preloads, `bin/detjs.js` restarts itself with early.js first in `NODE_OPTIONS`, which covers the main process (Jest runs in band there), forks and worker threads. Everything the preloads, Vitest's start-up and the test environment's `setup` read is recorded like any read of the process, and preload modules are code inputs. A custom Vitest `environment` is evaluated without file names in its frames, so in the worker start-up every read counts, as in the rest of the worker. A preload that reads the clock or OS entropy (before Level 0) makes the tests not cacheable. An off-thread loader (`--loader`, `--experimental-loader`, `module.register`) makes them not cacheable: its reads happen in another thread. Detjs' in-thread hooks are then removed, because Node refuses to mix them ("resolveSync not implemented", MEASURED). Other ways user code runs early, checked: Vitest `setupFiles` and `globalSetup`, and Jest `setupFiles`, `testEnvironment` and `globalSetup` held already (tests). The custom Vitest environment's `setup` **leaked** (found here, wrong reuse) and is now covered. | review G4; r021b-fixes: execArgv `--require`, `--import` importing a changed module, threads pool, custom environment `setup`, `NODE_OPTIONS --require` (both runners), preload clock read (both), `--experimental-loader`, Jest `setupFiles` | G4 wrong reuse → pass; custom environment wrong reuse → pass |

Totals (MEASURED, this container): `review-r021b.test.js` **45 passed, 0 failed** (Vitest and Jest).
`r021b-fixes.test.js` 38 passed. `review-r021.test.js` 32 passed, 1 skipped (F3b Jest, skipped by the reviewer).
`r021-fixes.test.js` 24 passed: one test was updated, because "mtime is not cacheable" became "mtime keyed by value,
a touch reruns". Other suites: cache 45, controls 16, jsdom 1, projects 1, regressions 7, unchanged 2. **Node total:
211 passed, 1 skipped, 0 failed.** `cargo test --workspace --exclude detpy-py`: **65 passed** (63 + 2 new). Python
(`pytest tests harness/node_cache/test_review_r021_labels.py`, editable build of this branch): **178 passed,
9 skipped, 1 failed**. The failure is the pre-existing
`test_review_r008d.py::test_finished_startup_process_that_left_a_daemon_is_not_ignored` (the same as on ea5bba6 and
495f858). Python's semantics are unchanged: `V:`, `u:` and the new `t:` are only recorded by the Node shell.

## Optional items of the review (4)

* The 396,780 verified reuses of r6 split into **378,866 test results + 17,914 file entries** (MEASURED, r6 data,
  re-derived by the reviewer and here).
* React Native's Level 0 ratio (`detjs --det` / project command): **27.5× to 30.3×** (2133.97/76.28,
  2114.80/69.89, 2134.17/77.60; MEASURED, run 44485937741). REPORT-2's "1.76-2.13×" sentence covers the other four
  repositories only.
* Docusaurus not-cacheable entries over the verify runs of both shards, deduplicated by commit index (commit 25 is
  in both shards): **918 / 459 / 204** instead of 936 / 468 / 208. That is 18, 9 and 4 entries per run (MEASURED, r6
  data).

## Capture overhead

Profile first (MEASURED, `--cpu-prof` on main and workers, TanStack Query `query-core` project, 41 files, this
container, 4 vCPUs). Before the work, the main process spent 2.4 s in the runtime identity: a stat walk of 175,950
installed files plus a 176k-entry JSON memo, re-parsed and rewritten every run. It also spent 0.84 s in stack-frame
classification (28k captures, 17k of them from Vite's `loadEnv` env reads), and `recordAll` re-observed every test's
log prefix from scratch. Workers rescanned the whole module registry at every test end. What changed (no soundness
trade):

1. Rust `treehash.rs`: roots are walked in parallel; the entry type comes from the listing; a directory is
   identified by device+inode instead of one `canonicalize` per directory; the memo is a compact binary file
   (`FXMEMO2`, the JSON form is still read) and is written only when it learned something. 2.5 s → 1.7 s (MEASURED,
   same tree, memo warm).
2. The package digest runs on libuv's pool (`treeDigestAsync`, a napi `AsyncTask`) from session start. The
   decision awaits it. It is recomputed if anything wrote into those trees through `fs` (any caller; excluded
   bookkeeping names aside), or if user code started a process or worker thread during start-up. Identity at the
   decision went from 2.4 s to 0.06 s (MEASURED). Residual assumption (documented in docs/NODE-CACHE.md Limits): a
   write into installed packages by native code of the main process during start-up is not seen.
3. Stack-frame classification is cached per file name (`frameClass`), and one capture serves caller+plugin.
4. `recordAll` observes each file's log once and advances it test by test. Inputs are prefixes, so the result is
   unchanged.
5. Workers rescan module registries only after a load. The counter comes from the loader's load hook and from
   counted `set`s on Vite's module map. `where()` results are memoised.

Local A/B on TanStack `query-core`, 3 runs each, alternating (MEASURED, this container): `detjs --det` 18.6 / 19.7 /
19.8 s; ea5bba6 cold capture 25.2 / 25.8 / 24.6 s (**+30%**); this branch 22.9 / 23.1 / 23.3 s (**+19%**). With 40
trivial files: det 6.2 s, both captures +0.6 s (15 ms per file of fixed cost).

On GitHub Actions (run 44580359261, same harness, repositories and commits; at each overhead commit, cold captures of
ea5bba6 and of this branch on the same machine, alternating, 2 runs each, with `detjs --det` runs in between):

R7_PENDING

## Measurement r7 (0 wrong reuses)

R7_PENDING

## Not done / limits

* The brain repository copy (`Mircoguidetti/fenvix-brain-cli`, `sessions/2026-11-18-node-cache-proof/`): attaching
  that repository was refused in this session ("add_repo" denied by the permission policy), so the copy on its main
  branch is not made. This file is on `claude/node-cache-proof` only.
* `Object.defineProperty(st, 'size', {value})` on a recording Stats object turns the accessor into a data property
  with `writable: false` (unspecified attributes of an accessor→data conversion default to false). On a plain Stats
  object, `writable` stays true. This affects no value read and only differs for code that redefines a Stats field
  and then checks that attribute.
* Key lists of Stats objects (`Object.keys`, `Reflect.ownKeys`) are not recorded as reads: they are the same for
  every file (fixed by the Node version, which is in the runtime identity), and every value read goes through a getter
  or a patched descriptor read.
