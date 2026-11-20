# ND2 notes: Node / TypeScript back-end, part 2 (controls, features, cache, Bun/Deno, matrix)

Cut short by a 20-minute budget from the coordinator. Everything below was run on Node v22.23.5, Vitest 3.2.7,
Jest 30.5.2, installed detjs 0.1.0 (`FENVIX_HOME=/home/user/audit/build/opt fenvix node ...`). Scratch projects:
`/home/user/audit/work/ND2/p1` (controls), `p2` (record/replay), `p3` (shuffle, verify), `p4` (cache probes),
`other/deep/p4b` (same project, other path). Gap ids: ND2-001..101 in `ND2.gaps.jsonl`.

## (a) Not covered (items of my brief I did NOT get to; another session must finish them)

Controls:
- Mocha and node:test spot-checks of every control (only Vitest and Jest were run).
- `mock.timers` of node:test on top of `--det`; Jest legacy fake timers (J3, DOC only).
- `Temporal` (needs Node 24), `ShadowRealm` (needs a flag): READ only (ND2-013, ND2-069).
- `--hash-seed` / V8 hash seed: only the observable orders were checked (spec-ordered, stable); no run with different `--hash-seed` values.
- `http2` beyond a blocked connect; `EventSource` global (undefined on Node 22 without flag); `sharp`; real gRPC call (only a blocked `waitForReady`).
- Record/replay over TLS (only plain HTTP to a non-loopback local address was recorded: the sandbox has no direct external network); cassette compatibility with the Python shell (same `detpy-cassette` v1 header seen, not cross-replayed).
- `import.meta.glob`, assets (`?raw`), `.env` files, tsconfig/babel changes, inline snapshots and `-u`, test-filter flags (`-t`) as cache inputs: not probed.
- Per-control disable: `--det-disable=order,seeds,time,timers,fs,net,isolation` exists (node/src/config.js:6); only `net` and `time` were exercised. There is no per-API switch.
- `cluster`: READ only (ND2-064).
Features:
- Jest `--det-cache`: no hands-on run at all (all cache probes are Vitest). `--det-cache-verify`: not run.
- Shared cache over the service URL (`--det-cache=https://...`, `python/detpy/cache_service.py`): not started; only a local store used from two directories (ND2-101).
- Date-dependent test across the UTC day with a real day change: not possible in the time; proven from the constant epoch (ND2-081) and from ND2-099/100.
- Overhead measurement on a real project (simple-statistics, 3 runs plain / `--det` / cache cold / warm): NOT done. No number from me.
- Cross-language `fenvix verify`: run once on two Node traces (same output and exit code 1 as `detjs verify`); Python-vs-Node trace comparison not tried.
- Parallel under `--det`: only the serial headers were observed (ND2-078, 079); details are ND1's.
Bun and Deno (brief item 3): NOT covered at all. No `detjs bun-test` run, no Deno install attempt. Only READ of the
file list (`node/src/runners/bun.js`, `bun-runtime.js`, `bun-preload.js`, `deno.js`, `deno-runtime.js`, `deno-setup.js`, `deno-preload.mjs`).
Matrix: rows Mocha, node:test, AVA, tap, uvu, Jasmine, Bun test, Deno test are `not checked` (ND1 had only packaging
entries ND1-001..021 when I wrote it; `ND1.notes.md` did not exist).
Source reading: of the 51 files in node/src I read fully: bin/detjs.js, session.js, controls.js, config.js, state.js,
clock.js, seeds.js, fsorder.js, patch.js, fileproc.js, native.js, register.js, replay-cert.js, network.js, sites.js,
vitest/cli.js, vitest/shell.js, vitest/runner.mjs, jest/cli.js; partly cache/proof.js (1-200) and cache/capture.js
(1735-1800). NOT read: jest/runner.js, jest/sequencer.js, mocha/*, nodetest/*, runners/*, cache/remote.js,
cache/runtime-id.js, cache/early.js, cache/loader-hooks.mjs, crates/detpy-node.

## User surface (from node/bin/detjs.js and node/src/session.js)

Subcommands: `detjs vitest|jest|node-test|mocha|bun-test|deno-test|tap|ava|jasmine|uvu [--det options] [runner args]`,
`detjs verify TRACE [TRACE ...] [--json] [--show-stable]`, `detjs --det-help`. Nothing else (no repro, explore,
replay, culprit, dep verdict, version, help).
Options: `--det`, `--det-seed=N`, `--det-trace=PATH`, `--det-compare=TRACE`, `--det-record`, `--det-cassette=PATH`,
`--det-allow-host=HOST`, `--det-epoch=ISO`, `--det-tick=NS`, `--det-tick-adapt=N`, `--det-timers=real`,
`--det-timer-budget=N`, `--det-disable=LIST`, `--det-urandom`, `--det-max-events=N`, `--det-sites=off`,
`--det-cache=DIR|URL`, `--det-cache-verify`, `--det-cache-receipts=P`, `--det-cache-summary=P`. Unknown `--det*` throws.
Environment read: `DETJS` (=1 enables), `DETJS_SEED`, `DETJS_CACHE_DIR`, `DETJS_NATIVE`, `DETJS_EARLY`,
`DETJS_JEST_RUNNER=replace`, `DETJS_CACHE_IDENTITY=sync`, `DETJS_CACHE_SKIP_DIRS`, `FENVIX_CACHE_TOKEN[_FD|_FILE]`,
`FENVIX_CACHE_LOCAL`, `FENVIX_CACHE_ALLOW_HTTP`, `FENVIX_RUNTIME_ISA` (last five from docs/NODE-CACHE.md, not verified in code).
Set for workers: `DETJS, DETJS_SEED, DETJS_SHUFFLE, DETJS_DIR, DETJS_ROOT, DETJS_EPOCH, DETJS_TICK, DETJS_TICK_ADAPT,
DETJS_TIMERS, DETJS_TIMER_BUDGET, DETJS_DISABLE, DETJS_NET_MODE, DETJS_CASSETTE, DETJS_ALLOW_HOSTS, DETJS_URANDOM,
DETJS_MAX_EVENTS, DETJS_SITES, DETJS_RUNNER`, plus `DETJS_CACHE`, `DETJS_VITEST_DIR`, `DETJS_JEST_RUNNERS`; Vitest path also sets `TEST`, `VITEST`, `NODE_ENV`.
Files written: `<root>/.detjs/run-<pid>/parts/*.jsonl` (removed), `.detjs/trace.jsonl`, `.detjs/cassette.json`
(record), `.detjs/receipts.jsonl`, `.detjs/cache-summary.json`, `.detjs/cache-identity.json`, the store
`<cache dir>/proof-cache.json`, shims `<root>/node_modules/.detjs/runner-<pid>.mjs` / `jest-runner-<pid>.js`,
replay sockets `$TMPDIR/detjs-<pid>-*.sock`.

## Control table (Vitest and Jest, RAN unless marked READ/DOC)

| API | state under `--det` | gap |
|---|---|---|
| Date.now, new Date(), Date() | controlled (epoch 2025-01-01Z per test) + recorded | fake timers: ND2-026 |
| performance.now (global) | controlled + recorded | Jest perf_hooks import real: ND2-012 |
| performance.timeOrigin / mark / eventLoopUtilization | untouched, unrecorded | ND2-002, 003, 005 |
| process.hrtime / hrtime.bigint | controlled + recorded | |
| process.uptime, os.uptime, process.cpuUsage | untouched, unrecorded | ND2-001, 004, 005 |
| setTimeout / setInterval | virtual inside tests ((due, creation) order; 60 s timer returns at once), real outside tests and once I/O is pending | ND2-027, 059 |
| setImmediate | native order, recorded | |
| timers/promises.setTimeout | virtual | |
| timers/promises.setInterval, scheduler.wait, setImmediate | untouched (real waits) | ND2-006, 007, 008 |
| AbortSignal.timeout | untouched (real), inverted against virtual timers | ND2-009 |
| queueMicrotask / nextTick / promise order | untouched (language order, stable in runs) | |
| time zone, locale, Intl defaults | untouched, unrecorded | ND2-010, 011 |
| Temporal | untouched (READ) | ND2-013 |
| vi/jest.useFakeTimers | fake clock starts at REAL time; advance works; after useRealTimers virtual again | ND2-026 |
| sinon fake timers | work (now given explicitly), virtual again after restore | |
| Math.random | controlled (per-test seed) + recorded | vm, workers: ND2-023, 024 |
| crypto.randomUUID, getRandomValues (global, node, webcrypto) | controlled + recorded | |
| crypto.randomBytes, pseudoRandomBytes, randomFillSync, randomInt (sync) | recorded only; controlled with `--det-urandom` | ND2-021 |
| crypto.randomFill (async), randomInt (callback) | untouched, unrecorded | ND2-014, 015 |
| generateKeyPair, generateKey, createECDH, generatePrime, subtle.generateKey | untouched, unrecorded | ND2-016..020 |
| uuid v4/v7, nanoid, faker, chance | deterministic (through the controlled sources); uuid v1 uses clock + random: stable x2 | |
| Buffer.allocUnsafe | untouched | ND2-022 |
| object key / Map / Set order, Symbol | language-defined, stable | |
| fetch, undici, http, https, http2, net, tls, axios, got, node-fetch, superagent, ws, eventsource, pg, mysql2, ioredis, mongodb | external: blocked (`NetworkBlockedError` ECONNREFUSED) + recorded as `net.connect ... blocked`; loopback allowed, unrecorded | ND2-033, 035 |
| dns.lookup, dns.resolve*, dns.promises.* | blocked (ENOTFOUND) + recorded | |
| new dns.Resolver(), dns.reverse, dns.lookupService | untouched | ND2-031, 032 |
| dgram | untouched | ND2-030 |
| global WebSocket | connect blocked; handshake key from real entropy | ND2-043 |
| nock 15 | BROKEN under `--det` | ND2-029 |
| msw 2, undici MockAgent | work | |
| record / replay | works for the opening test in the recorded order only | ND2-036..041 |
| fs.readdir (sync, cb, promises, withFileTypes, recursive), opendir, fs.glob (Node 22.23), glob, fast-glob, globby | sorted + recorded | ND2-047, 070 |
| fs.stat times / ino, mkdtemp names, fs.watch, chokidar | untouched, unrecorded | ND2-028, 044, 045, 046 |
| process.env (read, iteration), CI vars | untouched, unrecorded by `--det`; keyed by the cache only | ND2-048, 049, 050 |
| pid, hostname, cpus, userInfo, memoryUsage, argv | untouched, unrecorded | ND2-051..055 |
| I/O completion order, Promise.race of I/O | untouched, unrecorded | ND2-056, 057, 058 |
| worker_threads | untouched, untraced | ND2-024, 061 |
| child_process (spawn, exec, fork), cluster | untouched, untraced | ND2-062..065 |
| vm contexts, ShadowRealm | untouched | ND2-023, 069 |
| WebAssembly importing Math.random | controlled (gets the patched function); WASI natives untouched (READ) | ND2-068 |
| native addons (better-sqlite3), node:sqlite | untouched | ND2-066, 067 |
| Atomics.wait | real wait | ND2-060 |

## (b) Evidence appendix (trimmed real outputs)

§E-time (ND2-001..012). `detjs vitest run --det --det-trace=.detjs/v{1,2}.jsonl t/time.test.js`, values written by the tests:
```
["Date.now",1735689600000] ["performance.now",1000.004] ["hrtime",[1000,6000]]      (equal in both runs)
run1 ["performance.timeOrigin",1795163593129.604] ["process.uptime",0.368503246] ["os.uptime",1023.41] ["performance.mark",368.999451]
run2 ["performance.timeOrigin",1795163599897.377] ["process.uptime",0.524154346] ["os.uptime",1030.34] ["performance.mark",524.690856]
["long timer virtual elapsed",60000] ["order",["micro","then","tick","imm","c5","b10","a10"]]
["tp.setInterval 3x400 virtual ms",0] ["tp.setInterval real waited >1s",true] ["scheduler.wait(1500) virtual ms",0]
["AbortSignal.timeout(3000) vs setTimeout(10000)","timeout10s-first"]
detjs verify v1 v2 => covered by Level 0: 8  not covered: 0   exit=0
TZ=Asia/Tokyo LANG=de_DE.UTF-8 run => ["getTimezoneOffset",-540] ["locale","de-DE"] ["num.toLocaleString","1.234.567,891"]; verify v1 vtz => covered 8, exit 0
Jest: ["perf_hooks.now",1582.838862] (Vitest: 1000.005)
```
§E-fake (ND2-026): `["fake Date.now after useFakeTimers",1795163827415]` run 1, `1795163833817` run 2 (Vitest); Jest `1795163852842` / `1795163855158`; verify: covered 3.
§E-stdio (ND2-027): PipeWrap count `base 2, after stderr 2, after stdout 3, after stdin 4`, then `["real waited >1s",true]` (Vitest); Jest: stdin only.
§E-random (ND2-014..024): values differing between two `--det --det-urandom` runs: randomFill async, randomInt async,
generateKeyPairSync ec, generateKeySync aes, createECDH, generatePrimeSync, subtle.generateKey, Buffer.allocUnsafe,
vm.runInNewContext Math.random / Date.now (1795163710122 = real), worker Math.random / Date.now / randomUUID;
`detjs verify u1 u2` => `covered by Level 0: 4  not covered: 0`, exit 0. Events of the first test: Math.random,
randomUUID x2, getRandomValues x3, randomBytes x3, randomFillSync, randomInt. 'other realms' test: 1 event (outcome).
§E-net (ND2-029..035, 043): see the control table; `["dgram send ext","SENT (not blocked)"]`,
`["new dns.Resolver().resolve4 ext","ERR Error:ENOTFOUND:queryA ENOTFOUND example.com"]`; nock:
`npx vitest run` => `["nock http.get","nocked"]`, `detjs vitest run --det` => `"ERR detjs: network access to api.example.com:80 blocked"`, `--det-disable=net` => nocked.
§E-net-replay (ND2-036..039): server on 0.0.0.0:18473 reached through 192.0.2.2 (non-loopback, so "external").
Cassette after `--det-record`: `{"format":"detpy-cassette","version":1,"tests":{"t/rr.test.js::one":[{"host":"192.0.2.2","port":18473,"tls":false,"segments":[send,recv,send,recv]}]}}` (test two's request inside test one's connection; base64 of `authorization: Bearer SECRET-TOKEN-123` present).
Replay, server stopped: both pass. `-t two` => `["two","ERR detjs: network access to 192.0.2.2:18473 blocked ..."]`; `--det-seed=1` (order two, one) => same error for two. `ND2_PATH=/b` => one still returns `{"path":"/a",...}`, trace event `replay-mismatch 192.0.2.2:18473#0 segment 0`.
§E-sched (ND2-057, 058): 20 runs each of t2/race.test.js:
```
plain: fs 0123 x14, 0132, 0213, 1023, 1230 x2, 3120 | http /a x15, /b x5 | timer-vs-io: io x3, timer x17
--det: fs 0123 x9, 0132 x4, 0213 x2, 0231 x3, 2301, 3021 | http /a x15, /b x5 | timer-vs-io: timer x20
detjs verify race1..race20 => covered by Level 0: 3  not covered: 0  exit=0
```
§E-child (ND2-062..067): `["spawnSync node",{"r":0.788481319086958,"d":1795164414818,"det":"1",...}]`, fork the same, better-sqlite3 `{"r":"EFB17DB7","t":"1795164417"}`; all differ in run 2; trace counts `{"time":3,"outcome":1}`.
§E-features: seeds (p3) `vitest seed 1: b2 > b1 > a3 > a2 > a1 > c1` twice, identical on Jest; seed 2 and 3 differ.
Failure output ends with `detjs: trace .detjs/trace.jsonl: 6 tests, order digest ...` (no replay command, ND2-071).
`detjs verify s1 s2 --json` gives `divergence.index`, `event_a/event_b` with `at: "t/b.test.js:2"`, `reason`, `description`; exit 1 on divergence, 2 on usage or error; TS site `ts/x.test.ts:7` correct (source-mapped).
§E-cache (Vitest, p4): cold 15 s, warm "reused with proof 13 tests in 12 files". Wrong-reuse probes, each: mutate one input, run, revert. All of these correctly RAN and failed (no wrong reuse): fx JSON read with fs (`data: fx/data.json (f)`), transitive module (`data: lib/b.js (f)`), env var (`env: environment variable ND2_CACHE_VAR`), file read by a child (never cached: subprocess), existsSync target deleted (`data: fx/maybe.txt (s)`), node_modules file (everything reran, `runtime:`), snapshot file (`data: t/__snapshots__/snap.test.js.snap (f)`), vitest.config define (everything reran, `config:`), alias target (`code: lib/alias_target.js (content)`), setupFiles content (everything reran, `code: setup.js (content)`), computed require (`data: lib/dyn_one.js (f)`), second test's file, sqlite db through a native addon (never cached), globalSetup input (everything reran, `data: fx/gs-in.txt (f)`).
Wrong reuses found: ND2-099 (fake timers, real clock, `"reused":true,"epoch":null`), ND2-100 (`--det-disable=time` + cache).
ND2-101: `p4` warm => "reused with proof 15 tests in 14 files"; the copy in `other/deep/p4b` with the same store => "reused with proof 0 tests in 0 files", 14 x `config:`.

## (c) For the lead

- "Covered by Level 0" in `detjs verify` means only "the recorded events were equal". It was printed for runs that
  differed in time zone, locale, environment variables, child output, worker output, vm-context randomness and I/O
  order. This is the largest class of findings here (false "identical").
- docs/NODE.md lists J1-J17 as "known limits"; J1, J3, J4, J7, J8, J15 are gaps against the promise (entries above).
- DECISIONS 2026-11-19 says the virtual-day rule is "the same rule for Python, Node and Go"; Node has a constant epoch (ND2-081) and no nightly real-clock run (ND2-082).
- NOW.md says "detjs Vitest/Jest skip (0 wrong in 738,552)"; two wrong reuses were produced by hand in minutes (ND2-099, ND2-100). Both go through a clock read that never becomes an event.
- docs/NODE-CACHE.md says shared caches need "the same work paths" only for files outside the project; in my run the whole configuration digest changed with the checkout path (ND2-101), so nothing was reused.
- Severity note: ND2-081 is marked WRONG-RESULT from the constant epoch and one receipt, not from a run across two real days.
