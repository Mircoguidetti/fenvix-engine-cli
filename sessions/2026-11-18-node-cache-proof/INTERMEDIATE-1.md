# Node cache with proof — intermediate report 1 (steps 1–2)

Branch `claude/node-cache-proof` (from `claude/node-l0`, with `claude/shared-cache` merged in: the reviewed Python
design and its Rust core). Labels: MEASURED (run here or on GitHub Actions, with the command), ESTIMATED, DECLARED
(a vendor's documentation), UNKNOWN.

## Status

* **Step 1 (port): done.** `detjs vitest|jest --det --det-cache=DIR|URL` skips test files with proof. Design:
  [docs/NODE-CACHE.md](../../docs/NODE-CACHE.md).
* **Step 2 (tests): done.** `node/test/cache.test.js`: **40 of 40 pass** locally (Vitest 5.1 and Jest 30, Node 22;
  MEASURED, `cd node && node --test --test-concurrency=1 test/cache.test.js`). Rust core: 55 of 55 (MEASURED,
  `cargo test -p detpy-core`). The Python test suite was not re-run after the two additions to `proof.rs` (new
  dependency kinds only; UNKNOWN until CI runs it).
* **Step 3 (measurement): started.** Workflow `node-cache-proof` run 44349361887 (queued on the shared queue at the
  time of writing): docusaurus and vue-core over the skip study's 51 commits, Lexical (Vitest monorepo) and
  React Native (Jest monorepo) over 51 first-parent commits each; Nx affected per transition.

## What was built

| piece | where |
|---|---|
| napi `ProofCache` (the Python store, keys, reuse check and receipts unchanged), digests, tree hasher | `crates/detpy-node/src/lib.rs`, `crates/detpy-core/src/treehash.rs` |
| two new dependency kinds in the shared core: `l:` (symlink target) and `g:` (entries sharing a module's name stem: resolution shadowing) | `crates/detpy-core/src/proof.rs` (`link_dep`, `stem_listing_digest`) |
| input capture per process / worker: modules loaded, files read and written, env reads, machine facts, spawns, workers, sockets, UDP, entropy, `/proc`, clock | `node/src/cache/capture.js` |
| runtime identity (node binary and versions, mapped shared libraries, TZ, locale, CPU level, lockfiles, every installed file under every `node_modules`, ancestors' and `NODE_PATH` included) | `node/src/cache/runtime-id.js` |
| session: configuration digest, decision, recording, receipts (Python format), summary, verify mode | `node/src/cache/proof.js` |
| shared cache client (same service, documents, addresses, lookup keys as Python; synchronous push on exit for Jest `--forceExit`) | `node/src/cache/remote.js` |
| Vitest: decision in detjs' sequencer (after `globalSetup`); worker-side contexts and capture | `node/src/vitest/cli.js`, `node/src/vitest/shell.js` |
| Jest: decision in the sequencer; test-environment wrapper marks the file start (before `setupFiles`) and proxies the file's own `process.env` copy; capture re-wrapped after Level 0 installs | `node/src/jest/{cli,sequencer,runner}.js` |
| measurement harness and workflow | `harness/node_cache/walk.py`, `.github/workflows/node-cache-proof.yml` |

Unit of reuse: the **test file** (all its tests reused, or all run), with per-test entries and receipts and a file
manifest entry; inputs are cumulative within a test's process. Reason: tests of a file share module state, so a
partial skip would change the state the other tests run in. Vitest `isolate: false`, `vmThreads/vmForks`, browser
mode and custom Jest runners are not cached (state shared between files, or tests outside the captured process).

## Tests (step 2): one per input and per reviewer hole, both runners

Each test records, checks that an unchanged rerun reuses every file, changes one input, and checks that **exactly**
the dependent files run again.

| # | input / hole (origin) | Vitest | Jest |
|---|---|---|---|
| 1 | unchanged project: every file reused; receipt fields as Python; Level 0 fingerprint in the receipt | pass | pass |
| 2 | code: a changed module reruns only the files that loaded it, transitively | pass | pass |
| 3 | code loaded by a dynamic import inside one test | pass | pass |
| 4 | data: content read, **read-write open** (R-002 E1), stream, listing, existence, **symlink target** (R-008b) | pass | pass |
| 5 | env: unread variable not an input; **enumeration** (`Object.keys(process.env)`) makes the whole environment one (R-002 E2) | pass | pass |
| 6 | env: value of a read variable | pass | pass |
| 7 | machine facts: `os.homedir()` follows `HOME` (the docusaurus `$HOME` case, R-002 E2) | pass | pass |
| 8 | runtime: an installed package file, the lockfile | pass | pass |
| 9 | runtime: **TZ** (local-time formatting) | pass | pass |
| 10 | configuration: tsconfig, detjs option (`--det-seed`), runner configuration value | pass | pass |
| 11 | a failure is never reused (R-002 N4) | pass | pass |
| 12 | never cached: **child process** (git included), **worker thread**, **loopback connection** (R-002b proxy-on-loopback rule: every connection counts), OS entropy | pass | pass |
| 13 | **git reads**: a test reading `.git/HEAD` and the ref reruns after a new commit | pass | pass |
| 14 | a file written by another test file makes its reader not cached | pass | pass |
| 15 | verify mode: decides, runs everything, compares | pass | pass |
| 16 | Vitest **globalSetup**: a file it reads; a process it runs (output digest: R-008d start-up rule); an async process taints every file | pass | — |
| 17 | Vitest **setupFiles**: their code and what they read | pass | — |
| 18 | Vitest config dependencies (an alias module the config imports) | pass | — |
| 19 | module **shadowing**: a new `m.mjs` next to the resolved `m.ts` reruns the importers (Vite 8 resolves in native code: missing-path probes are invisible, hence the `g:` kind) | pass | — |
| 20 | snapshot files are inputs | pass | — |
| 21 | Jest **setupFiles**: what they read from disk and from the per-file `process.env` copy | — | pass |
| 22 | Jest **globalSetup**: what it reads | — | pass |
| 23 | shared cache: a second machine (empty mirror) reuses with proof from the service; a changed input defeats the pulled candidate; the token is not visible to tests | pass | pass |
| 24 | plain `http://` to a remote host refused; canonical JSON byte-identical to Python's (address check) | pass (runner-independent) | |

Bugs these tests (and two local trial runs on docusaurus and vue-core) found and that are fixed: unstable
configuration digest (runner shim path, `sequence.seed`, Vite `webSocketToken`, Vitest `api.token` and
`tokenCreated`); the fixture's own `node_modules` appearing after run 1 with only caches in it; runner frames copying
the environment (`*`, and Jest's per-key copy) recorded as test reads; Jest's Level 0 install replacing the capture's
socket and `readdir` wrappers (a loopback connection went unseen); Jest's transform cache counted as an input; Jest
`--forceExit` exiting before the push; Vitest's asynchronous cleanup of its temp directory counted as a start-up
write (tainted every vue-core test); async and disposable `mkdtemp` results not counted as the test's own output.

## First local numbers (MEASURED, this container, 4 vCPU, Node 26.13.1; not the step 3 measurement)

| project | cold capture run (empty cache) | rerun, unchanged tree | edit |
|---|---|---|---|
| docusaurus @4c4ec4a (207 files, 3254 tests) | 101 s, plain parallel `vitest run` 37 s, serial `--det` not measured here | 17 s: **192 of 207 files reused** with proof (2991 tests); 15 files run: never cacheable (git, loopback servers, `/tmp` listings) or failing | — |
| vue-core @2e2f7c6 (`--project 'unit*'`, 185 files, 4156 tests) | 89 s | **2 s: 185 of 185 reused** | one line appended to `compiler-ssr/src/transforms/ssrVIf.ts`: 47 files run (25 s), 138 reused |

Runtime identity cost (MEASURED, docusaurus, 74,526 installed files, 1.16 GB): 0.70–0.85 s cold (4 threads),
0.35–0.45 s warm (memo).

## Comparison targets for step 3

* **Blacksmith test selection** (Vitest, early beta): import/require/fs tracking, no child processes (DECLARED in
  docs.blacksmith.sh; to be quoted with the page in REPORT.md). Not runnable here (Blacksmith runners only).
* **Nx**: `nx show projects --affected` per transition (project-level, package-based inference), mapped to test
  files: MEASURED in the walk.
