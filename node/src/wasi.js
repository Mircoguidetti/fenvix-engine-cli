'use strict';
// WASI under Level 0 (audit G-1429): `node:wasi` implements `random_get` and `clock_time_get` natively, so a
// WebAssembly module compiled for WASI read real entropy and the real clock. Every `WASI` instance's import object
// (`wasi.wasiImport`, `getImportObject()`) gets JavaScript versions of the two imports:
//
// * `random_get(buf, len)`: bytes from a stream seeded per test (`derive_seed(seed, test id + "\0wasi")`, per file
//   outside tests), recorded as a `random` event `wasi.random_get`;
// * `clock_time_get(id, precision, out)`: the virtual clock (realtime: the virtual wall clock in ns; monotonic and
//   CPU-time clocks: the virtual monotonic clock), recorded as a clock read `wasi.clock_time_get`.
//
// The instance's memory is taken from `start(instance)` / `initialize(instance)`. node:wasi is loaded when Level 0 is
// installed (its experimental warning is not printed again). `poll_oneoff` clock subscriptions still sleep for real.
const native = require('./native');
const { STATE } = require('./state');
const { Xoshiro128 } = require('./seeds');

const ESUCCESS = 0;
const EFAULT = 21;
const EINVAL = 28;
const MEMORY = new WeakMap(); // WASI object -> WebAssembly.Memory
const GEN = new Xoshiro128();
let genKey = null;

function stream() {
  const key = STATE.testId !== null ? STATE.testId : `<file>\0${STATE.fileId || ''}`;
  if (key !== genKey) {
    genKey = key;
    const [hi, lo] = native.deriveSeedWords(STATE.config ? STATE.config.seed : 0n, `${key}\0wasi`);
    GEN.seed(hi, lo);
  }
  return GEN;
}

function virtualize(self, wrap) {
  if (!wrap || typeof wrap !== 'object' || wrap.__detjsWasi) return wrap;
  const view = () => {
    const m = MEMORY.get(self);
    return m && m.buffer ? new Uint8Array(m.buffer) : null;
  };
  const realRandom = wrap.random_get;
  const realClock = wrap.clock_time_get;
  if (typeof realRandom === 'function') {
    wrap.random_get = function random_get(ptr, len) {
      const mem = view();
      if (!mem) return realRandom(ptr, len);
      ptr >>>= 0;
      len >>>= 0;
      if (ptr + len > mem.length) return EFAULT;
      const out = mem.subarray(ptr, ptr + len);
      stream().fill(out);
      STATE.record('random', 'wasi.random_get', `${len}:${native.digest(Buffer.from(out)).slice(0, 16)}`);
      return ESUCCESS;
    };
  }
  if (typeof realClock === 'function') {
    wrap.clock_time_get = function clock_time_get(id, precision, ptr) {
      const mem = view();
      if (!mem) return realClock(id, precision, ptr);
      if (id < 0 || id > 3) return EINVAL;
      ptr >>>= 0;
      if (ptr + 8 > mem.length) return EFAULT;
      const ns = require('./clock').virtualNowNs('wasi.clock_time_get', id !== 0);
      if (ns === null) return realClock(id, precision, ptr);
      new DataView(mem.buffer, mem.byteOffset).setBigUint64(ptr, BigInt.asUintN(64, ns), true);
      return ESUCCESS;
    };
  }
  Object.defineProperty(wrap, '__detjsWasi', { value: true });
  return wrap;
}

function installProcess(patcher) {
  let m;
  const realEmit = process.emitWarning;
  process.emitWarning = function emitWarning(w, ...a) {
    const type = typeof a[0] === 'string' ? a[0] : (a[0] && a[0].type) || (w && w.name);
    if (/WASI/.test(String((w && w.message) || w)) && /Experimental/.test(String(type))) return undefined;
    return realEmit.call(this, w, ...a);
  };
  try {
    m = require('node:wasi');
  } catch {
    return false;
  } finally {
    process.emitWarning = realEmit;
  }
  const P = m && m.WASI && m.WASI.prototype;
  if (!P || Object.prototype.hasOwnProperty.call(P, 'wasiImport')) return false;
  // the constructor assigns `this.wasiImport = wrap`: the accessor virtualizes it and keeps it as an own property
  Object.defineProperty(P, 'wasiImport', {
    configurable: true,
    get() { return undefined; },
    set(wrap) { Object.defineProperty(this, 'wasiImport', { value: virtualize(this, wrap), writable: true, configurable: true, enumerable: true }); },
  });
  for (const n of ['start', 'initialize']) {
    const real = P[n];
    if (typeof real !== 'function') continue;
    patcher.set(P, n, function (instance, ...rest) {
      try { if (instance && instance.exports && instance.exports.memory) MEMORY.set(this, instance.exports.memory); } catch { /* validated by Node */ }
      return real.call(this, instance, ...rest);
    });
  }
  return true;
}

module.exports = { installProcess, virtualize };
