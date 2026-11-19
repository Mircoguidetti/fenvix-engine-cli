# `deno test` under detjs (`detjs deno-test`)

```bash
detjs deno-test [deno test args]                                    # deno test, unchanged
detjs deno-test --det [--det-seed=N] [deno test args]               # Level 0 (determinism)
detjs deno-test --det --det-cache=DIR|URL [--det-cache-verify] [deno test args]   # + skip with proof
```

Support: **det + skip**. Deno 2.9.8 measured (`deno test` appears in 0.8% of 1,999 popular JS/TS repositories,
MEASURED, `sessions/2026-11-19-all-runners/INTERMEDIATE-1.md`).

## The shared core in Deno

Deno loads the detpy-node Node-API addon and the detjs CommonJS modules through its Node compatibility layer
(`createRequire`; MEASURED in Deno 2.9.8), so the test process runs the shared Level 0 controls and the shared
capture (node:fs, process.env, os, child_process, net, ...) unchanged, and the main process (Node) runs
`ProofSession`. Files: `src/runners/deno.js` (main side), `deno-preload.mjs` + `deno-setup.js` (test process, loaded
with `deno test --preload`), `deno-runtime.js` (the `Deno` namespace), `bracket.js`, `common.js` (shared with Bun).

## Process model and order

* One `deno test` process per file, in detjs' order (sorted, or the core's shuffle with `--det-seed`); inside a file,
  declaration order or Deno's own `--shuffle=S` with `S = deriveSeed(seed, file)`. Deno already gives each file its
  own isolate (MEASURED: globals do not leak, the preload runs again per file), but one process: the environment
  (`Deno.env.set`), the working directory and written files are shared. The change is counted:
  `isolation: ... (counted)` in runner-deno.test.js (a test that passes under plain `deno test` because an earlier
  file set a variable fails alone). Deno also sorts the files of one process itself, so detjs' order needs one
  process per file anyway.
* Discovery: Deno has no listing command; detjs applies Deno's rules (file arguments as given; directories walked for
  `{*_,*.,}test.{js,mjs,ts,mts,jsx,tsx}`; `deno.json` `test.include/exclude`, top-level `exclude`, `--ignore=`).
  MEASURED identical to `deno test`'s list on oak (21 files).
* Permissions: detjs adds what its own code needs (read of detjs and the run directory, write of the run directory,
  `DETJS_*` and proxy variables, FFI for the addon, a few `sys` facts) to the permissions given; `-A` is left alone.
* Test location: Deno takes a test's location from its caller; the wrapper sets `Symbol.for('Deno.test.location')`
  (Deno's own override) to the test file's call site, so reports and JUnit name the test file.
* Refused with `--det`: `--watch`, `--parallel`, `--shuffle`, `--seed`, `--det-record`.
* JUnit output (`--junit-path=F`) is merged from the per-file reports.

## Hooks used

| need | Deno hook |
|---|---|
| test id, outcome, bracket | `Deno.test` (and `.only`, `.ignore`, `.each`) wrapped in the preload: the body runs between begin and end of `<file>::<name>`; `t.step()` steps belong to their test; @std/testing/bdd works through it (it calls `Deno.test`) |
| file end | the `unload` event (after the last test, hooks and sanitizers) |
| file outcome | the process exit status (sanitizer failures, uncaught errors, type-check errors fail the file: never reused) |

## What is captured (on top of the shared Node capture)

| Deno API / input | key |
|---|---|
| `Deno.readTextFile(Sync)`, `readFile(Sync)`, `open(Sync)` for reading, `fetch(file:)` | content `f:` |
| `Deno.stat/lstat(Sync)`, `FsFile#stat(Sync)` | kind (`s:` following links, `l:` the path's own); fields as for `fs.stat` (`size`, `mode` keyed; times, inode, owner: not cached) |
| `Deno.realPath(Sync)`, `readLink(Sync)` | resolved path `r:`, link target `l:` |
| `Deno.readDir(Sync)` | listing with entry types `e:` (a recursive walk keys every directory it lists) |
| writes (`writeFile`, `writeTextFile`, `mkdir`, `remove`, `rename`, `copyFile`, `symlink`, `link`, `truncate`, `chmod`, `chown`, `utime`, `makeTemp*`, `create`, `open` for writing) | outputs (a read of another file's output: not cached) |
| `Deno.env.get/has`, `Deno.env.toObject` | the variable, or the whole environment |
| `Deno.hostname`, `osRelease`, `networkInterfaces`, `uid`, `gid` | machine facts (`~os.*`) |
| `Deno.osUptime`, `loadavg`, `systemMemoryInfo` | not cached (change between calls) |
| modules (Deno's loader does not go through node:fs) | module graph of the file after its run (`deno info --json` with the run's configuration flags): local modules by content + stem listing, remote and JSR modules by their cached copy, npm packages from Deno's cache by their files (`c:`; a root node_modules is in the runtime identity), modules that do not resolve by what would make them resolve; `import()` of a non-literal specifier, or `require()` in a project module: not cached |
| `deno.json(c)`, `deno.lock`, import maps (`--import-map`, `importMap`), `--env-file`, `--config`, the Deno binary and version, `DENO_*`, `NODE_ENV`, `TZ`, the arguments | configuration digest; plus the shared configuration files and runtime identity |
| `Deno.Command`, `ChildProcess`, `kill` | not cached (process) |
| `Deno.serve/listen/listenTls/startTls/upgradeWebSocket/createHttpClient`, `connect` to loopback, `fetch` to loopback, `WebSocket` | not cached (socket); non-local hosts are closed by Level 0 |
| `Deno.dlopen` and the FFI classes, `watchFs`, `openKv`, `cron`, `consoleSize`, `stdin`, `localStorage`, `sessionStorage`, `caches` | not cached |
| `node:sqlite` | not cached (opened natively) |
| every other function of the `Deno` namespace not on the PURE list | not cached (`runtime-api`) |
| **Deno's permission audit** (`DENO_AUDIT_PERMISSIONS`, one log per file) | every read/write path, variable and system fact Deno checked while the file ran must have been seen by the capture; anything else (and any `run`, `net`, `ffi`, `import` check) makes the file not cached (`unobserved`). This is the completeness backstop: with every Deno wrapper switched off (`DETJS_DENO_WRAPPERS=off`) the audit alone still refuses a `Deno.readTextFile` the capture missed (runner-deno.test.js) |

## Level 0 in Deno

Shared controls (MEASURED working in Deno: `Date`, `performance.now`, timers, `Math.random`,
`crypto.getRandomValues`, `crypto.randomUUID`, node:net), plus a closed network for `fetch`, `Deno.connect`,
`Deno.connectTls`, `Deno.resolveDns`, `WebSocket`, `node:http(s).request/get`.

## Not covered, and why

* Reads Deno does not check against permissions and the wrappers do not see (none found; the audit logs every
  permission-checked access, and module loading is covered by the graph).
* A module loaded at run time by a computed specifier in an installed (remote/npm) module: the graph does not see it;
  remote modules are immutable by URL and npm packages are keyed by their files, but a computed import of a project
  file from a library is not keyed.
* `--det-record` / cassette replay of Deno's native connections.
* Per-test outcome as with Bun: a failure only Deno sees (sanitizers) fails the file through the exit status.
* Cost: one Deno process per file (type check, start-up) and one `deno info` per file: std subset cold run 412 s vs
  23 s for `deno test --parallel` (MEASURED, local, NOISY), warm run 20 s with 160 of 203 files reused.

Evidence: `node/test/runner-deno.test.js` (36 tests); walk specs `harness/node_cache/specs/{oak,std}.json`.
