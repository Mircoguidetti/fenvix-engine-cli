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
const fs = require('node:fs');
const net = require('node:net');
const { STATE } = require('./state');
const sites = require('./sites');

const FS_FNS = ['readFile', 'writeFile', 'appendFile', 'read', 'write', 'open', 'close', 'stat', 'lstat', 'fstat',
  'access', 'readdir', 'mkdir', 'rmdir', 'rm', 'unlink', 'rename', 'copyFile', 'readlink', 'realpath', 'truncate',
  'utimes', 'chmod', 'opendir', 'cp', 'mkdtemp', 'symlink', 'link'];

let seq = 0;
let pending = new Set();
let marked = false;

function startTest() {
  seq = 0;
  pending = new Set();
  marked = false;
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
}

function wrapCallback(name, real) {
  const w = function (...a) {
    const i = a.length - 1;
    if (i < 0 || typeof a[i] !== 'function') return real.apply(this, a);
    const op = begin(`fs.${name}`);
    if (op === null) return real.apply(this, a);
    const cb = a[i];
    a[i] = function (...r) { end(op); return cb.apply(this, r); };
    try {
      return real.apply(this, a);
    } catch (e) {
      end(op);
      throw e;
    }
  };
  return w;
}

function wrapPromise(name, real) {
  return function (...a) {
    const op = begin(`fs.${name}`);
    const p = real.apply(this, a);
    if (op !== null && p && typeof p.then === 'function') p.then(() => end(op), () => end(op));
    return p;
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
  STATE.onTestStart.push(startTest);
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
          if (op.overlapped && STATE.testId === op.test) STATE.recordAt('other', 'io.complete', op.site, `net#${op.n}:data`);
        }
        return origPush.call(this, chunk, enc);
      };
      this.once('close', () => end(op));
    }
    return realConnect.apply(this, a);
  });
}

module.exports = { installProcess };
