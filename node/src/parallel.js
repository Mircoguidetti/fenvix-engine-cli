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
 * The number of workers of a `--det` run, in precedence order:
 *   1. `--det-workers=N|N%|auto`, always;
 *   2. the user's own serial request (`--runInBand`, `--no-file-parallelism`, `-w 1`, `--test-concurrency=1`): 1 lane;
 *   3. the runner's own worker option when the user passed one on the command line (Vitest `--maxWorkers`,
 *      `--fileParallelism`; Jest `--maxWorkers`/`-w`; node:test `--test-concurrency`);
 *   4. otherwise this machine's CPUs (row JS-07, gap G-1044: `--det` is parallel by default).
 *
 * (4) is a default, not a promise that the run WILL be parallel: the caller still refuses parallel lanes for any
 * configuration where placement could decide what a test observes (a worker shared by several files, browser mode,
 * the vm pools, `isolate=false`, network recording, a custom Jest runner, `--detectOpenHandles`), and falls back to
 * one lane. Founder rule: the refusal is the safe side, so it is never skipped to gain a default.
 *
 * `runner.serial`: the user asked for serial. `runner.workers === 1`: the user asked for one worker by number, which
 * is the same request and must not be read as "said nothing".
 */
function resolveWorkers(opts, runner) {
  if (opts.workers !== null && opts.workers !== undefined) {
    const n = workerCount(opts.workers);
    if (n === null) throw new Error(`detjs: --det-workers: expected N, N% or auto, got ${JSON.stringify(opts.workers)}`);
    return { workers: n, source: '--det-workers' };
  }
  if (runner.serial) return { workers: 1, source: runner.serialSource || 'runner option' };
  if (runner.workers === 1) return { workers: 1, source: runner.source || 'runner option' };
  if (runner.workers && runner.workers > 1) return { workers: runner.workers, source: runner.source || 'runner option' };
  return { workers: defaultWorkers(), source: "default (this machine's CPUs)" };
}

/** The default lane count of a `--det` run with no worker option: this machine's usable CPUs (>= 1). */
function defaultWorkers() {
  const n = workerCount('auto');
  return n === null ? 1 : Math.max(1, n);
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

/** The real path of `d` (symlinks resolved); a path that does not exist: its nearest existing ancestor's real path + the rest. */
function realDir(d) {
  try { return fs.realpathSync.native(d); } catch {
    const parent = path.dirname(d);
    return parent === d ? d : path.join(realDir(parent), path.basename(d));
  }
}

const isUnder = (p, d) => p === d || p.startsWith(d.endsWith(path.sep) ? d : d + path.sep);

/** Every directory the footprint would leave out: runner and tool caches set by the shells or the environment. */
function footprintSkipCandidates() {
  const tmp = os.tmpdir();
  const uid = typeof process.getuid === 'function' ? process.getuid() : '';
  return [...(process.env.DETJS_CACHE_SKIP_DIRS || '').split(path.delimiter), ...(process.env.DETJS_FOOTPRINT_SKIP_DIRS || '').split(path.delimiter),
    path.join(tmp, 'jiti'), path.join(tmp, 'node-jiti'), path.join(tmp, `tsx-${uid}`), path.join(tmp, `v8-compile-cache-${uid}`),
    path.join(tmp, 'v8-compile-cache'), path.join(tmp, `swc-node-${uid}`)].filter(Boolean);
}

/**
 * Which candidate skip dirs the footprint honours (spec parallel-proof-gaps (c), gate note 3): a dir is left out of
 * the footprint ONLY if it lies under a `node_modules/` directory or strictly under `os.tmpdir()` outside the project,
 * and never if it is the project root or contains it. Any other location (the root, a parent, an in-repo `.cache/`,
 * `fixtures/`, `test-data/`) is ignored -- its paths are recorded like any others -- and listed with the reason.
 * Relative dirs resolve against `root`. Returns { skip: [real dir + sep], ignored: [{dir, reason}] }.
 * (The test file list is not available in the lanes' processes when the recorder is installed, so the location rule
 * alone applies, as gate note 8 allows; every test file of the run lies under the root, which is never skipped.)
 */
function footprintSkip(root, dirs) {
  const rootR = realDir(path.resolve(root));
  const tmpR = realDir(os.tmpdir());
  const skip = []; const ignored = []; const seen = new Set();
  for (const d0 of dirs) {
    if (typeof d0 !== 'string' || !d0) continue;
    const d = realDir(path.resolve(rootR, d0));
    if (seen.has(d)) continue;
    seen.add(d);
    let reason = null;
    if (isUnder(rootR, d)) reason = 'contains the project root';
    else if (!(d.split(path.sep).includes('node_modules') || (d !== tmpR && isUnder(d, tmpR) && !isUnder(d, rootR)))) reason = 'outside node_modules and tmpdir';
    if (reason) ignored.push({ dir: d, reason }); else skip.push(d + path.sep);
  }
  return { skip, ignored };
}

/** Install the footprint recorder in this process (once): fs reads, listings, writes; fixed ports. */
function installFootprint(root) {
  if (PROC.hazard) return;
  // keys are real paths (gate note 7): `path.resolve`, then the real path of the parent directory (memoized) + the
  // name; under the (real) root they are root-relative with `/` separators (the root itself is '.'), else absolute
  const rootR = realDir(path.resolve(root));
  const rootSep = rootR + path.sep;
  // runner and tool caches whose content is a function of their key (Jest's cacheDirectory, Vite's cacheDir and
  // temporary directories: set by the shells; jiti, tsx, swc-node, v8-compile-cache): every lane writes and reads them.
  // Only those under node_modules or the temporary directory are left out (footprintSkip).
  const { skip } = footprintSkip(rootR, footprintSkipCandidates());
  const dirMemo = new Map();
  const realOf = (abs) => {
    const dir = path.dirname(abs);
    if (dir === abs) return abs;
    let r = dirMemo.get(dir);
    if (r === undefined) { r = realDir(dir); if (dirMemo.size > 50000) dirMemo.clear(); dirMemo.set(dir, r); }
    return path.join(r, path.basename(abs));
  };
  const nm = (abs) => abs.includes(`${path.sep}node_modules${path.sep}`) || abs.endsWith(`${path.sep}node_modules`);
  const keyOf = (abs0) => {
    if (abs0.startsWith('/proc/') || abs0.startsWith('/dev/') || abs0.startsWith('/sys/')) return null;
    if (nm(abs0)) return null;
    const abs = realOf(abs0);
    if (abs !== abs0 && (nm(abs) || abs.startsWith('/proc/') || abs.startsWith('/dev/') || abs.startsWith('/sys/'))) return null;
    for (const d of skip) if (abs.startsWith(d)) return null;
    if (abs === rootR) return '.';
    if (abs.startsWith(rootSep)) {
      const r = abs.slice(rootSep.length).split(path.sep).join('/');
      if (r === '.detjs' || r.startsWith('.detjs/') || r.startsWith('coverage/')) return null;
      return r;
    }
    return abs;
  };
  let cur = null;
  const H = {
    begin(label) { cur = { label, w: new Set(), r: new Set(), l: new Set(), wr: new Set(), lr: new Set(), listen: new Set(), connect: new Set() }; },
    end(label) {
      if (!cur || cur.label !== label) return null;
      const c = cur; cur = null;
      return { w: [...c.w].sort(), r: [...c.r].sort(), l: [...c.l].sort(), wr: [...c.wr].sort(), lr: [...c.lr].sort(), listen: [...c.listen].sort(), connect: [...c.connect].sort() };
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
  // recursive operations (spec parallel-proof-gaps (b)): the target of a recursive rm / rmdir, the first directory a
  // recursive mkdir creates (below), the destination
  // of a recursive cp and both paths of a directory rename are recursive WRITE roots (`wr`): they conflict with every
  // key of another lane inside them and with listings of their ancestors; the source of a recursive cp and a recursive
  // readdir / opendir are recursive READ roots (`lr`): they conflict with every write of another lane inside them.
  // The plain keys are kept. DETJS_HAZARD_RECURSIVE=0 turns the roots off (measurement only; the runner gives no proof).
  const recursive = process.env.DETJS_HAZARD_RECURSIVE !== '0';
  const rec = (o) => Boolean(o && typeof o === 'object' && o.recursive);
  const lstat = fs.lstatSync;
  const isDir = (p) => { const x = toPath(p); if (x === null) return false; try { const st = lstat(x, { throwIfNoEntry: false }); return Boolean(st && st.isDirectory()); } catch { return false; } };
  const wRec = (a) => { H.add('w', a[0]); if (recursive && rec(a[1])) H.add('wr', a[0]); };
  // a recursive mkdir creates only the missing directories of its path: its root is the first of them (the nearest
  // missing ancestor of the target, checked before the call); when the target exists it creates nothing and has no
  // root (founder decision 2026-11-25, D1 = A: mkdir -p of /tmp, the tmpdir or the project root sent whole suites to
  // the one-lane re-run). A path component that cannot be checked counts as missing (a higher root: more hazards).
  const firstMissing = (p) => {
    let x = toPath(p);
    if (x === null) return null;
    x = path.resolve(x);
    let missing = null;
    for (;;) {
      let st = null;
      try { st = lstat(x, { throwIfNoEntry: false }); } catch { st = null; }
      if (st) return missing;
      missing = x;
      const up = path.dirname(x);
      if (up === x) return missing;
      x = up;
    }
  };
  // mkdir (recursive or not) writes only the directories it creates: a target that exists before the call is a READ
  // of it (the call observes it: EEXIST, or nothing to do), so files that each make sure one shared parent exists and
  // then create distinct children do not conflict on the parent (founder decision 2026-11-26, D2 = A; P2 BREAKDOWN C1)
  const exists = (p) => { const x = toPath(p); if (x === null) return false; try { return Boolean(lstat(x, { throwIfNoEntry: false })); } catch { return false; } };
  const mkRec = (a) => {
    if (exists(a[0])) { H.add('r', a[0]); return; }
    H.add('w', a[0]);
    if (!recursive || !rec(a[1])) return;
    const m = firstMissing(a[0]);
    if (m !== null) H.add('wr', m);
  };
  const lRec = (a) => { H.add('l', a[0]); if (recursive && rec(a[1])) H.add('lr', a[0]); };
  for (const o of [fs, P]) {
    for (const n of ['readFile', 'readFileSync', 'createReadStream', 'exists', 'existsSync', 'stat', 'statSync', 'lstat', 'lstatSync', 'access', 'accessSync', 'readlink', 'readlinkSync', 'realpath', 'realpathSync', 'openAsBlob']) wrap(o, n, r0);
    for (const n of ['readdir', 'readdirSync', 'opendir', 'opendirSync']) wrap(o, n, lRec);
    for (const n of ['writeFile', 'writeFileSync', 'appendFile', 'appendFileSync', 'createWriteStream', 'unlink', 'unlinkSync', 'truncate', 'truncateSync', 'chmod', 'chmodSync', 'utimes', 'utimesSync', 'lchown', 'chown', 'chownSync']) wrap(o, n, w0);
    for (const n of ['rm', 'rmSync', 'rmdir', 'rmdirSync']) wrap(o, n, wRec);
    for (const n of ['mkdir', 'mkdirSync']) wrap(o, n, mkRec);
    for (const n of ['rename', 'renameSync']) {
      wrap(o, n, (a) => {
        H.add('w', a[0]); H.add('w', a[1]); H.add('r', a[0]);
        if (recursive && isDir(a[0])) { H.add('wr', a[0]); H.add('wr', a[1]); }
      });
    }
    for (const n of ['copyFile', 'copyFileSync']) wrap(o, n, (a) => { H.add('r', a[0]); H.add('w', a[1]); });
    // a directory can only be copied with {recursive: true} (Node throws ERR_FS_EISDIR otherwise)
    for (const n of ['cp', 'cpSync']) {
      wrap(o, n, (a) => {
        H.add('r', a[0]); H.add('w', a[1]);
        if (recursive && rec(typeof a[2] === 'function' ? null : a[2])) { H.add('lr', a[0]); H.add('wr', a[1]); }
      });
    }
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
  // a unix socket a server listens on or a client connects to: `unix:<real path>` (abstract sockets: `unix:\0name`)
  const unixKey = (p) => (p.startsWith('\0') ? `unix:${p}` : `unix:${realOf(path.resolve(p))}`);
  const pathOf = (x) => {
    if (typeof x === 'string' && x && !/^\d+$/.test(x)) return x;
    if (x && typeof x === 'object' && typeof x.path === 'string' && x.path) return x.path;
    return null;
  };
  if (SP) {
    wrap(SP, 'listen', (a) => {
      if (!cur) return;
      const p = portOf(a);
      if (p) { cur.listen.add(String(p)); return; }
      const u = pathOf(a[0]);
      if (u) cur.listen.add(unixKey(u));
    });
  }
  // services (spec parallel-proof-gaps (a), gate notes 4 and 7): a TCP connect to a loopback host is keyed by its port
  // (as listeners are), a unix-socket connect by `unix:<path>`, a TCP connect to any other host by
  // `tcp:<host as given, lower-cased>:<port>`. Two lanes connecting to one loopback port or unix socket share a service:
  // a hazard (`shared-service`), whether or not a lane listens on it. A remote host key is recorded only, never paired
  // (founder decision 2026-11-26, D1 = A). DETJS_HAZARD_SHARED_SERVICE=0 records only loopback ports,
  // as before (measurement only; the runner then gives no proof). UDP / dgram is not recorded (known limit).
  const sharedService = process.env.DETJS_HAZARD_SHARED_SERVICE !== '0';
  const LOOPBACK = /^(localhost|127\.|::1$|0:0:0:0:0:0:0:1$|\[::1\]$|0\.0\.0\.0$|::$|::ffff:127\.)/;
  const SockP = net.Socket && net.Socket.prototype;
  if (SockP) {
    wrap(SockP, 'connect', (a) => {
      if (!cur) return;
      let o = a[0];
      if (Array.isArray(o)) o = o[0];
      let port = null; let host = 'localhost';
      const u = pathOf(o);
      if (u) { if (sharedService) cur.connect.add(unixKey(u)); return; }
      if (o && typeof o === 'object') { port = o.port; host = o.host || 'localhost'; } else if (o !== undefined) { port = o; host = typeof a[1] === 'string' ? a[1] : 'localhost'; }
      if (!port || !/^\d+$/.test(String(port))) return;
      const h = String(host).toLowerCase();
      if (LOOPBACK.test(h)) cur.connect.add(String(Number(port)));
      else if (sharedService) cur.connect.add(`tcp:${h}:${Number(port)}`);
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

// keys: root-relative ('a/b', the root itself '.') or absolute ('/x/y'); a root-relative key is never under an
// absolute one and the reverse (prefix matching compares keys of the same form only, gate note 7)
const keyUnder = (k, d) => (d === '.' ? !k.startsWith('/') : k === d || k.startsWith(`${d}/`));

/** The ancestors of key `d` (nearest first): 'a/b/c' -> ['a/b', 'a', '.']; '/x/y' -> ['/x', '/']. */
function keyAncestors(d) {
  const out = [];
  if (d === '.' || d === '/') return out;
  let x = d;
  for (;;) {
    const i = x.lastIndexOf('/');
    if (i < 0) { out.push('.'); return out; }
    x = i === 0 ? '/' : x.slice(0, i);
    out.push(x);
    if (x === '/') return out;
  }
}

/** Sorted [key, label] entries: the entries equal to `d` or inside it (a contiguous range, found by binary search). */
function sortedIndex(entries) {
  entries.sort((x, y) => (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : 0));
  const lower = (k) => { let lo = 0; let hi = entries.length; while (lo < hi) { const m = (lo + hi) >> 1; if (entries[m][0] < k) lo = m + 1; else hi = m; } return lo; };
  return {
    under(d) {
      if (d === '.') return entries.filter((e) => !e[0].startsWith('/'));
      const out = [];
      for (let i = lower(d); i < entries.length && entries[i][0] === d; i++) out.push(entries[i]);
      const pre = `${d}/`;
      for (let i = lower(pre); i < entries.length && entries[i][0].startsWith(pre); i++) out.push(entries[i]);
      return out;
    },
  };
}

/**
 * Cross-lane hazards between files of different lanes, from their footprints. Kinds: read-write, write-write (one
 * key), list-write (a write of a direct child of a listed dir), port (listen-listen, connect to a listener),
 * recursive-write (a recursive write root and any key of the other file inside it, a plain listing of its
 * parent, or a recursive listing of one of its ancestors), recursive-read (a recursive read root and a write inside it), shared-service (two files connecting to
 * the same loopback port or unix socket; a remote host:port is recorded but never paired). One hazard per file pair (the first found).
 */
function hazards(markers, laneOf) {
  const writers = new Map();
  const listeners = new Map();
  const connectors = new Map();
  const plainListers = new Map(); // dir listed by a plain readdir / opendir -> labels
  const recListers = new Map(); // dir listed recursively (readdir {recursive}, cp source) -> labels
  const anyKeys = []; // [key, label] of r, w, l, wr, lr
  const writeKeys = []; // [key, label] of w, wr
  const plainWrites = []; // [key, label] of w
  const S = (f, n) => (Array.isArray(f[n]) ? f[n] : []);
  const push = (m, k, label) => { if (!m.has(k)) m.set(k, []); m.get(k).push(label); };
  for (const [label, m] of markers) {
    const f = m.footprint;
    if (!f) continue;
    for (const w of S(f, 'w')) { push(writers, w, label); plainWrites.push([w, label]); writeKeys.push([w, label]); }
    for (const w of S(f, 'wr')) writeKeys.push([w, label]);
    for (const p of S(f, 'listen')) push(listeners, p, label);
    for (const p of S(f, 'connect')) push(connectors, p, label);
    for (const d of S(f, 'l')) push(plainListers, d, label);
    for (const d of S(f, 'lr')) push(recListers, d, label);
    for (const n of ['r', 'w', 'l', 'wr', 'lr']) for (const k of S(f, n)) anyKeys.push([k, label]);
  }
  const anyIdx = sortedIndex(anyKeys);
  const writeIdx = sortedIndex(writeKeys);
  const plainIdx = sortedIndex(plainWrites);
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
    for (const r of S(f, 'r')) for (const w of writers.get(r) || []) addH(label, w, 'read-write', r);
    for (const r of S(f, 'w')) for (const w of writers.get(r) || []) addH(label, w, 'write-write', r);
    for (const d of S(f, 'l')) {
      for (const [p, w] of plainIdx.under(d)) {
        if (p === d) continue;
        const rest = d === '.' ? p : p.slice(d.length + 1);
        if (!rest.includes('/')) addH(label, w, 'list-write', d);
      }
    }
    for (const p of S(f, 'listen')) for (const o of listeners.get(p) || []) addH(label, o, 'port', p);
    for (const p of S(f, 'connect')) for (const o of listeners.get(p) || []) addH(label, o, 'port', p);
    // a remote host (`tcp:<host>:<port>`) is recorded but never paired: only local services pair lanes (founder
    // decision 2026-11-26, D1 = A)
    if (process.env.DETJS_HAZARD_SHARED_SERVICE !== '0') {
      for (const p of S(f, 'connect')) if (!p.startsWith('tcp:')) for (const o of connectors.get(p) || []) addH(label, o, 'shared-service', p);
    }
    for (const d of S(f, 'wr')) {
      for (const [, o] of anyIdx.under(d)) addH(label, o, 'recursive-write', d);
      // a plain listing sees only direct children: it sees D appear or go only when it lists dirname(D); a
      // recursive listing sees everything below it (founder decision 2026-11-25, B1)
      const anc = keyAncestors(d);
      if (anc.length) for (const o of plainListers.get(anc[0]) || []) addH(label, o, 'recursive-write', d);
      for (const a of anc) for (const o of recListers.get(a) || []) addH(label, o, 'recursive-write', d);
    }
    for (const d of S(f, 'lr')) for (const [, o] of writeIdx.under(d)) addH(label, o, 'recursive-read', d);
  }
  return [...out.values()].sort((x, y) => (x.a < y.a ? -1 : x.a > y.a ? 1 : x.b < y.b ? -1 : x.b > y.b ? 1 : 0));
}

/** The footprint's skip dirs as the lanes applied them: effective (root-relative under the root) and ignored, with why. */
function skipMeta(root) {
  const rootR = realDir(path.resolve(root));
  const { skip, ignored } = footprintSkip(rootR, footprintSkipCandidates());
  const rel = (d) => (d.startsWith(rootR + path.sep) ? d.slice(rootR.length + 1).split(path.sep).join('/') : d);
  return { skip_dirs: skip.map((d) => rel(d.slice(0, -path.sep.length))), skip_dirs_ignored: ignored };
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
      ...skipMeta(root),
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
    // the markers whose start and end are both numbers (C3, /review): a marker without end (its file's leave() did not
    // run) made the test-file time NaN, written null
    const timed = keys.map((k) => markers.get(k)).filter((m) => m && typeof m.start === 'number' && typeof m.end === 'number');
    const durs = timed.map((m) => [m.label, Math.max(0, m.end - m.start) / 1000]);
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
        // C3 (spec "false greens on release-1"): over `timed`, the markers `durs` is computed from (non-empty here); a
        // marker without start or end made this NaN, written null, which the runner reads as "proof incomplete" on a
        // clean run. A timing field only: completeness is the outcome records' (exit-status countStatus: a test with no
        // record is `missing`, failed) and the hazard re-run's accounting
        const t0 = Math.min(...timed.map((m) => m.start));
        const t1 = Math.max(...timed.map((m) => m.end));
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
  PLACEMENT_VARS, workerCount, defaultWorkers, resolveWorkers, makePlan, readReplay, writeRunPlan, enter, leave, markDone, installFootprint, skipDirs, footprintSkip,
  carriedBefore, carriedAfter, collect, loadState, statePath, hazards,
};
