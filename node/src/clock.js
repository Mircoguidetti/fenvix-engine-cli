'use strict';
// Virtual clock and virtual timers.
//
// One virtual nanosecond counter drives every clock: each read advances it by
// a tick (adaptive, as in the Python shell: after `tickAdapt` consecutive
// reads with no other event every further read doubles the tick, up to 1 s),
// and timers advance it to their due time when they fire.
//
// * wall clock (`Date`, `Date.now`) restarts at the epoch for every test;
// * monotonic clocks (`performance.now`, `process.hrtime[.bigint]`) never go
//   backwards inside a realm; events record them relative to the test start.
//
// Timers (`setTimeout`, `setInterval`, `timers/promises.setTimeout`) are kept
// in one queue ordered by (virtual due time, creation sequence) and fired one
// per macrotask by a driver. While nothing but timers is pending (no socket,
// server, file request, child process or worker beyond those present when the
// test file started) the driver fires the next timer without waiting
// ("fast" mode, the analogue of the Python virtual sleep); as soon as real
// I/O is pending it waits for the real delay as well, so that the I/O can
// complete first (the analogue of the Python rule for sleeps while other
// threads are alive). A per-test budget of fast firings bounds intervals that
// are never cleared. `setImmediate` keeps the native FIFO order (already
// deterministic) and is recorded.
//
// Calls whose first non-Node, non-detjs frame belongs to the test runner
// (vitest, jest, tinypool, ...) get the real functions: runner timeouts and
// RPC timers keep real time (Python: pytest plugins keep real timers).

const { STATE } = require('./state');
const sites = require('./sites');

const NS_PER_MS = 1e6;
const MAX_TICK_NS = 1e9;
const MONO_BASE_NS = 1000 * 1e9; // arbitrary, positive, process independent
const TIMEOUT_MAX = 2 ** 31 - 1;

// Real functions, captured when this module is first loaded.
const REAL = {
  Date: globalThis.Date,
  setTimeout: globalThis.setTimeout,
  clearTimeout: globalThis.clearTimeout,
  setInterval: globalThis.setInterval,
  clearInterval: globalThis.clearInterval,
  setImmediate: globalThis.setImmediate,
  clearImmediate: globalThis.clearImmediate,
  hrtime: process.hrtime,
  hrtimeBigint: process.hrtime.bigint,
  perfNow: globalThis.performance.now.bind(globalThis.performance),
};
const realNowMs = () => REAL.perfNow();

class VirtualClock {
  constructor(epochNs, tickNs, adaptAfter) {
    this.epochMs = Number(epochNs / 1000000n);
    this.baseTick = tickNs;
    this.tick = tickNs;
    this.adaptAfter = adaptAfter;
    this.streak = 0;
    this.elapsed = 0; // ns since installation
    this.testStart = 0;
  }

  read() {
    this.elapsed += this.tick;
    if (this.adaptAfter) {
      this.streak += 1;
      if (this.streak >= this.adaptAfter) this.tick = Math.min(Math.max(1, this.tick) * 2, MAX_TICK_NS);
    }
    return this.elapsed;
  }

  otherEvent() {
    if (this.streak || this.tick !== this.baseTick) {
      this.streak = 0;
      this.tick = this.baseTick;
    }
  }

  advanceTo(ns) {
    if (ns > this.elapsed) this.elapsed = ns;
  }

  startTest() {
    this.streak = 0;
    this.tick = this.baseTick;
    this.testStart = this.elapsed;
  }

  wallMs(e) {
    return this.epochMs + (e - this.testStart) / NS_PER_MS;
  }

  rel(e) {
    return String(e - this.testStart);
  }
}

let CLOCK = null;

/** Site of the caller, or null for runner infrastructure (=> real behaviour). */
function callerIsInfra() {
  if (!STATE.config || !STATE.config.sites) return false;
  return STATE.quiet(() => sites.resolve()) === null;
}

// Clock reads ------------------------------------------------------------------
function readFor(op) {
  const e = CLOCK.read();
  STATE.record('time', op, CLOCK.rel(e));
  return e;
}

function makeDate(RealDate) {
  function Date(...args) {
    if (callerIsInfra()) {
      return new.target ? Reflect.construct(RealDate, args, new.target) : RealDate();
    }
    if (!new.target) return new RealDate(CLOCK.wallMs(readFor('Date()'))).toString();
    if (args.length === 0) return Reflect.construct(RealDate, [Math.floor(CLOCK.wallMs(readFor('new Date')))], new.target);
    return Reflect.construct(RealDate, args, new.target);
  }
  Date.prototype = RealDate.prototype;
  Object.defineProperty(Date, 'length', { value: 7 });
  Date.now = function now() {
    if (callerIsInfra()) return RealDate.now();
    return Math.floor(CLOCK.wallMs(readFor('Date.now')));
  };
  Date.parse = RealDate.parse;
  Date.UTC = RealDate.UTC;
  Date.toString = () => RealDate.toString();
  Date.__detjsReal = RealDate;
  return Date;
}

function monoNs(op) {
  return MONO_BASE_NS + readFor(op);
}

function performanceNow() {
  if (callerIsInfra()) return realNowMs();
  return monoNs('performance.now') / NS_PER_MS - MONO_BASE_NS / NS_PER_MS + 1000;
}

function hrtime(prev) {
  if (callerIsInfra()) return REAL.hrtime.call(process, prev);
  const ns = BigInt(Math.round(monoNs('process.hrtime')));
  let s = ns / 1000000000n;
  let n = ns % 1000000000n;
  if (Array.isArray(prev)) {
    s -= BigInt(prev[0]);
    n -= BigInt(prev[1]);
    if (n < 0n) { s -= 1n; n += 1000000000n; }
  }
  return [Number(s), Number(n)];
}
hrtime.bigint = function bigint() {
  if (callerIsInfra()) return REAL.hrtimeBigint.call(process);
  return BigInt(Math.round(monoNs('process.hrtime.bigint')));
};

// Timers ------------------------------------------------------------------------
let nextId = 1;
const BY_ID = new Map();

class Timeout {
  constructor(fn, args, delayMs, repeat, site) {
    this.id = nextId++;
    this._fn = fn;
    this._args = args;
    this._delayMs = delayMs;
    this._repeat = repeat;
    this._ref = true;
    this._site = site;
    this._due = 0;
    this._seq = 0;
    this._realDeadline = 0;
    this._active = false;
    this._destroyed = false;
  }
  ref() { this._ref = true; DRIVER.rearm(); return this; }
  unref() { this._ref = false; DRIVER.rearm(); return this; }
  hasRef() { return this._ref; }
  refresh() { if (this._active) { DRIVER.remove(this); DRIVER.schedule(this); } return this; }
  close() { DRIVER.clear(this); return this; }
  [Symbol.toPrimitive]() { return this.id; }
  [Symbol.dispose]() { DRIVER.clear(this); }
  get _onTimeout() { return this._fn; }
}

function normDelay(ms) {
  ms = Number(ms);
  if (!(ms >= 1 && ms <= TIMEOUT_MAX)) ms = 1;
  return ms;
}

class Driver {
  constructor() {
    this.queue = [];
    this.seq = 0;
    this.armed = null; // { kind: 'immediate'|'timeout', handle }
    this.fastFired = 0;
    this.budget = 100000;
    this.budgetHit = false;
    this.baseline = new Map();
    this.mode = 'virtual';
  }

  takeBaseline() {
    this.baseline = countResources();
  }

  ioPending() {
    const now = countResources();
    for (const [k, n] of now) if (n > (this.baseline.get(k) || 0)) return true;
    return false;
  }

  schedule(t) {
    t._due = CLOCK.elapsed + t._delayMs * NS_PER_MS;
    t._seq = this.seq++;
    t._realDeadline = realNowMs() + t._delayMs;
    t._active = true;
    BY_ID.set(t.id, t);
    // binary insertion by (due, seq)
    const q = this.queue;
    let lo = 0;
    let hi = q.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      const m = q[mid];
      if (m._due < t._due || (m._due === t._due && m._seq < t._seq)) lo = mid + 1; else hi = mid;
    }
    q.splice(lo, 0, t);
    this.rearm();
  }

  remove(t) {
    const i = this.queue.indexOf(t);
    if (i >= 0) this.queue.splice(i, 1);
    t._active = false;
  }

  clear(t) {
    if (!t || t._destroyed) return;
    this.remove(t);
    t._destroyed = true;
    BY_ID.delete(t.id);
    this.rearm();
  }

  fast() {
    return this.mode === 'virtual' && !this.budgetHit && !this.ioPending();
  }

  rearm() {
    if (this.armed) {
      const a = this.armed;
      this.armed = null;
      if (a.kind === 'immediate') REAL.clearImmediate(a.handle); else REAL.clearTimeout(a.handle);
    }
    if (!this.queue.length) return;
    const anyRef = this.queue.some((t) => t._ref);
    if (this.fast()) {
      const h = REAL.setImmediate(() => this.fire(true));
      if (!anyRef) h.unref();
      this.armed = { kind: 'immediate', handle: h };
    } else {
      const wait = Math.max(0, this.queue[0]._realDeadline - realNowMs());
      const h = REAL.setTimeout(() => this.fire(false), wait);
      if (!anyRef) h.unref();
      this.armed = { kind: 'timeout', handle: h };
    }
  }

  fire(fastMode) {
    this.armed = null;
    const t = this.queue.shift();
    if (!t) return;
    if (fastMode) {
      this.fastFired += 1;
      if (this.fastFired > this.budget && !this.budgetHit) {
        this.budgetHit = true;
        STATE.recordAt('time', 'timers.budget-exhausted', '<detjs>', String(this.budget));
      }
    }
    t._active = false;
    CLOCK.advanceTo(t._due);
    CLOCK.otherEvent();
    STATE.recordAt('time', t._repeat ? 'setInterval.fire' : 'setTimeout.fire', t._site, CLOCK.rel(t._due));
    if (!t._repeat) BY_ID.delete(t.id); // intervals are rescheduled after the callback
    try {
      t._fn.apply(undefined, t._args);
    } finally {
      if (t._repeat && !t._destroyed && !t._active) {
        const due = t._due + t._delayMs * NS_PER_MS;
        t._seq = this.seq++;
        t._due = due;
        t._realDeadline = realNowMs() + t._delayMs;
        t._active = true;
        const q = this.queue;
        let i = 0;
        while (i < q.length && (q[i]._due < due || (q[i]._due === due && q[i]._seq < t._seq))) i++;
        q.splice(i, 0, t);
      }
      this.rearm();
    }
  }

  startTest() {
    this.fastFired = 0;
    this.budgetHit = false;
    this.rearm();
  }
}

const IGNORED_RESOURCES = new Set(['Timeout', 'Immediate', 'TTYWrap']);

function countResources() {
  const m = new Map();
  for (const r of process.getActiveResourcesInfo()) {
    if (IGNORED_RESOURCES.has(r)) continue;
    m.set(r, (m.get(r) || 0) + 1);
  }
  return m;
}

const DRIVER = new Driver();

function makeSetTimeout(repeat) {
  const op = repeat ? 'setInterval' : 'setTimeout';
  const real = repeat ? REAL.setInterval : REAL.setTimeout;
  return function (fn, ms, ...args) {
    if (typeof fn !== 'function') return real(fn, ms, ...args); // native error message
    let site = '';
    if (STATE.config.sites) {
      site = STATE.quiet(() => sites.resolve());
      if (site === null) return real(fn, ms, ...args);
    }
    const delay = normDelay(ms);
    const t = new Timeout(fn, args, delay, repeat, site);
    CLOCK.otherEvent();
    STATE.record('time', op, String(delay * NS_PER_MS));
    DRIVER.schedule(t);
    return t;
  };
}

function makeClear(realClear) {
  return function (t) {
    if (t instanceof Timeout) return DRIVER.clear(t);
    if ((typeof t === 'number' || typeof t === 'string') && BY_ID.has(Number(t))) return DRIVER.clear(BY_ID.get(Number(t)));
    return realClear(t);
  };
}

function setImmediateRecorded(fn, ...args) {
  if (typeof fn === 'function' && STATE.testId !== null) STATE.record('time', 'setImmediate', '');
  return REAL.setImmediate(fn, ...args);
}

function promisesSetTimeout(ms, value, options = {}) {
  const signal = options && options.signal;
  if (signal && signal.aborted) return Promise.reject(abortError(signal));
  return new Promise((resolve, reject) => {
    const t = TIMERS.setTimeout(() => {
      if (signal) signal.removeEventListener('abort', onAbort);
      resolve(value);
    }, ms);
    if (options && options.ref === false && t && t.unref) t.unref();
    function onAbort() {
      TIMERS.clearTimeout(t);
      reject(abortError(signal));
    }
    if (signal) signal.addEventListener('abort', onAbort, { once: true });
  });
}

function abortError(signal) {
  const e = new Error('The operation was aborted', { cause: signal && signal.reason });
  e.name = 'AbortError';
  e.code = 'ABORT_ERR';
  return e;
}

const TIMERS = {
  setTimeout: makeSetTimeout(false),
  setInterval: makeSetTimeout(true),
  clearTimeout: makeClear(REAL.clearTimeout),
  clearInterval: makeClear(REAL.clearInterval),
  setImmediate: setImmediateRecorded,
};
for (const [name, fn] of Object.entries(TIMERS)) Object.defineProperty(fn, 'name', { value: name });

function wrapPerformance(hostPerf) {
  // A stand-in for the host `performance` object (Jest copies the host object
  // into every test context; patching it in place would change Jest's own timings).
  const out = Object.create(Object.getPrototypeOf(hostPerf));
  for (const k of ['mark', 'measure', 'clearMarks', 'clearMeasures', 'getEntries', 'getEntriesByName',
    'getEntriesByType', 'toJSON', 'timerify', 'eventLoopUtilization', 'markResourceTiming',
    'clearResourceTimings', 'setResourceTimingBufferSize', 'addEventListener', 'removeEventListener', 'dispatchEvent']) {
    if (typeof hostPerf[k] === 'function') out[k] = hostPerf[k].bind(hostPerf);
  }
  Object.defineProperty(out, 'timeOrigin', { get: () => hostPerf.timeOrigin, enumerable: true });
  Object.defineProperty(out, 'nodeTiming', { get: () => hostPerf.nodeTiming });
  out.now = performanceNow;
  return out;
}

/** Process-wide installation (once per process). */
function installProcess(patcher, cfg) {
  if (!CLOCK) {
    CLOCK = new VirtualClock(cfg.epochNs, cfg.tickNs, cfg.tickAdapt);
    if (cfg.tickAdapt) STATE.onOtherEvent = () => CLOCK.otherEvent();
    DRIVER.budget = cfg.timerBudget;
    DRIVER.mode = cfg.timers;
    STATE.onTestStart.push(() => { CLOCK.startTest(); DRIVER.startTest(); });
  }
  patcher.set(process, 'hrtime', hrtime);
  if (cfg.controls.has('timers')) {
    const timers = require('node:timers');
    const tp = require('node:timers/promises');
    for (const k of ['setTimeout', 'setInterval', 'clearTimeout', 'clearInterval', 'setImmediate']) patcher.set(timers, k, TIMERS[k]);
    patcher.set(tp, 'setTimeout', promisesSetTimeout);
  }
}

/** Installation into one realm (global object). */
function installRealm(patcher, g, cfg, { sameRealm }) {
  if (!(g.Date && g.Date.__detjsReal)) patcher.set(g, 'Date', makeDate(g.Date));
  if (g.performance) {
    if (sameRealm) patcher.define(g.performance, 'now', performanceNow);
    else patcher.set(g, 'performance', wrapPerformance(g.performance));
  }
  if (g.process && g.process !== process && typeof g.process.hrtime === 'function') {
    patcher.set(g.process, 'hrtime', hrtime); // Jest gives every context its own process object
  }
  if (cfg.controls.has('timers')) {
    for (const k of Object.keys(TIMERS)) patcher.set(g, k, TIMERS[k]);
  }
}

module.exports = {
  REAL, VirtualClock, installProcess, installRealm, TIMERS, DRIVER, Timeout,
  get CLOCK() { return CLOCK; },
};
