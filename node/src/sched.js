'use strict';
// Level 1 for Node: the order of virtual timers against pending I/O (audit G-0463, G-0464, G-1478, G-1484, G-1435).
//
// Level 0 decides *when* a virtual timer fires: at once ("fast") while nothing but timers is pending, after its real
// delay while real I/O is pending. Level 1 makes that decision a rule and records it:
//
// * what counts as pending I/O: requests (file operations, DNS, writes) and handles that can complete an operation
//   of the test: sockets, child processes, UDP sockets, `fs.watchFile` pollers. Not counted: the process' standard
//   streams (a library that looks at `process.stdout` / `process.stdin` opens a pipe that stays open for the whole
//   file, G-1435), listening servers (they complete nothing by themselves: the client side of a connection is
//   counted), `fs.watch` watchers (inotify events are delivered as soon as the change is made), message ports used
//   inside the thread, and worker threads that are idle: a worker counts only while it is busy, i.e. from its start
//   until its first message or exit, and from a message posted to it until its next message (a long-lived pool with
//   nothing to do no longer turns every timer into a real wait, G-1484). Handles that existed when the test file
//   started (the runner's own) are never counted.
// * thread-pool work that libuv does not list as a request is counted while it runs: the callback forms of
//   `crypto.pbkdf2`, `scrypt`, `randomBytes`, `randomFill`, `randomInt`, `generateKeyPair`, `generateKey`,
//   `generatePrime`, `checkPrime`, `hkdf`, `sign`, `verify` and of the zlib convenience methods (`gzip`, `inflate`,
//   `brotliCompress`, ...). Before, virtual timers (and so a runner deadline, src/deadline.js) could outrun them.
// * local I/O first, then timers: when an operation of the test completes and nothing else is pending, the driver
//   goes back to fast time at once (before, a timer kept waiting its whole real delay). A timer whose real delay has
//   passed while an operation of the test that just started (a file operation, a connection waiting for its first
//   data) is still pending waits a short grace (its own delay, between 30 and 50 ms) so that local I/O that completes
//   in that time completes first.
// * recorded decisions (event source `sched`, value `<chosen>/<set size>:<stable id>`, crates/detpy-core/src/event.rs):
//   `sched.timer` when a virtual timer fires while I/O of the test is still pending (the timer was chosen before
//   the I/O: set = the timer + the pending operations), `sched.io` when an operation of the test completes while
//   virtual timers of the test are waiting (the I/O was chosen before the timers). A run where real latency decided
//   differently records a different choice, and `detjs verify` names it ("first diverging scheduling choice").
const { STATE } = require('./state');

const MIN_GRACE_MS = 30;
const MAX_GRACE_MS = 50;

// Busy accounting of worker threads (posted - received; a fresh worker is busy until it is heard).
const BUSY = new WeakMap();
let baseline = new WeakSet();
let baselineNames = new Map();
const HAS_HANDLES = typeof process._getActiveHandles === 'function' && typeof process._getActiveRequests === 'function';

function busyOf(o) {
  let b = BUSY.get(o);
  if (!b) { b = { out: 0, heard: false, exited: false, port: false }; BUSY.set(o, b); }
  return b;
}

let net = null;
let wt = null;
function mods() {
  if (net === null) {
    net = require('node:net');
    wt = require('node:worker_threads');
  }
}

/** The public message port of a worker (Node keeps it under an internal symbol). */
function publicPort(w) {
  for (const s of Object.getOwnPropertySymbols(w)) {
    if (s.description === 'kPublicPort') return w[s];
  }
  return null;
}

const PORT_OWNER = new WeakMap(); // public port of a worker -> worker

/** Track workers and ports (process-wide, once). */
function installProcess(patcher) {
  if (STATE.__schedHooked) return;
  STATE.__schedHooked = true;
  mods();
  const W = wt.Worker && wt.Worker.prototype;
  if (W && typeof W.postMessage === 'function') {
    const post = W.postMessage;
    patcher.set(W, 'postMessage', function postMessage(...a) {
      const b = busyOf(this);
      b.out += 1;
      return post.apply(this, a);
    });
    const emit = W.emit;
    patcher.set(W, 'emit', function emit2(ev, ...a) {
      const b0 = busyOf(this);
      if (!b0.port) { b0.port = true; const p = publicPort(this); if (p) PORT_OWNER.set(p, this); }
      if (ev === 'message' || ev === 'messageerror') {
        const b = busyOf(this);
        b.heard = true;
        if (b.out > 0) b.out -= 1;
      } else if (ev === 'exit' || ev === 'error') {
        const b = busyOf(this);
        b.heard = true;
        b.out = 0;
        b.exited = true;
      }
      return emit.call(this, ev, ...a);
    });
  }
  trackWork(patcher, require('node:crypto'), ['pbkdf2', 'scrypt', 'randomBytes', 'randomFill', 'randomInt', 'generateKeyPair',
    'generateKey', 'generatePrime', 'checkPrime', 'hkdf', 'sign', 'verify']);
  trackWork(patcher, require('node:zlib'), ['deflate', 'deflateRaw', 'inflate', 'inflateRaw', 'gzip', 'gunzip', 'unzip',
    'brotliCompress', 'brotliDecompress', 'zstdCompress', 'zstdDecompress']);
}

/** A worker is busy from its start until it is first heard from, and from a message posted to it until its next message. */
function workerBusy(w) {
  const b = busyOf(w);
  if (b.exited) return false;
  return b.out > 0 || !b.heard;
}

/** Classify one active handle: a string kind when it counts as pending I/O, null otherwise. */
function kindOf(h) {
  if (h === null || typeof h !== 'object') return null;
  const name = h.constructor ? h.constructor.name : 'Object';
  // standard streams (G-1435)
  if (h._isStdio || ((h.fd === 0 || h.fd === 1 || h.fd === 2) && (name === 'Socket' || name === 'ReadStream' || name === 'WriteStream'))) return null;
  if (name === 'Server' || (typeof h.listening === 'boolean' && h.listening && typeof h.address === 'function' && typeof h.close === 'function' && !(h instanceof net.Socket))) return null;
  if (name === 'FSWatcher') return null;
  if (name === 'MessagePort') {
    const w = PORT_OWNER.get(h);
    if (w) return workerBusy(w) ? 'worker' : null;
    // other ports carry messages inside the thread (their delivery is not real I/O); a worker's own port counts
    // through its worker
    return null;
  }
  if (name === 'Worker') return workerBusy(h) ? 'worker' : null;
  if (name === 'TCP' || name === 'Pipe') return null; // raw server handles without an owner
  return name;
}

/** Pending I/O kinds beyond the baseline (empty: nothing pending). */
function pending() {
  if (!HAS_HANDLES) return pendingByNames();
  const out = [];
  for (let i = 0; i < held; i++) out.push('held');
  for (let i = 0; i < work; i++) out.push('work');
  for (const r of process._getActiveRequests()) {
    if (baseline.has(r)) continue;
    out.push(r && r.constructor ? r.constructor.name : 'request');
  }
  for (const h of process._getActiveHandles()) {
    if (baseline.has(h)) continue;
    const k = kindOf(h);
    if (k !== null) out.push(k);
  }
  return out;
}

const IGNORED_NAMES = new Set(['Timeout', 'Immediate', 'TTYWrap', 'TCPServerWrap', 'PipeServerWrap', 'FSEventWrap', 'MessagePort']);
function pendingByNames() {
  const m = new Map();
  for (const r of process.getActiveResourcesInfo()) {
    if (IGNORED_NAMES.has(r)) continue;
    m.set(r, (m.get(r) || 0) + 1);
  }
  const out = [];
  for (const [k, n] of m) for (let i = baselineNames.get(k) || 0; i < n; i++) out.push(k);
  return out;
}

let work = 0; // thread-pool jobs in flight (crypto, zlib callback forms)
let held = 0; // completions src/ioorder.js holds for ordering: delivered later, so still pending
function setHeld(n) { held = n; }

function isPending() {
  return held > 0 || work > 0 || pending().length > 0;
}

/** Wrap callback-style thread-pool functions of module `m`: pending while their job runs. */
function trackWork(patcher, m, names) {
  for (const n of names) {
    const real = m && m[n];
    if (typeof real !== 'function' || real.__detjsWork) continue;
    const w = function (...a) {
      const i = a.length - 1;
      if (i < 0 || typeof a[i] !== 'function') return real.apply(this, a);
      const cb = a[i];
      let done = false;
      a[i] = function (...r) { if (!done) { done = true; work -= 1; } return cb.apply(this, r); };
      work += 1;
      try {
        return real.apply(this, a);
      } catch (e) {
        if (!done) { done = true; work -= 1; }
        throw e;
      }
    };
    for (const k of Reflect.ownKeys(real)) {
      if (['length', 'name', 'prototype', 'arguments', 'caller'].includes(k)) continue;
      try { Object.defineProperty(w, k, Object.getOwnPropertyDescriptor(real, k)); } catch { /* ignore */ }
    }
    Object.defineProperty(w, 'name', { value: real.name, configurable: true });
    Object.defineProperty(w, '__detjsWork', { value: true });
    patcher.set(m, n, w);
  }
}

/** Handles and requests present now are the runner's own: never counted (taken when a test file starts). */
function takeBaseline() {
  if (HAS_HANDLES) {
    baseline = new WeakSet();
    for (const h of process._getActiveHandles()) if (h && typeof h === 'object') baseline.add(h);
    for (const r of process._getActiveRequests()) if (r && typeof r === 'object') baseline.add(r);
  }
  baselineNames = new Map();
  for (const r of process.getActiveResourcesInfo()) {
    if (IGNORED_NAMES.has(r)) continue;
    baselineNames.set(r, (baselineNames.get(r) || 0) + 1);
  }
}

function graceFor(delayMs) {
  return Math.min(MAX_GRACE_MS, Math.max(MIN_GRACE_MS, delayMs));
}

// Stable ids: creation site plus a per-site counter, per test (the shared vocabulary).
let siteCounters = new Map();
function stableId(site) {
  const s = site || '<unknown>';
  const n = (siteCounters.get(s) || 0) + 1;
  siteCounters.set(s, n);
  return `${s}#${n}`;
}
function startTest() { siteCounters = new Map(); }

/** A virtual timer was chosen while `n` operations of the test were still pending. */
function timerChosen(site, n) {
  STATE.recordAt('sched', 'sched.timer', site || '', `0/${1 + n}:${stableId(site)}`);
  // real time decided the order: the test's result is not reusable (src/cache/capture.js)
  if (STATE.onRealClock) STATE.onRealClock('a virtual timer fired while I/O of the test was pending (real time decided the order)');
}

/** An operation of the test completed while `n` virtual timers of the test were waiting. */
function ioChosen(site, kind, n) {
  STATE.recordAt('sched', 'sched.io', site || '', `0/${1 + n}:${stableId(site)}|${kind}`);
}

module.exports = {
  installProcess, takeBaseline, pending, isPending, graceFor, timerChosen, ioChosen, startTest, setHeld,
  kindOf, HAS_HANDLES,
};
