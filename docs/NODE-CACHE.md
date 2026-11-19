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
| files read | `fs` content reads (`readFile*`, `createReadStream`, `openAsBlob`, `open` for reading, **read-write opens included**), `process.loadEnvFile`, listings (`readdir*`: names; with `withFileTypes`: names and entry types; `recursive`: every path below with its type, descending into links to directories exactly where Node does (`readdirSync` and callback `readdir` always, `fs.promises.readdir` without `withFileTypes`; cycles cut by device and inode, and a tree with a cycle is keyed with its absolute path), not descending where Node does not (`fs.promises.readdir` with `withFileTypes`, recursive `opendir`); `opendir*`: typed), existence (`exists*`; `access*` with a mode: permission bits too), `stat*` (the kind, following links; the result is the real `fs.Stats` / BigIntStats object, same prototype, not a Proxy, whose fields record through accessors: `size` and `mode` are keyed together, every other field (times, inode, device, owner, block counts) by its exact value, unless runner or tool code reads it; `Object.getOwnPropertyDescriptor(s)` / `Reflect.getOwnPropertyDescriptor` (patched in every realm tests run in) and `util.inspect` / `console.log` read every field as without the cache; the `is*()` methods do not count as reading `mode`), `lstat*` and `readlink*` (link target, or the path's own kind), `realpath*` (incl. `.native`: the resolved path), `fstat*` and `FileHandle.stat` (as `stat` of the opened path) | `f:`, `missing`, `d:`, `e:`, `t:`, `u:`, `s:<kind>`, `m:` (kind, size, permission bits), `V:<follow>:<field>` (one Stats field by value), `l:`, `L:<kind>`, `r:`; project files by relative path, others absolute; reads outside the project count whoever the caller in test processes |
| copies | `cp*` source (review r021): every path, type, file content and link target below it (`c:`); every path of the copy is an output of the caller; `rename*`: the moved tree is read the same way unless the caller wrote it | `c:` |
| failed resolution | a module that could not be resolved or fetched (a caught `import()` / `require()` of an optional module): Vite's module runner (`cachedModule`), Node's loader (`module.registerHooks` resolve), Jest's resolver (`resolveModule*`). Relative and absolute specifiers: the target's content, its listing and the stem listings of its name (with and without extension). Bare specifiers from installed packages: runtime identity. Bare or mapped (`moduleNameMapper`) specifiers from project code: not cached | `f:`/`missing`, `d:`, `g:` |
| `import.meta.glob` | per loaded project module whose source calls it: the base directory of every pattern (`./`, `../` relative to the module, `/` to the Vite root): typed listing when the pattern matches direct entries, recursive listing when it can match deeper; a pattern that is not a literal, an alias pattern or a `base` option: not cached | `e:`, `t:` |
| mocks | Vitest: every `__mocks__` path `findMockRedirect` can consult (the mocker's own `fs` references are taken before the capture, so the call itself is wrapped): the adjacent `__mocks__/<name>` and the tree of `<root>/__mocks__/<dir>`; Jest: the mocks of Jest's crawl (every `__mocks__` file under the roots, applied to installed packages without `jest.mock`) are part of the configuration of every file | `s:`, `t:`; configuration part `jest-mocks` |
| native readers | `node:sqlite` `DatabaseSync` (wrapped when first loaded): a database opened from a path reads the file and its `-wal`/`-journal`/`-shm` files and, unless read-only, writes it; URIs, `ATTACH`, `VACUUM INTO`, extensions: not cached. `fs.statfs*`, `fs.watch*`, `fs.watchFile`: not cached | `f:` |
| environment | `process.env` is a Proxy over a stand-in target (Jest: also the per-file copy Jest gives each test environment, wrapped before `setupFiles` run): get / `in` / descriptor record the name; enumeration, `util.inspect` / `console.log` (a custom inspection on the stand-in formats the real environment) and structured cloning (`structuredClone`, `v8.serialize`, `postMessage`: retried with the real environment in place of the Proxy, so they succeed or fail as without the cache) record `*` (the whole environment); `util.types.isProxy` answers for the real environment object | value digest against the environment at session start |
| code before the runner | `node/src/cache/early.js`, the first preload of every Vitest worker (`--require` put first in each project's `execArgv`) and, when `NODE_OPTIONS` or the command line has user preloads, of every process (`bin/detjs.js` starts itself again with it first in `NODE_OPTIONS`): the capture starts before user preloads (`--require`, `--import`), Vitest's start-up and the test environment's `setup`; what they read is recorded like any read of the process; the clock or OS entropy read by a preload (before Level 0) makes the process's tests not cached; an off-thread loader (`--loader`, `--experimental-loader`, `module.register`) makes them not cached (its reads are in another thread) | as files read, code, environment |
| machine facts | `os.hostname/userInfo/homedir/tmpdir/networkInterfaces/cpus/availableParallelism/totalmem/release/version/machine/getPriority` (`homedir` also records `HOME`, `tmpdir` `TMPDIR/TMP/TEMP`) | `~os.<name>` digests; `freemem/loadavg/uptime` make the test not cached |
| clock | any Level 0 clock event | the epoch (`--det-epoch`), only for tests that read the clock |
| runtime identity | `node/src/cache/runtime-id.js` | node version + every component version, build flags, `execArgv`, `NODE_OPTIONS`; node binary bytes; every mapped shared library by bytes (+`LD_PRELOAD`, `/etc/ld.so.preload`); glibc; `TZ`, zone file, `/etc/localtime` bytes and link, `/etc/timezone`, Intl zone, tzdata; `LANG/LANGUAGE/LC_*`, Intl locale, `NODE_ICU_DATA`; visible CPUs and instruction-set level (`FENVIX_RUNTIME_ISA=off`); lockfiles; **every installed file** under every `node_modules` of the project and of its ancestors and `NODE_PATH` (Rust tree hasher, memoised by device/inode/size/mtime/ctime in a binary memo, roots walked and files hashed in parallel; links leaving the project followed; started on a background thread when the session starts and used at the reuse decision unless something wrote into those trees or a start-up process ran meanwhile, then recomputed) minus per-machine bookkeeping (`.modules.yaml`, `.pnpm-workspace-state*.json`, `.package-lock.json`, `.yarn-state.yml`, `.yarn-integrity`, `.cache`, `.vite*`, `.vitest*`) |
| configuration | `node/src/cache/proof.js` `setConfig` | detjs version, its source tree and addon; Level 0 options (seed, controls, ticks, timers, network mode, allowed hosts, urandom); the cassette in replay mode; Vitest: each resolved project configuration (minus selection/output keys and detjs' own values), the Vite settings (define, resolve, plugins by name, esbuild/oxc, ssr, env), config file + `configFileDependencies` by bytes; Jest: `--showConfig` (global + every project, minus selection/output keys); command-line options that are not selection or output; every configuration file of the repository by bytes (`tsconfig*`, `jsconfig*`, babel, swc, postcss, browserslist, vite/vitest/jest configs and workspaces, `.env*`, `.nvmrc`, root `package.json`; with Vitest, `vite.config.*`/`vitest.config.*` below the root are left to the project that loads them, and the root configuration file and every file it imports are keyed instead). **Per project**: a file is keyed by the global parts plus its own project's part only, so a change to one package's configuration (or a file it imports, such as its `package.json`) reruns that package's files; a project name shared by two projects (Jest projects without `displayName`) keeps the whole digest |
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
  `getenv`) is not observed; native addons themselves are keyed (runtime identity or `process.dlopen` path). Node's
  own native readers reachable from a test (`openAsBlob`, `loadEnvFile`, `node:sqlite`, `statfs`, `watch`) are
  wrapped (review r021).
* A Vite plugin's transform whose output depends on a directory listing other than `import.meta.glob` (read by the
  plugin in the main process, where runner reads are not inputs) is not keyed.
* `process.binding` / internal `fs` bindings, and references to `fs` functions taken before the capture is installed
  (Jest `setupFiles` run after it; Vitest workers start it as their first preload, early.js), are not seen.
* The installed packages' digest is computed while the runner starts (on a background thread). A write into those
  trees through Node's `fs` by anyone, or any start-up process or worker thread started by user code, makes it be
  computed again at the decision; a write into them by native code of the main process during start-up (not through
  `fs`) would not be seen.
* With user preloads in `NODE_OPTIONS` or on the command line, detjs starts itself again (its own preload first), so
  those preloads run twice in the main process: once before detjs, once recorded.
* Machines that share a cache must use the same work paths (absolute paths of files outside the project).
* Reading `process.memoryUsage()` or `process.pid` is not keyed (not deterministic anyway; Level 0 does not control it).
