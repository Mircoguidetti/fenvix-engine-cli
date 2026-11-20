'use strict';
// Further clock and realm controls (audit G-1434, G-2167, G-2168).
//
// * Temporal.Now (Node 24+ with --harmony-temporal, later unflagged): `instant()` is the virtual clock (a clock read,
//   recorded like Date.now), `zonedDateTimeISO()`, `plainDateTimeISO()`, `plainDateISO()`, `plainTimeISO()` (and
//   the calendar forms of the older proposal: `zonedDateTime(cal, tz)`, `plainDateTime(cal, tz)`, `plainDate(cal, tz)`)
//   are derived from it; the time zone (`timeZoneId()` / `timeZone()`) is the pinned one (NODE.md 7b).
// * Buffer.allocUnsafe / allocUnsafeSlow: zero-filled under --det (their content was whatever the allocator left:
//   hashing an unfilled buffer differed run to run). `new SlowBuffer(n)` likewise.
// * ShadowRealm (--experimental-shadow-realm): a new realm gets the realm controls its globals allow: Math.random from
//   the test's seeded stream, Date and Date.now on the virtual clock (its global object is not reachable from
//   outside; the set-up code runs inside it and calls back into the controlled functions of the creating realm).
const { STATE } = require('./state');
const sites = require('./sites');

function infra() {
  if (!STATE.config || !STATE.config.sites) return false;
  return STATE.quiet(() => sites.resolve()) === null;
}

/** Virtual epoch nanoseconds (a clock read of the running test). */
function virtualEpochNs(op) {
  const clock = require('./clock');
  const C = clock.CLOCK;
  const e = C.read();
  STATE.record('time', op, C.rel(e));
  return BigInt(C.epochMs) * 1000000n + BigInt(Math.round(e - C.testStart));
}

function installTemporal(patcher, g) {
  const T = g.Temporal;
  const N = T && T.Now;
  if (!N || typeof N !== 'object' || N.__detjsTemporal) return;
  const clock = require('./clock');
  const real = {};
  for (const k of Object.getOwnPropertyNames(N)) if (typeof N[k] === 'function') real[k] = N[k].bind(N);
  const tzOf = (tz) => {
    if (tz !== undefined) return tz;
    if (real.timeZoneId) return real.timeZoneId();
    if (real.timeZone) return real.timeZone();
    return 'UTC';
  };
  const instant = (op) => T.Instant.fromEpochNanoseconds(virtualEpochNs(op));
  const zoned = (op, tz, cal) => {
    const i = instant(op);
    let z = typeof i.toZonedDateTimeISO === 'function' ? i.toZonedDateTimeISO(tzOf(tz)) : i.toZonedDateTime({ timeZone: tzOf(tz), calendar: 'iso8601' });
    if (cal !== undefined && typeof z.withCalendar === 'function') z = z.withCalendar(cal);
    return z;
  };
  const make = {
    instant: () => instant('Temporal.Now.instant'),
    zonedDateTimeISO: (tz) => zoned('Temporal.Now.zonedDateTimeISO', tz),
    plainDateTimeISO: (tz) => zoned('Temporal.Now.plainDateTimeISO', tz).toPlainDateTime(),
    plainDateISO: (tz) => zoned('Temporal.Now.plainDateISO', tz).toPlainDate(),
    plainTimeISO: (tz) => zoned('Temporal.Now.plainTimeISO', tz).toPlainTime(),
    // the older proposal's calendar forms (Node 24 --harmony-temporal)
    zonedDateTime: (cal, tz) => zoned('Temporal.Now.zonedDateTime', tz, cal),
    plainDateTime: (cal, tz) => zoned('Temporal.Now.plainDateTime', tz, cal).toPlainDateTime(),
    plainDate: (cal, tz) => zoned('Temporal.Now.plainDate', tz, cal).toPlainDate(),
  };
  for (const [k, f] of Object.entries(make)) {
    if (!real[k]) continue;
    const w = { [k](...a) { return !clock.CLOCK || infra() ? real[k](...a) : f(...a); } }[k];
    patcher.define(N, k, w);
  }
  Object.defineProperty(N, '__detjsTemporal', { value: true });
}

function installBuffer(patcher) {
  const B = Buffer;
  if (B.allocUnsafe.__detjsZero) return;
  const alloc = B.alloc;
  const au = function allocUnsafe(size) { return alloc(size); };
  Object.defineProperty(au, '__detjsZero', { value: true });
  const realSlow = B.allocUnsafeSlow;
  const slow = function allocUnsafeSlow(size) { const b = realSlow(size); b.fill(0); return b; };
  Object.defineProperty(slow, '__detjsZero', { value: true });
  patcher.set(B, 'allocUnsafe', au);
  patcher.set(B, 'allocUnsafeSlow', slow);
  try {
    const bmod = require('node:buffer');
    if (typeof bmod.SlowBuffer === 'function' && !bmod.SlowBuffer.__detjsZero) {
      const RealSlow = bmod.SlowBuffer;
      const SB = function SlowBuffer(size) { const b = RealSlow(size); b.fill(0); return b; };
      SB.prototype = RealSlow.prototype;
      Object.defineProperty(SB, '__detjsZero', { value: true });
      patcher.set(bmod, 'SlowBuffer', SB);
    }
  } catch { /* gone in newer Node */ }
}

const SHADOW_SETUP = `(random, now) => {
  Math.random = function random_() { return random(); };
  const D = Date;
  function Date_(...a) {
    if (!new.target) return new D(now()).toString();
    return a.length === 0 ? Reflect.construct(D, [now()], new.target) : Reflect.construct(D, a, new.target);
  }
  Date_.prototype = D.prototype;
  Object.defineProperty(D.prototype, 'constructor', { value: Date_, writable: true, configurable: true });
  Date_.now = function now_() { return now(); };
  Date_.parse = D.parse;
  Date_.UTC = D.UTC;
  globalThis.Date = Date_;
  return true;
}`;

function installShadowRealm(patcher, g) {
  const SR = g.ShadowRealm;
  if (typeof SR !== 'function' || SR.__detjsLevel0) return;
  const W = new Proxy(SR, {
    construct(target, args, nt) {
      const r = Reflect.construct(target, args, nt === W ? target : nt);
      if (STATE.config && STATE.config.active && !infra()) {
        try {
          const setup = r.evaluate(SHADOW_SETUP);
          // the creating realm's controlled functions (seeded Math.random, virtual Date.now), recorded there
          setup(() => g.Math.random(), () => g.Date.now());
        } catch (e) {
          STATE.recordAt('other', 'uncontrolled.level0', '<detjs>', `ShadowRealm: ${e && e.message}`);
        }
      }
      return r;
    },
    get(t, k, rcv) { return k === '__detjsLevel0' ? true : Reflect.get(t, k, rcv); },
  });
  patcher.set(g, 'ShadowRealm', W);
}

/**
 * Jest's legacy fake timers (`legacyFakeTimers: true`, `timers: 'legacy'`) saved the realm's timers when the
 * environment was built, before the controls: `useRealTimers()` then restored real timers (G-1468). They restore
 * the virtual ones instead.
 */
function virtualLegacyTimers(ft, g) {
  if (!ft || !ft._timerAPIs || typeof ft._timerAPIs !== 'object' || ft.__detjsVirtual) return;
  for (const k of ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'setImmediate', 'clearImmediate']) {
    if (typeof g[k] === 'function' && g[k].__detjs) ft._timerAPIs[k] = g[k];
  }
  try { Object.defineProperty(ft, '__detjsVirtual', { value: true }); } catch { /* ignore */ }
}

/** Process-wide part (Buffer). */
function installProcess(patcher) {
  if (STATE.__realmxHooked) return;
  STATE.__realmxHooked = true;
  installBuffer(patcher);
}

/** Per realm: Temporal.Now and ShadowRealm of global object g. */
function installRealm(patcher, g, cfg) {
  if (cfg.controls.has('time')) installTemporal(patcher, g);
  installShadowRealm(patcher, g);
}

module.exports = { installProcess, installRealm, virtualLegacyTimers };
