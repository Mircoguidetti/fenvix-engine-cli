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

## Unit of reuse: the test file, the process, or the test (`--det-isolate`)

Every test gets its own entry (per-test receipts), but a file is reused only when **all** of its tests and its
file entry (*manifest*: the list of its tests and the inputs of its collection, `nodeid` = file path, with
`@@<project>` for Vitest projects / Jest display names) prove reuse; otherwise the whole file runs. Tests of one file
share module state (Vitest: one worker per file; Jest: one module registry per file), so skipping some tests of a
file would change the state the others run in. The inputs of a test are **cumulative**: everything logged in its
process up to the end of the test (collection, `beforeAll`, earlier tests). Where state is shared *between* files
in one process (Vitest `isolate: false`, a custom Jest `runner` such as jest-light-runner in band), the files form one
group (`src/cache/groups.js`, P-041 G-1475, G-0402): the ordered list of the group's files is part of their projects'
configuration digest (another selection or order reuses nothing), and the group is reused all together or run all
together (a file that could be reused runs when another file of the group must run; receipt reason `group: ...`).
The Vitest vm pools and browser mode stay not cached.

Why the file and not the test (audit G-1397): without isolation the tests of a file share module state that no
capture observes (a module variable, a library's registry). Skipping a reused test would change what the next one
runs with: `node/test/cache-p041.test.js` "G-1397" has a file whose second test passes after the first and fails
alone (`-t`), so a per-test unit there would report a false failure (or, the other way round, a false pass). A
change of an input only one test reads therefore reruns its whole file, whose verdict is then a fresh run's.

**Shared-process runners** (Mocha, Jasmine, uvu, Bun, Deno; audit G-0145..G-0149). These runners run every test
file in one process (Bun: one global object; Deno: one OS process, an isolate per file, with the environment, the
working directory and the files shared; Mocha, Jasmine, uvu: one Node process). detjs keeps that model under `--det`
and `--det-cache`, so the verdict is the plain runner's: a suite whose files share state passes as it does plain.
With the cache the **process is the unit** (`<mocha>`, `<jasmine>`, `<uvu>`, `<bun>`, `<deno>`; entries under the
project `process`: `<file>@@process::<test>`): one capture for the whole process (Deno: the isolates' captures
merged in run order), whose inputs are every file's, so every file is reused or every file runs, and a file that
read what an earlier file left is never reused with that earlier file changed (the carried-set rule at its widest).
The configuration of the unit includes the plan (the list of files in run order). `--det-isolate` gives each file a
fresh process of its own (the per-file model of earlier versions): the file is then the unit, and a test that needs
another file's state fails there, which is the isolation the user asked for.

**`--det-isolate` for Vitest and Jest** (audit G-1394; `src/isolate.js`): every test runs in a runner session of its
own (a fresh worker process after its file's collection, a name filter that matches only that test; Vitest's tests
are listed with `vitest list`, Jest's from a collection session whose name filter matches nothing). With the cache,
each per-test session keeps its entries under a scope of its own (`DETJS_CACHE_SCOPE`: `<file>@@~iso.<digest>`):
its key is the file's collection and the test itself, nothing of another test, so **a test is reused or run on its
own inputs** (G-1397). Tests whose full names are equal run together. The trace lists every test
(`meta.isolate_tests`), the summary `reused_tests_list` / `ran_tests_list`. Cost: one runner start-up per test.

## What is an input (recorded while the tests run: `node/src/cache/capture.js`)

| input | how | key |
|---|---|---|
| code | modules loaded in the test's process: Vitest's module runner graph (`__vitest_worker__.evaluatedModules` / `moduleCache`), Node's own loader (`module.registerHooks`, `require.cache`), native addons (`process.dlopen`), Jest's runtime registries (`_cacheFS`, `_moduleRegistry`, `_esmoduleRegistry`) | project files by relative path and content digest; files outside the project by absolute path and digest; installed packages through the runtime identity |
| resolution | per loaded project module: its nearest `package.json`, and the directory entries sharing its name stem (`m`, `m.*`; for `x/index.*` also `x`, `x.*` in the parent): a new `m.mjs` that would shadow `m.ts` reruns the importers (Vite 8 resolves in native code, so missing-path probes are not visible) | `f:` digest; new `g:` dependency kind (stem listing) |
| files read | `fs` content reads (`readFile*`, `createReadStream`, `openAsBlob`, `open` for reading, **read-write opens included**), `process.loadEnvFile`, listings (`readdir*`: names; with `withFileTypes`: names and entry types; `recursive`: every path below with its type; `opendir*`: typed), existence (`exists*`; `access*` with a mode: permission bits too), `stat*` (the kind, following links; reading `size` or `mode` from the result keys them; reading times, inode, device, owner or block counts makes the test not cached unless runner or tool code reads them), `lstat*` and `readlink*` (link target, or the path's own kind), `realpath*` (incl. `.native`: the resolved path), `fstat*` and `FileHandle.stat` (as `stat` of the opened path) | `f:`, `missing`, `d:`, `e:`, `t:`, `s:<kind>`, `m:` (kind, size, permission bits), `l:`, `L:<kind>`, `r:`; project files by relative path, others absolute; reads outside the project count whoever the caller in test processes |
| copies | `cp*` source (review r021): every path, type, file content and link target below it (`c:`); every path of the copy is an output of the caller; `rename*`: the moved tree is read the same way unless the caller wrote it | `c:` |
| failed resolution | a module that could not be resolved or fetched (a caught `import()` / `require()` of an optional module): Vite's module runner (`cachedModule`), Node's loader (`module.registerHooks` resolve), Jest's resolver (`resolveModule*`). Relative and absolute specifiers: the target's content, its listing and the stem listings of its name (with and without extension). Bare specifiers from installed packages: runtime identity. Bare or mapped (`moduleNameMapper`) specifiers from project code: not cached | `f:`/`missing`, `d:`, `g:` |
| `import.meta.glob` | per loaded project module whose source calls it: the base directory of every pattern (`./`, `../` relative to the module, `/` to the Vite root): typed listing when the pattern matches direct entries, recursive listing when it can match deeper; a pattern that is not a literal, an alias pattern or a `base` option: not cached | `e:`, `t:` |
| mocks | Vitest: every `__mocks__` path `findMockRedirect` can consult (the mocker's own `fs` references are taken before the capture, so the call itself is wrapped): the adjacent `__mocks__/<name>` and the tree of `<root>/__mocks__/<dir>`; Jest: the mocks of Jest's crawl (every `__mocks__` file under the roots, applied to installed packages without `jest.mock`) are part of the configuration of every file | `s:`, `t:`; configuration part `jest-mocks` |
| native readers | `node:sqlite` `DatabaseSync` (wrapped when first loaded): a database opened from a path reads the file and its `-wal`/`-journal`/`-shm` files and, unless read-only, writes it; URIs, `ATTACH`, `VACUUM INTO`, extensions: not cached. SQLite's 'now' (node:sqlite, better-sqlite3) is a virtual clock read (`clock`: the epoch is an input) and `random()` / `randomblob()` are seeded (Level 0 control 2a); better-sqlite3 is a native addon, so its tests stay never reused. `fs.statfs*`, `fs.watch*`, `fs.watchFile`: not cached | `f:` |
| environment | `process.env` is a Proxy (Jest: also the per-file copy Jest gives each test environment, wrapped before `setupFiles` run): get / `in` / descriptor record the name; enumeration records `*` (the whole environment) | value digest against the environment at session start |
| machine facts | `os.hostname/userInfo/homedir/tmpdir/networkInterfaces/cpus/availableParallelism/totalmem/release/version/machine/getPriority` (`homedir` also records `HOME`, `tmpdir` `TMPDIR/TMP/TEMP`) | `~os.<name>` digests; `freemem/loadavg/uptime` make the test not cached |
| clock | any Level 0 clock event, including the start of a runner's fake clock (`useFakeTimers` without `now`) | the epoch, only for tests that read the clock. With `--det-cache` and no `--det-epoch`, the epoch is **today 00:00 UTC** (the virtual day, DECISIONS 2026-11-19): a test that reads the clock is reused only on the UTC day it was recorded (audit G-0120, G-0122) |
| runtime identity | `node/src/cache/runtime-id.js` | node version + every component version, build flags, `execArgv`, `NODE_OPTIONS`; node binary bytes; every mapped shared library by bytes (+`LD_PRELOAD`, `/etc/ld.so.preload`); glibc; `TZ`, zone file, `/etc/localtime` bytes and link, `/etc/timezone`, Intl zone, tzdata; `LANG/LANGUAGE/LC_*`, Intl locale, `NODE_ICU_DATA`; visible CPUs and instruction-set level (`FENVIX_RUNTIME_ISA=off`); lockfiles; **every installed file** under every `node_modules` of the project and of its ancestors and `NODE_PATH` (Rust tree hasher, memoised by device/inode/size/mtime/ctime, multithreaded; links leaving the project followed) minus per-machine bookkeeping (`.modules.yaml`, `.pnpm-workspace-state*.json`, `.package-lock.json`, `.yarn-state.yml`, `.yarn-integrity`, `.cache`, `.vite*`, `.vitest*`) |
| configuration | `node/src/cache/proof.js` `setConfig` | detjs version, its source tree and addon; Level 0 options (seed, controls, ticks, timers, network mode, allowed hosts, urandom); the cassette in replay mode (its bytes and, with `--det-cassette-max-age`, the limit and which recorded tests are stale today: a recording that becomes stale changes the configuration, G-1418); Vitest: each resolved project configuration (minus selection/output keys and detjs' own values), the Vite settings (define, resolve, plugins by name, esbuild/oxc, ssr, env), config file + `configFileDependencies` by bytes; Jest: `--showConfig` (global + every project, minus selection/output keys); command-line options that are not selection or output; every configuration file of the repository the runner can load, by bytes (another runner's own configuration is left out: Vitest does not key `jest.config.*`/`jest.preset.*`, Jest does not key `vite.config.*`/`vitest.config.*`/`vitest.workspace|projects.*`, the other shells neither: audit G-1399; `tsconfig*`, `jsconfig*`, babel, swc, postcss, browserslist, vite/vitest/jest configs and workspaces, `.env*`, `.nvmrc`, root `package.json`; with Vitest, `vite.config.*`/`vitest.config.*` below the root are left to the project that loads them, and the root configuration file and every file it imports are keyed instead). **Per project**: a file is keyed by the global parts plus its own project's part only, so a change to one package's configuration (or a file it imports, such as its `package.json`) reruns that package's files; a project name shared by two projects (Jest projects without `displayName`) keeps the whole digest |
| start-up outputs | Vitest decides after `globalSetup`: a file the start-up wrote before the decision is on disk as this session's start-up left it, so a test that read it is keyed by its content (`f:`), not refused (audit G-1401). A write of the main process after the decision (teardown, during the tests; marked `run` by the capture) or by another test file stays a writer (refused). Jest decides before `globalSetup`: there a file the start-up wrote is never reused (kept; `cache-p041` "G-1401 (kept for Jest)") | `f:` |
| start-up | main process before the tests (Vitest: until its sequencer runs, which is after `globalSetup`; Jest: everything outside test files) | content of every project file read by anyone at start-up (configuration modules, globalSetup and what it imports) and every missing path probed; user code's reads, environment reads, writes at any time; `execSync/spawnSync/execFileSync` by user code at start-up: argv, cwd, exit code and output digests make the **start-up digest** (as Python R-008d); any other process, worker thread or socket started by user code in the main process taints every test |

A session with a Level 0 control switched off (`--det-disable=time`, `seeds`, `net` or `fs`) neither reuses nor
records: the real clock, real randomness, the open network or the file system's own order would be inputs no key
holds (audit G-0123). A flag the Rust policy does not know refuses reuse instead of being ignored.

Nightly real-clock check (DECISIONS 2026-11-19, audit G-0121): `--det-cache-real-clock` decides reuse as the virtual
day would, runs every file on the real clock, records nothing, and reports each test whose result differs from its
cached one as `EXPIRY` (a certificate, token or fixture valid until a date); the entries of the test and of its file
are removed, so the next run executes it again.

Never reused: a failure (failed test, file-level error, failing hook); a test whose process loaded a native addon
for the code under test (row JS-09; the runners' and tools' own bindings — resolvers, bundlers, transformers,
watchers — excepted; every load request of a `.node` file counts, also a cached one); a test that started a process (git included)
or a worker thread, opened a socket (loopback and Unix sockets included; external hosts are Level 0's: blocked, or
replayed from the cassette, which is then configuration; the bytes of every connection are also in the fingerprint), sent UDP, drew OS entropy without `--det-urandom` (WebSocket handshake keys and masks are seeded nonces, not entropy), read
`/proc`, `/sys` or `/dev` (except `/proc/self/exe`, in the runtime identity, and `/proc/version`, keyed as a file),
recorded the network, or read a file another test file or the start-up code wrote.

Not inputs (by design): files under `node_modules` (runtime identity), detjs itself (configuration), runner and tool
caches whose content is a function of their key (Jest `cacheDirectory`, Vite `cacheDir`, `$TMPDIR/jiti`; more with
`DETJS_CACHE_SKIP_DIRS`), and, in the main process, what the runner itself reads during the run (Vite's transforms of
the test modules are covered by the module graph).

## Receipts, refusals, trace

* A reused row says why (`why`: "reused: every input unchanged since run R; same configuration and runtime digests;
  N code file(s) by content; M file/listing/metadata key(s); K environment variable(s); reads the clock: same
  virtual day D | does not read the clock; ...", audit G-2161). A miss on the configuration names what changed
  (`config: changed jest.config.js`, `config: changed resolved configuration of project web`): the parts of every
  configuration digest are kept in `<cache>/config-parts/<digest>.json`.
* A file that was to run but whose capture never reached detjs (a write that failed, a process that died before it)
  is a refusal like any other: `not cached: capture not written N` in the summary line and `not_cached_detail`
  (audit G-2225).
* The trace of a `--det-cache` run lists the reused tests too, with the outcome and fingerprint recorded with the
  reused result (`events: []`, header `meta.reused_tests`), at their file's place in the plan (audit G-1402):
  `detjs verify` of a cached run against a full run compares them.

## Refusals kept (each with the test that shows it never gives a wrong result)

| flag | why it cannot be keyed | proof |
|---|---|---|
| `clock-real` (process.uptime/cpuUsage/resourceUsage, performance.timeOrigin, Intl format of now, Temporal.Now) | the real clock, not controlled | cache-p041 "G-1582" |
| `dynamic-import` (Bun, Deno: `import(x)` with a non-literal specifier in project code) | the target is not known before the run | cache-p041 "G-1583" (Bun) |
| `keygen` (key generation, randomized encryption or signatures) | OS randomness drawn in native code, not controlled by `--det-urandom` | cache-p041 "G-1584" |
| `loader` (`--loader`, `module.register`) | the loader thread's reads are not observed | cache-p041 "G-1585"; r021b-fixes "G4" |
| `preload` (a preload read the clock or OS entropy before Level 0) | the value is not controlled | cache-p041 "G-1586" |
| `proc` (`/proc`, `/sys`, `/dev`) | process and kernel state, not files (reading some at the decision would block or never end) | cache-p041 "G-2220" |
| `env-unobserved` (tap's per-process variables read by the test's own code) | set per test process, different every run | cache-p041 "G-2221" (tap) |
| `net-record` (`--det-record`) | the live network is the input | cache-p041 "G-2222" |
| `udp` | real datagrams, not recorded | cache-p041 "G-2223" |
| `unobserved` (Deno's permission audit saw an access the capture did not) | not observed | runner-deno "the audit cross-check alone catches reads the wrappers miss" |

## Where the decision happens

* **Vitest**: in detjs' sequencer (`sort`), which Vitest calls after `globalSetup`; files proven reusable are removed
  from the run. If every file is reused, the run passes (`passWithNoTests` set for that session only).
* **Jest**: when Jest schedules the files, after `globalSetup` (P-041 G-1290): detjs patches the `scheduleTests` of the
  TestScheduler that jest-cli's @jest/core uses; it awaits the decision and schedules the files that are not reused
  (Jest's own list keeps every file: globalTeardown, results cache). A globalSetup's synchronous processes and reads are
  then part of the start-up digest of both the recording run and the deciding run. With parallel lanes
  (`--det-workers`) the plan is made from the decided files, so the decision stays in the sequencer, before
  `globalSetup`. `--passWithNoTests` is added and a run that found no tests at all still exits 1.
* Reused files do not appear in the runner's reporters; they are in the detjs summary line, the receipts and
  `cache-summary.json` (`reused_files_list`).

## Parallel runs (`--det-workers`, docs/NODE.md "Parallel")

* The reuse decision is made once, in the main process, before the plan: only the files that run are placed in
  lanes; reused files cost no worker time.
* Inputs per file stay per file when files run at the same time: Vitest records them in each file's fresh worker,
  as serially; Jest workers start the capture in each worker process (`src/jest/worker.js`, the in-band main
  process's capture role and environment wrapping), and what a worker logs outside any file (a custom environment
  module's own reads) is a global input of every file of the session, as the main process's own items are in band.
* The writers rule ("never reuse a test that read a file another test file wrote") is applied by the session
  policy over every file's capture, whichever process ran it, so it does not depend on timing. On top of it, a file
  that touched a path or a fixed port that a file of another lane touched is not cached (`cross-worker`), a file
  that ran after a file that left process-wide state changed in its process is not cached (`carried`), and a test
  that reads its worker or pool id in a parallel run is not cached (`placement`: the value is the lane). Serially
  the runners give every test `JEST_WORKER_ID=1` / `VITEST_POOL_ID=1`, and the environment the cache keys against
  holds these values (before, such a read was keyed as an unset variable); `VITEST_WORKER_ID` (the number of files
  before the test's file) is never cached.
* Keys are the serial keys: worker counts (`maxWorkers`, `minWorkers`, `fileParallelism`, pool thread/fork counts,
  wherever the resolved configuration repeats them, and the runners' worker options on the command line) are not
  part of the configuration digest, so an entry recorded in parallel is reused serially and the reverse (MEASURED in
  `node/test/parallel-p041.test.js` on Vitest 3, 4, 5 and Jest 29, 30).
* Receipts and the summary are written once, by the main process, for every decided file.

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
  (Jest `setupFiles` run after it; Vitest installs in the runner constructor, before any test module), are not seen.
* Machines that share a cache must use the same work paths (absolute paths of files outside the project).
* Reading `process.memoryUsage()` or `process.pid` is not keyed (not deterministic anyway; Level 0 does not control it).
