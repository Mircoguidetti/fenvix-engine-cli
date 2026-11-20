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
//   from run to run. They come from a stream seeded per test and are `random` events (`crypto.randomBytes` /
//   `crypto.randomFillSync`, value `nonce <length>:<digest>`).

const nodeCrypto = require('node:crypto');
const native = require('./native');
const { STATE } = require('./state');

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

function reseed(key) {
  const base = STATE.config.seed;
  const [h1, l1] = native.deriveSeedWords(base, key);
  MATH.seed(h1, l1);
  const [h2, l2] = native.deriveSeedWords(base, key + '\0crypto');
  CRYPTO.seed(h2, l2);
  const [h3, l3] = native.deriveSeedWords(base, key + '\0urandom');
  ENTROPY.seed(h3, l3);
  const [h4, l4] = native.deriveSeedWords(base, key + '\0nonce');
  NONCE.seed(h4, l4);
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
  NONCE.fill(buf);
  STATE.record('random', op, `nonce ${buf.length}:${native.digest(Buffer.from(buf.buffer, buf.byteOffset, buf.byteLength))}`);
  return buf;
}

function mathRandom() {
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
  // Tag check, not instanceof: Jest test files run in another realm.
  const tag = Object.prototype.toString.call(arr);
  if (!ArrayBuffer.isView(arr) || /Float(16|32|64)Array|DataView/.test(tag)) {
    return real.getRandomValues(arr); // native TypeError / TypeMismatchError
  }
  if (arr.byteLength > 65536) return real.getRandomValues(arr); // native QuotaExceededError
  const bytes = new Uint8Array(arr.buffer, arr.byteOffset, arr.byteLength);
  CRYPTO.fill(bytes);
  STATE.record('random', 'crypto.getRandomValues', `${bytes.length}:${native.digest(Buffer.from(bytes))}`);
  return arr;
}

function randomUUID(options) {
  if (options !== undefined && (options === null || typeof options !== 'object')) return real.randomUUID(options);
  const b = new Uint8Array(16);
  CRYPTO.fill(b);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Buffer.from(b).toString('hex');
  const uuid = `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
  STATE.record('random', 'crypto.randomUUID', uuid);
  return uuid;
}

// OS entropy: observed, controlled only with --det-urandom.
function randomBytes(size, cb) {
  if (!STATE.config.urandom && typeof cb !== 'function' && protocolNonce()) return nonce('crypto.randomBytes', real.randomBytes(size));
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
  if (!STATE.config.urandom && protocolNonce()) nonce('crypto.randomFillSync', view.subarray(start, start + len));
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
  if (STATE.config.urandom) {
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
  if (STATE.config.urandom) ENTROPY.fill(buf);
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
