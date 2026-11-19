# detjs tap (node-tap, the `tap` package)

`detjs tap [--det options] [tap args]` — shell in `node/src/runners/tap.js` on the shared glue
`node/src/runners/common.js` (main side: options, discovery, reuse decision, launch, summary; child side: Level 0,
capture, test brackets) and the shared session / proof cache (`session.js`, `cache/proof.js`, `cache/capture.js`).
Without `--det` the project's tap runs unchanged.

Supported: tap 18+ (`@tapjs/run`, `@tapjs/core`); built and tested against tap 21.8. tap 16 and older (no
`@tapjs/run`) are refused (`detjs: tap ... without @tapjs/run and @tapjs/core`).

## Process model and hooks

| step | how |
|---|---|
| discovery | `tap list [user args]` in a child process (tap's own selection: `.taprc`, `package.json` "tap", globs, positionals); the preload (list mode) imports tap's `main-config.js` and reports the parsed configuration values, the project root, the configuration file and the plugin signature |
| order | files sorted by path; `--det-seed`: the shared shuffle (`shuffle_indices`). In the runner process the preload holds the per-file subtests tap creates (`TestBase.prototype.sub` of the runner root, `context: tap.isRunner`) and releases them in detjs' order: tap's own order depends on the completion order of asynchronous `stat` calls |
| run | `tap [user args] --jobs=1 --save=<files to run>` (+ `--disable-coverage` with `--det-cache`: coverage of a run that skips files is meaningless and tap fails a run whose coverage is incomplete). One process per test file, as tap does |
| test process | `TAP_CHILD_ID` set and `argv[1]` one of the files to run: Level 0 and the capture are installed by the preload (`NODE_OPTIONS=--require`, first); the root TAP object is caught when tap stores its singleton on `globalThis` (`Symbol.for('TAP private constructor')`), `t.jobs` is pinned to 1 |
| tests | every top-level subtest (`t.test`) is a test: begin at `subtestStart`, end at `subtestProcess` (its result is final there; `subtestEnd` can arrive after the next subtest started). Nested subtests and assertions belong to it; top-level assertions belong to the file |
| file verdict | the root's results (`complete`) and the process exit code; a process that exits without a clean end is never recorded as a pass |
| within-file order | declaration order, also with `--det-seed`: tap starts a subtest as soon as it is declared, so subtests cannot be reordered without changing tap's semantics (documented, not shuffled) |

Configuration digest: tap's parsed configuration values (minus output / scheduling keys: reporter, color, jobs,
save, changed, coverage report and thresholds), the configuration file by content, the plugin signature, the
command-line options (`--grep`, `--only`, `--node-arg`, `--test-env`, ... are keys), the runner version, and the
shared parts (detjs, Level 0 options, repository configuration files incl. `tsconfig*`).

## Refused or never cached, and why

* `before` / `after` scripts: they run outside the test processes and can change what tests read: every file of
  the session is uncacheable (`tap before/after script`).
* environment variables tap sets per test process (`TAP_CHILD_ID`, `TAP_JOB_ID`, `TAP_CHILD_KEY`,
  `_TAPJS_PROCESSINFO_*`): reads are keyed against the session's environment, so a test whose own code reads them is
  not cached (`env-unobserved`); tap's own reads are infrastructure.
* `t.testdir()` fixtures: written by the test (outputs), read back by it: cached. The first `t.testdir` of a fresh
  checkout creates `.tap/fixtures` (a `mkdir` whose prior state is an input): a second run converges.
* TypeScript / tsx: a module transformed for the first time by tsx starts esbuild's worker thread: never cached
  (worker thread); tsx's transform cache (content-addressed) makes the next run cacheable.
* tap's own bookkeeping (`.tap/processinfo`, `.tap/test-results`, `.tap/coverage`, `.tap/report`) is not an input.

The capture sees Node's ES module loader through asynchronous hooks (`DETJS_CAPTURE_LOADER=register`): in Node 22
a synchronous `module.registerHooks` hook in a process that also has tap's asynchronous loaders (mock, processinfo,
typescript) breaks `t.mockImport` (`loadSync is not a function`, or a dead lock).

Tests: `node/test/runner-tap.test.js` (shared cases in `runner-b-cases.js`, tap cases in `runner-b-specific.js`).
