'use strict';
// Seeded randomness.
//
// * `Math.random` draws from a xoshiro128** generator reseeded at the start of
//   every test with derive_seed(seed, test id) (and per test file before the
//   first test, for module-level draws), so a test draws the same numbers
//   whatever its position in the run.
// * `crypto.getRandomValues` and `crypto.randomUUID` (global Web Crypto and
//   `node:crypto`) draw from a second stream derived from the same key.
// * `crypto.randomBytes`, `randomFillSync`, `randomFill`, `randomInt`, `pseudoRandomBytes` are OS
//   entropy: observed (digest in the fingerprint), not controlled, unless
//   `--det-urandom` is given (the Python shell's contract: os.urandom observed, --det-urandom controls it; audit
//   G-1426). Never silently: each draw is an `entropy` event and the run ends with the list of tests that drew it.
// * Protocol nonces drawn through them are controlled whatever the option (G-1421): the WebSocket handshake key
//   (`Sec-WebSocket-Key`) and the frame masks of the global `WebSocket` (undici) and of the `ws` package. They are
//   not secrets (RFC 6455 uses them against proxy cache poisoning), and real ones made every WebSocket test differ
//   from run to run. They come from a stream seeded per test (independent of --det-seed) and are `random` events (`crypto.randomBytes` /
//   `crypto.randomFillSync`, value `nonce <length>:<digest>`).

const nodeCrypto = require('node:crypto');
const native = require('./native');
const { STATE } = require('./state');
const sites = require('./sites');

// xoshiro128** (Blackman & Vigna), 32-bit arithmetic, seeded with SplitMix32.
class Xoshiro128 {
  constructor() {
    this.s = new Uint32Array(4);
  }

  seed(hi, lo) {
    let x = (hi ^ Math.imul(lo, 0x9e3779b9)) >>> 0;
    for (let i = 0; i < 4; i++) {
      x = (x + 0x9e3779b9) >>> 0;
      let z = x;
      z = Math.imul(z ^ (z >>> 16), 0x85ebca6b) >>> 0;
      z = Math.imul(z ^ (z >>> 13), 0xc2b2ae35) >>> 0;
      this.s[i] = (z ^ (z >>> 16) ^ (i === 0 ? lo : i === 1 ? hi : 0)) >>> 0;
    }
    if (!(this.s[0] | this.s[1] | this.s[2] | this.s[3])) this.s[0] = 1;
  }

  nextU32() {
    const s = this.s;
    const r = Math.imul(rotl(Math.imul(s[1], 5) >>> 0, 7), 9) >>> 0;
    const t = (s[1] << 9) >>> 0;
    s[2] ^= s[0];
    s[3] ^= s[1];
    s[1] ^= s[2];
    s[0] ^= s[3];
    s[2] ^= t;
    s[3] = rotl(s[3], 11);
    return r;
  }

  /** Double in [0, 1) with 53 random bits. */
  nextDouble() {
    const a = this.nextU32() >>> 5;
    const b = this.nextU32() >>> 6;
    return (a * 67108864 + b) / 9007199254740992;
  }

  fill(bytes) {
    for (let i = 0; i < bytes.length; i += 4) {
      const v = this.nextU32();
      for (let k = 0; k < 4 && i + k < bytes.length; k++) bytes[i + k] = (v >>> (8 * k)) & 0xff;
    }
  }
}

function rotl(x, k) {
  return ((x << k) | (x >>> (32 - k))) >>> 0;
}

const MATH = new Xoshiro128();
const CRYPTO = new Xoshiro128();
const ENTROPY = new Xoshiro128();
const NONCE = new Xoshiro128();
// draws made for the runner (a library working for it: source-map while Jest formats a stack trace): their own
// streams, not recorded, so that how many of them a process makes (lazily, in whichever test comes first in it)
// never shifts the test's own values (found on dom-testing-library: 2 fingerprints differed parallel vs serial)
const INFRA_MATH = new Xoshiro128();
const INFRA_CRYPTO = new Xoshiro128();

// whether the streams were seeded in this process (a test, or a file's module scope / hooks: seedFile). Before that
// (a runner's or a library's start-up) the controlled entropy stream is not used: an unseeded xoshiro state is all
// zeros and gives zero bytes, the same bytes on every draw (Playwright's in-process start-up then made the same
// dispatcher GUID twice and its worker exited). Such draws stay real and observed, as with --det-urandom=off.
let SEEDED = false;

function reseed(key) {
  SEEDED = true;
  const base = STATE.config.seed;
  const [h1, l1] = native.deriveSeedWords(base, key);
  MATH.seed(h1, l1);
  const [h2, l2] = native.deriveSeedWords(base, key + '\0crypto');
  CRYPTO.seed(h2, l2);
  const [h3, l3] = native.deriveSeedWords(base, key + '\0urandom');
  ENTROPY.seed(h3, l3);
  // protocol nonces do not depend on --det-seed: a recorded WebSocket handshake (its Sec-WebSocket-Accept answers the
  // key) replays under any seed
  const [h4, l4] = native.deriveSeedWords(0n, key + '\0nonce');
  NONCE.seed(h4, l4);
  const [h5, l5] = native.deriveSeedWords(base, key + '\0infra');
  INFRA_MATH.seed(h5, l5);
  const [h6, l6] = native.deriveSeedWords(base, key + '\0infra-crypto');
  INFRA_CRYPTO.seed(h6, l6);
}

// per-test state of a concurrent test (src/concur.js): each test draws from its own streams
const STREAMS = [MATH, CRYPTO, ENTROPY, NONCE, INFRA_MATH, INFRA_CRYPTO];
require('./concur').register({
  name: 'seeds',
  save: () => STREAMS.map((g) => g.s.slice()),
  restore: (x) => { STREAMS.forEach((g, i) => g.s.set(x[i])); },
});

/**
 * A draw not made for the test, inside a test (where the streams are the test's): made for the runner (src/sites.js
 * runnerInitiated), or by detjs' own work (quiet: a site lookup formats a stack, and the runner's source-map hook
 * draws). Such draws use their own streams, so they never shift the test's values.
 */
function forRunner() {
  if (STATE.testId === null) return false;
  if (STATE.quietDepth > 0) return true;
  return !!(STATE.config && STATE.config.sites && sites.runnerInitiated());
}

// A draw made by a WebSocket implementation for its handshake key or frame masks (Node's bundled undici:
// establishWebSocketConnection, generateMask / WebsocketFrameSend; undici from npm: lib/web/websocket/; ws:
// lib/websocket.js, lib/sender.js).
const STRUCTURED = (_e, cs) => cs;
function protocolNonce() {
  const E = Error;
  const prevPrepare = E.prepareStackTrace;
  const prevLimit = E.stackTraceLimit;
  E.prepareStackTrace = STRUCTURED;
  E.stackTraceLimit = 6;
  const holder = {};
  let frames;
  try {
    E.captureStackTrace(holder, protocolNonce);
    frames = holder.stack;
  } catch {
    frames = null;
  } finally {
    E.prepareStackTrace = prevPrepare;
    E.stackTraceLimit = prevLimit;
  }
  if (!Array.isArray(frames)) return false;
  for (const cs of frames) {
    const f = (cs.getFileName && cs.getFileName()) || '';
    if (!f) continue;
    if (f.includes('undici')) {
      if (/[\\/]websocket[\\/]/.test(f)) return true;
      const fn = `${(cs.getTypeName && cs.getTypeName()) || ''}.${(cs.getFunctionName && cs.getFunctionName()) || ''}`;
      if (/WebSocket|Websocket|generateMask/.test(fn)) return true;
    } else if (/[\\/]ws[\\/]lib[\\/](?:websocket|sender)\.js$/.test(f)) {
      return true;
    }
  }
  return false;
}

function nonce(op, buf) {
  require('./concur').sync();
  NONCE.fill(buf);
  STATE.record('random', op, `nonce ${buf.length}:${native.digest(Buffer.from(buf.buffer, buf.byteOffset, buf.byteLength))}`);
  return buf;
}

function mathRandom() {
  require('./concur').sync();
  if (forRunner()) return INFRA_MATH.nextDouble();
  const v = MATH.nextDouble();
  STATE.record('random', 'Math.random', String(v));
  return v;
}

const real = {
  getRandomValues: globalThis.crypto && globalThis.crypto.getRandomValues.bind(globalThis.crypto),
  randomUUID: nodeCrypto.randomUUID,
  randomBytes: nodeCrypto.randomBytes,
  randomFillSync: nodeCrypto.randomFillSync,
  randomFill: nodeCrypto.randomFill,
  randomInt: nodeCrypto.randomInt,
};

function getRandomValues(arr) {
  require('./concur').sync();
  // Tag check, not instanceof: Jest test files run in another realm.
  const tag = Object.prototype.toString.call(arr);
  if (!ArrayBuffer.isView(arr) || /Float(16|32|64)Array|DataView/.test(tag)) {
    return real.getRandomValues(arr); // native TypeError / TypeMismatchError
  }
  if (arr.byteLength > 65536) return real.getRandomValues(arr); // native QuotaExceededError
  const bytes = new Uint8Array(arr.buffer, arr.byteOffset, arr.byteLength);
  if (forRunner()) { INFRA_CRYPTO.fill(bytes); return arr; }
  CRYPTO.fill(bytes);
  STATE.record('random', 'crypto.getRandomValues', `${bytes.length}:${native.digest(Buffer.from(bytes))}`);
  return arr;
}

function randomUUID(options) {
  require('./concur').sync();
  if (options !== undefined && (options === null || typeof options !== 'object')) return real.randomUUID(options);
  const b = new Uint8Array(16);
  const runner = forRunner();
  (runner ? INFRA_CRYPTO : CRYPTO).fill(b);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Buffer.from(b).toString('hex');
  const uuid = `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
  if (!runner) STATE.record('random', 'crypto.randomUUID', uuid);
  return uuid;
}

// OS entropy: a per-test deterministic stream by default (P1 D), observed only with --det-urandom=off.
function randomBytes(size, cb) {
  // a protocol nonce (WebSocket key / mask) keeps its own seeded stream whatever --det-urandom says (P1 D)
  if (typeof cb !== 'function' && protocolNonce()) return nonce('crypto.randomBytes', real.randomBytes(size));
  if (typeof cb === 'function') {
    return real.randomBytes(size, (err, buf) => {
      if (!err) observe('crypto.randomBytes', buf);
      cb(err, buf);
    });
  }
  return observe('crypto.randomBytes', real.randomBytes(size));
}

function randomFillSync(buf, offset, size) {
  const out = real.randomFillSync(buf, offset, size);
  const view = ArrayBuffer.isView(buf) ? Buffer.from(buf.buffer, buf.byteOffset, buf.byteLength) : Buffer.from(buf);
  const start = offset === undefined ? 0 : offset * (ArrayBuffer.isView(buf) ? buf.BYTES_PER_ELEMENT || 1 : 1);
  const len = size === undefined ? view.length - start : size * (ArrayBuffer.isView(buf) ? buf.BYTES_PER_ELEMENT || 1 : 1);
  if (protocolNonce()) nonce('crypto.randomFillSync', view.subarray(start, start + len));
  else observe('crypto.randomFillSync', view.subarray(start, start + len));
  return out;
}

// Async forms (callback): the value is drawn (and recorded) at the call, the callback runs on a later tick, as the
// real API does (audit G-0133, G-0132: they bypassed the control and the trace).
function randomInt(min, max, cb) {
  if (typeof max === 'function') { cb = max; max = min; min = 0; }
  if (typeof cb === 'function') {
    if (max === undefined) real.randomInt(min); else real.randomInt(min, max); // argument validation, thrown synchronously
    const v = max === undefined ? randomInt(min) : randomInt(min, max);
    process.nextTick(cb, null, v);
    return undefined;
  }
  if (STATE.config.urandom && SEEDED) {
    if (max === undefined) { max = min; min = 0; }
    const range = max - min;
    const v = min + Math.floor(ENTROPY.nextDouble() * range);
    STATE.record('entropy', 'crypto.randomInt', String(v));
    return v;
  }
  const v = real.randomInt(min, max);
  STATE.record('entropy', 'crypto.randomInt', String(v));
  return v;
}

function randomFill(buf, offset, size, cb) {
  if (typeof offset === 'function') { cb = offset; offset = undefined; size = undefined; } else if (typeof size === 'function') { cb = size; size = undefined; }
  if (typeof cb !== 'function') return real.randomFill(buf, offset, size, cb); // the real API's own error
  randomFillSync(buf, offset, size);
  process.nextTick(cb, null, buf);
  return undefined;
}

function observe(op, buf) {
  if (STATE.config.urandom && SEEDED) ENTROPY.fill(buf);
  STATE.record('entropy', op, `${buf.length}:${native.digest(Buffer.from(buf.buffer, buf.byteOffset, buf.byteLength))}`);
  return buf;
}

function wrapWebCrypto(host) {
  // Web Crypto methods check their receiver: keep the host object as `this`.
  const out = Object.create(Object.getPrototypeOf(host));
  Object.defineProperty(out, 'subtle', { get: () => host.subtle, enumerable: true });
  out.getRandomValues = getRandomValues;
  out.randomUUID = randomUUID;
  return out;
}

function installProcess(patcher, cfg) {
  if (!STATE.__seedsHooked) {
    STATE.__seedsHooked = true;
    STATE.onTestStart.push((id) => reseed(id));
  }
  patcher.set(nodeCrypto, 'randomUUID', randomUUID);
  patcher.set(nodeCrypto, 'randomBytes', randomBytes);
  patcher.set(nodeCrypto, 'pseudoRandomBytes', randomBytes);
  patcher.set(nodeCrypto, 'randomFillSync', randomFillSync);
  patcher.set(nodeCrypto, 'randomFill', randomFill);
  patcher.set(nodeCrypto, 'randomInt', randomInt);
  if (nodeCrypto.webcrypto) {
    patcher.define(nodeCrypto.webcrypto, 'getRandomValues', getRandomValues);
    patcher.define(nodeCrypto.webcrypto, 'randomUUID', randomUUID);
  }
  installDevRandom(patcher);
}

// /dev/urandom and /dev/random read as files (review P1 F-03: the bytes differed between runs and the verifier
// called the test identical): the same contract as crypto.randomBytes. Observed (an `entropy` event with the
// bytes' digest), or, with --det-urandom, replaced by the controlled stream.
const DEV_RANDOM = /^\/dev\/u?random$/;
const randomFds = new Set();
function isDevRandom(p) {
  try {
    const s = typeof p === 'string' ? p : Buffer.isBuffer(p) ? p.toString() : (p && p.protocol === 'file:') ? require('node:url').fileURLToPath(p) : null;
    return s !== null && DEV_RANDOM.test(require('node:path').resolve(s));
  } catch { return false; }
}
function offsetOf(a) {
  if (typeof a[0] === 'number') return a[0];
  if (a[0] && typeof a[0] === 'object' && !ArrayBuffer.isView(a[0]) && typeof a[0].offset === 'number') return a[0].offset;
  return 0;
}
function devRandomRead(op, buf, offset, n) {
  if (!ArrayBuffer.isView(buf) || !(n > 0)) return;
  require('./concur').sync();
  observe(op, new Uint8Array(buf.buffer, buf.byteOffset + offset, n));
}
function installDevRandom(patcher) {
  const fs = require('node:fs');
  const w = (name, make) => { const real = fs[name]; if (typeof real === 'function') patcher.set(fs, name, make(real)); };
  w('openSync', (real) => function openSync(p, ...a) { const fd = real.call(this, p, ...a); if (isDevRandom(p)) randomFds.add(fd); return fd; });
  w('open', (real) => function open(p, ...a) {
    const cb = a[a.length - 1];
    if (typeof cb === 'function' && isDevRandom(p)) a[a.length - 1] = (e, fd) => { if (!e) randomFds.add(fd); cb(e, fd); };
    return real.call(this, p, ...a);
  });
  w('closeSync', (real) => function closeSync(fd, ...a) { randomFds.delete(fd); return real.call(this, fd, ...a); });
  w('close', (real) => function close(fd, ...a) { randomFds.delete(fd); return real.call(this, fd, ...a); });
  w('readSync', (real) => function readSync(fd, buf, ...a) {
    const n = real.call(this, fd, buf, ...a);
    if (randomFds.has(fd)) devRandomRead('/dev/urandom read', buf, offsetOf(a), n);
    return n;
  });
  w('read', (real) => function read(fd, ...a) {
    const cb = a[a.length - 1];
    if (randomFds.has(fd) && typeof cb === 'function') {
      const off = ArrayBuffer.isView(a[0]) ? offsetOf(a.slice(1)) : offsetOf(a);
      a[a.length - 1] = (e, n, buf) => { if (!e) devRandomRead('/dev/urandom read', buf, off, n); cb(e, n, buf); };
    }
    return real.call(this, fd, ...a);
  });
  const P = fs.promises;
  if (P && typeof P.open === 'function') {
    const realOpen = P.open;
    patcher.set(P, 'open', async function open(p, ...a) {
      const fh = await realOpen.call(this, p, ...a);
      if (isDevRandom(p) && fh && typeof fh.read === 'function') {
        const rr = fh.read;
        fh.read = async function read(buf, ...b) {
          const r = await rr.call(this, buf, ...b);
          if (r && r.buffer) devRandomRead('/dev/urandom read', r.buffer, ArrayBuffer.isView(buf) ? offsetOf(b) : offsetOf([buf]), r.bytesRead);
          return r;
        };
      }
      return fh;
    });
  }
}

function installRealm(patcher, g, _cfg, { sameRealm }) {
  if (g.Math) patcher.set(g.Math, 'random', mathRandom);
  if (g.crypto && typeof g.crypto.getRandomValues === 'function') {
    if (sameRealm) {
      patcher.define(g.crypto, 'getRandomValues', getRandomValues);
      patcher.define(g.crypto, 'randomUUID', randomUUID);
    } else {
      patcher.set(g, 'crypto', wrapWebCrypto(g.crypto));
    }
  }
}

/** Seed the streams for code that runs outside tests (module level, beforeAll). */
function seedFile(fileKey) {
  reseed(`<file>\0${fileKey}`);
}

module.exports = { Xoshiro128, installProcess, installRealm, seedFile, reseed, mathRandom };
