# detjs ava (AVA)

`detjs ava [--det options] [ava args]` — shell in `node/src/runners/ava.js` on the shared glue
`node/src/runners/common.js` and the shared session / proof cache. Without `--det` AVA runs unchanged.

Supported: AVA 6+ (ES module internals loadable with `require(esm)`: `lib/runner.js`, `lib/scheduler.js`,
`lib/run-status.js`, `lib/load-config.js`); built and tested against AVA 8.4. AVA 5 and older are not supported.

## Process model and hooks

| step | how |
|---|---|
| discovery | AVA itself in list mode: the preload replaces `scheduler.failingTestsFirst`, which receives the files AVA selected (configuration globs, `files`, command-line filters), writes them and returns none |
| configuration | AVA's `loadConfig` in the detjs process (ava.config.* / package.json "ava", the factory function evaluated; its imports are start-up inputs), the configuration files by content, the command-line options (`--match`, `--node-arguments`, `--no-worker-threads`, ... are keys) |
| order | files sorted by path; `--det-seed`: shared shuffle. AVA's own order puts the files that failed in the previous run first (`failingTestsFirst`, a dependency between runs): replaced by detjs' order restricted to the files that are not reused |
| run | `ava [user args] --concurrency=1 --serial`: one file at a time, the tests of a file one after the other; worker threads (default) or worker processes as configured |
| worker realm | the preload reaches every worker thread through `NODE_OPTIONS` (verified: Node applies NODE_OPTIONS preloads to `new Worker()` even with explicit `execArgv`); Level 0 (`installProcess`, `installRealm`) and the capture are installed per realm before AVA loads the test file; Node's internal loader thread is skipped (`isInternalThread`) |
| tests | `Runner.prototype.runTest` (patched in the worker realm): a test's bracket covers its beforeEach / afterEach hooks; outcome = AVA's own result (`test.failing` passes when it fails) |
| task order | `Runner.prototype.start`: fixed = declaration order, serial tests first as AVA does; `--det-seed`: shared shuffle of the serial and of the concurrent tasks (key `file\0serial|concurrent`) |
| file end | `Runner.prototype.saveSnapshotState` (snapshots written), then the capture is written; a worker that exits non-zero rewrites it as failed |
| main-process verdict | `RunStatus.prototype.emitStateChange` in AVA's main process: a file with a hook failure, uncaught exception, unhandled rejection, timeout, interrupt, unexpected `process.exit`, or that never sent `worker-finished` is marked failed (`common.markFailed`): never recorded as a pass |

## Refused or never cached, and why

* a test file that uses a shared worker (`ava/plugin` loaded): code running in AVA's main process: never cached;
* a test that starts its own worker thread: never cached (the capture flags `new Worker`);
* snapshot files (`snapshots/*.snap`, `.md`) are read by the worker: inputs; the first run that records new
  snapshots writes them (outputs of that file);
* tsx (`nodeArguments: ['--import=tsx']`): first transform of a module starts esbuild's worker thread: never cached
  that run; the next run (tsx cache warm) is cacheable;
* `match` / `--match` are part of the digest; `failFast`, `concurrency`, `serial`, reporters, `verbose`, `tap`
  are not.

Tests: `node/test/runner-ava.test.js`.
