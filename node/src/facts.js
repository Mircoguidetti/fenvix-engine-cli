'use strict';
// Machine and process facts, native key generation and temporary directory names under --det (P-041; audit G-1406,
// G-1407, G-1408, G-1409, G-1430, G-1431, G-1422..G-1425, G-2163, G-2166).
//
// * Facts of the machine and of the process that Level 0 does not choose (host name, user, home and temporary
//   directories, network interfaces, CPUs, memory, load, uptimes, process ids, CPU and resource usage, event loop
//   utilisation) are passed through and recorded when a test reads them: `other` events `os.<name>` /
//   `process.<name>` with a digest of the value. A run on another machine, or a value that changes from call to call,
//   is then a different fingerprint, never "identical".
// * Native key generation draws OS randomness Level 0 cannot seed (`generateKeyPair`, `generateKey`, ECDH /
//   Diffie-Hellman `generateKeys`, `generatePrime`, WebCrypto `subtle.generateKey`): recorded as `entropy` events with
//   a digest of the generated material (the cache never reuses such a test: `keygen` / `entropy`).
// * `fs.mkdtemp` names: the random suffix comes from a stream seeded by the test id (the same in every run), so paths
//   under the temporary directory are reproducible; the name is recorded.
const os = require('node:os');
const fs = require('node:fs');
const nodeCrypto = require('node:crypto');
const path = require('node:path');
const { STATE } = require('./state');
const native = require('./native');

const dig = (v) => native.digest(Buffer.from(typeof v === 'string' ? v : JSON.stringify(v) || String(v))).slice(0, 12);

function rec(op, v, source = 'other') {
  if (STATE.testId === null || STATE.quietDepth > 0) return;
  let s;
  try { s = dig(v); } catch { s = '?'; }
  STATE.record(source, op, s);
}

function wrap(obj, name, op, patcher, source = 'other', view = (r) => r) {
  const real = obj && obj[name];
  if (typeof real !== 'function' || real.__detjsFacts) return;
  const w = function (...a) {
    const r = real.apply(this, a);
    if (STATE.testId !== null && STATE.quietDepth === 0) { try { recQuietSafe(op, view(r), source); } catch { /* never break the call */ } }
    return r;
  };
  for (const k of Reflect.ownKeys(real)) {
    if (['length', 'name', 'prototype', 'arguments', 'caller'].includes(k)) continue;
    try { Object.defineProperty(w, k, Object.getOwnPropertyDescriptor(real, k)); } catch { /* ignore */ }
  }
  Object.defineProperty(w, '__detjsFacts', { value: true });
  Object.defineProperty(w, 'name', { value: real.name, configurable: true });
  patcher.set(obj, name, w);
}

// `rec` runs inside STATE.quiet (so that digesting does not record): record with the test's site explicitly
function recQuietSafe(op, v, source) {
  const depth = STATE.quietDepth;
  STATE.quietDepth = 0;
  try { rec(op, v, source); } finally { STATE.quietDepth = depth; }
}

const OS_FACTS = ['hostname', 'userInfo', 'homedir', 'tmpdir', 'networkInterfaces', 'availableParallelism', 'totalmem',
  'freemem', 'loadavg', 'uptime', 'release', 'version', 'machine', 'getPriority', 'type', 'arch', 'endianness'];

function installProcessFacts(patcher, proc) {
  for (const n of ['cpuUsage', 'resourceUsage', 'memoryUsage', 'constrainedMemory', 'availableMemory']) {
    const real = proc[n];
    if (typeof real !== 'function' || real.__detjsFacts) continue;
    const w = function (...a) {
      const r = real.apply(this, a);
      if (STATE.testId !== null && STATE.quietDepth === 0) recQuietSafe(`process.${n}`, r);
      return r;
    };
    for (const k of Reflect.ownKeys(real)) {
      if (['length', 'name', 'prototype', 'arguments', 'caller'].includes(k)) continue;
      try { Object.defineProperty(w, k, Object.getOwnPropertyDescriptor(real, k)); } catch { /* ignore */ }
    }
    if (typeof real.rss === 'function') w.rss = function rss() { const r = real.rss(); if (STATE.testId !== null) recQuietSafe('process.memoryUsage.rss', r); return r; };
    Object.defineProperty(w, '__detjsFacts', { value: true });
    patcher.set(proc, n, w);
  }
  for (const n of ['pid', 'ppid']) {
    const d = Object.getOwnPropertyDescriptor(proc, n);
    if (!d || !d.configurable || d.get) continue;
    const value = d.value;
    try {
      Object.defineProperty(proc, n, {
        configurable: true, enumerable: d.enumerable,
        get() { if (STATE.testId !== null && STATE.quietDepth === 0) recQuietSafe(`process.${n}`, value); return value; },
        set(v) { Object.defineProperty(proc, n, { value: v, writable: true, configurable: true, enumerable: d.enumerable }); },
      });
    } catch { /* keep */ }
  }
}

function installProcess(patcher) {
  if (STATE.__factsHooked) return;
  STATE.__factsHooked = true;
  for (const n of OS_FACTS) wrap(os, n, `os.${n}`, patcher);
  wrap(os, 'cpus', 'os.cpus', patcher, 'other', (r) => `${r.length}|${r[0] ? r[0].model : ''}`);
  installProcessFacts(patcher, process);
  const perf = globalThis.performance;
  if (perf && typeof perf.eventLoopUtilization === 'function') wrap(perf, 'eventLoopUtilization', 'performance.eventLoopUtilization', patcher);
  // native key generation (entropy Level 0 cannot seed)
  const keyView = (r) => {
    const one = (k) => {
      if (k && typeof k.export === 'function') {
        try { return k.type === 'secret' ? k.export().toString('hex') : JSON.stringify(k.export({ format: 'jwk' })); } catch { return k.type || '?'; }
      }
      return Buffer.isBuffer(k) ? k.toString('hex') : String(k);
    };
    if (r && typeof r === 'object' && 'publicKey' in r) return one(r.publicKey);
    return one(r);
  };
  wrap(nodeCrypto, 'generateKeyPairSync', 'crypto.generateKeyPairSync', patcher, 'entropy', keyView);
  wrap(nodeCrypto, 'generateKeySync', 'crypto.generateKeySync', patcher, 'entropy', keyView);
  wrap(nodeCrypto, 'generatePrimeSync', 'crypto.generatePrimeSync', patcher, 'entropy', (r) => Buffer.from(r).toString('hex'));
  for (const [n, view] of [['generateKeyPair', keyView], ['generateKey', keyView], ['generatePrime', (r) => Buffer.from(r).toString('hex')]]) {
    const real = nodeCrypto[n];
    if (typeof real !== 'function' || real.__detjsFacts) continue;
    const w = function (...a) {
      const i = a.length - 1;
      if (STATE.testId !== null && typeof a[i] === 'function') {
        const cb = a[i];
        const test = STATE.testId;
        a[i] = function (err, ...r) {
          if (!err && STATE.testId === test) recQuietSafe(`crypto.${n}`, view(r.length > 1 ? { publicKey: r[0] } : r[0]), 'entropy');
          return cb.call(this, err, ...r);
        };
      }
      return real.apply(this, a);
    };
    for (const k of Reflect.ownKeys(real)) {
      if (['length', 'name', 'prototype', 'arguments', 'caller'].includes(k)) continue;
      try { Object.defineProperty(w, k, Object.getOwnPropertyDescriptor(real, k)); } catch { /* ignore */ }
    }
    Object.defineProperty(w, '__detjsFacts', { value: true });
    patcher.set(nodeCrypto, n, w);
  }
  for (const make of ['createECDH', 'createDiffieHellman', 'createDiffieHellmanGroup', 'getDiffieHellman']) {
    const real = nodeCrypto[make];
    if (typeof real !== 'function' || real.__detjsFacts) continue;
    const w = function (...a) {
      const o = real.apply(this, a);
      if (o && typeof o.generateKeys === 'function' && !o.__detjsFacts) {
        const g = o.generateKeys;
        o.generateKeys = function (...b) { const r = g.apply(this, b); if (STATE.testId !== null) recQuietSafe(`crypto.${make}.generateKeys`, Buffer.isBuffer(r) ? r.toString('hex') : String(r), 'entropy'); return r; };
      }
      return o;
    };
    Object.defineProperty(w, '__detjsFacts', { value: true });
    patcher.set(nodeCrypto, make, w);
  }
  const subtle = nodeCrypto.webcrypto && nodeCrypto.webcrypto.subtle;
  if (subtle && typeof subtle.generateKey === 'function' && !subtle.generateKey.__detjsFacts) {
    const real = subtle.generateKey;
    const w = function generateKey(...a) {
      const test = STATE.testId;
      const p = real.apply(this, a);
      if (test !== null) {
        // the key material is usually not extractable: the use of native randomness is what is recorded
        STATE.record('entropy', 'subtle.generateKey', 'native');
        STATE.record('other', 'uncontrolled.entropy', 'subtle.generateKey');
      }
      return p;
    };
    Object.defineProperty(w, '__detjsFacts', { value: true });
    try { Object.defineProperty(subtle, 'generateKey', { value: w, writable: true, configurable: true }); } catch { /* keep */ }
  }
  installMkdtemp(patcher);
}

/** Jest's per-file process object: the same facts. */
function installRealm(patcher, g) {
  if (g.process && g.process !== process) installProcessFacts(patcher, g.process);
}

// -- fs.mkdtemp ------------------------------------------------------------------------------------------------------
const CHARS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
let mkdtempN = 0;
STATE.onTestStart.push(() => { mkdtempN = 0; });

function suffixes(prefix) {
  const cfg = STATE.config;
  const n = mkdtempN++;
  let k = 0;
  return () => {
    const [h, l] = native.deriveSeedWords(cfg.seed, `${STATE.testId}\u0000mkdtemp\u0000${n}\u0000${k++}\u0000${path.basename(String(prefix))}`);
    let x = (BigInt(h >>> 0) << 32n) | BigInt(l >>> 0);
    let s = '';
    for (let i = 0; i < 6; i++) { s += CHARS[Number(x % 62n)]; x /= 62n; }
    return s;
  };
}

function installMkdtemp(patcher) {
  const realSync = fs.mkdtempSync;
  const realCb = fs.mkdtemp;
  const realP = fs.promises && fs.promises.mkdtemp;
  const inTest = () => STATE.testId !== null && STATE.quietDepth === 0 && STATE.config;
  const name = (prefix, opts) => {
    const enc = typeof opts === 'string' ? opts : opts && opts.encoding;
    return { pre: Buffer.isBuffer(prefix) ? prefix.toString() : String(prefix), enc };
  };
  const out = (p, enc) => (enc === 'buffer' ? Buffer.from(p) : p);
  if (typeof realSync === 'function') {
    patcher.set(fs, 'mkdtempSync', function mkdtempSync(prefix, opts) {
      if (!inTest() || prefix instanceof URL) return realSync.call(this, prefix, opts);
      const { pre, enc } = name(prefix, opts);
      const next = suffixes(pre);
      for (let i = 0; i < 100; i++) {
        const p = pre + next();
        try {
          fs.mkdirSync(p, 0o700);
          STATE.record('fs', 'fs.mkdtemp', path.basename(p));
          return out(p, enc);
        } catch (e) { if (e.code !== 'EEXIST') throw e; }
      }
      return realSync.call(this, prefix, opts);
    });
  }
  if (typeof realP === 'function') {
    patcher.set(fs.promises, 'mkdtemp', async function mkdtemp(prefix, opts) {
      if (!inTest() || prefix instanceof URL) return realP.call(this, prefix, opts);
      const { pre, enc } = name(prefix, opts);
      const next = suffixes(pre);
      const site = STATE.testId;
      for (let i = 0; i < 100; i++) {
        const p = pre + next();
        try {
          await fs.promises.mkdir(p, 0o700);
          if (STATE.testId === site) STATE.record('fs', 'fs.mkdtemp', path.basename(p));
          return out(p, enc);
        } catch (e) { if (e.code !== 'EEXIST') throw e; }
      }
      return realP.call(this, prefix, opts);
    });
  }
  if (typeof realCb === 'function') {
    patcher.set(fs, 'mkdtemp', function mkdtemp(prefix, opts, cb) {
      if (typeof opts === 'function') { cb = opts; opts = undefined; }
      if (typeof cb !== 'function' || !inTest() || prefix instanceof URL) return realCb.call(this, prefix, opts, cb);
      fs.promises.mkdtemp(prefix, opts).then((p) => cb(null, p), (e) => cb(e));
      return undefined;
    });
  }
}

module.exports = { installProcess, installRealm };
