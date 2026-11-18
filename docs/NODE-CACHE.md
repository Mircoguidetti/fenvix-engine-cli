# detjs cache with proof (`--det-cache`)

`detjs vitest|jest --det --det-cache=DIR|URL` skips a test file when every input its tests depended on is unchanged,
and gives a receipt for every reused result. It is the Node counterpart of `pytest --det --det-cache`
(`python/detpy/proofcache.py`, docs/SHARED-CACHE.md) and reuses its Rust core unchanged in format:
`crates/detpy-core/src/proof.rs` (store, entry keys, reuse check, receipts) through the napi bindings
(`crates/detpy-node`, class `ProofCache`). The shared cache service is the Python one (`python/detpy/cache_service.py`);
the Node client speaks its protocol (`node/src/cache/remote.js`).

```bash
detjs vitest run --det --det-cache=.detjs-cache            # local store
detjs jest --det --det-cache=https://cache.example/acme/repo   # shared cache (token: FENVIX_CACHE_TOKEN[_FD|_FILE])
detjs vitest run --det --det-cache=DIR --det-cache-verify  # decide, but run everything and compare
```

Output: one summary line per session, `.detjs/receipts.jsonl` (same rows as Python: `nodeid`, `reused`, `key`,
`run`, `outcome`, `fingerprint`, `duration`, `config`, `runtime`, `epoch`, `n_*`; or `reused: false` with `why`),
`.detjs/cache-summary.json` and `.detjs/cache-identity.json` (every part of the runtime and configuration digests).

## Unit of reuse: the test file

Every test gets its own entry (per-test receipts), but a file is reused only when **all** of its tests and its
file entry (*manifest*: the list of its tests and the inputs of its collection, `nodeid` = file path, with
`@@<project>` for Vitest projects / Jest display names) prove reuse; otherwise the whole file runs. Tests of one file
share module state (Vitest: one worker per file; Jest: one module registry per file), so skipping some tests of a
file would change the state the others run in. The inputs of a test are **cumulative**: everything logged in its
process up to the end of the test (collection, `beforeAll`, earlier tests). Where state is shared *between* files
(Vitest `isolate: false`, `vmThreads`/`vmForks`, browser mode, a custom Jest `runner`), the project is not cached.

## What is an input (recorded while the tests run: `node/src/cache/capture.js`)

| input | how | key |
|---|---|---|
| code | modules loaded in the test's process: Vitest's module runner graph (`__vitest_worker__.evaluatedModules` / `moduleCache`), Node's own loader (`module.registerHooks`, `require.cache`), native addons (`process.dlopen`), Jest's runtime registries (`_cacheFS`, `_moduleRegistry`, `_esmoduleRegistry`) | project files by relative path and content digest; files outside the project by absolute path and digest; installed packages through the runtime identity |
| resolution | per loaded project module: its nearest `package.json`, and the directory entries sharing its name stem (`m`, `m.*`; for `x/index.*` also `x`, `x.*` in the parent): a new `m.mjs` that would shadow `m.ts` reruns the importers (Vite 8 resolves in native code, so missing-path probes are not visible) | `f:` digest; new `g:` dependency kind (stem listing) |
| files read | `fs` content reads (`readFile*`, `createReadStream`, `open` for reading, **read-write opens included**), listings (`readdir*`, `opendir*`), existence (`exists*`, `access*`, `stat*`, `lstat*`, `realpath*`), link targets (`readlink*`, new `l:` kind) | `f:`, `missing`, `d:`, `s:<kind>`, `l:`; project files by relative path, others absolute |
| files written | `write*`, `append*`, `rm*`, `rename*`, `mkdir*`, `mkdtemp*` (incl. disposable), `copyFile`, `cp`, `symlink`, `link`, `truncate`, write opens | a read of a path another test file or the start-up code wrote (this session or an earlier one: `Store.written`) makes the reader **not cached**; a file's own outputs are not inputs |
| environment | `process.env` is a Proxy (Jest: also the per-file copy Jest gives each test environment, wrapped before `setupFiles` run): get / `in` / descriptor record the name; enumeration records `*` (the whole environment) | value digest against the environment at session start |
| machine facts | `os.hostname/userInfo/homedir/tmpdir/networkInterfaces/cpus/availableParallelism/totalmem/release/version/machine/getPriority` (`homedir` also records `HOME`, `tmpdir` `TMPDIR/TMP/TEMP`) | `~os.<name>` digests; `freemem/loadavg/uptime` make the test not cached |
| clock | any Level 0 clock event | the epoch (`--det-epoch`), only for tests that read the clock |
| runtime identity | `node/src/cache/runtime-id.js` | node version + every component version, build flags, `execArgv`, `NODE_OPTIONS`; node binary bytes; every mapped shared library by bytes (+`LD_PRELOAD`, `/etc/ld.so.preload`); glibc; `TZ`, zone file, `/etc/localtime` bytes and link, `/etc/timezone`, Intl zone, tzdata; `LANG/LANGUAGE/LC_*`, Intl locale, `NODE_ICU_DATA`; visible CPUs and instruction-set level (`FENVIX_RUNTIME_ISA=off`); lockfiles; **every installed file** under every `node_modules` of the project and of its ancestors and `NODE_PATH` (Rust tree hasher, memoised by device/inode/size/mtime/ctime, multithreaded; links leaving the project followed) minus per-machine bookkeeping (`.modules.yaml`, `.pnpm-workspace-state*.json`, `.package-lock.json`, `.yarn-state.yml`, `.yarn-integrity`, `.cache`, `.vite*`, `.vitest*`) |
| configuration | `node/src/cache/proof.js` `setConfig` | detjs version, its source tree and addon; Level 0 options (seed, controls, ticks, timers, network mode, allowed hosts, urandom); the cassette in replay mode; Vitest: each resolved project configuration (minus selection/output keys and detjs' own values), the Vite settings (define, resolve, plugins by name, esbuild/oxc, ssr, env), config file + `configFileDependencies` by bytes; Jest: `--showConfig` (global + every project, minus selection/output keys); command-line options that are not selection or output; every configuration file of the repository by bytes (`tsconfig*`, `jsconfig*`, babel, swc, postcss, browserslist, vite/vitest/jest configs and workspaces, `.env*`, `.nvmrc`, root `package.json`) |
| start-up | main process before the tests (Vitest: until its sequencer runs, which is after `globalSetup`; Jest: everything outside test files) | content of every project file read by anyone at start-up (configuration modules, globalSetup and what it imports) and every missing path probed; user code's reads, environment reads, writes at any time; `execSync/spawnSync/execFileSync` by user code at start-up: argv, cwd, exit code and output digests make the **start-up digest** (as Python R-008d); any other process, worker thread or socket started by user code in the main process taints every test |

Never reused: a failure (failed test, file-level error, failing hook); a test that started a process (git included)
or a worker thread, opened a socket (loopback and Unix sockets included; external hosts are Level 0's: blocked, or
replayed from the cassette, which is then configuration), sent UDP, drew OS entropy without `--det-urandom`, read
`/proc`, `/sys` or `/dev` (except `/proc/self/exe`, in the runtime identity, and `/proc/version`, keyed as a file),
recorded the network, or read a file another test file or the start-up code wrote.

Not inputs (by design): files under `node_modules` (runtime identity), detjs itself (configuration), runner and tool
caches whose content is a function of their key (Jest `cacheDirectory`, Vite `cacheDir`, `$TMPDIR/jiti`; more with
`DETJS_CACHE_SKIP_DIRS`), and, in the main process, what the runner itself reads during the run (Vite's transforms of
the test modules are covered by the module graph).

## Where the decision happens

* **Vitest**: in detjs' sequencer (`sort`), which Vitest calls after `globalSetup`; files proven reusable are removed
  from the run. If every file is reused, the run passes (`passWithNoTests` set for that session only).
* **Jest**: in detjs' sequencer, which Jest calls *before* `globalSetup` (a globalSetup that runs processes changes
  the start-up digest after the decision: such suites rerun every file); `--passWithNoTests` is added and a run that
  found no tests at all still exits 1.
* Reused files do not appear in the runner's reporters; they are in the detjs summary line, the receipts and
  `cache-summary.json` (`reused_files_list`).

## Shared cache

`--det-cache=https://host/<namespace>` works on a local mirror (`FENVIX_CACHE_LOCAL` or
`~/.cache/fenvix/remote/<digest>`); pull at the decision (file manifests first, then the tests they list; candidates
are checked like local entries; a candidate must list its own test file among its inputs), push at the end (file,
set and entry documents, key log, receipts linked to the run). Documents are canonical JSON byte-identical to
Python's, so the service's address check accepts them. The token is read in the main process and removed from the
environment before any worker starts. Plain `http://` is refused to non-loopback hosts unless
`FENVIX_CACHE_ALLOW_HTTP=1`. Trust model and limits: docs/SHARED-CACHE.md (write tokens only for trusted refs).

## Limits

* The decision uses the inputs recorded for the previous run of each file. A test that reads an input only in a
  branch it did not take last time is covered: the branch condition's inputs changed first.
* Native code that reads files or the environment without going through Node (`fs` bindings called directly, C
  `getenv`) is not observed; native addons themselves are keyed (runtime identity or `process.dlopen` path).
* `process.binding` / internal `fs` bindings, and references to `fs` functions taken before the capture is installed
  (Jest `setupFiles` run after it; Vitest installs in the runner constructor, before any test module), are not seen.
* Machines that share a cache must use the same work paths (absolute paths of files outside the project).
* Reading `process.memoryUsage()` or `process.pid` is not keyed (not deterministic anyway; Level 0 does not control it).
