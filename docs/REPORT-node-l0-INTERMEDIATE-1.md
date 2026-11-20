# Node L0 — intermediate report 1 (steps 1–3)

Session: node-l0, 2026-11-16. Repository fenvix-engine-cli, branch `claude/node-l0`
(created from `claude/gracious-rubin-eyswxd`).

> Delivery note: attaching fenvix-brain-cli was refused twice by the session's
> permission system, so the brain documents could not be read; per the
> coordinator's fallback this report lives in fenvix-engine-cli
> `docs/REPORT-node-l0-INTERMEDIATE-1.md` (branch `claude/node-l0`). The rules
> relayed by the coordinator (English, labelled numbers, shared event
> vocabulary, report paths) are applied.

## Step 1 — Node bindings (DONE, MEASURED by tests)

* New crate `crates/detpy-node` (napi-rs 3, N-API 6) next to `crates/detpy-py`,
  with the same surface: `Recorder` (+ `recordPacked`, events batched from JS),
  `Cassette`, `verify`, `verifyText`, `deriveSeed`/`deriveSeedWords`,
  `shuffleOrder`, `shuffleIndices`, `orderDigest`, `digest`, `mergeTraces`,
  `backends`. Seeds cross the boundary as `BigInt`.
* Core additions (used by both shells, 41/41 Rust tests pass):
  `order::shuffle_indices` (one level of the hierarchical shuffle; the
  module → class → test shuffle now uses it, identical results) and
  `trace::merge_traces` (concatenate per-file trace parts in execution order).
* Same trace and cassette formats as Python: `detjs verify` reads Node traces,
  and the CI job runs `python -m detpy verify` on a Node trace (the Python
  binding of the same verifier).

## Step 2 — shells for Vitest and Jest (DONE)

`node/` (package `detjs`), `detjs vitest|jest --det [--det-seed=N] …` or
`DETJS=1`. Architecture, options and limits in `docs/NODE.md`.

| control | Vitest (1.4–5.x; tested 3.2.7 and 5.1.0) | Jest (tested 30.5.2) |
|---|---|---|
| order of files | sequencer: sorted by path / seeded shuffle | `--testSequencer` |
| order of tests | custom runner `onCollected`, describe-contiguous shuffle | circus `run_start`, same shuffle |
| seeds | `Math.random` xoshiro128** per test; `crypto.getRandomValues`/`randomUUID` seeded; `randomBytes/randomFillSync/randomInt` observed (`--det-urandom` controls) | same, installed in the vm context of each file |
| clock | `Date`, `performance.now`, `process.hrtime(.bigint)`, adaptive tick (as Python) | same (+ Jest's per-context `process`) |
| timers | `setTimeout/setInterval/clear*`, `timers`, `timers/promises`: virtual queue, fast while no real I/O is pending, real waits otherwise, per-test budget; `setImmediate` native FIFO, recorded | same; Jest modern fake timers re-created on top |
| fs order | `readdir`, `readdirSync`, `promises.readdir`, `opendir*` sorted | same |
| network | `net.Socket#connect`, `tls.connect`, `dns.*`: closed, record/replay (http, https, fetch/undici) | same |
| isolation | one worker, `fileParallelism: false`, `maxConcurrency: 1`; pool and isolation recorded | `--runInBand`, `--maxConcurrency=1`; recorded |

Runner infrastructure keeps real time: patched calls whose first non-Node,
non-detjs frame is vitest/vite/tinypool/jest-* get the real functions (the
Python rule for pytest plugins).

## Shared event vocabulary (applied after the coordinator's addendum)

* The core is bound, not edited: `event.rs` and the encoding are untouched
  (owned by the L1 study session; `Source::Sched` / encoding 2 arrive with it).
  The only core changes are additive helpers in `order.rs` and `trace.rs`.
* `op` = Node API names, unprefixed: `Date.now`, `Date`, `performance.now`,
  `process.hrtime`, `process.hrtime.bigint`, `setTimeout`/`setInterval`
  (value `schedule:<ns>` or `fire:<ns>`), `setImmediate`, `Math.random`,
  `crypto.randomUUID`, `crypto.getRandomValues`, `crypto.randomBytes`,
  `fs.readdirSync`, `fs.readdir`, `fs.promises.readdir`, `fs.opendirSync`,
  `fs.promises.opendir`, `net.connect`, `tls.connect`, `dns.lookup`,
  `dns.resolve`. HTTP/HTTPS/fetch are intercepted at `net.connect` /
  `tls.connect` (the byte stream is what is recorded and replayed).
* `site` = `path:line` relative to the repository root, POSIX separators,
  from the stack of the test realm's `Error`, which Vitest and Jest source-map:
  original `.ts` line (MEASURED on a Vitest `.ts` file: `tests/a.test.ts:4`,
  the original line, not the transformed one; Jest TypeScript projects rely on
  Jest's own source-map support, not measured here). `<node>` when only Node
  internals are on the stack.
* `thread` = 0 (worker threads created by tests are not controlled, J1).
* Header `meta`: `runtime=node`, `runtime_version`, `runner` (vitest|jest),
  `runner_version`, `seed`, `controls`, plus isolation, pool, epoch, tick.

## Step 3 — tests (DONE, MEASURED in this container)

`node/test/controls.test.js`, `node/test/unchanged.test.js` (`npm test`):

* 8 control tests × 2 runners = **16/16 pass**. Each builds a fixture project
  whose suite **fails without `--det`** in a realistic run and **passes with
  `--det`** (twice, identical fingerprints per the verifier): seeds, clock,
  timers (sleeps longer than the test timeout), fs order, network
  (live service whose answer changes; closed under `--det`; recorded once, then
  replayed with the service stopped, http and https), isolation (two files
  interleaving through a shared file with 2 workers), file order, test order
  (random order configured in the project; seeds reproduce the order
  dependency, each seed twice with identical order and outcomes).
* Deterministic suite (13 tests: Date forms, subclassing, structuredClone,
  timer ordering/clear/refresh/unref/args, microtask ordering,
  `timers/promises` with abort, runner fake timers, crypto ranges and errors,
  Web Crypto digest, directory contents, local HTTP server, local fetch, local
  timeout race): **same outcomes (all pass) without `--det`, with `--det`, with
  `--det-seed=3` and `--det-seed=11`, for both runners**.
* Defects found and fixed by these tests: ESM named imports of builtins kept
  the unpatched functions (`syncBuiltinESMExports`); `net.connect` passes
  pre-normalized arguments (connections were not intercepted); cross-realm
  `instanceof` in Jest's vm context; the call-site filter treated
  `node/node_modules` as detjs itself (runner timeouts became virtual).

## Next (step 4–5)

Harness `harness/node/` (reuses the Python protocol and per-test analysis),
workflow `.github/workflows/node-harness.yml` (one matrix job per project,
each job commits its own results). The validation round is running.

Flaky pool: the public JavaScript flaky-test dataset of Hashemi, Tahir,
Rasheed (ICSME 2022, Zenodo 10.5281/zenodo.6673741) was fetched with an Actions
job (`harness/node/dataset/raw/`). It has 18 projects, most not on
Jest/Vitest (Node core, Atom, Electron, Meteor, jQuery/QUnit, Karma), so it
cannot provide 25 projects: its Jest/Vitest projects come first (pinned at
the parent of a flaky-test fix commit) and the pool is completed with popular
projects that have GitHub issues documenting flaky Jest/Vitest tests (pinned
at the last commit before the issue). A further fetch of the JS-TOD and
environmental-flakiness packages through Actions was refused by the session's
permission system and not attempted again.
