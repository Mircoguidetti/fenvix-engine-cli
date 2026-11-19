# Every test runner on one engine (P-032 design)

Branch `claude/all-runners`. This is the contract every runner adapter follows. Owner: the all-runners session.

## The rule

A runner decides only four things: **which tests exist** (discovery), **when a test starts and ends** (its
lifecycle hooks), **in which order they run**, and **how it loads modules and mocks**. Everything else is the shared
engine and is never copied per runner:

| concern | where it lives (shared) |
|---|---|
| fingerprints, trace format, verifier, reproducible shuffle | Rust `detpy-core` (`recorder`, `trace`, `verify`, `order`) |
| proof store, entry keys, reuse check, receipts, verify draw, record plan | Rust `detpy-core::proof` + `detpy-py::session` (`CacheSession`) / `detpy-node` (`ProofCache`) |
| capture of inputs (files, listings, metadata, env, processes, sockets, entropy, clock) | Python: Rust `detpy-py::capture` (`CaptureCore`, sys.monitoring + audit hooks); Node: `node/src/cache/capture.js` |
| Level 0 controls (clock, seeds, fs order, network, hash seed re-exec) | Python: `detpy` modules over `detpy-py`; Node: `node/src/controls.js` |
| runtime identity, configuration digest helpers | Rust `identity.rs` / `treehash.rs`; `proofcache.runtime_identity`, `node/src/cache/runtime-id.js` |

## Python: one driver, one lifecycle

`python/detpy/runners/` holds the runner-neutral driver (`DetRun`) used by every non-pytest Python runner. It does
what the pytest plugin's hooks do, with the same calls into the same Rust objects:

1. options (`--det`, `--det-seed`, `--det-cache=DIR|URL`, `--det-cache-verify`, `--det-trace`, ... same names as the
   pytest plugin), hash-seed re-exec, `_install` of the controls;
2. `collect(ctx)`: import-time reads of a test module are attributed to `c|<file>` (like pytest's collector context);
3. `fixture(scope, owner, name)`: class / module set-up (`setUpClass`, `setUpModule`, zope layers, Django
   `setUpTestData`) recorded as `f|<scope>|<owner>|<name>` contexts, inputs of every test that uses them;
4. `decide(ids)` -> reused set (with receipts), before anything runs;
5. `begin(id)` / `end(id, outcome)` -> recorder bracket + `CacheSession.start_test` / `end_test` + capture context;
6. `report(id, when, outcome, longrepr)` -> `CacheSession.report` (same phase records as pytest reports);
7. `finish()` -> record, receipts, trace, summary.

Adapters (thin):

| runner | hooks used |
|---|---|
| `unittest` (`python -m detpy unittest ...`) | `unittest.TestCase.run` / `TestSuite._handleClassSetUp` / `_handleModuleFixture`, loader order |
| Django (`python -m detpy django manage.py test ...`) | the unittest hooks, plus `DiscoverRunner` order groups kept (TestCase, TransactionTestCase, other), DB set-up as start-up |
| nose2 | the unittest hooks (nose2 runs unittest cases; function and generator tests are `FunctionTestCase`s) |
| zope.testrunner | the unittest hooks, layers as `f|layer|...` contexts; layer subprocesses refused (not reused) |
| doctest (`python -m detpy doctest file ...`) | `doctest.DocTestRunner.run` per docstring |
| ward | ward's `Test.run` |
| Hypothesis (under each) | the seeds control: `derandomize`-equivalent seed per test id; the example database is an input (reads keyed) |

## Node: one session, many shells

`node/src/session.js` (options, run directory, trace merge) and `node/src/cache/proof.js` (`ProofSession`: config
parts, decide, record, receipts) already serve Vitest and Jest. New shells add only their runner glue:

| runner | process model | unit of reuse |
|---|---|---|
| `node --test` | process per file (default) | file |
| Mocha | one process for all files | file, in a fresh process per file under `--det-cache` |
| Jasmine | one process | same as Mocha |
| uvu | one process | same as Mocha |
| AVA | worker thread / process per file | file |
| tap | process per file | file |
| Bun `bun test` | one process, Bun runtime | refused unless the Bun capture covers every API used (Bun.file, Bun.spawn, ...) |
| Deno `deno test` | one process, Deno runtime | refused unless the Deno capture covers every API used |

### Why "a fresh process per file" for shared-process runners

When all test files share one process (Mocha, Jasmine, uvu, Bun), file B's result can depend on what file A did
(module-level code, globals, `process.env`, the module cache). If the engine skipped A and ran B, B would run in a
context that never existed in the reference run: reusing A's result is fine, but B's fresh result is no longer
what a full run gives. Under `--det-cache` these runners therefore run each file in its own process, the same
model as Jest and `node --test`. The control tests count tests whose outcome changes under file isolation; such a
file is reported, never silently reused.

## Soundness rules (unchanged, shared)

* failures are never reused; a test that ran a process, opened a socket, read entropy or `/proc`, or read a file
  another test wrote is not cached;
* every input kind the capture knows (content, metadata, listings, recursive listings, existence, link targets,
  resolution misses, mocks directories, env reads, env enumeration, machine facts) is a key part;
* an API the capture does not see makes the test **uncacheable**, never silently reusable (the R-021 F3 rule);
* the adversarial suites translate R-009, R-017 and R-021 to every runner.
