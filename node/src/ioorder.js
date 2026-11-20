'use strict';
// Completion order of concurrent asynchronous I/O (audit G-0150, G-0151).
//
// Level 0 does not choose the order in which the thread pool or the kernel completes concurrent operations (two
// `fs.readFile` calls in flight, two local HTTP requests racing). It records it: while a test has more than one of
// its own asynchronous file operations or connections pending, each completion of an overlapping operation is an
// event `io.complete <kind>#<n>` (n = the operation's start index in the test), and the test gets one
// `uncontrolled.io` event. A different completion order is then a different fingerprint, and the verifier never
// calls the runs identical. Operations that never overlap (each awaited before the next starts) record nothing:
// their order is the program's.
//
// Level 1 (audit G-1412, G-1478): the completions of a test's concurrent file operations are delivered in the order
// the operations started (a callback or promise of an operation that completed early waits until every operation
// started before it has been delivered). Parallel directory walks (fast-glob, globby, readdirp, @nodelib/fs.walk)
// then merge their listings in the same order in every run. An operation held longer than HOLD_MAX_MS of real time
// by an earlier one that does not complete (a FIFO, a device) is released in completion order, recorded
// (`io.release`). Every completion also tells the virtual timer driver that local I/O progressed (timers go back to
// fast time once nothing is pending), and a completion while virtual timers of the test wait is a scheduling
// decision (`sched.io`, src/sched.js).
const fs = require('node:fs');
const net = require('node:net');
const { STATE } = require('./state');
const sites = require('./sites');
const sched = require('./sched');

const HOLD_MAX_MS = 200;
let clock = null; // src/clock.js (set at installation)
let REAL_SET_IMMEDIATE = setImmediate;
let REAL_SET_TIMEOUT = setTimeout;
let REAL_CLEAR_TIMEOUT = clearTimeout;

const FS_FNS = ['readFile', 'writeFile', 'appendFile', 'read', 'write', 'open', 'close', 'stat', 'lstat', 'fstat',
  'access', 'readdir', 'mkdir', 'rmdir', 'rm', 'unlink', 'rename', 'copyFile', 'readlink', 'realpath', 'truncate',
  'utimes', 'chmod', 'opendir', 'cp', 'mkdtemp', 'symlink', 'link'];

let seq = 0;
let pending = new Set();
let marked = false;
// file operations of the running test not yet delivered, in start order, and completions waiting for them
let undelivered = [];
let held = [];
let holdTimer = null;

function startTest() {
  seq = 0;
  pending = new Set();
  marked = false;
  releaseAll(false);
  undelivered = [];
}

/** An operation of the test that just started is still pending (a file operation, a connection without data yet). */
function freshPending() {
  for (const o of pending) if (o.kind !== 'net' || !o.data) return true;
  return false;
}

/** Number of completions held for ordering (pending I/O for the timer driver). */
function heldCount() {
  return held.length;
}

function timersWaiting(test) {
  if (clock === null) return 0;
  let n = 0;
  for (const t of clock.DRIVER.queue) if (t._test === test) n += 1;
  return n;
}

/** Local I/O progressed: record the choice against waiting timers, let the driver go back to fast time. */
function progressed(op, kind) {
  if (clock === null) return;
  if (STATE.testId === op.test) {
    const n = timersWaiting(op.test);
    if (n) sched.ioChosen(op.site, kind, n);
  }
  clock.DRIVER.rearm();
}

/** A new operation of the running test (null when outside tests or started by the runner). */
function begin(kind) {
  if (STATE.testId === null || STATE.quietDepth > 0) return null;
  let site = '';
  if (STATE.config && STATE.config.sites) {
    site = STATE.quiet(() => sites.resolve());
    if (site === null) return null;
  }
  const op = { kind, n: seq++, test: STATE.testId, overlapped: false, site, done: false };
  if (pending.size) {
    for (const o of pending) o.overlapped = true;
    op.overlapped = true;
    if (!marked) {
      marked = true;
      STATE.recordAt('other', 'uncontrolled.io', site, 'concurrent I/O');
    }
  }
  pending.add(op);
  return op;
}

function end(op) {
  if (!op || op.done) return;
  op.done = true;
  pending.delete(op);
  if (op.overlapped && STATE.testId === op.test) STATE.recordAt('other', 'io.complete', op.site, `${op.kind}#${op.n}`);
  progressed(op, op.kind);
}

/** A file operation started (ordered delivery). */
function track(op) {
  if (op !== null) undelivered.push(op);
}

/**
 * Operation `op` completed: `deliver` runs its callback (or settles its promise) once every file operation started
 * before it has been delivered.
 */
function complete(op, deliver) {
  if (op === null) { deliver(); return; }
  const i = undelivered.indexOf(op);
  if (i <= 0) {
    if (i === 0) undelivered.shift();
    end(op);
    try { deliver(); } finally { if (held.length) REAL_SET_IMMEDIATE(drain); }
    return;
  }
  held.push({ op, deliver });
  sched.setHeld(held.length);
  if (holdTimer === null) {
    holdTimer = REAL_SET_TIMEOUT(() => { holdTimer = null; releaseAll(true); }, HOLD_MAX_MS);
    if (holdTimer.unref) holdTimer.unref();
  }
}

/** Deliver the held completion whose predecessors were all delivered (one per macrotask, in start order). */
function drain() {
  if (!held.length) return;
  const first = undelivered[0];
  const k = held.findIndex((h) => h.op === first);
  if (k < 0) return;
  const [h] = held.splice(k, 1);
  sched.setHeld(held.length);
  undelivered.shift();
  if (!held.length && holdTimer !== null) { REAL_CLEAR_TIMEOUT(holdTimer); holdTimer = null; }
  end(h.op);
  try { h.deliver(); } finally { if (held.length) REAL_SET_IMMEDIATE(drain); }
}

/** Release every held completion (an earlier operation does not complete, or the test ended). */
function releaseAll(record) {
  if (holdTimer !== null) { REAL_CLEAR_TIMEOUT(holdTimer); holdTimer = null; }
  const list = held.sort((a, b) => a.op.n - b.op.n);
  held = [];
  sched.setHeld(0);
  for (const h of list) {
    const i = undelivered.indexOf(h.op);
    if (i >= 0) undelivered.splice(i, 1);
    if (record && STATE.testId === h.op.test) {
      STATE.recordAt('other', 'io.release', h.op.site, `${h.op.kind}#${h.op.n}`);
      if (STATE.onRealClock) STATE.onRealClock('a file operation was delivered out of start order (real time decided)');
    }
    end(h.op);
    try { h.deliver(); } catch (e) { REAL_SET_IMMEDIATE(() => { throw e; }); }
  }
}

function wrapCallback(name, real) {
  const w = function (...a) {
    const i = a.length - 1;
    if (i < 0 || typeof a[i] !== 'function') return real.apply(this, a);
    const op = begin(`fs.${name}`);
    if (op === null) return real.apply(this, a);
    const cb = a[i];
    a[i] = function (...r) { const self = this; complete(op, () => cb.apply(self, r)); };
    track(op);
    try {
      return real.apply(this, a);
    } catch (e) {
      const j = undelivered.indexOf(op);
      if (j >= 0) undelivered.splice(j, 1);
      end(op);
      if (held.length) REAL_SET_IMMEDIATE(drain);
      throw e;
    }
  };
  return w;
}

function wrapPromise(name, real) {
  return function (...a) {
    const op = begin(`fs.${name}`);
    let p;
    try { p = real.apply(this, a); } catch (e) { end(op); throw e; }
    if (op === null || !p || typeof p.then !== 'function') { end(op); return p; }
    track(op);
    return new Promise((resolve, reject) => {
      p.then((v) => complete(op, () => resolve(v)), (e) => complete(op, () => reject(e)));
    });
  };
}

function copyMeta(real, w) {
  for (const k of Reflect.ownKeys(real)) {
    if (['length', 'name', 'prototype', 'arguments', 'caller'].includes(k)) continue;
    try { Object.defineProperty(w, k, Object.getOwnPropertyDescriptor(real, k)); } catch { /* ignore */ }
  }
  try { Object.defineProperty(w, 'name', { value: real.name, configurable: true }); } catch { /* ignore */ }
  return w;
}

function installProcess(patcher) {
  if (STATE.__ioHooked) return;
  STATE.__ioHooked = true;
  clock = require('./clock');
  REAL_SET_IMMEDIATE = clock.REAL.setImmediate;
  REAL_SET_TIMEOUT = clock.REAL.setTimeout;
  REAL_CLEAR_TIMEOUT = clock.REAL.clearTimeout;
  clock.setFreshIO(freshPending);
  STATE.onTestStart.push(startTest);
  STATE.onTestEnd.push(() => releaseAll(false));
  for (const n of FS_FNS) {
    if (typeof fs[n] === 'function') patcher.set(fs, n, copyMeta(fs[n], wrapCallback(n, fs[n])));
    if (fs.promises && typeof fs.promises[n] === 'function') patcher.set(fs.promises, n, copyMeta(fs.promises[n], wrapPromise(n, fs.promises[n])));
  }
  // connections (local ones: external hosts are closed, recorded or replayed by the network control): pending from
  // connect to close; the arrival of their first data is the completion that races
  const realConnect = net.Socket.prototype.connect;
  patcher.set(net.Socket.prototype, 'connect', function connect(...a) {
    const op = begin('net');
    if (op !== null) {
      const origPush = this.push;
      let first = true;
      this.push = function push(chunk, enc) {
        if (first && chunk !== null && chunk !== undefined) {
          first = false;
          op.data = true;
          if (op.overlapped && STATE.testId === op.test) STATE.recordAt('other', 'io.complete', op.site, `net#${op.n}:data`);
          progressed(op, 'net:data');
        }
        return origPush.call(this, chunk, enc);
      };
      this.once('close', () => end(op));
    }
    return realConnect.apply(this, a);
  });
}

module.exports = { installProcess, heldCount };
