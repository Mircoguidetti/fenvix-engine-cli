# Native addons and pending work (P3, founder decision D2 = A, 2026-11-27)

The virtual timer driver runs fast only while nothing real is pending (`node/src/sched.js` `isPending()`): active
resources (`process.getActiveResourcesInfo()`), plus thread-pool calls it wraps itself (crypto, zlib, and since
d9d46c42 the addons in `NATIVE_WORK`). A native addon that runs work on the libuv thread pool (an N-API AsyncWorker
or a napi-rs task) leaves no active resource. While such a call is in flight the driver sees nothing pending and can
jump virtual time to the next timer (on alakajam, tarn's 60 s acquire timeout past the 5 s runner deadline).

Method: list every `*.node` file under each measured repository's `node_modules`. For each addon that can do async
work, count the repository source files that import it (outside `node_modules` and `dist`), then probe one async
call: does `process.getActiveResourcesInfo()` list anything while the call is in flight? Probes ran on this machine
on 2026-11-27, in the repositories' own installs under `$PM_WORK`.

Repositories: agentic-qe, agentlang, agentsys, alakajam, claudekit, codex-multi-auth, ironcurtain, nestjs-pino,
sqlectron, drydock. 69 (repository, addon package) pairs.

| addon | repositories (source files importing it) | async work in flight visible? | status |
|---|---|---|---|
| `sqlite3` (node-sqlite3 5.1.7) | alakajam (0 direct; through knex and TypeORM) | no (`[]` during a 2M-row query) | **counted** since d9d46c42 (`NATIVE_WORK`) |
| `better-sqlite3` | agentic-qe (211), ironcurtain (14) | synchronous API, nothing in flight | not affected |
| `hnswlib-node` | agentic-qe (5) | no (`[]` during `writeIndex`) | **same blind spot**, not counted (no flip traced to it) |
| `sharp` (`@img/sharp-*`) | alakajam (2), agentic-qe (0), ironcurtain (0) | no (`[]` during `toBuffer` of a 4000x4000 PNG) | **same blind spot**, not counted (no flip traced to it) |
| `@huggingface/transformers` (onnxruntime-node) | agentic-qe (3) | not probed (needs a model) | likely the same (onnxruntime runs inference on its own threads) |
| `isolated-vm` | ironcurtain (3) | cannot load in the measured install (`npm ci --ignore-scripts`: no native build for Node 22) | not reachable in the measured runs |
| `node-pty` | ironcurtain (5) | cannot load in the measured install (same) | not reachable; if built, its pty is a `TTYWrap`, which `sched.js` ignores, and its child is not started through `child_process` (not seen by P2) |
| `argon2`, `@napi-rs/keyring`, `ruvector` / `@ruvector/*`, `agentdb`, `@claude-flow/*`, `onnxruntime-node` (ironcurtain) | agentic-qe / ironcurtain (0 each) | not probed | not imported by the repositories' own code |
| `@parcel/watcher`, `@node-rs/xxhash` | agentsys, alakajam (0) | not probed | not imported by the repositories' own code |
| build tooling: `@swc/core`, `@rolldown/binding`, `@rollup/rollup`, `lightningcss`, `@oxc-resolver`, `@oxc-parser`, `@unrs/resolver`, `@tailwindcss/oxide` | several | not probed | used by the runner's transform (Vite / Vitest in the main process), outside a test's timers |

What a fix for another addon would take: an entry in `NATIVE_WORK` (a match on the addon's exports and the callback
methods to count), and for promise-returning napi-rs methods a variant that ends the pending work when the promise
settles (`trackWork` handles callbacks only). Not done: no flip in the P3 / P3b sets was traced to hnswlib-node,
sharp or onnxruntime; each needs a failing-first case of its own.
