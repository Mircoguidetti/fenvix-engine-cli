'use strict';
// Init script for the pages of a Level 2 browser run (Playwright
// `context.addInitScript`): runs in every frame before the page's own scripts.
//
// * Math.random: xoshiro128** (the same generator as the Node shell) seeded
//   with derive_seed(seed, test id) mixed with a hash of the document URL
//   (origin + path), so every document of a test draws a fixed sequence;
// * crypto.getRandomValues / crypto.randomUUID: a second stream of the same key;
// * window.__detjs.stats(): draw counters and a running digest of the values
//   handed out, read by the worker at the end of the test for the fingerprint.
//
// Date, performance.now and timers are not touched here: the browser's own
// virtual time (CDP Emulation.setVirtualTimePolicy) controls them, so that
// they stay consistent with layout, animations and requestAnimationFrame.
// Dedicated and shared workers get the same script prepended to their main script (worker.js,
// round 2); service workers are not reached (limit B3 in docs/L2-BROWSER.md).

function pageInit(seedHi, seedLo) {
  // Stringified and evaluated in the page: no closures over Node values.
  /* eslint-disable no-var */
  (function () {
    // Pages and (round 2) dedicated/shared workers: `self` is the global of both.
    var G = typeof self !== 'undefined' ? self : window;
    if (G.__detjs) return;
    var SEED_HI = __SEED_HI__ >>> 0;
    var SEED_LO = __SEED_LO__ >>> 0;
    function rotl(x, k) { return ((x << k) | (x >>> (32 - k))) >>> 0; }
    function X() { this.s = new Uint32Array(4); }
    X.prototype.seed = function (hi, lo) {
      var x = (hi ^ Math.imul(lo, 0x9e3779b9)) >>> 0;
      for (var i = 0; i < 4; i++) {
        x = (x + 0x9e3779b9) >>> 0;
        var z = x;
        z = Math.imul(z ^ (z >>> 16), 0x85ebca6b) >>> 0;
        z = Math.imul(z ^ (z >>> 13), 0xc2b2ae35) >>> 0;
        this.s[i] = (z ^ (z >>> 16) ^ (i === 0 ? lo : i === 1 ? hi : 0)) >>> 0;
      }
      if (!(this.s[0] | this.s[1] | this.s[2] | this.s[3])) this.s[0] = 1;
    };
    X.prototype.next = function () {
      var s = this.s;
      var r = Math.imul(rotl(Math.imul(s[1], 5) >>> 0, 7), 9) >>> 0;
      var t = (s[1] << 9) >>> 0;
      s[2] ^= s[0]; s[3] ^= s[1]; s[1] ^= s[2]; s[0] ^= s[3]; s[2] ^= t; s[3] = rotl(s[3], 11);
      return r;
    };
    function fnv(str) {
      var h = 0x811c9dc5;
      for (var i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
      return h >>> 0;
    }
    var docKey = fnv(String(location.origin) + String(location.pathname));
    var M = new X(); M.seed(SEED_HI ^ docKey, SEED_LO);
    var C = new X(); C.seed(SEED_HI, (SEED_LO ^ docKey ^ 0x5bd1e995) >>> 0);
    var stats = { random: 0, crypto: 0, uuid: 0, digest: 0x811c9dc5 };
    function mix(v) { stats.digest = Math.imul((stats.digest ^ v) >>> 0, 0x01000193) >>> 0; }

    var random = function random() {
      var a = M.next() >>> 5;
      var b = M.next() >>> 6;
      stats.random++; mix(a);
      return (a * 67108864 + b) / 9007199254740992;
    };
    try { Object.defineProperty(Math, 'random', { value: random, writable: true, configurable: true }); } catch (e) { /* frozen */ }

    var C_PROTO = G.Crypto && G.Crypto.prototype;
    if (C_PROTO && typeof C_PROTO.getRandomValues === 'function') {
      var realGRV = C_PROTO.getRandomValues;
      var grv = function getRandomValues(arr) {
        if (!arr || !ArrayBuffer.isView(arr) || arr instanceof Float32Array || arr instanceof Float64Array) {
          return realGRV.call(this, arr); // let the browser throw its own TypeError
        }
        if (arr.byteLength > 65536) return realGRV.call(this, arr);
        var b = new Uint8Array(arr.buffer, arr.byteOffset, arr.byteLength);
        for (var i = 0; i < b.length; i += 4) {
          var v = C.next();
          for (var k = 0; k < 4 && i + k < b.length; k++) b[i + k] = (v >>> (8 * k)) & 0xff;
        }
        stats.crypto++; mix(b.length);
        return arr;
      };
      Object.defineProperty(C_PROTO, 'getRandomValues', { value: grv, writable: true, configurable: true });
      if (typeof C_PROTO.randomUUID === 'function') {
        var uuid = function randomUUID() {
          var b = new Uint8Array(16);
          for (var i = 0; i < 16; i += 4) { var v = C.next(); for (var k = 0; k < 4; k++) b[i + k] = (v >>> (8 * k)) & 0xff; }
          b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
          var h = [];
          for (var j = 0; j < 16; j++) h.push((b[j] + 0x100).toString(16).slice(1));
          stats.uuid++; mix(b[0]);
          return h.slice(0, 4).join('') + '-' + h.slice(4, 6).join('') + '-' + h.slice(6, 8).join('') + '-' + h.slice(8, 10).join('') + '-' + h.slice(10).join('');
        };
        Object.defineProperty(C_PROTO, 'randomUUID', { value: uuid, writable: true, configurable: true });
      }
    }
    // Workers created by the page: their main script URL is marked so that the worker process
    // (worker.js) prepends this seed script to it (request headers do not tell a worker script apart).
    ['Worker', 'SharedWorker'].forEach(function (name) {
      var Real = typeof window !== 'undefined' && G[name];
      if (typeof Real !== 'function') return;
      var Wrapped = function (u, o) {
        var s = u;
        try {
          var x = new URL(String(u && u.href ? u.href : u), location.href);
          if (x.protocol === 'http:' || x.protocol === 'https:') { x.searchParams.set('__detjs_w', '1'); s = x.href; }
        } catch (e) { s = u; }
        return new Real(s, o);
      };
      Wrapped.prototype = Real.prototype;
      try { Object.defineProperty(G, name, { value: Wrapped, writable: true, configurable: true }); } catch (e) { /* frozen */ }
    });
    Object.defineProperty(G, '__detjs', {
      value: { stats: function () { return { random: stats.random, crypto: stats.crypto, uuid: stats.uuid, digest: stats.digest.toString(16) }; } },
      enumerable: false,
    });
  })();
}

/** Source of the init script for one test (seed words from derive_seed). */
function pageInitSource(seedHi, seedLo) {
  return `(${pageInit.toString()})();`
    .replace('__SEED_HI__', String(seedHi >>> 0))
    .replace('__SEED_LO__', String(seedLo >>> 0));
}

module.exports = { pageInitSource };
