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
  constructor(epochNs, tickNs, adaptAfter, wallReset = true) {
    this.epochMs = Number(epochNs / 1000000n);
    this.wallReset = wallReset; // false for long-lived app servers (Level 2 browser): one wall clock for the run
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
    return this.epochMs + (e - (this.wallReset ? this.testStart : 0)) / NS_PER_MS;
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
// Level 2 app servers scope clock values to the message being handled (pw/server.js): the hook
// returns { e: elapsed ns, rel: recorded value } or null for the default single counter.
let VALUE_HOOK = null;
function setValueHook(f) { VALUE_HOOK = f; }

function readFor(op) {
  if (VALUE_HOOK) {
    const r = VALUE_HOOK(op);
    if (r) {
      STATE.record('time', op, r.rel);
      return r.e;
    }
  }
  const e = CLOCK.read();
  STATE.record('time', op, CLOCK.rel(e));
  return e;
}

function makeDate(RealDate) {
  function Date(...args) {
    if (callerIsInfra()) {
      return new.target ? Reflect.construct(RealDate, args, new.target) : RealDate();
    }
    if (!new.target) return new RealDate(CLOCK.wallMs(readFor('Date'))).toString();
    if (args.length === 0) return Reflect.construct(RealDate, [Math.floor(CLOCK.wallMs(readFor('Date')))], new.target);
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

let TIMER_CTX_HOOK = null; // Level 2 servers: the message context a timer was created in (pw/server.js)
function setTimerContextHook(f) { TIMER_CTX_HOOK = f; }

class Timeout {
  constructor(fn, args, delayMs, repeat, site, realm) {
    this._realm = realm;
    this._ctx = TIMER_CTX_HOOK ? TIMER_CTX_HOOK() : null;
    this._test = STATE.testId;
    this._handle = null; // realm timer once the timer was released to real time
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
  ref() { this._ref = true; if (this._handle && this._handle.ref) this._handle.ref(); DRIVER.rearm(); return this; }
  unref() { this._ref = false; if (this._handle && this._handle.unref) this._handle.unref(); DRIVER.rearm(); return this; }
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
    this.deferrals = 0;
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
    if (t._handle) {
      t._realm.clearTimeout(t._handle);
      t._realm.clearInterval(t._handle);
      t._handle = null;
    }
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
    // Fast time only jumps when the event loop is otherwise idle: while other
    // setImmediate callbacks are pending (React act() / scheduler chains), wait
    // for them as the real delay would (found on apollo-client: a mocked
    // response delayed 20 ms arrived before act() had flushed the previous
    // render). Bounded, so that a setImmediate loop cannot starve the timers.
    if (fastMode && this.deferrals < MAX_DEFERRALS && pendingImmediates() > 0) {
      this.deferrals += 1;
      const h = REAL.setImmediate(() => this.fire(true));
      if (!this.queue.some((x) => x._ref)) h.unref();
      this.armed = { kind: 'immediate', handle: h };
      return;
    }
    this.deferrals = 0;
    const t = this.queue.shift();
    if (!t) return;
    if (fastMode) {
      this.fastFired += 1;
      if (this.fastFired > this.budget && !this.budgetHit) {
        this.budgetHit = true;
        STATE.recordAt('time', 'setTimeout', '<detjs>', `budget-exhausted:${this.budget}`);
      }
    }
    t._active = false;
    CLOCK.advanceTo(t._due);
    CLOCK.otherEvent();
    // With scoped values (Level 2 servers) the global counter is not part of the fingerprint: the delay is.
    STATE.recordAt('time', t._repeat ? 'setInterval' : 'setTimeout', t._site, VALUE_HOOK ? `fire+${t._delayMs * NS_PER_MS}` : `fire:${CLOCK.rel(t._due)}`);
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

  /**
   * A test ended: its pending virtual timers become real timers of their realm
   * with the real delay that remains. Fast virtual time must not fire a timer
   * leaked by a finished test (it would fire at once, during the next test,
   * instead of later or never: jsdom clears its timers at teardown).
   */
  releaseTest(testId) {
    const leaked = this.queue.filter((t) => t._test === testId);
    if (!leaked.length) return 0;
    this.queue = this.queue.filter((t) => t._test !== testId);
    for (const t of leaked) {
      t._active = false;
      const remaining = Math.max(0, t._realDeadline - realNowMs());
      const R = t._realm;
      const run = () => {
        if (t._destroyed) return;
        if (t._repeat) {
          t._handle = R.setInterval(() => { if (!t._destroyed) t._fn.apply(undefined, t._args); }, t._delayMs);
          if (!t._ref && t._handle && t._handle.unref) t._handle.unref();
        } else {
          t._destroyed = true;
          BY_ID.delete(t.id);
        }
        t._fn.apply(undefined, t._args);
      };
      t._handle = R.setTimeout(run, remaining);
      if (!t._ref && t._handle && t._handle.unref) t._handle.unref();
    }
    this.rearm();
    return leaked.length;
  }

  /** Cancel every pending virtual timer. */
  clearAll() {
    const n = this.queue.length;
    for (const t of this.queue) {
      t._active = false;
      t._destroyed = true;
      BY_ID.delete(t.id);
    }
    this.queue = [];
    this.rearm();
    return n;
  }

  startTest() {
    this.fastFired = 0;
    this.budgetHit = false;
    this.rearm();
  }
}

const IGNORED_RESOURCES = new Set(['Timeout', 'Immediate', 'TTYWrap']);

const MAX_DEFERRALS = 1000;

function pendingImmediates() {
  let n = 0;
  for (const r of process.getActiveResourcesInfo()) if (r === 'Immediate') n += 1;
  return n;
}

function countResources() {
  const m = new Map();
  for (const r of process.getActiveResourcesInfo()) {
    if (IGNORED_RESOURCES.has(r)) continue;
    m.set(r, (m.get(r) || 0) + 1);
  }
  return m;
}

const DRIVER = new Driver();

function makeSetTimeout(repeat, R) {
  const op = repeat ? 'setInterval' : 'setTimeout';
  const real = repeat ? R.setInterval : R.setTimeout;
  return function (fn, ms, ...args) {
    // Outside tests (module level, beforeAll, teardown) timers stay the realm's own.
    if (typeof fn !== 'function' || STATE.testId === null) return real(fn, ms, ...args);
    let site = '';
    if (STATE.config.sites) {
      site = STATE.quiet(() => sites.resolve());
      if (site === null) return real(fn, ms, ...args);
    }
    const delay = normDelay(ms);
    const t = new Timeout(fn, args, delay, repeat, site, R);
    CLOCK.otherEvent();
    STATE.record('time', op, `schedule:${delay * NS_PER_MS}`);
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

function makeTimers(R) {
  const T = {
    setTimeout: makeSetTimeout(false, R),
    setInterval: makeSetTimeout(true, R),
    clearTimeout: makeClear(R.clearTimeout),
    clearInterval: makeClear(R.clearInterval),
    setImmediate: setImmediateRecorded,
  };
  for (const [name, fn] of Object.entries(T)) Object.defineProperty(fn, 'name', { value: name });
  return T;
}

const TIMERS = makeTimers(REAL);


function wrapPerformance(hostPerf) {
  // A stand-in for the host `performance` object (Jest copies the host object
  // into every test context; patching it in place would change Jest's own timings).
  const out = Object.create(Object.getPrototypeOf(hostPerf));
  for (const k of ['mark', 'measure', 'clearMarks', 'clearMeasures', 'getEntries', 'getEntriesByName',
    'getEntriesByType', 'toJSON', 'timerify', 'eventLoopUtilization', 'markResourceTiming',
    'clearResourceTimings', 'setResourceTimingBufferSize', 'addEventListener', 'removeEventListener', 'dispatchEvent']) {
    if (typeof hostPerf[k] === 'function') {
      // defineProperty: on some Node versions the prototype methods are read-only
      Object.defineProperty(out, k, { value: hostPerf[k].bind(hostPerf), writable: true, configurable: true });
    }
  }
  Object.defineProperty(out, 'timeOrigin', { get: () => hostPerf.timeOrigin, enumerable: true });
  Object.defineProperty(out, 'nodeTiming', { get: () => hostPerf.nodeTiming });
  Object.defineProperty(out, 'now', { value: performanceNow, writable: true, configurable: true, enumerable: true });
  return out;
}

/** Process-wide installation (once per process). */
function installProcess(patcher, cfg) {
  if (!CLOCK) {
    CLOCK = new VirtualClock(cfg.epochNs, cfg.tickNs, cfg.tickAdapt, cfg.wallReset !== false);
    if (cfg.tickAdapt) STATE.onOtherEvent = () => CLOCK.otherEvent();
    DRIVER.budget = cfg.timerBudget;
    DRIVER.mode = cfg.timers;
    STATE.onTestStart.push(() => { CLOCK.startTest(); DRIVER.startTest(); });
    STATE.onTestEnd.push((id) => { DRIVER.releaseTest(id); });
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
    // The realm's own timers (jsdom's window timers in a Jest jsdom environment)
    // serve the timers created outside tests and the ones released at test end.
    const R = {};
    for (const k of ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'setImmediate']) {
      R[k] = typeof g[k] === 'function' && !g[k].__detjs ? g[k].bind(g) : REAL[k];
    }
    const T = sameRealm ? TIMERS : makeTimers(R);
    for (const k of Object.keys(T)) {
      Object.defineProperty(T[k], '__detjs', { value: true });
      patcher.set(g, k, T[k]);
    }
  }
}

module.exports = {
  REAL, VirtualClock, installProcess, installRealm, TIMERS, DRIVER, Timeout, setValueHook, setTimerContextHook,
  get CLOCK() { return CLOCK; },
};
