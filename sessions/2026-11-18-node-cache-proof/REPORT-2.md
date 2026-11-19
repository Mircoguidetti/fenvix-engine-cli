DONE

# Skip with proof for JS/TS (`detjs --det-cache`): fixes of review r021 — report 2

Branch `claude/node-cache-proof`. Review: `sessions/2026-11-19-review-node-cache/REPORT.md` (verdict FIX 9), merged
from `claude/review-r021` (3188df6) without changes to its tests. Fix commit: 4b376e0; measurement launch: cc09727.
Labels: **MEASURED** (with the command or the GitHub Actions run id), **ESTIMATED**, **DECLARED** (with source),
**UNKNOWN**.

## Answer

* All nine findings are fixed. Every `F<n>` test of the review passes, and every `held:` test still passes. That is
  32 passed and 1 skipped (F3b under Jest, skipped by the reviewer) in `node/test/review-r021.test.js`. Before the
  fixes it was 24 failed, 8 passed and 1 skipped (MEASURED by the reviewer on 495f858). After, it was MEASURED here
  (Node 22.23.5) and in the `tests` job of Actions run 44485937741.
* New measurement r6 on the same five repositories (Actions run 44485937741), with every would-be reuse checked by a
  fresh run at the same commit: **0 wrong reuses in 396,780 verified reuses** (MEASURED).
* Reuse goes down where the fixes found real unkeyed inputs. On docusaurus the median drops from 88% to 85% and the
  mean from 73% to 70%: blog tests read a fixture's **mtime**, which was never keyed before, and tests reach a
  stat of `npm`'s `uid`. These now run every time. vue-core is unchanged (26% / 32%). TanStack Query is 92% / 62%
  (r5: 91% / 61%).
* Capture overhead rises. On docusaurus the cold capture run now costs +12.5% to +23.2% over serial `detjs --det`
  (r1/r3: +9.0% to +13.9%). The extra cost is the Stats proxies and the caller checks they need (MEASURED, below).

## Per finding

"Before" is the review's result on 495f858 (MEASURED by the reviewer). "After" is this branch, MEASURED locally with
`cd node && node --test --test-concurrency=1 test/review-r021.test.js test/r021-fixes.test.js` (56 passed,
1 skipped) and in the `tests` job of run 44485937741 (success).

New keying logic is in the shared Rust core: `crates/detpy-core/src/deps.rs`, plus `data_now` and `link_dep` in
`proof.rs`. It is exposed through napi in `crates/detpy-node`. The `s:` kind is **unchanged**, so Python keeps its
semantics and its tests stay green (below). The new kinds are recomputed by the same `data_now` that both shells use.
An older engine meeting an unknown kind returns `unknown` and misses, which is the sound direction.

| # | what changed | proving tests | before → after |
|---|---|---|---|
| F1 | `stat*`/`fstat*`/`FileHandle.stat` return a recording proxy of the Stats object. Reading `size` or `mode` records a new `m:` dependency (kind, size, permission bits). Reading times, inode, device, owner, nlink or block counts makes the test **not cacheable**, unless the code doing the read is runner or Node-fs infrastructure (Jest's transform cache key, graceful-fs' uid fix-up, Node's async `cp`). `is*()` methods run on the real object, so the kind stays keyed by `s:`. `lstat*` records the link target (`l:`) or the path's own kind, as a new `L:<kind>` that does not follow links. The old `s:` fallback missed a regular file being replaced by a link to a file. `realpath*` (including `.native`, which was unwrapped before) records a new `r:` (the resolved path). `access` with a mode records `m:`. | F1a, F1b, F1c (both runners); `r021-fixes`: lstat file→link, chmod +x, async `stat().size`, `mtimeMs` not cacheable | wrong reuse ×6 → pass |
| F2 | `readdir*` with `recursive` records a new `t:` (every path below, with its type, links not followed). `withFileTypes` and `opendir*` record a new `e:` (names and entry types). | F2a, F2b; `r021-fixes`: recursive+withFileTypes, opendir | wrong reuse ×4 → pass |
| F3 | `fs.openAsBlob` and `process.loadEnvFile` read the file (`f:`; the variables it sets follow from that content). `node:sqlite` is wrapped when it is first loaded (through a loader `resolve` hook, `process.getBuiltinModule`, or at install if already loaded). Loading it eagerly would print its experimental warning on every run. A read-only database keys the db file and its `-wal`, `-journal` and `-shm` files. A writable one is also an output. URIs, `ATTACH`, `VACUUM INTO` and extensions make the test not cacheable. `fs.statfs*`, `fs.watch*` and `fs.watchFile` make it not cacheable. | F3a, F3b, F3c; `r021-fixes`: read-only sqlite reused, then rerun on change | wrong reuse ×5 → pass |
| F4 | `cp*` keys its source as a new `c:` (every path, type, file content and link target below it, links followed, cycles cut). Every path of the copy is marked as an output of the caller. `rename*` is handled the same way. The internal fs calls of Node's async `cp` are not counted as the caller's reads. | F4; `r021-fixes`: `fs.promises.cp` of a nested tree | wrong reuse ×2 → pass |
| F5 | Failed resolutions are recorded from three places: Vite's module runner (`cachedModule` rejections), Node's loader (`registerHooks` resolve throws) and Jest's resolver (`runtime._resolution.resolver.resolveModule*` in Jest 30, `_resolver` before). For relative or absolute specifiers, the target is keyed: content or `missing`, its listing, and the stem listings with and without extension. Bare specifiers from installed packages are covered by the runtime identity. Bare or `moduleNameMapper`-matched specifiers from project code make the test not cacheable. | F5 (both runners); `r021-fixes`: extensionless relative optional module (keyed), bare optional module (not cacheable) | wrong reuse ×2 → pass |
| F6 | For every loaded project module whose source calls `import.meta.glob`, the Rust parser (`import_glob_bases`) reads the literal patterns. Each base directory is keyed: `e:` when the pattern matches direct entries, `t:` when it can match deeper. `/…` resolves against the Vite root and `./`/`../` against the module. Alias or bare patterns, non-literals and a `base` option make the test not cacheable. Also new: reads of project files and directories by a third-party Vite plugin (installed code that is not runner infrastructure), at start-up or during transforms, are inputs of every file. This is the review's "any Vite transform whose output depends on a directory listing". | F6; `r021-fixes`: `**` two levels deep, alias pattern (not cacheable), plugin that lists `content/` in `transform` | wrong reuse ×1 → pass |
| F7 | Vitest: the mocker's `findMockRedirect` is wrapped on each file's module runner. Its own `fs` references predate the capture, so the call itself is recorded: existence of the mocked path and of `__mocks__/<name>` next to it, and the tree of `<root>/__mocks__/<dir>` (`t:`). Jest: the mocks map of Jest's crawl (every `__mocks__` file under the roots) becomes a configuration part `jest-mocks` of every file, added in the sequencer before the decision. | F7a, F7b, held `jest.mock`; `r021-fixes`: `vi.mock` of an installed package with a root `__mocks__` file | wrong reuse ×2 → pass |
| F8 | In test processes, reads outside the project are recorded whoever the caller is; the caller filter is now only applied in the main process. The engine-directory skip was also narrowed to detjs' own `src`, `bin`, `scripts`, `node_modules`, package files and addon. The old skip of everything under `node/` hid the review's outside directory, which sits in `node/test/.tmp`. | F8 (both runners) | wrong reuse ×2 → pass |
| F9 | `REPORT.md` labels corrected. Overhead is now "+6% (vue-core) to +14% (docusaurus)", with per-repository ranges and TanStack +7–16%. Runtime identity is "up to 220,327 installed files / 3.47 GB". Verified reuses are split into 431,029 test results and 18,241 file entries. React Native 36 is named by its measured reason, `config`. The Level 0 ratio is 1.65–2.15×. | `harness/node_cache/test_review_r021_labels.py` | 2 failed → 2 passed |

Other suites (MEASURED, this container, Node 22.23.5):
* full node suite `node --test --test-concurrency=1 test/*.test.js`: **128 passed, 1 skipped, 0 failed** (cache,
  controls, jsdom, projects, regressions, unchanged, review-r021, r021-fixes);
* `cargo test --workspace --exclude detpy-py`: **63 passed** (56 before, plus 7 new: six in `deps`, one for `L:`);
* Python (`pytest tests harness/node_cache/test_review_r021_labels.py`, editable build of this branch):
  **178 passed, 9 skipped, 1 failed**. The failure is
  `test_review_r008d.py::test_finished_startup_process_that_left_a_daemon_is_not_ignored`. It fails the same way on
  495f858 in a separate worktree in this container (MEASURED), so it does not come from this work.

## Measurement r6 (Actions run 44485937741, same harness and specs as r1/r5)

Every reuse was checked by a fresh run at the same commit (verify mode). Shares are priced with each file's duration
in the fresh run. All MEASURED, from `python3 harness/node_cache/aggregate.py r6 --md`.

| project (runner) | transitions | skip with proof, median / mean: **r6** | before the fixes (r1; TanStack r5) | tests reused, median (r6) | verified reuses (r6) | **wrong (r6)** | flaky (r6) | Nx affected, median / mean (r6) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| docusaurus (Vitest) | 50 | **85% / 70%** | 88% / 73% | 92% | 129,295 | **0** | 0 | 27% / 56% |
| vue-core (Vitest) | 50 | **26% / 32%** | 26% / 32% | 46% | 85,112 | **0** | 0 | 27% / 29% |
| TanStack Query (Vitest, Nx) | 50 | **92% / 62%** | 91% / 61% | 94% | 158,515 | **0** | 0 | 92% / 69% |
| React Native (Jest) | 9 | **0% / 1%** | 0% / 1% | 0% | 22,330 | **0** | 0 | 98% / 87% (unproven) |
| Lexical (Vitest, `vmThreads`) | 10 | **0% / 0%** | 0% / 0% (19 transitions) | 0% | 1,528 | **0** | 0 | 75% / 62% (approximate) |
| **total** | 169 | | | | **396,780** | **0** | 0 | |

Raw results: `harness/node_cache/results/r6/` (`*.json.gz`, `TABLES.md`, `aggregate.json`). Warm rerun of an
unchanged tree (r6): vue-core 184–185 of 184–185 files reused, docusaurus 188–189 of 205–207 (r3: 194–195 of
206–207), TanStack Query 161–162 of 179–180, React Native 231 of 284 (r1: 232), Lexical 6 of 982.

Notes:
* Lexical r6 covers transitions 40–50 (the spec's window, 10 transitions); r1 covered 19. 97% of its files run
  under `vmThreads`, which is not cacheable by design.
* What the fixes made not cacheable on docusaurus (verify runs, all shards, file and test entries; MEASURED):
  * 936 for reading `build-snap/blog` `.mtime` (blog plugin fixtures);
  * 468 for `npm`'s `.uid` read through a stat;
  * 208 for an unresolved bare specifier (`content-docs` from `moduleShorthand.test.ts`, mapped by the test's own
    resolution);
  * a few for swizzle tests reading `mtime` of temporary directories they create.

  These inputs were unkeyed before. Whether one of them ever changed an outcome over the 50 transitions is UNKNOWN;
  no wrong reuse was observed in r1 either.
* Capture overhead (cold capture over serial `detjs --det`, every r6 overhead row): docusaurus +12.5% to +23.2%,
  TanStack Query +9.5% to +15.7%, vue-core +7.6% to +9.8%, Lexical +2.3%. React Native +0.6% to +0.8%.

  Serial Level 0 over the project's own command: docusaurus 2.10–2.13×, vue-core 2.05–2.10×, TanStack 1.76–1.86×,
  Lexical 1.89×.

  Runtime identity: up to 220,327 installed files (TanStack Query).
* Wall time of the run that skips (median): docusaurus 22 s vs 107 s (0.20), TanStack Query 62 s vs 156 s (0.40),
  vue-core 63 s vs 92 s (0.68).

## Left open

* **Python shell, `stat`**: `os.stat` and friends raise no audit event, so the Python side records no metadata read
  at all. The `s:` kind used there is only the fallback for an `open` of a non-file. This is the Python counterpart
  of F1 and was not part of r021; the shared `m:`/`r:`/`L:` kinds are ready for it. UNKNOWN whether any Python
  suite depends on it.
* **Node's async `cp` internals** are recognised by a stack check (`internal/fs/cp/`) while an async `cp` is in
  flight: every read during a copy pays a stack capture.
* **Plugin reads (F6 extension)**: a third-party plugin that reads project files is an input of every file (coarse
  but sound). A plugin that reads files *outside* the project is still not keyed in the main process.
* **Stats field reads by infrastructure** are not counted when the reading frame is runner, bundler or Node-fs code
  (list in `capture.js`: `INFRA`, `RUNNER_FN`). A library on that list that reads `mtime` and returns a decision
  derived from it to the test would be missed. None is known; chokidar uses `fs.watch`, which is not cacheable
  anyway.
* `fstat` on a descriptor opened by `FileHandle` APIs other than `fs.promises.open`, or inherited, has no path and
  its fields are not tracked.
* Overhead: the Stats proxy and caller checks raised docusaurus' capture overhead to as much as +23%. Not optimised
  in this round.
* The review's untested notes (native addons linking project shared libraries, `tsconfig` `extends` above the root,
  Jest custom transformers, `nodeModulesDirs`' 20,000-directory limit) were not addressed in this round.
