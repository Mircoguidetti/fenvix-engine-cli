'use strict';
// P2 (spec "P2 speed", Phase B): where a --det run's time goes. Opt-in with DETJS_PHASES=1, off by default; nothing
// here changes what a run records. With it on, every process of the run appends JSON lines to `<trace>.phases.jsonl`
// (never to the trace): the main process its phases (start, deps_hash, plan, workers_spawn, rerun_one_lane,
// trace_write, exit; `tests` per worker, aggregated at the end from the file lines), each worker one `worker_ready`
// line and one `file` line per test file with its counters (io_release count and held ms, stack_captures,
// uncontrolled_io). The file name reaches the workers through DETJS_PHASES_FILE (DETJS_* variables are detjs' own:
// hidden from the tests and from the recorded inputs, src/envview.js).
//
// The real clock and the real fs functions are captured when this module loads, before any control is installed
// (it is required by session.js in the main process and by controls.js/sites.js in a worker, ahead of the patches):
// these writes are never seen by ioorder, fsorder or the cache capture, and the virtual clock never answers them.
const fs = require('node:fs');

const REAL = {
  now: Date.now,
  hr: process.hrtime.bigint,
  openSync: fs.openSync,
  writeSync: fs.writeSync,
  closeSync: fs.closeSync,
  readFileSync: fs.readFileSync,
};
const now = () => REAL.now.call(Date);
const ms = (t0) => Number(REAL.hr.call(process) - t0) / 1e6;

const on = () => process.env.DETJS_PHASES === '1' && Boolean(process.env.DETJS_PHASES_FILE);

// counters of this process, incremented unconditionally (integer adds); written only when on
// (P2 C6: resolve_calls = sites.resolve() calls, stack_deep = those that needed the second, deeper capture,
// stack_runner = runnerInitiated() captures, site_formatted = source-mapped stack formats on a site cache miss)
const C = { io_release: 0, held_ms: 0, stack_captures: 0, uncontrolled_io: 0, resolve_calls: 0, stack_deep: 0, stack_runner: 0, site_formatted: 0 };

function write(obj) {
  if (!on()) return;
  let fd = null;
  try {
    fd = REAL.openSync.call(fs, process.env.DETJS_PHASES_FILE, 'a');
    REAL.writeSync.call(fs, fd, `${JSON.stringify({ pid: process.pid, thread: threadId(), pass: pass(), ...obj })}\n`);
  } catch { /* timing is best effort: never fails a run */ } finally {
    if (fd !== null) { try { REAL.closeSync.call(fs, fd); } catch { /* closed */ } }
  }
}

// the hazard re-run wrapper's pass (src/parallel-rerun.js), null outside it
const pass = () => process.env.DETJS_HAZARD_PASS || null;

function threadId() {
  try { return require('node:worker_threads').threadId; } catch { return 0; }
}

/** Main process: name the phases file after the trace (and hand it to the workers), then write `start`. */
function startRun(tracePath) {
  if (process.env.DETJS_PHASES !== '1') return;
  // a pass of the hazard re-run wrapper appends to the wrapper's file; a top-level run starts its own
  if (!process.env.DETJS_PHASES_FILE) {
    process.env.DETJS_PHASES_FILE = `${tracePath}.phases.jsonl`;
    try { fs.rmSync(process.env.DETJS_PHASES_FILE, { force: true }); } catch { /* none */ }
  }
  write({ phase: 'start', t: now(), uptime_ms: Math.round(process.uptime() * 1000) });
}

function mark(phase, extra = {}) {
  if (on()) write({ phase, t: now(), ...extra });
}

/** Time fn (sync) as `phase`; returns fn's value. */
function span(phase, fn, extra = {}) {
  if (!on()) return fn();
  const t = now();
  const t0 = REAL.hr.call(process);
  try { return fn(); } finally { write({ phase, t, ms: Math.round(ms(t0) * 1000) / 1000, ...extra }); }
}

// worker side: one `file` line per test file with the counters' deltas
let cur = null;
let ready = false;
function fileStart(label) {
  if (!on()) return;
  if (!ready) { ready = true; write({ phase: 'worker_ready', t: now() }); }
  cur = { label, t: now(), t0: REAL.hr.call(process), c: { ...C } };
}
function fileEnd() {
  if (!on() || cur === null) return;
  const d = {};
  for (const k of Object.keys(C)) d[k] = Math.round((C[k] - cur.c[k]) * 1000) / 1000;
  write({ phase: 'file', file: cur.label, t: cur.t, ms: Math.round(ms(cur.t0) * 1000) / 1000, ...d });
  cur = null;
}

/** Main process, at the end: per worker (pid:thread) the `tests` line from the file lines, then `exit`. */
function finishRun() {
  if (!on()) return;
  let lines = [];
  try {
    lines = String(REAL.readFileSync.call(fs, process.env.DETJS_PHASES_FILE, 'utf8')).split('\n').filter(Boolean).map((l) => JSON.parse(l));
  } catch { /* none */ }
  const per = new Map();
  for (const l of lines) {
    if (l.phase !== 'file' || l.pass !== pass()) continue;
    const k = `${l.pid}:${l.thread}`;
    const w = per.get(k) || { first: Infinity, last: 0, files: 0, file_ms: 0, io_release: 0, held_ms: 0, stack_captures: 0, uncontrolled_io: 0 };
    w.first = Math.min(w.first, l.t);
    w.last = Math.max(w.last, l.t + l.ms);
    w.files++;
    for (const c of ['io_release', 'held_ms', 'stack_captures', 'uncontrolled_io']) w[c] += l[c] || 0;
    w.file_ms += l.ms;
    per.set(k, w);
  }
  for (const [k, w] of per) {
    write({ phase: 'tests', worker: k, t: w.first, wall_ms: Math.round(w.last - w.first), files: w.files,
      file_ms: Math.round(w.file_ms), io_release: w.io_release, held_ms: Math.round(w.held_ms), stack_captures: w.stack_captures,
      uncontrolled_io: w.uncontrolled_io });
  }
  write({ phase: 'exit', t: now(), uptime_ms: Math.round(process.uptime() * 1000) });
}

module.exports = { C, on, now, startRun, mark, span, fileStart, fileEnd, finishRun };
