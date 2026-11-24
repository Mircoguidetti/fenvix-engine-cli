'use strict';
const volatile = require('./volatile');
// Main-process side of a --det run, shared by `detjs vitest` and `detjs jest`:
// option parsing, environment for the workers, merge of the per-file trace
// parts into one trace (same format as the Python shell), comparison report.
const fs = require('node:fs');
const path = require('node:path');
const native = require('./native');
const config = require('./config');
const exitStatus = require('./exit-status');

const VERSION = require('../package.json').version;

const HELP = `detjs options (all others are passed to the test runner):
  --det                    enable deterministic execution (Level 0); also DETJS=1
  --det-seed=N             reproducible shuffle of files and tests, seed of every generator
                           (default: fixed order, seed 0)
  --det-order-seed=N       shuffle the order with N, keep the generators on --det-seed (default: --det-seed): a new
                           order with the same Math.random / randomUUID values, or new values in the same order
  --det-trace=PATH         trace file (default: <root>/.detjs/trace.jsonl)
  --det-order=FILE         run exactly the test ids listed in FILE (one per line), in that order; files run in the
                           order of their first listed test, describe blocks likewise (docs/NODE.md, "Repro")
  --det-outcomes=PATH      write order, outcomes, fingerprints and exceptions of the run as JSON (repro drivers)
  --det-collect            collection only: write the order this run would use to --det-outcomes; run no test
  --det-compare=TRACE      compare fingerprints with a previous trace
  --det-net=open|closed    open (default): external hosts are reached like --det-allow-host hosts (a net event
                           "<host>:<port> allowed", bytes in the fingerprint; a test that used one is never reused by
                           the cache); closed: refused with NetworkBlockedError (the earlier default)
  --det-record             allow external network access and record it into the cassette
  --det-cassette=PATH      network cassette (default: <root>/.detjs/cassette.json); replayed when present
  --det-cassette-max-age=D do not replay recordings older than D days (refused like an unrecorded connection; default
                           0 = no limit; recordings older than 30 days are always reported)
  --det-allow-host=HOST    external host that may be reached (repeatable)
  --det-epoch=ISO|fixed    wall clock at the start of every test (default: the machine's time when the run starts,
                           rounded down to the second, one value for every process of the run; with --det-cache the
                           virtual day; with --det-compare/--det-plan=TRACE the epoch of that trace; fixed =
                           ${config.DEFAULT_EPOCH}); recorded as meta.epoch / meta.epoch_ns
  --det-tick=NS            nanoseconds per clock read (default 1000)
  --det-tick-adapt=N       double the tick after N consecutive reads with no other event (default 1000, 0 = fixed)
  --det-timers=real        timers wait for real (default: virtual, fast while no I/O is pending)
  --det-timer-budget=N     fast timer firings per test before falling back to real waits (default 100000)
  --det-disable=LIST       controls to turn off: ${config.CONTROLS.join(',')}
  --det-urandom[=on|off]   on: also make crypto.randomBytes/randomFillSync/randomInt deterministic (NOT for crypto
                           tests); off (default): observed only, recorded as entropy events and reported at the end
                           (the WebSocket handshake keys and frame masks are deterministic either way)
  --det-max-events=N       events stored verbatim per test (default 10000)
  --det-sites=off          do not resolve call sites (faster; runner frames are then not told apart)
  --det-cache=DIR|URL      cache with proof: skip test files whose every recorded input is unchanged
                           (a directory, or a shared cache service https://host/<namespace>)
  --det-cache-verify       decide reuse but run every file anyway and compare (receipts say what would be reused)
  --det-tz=ZONE|keep       time zone of the run (default keep: the machine's TZ; --det-tz=UTC pins it; recorded)
  --det-locale=LOC|keep    LC_ALL and LANG of the run (default keep: the machine's; --det-locale=C.UTF-8 pins them)
  --det-cache-max-age=D    never reuse a result recorded more than D days ago (default 30; 0 = no limit)
  --det-cache-real-clock   nightly check: run every file on the real clock (no reuse, nothing recorded) and report
                           each test whose cached result differs (an expiry); its cache entries are removed
                           With --det-cache and no --det-epoch the epoch is today 00:00 UTC (the virtual day): a
                           test that reads the clock is reused only on the UTC day it was recorded
  --det-isolate            a fresh process per test (Vitest, Jest) or per test file (Mocha, Jasmine, uvu, Bun, Deno):
                           no in-memory state crosses that boundary; with --det-cache, a test (file) is reused or run
                           on its own inputs only (docs/NODE-CACHE.md)
  --det-cache-receipts=P   receipts file (default <root>/.detjs/receipts.jsonl)
  --det-cache-summary=P    summary JSON (default <root>/.detjs/cache-summary.json)
  --det-workers=N|N%|auto  run test files in N parallel lanes with a fixed plan (default: the machine's CPUs, or the
                           runner's own --maxWorkers / -w / --fileParallelism when given on the command line;
                           --det-workers=1 or the runner's own serial option for one lane)
  --det-plan=TRACE|JSON    replay the lane plan of an earlier parallel run (its trace's meta.parallel.plan)
`;

/** Split argv into detjs options and runner arguments. */
function parseArgs(argv, env = process.env) {
  const opts = {
    det: env.DETJS === '1' || env.DETJS === 'true',
    seed: null, trace: null, compare: null, record: false, cassette: null, allowHosts: [],
    epoch: null, tick: 1000, tickAdapt: 1000, timers: 'virtual', timerBudget: 100000,
    disable: '', urandom: false, cassetteMaxAge: 0, maxEvents: 10000, sites: true,
    cache: null, cacheVerify: false, cacheReceipts: null, cacheSummary: null, cacheRealClock: false, epochExplicit: false,
    net: 'open',
    workers: null, plan: null,
    order: null, outcomes: null, collect: false, orderSeed: null,
    isolate: env.DETJS_ISOLATE === '1',
  };
  if (env.DETJS_CACHE_DIR) opts.cache = env.DETJS_CACHE_DIR;
  if (env.DETJS_SEED !== undefined && env.DETJS_SEED !== '') opts.seed = config.int(env.DETJS_SEED, 0);
  const rest = [];
  const takes = new Set(['--det-cassette-max-age', '--det-cache-max-age', '--det-tz', '--det-locale', '--det-seed', '--det-order-seed', '--det-trace', '--det-compare', '--det-cassette', '--det-allow-host', '--det-epoch', '--det-net',
    '--det-tick', '--det-tick-adapt', '--det-timers', '--det-timer-budget', '--det-disable', '--det-max-events', '--det-sites',
    '--det-cache', '--det-cache-receipts', '--det-cache-summary', '--det-workers', '--det-plan', '--det-order', '--det-outcomes']);
  for (let i = 0; i < argv.length; i++) {
    let a = argv[i];
    if (!a.startsWith('--det')) { rest.push(a); continue; }
    let value;
    const eq = a.indexOf('=');
    if (eq >= 0) { value = a.slice(eq + 1); a = a.slice(0, eq); } else if (takes.has(a)) { value = argv[++i]; }
    switch (a) {
      case '--det': opts.det = true; break;
      case '--det-seed': opts.seed = config.int(value, 0); break;
      case '--det-order-seed': opts.orderSeed = config.int(value, 0); break;
      case '--det-trace': opts.trace = value; break;
      case '--det-compare': opts.compare = value; break;
      case '--det-record': opts.record = true; break;
      case '--det-net':
        if (value !== 'open' && value !== 'closed') throw new Error(`detjs: --det-net: open or closed, got ${value}`);
        opts.net = value;
        break;
      case '--det-cassette': opts.cassette = value; break;
      case '--det-allow-host': opts.allowHosts.push(value); break;
      case '--det-epoch': config.parseEpoch(value); opts.epoch = value === 'fixed' ? config.DEFAULT_EPOCH : value; opts.epochExplicit = true; break;
      case '--det-tick': opts.tick = config.int(value, 1000); break;
      case '--det-tick-adapt': opts.tickAdapt = config.int(value, 1000); break;
      case '--det-timers': opts.timers = value === 'real' ? 'real' : 'virtual'; break;
      case '--det-timer-budget': opts.timerBudget = config.int(value, 100000); break;
      case '--det-disable': config.controls(value); opts.disable = value; break;
      case '--det-urandom':
        if (value === undefined || ['on', '1', 'true', 'yes'].includes(value)) opts.urandom = true;
        else if (['off', '0', 'false', 'no'].includes(value)) opts.urandom = false;
        else throw new Error(`detjs: --det-urandom: on or off, got ${value}`);
        break;
      case '--det-cassette-max-age':
        opts.cassetteMaxAge = Number(value);
        if (!(opts.cassetteMaxAge >= 0)) throw new Error(`detjs: --det-cassette-max-age: not a number of days: ${value}`);
        break;
      case '--det-max-events': opts.maxEvents = config.int(value, 10000); break;
      case '--det-sites': opts.sites = value !== 'off' && value !== '0'; break;
      case '--det-cache': opts.cache = value; break;
      case '--det-cache-verify': opts.cacheVerify = value === undefined || value === '1' || value === 'true'; break;
      case '--det-cache-real-clock': opts.cacheRealClock = true; break;
      case '--det-isolate': opts.isolate = value === undefined || value === '1' || value === 'true'; break;
      case '--det-cache-max-age': opts.cacheMaxAge = Number(value); if (!(opts.cacheMaxAge >= 0)) throw new Error(`detjs: --det-cache-max-age: not a number of days: ${value}`); break;
      case '--det-tz': case '--det-locale': break; // applied by bin/detjs.js before the runner starts
      case '--det-cache-receipts': opts.cacheReceipts = value; break;
      case '--det-cache-summary': opts.cacheSummary = value; break;
      case '--det-workers': opts.workers = value; break;
      case '--det-plan': opts.plan = value; break;
      case '--det-order': opts.order = value; break;
      case '--det-outcomes': opts.outcomes = value; break;
      case '--det-collect': opts.collect = value === undefined || value === '1' || value === 'true'; break;
      case '--det-help': process.stdout.write(HELP); process.exit(0); break;
      default: throw new Error(`detjs: unknown option ${a}\n${HELP}`);
    }
  }
  resolveEpoch(opts, env);
  if (opts.cacheRealClock) {
    if (!opts.cache) throw new Error('detjs: --det-cache-real-clock needs --det-cache=DIR|URL');
    // run on the real clock; the reuse decision is still the one of the virtual day (src/cache/proof.js)
    opts.cacheVerify = true;
    const off = new Set(String(opts.disable || '').split(',').filter(Boolean));
    off.add('time');
    opts.disable = [...off].join(',');
  }
  return { opts, rest };
}

/**
 * The epoch of the run, picked once (spec "--det uses the machine's values by default", 2026-11-23). First match:
 * --det-epoch; the DETJS_EPOCH of the run this session belongs to (exported by the outermost detjs, bin/detjs.js,
 * which marks it DETJS_EPOCH_RUN=1; the one-lane re-run's passes and --det-isolate's sessions carry their own marks
 * too); with --det-cache the virtual day; the meta.epoch_ns of the trace given to --det-compare or --det-plan; the
 * machine's time now, rounded down to the second.
 */
function resolveEpoch(opts, env = process.env) {
  opts.epochSource = 'option';
  if (opts.epochExplicit) return opts.epoch;
  const child = env.DETJS_EPOCH_RUN === '1' || env.DETJS_HAZARD_RERUN === '1' || env.DETJS_ISOLATE_CHILD === '1';
  if (child && env.DETJS_EPOCH) {
    try { config.parseEpoch(env.DETJS_EPOCH); opts.epoch = env.DETJS_EPOCH; opts.epochSource = 'run'; return opts.epoch; } catch { /* picked below */ }
  }
  if (opts.cache) { opts.epochSource = 'cache'; return (opts.epoch = virtualDay()); }
  for (const t of [opts.compare, opts.plan]) {
    const ns = traceEpochNs(t);
    if (ns !== null) { opts.epochSource = 'trace'; return (opts.epoch = isoOfNs(ns)); }
  }
  opts.epochSource = 'host';
  return (opts.epoch = new Date(Math.floor(Date.now() / 1000) * 1000).toISOString().replace('.000Z', 'Z'));
}

function isoOfNs(ns) {
  return new Date(Number(BigInt(ns) / 1000000n)).toISOString();
}

/** meta.epoch_ns of a trace file (its header line), or null (no such file, a JSON plan, no epoch). */
function traceEpochNs(file) {
  if (!file) return null;
  let fd = null;
  try {
    fd = fs.openSync(file, 'r');
    const buf = Buffer.alloc(1 << 20);
    const n = fs.readSync(fd, buf, 0, buf.length, 0);
    const text = buf.subarray(0, n).toString('utf8');
    const nl = text.indexOf('\n');
    const head = JSON.parse(nl < 0 ? text : text.slice(0, nl));
    const ns = head && head.type === 'header' && head.meta ? head.meta.epoch_ns : undefined;
    return ns !== undefined && /^\d+$/.test(String(ns)) ? String(ns) : null;
  } catch {
    return null;
  } finally {
    if (fd !== null) { try { fs.closeSync(fd); } catch { /* closed */ } }
  }
}

/** Today 00:00 UTC on the real clock (DECISIONS 2026-11-19: the virtual day of skip with proof). */
function virtualDay(now = Date.now()) {
  const d = new Date(now);
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate())).toISOString().replace('.000Z', 'Z');
}

/** Prepare the run directory and the DETJS_* environment inherited by the workers. */
function prepare(opts, root, runner) {
  const dir = path.join(root, '.detjs', `run-${process.pid}`);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'parts'), { recursive: true });
  // .detjs holds the engine's run state: a .gitignore of `*` keeps the checkout clean for later CI steps (audit
  // G-2177), as pytest's and Vitest's caches do
  try { fs.writeFileSync(path.join(root, '.detjs', '.gitignore'), "# created by fenvix (the engine's run state)\n*\n", { flag: 'wx' }); } catch { /* present or read-only */ }
  const cassette = path.resolve(root, opts.cassette || path.join('.detjs', 'cassette.json'));
  // --det-net=open (default) reaches external hosts live; closed refuses them; --det-record and an existing cassette
  // keep recording and replaying
  const netMode = opts.record ? 'record' : fs.existsSync(cassette) ? 'replay' : opts.net === 'closed' ? 'block' : 'open';
  const env = {
    DETJS: '1',
    DETJS_SEED: String(opts.seed ?? 0),
    DETJS_SHUFFLE: opts.seed !== null || opts.orderSeed !== null ? '1' : '0',
    DETJS_ORDER_SEED: opts.orderSeed !== null ? String(opts.orderSeed) : '',
    DETJS_DIR: dir,
    DETJS_ROOT: root,
    DETJS_EPOCH: opts.epoch,
    DETJS_TICK: String(opts.tick),
    DETJS_TICK_ADAPT: String(opts.tickAdapt),
    DETJS_TIMERS: opts.timers,
    DETJS_TIMER_BUDGET: String(opts.timerBudget),
    DETJS_DISABLE: opts.disable,
    DETJS_NET_MODE: netMode,
    DETJS_CASSETTE: cassette,
    DETJS_ALLOW_HOSTS: opts.allowHosts.join(','),
    DETJS_URANDOM: opts.urandom ? '1' : '0',
    DETJS_CASSETTE_MAX_AGE: String(opts.cassetteMaxAge || 0),
    DETJS_MAX_EVENTS: String(opts.maxEvents),
    DETJS_SITES: opts.sites ? '1' : '0',
    DETJS_RUNNER: runner,
    DETJS_ORDER: opts.order ? path.resolve(opts.order) : '',
    DETJS_COLLECT: opts.collect ? '1' : '',
  };
  if (opts.order && !fs.existsSync(env.DETJS_ORDER)) throw new Error(`detjs: --det-order: no such file ${opts.order}`);
  Object.assign(process.env, env);
  // the mark of the run's epoch is for the detjs sessions of the run (bin/detjs.js), not for the tests' processes
  delete process.env.DETJS_EPOCH_RUN;
  // the capture's loader mode is chosen per shell for its own test processes (runners/common.js childEnv sets
  // `register` for the tap, AVA, Jasmine and uvu shells): never inherited from an outer process
  delete process.env.DETJS_CAPTURE_LOADER;
  const cfg = config.fromEnv(process.env);
  const run = { dir, cassette, netMode, cfg, tracePath: path.resolve(root, opts.trace || path.join('.detjs', 'trace.jsonl')) };
  if (netMode === 'replay') cassetteStaleness(run, opts);
  // the main process (globalSetup, start-up code): external connections closed, recorded or replayed (G-1419)
  if (cfg.active && cfg.controls.has('net')) {
    try { require('./network').installStartup(new (require('./patch').Patcher)(), cfg); } catch (e) { process.stderr.write(`detjs: WARNING: the network control could not be installed in the main process: ${e && e.message}\n`); }
  }
  // the project's own reads in this process (the runner's configuration, globalSetup) are reads outside any test
  // (docs/VERIFY-INPUTS.md)
  if (cfg.active) {
    try { require('./controls').installMainEnvRecord(root); } catch (e) { process.stderr.write(`detjs: WARNING: environment reads of the main process are not recorded: ${e && e.message}\n`); }
  }
  // Jest runs the tests in this process, and its test environment loads Node's bundled undici (it copies the
  // global descriptors) before the detjs test runner installs Level 0; from Node 24 undici keeps the
  // `crypto.randomFillSync` / `randomInt` it finds when it loads (WebSocket masks, FormData boundaries). The OS entropy
  // controls are installed now, so that what undici keeps is detjs' (G-1421, G-1426).
  if (runner === 'jest' && cfg.active && cfg.controls.has('seeds')) {
    try {
      const controls = require('./controls');
      require('./seeds').installProcess(controls.PATCHER, controls.cfg());
    } catch (e) { process.stderr.write(`detjs: WARNING: the entropy control could not be installed early: ${e && e.message}\n`); }
  }
  return run;
}

const CASSETTE_WARN_DAYS = 30;
/**
 * Age of the replayed recordings (G-1418): recordings older than --det-cassette-max-age are not replayed; older than
 * 30 days (or of unknown age) are reported. The cache key of the cassette covers which recordings are stale today.
 */
function cassetteStaleness(run, opts) {
  const network = require('./network');
  const max = Number(opts.cassetteMaxAge) || 0;
  const ages = network.cassetteAges(run.cassette, max);
  run.cassetteStale = ages.stale;
  run.cassetteKey = `${native.fileDigest(run.cassette) || 'missing'}${max > 0 ? `|max-age=${max}|stale=${native.digest(Buffer.from(ages.stale.join('\n'))).slice(0, 16)}` : ''}`;
  run.cassetteOldestDays = ages.oldest ? Math.floor(ages.oldest.days) : null;
  const rel = path.relative(process.cwd(), run.cassette) || run.cassette;
  if (max > 0 && ages.stale.length) {
    process.stderr.write(`detjs: cassette ${rel}: ${ages.stale.length} recorded test(s) older than ${max} days or of unknown age are not replayed (--det-cassette-max-age); re-record them with --det-record\n`);
  } else if (ages.oldest && ages.oldest.days > CASSETTE_WARN_DAYS) {
    process.stderr.write(`detjs: WARNING: cassette ${rel}: recordings up to ${Math.floor(ages.oldest.days)} days old (${ages.oldest.key}); replayed responses may be stale: re-record with --det-record, or refuse old ones with --det-cassette-max-age=D\n`);
  }
  if (ages.unknown && !(max > 0)) {
    process.stderr.write(`detjs: WARNING: cassette ${rel}: ${ages.unknown} recorded connection(s) of unknown age (recorded before detjs stored recording dates); re-record with --det-record\n`);
  }
}

function header(run, opts, extra) {
  const c = run.cfg;
  const shuffleSeed = opts.orderSeed !== null ? opts.orderSeed : opts.seed;
  const order = shuffleSeed !== null ? `shuffled with seed ${shuffleSeed}${opts.orderSeed !== null ? ` (--det-order-seed; generators: seed ${opts.seed ?? 0})` : ''}` : 'fixed (sorted files, declaration order)';
  return [
    `detjs ${VERSION}: Level 0 active; runner=${extra.runner} ${extra.runnerVersion}; controls=${[...c.controls].sort().join(',')}; order ${order}`,
    `detjs: ${extra.parallel || 'serial execution'} (${extra.isolation}); network=${run.netMode}; timers=${c.timers}; entropy=${c.urandom ? 'controlled (--det-urandom)' : 'observed (--det-urandom to control)'}; node ${process.version}`,
  ];
}

/** Ids of the tests recorded in a part, in execution order. */
function partNotes(file) {
  try {
    const first = require('./trace-lines').firstLine(file);
    return (JSON.parse(first).meta || {}).notes || [];
  } catch {
    return [];
  }
}

/** The ids of every part, in order; `onError(part, err)` for a part whose ids cannot be read (it adds none). */
function partOrder(parts, onError) {
  const order = [];
  for (const p of parts) {
    let ids;
    try { ids = partIds(p); } catch (e) { onError(p, e); continue; }
    // one push per id: spreading a part's ids into push() overflows the stack above ~100 000 arguments
    for (const id of ids) order.push(id);
  }
  return order;
}

/** Ids of the tests recorded in a part, in execution order. Streams the part (src/trace-lines.js); a part that
 * cannot be read throws (the caller fails closed: src/session.js finish). A line that is not JSON is skipped (a
 * truncated last line, as before). */
function partIds(file) {
  const ids = [];
  require('./trace-lines').forEachLine(file, (line) => {
    if (!line.startsWith('{"type":"test"')) return;
    try { ids.push(JSON.parse(line).nodeid); } catch { /* truncated last line */ }
  });
  return ids;
}

/** Run inputs the verifier compares (header `inputs`, crates/detpy-core/src/verify.rs): two runs whose inputs differ
 * are never reported identical, and the first differing input is named. Values of environment variables are
 * digests. The time zone and the locale are not pinned by this shell: they are recorded, so a difference is reported
 * (audit G-0139, G-0140). */
function runInputs(run, meta) {
  const crypto = require('node:crypto');
  const dig = (t) => crypto.createHash('sha256').update(String(t)).digest('hex').slice(0, 16);
  const cfg = run.cfg;
  const has = (c) => cfg.controls.has ? cfg.controls.has(c) : [...cfg.controls].includes(c);
  let tz = '?';
  let loc = '?';
  try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch { /* no Intl */ }
  try { loc = Intl.DateTimeFormat().resolvedOptions().locale; } catch { /* no Intl */ }
  const offset = new Date(Number(cfg.epochNs / 1000000n)).getTimezoneOffset();
  const lc = ['LC_ALL', 'LC_CTYPE', 'LC_TIME', 'LC_NUMERIC', 'LANG', 'LANGUAGE'].filter((k) => k in process.env)
    .map((k) => `${k}=${process.env[k]}`).join(',');
  const inputs = {
    runtime: `node ${process.version} ${process.platform} ${process.arch}`,
    runner: `${(meta && meta.runner) || ""} ${(meta && meta.runner_version) || ""}`.trim(),
    seed: String(cfg.seed),
    shuffle: cfg.shuffle ? 'yes' : 'no',
    clock: has('time') ? `virtual epoch_ns=${cfg.epochNs} tick_ns=${cfg.tickNs} adapt=${cfg.tickAdapt} timers=${cfg.timers}` : 'real (time control off)',
    tz: `${tz} offset=${offset} TZ=${process.env.TZ === undefined ? '<unset>' : process.env.TZ} (not pinned)`,
    locale: `${loc} ${lc} (not pinned)`,
    network: has('net') ? String(run.netMode) : 'open (net control off)',
    entropy: cfg.urandom ? 'controlled' : 'observed',
  };
  // every variable but the engine's and the CI-volatile ones (design A: node/src/volatile.js) is a run input; a
  // differing one is reported `input-differs` for the tests that read it (their `env.get` events, src/controls.js)
  const vp = volatile.patterns();
  // while the network is closed the proxy variables are its part (the closed network decides every connection), not
  // inputs; while recording or open (the real network) they are inputs
  const closed = has('net') && String(run.netMode) !== 'record' && String(run.netMode) !== 'open';
  for (const [k, v] of Object.entries(process.env)) {
    if (volatile.isVolatile(k, vp) || (closed && volatile.PROXY_ENV.has(k))) continue;
    inputs[`env:${k}`] = dig(`${k}=${v}`);
  }
  return inputs;
}

const ENV_UNRECORDED_RUNNERS = new Set(['bun', 'deno']);

/** The variables the run's processes read outside any test (src/controls.js noteOutside), sorted. */
function envReadOutside(dir) {
  const names = new Set();
  const d = path.join(dir, 'envout');
  try {
    for (const f of fs.readdirSync(d)) {
      for (const l of fs.readFileSync(path.join(d, f), 'utf8').split('\n')) if (l) names.add(l);
    }
  } catch { /* none read */ }
  return [...names].sort();
}

/** The lines of every <run dir>/<sub>/*.txt, deduplicated. */
/**
 * `meta.provable` for the run, assembled from what every process declared (`prov/<pid>.txt`).
 *
 * The run declares a sensor only when every part declared the same one. A part that could not start a sensor, or
 * a part that wrote nothing, makes the run declare none -- and then the verifier reports every test NOT PROVEN,
 * which is the honest answer: that part's tests were not watched. Node runs tests in worker processes and merges
 * their traces here, so a worker's sensor is not otherwise visible where the header is built.
 */
function provableField(dir, reusedTests, order) {
  const lines = [...runLines(dir, 'prov')];
  const absent = lines.find((l) => l.startsWith('absent '));
  if (absent) return { provable_absent: absent.slice('absent '.length) };
  const decls = new Set(lines.filter((l) => l.startsWith('ok ')).map((l) => l.slice('ok '.length)));
  if (decls.size === 1) {
    try { return { provable: JSON.parse([...decls][0]) }; } catch { return {}; }
  }
  if (decls.size > 1) {
    return { provable_absent: `the run's processes declared ${decls.size} different sensors` };
  }
  // No process declared anything. That is right for a run in which nothing ran: every test came from the cache.
  // The claim this declaration rests on is that the RECORDING run could not have stored a test the rule refuses,
  // and it is kept by two paths that exist and are called (R-058 found this comment citing `admit_record`, which
  // has no caller outside its own test -- a premise nothing implemented, the same shape as the fail-open hole it
  // sat above, so it is replaced by what actually runs):
  //   * src/provable.js, on a gap -> STATE.onLevel0Gap, the engine's "never reuse this test" signal;
  //   * src/controls.js level0Gap, which fires when a sensor could not start, so a process without one makes the
  //     whole run store nothing.
  // There was nothing for this run to watch, and the fingerprints it compares are the ones the recording run was
  // held to, so the run declares the build's own table under `cache-reuse/1`. That name is in the core's known
  // set and carries the Node shell's required controls (crates/detpy-core/src/provable.rs: `sensor_known`,
  // `required_controls`), so a run that switched a control off is refused rather than waved through.
  const reused = (reusedTests || []).length;
  if (reused > 0 && reused === (order || []).length) {
    try {
      return { provable: JSON.parse(native.provableHeader('cache-reuse/1', require('./provable').runtimeKey())) };
    } catch { return {}; }
  }
  return {};
}

function runLines(dir, sub) {
  const out = new Set();
  const d = path.join(dir, sub);
  try {
    for (const f of fs.readdirSync(d)) {
      for (const l of fs.readFileSync(path.join(d, f), 'utf8').split('\n')) if (l) out.add(l);
    }
  } catch { /* none */ }
  return out;
}

/** Files read while no test ran (src/outside.js; docs/VERIFY-CONTRACT.md `files_read_outside_tests`), sorted. */
function filesReadOutside(dir) {
  const out = [];
  for (const l of runLines(dir, 'filesout')) {
    try { const e = JSON.parse(l); if (e && typeof e.path === 'string' && typeof e.digest === 'string') out.push({ path: e.path, digest: e.digest }); } catch { /* torn line */ }
  }
  return out.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : a.digest < b.digest ? -1 : a.digest > b.digest ? 1 : 0));
}

/** Merge the parts of the run into the final trace. `files`: [{fileId, part}] in execution order. */
function finish(run, opts, files, meta) {
  // what the main process (globalSetup) recorded
  try { require('./network').saveRecordings(); } catch (e) { process.stderr.write(`detjs: could not save the start-up recordings: ${e && e.message}\n`); }
  const executed = files.map((f) => ({ fileId: f.fileId, path: path.join(run.dir, 'parts', f.part) })).filter((p) => fs.existsSync(p.path));
  // --det-cache: the reused tests are in the trace too, with their recorded fingerprints (G-1402)
  const { paths: parts, reusedTests } = require('./cache/trace-reused').withReused(run, executed);
  // Parts not claimed by the sequencer order (should not happen) go last, sorted.
  const known = new Set(parts);
  const extra = fs.readdirSync(path.join(run.dir, 'parts')).map((p) => path.join(run.dir, 'parts', p)).filter((p) => !known.has(p)).sort();
  const all = [...parts, ...extra];
  // P0 big trace: a part whose ids cannot be read leaves the order incomplete: the run's status is unknown (exit 2)
  const order = partOrder(all, (p, e) => exitStatus.recordUnknown(`trace part ${p} could not be read: ${e && e.message}`));
  const full = {
    ...meta,
    runtime: 'node',
    runtime_version: process.versions.node,
    detjs: VERSION,
    seed: Number(run.cfg.seed),
    order_seed: Number(run.cfg.orderSeed),
    shuffle: run.cfg.shuffle,
    controls: [...run.cfg.controls].sort(),
    epoch_ns: run.cfg.epochNs.toString(),
    epoch: isoOfNs(run.cfg.epochNs),
    tick_ns: run.cfg.tickNs,
    tick_adapt: run.cfg.tickAdapt,
    timers: run.cfg.timers,
    network: run.netMode,
    urandom_controlled: run.cfg.urandom,
    entropy: run.cfg.urandom ? 'controlled' : 'observed',
    // the tests' environment reads are events (src/controls.js installEnvRecord) in Node processes; Bun's and
    // Deno's own environment APIs are not recorded. Without this the verifier counts every differing variable as
    // read by every test (exam F-01.hostname.pinned.node: USER/LOGNAME under sudo, read by no test)
    env_reads_recorded: !ENV_UNRECORDED_RUNNERS.has(String((meta && meta.runner) || '')),
    env_read_outside_tests: envReadOutside(run.dir),
    // review R-055 (docs/VERIFY-CONTRACT.md): files read and uncontrolled variables read while no test ran
    files_read_outside_tests: filesReadOutside(run.dir),
    not_proven_outside_tests: [...runLines(run.dir, 'npout')].sort(),
    // The general rule (crates/detpy-core/src/provable.rs): what this run watched. The verifier reports a test
    // IDENTICAL only when the run declared a sensor it knows, so leaving this out is not a cosmetic omission --
    // it is the run saying "I cannot show anything identical", which is what a run without a sensor must say.
    ...provableField(run.dir, reusedTests, order),
    cassette_max_age_days: run.cfg.cassetteMaxAge || 0,
    cassette_oldest_days: run.cassetteOldestDays === undefined ? null : run.cassetteOldestDays,
    node: process.version,
    platform: process.platform,
    files: files.map((f) => f.fileId),
    ...(reusedTests.length ? { reused_tests: reusedTests } : {}),
    unordered_parts: extra.length,
    notes: [...new Set(all.flatMap(partNotes))],
    // time zone and locale of the run: pinned by bin/detjs.js unless --det-tz/--det-locale=keep (G-0139, G-0140)
    pinned: process.env.DETJS_PINNED || 'no',
    tz: (() => { try { return `${Intl.DateTimeFormat().resolvedOptions().timeZone} TZ=${process.env.TZ === undefined ? '<unset>' : process.env.TZ}`; } catch { return '?'; } })(),
    locale: (() => { try { return `${Intl.DateTimeFormat().resolvedOptions().locale} LC_ALL=${process.env.LC_ALL || ''} LANG=${process.env.LANG || ''} LANGUAGE=${process.env.LANGUAGE || ''}`; } catch { return '?'; } })(),
  };
  try { full.inputs = runInputs(run, meta); } catch (e) { full.inputs_error = String(e && e.message); }
  // the installed dependencies of the project (src/loaded.js, review R-055 V5)
  try { const d = require('./loaded').depsInput(run.dir); if (d && full.inputs) full.inputs.deps = d; } catch (e) { full.inputs_error = String(e && e.message); }
  const res = native.mergeTraces(all, run.tracePath, JSON.stringify(full), order);
  // P0 big trace: a worker part the merge could not read is missing from the trace with its tests (and their
  // failures): the run's status is unknown, exit 2, never green
  if (res.skipped.length) exitStatus.recordUnknown(`unreadable trace parts, their tests are not counted: ${res.skipped.join('; ')}`);
  // B7 (spec "Engine P0: no false green"): the counts of the trace, in its header and on one status line; the exit
  // decision of this process (bin/detjs.js, src/exit-status.js runExit) uses them. A trace that cannot be read back
  // or stamped is a run whose status is unknown: exit 2 (P0 big trace; before, the runner's code decided, and a 1.2
  // GB trace with failed tests ended 0)
  let status = null;
  try {
    status = stampStatus(run.tracePath);
    if (!status) exitStatus.recordUnknown(`the trace ${run.tracePath} could not be read back`);
  } catch (e) {
    exitStatus.recordUnknown(`the trace ${run.tracePath} could not be read back or stamped: ${e && e.message}`);
  }
  if (status && !res.skipped.length && !exitStatus.recordedStatus()?.internalError) {
    exitStatus.record(status);
    // sync: the runner may be exiting; a stderr that cannot take the line (closed, full) must not abort the finish
    if (printsStatus(full)) { try { fs.writeSync(2, `${exitStatus.statusLine(status)}\n`); } catch { /* not printed */ } }
  }
  let reproLines = [];
  try { reproLines = require('./repro').afterMerge(run, opts, files, meta.runner); } catch (e) { reproLines = [`detjs: --det-outcomes not written: ${e && e.message}`]; }
  fs.rmSync(run.dir, { recursive: true, force: true });
  const lines = [`detjs: trace ${path.relative(process.cwd(), run.tracePath) || run.tracePath}: ${res.nTests} tests, order digest ${res.orderDigest}`];
  if (res.skipped.length) lines.push(`detjs: unreadable trace parts: ${res.skipped.join('; ')}`);
  let ent = [];
  try { ent = realEntropyTests(run.tracePath, run.cfg.urandom); } catch (e) { lines.push(`detjs: the entropy check could not read the trace: ${e && e.message}`); }
  if (ent.length) {
    lines.push(`detjs: ${ent.length} test(s) used real OS entropy, observed but not controlled (${[...new Set(ent.flatMap((e) => e.ops))].sort().join(', ')}): their results can differ between runs${run.cfg.urandom ? ' (native key generation)' : '; --det-urandom makes crypto.randomBytes & co. deterministic (not for tests of cryptography)'}, e.g. ${ent[0].nodeid}`);
  }
  if (opts.compare) {
    try {
      const rep = JSON.parse(native.verify([opts.compare, run.tracePath]));
      const s = rep.summary;
      lines.push(`detjs: compare with ${opts.compare}: covered=${s.stable} not-covered=${s.diverged} missing=${s.missing} outcome-unstable=${s.outcome_unstable}${s.order_identical ? '' : ' (ORDER DIFFERS)'}`);
      for (const t of rep.tests) {
        if (t.status === 'diverged' && t.divergence) {
          lines.push(`NOT COVERED by Level 0: ${t.nodeid} [${t.divergence.reason}]`);
          lines.push(`    ${t.divergence.description}`);
        }
      }
    } catch (e) {
      lines.push(`detjs: compare failed: ${e.message}`);
    }
  }
  lines.push(...reproLines);
  return { lines, result: res };
}

/**
 * Count the merged trace's tests (exit-status.js countStatus; a single run has no NOT PROVEN test of its own, B3)
 * and write the counts into its header as `meta.status` (appendix point 3: in `meta`, no change to the Rust Header).
 * The header line is edited as text, not re-serialized, so no other field of it can change; the new trace is
 * written beside the old one and renamed over it, so a crash never leaves a truncated trace. A test line that
 * cannot be parsed counts as failed.
 *
 * P0 big trace: the trace is streamed (src/trace-lines.js; a 1.2 GB trace does not fit in one JavaScript string),
 * and the body after the header line is copied byte for byte. A trace that cannot be read gives null; a stamp that
 * cannot be written or renamed THROWS. Either way the caller records the run's status as unknown (exit 2).
 */
function stampStatus(tracePath) {
  const { forEachLine, copyRange } = require('./trace-lines');
  const recs = [];
  let head = null;
  let headLen = 0;
  try {
    forEachLine(tracePath, (line, i, off, len) => {
      if (i === 0) { head = line; headLen = len; }
      if (!line.startsWith('{"type":"test"')) return;
      try { const t = JSON.parse(line); recs.push({ nodeid: t.nodeid, outcome: t.outcome }); } catch { recs.push({ nodeid: `<unreadable line ${recs.length}>`, outcome: 'unreadable' }); }
    });
  } catch {
    // no counts are invented for a trace that cannot be read (absent, a read error, a line over the limit): null,
    // and the caller records the run's status as unknown (exit 2)
    return null;
  }
  const status = exitStatus.countStatus(recs);
  if (head === null) head = '';
  const at = head.indexOf('"meta":{');
  if (head.startsWith('{"type":"header"') && at >= 0) {
    const i = at + '"meta":{'.length;
    const field = `"status":${JSON.stringify(status)}${head[i] === '}' ? '' : ','}`;
    // beside the real file (a --det-trace that is a symbolic link stays one), with its mode
    let real = tracePath;
    try { real = fs.realpathSync(tracePath); } catch { /* as given */ }
    const size = fs.statSync(real).size;
    // the raw header line ends with "\r" when the file's lines do: kept
    const cr = Buffer.byteLength(head, 'utf8') < headLen ? '\r' : '';
    // created exclusively (never through a file or link already at that name) and set up through its descriptor
    const tmp = `${real}.status-${process.pid}-${Date.now().toString(36)}`;
    let fd = null;
    try {
      let mode = 0o644;
      try { mode = fs.statSync(real).mode & 0o7777; } catch { /* default */ }
      fd = fs.openSync(tmp, 'wx', mode);
      // a trace of one line without "\n" stays one line without "\n"
      fs.writeSync(fd, `${head.slice(0, i)}${field}${head.slice(i)}${cr}${size > headLen ? '\n' : ''}`);
      if (size > headLen + 1) copyRange(real, headLen + 1, fd);
      fs.fchmodSync(fd, mode);
      fs.closeSync(fd);
      fd = null;
      fs.renameSync(tmp, real);
    } catch (e) {
      if (fd !== null) { try { fs.closeSync(fd); } catch { /* closed */ } }
      if (e && e.code !== 'EEXIST') { try { fs.rmSync(tmp, { force: true }); } catch { /* best effort */ } }
      throw new Error(`meta.status not written into ${tracePath}: ${e && e.message}`);
    }
  }
  return status;
}

/**
 * Whether this session prints the status line: only the process that writes the FINAL trace of the run does (B7).
 * Not a pass of the hazard re-run wrapper whose trace the wrapper replaces (src/parallel-rerun.js: pass 2 always,
 * pass 1 when it found a cross-worker hazard; with none, pass 1's trace is the final one -- appendix points 1, 2),
 * and not a per-test session of --det-isolate (src/isolate.js merges and prints).
 */
function printsStatus(meta, env = process.env) {
  if (env.DETJS_ISOLATE_CHILD === '1') return false;
  if (env.DETJS_HAZARD_RERUN === '1' && env.DETJS_HAZARD_PASS === '2') return false;
  if (env.DETJS_HAZARD_RERUN === '1' && env.DETJS_HAZARD_PASS === '1') {
    return require('./parallel-rerun').hazardFiles({ meta }).length === 0;
  }
  return true;
}

// OS entropy Level 0 only observes: crypto.randomBytes & co. without --det-urandom, native key generation always
const URANDOM_OPS = /^crypto\.(?:randomBytes|randomFillSync|randomFill|randomInt|pseudoRandomBytes)$/;
/** Tests of the merged trace that drew real OS entropy: [{nodeid, ops}] (G-1426: the default is never silent). */
function realEntropyTests(tracePath, urandom) {
  const out = [];
  // streamed (P0 big trace); a read error is thrown to the caller, which prints it
  require('./trace-lines').forEachLine(tracePath, (line) => {
    if (!line.startsWith('{"type":"test"') || !line.includes('"entropy"')) return;
    let t;
    try { t = JSON.parse(line); } catch { return; }
    const ops = new Set();
    for (const e of t.events || []) {
      if (e.s !== 'entropy') continue;
      if (urandom && URANDOM_OPS.test(e.o)) continue;
      ops.add(e.o);
    }
    if (!ops.size && t.counts && t.counts.entropy && !urandom && !(t.events || []).length) ops.add('entropy');
    if (ops.size) out.push({ nodeid: t.nodeid, ops: [...ops] });
  });
  return out;
}

module.exports = { realEntropyTests, parseArgs, resolveEpoch, traceEpochNs, prepare, header, finish, partIds, partOrder, stampStatus, printsStatus, HELP, VERSION };
