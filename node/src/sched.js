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
  installNativeWork(patcher);
}

// Native addons whose callback-style calls run on the libuv thread pool and leave no active resource (so pending()
// cannot see them): each listed method of the addon's classes counts as pending work until its callback runs, as for
// crypto and zlib above. Found on alakajam (P3, founder decision D2 = A, 2026-11-27): a node-sqlite3 query in flight
// looked idle, so virtual time jumped to tarn's 60 s acquire timeout and the 5 s runner deadline fired first.
// harness/p3_flips/NATIVE.md lists the other addons of the measured repositories and why they are not here.
const NATIVE_WORK = [
  {
    name: 'node-sqlite3', // npm `sqlite3` (better-sqlite3 is synchronous; its addon has no OPEN_READWRITE)
    match: (b) => typeof b.Database === 'function' && typeof b.Statement === 'function' && typeof b.OPEN_READWRITE === 'number',
    classes: [['Database', ['close', 'exec', 'wait', 'loadExtension']],
      ['Statement', ['bind', 'get', 'run', 'all', 'each', 'reset', 'finalize']], ['Backup', ['step', 'finish']]],
    // a statement that failed to prepare (its own callback gets the error, or an 'error' event) never calls back the
    // calls queued on it
    failing: 'Statement',
  },
];

const OPEN = new WeakMap(); // native object -> Set of release functions of its calls in flight
const IN_FLIGHT = new Set(); // release functions of every node-sqlite3 call in flight (in a test, a hook, anywhere)
const POISONED = new WeakSet(); // statements that failed to prepare: their calls never call back, so are not counted
function releaseAll(o) {
  const s = o && OPEN.get(o);
  if (!s) return;
  OPEN.delete(o);
  for (const r of [...s]) r();
}

// A native call still in flight when the test that started it ends keeps counting for at most NATIVE_GRACE_MS of
// real time after that end, then stops counting. Another test's end (a concurrent or skipped sibling) does not start
// it; a call started outside a test (a hook, module scope) starts it at the next test end. A query the next test
// waits on (alakajam: the pool's connection still busy with the previous test's query while the next test waits in
// tarn's queue) is done long before; a call that never calls back (a path not caught by the callback wrap, eachDone
// or releaseOnError: a database whose open failed, a statement that failed without a callback) costs at most that
// much real time. When the grace ends a call that never returned, real time decided it: the running test is reported
// to the cache as reading the real clock (not reusable).
const NATIVE_GRACE_MS = 3000;
function releaseTestWork(testId) {
  const { REAL } = require('./clock');
  for (const r of IN_FLIGHT) {
    if (r.expiry || (r.owner !== testId && r.owner !== null)) continue;
    r.expiry = REAL.setTimeout(r.expire, NATIVE_GRACE_MS);
    if (r.expiry && r.expiry.unref) r.expiry.unref();
  }
}

/**
 * trackWork for the methods of a native class: each call in flight is also remembered on its object (releaseAll)
 * and in IN_FLIGHT (releaseTestWork). `each` is released by its completion callback (with only a row callback, one
 * that only releases is added) or by its row callback called with an error (a finalized statement calls only that).
 */
function trackOwned(patcher, P, names) {
  for (const n of names) {
    const real = P[n];
    if (typeof real !== 'function' || real.__detjsWork) continue;
    const w = function (...a) {
      const self = this;
      if (self && typeof self === 'object' && POISONED.has(self)) return real.apply(this, a);
      const i = a.length - 1;
      if (i < 0 || typeof a[i] !== 'function') return real.apply(this, a);
      let done = false;
      const release = () => {
        if (done) return;
        done = true;
        work -= 1;
        const s = OPEN.get(self);
        if (s) s.delete(release);
        IN_FLIGHT.delete(release);
        if (release.expiry) require('./clock').REAL.clearTimeout(release.expiry);
      };
      if (n === 'each') {
        const two = i >= 1 && typeof a[i - 1] === 'function';
        const row = two ? i - 1 : i;
        const rowCb = a[row];
        a[row] = function (err, ...r) { if (err) release(); return rowCb.call(this, err, ...r); };
        if (two) { const cb = a[i]; a[i] = function (...r) { release(); return cb.apply(this, r); }; } else a.push(function eachDone() { release(); });
      } else { const cb = a[i]; a[i] = function (...r) { release(); return cb.apply(this, r); }; }
      work += 1;
      release.owner = STATE.testId;
      release.expire = () => {
        if (done) return;
        release();
        if (STATE.onRealClock) STATE.onRealClock('a node-sqlite3 call still in flight 3 s of real time after its test ended stopped counting as pending work (real time decided)');
      };
      if (self && typeof self === 'object') { let s = OPEN.get(self); if (!s) OPEN.set(self, (s = new Set())); s.add(release); }
      IN_FLIGHT.add(release);
      try {
        return real.apply(this, a);
      } catch (e) {
        release();
        throw e;
      }
    };
    Object.defineProperty(w, 'name', { value: real.name, configurable: true });
    Object.defineProperty(w, '__detjsWork', { value: true });
    patcher.set(P, n, w);
  }
}

/**
 * The failing class: its constructor's callback with an error (also when it runs inside the constructor, as on a
 * closed database) ends its calls in flight, and later calls on it are not counted. A failure without a callback
 * (an 'error' event on it or on its database) is left to releaseTestWork.
 */
function releaseOnError(patcher, b, c) {
  const Real = b[c];
  if (!Real || Real.__detjsWorkCtor) return;
  const P = new Proxy(Real, {
    construct(target, args, nt) {
      let o = null;
      let failedEarly = false;
      const i = args.length - 1;
      if (i >= 0 && typeof args[i] === 'function') {
        const cb = args[i];
        args = [...args];
        args[i] = function (err, ...r) {
          if (err) { if (o === null) failedEarly = true; else { POISONED.add(o); releaseAll(o); } }
          return cb.call(this, err, ...r);
        };
      }
      o = Reflect.construct(target, args, nt === P ? target : nt);
      if (failedEarly && o && typeof o === 'object') POISONED.add(o);
      return o;
    },
    get(t, k, r) { return k === '__detjsWorkCtor' ? true : Reflect.get(t, k, r); },
  });
  patcher.set(b, c, P);
}

function nativeWork(patcher, b) {
  for (const n of NATIVE_WORK) {
    if (!n.match(b)) continue;
    for (const [c, names] of n.classes) if (b[c] && b[c].prototype) trackOwned(patcher, b[c].prototype, names);
    if (n.failing) releaseOnError(patcher, b, n.failing);
  }
}

function installNativeWork(patcher) {
  const Module = require('node:module');
  const realLoad = Module._load;
  if (realLoad.__detjsNativeWork) return;
  const w = function _load(request, ...rest) {
    const r = realLoad.call(this, request, ...rest);
    if (typeof request === 'string' && request.endsWith('.node') && r && typeof r === 'object') {
      try { nativeWork(patcher, r); } catch { /* never break the load */ }
    }
    return r;
  };
  for (const k of Reflect.ownKeys(realLoad)) {
    if (['length', 'name', 'prototype', 'arguments', 'caller'].includes(k)) continue;
    try { Object.defineProperty(w, k, Object.getOwnPropertyDescriptor(realLoad, k)); } catch { /* ignore */ }
  }
  Object.defineProperty(w, '__detjsNativeWork', { value: true });
  patcher.set(Module, '_load', w);
  if (Array.isArray(STATE.onTestEnd)) STATE.onTestEnd.push((id) => releaseTestWork(id));
  // already loaded (an earlier file of this process)
  for (const [file, mod] of Object.entries(require.cache)) {
    if (file.endsWith('.node') && mod && mod.exports && typeof mod.exports === 'object') { try { nativeWork(patcher, mod.exports); } catch { /* ignore */ } }
  }
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

let work = 0; // thread-pool jobs in flight (crypto, zlib callback forms, NATIVE_WORK addons)
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

// per-test state of a concurrent test (src/concur.js)
require('./concur').register({ name: 'sched', save: () => siteCounters, restore: (x) => { siteCounters = x; } });

/** A virtual timer was chosen while `n` operations of the test were still pending. */
function timerChosen(site, n, why) {
  STATE.recordAt('sched', 'sched.timer', site || '', `0/${1 + n}:${stableId(site)}`);
  // real time decided the order: the test's result is not reusable (src/cache/capture.js)
  if (STATE.onRealClock) STATE.onRealClock(why || 'a virtual timer fired while I/O of the test was pending (real time decided the order)');
}

/** An operation of the test completed while `n` virtual timers of the test were waiting. */
function ioChosen(site, kind, n) {
  STATE.recordAt('sched', 'sched.io', site || '', `0/${1 + n}:${stableId(site)}|${kind}`);
}

module.exports = {
  installProcess, takeBaseline, pending, isPending, graceFor, timerChosen, ioChosen, startTest, setHeld,
  kindOf, HAS_HANDLES, nativeWork, releaseTestWork,
};
