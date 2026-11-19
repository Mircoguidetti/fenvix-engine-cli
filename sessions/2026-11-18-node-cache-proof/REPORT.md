DONE

# Skip with proof for JavaScript / TypeScript (detjs `--det-cache`) — report

Branch `claude/node-cache-proof`. Labels: **MEASURED** (run, with the command or the GitHub Actions run id),
**ESTIMATED**, **DECLARED** (a vendor's own documentation), **UNKNOWN**. Intermediate report:
[INTERMEDIATE-1.md](INTERMEDIATE-1.md). Design: [docs/NODE-CACHE.md](../../docs/NODE-CACHE.md). Raw results and
tables: `harness/node_cache/results/r*/` (`python3 harness/node_cache/aggregate.py <label> --md`).

## Answer

* **Skip with proof now exists in the product for JS/TS**: `detjs vitest|jest --det --det-cache=DIR|https://…`
  reuses test-file results with proof (same Rust proof core, receipts and shared cache service as
  `pytest --det --det-cache`). On GitHub Actions it was checked against a fresh run at the same commit for every
  reuse: **0 wrong in 449,270 verified reuses** across five repositories (MEASURED, below; 431,029 test results and
  18,241 file-level entries, each compared by outcome only, so a reused `skipped` result always verifies; corrected
  by review r021).
* **Share of test time skipped with proof** (MEASURED, GitHub Actions, per transition = one commit after another,
  priced with each file's duration in the fresh run; median / mean):

  | project (runner) | transitions | detjs skip with proof | Nx affected, same transitions | skip study (harness) |
  |---|---:|---:|---:|---:|
  | docusaurus (Vitest) | 50 | **88% / 73%** | 26% / 56% | 98% / 81% |
  | vue-core (Vitest) | 50 | **26% / 32%** | 28% / 29% | 25% / 31% |
  | TanStack Query (Vitest, Nx monorepo) | 50 | **91% / 61%** | 92% / 69% | — |
  | React Native (Jest monorepo) | 9 | **0% / 1%** (53–57% outside `dev-middleware`) | 98% / 87% (unproven) | — |
  | Lexical (Vitest monorepo) | 19 | **0% / 0%** (97% of files in `vmThreads`, not cacheable) | 40% / 51% (approximate) | — |

* Why below the study on docusaurus: the product keys every installed package file and the lockfile (6 of 50
  transitions are dependency bumps and rerun everything; the study did not key them), and never reuses files that run
  processes, open sockets or read `/tmp` listings. On the other 43 transitions the median is 89%.
* Wall time of the run that actually skips (MEASURED, r3, valid skip runs): docusaurus **18 s vs 88 s** (median,
  0.20), vue-core **25 s vs 64 s** (0.38). Warm rerun of an unchanged tree: vue-core 1.2 s (185/185 files reused),
  docusaurus 11–12 s (194–195 of 206–207), TanStack Query 40–60 s (161–162 of 179–180; 78 type-test files and 27
  `vmThreads` files always run).
* **Overhead** (MEASURED, Actions, 4 vCPU, every measured row of r1/r3/r4/r5; corrected by review r021): the cold
  capture run costs **+6% (vue-core) to +14% (docusaurus)** over a serial `detjs --det` run without cache (vue-core
  +5.7% to +9.6%, docusaurus +9.0% to +13.9%; TanStack +7–16%, i.e. +6.7% to +16.4%; React Native ≤ +0.6%, Lexical
  ≤ +2.4%); serial Level 0 itself is 1.65–2.15× the project's own parallel command (React Native: 30×, from
  `dev-middleware`, below). Runtime identity: 0.2–3 s per session (memoised; up to 220,327 installed files / 3.47 GB,
  TanStack Query r4/r5 commit 44; 171,316 / 2.72 GB at its commit 0).
* **Nx** skips about as much as detjs on TanStack Query at the median (92% vs 91%) and more on average (69% vs 61%:
  release commits and repository-wide configuration edits rerun everything in detjs). It skips more where detjs
  cannot cache (React Native, Lexical), and much less on single-package repositories (docusaurus: 26% vs 88%),
  because its unit is the project. Nx reruns nothing for an undeclared input,
  and its skips there carry no proof. In React Native, 95% of the test time is in `dev-middleware` socket suites that
  Nx skips whenever that package is not affected; detjs never reuses them, because they open sockets. **Blacksmith**
  could not be run here; by its own documentation it tracks less (no child processes, no `globalSetup`, lockfile
  change runs everything; DECLARED). Its skip share is UNKNOWN.

## What is delivered

`detjs vitest|jest --det --det-cache=DIR|https://host/<namespace>`, in the product (not a study harness):

* the Rust proof core (`detpy_core::proof`: store, entry keys, reuse check, receipts in the Python format) through
  napi (`crates/detpy-node`), three new dependency kinds in the shared core (`l:` link target, `g:` names sharing a
  module's stem for resolution shadowing, `p:` a `package.json`'s resolution fields only) and a tree hasher for the
  runtime identity (`crates/detpy-core/src/treehash.rs`);
* capture per process and worker (`node/src/cache/capture.js`): modules loaded, files read, read-write opens,
  listings, existence probes, link targets, environment reads (enumeration = whole environment), machine facts,
  child processes, worker threads, sockets, UDP, entropy, `/proc`, clock;
* runtime identity (`node/src/cache/runtime-id.js`): node binary and versions, mapped shared libraries, glibc, TZ,
  locale, CPU level, lockfiles, every installed file under every `node_modules` (ancestors' and `NODE_PATH` too);
* configuration (`node/src/cache/proof.js`): detjs and Level 0 options, the runner's resolved configuration
  (Vitest per project including Vite settings and config-file imports; Jest `--showConfig`), configuration files of
  the repository by bytes; **keyed per project** (a test file depends on the global parts and its own project's
  configuration);
* the same shared cache client and protocol as Python (`node/src/cache/remote.js`): `--det-cache=https://…`;
* rules from the reviewed Python design: failures never reused; processes, workers, sockets, entropy, `/proc` reads
  and reads of files another test wrote make a test uncacheable; start-up processes are keyed by what they gave back.

Tests: `node/test/cache.test.js`, **45 of 45** pass on Vitest 5.1 and Jest 30 (MEASURED locally, Node 26; also run by
the workflow's `tests` job), one per input and per reviewer hole translated to Node (git reads, TZ, environment
enumeration, `child_process`, `worker_threads`, start-up work in `globalSetup`/`setupFiles`, read-write opens,
symlinks, loopback sockets, files written by another test file, resolution shadowing, `package.json` resolution
fields, snapshots, configuration file imports, per-project configuration, the shared service). Rust core: 56 of 56.
Python proof-cache, shared-cache and R-008* suites with the extended core: 93 passed, 3 skipped, 1 failed
(`test_finished_startup_process_that_left_a_daemon_is_not_ignored`), which fails the same way on
`origin/claude/shared-cache` itself in this container (MEASURED), so it is not caused by this work.

Unit of reuse: the **test file** (per-test entries and receipts, but a file runs whole or not at all), because tests
of a file share module state. Not cached by design: Vitest `isolate: false`, `vmThreads`/`vmForks` (Level 0's clock
and randomness controls do not reach the vm realm), browser mode, custom Jest runners, Vitest type tests
(`*.test-d.ts`, checked by `tsc` in a child process).

## Results (MEASURED on GitHub Actions)

Method (`harness/node_cache/walk.py`, workflow `.github/workflows/node-cache-proof.yml`): per repository, the 51
commits of the skip study (docusaurus, vue-core) or 51 first-parent commits (the others), split in shards; per
commit *i*: a **skip run** on a copy of the cache as it was after commit *i−1* (the real decision, real wall time)
and a **verify run** from the same cache state with `--det-cache-verify` (same decisions, but every file runs and
each would-be reuse is compared with the fresh result; a mismatch is rechecked to separate flakiness from a wrong
reuse). Shares are priced with each file's duration in the verify run. Nx 22.7.12 `show projects --affected
--base=<i-1> --head=<i>` on the same transitions, priced the same way (package-based inference where the repository
has no Nx configuration). Runs: r1 = 44349361887 (docusaurus, vue-core, React Native, Lexical), r3 = 44381724251
(wall times), r4 = 44415205842 and r5 = 44440829981 (TanStack Query).

| project | transitions | skip with proof: time, median / mean | tests reused, median | verified reuses | wrong | flaky mismatches | Nx: time skipped, median / mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| docusaurus (r1) | 50 | **88% / 73%** | 94% | 132,108 | **0** | 0 | 26% / 56% |
| vue-core (r1) | 50 | **26% / 32%** | 46% | 85,112 | **0** | 0 | 28% / 29% |
| TanStack Query (r5) | 50 | **91% / 61%** | 94% | 158,515 | **0** | 0 | 92% / 69% |
| TanStack Query (r4, configuration not yet per project) | 50 | 90% / 58% | 91% | 148,985 | **0** | 0 | 92% / 69% |
| React Native (r1) | 9 | **0% / 1%** | 0% | 22,574 | **0** | 0 | 98% / 87% |
| Lexical (r1) | 19 | **0% / 0%** | 8% | 50,961 | **0** | 0 | 40% / 51% |

Transitions that rerun everything, by reason (MEASURED, from each run's miss reasons and changed files):

* docusaurus 7 of 50: 6 dependency bumps (lockfile and installed packages changed), 1 data
  (`packages/docusaurus/package.json`, which docusaurus' own code imports). Median on the other 43: 89%.
* vue-core 15 of 50: 5 dependency bumps, 5 configuration (root `package.json` changes, which also bump
  dependencies), 5 changes to modules nearly every test loads (2 of 184 files reused). Median on the rest: 27%.
* TanStack Query (r4) 16 of 50: 2 dependency bumps, 14 configuration. Of the 14, release commits bump every package's
  `package.json` and the lockfile (rerun anyway); the others change one or two packages' Vite configuration, or a
  `package.json` that their Vite configuration imports (`import packageJson from './package.json'` for `test.name`),
  and reran every package because the configuration was one digest. Fixed in 48d2068c (per-project configuration,
  below) and measured again in r5. Median on the other 34: 93%.
* TanStack Query (r5, per-project configuration) 14 of 50: transitions 34 and 35 now reuse 95% (were 0%). The rest:
  7 lockfile changes (release and dependency commits), 2 dependency bumps, 2 edits of `tsconfig*.json` under
  `examples/` (every `tsconfig*` of the repository is a global input), and 3 changes to a package's `package.json`
  that its `vite.config.ts` imports. Those now miss as **data**, not configuration: the configuration loader reads
  the file during start-up, and every project file read at start-up is an input of every test file. Narrowing that
  rule (a start-up read made for one project's configuration only) is the next step; it needs to tell apart why a
  file was read at start-up (one project's configuration vs `globalSetup` or a plugin acting on every project), so it
  was not rushed into this run.
* React Native 5 of 9: one transition whose recorded miss reason is `config`, not `runtime` (36; most likely a root
  `package.json` change; named as measured after review r021), and four times (the first transition of each shard, and 37 after
  the install at 36) the harness's fallback
  `yarn install` (used when `--frozen-lockfile` fails) had rewritten `yarn.lock`, and the next checkout restored it.
  The engine correctly keyed the changed lockfile (only the `lockfiles` part differed, installed packages were
  identical). This is a harness artifact. On the other transitions 232 of 284 files (80% of the tests) are reused,
  but the time share is 2–3%: `packages/dev-middleware` (5 suites with sockets, never cacheable) takes ~2,044 s of
  ~2,130 s under Level 0 (10 s hook timeouts; the project's own run takes 71 s for everything). Outside
  `dev-middleware`, **53–57%** of the time is skipped with proof.
* Lexical: its `unit` project (914–970 of 936–992 files) runs in `vmThreads`, not cacheable by design; 7–11 files of
  `scripts-unit` are reused at every transition.

No verify run found a mismatch, wrong or flaky, in any repository. Lexical's `@lexical/y` and
`@lexical/react` files disagree with themselves between the skip and the verify run of the same commit 53 times
(uncached files, `vmThreads`); most of the 37 files Nx would have skipped while their outcome changed from the
previous commit are these, so whether any is a real Nx miss is UNKNOWN. Some `@lexical/y` files report negative
durations (they move the worker's clock back); the aggregation counts them as 0 s, which makes Lexical's Nx share
approximate.

### Wall time and overhead (MEASURED)

| project | run | plain (project's command) s | `detjs --det` serial, no cache s | cold capture s | capture overhead | warm rerun s (files reused) |
|---|---|---:|---:|---:|---:|---:|
| docusaurus | r3, commit 40 | 36.9 | 78.5 | 87.6 | +12% | 11.9 (194/206) |
| docusaurus | r3, commit 50 | 36.8 | 79.2 | 86.3 | +9% | 11.3 (195/207) |
| docusaurus | r1, commit 45 | 41.5 | 86.1 | 96.9 | +13% | (r1 warm runs invalid, below) |
| vue-core | r3, commit 40 | 29.4 | 61.0 | 64.8 | +6% | 1.15 (185/185) |
| vue-core | r1, commit 45 | 41.7 | 88.1 | 93.4 | +6% | 1.77 (185/185) |
| TanStack Query | r4, commit 0 | 78.4 | 136.2 | 145.3 | +7% | 41.2 (161/179) |
| TanStack Query | r3, commit 50 | 89.5 | 169.7 | 187.9 | +11% | 52.5 (162/180) |
| TanStack Query | r5, commit 27 | 72.0 | 137.0 | 152.2 | +11% | 40.5 (162/180) |
| React Native | r1, commit 34 | 72.0 | 2,126.4 | 2,135.4 | +0.4% | 2,087.3 (232/284) |
| Lexical | r1, commit 34 | 618.8 | 1,157.1 | 1,167.8 | +0.9% | 1,155.3 (12/966) |

| project | skip run vs full verify run, median | sum over the transitions |
|---|---:|---:|
| docusaurus (r3, last 10 transitions) | **18 s vs 88 s** (0.20) | 394 s vs 880 s |
| vue-core (r3, last 10) | **25 s vs 64 s** (0.38) | — |
| vue-core (r1, 50) | 40 s vs 76 s (0.52) | 2,479 s vs 3,678 s |
| TanStack Query (r4, 50) | 58 s vs 178 s (0.33) | 4,926 s vs 8,793 s |
| TanStack Query (r5, 50) | **44 s vs 149 s** (0.29) | 3,815 s vs 7,140 s |

The docusaurus skip and warm runs in r1 are not valid wall times: Vitest 5 repeats the JSON reporter's `outputFile`
inside nested configuration, the harness varied it per run, and those runs missed on configuration. Fixed in
7ed78200 (output and selection settings excluded at every depth, with a regression test); r3 re-measured the wall
times. The verify-mode decisions, shares and the 0-wrong check do not depend on it.

## Comparison

### Nx (DECLARED: nx.dev/docs/reference/inputs; MEASURED above)

DECLARED: default task inputs are "all files in a project as well as any shared global inputs"; environment
variables and runtime commands are hashed "only when you declare them"; external dependencies the project imports
are considered. Consequences seen in the measurements:

* granularity is the project: on docusaurus (most tests in one package) Nx reruns that whole package for most
  changes, so it skips 26% median where detjs skips 88%;
* on monorepos with many small packages (TanStack Query, React Native, Lexical) Nx skips more than detjs where detjs
  cannot cache (`vmThreads`, sockets, type tests) or where a shared input changed;
* Nx's skips carry no proof, and inputs it does not see (an environment variable, a file outside the project read at
  run time, a child process's inputs) are not inputs unless declared. detjs records them.

### Blacksmith Vitest test selection (DECLARED, docs.blacksmith.sh/blacksmith-selective-execution/vitest, read 2026-11-18)

| | detjs `--det-cache` | Blacksmith (DECLARED) |
|---|---|---|
| status | this branch | "The plugin is in early beta. Options and the cache format may change between releases." |
| what is tracked | modules loaded (Vitest graph, Node loader, Jest registries), files read incl. read-write opens, listings, existence, link targets, stem listings for resolution; env reads; machine facts; runtime identity by content (node binary, shared libraries, TZ, locale, CPU level, every installed file); config by content, per project | "Each run records the modules and files every test depends on, through `import`, `require`, and `fs`." |
| child processes | the test is never reused; start-up processes keyed by argv, cwd, exit code, output | "Files read from a child process, from `globalSetup`, or from outside Node are not [tracked]; declare them with the `dependencies` option." |
| globalSetup | its reads, its imports' contents, the processes it ran: inputs of every file | not tracked (above) |
| environment variables | value of every variable read; enumeration = whole environment | not stated beyond a Turborepo note |
| dependencies / lockfile | every installed file by content (and the lockfile) | "a lockfile change runs everything" |
| failures | never reused | "A test the last successful run did not cover always runs." |
| proof per reuse | receipt per test (digest of every input checked) | no guarantee stated; "shadow" mode "runs every test and logs what the selection would have run" |
| runners | Vitest 1.4–5.x, Jest | "requires Vitest 5.1 or newer"; Vitest only |

Blacksmith runs only on its own runners: its skip share on these repositories is UNKNOWN.

## Fixes made from the measurements (each with a test)

* Configuration digest stability: runner shim path, `sequence.seed`, `api.token`, `webSocketToken`, nested
  `outputFile` (Vitest 5) — 7ed78200.
* Runtime identity: tool state written inside installed packages at run time (Vitest typecheck's
  `tsconfig.tmp.tsbuildinfo` in `vitest/dist`) made TanStack Query's skip and verify runs disagree (r2: 0% median)
  — suffix exclusions in the tree hasher, e7a2d6e5 (r4: 92% median).
* **Configuration per project** (48d2068c): a file is keyed by the global parts (detjs, Level 0, runner version and
  options, other tools' configuration files, the root Vitest configuration and every file it imports) plus its own
  project's resolved configuration, its configuration file and the files that file imports. Nested
  `vite.config.*`/`vitest.config.*` are keyed through the project that loads them. A project name shared by two
  projects (Jest projects without `displayName`) keeps the whole digest. Shared-cache lookups and checks of pulled
  entries use the same per-project digest. Tests: a project's imported file and its configuration file rerun only
  that project; the root configuration and its imports rerun everything; two unnamed Jest projects.

## Limits (each with where)

* Not cacheable by design: `vmThreads`/`vmForks` (Lexical: 97% of files), browser mode, `isolate: false`, custom
  Jest runners, Vitest type tests (TanStack Query: 78 of 267 files).
* Coarse inputs that rerun more than needed: every installed package file and the lockfile are one runtime digest (a
  dependency bump reruns everything); the repository's configuration files of other tools (tsconfig, babel, …) and
  the root `package.json` are global; a file that imports its package's `package.json` depends on all of it; every
  project file read at start-up (configuration loading included) is an input of every test file (TanStack Query r5:
  3 of 50 transitions).
* Coverage of the monorepo walks: React Native 9 of 50 transitions and Lexical 19 of 50 (MEASURED). Under Level 0 one
  React Native run takes ~35 min (`dev-middleware`) and one Lexical run ~20–25 min, and each job has a ~5 h budget
  for its shard. Docusaurus, vue-core and TanStack Query cover all 50.
* Jest decides before `globalSetup` runs (Jest calls the sequencer first): a `globalSetup` that runs processes reruns
  every file.
* React Native's `dev-middleware` socket suites fail or hang under Level 0 (timer/socket interplay, docs/NODE.md J4).
  They are never cached anyway.
* Reused files are not in the runner's own reporters (they are in the detjs summary, receipts and
  `cache-summary.json`).
* Wall times are from GitHub-hosted 4 vCPU runners on a shared queue; overhead varies ±10% between runs of the same
  commit (MEASURED: docusaurus commit 0 vs 35 in r1).
