'use strict';
// Parallel `--det` runs (`--det-workers=N`, or the runner's own worker options): a fixed plan, lanes that follow it,
// and the detection of what placement can change (docs/NODE.md "Parallel").
//
// Main process (the runner's sequencer):
//   * the plan: which test files go to which lane (worker) and in which order, a pure function of the ordered file
//     list (detjs' order: sorted, or shuffled with the seed), the number of workers, the recorded file durations and
//     the previous plan (stickiness), and the together-edges learnt from earlier runs (files that touched the same
//     path or port from two lanes); the assignment is Rust's (`detpy_core::schedule::plan`, the planner of the
//     Python xdist path: LPT over atoms, ties by digest, sticky); every lane runs a subsequence of the serial order;
//   * the plan goes into the trace header (`meta.parallel.plan`); `--det-plan=TRACE|JSON` replays it;
//   * after the run: durations, observed placement (process, lane, in-process predecessors) against the plan,
//     cross-worker hazards (a path one lane wrote and another lane read, listed or wrote; a fixed port two lanes
//     used), state carried between files of one process; all reported (stderr, trace) and turned into cache flags.
// Test processes (`enter` / `leave`, called by the Vitest and Jest shells around each test file):
//   * a file waits until its lane predecessor has finished (lane exclusivity: one file of a lane at a time, in plan
//     order), and Vitest's `VITEST_POOL_ID` is set to the lane (Jest's `JEST_WORKER_ID` is the lane through the
//     worker binding in src/jest/cli.js);
//   * a marker per file: process, thread, real start/end, the files that ran before it in the same process, the
//     paths and ports it touched (parallel runs only) and the process-wide state it found changed by earlier files.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

// real clocks, taken before Level 0 replaces them in this process
const REAL_NOW = Date.now;
const now = () => REAL_NOW.call(Date);
const SLEEP = new Int32Array(new SharedArrayBuffer(4));
const sleep = (ms) => Atomics.wait(SLEEP, 0, 0, ms);

/** Environment variables whose value is the runner's placement of the process (worker or pool ids). */
const PLACEMENT_VARS = new Set(['JEST_WORKER_ID', 'VITEST_POOL_ID', 'VITEST_WORKER_ID', 'TEST_WORKER_INDEX', 'TEST_PARALLEL_INDEX']);

const STATE_VERSION = 1;
const TOLERANCE = 0.10;
const SLACK = 1.0;

function native() { return require('./native'); }
function stableName(label) { return native().digest(label).slice(0, 16); }

// -- options -------------------------------------------------------------------------------------------------------

/** `N`, `N%` (of the CPUs) or `auto` -> a worker count (null when absent or not a count). */
function workerCount(v) {
  if (v === undefined || v === null || v === true || v === '') return null;
  const cpus = typeof os.availableParallelism === 'function' ? os.availableParallelism() : os.cpus().length;
  const s = String(v).trim();
  if (s === 'auto') return Math.max(cpus, 1);
  const pct = /^(\d+(?:\.\d+)?)%$/.exec(s);
  if (pct) return Math.max(1, Math.floor((cpus * Number(pct[1])) / 100));
  const n = Number(s);
  if (!Number.isFinite(n) || n < 1) return null;
  return Math.floor(n);
}

/**
 * The number of workers of a `--det` run: `--det-workers` if given, else the runner's own worker option when the
 * user passed one on the command line (Vitest `--maxWorkers`, `--fileParallelism`; Jest `--maxWorkers`/`-w`), else 1
 * (serial, the default). `runner.serial`: the user asked for serial (`--runInBand`, `--no-file-parallelism`).
 */
function resolveWorkers(opts, runner) {
  if (opts.workers !== null && opts.workers !== undefined) {
    const n = workerCount(opts.workers);
    if (n === null) throw new Error(`detjs: --det-workers: expected N, N% or auto, got ${JSON.stringify(opts.workers)}`);
    return { workers: n, source: '--det-workers' };
  }
  if (runner.serial) return { workers: 1, source: runner.serialSource || 'runner option' };
  if (runner.workers && runner.workers > 1) return { workers: runner.workers, source: runner.source || 'runner option' };
  return { workers: 1, source: 'default' };
}

// -- state across runs -----------------------------------------------------------------------------------------------

function statePath(root) { return process.env.DETJS_PLAN_STATE || path.join(root, '.detjs', 'plan-state.json'); }

function loadState(root) {
  try {
    const s = JSON.parse(fs.readFileSync(statePath(root), 'utf8'));
    if (s && s.version === STATE_VERSION) return { durations: s.durations || {}, together: s.together || {}, previous: s.previous || {} };
  } catch { /* none */ }
  return { durations: {}, together: {}, previous: {} };
}

function saveState(root, s) {
  try {
    const p = statePath(root);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    const sorted = (o) => Object.fromEntries(Object.keys(o).sort().map((k) => [k, o[k]]));
    fs.writeFileSync(p, JSON.stringify({ version: STATE_VERSION, durations: sorted(s.durations), together: sorted(s.together), previous: s.previous }, null, 1));
  } catch { /* report only */ }
}

function median3(list) {
  const t = (list || []).slice(-3).filter((x) => typeof x === 'number' && x >= 0).sort((a, b) => a - b);
  if (!t.length) return null;
  return t.length % 2 ? t[(t.length - 1) / 2] : (t[t.length / 2 - 1] + t[t.length / 2]) / 2;
}

// -- the plan -----------------------------------------------------------------------------------------------------

/** A plan replayed from a trace (its header's `meta.parallel.plan`) or a plan JSON file. */
function readReplay(file) {
  const text = fs.readFileSync(file, 'utf8');
  let obj;
  try { obj = JSON.parse(text); } catch { obj = JSON.parse(text.split('\n', 1)[0]); }
  const p = (obj && obj.meta && obj.meta.parallel && obj.meta.parallel.plan) || (obj && obj.parallel && obj.parallel.plan) || (obj && obj.plan) || obj;
  if (!p || !Array.isArray(p.lanes)) throw new Error(`detjs: --det-plan: no plan (lanes) in ${file}`);
  return p;
}

/**
 * The plan for `keys` (file labels in the serial order) over `workers` lanes.
 * Returns { workers, lanes: [[label]], digest, inputs_digest, sticky, loads, makespan, lpt_makespan, costs_known,
 * groups (together-edges used), replayed, dispatch: [label] }.
 */
function makePlan(root, keysIn, workers, { replay = null } = {}) {
  const n = native();
  const keys = [...new Set(keysIn)];
  const state = loadState(root);
  const pos = new Map(keys.map((k, i) => [k, i]));
  const costOf = keys.map((k) => median3(state.durations[k]));
  const known = costOf.filter((c) => c !== null);
  let lanes;
  let out;
  let groups = [];
  if (replay) {
    const want = new Map();
    replay.lanes.forEach((l, i) => l.forEach((k) => want.set(k, i)));
    const w = Math.max(replay.lanes.length, 1);
    lanes = Array.from({ length: w }, () => []);
    const extra = [];
    for (const k of keys) { if (want.has(k)) lanes[want.get(k)].push(k); else extra.push(k); }
    // files the replayed plan does not know: the lane with the fewest files, in serial order
    for (const k of extra) { let b = 0; for (let i = 1; i < w; i++) if (lanes[i].length < lanes[b].length) b = i; lanes[b].push(k); }
    for (const l of lanes) l.sort((a, b) => pos.get(a) - pos.get(b));
    out = { digest: planDigest(lanes), sticky: false, kept: 0, loads: null, makespan: null, lpt_makespan: null, replayed: true, unknown_files: extra.length };
    workers = w;
  } else {
    // together-edges learnt from earlier runs: union-find over the files present
    const parent = new Map(keys.map((k) => [k, k]));
    const find = (k) => { while (parent.get(k) !== k) { parent.set(k, parent.get(parent.get(k))); k = parent.get(k); } return k; };
    for (const pair of Object.keys(state.together)) {
      const [a, b] = pair.split('\u0000');
      if (!parent.has(a) || !parent.has(b)) continue;
      const ra = find(a); const rb = find(b);
      if (ra === rb) continue;
      // the representative is the earlier file in the serial order (deterministic)
      if (pos.get(ra) < pos.get(rb)) parent.set(rb, ra); else parent.set(ra, rb);
      groups.push([a, b]);
    }
    groups = groups.sort();
    const atoms = keys.map((k) => `f:${find(k)}`);
    const prev = state.previous[String(workers)] || {};
    const res = JSON.parse(n.planLanes(keys, atoms, costOf, workers, JSON.stringify(prev), TOLERANCE, SLACK));
    lanes = res.lists.map((l) => l.map((i) => keys[i]));
    out = { digest: res.digest, sticky: res.sticky, kept: res.kept, loads: res.loads, makespan: res.makespan, lpt_makespan: res.lpt_makespan, atom_worker: res.atom_worker, replayed: false };
  }
  // the order files are handed to the runner: by planned start time (recorded durations; unknown = median), then lane,
  // so that a lane's next file is offered when its predecessor should be ending; a lane's files keep their order
  const dflt = known.length ? known.slice().sort((a, b) => a - b)[Math.floor(known.length / 2)] : 1;
  const starts = [];
  lanes.forEach((l, li) => {
    let t = 0;
    l.forEach((k, j) => { starts.push({ k, li, j, t }); t += Math.max(costOf[pos.get(k)] ?? dflt, 1e-6); });
  });
  starts.sort((a, b) => (a.t - b.t) || (a.li - b.li) || (a.j - b.j));
  const inputs = { keys, workers, costs: costOf, previous: replay ? null : state.previous[String(workers)] || null, together: groups, replay: replay ? planDigest(replay.lanes) : null };
  return {
    version: 1,
    workers,
    lanes,
    digest: out.digest,
    inputs_digest: n.digest(JSON.stringify(inputs)),
    costs: Object.fromEntries(keys.map((k, i) => [k, costOf[i]])),
    costs_known: known.length,
    sticky: out.sticky,
    kept: out.kept,
    loads: out.loads,
    makespan: out.makespan,
    lpt_makespan: out.lpt_makespan,
    atom_worker: out.atom_worker || null,
    together: groups,
    replayed: Boolean(out.replayed),
    unknown_files: out.unknown_files || 0,
    dispatch: starts.map((s) => s.k),
  };
}

function planDigest(lanes) {
  return native().digest(JSON.stringify(lanes));
}

/** Write the plan for the test processes (`<run dir>/plan.json`). */
function writeRunPlan(dir, plan, mode) {
  plan.mode = mode;
  const pred = {};
  const laneOf = {};
  plan.lanes.forEach((l, i) => l.forEach((k, j) => { laneOf[k] = i; pred[k] = j ? l[j - 1] : null; }));
  fs.mkdirSync(path.join(dir, 'lanes'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'plan.json'), JSON.stringify({ workers: plan.workers, laneOf, pred, mode, digest: plan.digest }));
}

// -- test processes ----------------------------------------------------------------------------------------------

const PROC = { run: [], plan: undefined, current: null, hazard: null, notes: [] };

function runPlan(dir) {
  if (PROC.plan === undefined || (PROC.plan && PROC.plan.dir !== dir)) {
    try { PROC.plan = { dir, ...JSON.parse(fs.readFileSync(path.join(dir, 'plan.json'), 'utf8')) }; } catch { PROC.plan = null; }
  }
  return PROC.plan;
}

function marker(dir, label, kind) { return path.join(dir, 'lanes', `${stableName(label)}.${kind}`); }

function alive(pid) {
  try { process.kill(pid, 0); return true; } catch (e) { return e && e.code === 'EPERM'; }
}

/**
 * Wait for the lane predecessor of `label` (if the run has a plan), then mark the file as started. Returns
 * { lane, waited, note }.
 */
function enter(label, { runner } = {}) {
  const dir = process.env.DETJS_DIR;
  if (!dir) return null;
  const plan = runPlan(dir);
  const info = { label, lane: null, waited: 0, note: null, start: 0 };
  if (plan && Object.prototype.hasOwnProperty.call(plan.laneOf, label)) {
    info.lane = plan.laneOf[label];
    const pred = plan.pred[label];
    if (pred) {
      const t0 = now();
      const done = marker(dir, pred, 'done');
      const started = marker(dir, pred, 'start');
      const waitMark = marker(dir, label, 'wait');
      let waitingSince = null;
      let stallSince = null;
      const max = Number(process.env.DETJS_LANE_WAIT_MS || 30 * 60 * 1000);
      while (!fs.existsSync(done)) {
        if (waitingSince === null) { waitingSince = now(); try { fs.writeFileSync(waitMark, String(process.pid)); } catch { /* ignore */ } }
        let ms = 2;
        const el = now() - t0;
        if (el > 50) ms = 10;
        if (el > 1000) ms = 25;
        sleep(ms);
        if (el < 1000) continue;
        // a predecessor that started in another process which has died: it will never finish
        let st = null;
        try { st = JSON.parse(fs.readFileSync(started, 'utf8')); } catch { st = null; }
        if (st && st.pid !== process.pid && !alive(st.pid)) { info.note = `lane predecessor ${pred} died (process ${st.pid})`; break; }
        // every worker slot waits for a file the runner has not started: the runner's dispatch order differs from
        // the plan (a stall); go on and report it
        if (!st) {
          let waiting = 0;
          try { waiting = fs.readdirSync(path.join(dir, 'lanes')).filter((f) => f.endsWith('.wait')).length; } catch { waiting = 0; }
          if (waiting >= plan.workers) {
            if (stallSince === null) stallSince = now();
            else if (now() - stallSince > 5000) { info.note = `lane order broken: every worker waited for ${pred}, which the runner had not started (its dispatch order differs from the plan)`; break; }
          } else stallSince = null;
        }
        if (el > max) { info.note = `lane predecessor ${pred} did not finish within ${max} ms`; break; }
      }
      if (waitingSince !== null) { try { fs.rmSync(waitMark, { force: true }); } catch { /* ignore */ } }
      info.waited = now() - t0;
    }
    if (runner === 'vitest') {
      // the pool id is the lane (unique among files running at the same time, as Vitest's own)
      process.env.VITEST_POOL_ID = String(info.lane + 1);
    }
  }
  info.start = now();
  info.preds = PROC.run.slice();
  try {
    fs.mkdirSync(path.join(dir, 'lanes'), { recursive: true });
    fs.writeFileSync(marker(dir, label, 'start'), JSON.stringify({ pid: process.pid, thread: require('node:worker_threads').threadId }));
  } catch { /* ignore */ }
  PROC.current = info;
  if (PROC.hazard) PROC.hazard.begin(label);
  if (info.note) process.stderr.write(`detjs: WARNING ${label}: ${info.note}\n`);
  return info;
}

/** A variable read for detjs itself: not an input of the running test (the cache capture is told to look away). */
function ownEnv(name) {
  const capFile = require.resolve('./cache/capture');
  const cap = require.cache[capFile] ? require.cache[capFile].exports.CAPTURE : null;
  if (cap) cap.busy++;
  try { return process.env[name] || null; } finally { if (cap) cap.busy--; }
}

/** Mark the file as finished (`extra`: carried state found, ...). */
function leave(label, extra = {}) {
  const dir = process.env.DETJS_DIR;
  if (!dir) return;
  const info = PROC.current && PROC.current.label === label ? PROC.current : { label, lane: null, waited: 0, note: null, start: now(), preds: PROC.run.slice() };
  PROC.current = null;
  const fp = PROC.hazard ? PROC.hazard.end(label) : null;
  const rec = {
    label, lane: info.lane, pid: process.pid, thread: require('node:worker_threads').threadId,
    start: info.start, end: now(), waited: info.waited, preds: info.preds, note: info.note,
    pool_id: ownEnv('VITEST_POOL_ID'), jest_worker_id: ownEnv('JEST_WORKER_ID'),
    footprint: fp, ...extra,
  };
  PROC.run.push(label);
  try {
    fs.mkdirSync(path.join(dir, 'lanes'), { recursive: true });
    fs.writeFileSync(marker(dir, label, 'json'), JSON.stringify(rec));
    fs.writeFileSync(marker(dir, label, 'done'), '');
  } catch { /* ignore */ }
}

/** The main process marks a file finished when its runner reports it final (a worker that died never does). */
function markDone(dir, label) {
  try { const d = marker(dir, label, 'done'); if (!fs.existsSync(d)) fs.writeFileSync(d, 'main'); } catch { /* ignore */ }
}

// -- footprints: paths and ports a test file touched (parallel runs) ------------------------------------------------

function toPath(p) {
  if (p === undefined || p === null || typeof p === 'number') return null;
  let s;
  if (typeof p === 'string') s = p;
  else if (Buffer.isBuffer(p)) s = p.toString('utf8');
  else if (p instanceof URL || (typeof p === 'object' && typeof p.href === 'string')) {
    if (p.protocol !== 'file:') return null;
    try { s = require('node:url').fileURLToPath(p.href); } catch { return null; }
  } else return null;
  if (!s) return null;
  if (s.startsWith('file://')) { try { s = require('node:url').fileURLToPath(s); } catch { return null; } }
  return path.resolve(s);
}

const WRITE_FLAGS = /[wax+]/;

/** Directories of runner caches the footprint leaves out (inherited by the test processes). */
function skipDirs(dirs) {
  const cur = (process.env.DETJS_FOOTPRINT_SKIP_DIRS || '').split(path.delimiter).filter(Boolean);
  for (const d of dirs) if (typeof d === 'string' && d && !cur.includes(d)) cur.push(d);
  process.env.DETJS_FOOTPRINT_SKIP_DIRS = cur.join(path.delimiter);
}

/** Install the footprint recorder in this process (once): fs reads, listings, writes; fixed ports. */
function installFootprint(root) {
  if (PROC.hazard) return;
  const rootSep = path.resolve(root) + path.sep;
  // runner and tool caches whose content is a function of their key (Jest's cacheDirectory, Vite's cacheDir and
  // temporary directories: set by the shells; jiti, tsx, swc-node, v8-compile-cache): every lane writes and reads them
  const tmp = os.tmpdir();
  const uid = typeof process.getuid === 'function' ? process.getuid() : '';
  const skip = [...(process.env.DETJS_CACHE_SKIP_DIRS || '').split(path.delimiter), ...(process.env.DETJS_FOOTPRINT_SKIP_DIRS || '').split(path.delimiter),
    path.join(tmp, 'jiti'), path.join(tmp, 'node-jiti'), path.join(tmp, `tsx-${uid}`), path.join(tmp, `v8-compile-cache-${uid}`),
    path.join(tmp, 'v8-compile-cache'), path.join(tmp, `swc-node-${uid}`)].filter(Boolean).map((d) => path.resolve(d) + path.sep);
  const keyOf = (abs) => {
    if (abs.startsWith('/proc/') || abs.startsWith('/dev/') || abs.startsWith('/sys/')) return null;
    if (abs.includes(`${path.sep}node_modules${path.sep}`) || abs.endsWith(`${path.sep}node_modules`)) return null;
    for (const d of skip) if (abs.startsWith(d)) return null;
    if (abs.startsWith(rootSep)) {
      const r = abs.slice(rootSep.length).split(path.sep).join('/');
      if (r === '.detjs' || r.startsWith('.detjs/') || r.startsWith('coverage/')) return null;
      return r;
    }
    return abs;
  };
  let cur = null;
  const H = {
    begin(label) { cur = { label, w: new Set(), r: new Set(), l: new Set(), listen: new Set(), connect: new Set() }; },
    end(label) {
      if (!cur || cur.label !== label) return null;
      const c = cur; cur = null;
      return { w: [...c.w].sort(), r: [...c.r].sort(), l: [...c.l].sort(), listen: [...c.listen].sort(), connect: [...c.connect].sort() };
    },
    add(set, p) {
      if (!cur) return;
      const abs = toPath(p);
      if (abs === null) return;
      const k = keyOf(abs);
      if (k !== null) cur[set].add(k);
    },
  };
  PROC.hazard = H;
  const wrap = (obj, name, fn) => {
    const real = obj && obj[name];
    if (typeof real !== 'function' || real.__detjsFootprint) return;
    const w = function (...a) { if (cur) { try { fn(a); } catch { /* never break the call */ } } return real.apply(this, a); };
    for (const k of Reflect.ownKeys(real)) {
      if (k === 'length' || k === 'name' || k === 'prototype' || k === 'arguments' || k === 'caller') continue;
      try { Object.defineProperty(w, k, Object.getOwnPropertyDescriptor(real, k)); } catch { /* ignore */ }
    }
    Object.defineProperty(w, '__detjsFootprint', { value: true });
    // the cache capture must not wrap it again on every file (Jest reinstalls): it already sits below
    Object.defineProperty(w, '__detjsCache', { value: true });
    Object.defineProperty(w, 'name', { value: real.name, configurable: true });
    try { obj[name] = w; } catch { /* read-only */ }
  };
  const P = fs.promises;
  const r0 = (a) => H.add('r', a[0]);
  const w0 = (a) => H.add('w', a[0]);
  const w1 = (a) => H.add('w', a[1]);
  const l0 = (a) => H.add('l', a[0]);
  const open = (a) => { const f = a[1]; if (f !== undefined && f !== null && (typeof f === 'number' ? (f & 3) !== 0 || (f & fs.constants.O_CREAT) : WRITE_FLAGS.test(String(f)))) H.add('w', a[0]); else H.add('r', a[0]); };
  for (const o of [fs, P]) {
    for (const n of ['readFile', 'readFileSync', 'createReadStream', 'exists', 'existsSync', 'stat', 'statSync', 'lstat', 'lstatSync', 'access', 'accessSync', 'readlink', 'readlinkSync', 'realpath', 'realpathSync', 'openAsBlob']) wrap(o, n, r0);
    for (const n of ['readdir', 'readdirSync', 'opendir', 'opendirSync']) wrap(o, n, l0);
    for (const n of ['writeFile', 'writeFileSync', 'appendFile', 'appendFileSync', 'createWriteStream', 'mkdir', 'mkdirSync', 'rm', 'rmSync', 'rmdir', 'rmdirSync', 'unlink', 'unlinkSync', 'truncate', 'truncateSync', 'chmod', 'chmodSync', 'utimes', 'utimesSync', 'lchown', 'chown', 'chownSync']) wrap(o, n, w0);
    for (const n of ['rename', 'renameSync']) wrap(o, n, (a) => { H.add('w', a[0]); H.add('w', a[1]); H.add('r', a[0]); });
    for (const n of ['copyFile', 'copyFileSync', 'cp', 'cpSync']) wrap(o, n, (a) => { H.add('r', a[0]); H.add('w', a[1]); });
    for (const n of ['symlink', 'symlinkSync', 'link', 'linkSync']) wrap(o, n, w1);
    for (const n of ['open', 'openSync']) wrap(o, n, open);
  }
  const net = require('node:net');
  const SP = net.Server && net.Server.prototype;
  const portOf = (a) => {
    const x = a[0];
    if (typeof x === 'number' || (typeof x === 'string' && /^\d+$/.test(x))) return Number(x);
    if (x && typeof x === 'object' && x.port !== undefined && /^\d+$/.test(String(x.port))) return Number(x.port);
    return null;
  };
  if (SP) wrap(SP, 'listen', (a) => { const p = portOf(a); if (cur && p) cur.listen.add(String(p)); });
  const SockP = net.Socket && net.Socket.prototype;
  if (SockP) {
    wrap(SockP, 'connect', (a) => {
      let o = a[0];
      if (Array.isArray(o)) o = o[0];
      let port = null; let host = 'localhost';
      if (o && typeof o === 'object') { port = o.port; host = o.host || 'localhost'; } else if (o !== undefined) { port = o; host = typeof a[1] === 'string' ? a[1] : 'localhost'; }
      if (cur && port && /^(localhost|127\.|::1$|0\.0\.0\.0$)/.test(String(host))) cur.connect.add(String(port));
    });
  }
  require('node:module').syncBuiltinESMExports();
}

// -- state carried between files of one process (Jest: a worker or the in-band process runs many files) -------------

const SHARED_MODULES = ['fs', 'fs/promises', 'path', 'os', 'http', 'https', 'http2', 'net', 'tls', 'dns', 'child_process', 'crypto', 'util',
  'events', 'stream', 'url', 'zlib', 'module', 'timers', 'worker_threads', 'buffer', 'readline', 'string_decoder', 'querystring', 'assert'];

function snapshotShared() {
  const snap = new Map();
  for (const m of SHARED_MODULES) {
    let mod;
    try { mod = require(`node:${m}`); } catch { continue; }
    for (const k of Reflect.ownKeys(mod)) {
      if (typeof k !== 'string') continue;
      let v;
      try { const d = Object.getOwnPropertyDescriptor(mod, k); v = d && ('value' in d ? d.value : d.get); } catch { continue; }
      if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
        // one level into plain objects (http.globalAgent options, fs.constants are frozen)
        snap.set(`${m}.${k}`, v);
        if (Object.getPrototypeOf(v) === Object.prototype || k === 'globalAgent') {
          for (const k2 of Object.keys(v)) { try { snap.set(`${m}.${k}.${k2}`, v[k2]); } catch { /* ignore */ } }
        }
      } else snap.set(`${m}.${k}`, v);
    }
  }
  for (const k of Object.getOwnPropertyNames(globalThis)) {
    try { const d = Object.getOwnPropertyDescriptor(globalThis, k); snap.set(`globalThis.${k}`, d && ('value' in d ? d.value : d.get)); } catch { /* ignore */ }
  }
  for (const k of ['umask', 'cwd', 'emitWarning', 'nextTick', 'exit', 'on', 'emit']) { try { snap.set(`process.${k}`, process[k]); } catch { /* ignore */ } }
  try { snap.set('process.cwd()', process.cwd()); } catch { /* ignore */ }
  // (Error.prepareStackTrace is not compared: Jest's source-map support installs its own on every test file)
  return snap;
}

/** A function detjs itself installed (its wrappers carry a `__detjs*` marker): wrapping again is not a leak. */
function ownWrapper(v) {
  if (typeof v !== 'function') return false;
  try { return Reflect.ownKeys(v).some((k) => typeof k === 'string' && k.startsWith('__detjs')); } catch { return false; }
}

function diffShared(a, b) {
  const out = [];
  for (const [k, v] of b) if (!a.has(k) || !Object.is(a.get(k), v)) { if (!(a.has(k) && ownWrapper(v) && (ownWrapper(a.get(k)) || typeof a.get(k) === 'function'))) out.push(k); }
  for (const k of a.keys()) if (!b.has(k)) out.push(k);
  return out;
}

const CARRY = { base: null, changedBy: new Map() /* key -> label that changed it */ };

/**
 * Before a file runs in a process that runs several files: the process-wide state that earlier files of this
 * process changed and that is still changed now (Node's shared modules, the process's global object, the working
 * directory, `Error.prepareStackTrace`). Returns [{key, by}] and takes the file's own baseline.
 */
function carriedBefore() {
  const snap = snapshotShared();
  const out = [];
  if (CARRY.base) {
    // a value an earlier file changed is carried until it is the baseline's again (detjs re-wrapping a user's
    // replacement at the next file start does not hide it: compared by identity, not filtered)
    for (const [k, by] of CARRY.changedBy) {
      if (!(CARRY.base.has(k) && snap.has(k) && Object.is(CARRY.base.get(k), snap.get(k)))) out.push({ key: k, by });
    }
    out.sort((x, y) => (x.key < y.key ? -1 : x.key > y.key ? 1 : 0));
  } else {
    CARRY.base = snap;
  }
  CARRY.before = snap;
  return out;
}

/** After the file: the state it left changed (recorded against the process baseline). */
function carriedAfter(label) {
  if (!CARRY.before) return [];
  const snap = snapshotShared();
  const changed = diffShared(CARRY.before, snap);
  for (const k of changed) if (!CARRY.base.has(k) || !Object.is(CARRY.base.get(k), snap.get(k))) CARRY.changedBy.set(k, label);
  CARRY.before = null;
  return changed;
}

// -- after the run (main process) -----------------------------------------------------------------------------------

function readMarkers(dir) {
  const out = new Map();
  let names = [];
  try { names = fs.readdirSync(path.join(dir, 'lanes')).filter((n) => n.endsWith('.json')).sort(); } catch { return out; }
  for (const n of names) {
    try { const m = JSON.parse(fs.readFileSync(path.join(dir, 'lanes', n), 'utf8')); out.set(m.label, m); } catch { /* truncated */ }
  }
  return out;
}

/** Cross-lane hazards between files of different lanes, from their footprints. */
function hazards(markers, laneOf) {
  const writers = new Map();
  const listeners = new Map();
  for (const [label, m] of markers) {
    const f = m.footprint;
    if (!f) continue;
    for (const w of f.w) { if (!writers.has(w)) writers.set(w, []); writers.get(w).push(label); }
    for (const p of f.listen) { if (!listeners.has(p)) listeners.set(p, []); listeners.get(p).push(label); }
  }
  const out = new Map(); // "a\0b" -> {a, b, kind, what}
  const lane = (l) => (laneOf.has(l) ? laneOf.get(l) : null);
  const addH = (a, b, kind, what) => {
    if (a === b) return;
    const la = lane(a); const lb = lane(b);
    if (la === null || lb === null || la === lb) return;
    const [x, y] = a < b ? [a, b] : [b, a];
    const k = `${x}\u0000${y}`;
    if (!out.has(k)) out.set(k, { a: x, b: y, kind, what });
  };
  for (const [label, m] of markers) {
    const f = m.footprint;
    if (!f) continue;
    for (const r of f.r) for (const w of writers.get(r) || []) addH(label, w, 'read-write', r);
    for (const r of f.w) for (const w of writers.get(r) || []) addH(label, w, 'write-write', r);
    for (const d of f.l) {
      const pre = d.endsWith('/') ? d : `${d}/`;
      for (const [p, ws] of writers) if (p.startsWith(pre) && !p.slice(pre.length).includes('/')) for (const w of ws) addH(label, w, 'list-write', d);
    }
    for (const p of f.listen) for (const o of listeners.get(p) || []) addH(label, o, 'port', p);
    for (const p of f.connect) for (const o of listeners.get(p) || []) addH(label, o, 'port', p);
  }
  return [...out.values()].sort((x, y) => (x.a < y.a ? -1 : x.a > y.a ? 1 : x.b < y.b ? -1 : x.b > y.b ? 1 : 0));
}

/** Real start and end of each file (ms after the first start): how the lanes overlapped. */
function spansOf(markers, keys) {
  const ms = keys.map((k) => markers.get(k)).filter((m) => m && typeof m.start === 'number');
  const t0 = Math.min(...ms.map((m) => m.start));
  return Object.fromEntries(ms.map((m) => [m.label, [m.start - t0, m.end - t0]]));
}

/**
 * After the run: read the markers, compare placement with the plan, find hazards, update the state, and return
 * { meta, lines, flags: Map(label -> [flag, detail]) } (flags: what makes a file's results not cacheable).
 * `keys`: the files that ran, serial order; `plan`: null for a serial run; `shared`: files of one lane share a process
 * (Jest workers; Vitest isolate=false); `planned`: what the run was asked for ({workers, source, refused}).
 */
function collect(root, dir, keysIn, plan, { shared, planned, write = true } = {}) {
  const keys = [...new Set(keysIn)];
  const markers = readMarkers(dir);
  const state = loadState(root);
  const lines = [];
  const flags = new Map();
  for (const [label, m] of markers) {
    if (typeof m.start === 'number' && typeof m.end === 'number' && m.end >= m.start) {
      const dur = Math.round(m.end - m.start) / 1000;
      state.durations[label] = [...(state.durations[label] || []), dur].slice(-3);
    }
  }
  const carried = [];
  for (const [label, m] of markers) {
    if (m.carried && m.carried.length) {
      carried.push({ file: label, state: m.carried });
      flags.set(label, ['carried', `${m.carried.slice(0, 3).map((c) => `${c.key} changed by ${c.by}`).join('; ')}${m.carried.length > 3 ? ` (+${m.carried.length - 3})` : ''}`]);
    }
  }
  const meta = { workers: plan ? plan.workers : 1, requested: planned || null };
  if (plan) {
    const laneOf = new Map();
    plan.lanes.forEach((l, i) => l.forEach((k) => laneOf.set(k, i)));
    const deviations = [];
    const procs = new Map();
    for (const k of keys) {
      const m = markers.get(k);
      if (!m) { deviations.push({ file: k, what: 'no marker (the file did not run or its process died)' }); continue; }
      const p = `${m.pid}:${m.thread}`;
      if (!procs.has(p)) procs.set(p, []);
      procs.get(p).push(k);
      const lane = laneOf.get(k);
      const l = plan.lanes[lane];
      const planPreds = shared ? l.slice(0, l.indexOf(k)) : [];
      const same = planPreds.length === (m.preds || []).length && planPreds.every((x, i) => x === m.preds[i]);
      if (!same) deviations.push({ file: k, what: `in-process predecessors ${JSON.stringify(m.preds)} differ from the plan's ${JSON.stringify(planPreds)}` });
      if (m.note) deviations.push({ file: k, what: m.note });
      if (m.pool_id && plan.mode === 'vitest' && String(lane + 1) !== m.pool_id) deviations.push({ file: k, what: `VITEST_POOL_ID ${m.pool_id}, planned lane ${lane + 1}` });
      if (m.jest_worker_id && plan.mode === 'jest-workers' && String(lane + 1) !== m.jest_worker_id) deviations.push({ file: k, what: `JEST_WORKER_ID ${m.jest_worker_id}, planned lane ${lane + 1}` });
    }
    const hz = hazards(markers, laneOf);
    for (const h of hz) {
      const d = `${h.kind} ${h.what}: ${h.a} (lane ${laneOf.get(h.a) + 1}) and ${h.b} (lane ${laneOf.get(h.b) + 1})`;
      for (const f of [h.a, h.b]) if (!flags.has(f) || flags.get(f)[0] !== 'cross-worker') flags.set(f, ['cross-worker', d]);
      state.together[`${h.a}\u0000${h.b}`] = `${h.kind} ${h.what}`;
    }
    if (!plan.replayed && plan.atom_worker) state.previous[String(plan.workers)] = plan.atom_worker;
    const waited = [...markers.values()].reduce((a, m) => a + (m.waited || 0), 0) / 1000;
    Object.assign(meta, {
      plan: {
        workers: plan.workers, lanes: plan.lanes, digest: plan.digest, inputs_digest: plan.inputs_digest, costs: plan.costs,
        costs_known: plan.costs_known, sticky: plan.sticky, loads: plan.loads, makespan: plan.makespan, lpt_makespan: plan.lpt_makespan,
        together: plan.together, replayed: plan.replayed, dispatch: plan.dispatch, mode: plan.mode, shared_process: Boolean(shared),
      },
      placement: { processes: [...procs.values()], deviations, waited_seconds: Math.round(waited * 1000) / 1000, spans: spansOf(markers, keys) },
      hazards: hz,
    });
    lines.push(`detjs: parallel: ${plan.workers} lanes, plan ${plan.digest}${plan.replayed ? ' (replayed)' : plan.sticky ? ' (sticky)' : ''}; `
      + `${keys.length} files; ${deviations.length} placement deviations; ${hz.length} cross-worker hazards; ${carried.length} files with carried state`);
    for (const d of deviations.slice(0, 20)) lines.push(`detjs: PLACEMENT ${d.file}: ${d.what}`);
    for (const h of hz.slice(0, 20)) lines.push(`detjs: CROSS-WORKER ${h.kind} ${h.what}: ${h.a} (lane ${laneOf.get(h.a) + 1}) / ${h.b} (lane ${laneOf.get(h.b) + 1}); the next plan puts them in one lane`);
  }
  if (carried.length) meta.carried = carried;
  // what serial costs, shown to the user (audit G-1458): the test-file time of this run, and the same files over the
  // machine's CPUs with a plan over these durations (ESTIMATED); for a parallel run, the lanes' wall time
  try {
    const durs = keys.map((k) => markers.get(k)).filter((m) => m && typeof m.start === 'number').map((m) => [m.label, Math.max(0, m.end - m.start) / 1000]);
    const total = durs.reduce((a, [, d]) => a + d, 0);
    const r3 = (x) => Math.round(x * 1000) / 1000;
    if (durs.length) {
      const cpus = workerCount('auto');
      if (!plan) {
        let est = null;
        if (cpus > 1 && durs.length > 1) {
          const p = JSON.parse(native().planLanes(durs.map(([k]) => k), durs.map(([k]) => `f:${k}`), durs.map(([, d]) => d), cpus, '', TOLERANCE, SLACK));
          est = p.makespan;
        }
        meta.timing = { files: durs.length, test_file_seconds: r3(total), workers_estimate: cpus, estimated_lanes_seconds: est === null ? null : r3(est) };
        if (est !== null && total > 0) {
          lines.push(`detjs: serial run: ${durs.length} files, ${r3(total)} s of test-file time (MEASURED); with --det-workers=${cpus} (this machine's CPUs) about ${r3(est)} s (ESTIMATED: a plan over these durations, worker start-up not counted)`);
        }
      } else {
        const t0 = Math.min(...keys.map((k) => markers.get(k)).filter(Boolean).map((m) => m.start));
        const t1 = Math.max(...keys.map((k) => markers.get(k)).filter(Boolean).map((m) => m.end));
        meta.timing = { files: durs.length, test_file_seconds: r3(total), lanes_wall_seconds: r3((t1 - t0) / 1000) };
        lines.push(`detjs: parallel: ${r3(total)} s of test-file time ran in ${r3((t1 - t0) / 1000)} s across ${plan.workers} lanes (MEASURED, first file start to last file end, worker start-up included)`);
      }
    }
  } catch { /* report only */ }
  for (const c of carried.slice(0, 20)) lines.push(`detjs: CARRIED STATE ${c.file}: ${c.state.slice(0, 3).map((s) => `${s.key} (changed by ${s.by})`).join(', ')}${c.state.length > 3 ? ` +${c.state.length - 3}` : ''}`);
  if (write) saveState(root, state);
  return { meta, lines, flags };
}

module.exports = {
  PLACEMENT_VARS, workerCount, resolveWorkers, makePlan, readReplay, writeRunPlan, enter, leave, markDone, installFootprint, skipDirs,
  carriedBefore, carriedAfter, collect, loadState, statePath, hazards,
};
