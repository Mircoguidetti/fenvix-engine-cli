# detjs jasmine (the `jasmine` package for Node)

`detjs jasmine [--det options] [jasmine args]` — shell in `node/src/runners/jasmine.js` on the shared glue
`node/src/runners/common.js`. Without `--det` Jasmine runs unchanged.

Supported: jasmine 5-7 (`lib/jasmine.js`, `lib/runner_base.js`: `loadConfig`, `execute`, `loadSpecs`); built and
tested against jasmine 7.0 / jasmine-core 7.0. `--parallel` is removed under `--det` (noted).

## Process model and hooks

| step | how |
|---|---|
| discovery | Jasmine itself in list mode: the preload records the configuration object (`RunnerBase.loadConfig`) and replaces `execute`: the spec files, helpers and requires Jasmine resolved are written, nothing runs |
| configuration | that configuration (env options such as `failSpecWithNoExpectations`, `stopOnSpecFailure`, spec_dir, helpers list, requires, loader settings; `random` and `seed` excluded: detjs sets the order), the configuration file by content (`--config=`, `JASMINE_CONFIG_PATH`, or the default `spec/support/jasmine.{mjs,json,js}`), the command-line options (`--filter=` is a key) |
| --det | one process, spec files given in detjs' order, `random: false` (Jasmine's default `random: true` draws a new seed every run) |
| --det-seed | shared shuffle of every suite's children through Jasmine's `orderChildren` step (jasmine-core source hook at load: `return order.sort(node.children)`; top suite: files kept together in detjs' file order, each file's children shuffled with key `file`; nested suites with key `file::suite path`). Without the hook (another jasmine-core build): declaration order, noted |
| --det-cache | a fresh process per spec file (helpers, requires, globalSetup run in each): in one process a reused file A would change the context file B runs in (docs/ALL-RUNNERS.md) |
| tests | every spec: a reporter (`specStarted`: before its beforeEach functions; `specDone`: after its afterEach functions), added after the helpers are loaded (helpers often `clearReporters()`); a suite failure (beforeAll / afterAll) or a global failure fails the file |
| file verdict | `jasmineDone.overallStatus === 'passed'` and exit code 0; a run whose end detjs' reporter did not see is never recorded as a pass |

The spec and helper globs Jasmine expands inside a test process are discovery (path-scurry copies every Stats field,
times included): the helper list is in the configuration digest instead, and every helper is a loaded module.

## Not cached / limits

* cross-file state: a spec that depends on another file's globals passes in one process and fails in a process of
  its own: under `--det-cache` it is reported as a failure, never reused (test
  `--det-cache runs each spec file in its own process`);
* an `fdescribe` / `fit` makes Jasmine's overall status `incomplete`: such a file is never recorded as a pass.

Tests: `node/test/runner-jasmine.test.js`.
