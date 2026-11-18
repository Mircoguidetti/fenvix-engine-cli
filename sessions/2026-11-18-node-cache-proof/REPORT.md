PARTIAL

# Skip with proof for JavaScript / TypeScript (detjs `--det-cache`) — report

Branch `claude/node-cache-proof`. Labels: **MEASURED** (run, with the command or the GitHub Actions run id),
**ESTIMATED**, **DECLARED** (a vendor's own documentation), **UNKNOWN**. Intermediate report:
[INTERMEDIATE-1.md](INTERMEDIATE-1.md). Design: [docs/NODE-CACHE.md](../../docs/NODE-CACHE.md).

<!-- RESULTS -->

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
