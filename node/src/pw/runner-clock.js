'use strict';
// Lockstep (round 4): the clock and timers of the Playwright runner (a test worker process) on the engine clock.
//
// Inside a test (Playwright's current test info is set: fixtures, hooks, the test function, teardown) every timer
// created in the worker is virtual: it is due at T + delay on the engine clock T and fires only when the
// coordinator (lockstep.js) reaches that instant. That covers the test code and Playwright itself: expect
// polling, actionability retries, action/expect/test timeouts, waitForTimeout. Outside tests (worker start,
// browser launch, worker fixtures) timers are the real ones.
//
// The worker's clocks follow the same rule without a jump at the switch:
//   * monotonic (performance.now, process.hrtime): real time outside tests; inside a test the value at the
//     test's start plus the engine time elapsed since (plus 1 us per read, so values strictly increase);
//   * wall (Date): inside a test epoch + T (+ the same per-read microseconds); outside, the real wall clock.
// So deadlines computed inside a test (Playwright's TimeoutManager, ProgressController) are virtual.
//
// Every timer created in a test is classified once, from its creation stack:
//   * `watchdog`: Playwright's test/hook timeout (TimeoutManager._updateTimeout): pending for the whole test,
//     it does not mean the runner waits on time;
//   * `lib`: created by a library outside Playwright (database pools, keep-alive agents): not a wait either;
//   * `wait`: anything else (test code sleeps, expect.poll / toPass intervals, Playwright retries).
// The coordinator advances time only while the runner waits on the engine (see lockstep.js).

const REAL = {
  setTimeout: globalThis.setTimeout,
  clearTimeout: globalThis.clearTimeout,
  setInterval: globalThis.setInterval,
  clearInterval: globalThis.clearInterval,
  setImmediate: globalThis.setImmediate,
  Date: globalThis.Date,
  perfNow: globalThis.performance.now.bind(globalThis.performance),
  hrtime: process.hrtime,
  hrtimeBigint: process.hrtime.bigint,
};
const NS_PER_MS = 1e6;
const TIMEOUT_MAX = 2 ** 31 - 1;

class VTimer {
  constructor(clock, fn, args, delay, repeat, kind, test) {
    this._clock = clock;
    this.id = clock.nextId++;
    this._fn = fn;
    this._args = args;
    this._delay = delay;
    this._repeat = repeat;
    this._kind = kind;
    this._test = test;
    this._due = 0;
    this._seq = 0;
    this._active = false;
    this._destroyed = false;
    this._ref = true;
    this._real = null; // the real timer once released at test end
  }
  ref() { this._ref = true; if (this._real && this._real.ref) this._real.ref(); return this; }
  unref() { this._ref = false; if (this._real && this._real.unref) this._real.unref(); return this; }
  hasRef() { return this._ref; }
  refresh() {
    if (this._real) { this._real.refresh(); return this; }
    if (this._active) { this._clock._remove(this); this._clock._schedule(this); }
    return this;
  }
  close() { this._clock.clear(this); return this; }
  [Symbol.toPrimitive]() { return this.id; }
  [Symbol.dispose]() { this._clock.clear(this); }
  get _onTimeout() { return this._fn; }
}

function normDelay(ms) {
  ms = Number(ms);
  if (!(ms >= 1 && ms <= TIMEOUT_MAX)) ms = 1;
  return ms;
}

function classify() {
  const prev = Error.stackTraceLimit;
  Error.stackTraceLimit = 14;
  const o = {};
  Error.captureStackTrace(o, classify);
  Error.stackTraceLimit = prev;
  const stack = String(o.stack || '');
  if (/_updateTimeout|timeoutManager/i.test(stack)) return 'watchdog';
  // Deadlines of one Playwright operation (action/expect/event timeouts): the operation waits for something.
  const head = stack.split('\n').slice(1, 9).join('\n');
  if (/ProgressController\.run|raceAgainstDeadline|rejectOnTimeout|pollAgainstDeadline.*deadline/.test(head)) return 'deadline';
  // Playwright's own bookkeeping (network-idle lifecycle, worker shutdown): not a wait of the runner.
  if (/_startNetworkIdleTimer|gracefullyCloseAndExit|gracefullyClose|_scheduleGC|heartbeat/i.test(head)) return 'lib';
  const frames = stack.split('\n').slice(1).map((l) => l.trim()).filter((l) => !/runner-clock\.js|node:internal|\(node:|^at new Promise|<anonymous>/.test(l));
  // First frame outside Node: a library unless it is Playwright or the project's own code.
  const first = frames.find((l) => /\//.test(l));
  if (!first) return 'wait';
  if (/[\\/]node_modules[\\/]/.test(first) && !/[\\/]node_modules[\\/](@playwright[\\/]test|playwright|playwright-core)[\\/]/.test(first)) return 'lib';
  if (process.env.DETJS_LS_STACKS) require('node:fs').appendFileSync(process.env.DETJS_LS_STACKS, `wait ${head.replace(/\n/g, ' | ')}\n`);
  return 'wait';
}

class RunnerClock {
  /**
   * @param {object} o
   * @param {() => (string|null)} o.currentTest  id of the running test, or null
   * @param {number} o.epochMs  wall clock of T = 0
   * @param {() => number} o.now  engine clock T in ns (from the coordinator)
   * @param {() => void} o.onActivity  called when a virtual timer is created or cleared
   */
  constructor(o) {
    this.currentTest = o.currentTest;
    this.epochMs = o.epochMs;
    this.engineNow = o.now;
    this.onActivity = o.onActivity || (() => {});
    this.nextId = 1;
    this.queue = [];
    this.byId = new Map();
    this.seq = 0;
    // Monotonic continuity: mono = monoAtSwitch + (real - realAtSwitch) outside tests,
    //                       mono = monoAtSwitch + (T - tAtSwitch) inside a test.
    this.inTest = false;
    this.monoAtSwitch = REAL.perfNow();
    this.realAtSwitch = REAL.perfNow();
    this.tAtSwitch = 0;
    this.lastT = -1;
    this.reads = 0;
    this.installed = false;
  }

  /** Track the current test; on a change, timers of the finished test become real. */
  sync() {
    const k = this.currentTest();
    const nowIn = k !== null;
    if (nowIn !== this.inTest) {
      const mono = this._mono(this.inTest);
      this.inTest = nowIn;
      this.monoAtSwitch = mono;
      this.realAtSwitch = REAL.perfNow();
      this.tAtSwitch = this.engineNow();
    }
    return k;
  }

  /** Sub-tick of the current engine instant: 1 us per clock read at the same T (values strictly increase). */
  _sub() {
    const t = this.engineNow();
    if (t !== this.lastT) { this.lastT = t; this.reads = 0; }
    this.reads += 1;
    return t + this.reads * 1000;
  }

  _mono(inTest) {
    if (!inTest) return this.monoAtSwitch + (REAL.perfNow() - this.realAtSwitch);
    return this.monoAtSwitch + (this._sub() - this.tAtSwitch) / NS_PER_MS;
  }

  monoMs() {
    this.sync();
    return this._mono(this.inTest);
  }

  wallMs() {
    this.sync();
    if (!this.inTest) return REAL.Date.now();
    return this.epochMs + this._sub() / NS_PER_MS;
  }

  // ------------------------------------------------------------ timers
  _schedule(t) {
    t._due = Math.ceil(this.engineNow() + t._delay * NS_PER_MS); // whole ns: the scheduler's clock is an integer
    t._seq = this.seq++;
    t._active = true;
    this.byId.set(t.id, t);
    const q = this.queue;
    let lo = 0;
    let hi = q.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      const m = q[mid];
      if (m._due < t._due || (m._due === t._due && m._seq < t._seq)) lo = mid + 1; else hi = mid;
    }
    q.splice(lo, 0, t);
  }

  _remove(t) {
    const i = this.queue.indexOf(t);
    if (i >= 0) this.queue.splice(i, 1);
    t._active = false;
  }

  clear(t) {
    if (!t || t._destroyed) return;
    if (t._real) { REAL.clearTimeout(t._real); REAL.clearInterval(t._real); t._real = null; }
    if (t._active) this.onActivity();
    this._remove(t);
    t._destroyed = true;
    this.byId.delete(t.id);
  }

  create(fn, ms, args, repeat) {
    const test = this.sync();
    if (typeof fn !== 'function' || test === null) return null;
    const t = new VTimer(this, fn, args, normDelay(ms), repeat, classify(), test);
    this._schedule(t);
    this.onActivity();
    return t;
  }

  /** Earliest due instant of a pending virtual timer (ns), or null. */
  nextDue() {
    return this.queue.length ? this.queue[0]._due : null;
  }

  /** Does the runner wait on time? (a pending virtual timer that is neither the test watchdog nor a library's) */
  waitingTimers() {
    let n = 0;
    for (const t of this.queue) if (t._kind === 'wait' || t._kind === 'deadline') n++;
    return n;
  }

  kinds() {
    const k = {};
    for (const t of this.queue) k[t._kind] = (k[t._kind] || 0) + 1;
    return k;
  }

  hasDue(tNs) {
    return this.queue.length > 0 && this.queue[0]._due <= tNs;
  }

  /** Fire every timer due at or before tNs, in (due, creation) order, one per macrotask. Returns the count. */
  async fireDue(tNs) {
    let n = 0;
    while (this.queue.length && this.queue[0]._due <= tNs) {
      const t = this.queue.shift();
      t._active = false;
      if (!t._repeat) this.byId.delete(t.id);
      n++;
      try {
        t._fn.apply(undefined, t._args);
      } catch (e) {
        // A timer callback that throws in Node is an uncaught exception: keep that behaviour.
        REAL.setImmediate(() => { throw e; });
      } finally {
        if (t._repeat && !t._destroyed && !t._active) {
          t._seq = this.seq++;
          t._due = Math.ceil(t._due + t._delay * NS_PER_MS);
          t._active = true;
          const q = this.queue;
          let i = 0;
          while (i < q.length && (q[i]._due < t._due || (q[i]._due === t._due && q[i]._seq < t._seq))) i++;
          q.splice(i, 0, t);
        }
      }
      // Microtasks and immediates of this callback run before the next timer (as in Node's timer phase).
      await new Promise((r) => REAL.setImmediate(r));
    }
    return n;
  }

  /** The test `key` ended: its pending timers become real timers with the virtual delay that remains. */
  releaseTest(key) {
    const leaked = this.queue.filter((t) => t._test === key);
    if (!leaked.length) return 0;
    this.queue = this.queue.filter((t) => t._test !== key);
    const now = this.engineNow();
    for (const t of leaked) {
      t._active = false;
      const remaining = Math.max(0, (t._due - now) / NS_PER_MS);
      const run = () => {
        if (t._destroyed) return;
        if (t._repeat) {
          t._real = REAL.setInterval(() => { if (!t._destroyed) t._fn.apply(undefined, t._args); }, t._delay);
          if (!t._ref && t._real.unref) t._real.unref();
        } else {
          t._destroyed = true;
          this.byId.delete(t.id);
        }
        t._fn.apply(undefined, t._args);
      };
      t._real = REAL.setTimeout(run, remaining);
      if (!t._ref && t._real.unref) t._real.unref();
    }
    return leaked.length;
  }

  // ------------------------------------------------------------ installation
  install() {
    if (this.installed) return;
    this.installed = true;
    const self = this;
    const mk = (repeat) => {
      const real = repeat ? REAL.setInterval : REAL.setTimeout;
      const f = function (fn, ms, ...args) {
        const t = self.create(fn, ms, args, repeat);
        return t || real(fn, ms, ...args);
      };
      Object.defineProperty(f, 'name', { value: repeat ? 'setInterval' : 'setTimeout' });
      return f;
    };
    const clr = (realClear) => function (t) {
      if (t instanceof VTimer) return self.clear(t);
      if ((typeof t === 'number' || typeof t === 'string') && self.byId.has(Number(t))) return self.clear(self.byId.get(Number(t)));
      return realClear(t);
    };
    const T = { setTimeout: mk(false), setInterval: mk(true), clearTimeout: clr(REAL.clearTimeout), clearInterval: clr(REAL.clearInterval) };
    // Node's own promisified setTimeout keeps its util.promisify.custom: give ours one.
    const util = require('node:util');
    const pSet = (ms, value, options = {}) => new Promise((resolve, reject) => {
      const signal = options && options.signal;
      if (signal && signal.aborted) { reject(abortError(signal)); return; }
      const t = T.setTimeout(() => { if (signal) signal.removeEventListener('abort', onAbort); resolve(value); }, ms);
      if (options && options.ref === false && t && t.unref) t.unref();
      function onAbort() { T.clearTimeout(t); reject(abortError(signal)); }
      if (signal) signal.addEventListener('abort', onAbort, { once: true });
    });
    Object.defineProperty(T.setTimeout, util.promisify.custom, { value: pSet });
    for (const k of Object.keys(T)) globalThis[k] = T[k];
    const timers = require('node:timers');
    for (const k of Object.keys(T)) timers[k] = T[k];
    try { require('node:timers/promises').setTimeout = pSet; } catch { /* read-only on some versions */ }

    // Clocks.
    const RealDate = REAL.Date;
    function DetDate(...a) {
      if (!new.target) return new RealDate(self.wallMs()).toString();
      if (a.length === 0) return Reflect.construct(RealDate, [Math.floor(self.wallMs())], new.target);
      return Reflect.construct(RealDate, a, new.target);
    }
    DetDate.prototype = RealDate.prototype;
    Object.defineProperty(DetDate, 'length', { value: 7 });
    DetDate.now = () => Math.floor(self.wallMs());
    DetDate.parse = RealDate.parse;
    DetDate.UTC = RealDate.UTC;
    DetDate.__detjsReal = RealDate;
    globalThis.Date = DetDate;
    Object.defineProperty(globalThis.performance, 'now', { value: () => self.monoMs(), writable: true, configurable: true });
    const hr = function hrtime(prev) {
      const ns = BigInt(Math.round(self.monoMs() * NS_PER_MS));
      let s = ns / 1000000000n;
      let n = ns % 1000000000n;
      if (Array.isArray(prev)) {
        s -= BigInt(prev[0]);
        n -= BigInt(prev[1]);
        if (n < 0n) { s -= 1n; n += 1000000000n; }
      }
      return [Number(s), Number(n)];
    };
    hr.bigint = () => BigInt(Math.round(self.monoMs() * NS_PER_MS));
    process.hrtime = hr;
  }
}

function abortError(signal) {
  const e = new Error('The operation was aborted', { cause: signal && signal.reason });
  e.name = 'AbortError';
  e.code = 'ABORT_ERR';
  return e;
}

module.exports = { RunnerClock, REAL, VTimer };
