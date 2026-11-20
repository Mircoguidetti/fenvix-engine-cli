# `node --test` under detjs (`detjs node-test`)

Builder: node-a (all-runners). Code: `node/src/nodetest/` (`cli.js` main process, `driver.js`, `preload.js`,
`facade.js` + `facade.cjs`/`facade.mjs`), the shared per-process file lifecycle `node/src/fileproc.js`, and the
shared layers it reuses unchanged in design (`session.js`, `controls.js`, `cache/capture.js`, `cache/proof.js`).

```bash
detjs node-test --det [node flags] [file patterns]                  # = node --test ..., deterministic (Level 0)
detjs node-test --det --det-seed=7 ...                              # reproducible shuffle of files and tests
detjs node-test --det --det-cache=.detjs-cache [...]                # skip test files with proof
detjs node-test --det --det-cache=DIR --det-cache-verify [...]      # decide, run everything, compare
```

Without `--det` (and without `DETJS=1`) it runs `node --test <args>` unchanged.

## Support: `--det` and `--det-cache` (skip with proof)

| feature | status |
|---|---|
| process per file (node's default isolation) | supported; unit of reuse = the test file |
| `--test-isolation=none` / `--experimental-test-isolation=none` | `--det`: one process (the driver), as node does; `--det-cache`: every file in its own process (header note). Control test counts the tests whose outcome changes |
| `--test-concurrency` | ignored under `--det` (files one at a time, in the plan's order) |
| `--test-name-pattern`, `--test-skip-pattern`, `--test-only` | passed to node; part of the configuration digest (another selection never reuses) |
| `--test-shard` | applied to the sorted file list like node does (selection: not in the digest) |
| `--test-reporter`, `--test-reporter-destination` (built-in and custom) | attached by the driver like node's CLI; reporter locations kept (see facade) |
| `--test-timeout`, `--test-force-exit`, `--test-update-snapshots`, `--experimental-test-module-mocks`, `--experimental-test-coverage` + `--test-coverage-*` | passed through (coverage flags are output: not in the digest) |
| `--import`, `--require`, `--loader`, `--env-file`, `--conditions`, any other node flag | given to the driver, inherited by every test process; in the digest, project files they name by content |
| `NODE_OPTIONS` | in the digest; its `--require`/`--import`/`--loader` modules are moved after detjs' preload (else an `fs` reference they take before the capture is invisible, adversarial test "unwrapped read"); test processes get the original `NODE_OPTIONS` back for the processes they start |
| type stripping (default on in Node 22.18+), `--import tsx`, `--require ts-node/register` | supported (default pattern gains `.ts/.mts/.cts` when type stripping is on, as node's) |
| `--watch` | refused under `--det` |
| `--test-global-setup` (Node 24) | the run is not cached (the module runs in the runner process, outside the capture) |
| Node < 22.15 (no `module.registerHooks`) | `--det` works with fixed order; no `node:test` facade (no shuffle of tests, no serial `concurrency`) |

## Hooks used (the runner glue)

* **Main process** (`cli.js`): finds the files as `node --test` does (node's `createTestFileList`: the same default
  pattern, `node_modules` excluded, sorted; `--test-shard`), orders them (sorted or `native.shuffleIndices`, as the
  Jest sequencer), and with `--det-cache` builds the configuration digest and calls `ProofSession.decide` before
  any file runs. Reused files are left out of the run; the receipts and summary list them.
* **Driver** (`driver.js`): `node <user flags> --require preload.js driver.js`; calls `node:test`'s `run()` with the
  ordered files, `concurrency: 1`, the isolation, patterns and timeout, and attaches the reporters. Node propagates
  the driver's execArgv to every file process (`getRunArgs`), so each one gets the user's flags plus the preload.
  The per-file `test:summary` events give each file's verdict (a file is recorded as passed only if its summary
  says so and its process exited 0).
* **Test file process** (`preload.js`, `NODE_TEST_CONTEXT=child-v8`): installs Level 0 and the cache capture before
  any user module, opens the file (trace part, module seed, capture context), and when the file first resolves
  `node:test`, registers on the file's root test a `beforeEach` (inherited by every test, prepended to the user's
  hooks: the test begins before its `beforeEach` hooks) and an `afterEach` (marks it finished). A test ends when the
  next one begins or at process exit (its `afterEach` hooks inside the bracket); the outcome is read from the
  test context (`passed`; `t.skip()`/`t.todo()` -> skipped). Subtests (`t.test`) belong to their test. The capture
  is written after every other `exit` listener ran (`process.emit` wrapper), so code reading files at shutdown is
  part of the file (R-009 "interpreter shutdown", adversarial test).
* **`node:test` facade** (`facade.js`): the preload redirects `node:test` (registerHooks resolve) to a facade that
  (1) sets `concurrency` to 1 in test/suite/`t.test` options, (2) with `--det-seed` declares the tests of each scope
  in a reproducible shuffled order (suite children: when the suite callback returns; top-level: when the entry
  module finished evaluating: after `Module.runMain` for CommonJS, a call appended to the ES module entry; nothing
  runs before, so the order does not depend on timing), and (3) calls node:test through a one-line trampoline
  compiled with the caller's file name and position, because node:test records its caller's location
  (`getCallerLocation`) for reporters (spec failures, junit `file`/`line`): control test "reporter locations".
* **`--test-isolation=none` (`--det` only)**: the driver is the test process; the hooks attach after `run()` created
  the root; a new trace part starts when a test of another file begins.

## What is refused or not cached, and why

* Every rule of the shared capture (docs/NODE-CACHE.md): processes, worker threads, sockets, entropy, `/proc`, files
  another test file wrote, unkeyed metadata, `node:sqlite` URIs, `process.binding` (new), bare optional modules
  from project code: such files always run.
* `--test-global-setup`: not cached (above).
* Per-test reuse: no (unit = file, as Vitest/Jest).
* Tests that never begin (declared skipped, filtered by a pattern) are not in the trace or the receipts (node:test
  runs no hook for them); node's own reporter lists them.

## Shared-layer changes made for this runner (generic, used by every runner)

* `cache/capture.js`: an existence probe before writes whose success depends on what is at the path (exclusive
  creates `wx`/`O_EXCL`, non-recursive `mkdir`, `unlink`/`rmdir`/`rm` without force, `link`/`symlink` destinations,
  `copyFile` with `COPYFILE_EXCL`; Node's own `cp`/`rm` internals excluded); `process.binding('fs'|...)` by
  non-infrastructure code makes the test not cached; `node:sqlite` `DatabaseSync` keeps its arity (an explicit
  `undefined` options argument was refused: single-argument opens failed under the capture); tool caches skipped
  like jiti's (`$TMPDIR/tsx-<uid>`, `$TMPDIR/swc-node-<uid>`, `v8-compile-cache`); tsx's relay pipe to a parent
  `tsx` CLI is not a socket of the test; esbuild's own service thread is not a worker of the test.
* `cache/proof.js`: `captureFilter` (a shell corrects a file's `ok` with the runner's verdict); environment names
  that are `Object.prototype` properties (`process.env.constructor`) no longer crash the recording; new
  not-cached reason `binding`.
* `sites.js`: `node:internal/test_runner` frames are runner infrastructure (node:test's durations and timeouts use
  the real clock and stay out of the fingerprints).
* `fileproc.js` (new): the per-process file lifecycle shared with the Mocha shell.

Tests: `node/test/runner-node-test.test.js` (control + adversarial); results in docs/runners/BUILD-node-a.md.
