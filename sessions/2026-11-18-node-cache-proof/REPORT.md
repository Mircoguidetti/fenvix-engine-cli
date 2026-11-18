PARTIAL

# Skip with proof for JavaScript / TypeScript (detjs `--det-cache`) — report

Branch `claude/node-cache-proof`. Labels: **MEASURED** (run, with the command or the GitHub Actions run id),
**ESTIMATED**, **DECLARED** (a vendor's own documentation), **UNKNOWN**. Intermediate report:
[INTERMEDIATE-1.md](INTERMEDIATE-1.md). Design: [docs/NODE-CACHE.md](../../docs/NODE-CACHE.md).

## Answer (so far)

* **Skip with proof now exists in the product for JS/TS**: `detjs vitest|jest --det --det-cache`. On docusaurus it
  skips **86% median / 63% mean of test time with proof** over 25 commits on GitHub Actions (MEASURED, run
  44349361887, transitions 26→50 of the skip study's window), with **0 wrong in 57,695 verified reuses** (every
  reuse compared with a fresh run at the same commit). The study harness measured 98% / 81% on the same project
  (MEASURED there): the product is lower because it keys every installed package file (a dependency bump reruns
  everything: 4 of 25 transitions) and never reuses files that run `git`, open sockets or read `/tmp` listings
  (≈12% of the time at every commit).
* vue-core: **1% median / 28% mean** (MEASURED, same run, transitions 26→50), 0 wrong in 34,409 verified reuses:
  13 of 25 transitions rerun everything (5 dependency bumps, 5 configuration changes, 3 changes to modules every
  test loads); the study measured 25% / 31% there.
* Overhead (MEASURED, Actions, 4 vCPU): the cold capture run costs **+6% (vue-core) to +12% (docusaurus)** over a
  serial `detjs --det` run without cache; serial Level 0 itself is ~2.1× the project's own 4-worker run. A warm
  rerun of an unchanged tree: 1.7 s for vue-core (185 of 185 files reused; full run 91 s) and 18.7 s for docusaurus
  (191 of 206 reused; full run 108 s, MEASURED locally).
* **Nx affected** (MEASURED, same transitions, priced with the same durations): docusaurus 24% / 53%, vue-core
  0% / 25%. detjs skips more at file level where Nx's project level reruns a whole package, and the same on the
  dependency-bump transitions (both rerun everything). Nx keys environment variables and runtime only when declared
  (DECLARED); detjs records them.
* **Blacksmith** Vitest selection: not runnable here; its tracking is narrower by its own documentation (no child
  processes, no globalSetup, lockfile change runs everything; DECLARED). Skip share UNKNOWN.

Pending at the time of writing (shared queue): docusaurus and vue-core transitions 1→25, React Native (Jest),
TanStack Query (Vitest + Nx), Lexical. This report is regenerated when they land.

## Results

### GitHub Actions (MEASURED; `python3 harness/node_cache/aggregate.py r1`)

| project | transitions | skip with proof: test time, median / mean | tests reused, median | verified reuses | wrong | Nx affected: time skipped, median / mean |
|---|---:|---:|---:|---:|---:|---:|
| docusaurus (26→50) | 25 | **86% / 63%** | 94% | 57,695 | **0** | 24% / 53% |
| vue-core (26→50) | 25 | **1% / 28%** | 0% | 34,409 | **0** | 0% / 25% |

Transitions that rerun everything, by main reason: docusaurus 4 runtime (dependency bumps) + 1 data
(`packages/docusaurus/package.json`, which docusaurus' own code imports); vue-core 5 runtime, 5 configuration,
3 code. On the other transitions the median share is 87% (docusaurus) and 60% (vue-core).

Wall time of the run that actually skips (vue-core, Vitest 4: valid in r1): 1,628 s over the 25 transitions vs
2,305 s for the full runs (0.71). Docusaurus skip-run wall times in r1 are not valid: Vitest 5 repeats the JSON
reporter's `outputFile` inside nested configuration, which the harness varied per run, so those skip runs missed on
configuration (fixed in 7ed78200; the verify-mode decisions, the shares and the 0-wrong check do not depend on it).
Valid docusaurus wall times: the local walk below.

| project | commit | plain (4 workers) s | `detjs --det` serial s | cold capture s | overhead of capture |
|---|---|---:|---:|---:|---:|
| docusaurus | 25 | 46.4 | 92.9 | 104.4 | +12% |
| docusaurus | 35 | 40.7 | 85.6 | 95.9 | +12% |
| docusaurus | 45 | 41.5 | 86.1 | 96.9 | +13% |
| vue-core | 25 | 42.7 | 85.5 | 90.5 | +6% |
| vue-core | 35 | 41.0 | 85.7 | 90.8 | +6% |
| vue-core | 45 | 41.7 | 88.1 | 93.4 | +6% |

Runtime identity: 0.3–0.9 s per session (docusaurus: 74,526 installed files, 1.16 GB; memoised).

### Local walk with the final engine (MEASURED, this container, 4 vCPU, Node 26.13.1; docusaurus transitions 41→50)

| | |
|---|---|
| test time skipped with proof, median / mean | 81% / 56% |
| verified reuses / wrong | 21,798 / **0** |
| wall: skip run vs full run, median | **26 s vs 115 s** (0.23) |
| warm rerun of an unchanged tree | 18.7 s (191 of 206 files reused) |
| Nx affected on the same transitions | 50% / 54% |


## What is delivered

`detjs vitest|jest --det --det-cache=DIR|https://host/<namespace>` reuses test-file results with proof, in the
product (not a study harness): the same Rust proof core as `pytest --det --det-cache` (store, entry keys, reuse check,
receipts in the Python format) through the napi bindings, the same shared cache service and protocol, the same rules
from the reviewed Python design (failures never reused; processes, sockets, entropy, `/proc` reads and cross-test
writes make a test uncacheable; runtime identity by content; start-up processes keyed by what they gave back).
What it covers per test, how, and the limits: [docs/NODE-CACHE.md](../../docs/NODE-CACHE.md).

* Tests: `node/test/cache.test.js`, 40 of 40 pass on Vitest 5.1 and Jest 30 (MEASURED locally; also in the workflow's
  `tests` job). Rust core 55 of 55 (MEASURED). Python proof-cache, shared-cache and R-008* suites with the extended core:
  93 passed, 3 skipped, 1 failed — `test_finished_startup_process_that_left_a_daemon_is_not_ignored`, which fails the
  same way on `origin/claude/shared-cache` itself in this container (MEASURED), so it is not caused by this work.
* Unit of reuse: the **test file** (per-test entries and receipts, but a file runs whole or not at all), because
  tests of a file share module state.
* Not cached by design: Vitest `isolate: false`, `vmThreads`/`vmForks` (Level 0's clock and randomness controls do
  not reach the vm realm, so results there rest on uncontrolled inputs), browser mode, custom Jest runners, Vitest
  type tests (`*.test-d.ts`, checked by `tsc` in a child process).

## Comparison

### Blacksmith Vitest test selection (DECLARED, docs.blacksmith.sh/blacksmith-selective-execution/vitest, read 2026-11-18)

| | detjs `--det-cache` | Blacksmith (DECLARED) |
|---|---|---|
| status | this branch | "The plugin is in early beta. Options and the cache format may change between releases." |
| what is tracked | modules loaded (Vitest graph, Node loader, Jest registries), files read incl. read-write opens, listings, existence, link targets, stem listings for resolution; env reads; machine facts; runtime identity by content (node binary, shared libraries, TZ, locale, CPU level, every installed file); config by content | "Each run records the modules and files every test depends on, through `import`, `require`, and `fs`." |
| child processes | the test is never reused; start-up processes keyed by argv, cwd, exit code, output | "Files read from a child process, from `globalSetup`, or from outside Node are not [tracked]; declare them with the `dependencies` option." |
| globalSetup | its reads, its imports' contents, the processes it ran: inputs of every file | not tracked (above) |
| environment variables | value of every variable read; enumeration = whole environment | not stated in the page beyond a Turborepo note ("`vitest` cannot see `ACTIONS_RESULTS_URL`") |
| dependencies / lockfile | every installed file by content (and the lockfile) | "a lockfile change runs everything" |
| failures | never reused | "A test the last successful run did not cover always runs." |
| proof per reuse | receipt per test (digest of every input checked) | no guarantee stated; "shadow" mode "runs every test and logs what the selection would have run" |
| runners | Vitest 1.4–5.x, Jest | "requires Vitest 5.1 or newer"; Vitest only |

Blacksmith could not be run here (its runners only): its skip share on these repositories is UNKNOWN.

### Nx (DECLARED: nx.dev/docs/reference/inputs; MEASURED: `nx show projects --affected` on the same transitions)

DECLARED: default task inputs are "all files in a project as well as any shared global inputs"; environment
variables and runtime commands are hashed "only when you declare them"; external dependencies the project imports
are considered. Project granularity: any change in a project (or a project it depends on) reruns all of the
project's tests; anything not declared (an environment variable, a file outside the project read at run time, a
child process's inputs) is not an input unless declared.

MEASURED: Nx 22.7.12 `show projects --affected --base=<i-1> --head=<i>` for every transition of the five windows
(package-based inference where the repository has no Nx configuration; TanStack Query uses its own Nx setup):
`harness/node_cache/results/nx/`. Priced with detjs' per-file durations in the tables above.

## Limits found in this session (each with where)

* Lexical's `unit` project (978 of 1,000 files) runs in `vmThreads`: not cached by design (MEASURED locally: 0 of 978
  files cacheable; `scripts-unit`, 22 files, cacheable).
* React Native: `packages/dev-middleware` socket suites fail or hang under Level 0 (10 s hook timeouts; one hang in
  `InspectorProxyCdpRewritingHacks-test.js` on a rerun, MEASURED locally) — Level 0 timer/socket interplay (docs/NODE.md
  J4), not the cache; those files use sockets and are never cached anyway.
* Jest decides before `globalSetup` runs (Jest calls the sequencer first): a globalSetup that runs processes reruns
  every file.
* Reused files are not in the runner's own reporters (they are in the detjs summary, receipts and
  `cache-summary.json`).
