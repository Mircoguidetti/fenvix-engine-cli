# detjs uvu

`detjs uvu [--det options] [dir] [pattern] [-r module] [-i ignore] [-b]` — shell in `node/src/runners/uvu.js` on
the shared glue `node/src/runners/common.js`. Without `--det` uvu runs unchanged. Supported: uvu 0.5 (the last
release line).

## Process model and hooks

| step | how |
|---|---|
| discovery | uvu itself in list mode (the preload wraps `uvu/parse`, which also loads the `-r` modules) |
| configuration | the command line (uvu has no configuration file; `-r` modules are loaded modules, inputs of every file), the runner version |
| --det | one process; `parse` is replaced in the test process: the `-r` modules load exactly as uvu loads them, the suites are detjs' list in detjs' order (sorted by path; `--det-seed`: shared shuffle) |
| --det-cache | a fresh process per test file (the runner's listing of the test directory is not an input there: it is discovery) |
| tests | uvu's runner is a closure, so its source is hooked when it loads (both `dist/index.js` and `dist/index.mjs`; through `module.registerHooks` load and `Module.prototype._compile` for CommonJS loaders such as `tsx/cjs`, `ts-node`): begin before a test's `before.each` hooks, end after its `after.each` hooks; `--det-seed` shuffles the suites of a file and the tests of a suite. A uvu build whose source is not recognised makes every file of the run fail-closed (never recorded as a pass) with a message |
| file verdict | no failing test and exit code 0 |

## Not cached / limits

* uvu test files run directly with `node test/x.js` (no CLI) are not covered: use `detjs uvu`;
* cross-file state, as for Jasmine: reported as a failure under `--det-cache`, never reused;
* `-r esm` (the `esm` package) does not work on Node 22 with or without detjs.

Tests: `node/test/runner-uvu.test.js`.
