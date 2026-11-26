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
const sched = require('./sched');
const concur = require('./concur');

const NS_PER_MS = 1e6;
const MAX_TICK_NS = 1e9;
const MONO_BASE_NS = 1000 * 1e9; // arbitrary, positive, process independent
const TIMEOUT_MAX = 2 ** 31 - 1;

// The process' own clock functions, saved by the runner-deadline preload (src/deadline-preload.js) when it ran first.
const NATIVE = globalThis[Symbol.for('detjs.deadlineClock')] || null;

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
  uptime: process.uptime,
  hrtimeBigint: process.hrtime.bigint,
  perfNow: NATIVE ? NATIVE.perfNow : globalThis.performance.now.bind(globalThis.performance),
  dateNow: NATIVE ? NATIVE.dateNow : globalThis.Date.now,
  timeOrigin: globalThis.performance.timeOrigin,
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
    this.surplus = 0; // ns the adaptive tick added beyond the base tick (not charged to the runners' deadlines)
    this.testStart = 0;
  }

  read() {
    this.elapsed += this.tick;
    if (this.tick > this.baseTick) this.surplus += this.tick - this.baseTick;
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

  /** Virtual time charged to the runners' deadlines: the elapsed time without the adaptive tick's surplus. */
  charged() {
    return this.elapsed - this.surplus;
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
let onRead = null; // set by src/fstime.js: the virtual clock advanced (real -> virtual checkpoints)
function readFor(op) {
  concur.sync(); // a concurrent test reads its own clock
  const e = CLOCK.read();
  STATE.record('time', op, CLOCK.rel(e));
  if (onRead !== null) onRead(e);
  return e;
}

// Fake timers of the runners (Vitest's and Jest's `useFakeTimers`, `getRealSystemTime`) read "now" from the runner's
// own code, which gets the real clock: their fake clock would then start from the machine's time, a value that changes
// with every run and that the cache cannot key (audit G-0122, G-0142). Such reads get the virtual clock instead, and
// are recorded (the epoch becomes an input of the test).
const FAKE_CLOCK_FRAME = /\b(?:useFakeTimers|_toSinonFakeTimersConfig|getRealSystemTime|setSystemTime)\b/;
function fakeClockCaller() {
  if (!CLOCK) return false;
  const lim = Error.stackTraceLimit;
  Error.stackTraceLimit = 6;
  let st;
  try { st = new Error().stack || ''; } finally { Error.stackTraceLimit = lim; }
  return FAKE_CLOCK_FRAME.test(st);
}

/** Virtual wall-clock milliseconds for a fake clock's start, recorded as a clock read. */
function fakeNow(what = 'fakeTimers.now') {
  concur.sync();
  const e = CLOCK.read();
  STATE.recordAt('time', what, '<fake-timers>', CLOCK.rel(e));
  return Math.floor(CLOCK.wallMs(e));
}

/** Virtual wall-clock ms / ns for a clock Level 0 reaches in native code (HTTP Date, SQLite, WASI); null when the
 * clock is not installed. Recorded as a clock read `op` at the caller's site. */
function virtualNowMs(op) {
  return CLOCK ? Math.floor(CLOCK.wallMs(readFor(op))) : null;
}
function virtualNowNs(op, monotonic = false) {
  if (!CLOCK) return null;
  const e = readFor(op);
  return monotonic ? BigInt(Math.round(MONO_BASE_NS + e)) : BigInt(CLOCK.epochMs) * 1000000n + BigInt(Math.round(e - CLOCK.testStart));
}

function makeDate(RealDate) {
  function Date(...args) {
    if (callerIsInfra()) {
      if (fakeClockCaller()) {
        if (!new.target) return new RealDate(fakeNow('Date')).toString();
        if (args.length === 0) return Reflect.construct(RealDate, [fakeNow('Date')], new.target);
      }
      return new.target ? Reflect.construct(RealDate, args, new.target) : RealDate();
    }
    if (!new.target) return new RealDate(CLOCK.wallMs(readFor('Date'))).toString();
    if (args.length === 0) return Reflect.construct(RealDate, [Math.floor(CLOCK.wallMs(readFor('Date')))], new.target);
    return Reflect.construct(RealDate, args, new.target);
  }
  Date.prototype = RealDate.prototype;
  Object.defineProperty(Date, 'length', { value: 7 });
  Date.now = function now() {
    if (callerIsInfra()) return fakeClockCaller() ? fakeNow('Date.now') : (RealDate === REAL.Date ? REAL.dateNow() : RealDate.now());
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

// performance.now() counts from the start of the test file, as in a fresh
// realm: each Vitest/Jest file normally gets its own worker or context, whose
// time origin is near 0. Counting from the process start instead made the
// virtual value grow over a whole run (found on recharts: code comparing it
// with Vitest's fake requestAnimationFrame timestamps, which start at 0, looped
// in later files only: 40 tests broken in a full run, none in the file alone).
let FILE_ORIGIN_NS = 0;
function startFile() {
  if (!CLOCK) return;
  FILE_ORIGIN_NS = CLOCK.elapsed;
  // module-level code of a file sees the wall clock from the epoch, as in a fresh worker, whatever files ran before it
  // in this process (Vitest isolate=false and the vm pools, Jest in band; audit G-1475)
  CLOCK.startTest();
}

function performanceNow() {
  if (callerIsInfra()) return realNowMs();
  return (monoNs('performance.now') - MONO_BASE_NS - FILE_ORIGIN_NS) / NS_PER_MS + 1000;
}

// process.uptime(): seconds since the start of the test file on the virtual clock (as performance.now), plus one
// second, so that it is positive and grows (audit G-0135: it was the real uptime, unrecorded).
function uptime() {
  if (callerIsInfra()) return REAL.uptime.call(process);
  return (monoNs('process.uptime') - MONO_BASE_NS - FILE_ORIGIN_NS) / 1e9 + 1;
}

// performance.timeOrigin: the epoch (a constant of the run, like the clock it belongs to; G-0136)
function timeOrigin() {
  if (CLOCK) STATE.record('time', 'performance.timeOrigin', '0');
  return CLOCK ? CLOCK.epochMs : 0;
}

// performance.mark()/measure() without explicit times read the host's real clock: give them the virtual one (G-0137).
function wrapMark(realMark) {
  return function mark(name, opts) {
    if (callerIsInfra()) return realMark(name, opts);
    if (!opts || typeof opts !== 'object') return realMark(name, { startTime: performanceNow() });
    if (opts.startTime === undefined) return realMark(name, { ...opts, startTime: performanceNow() });
    return realMark(name, opts);
  };
}
function wrapMeasure(realMeasure) {
  return function measure(name, a, b) {
    if (callerIsInfra()) return realMeasure(name, a, b);
    if (a && typeof a === 'object') {
      if (a.end === undefined && a.duration === undefined) return realMeasure(name, { ...a, end: performanceNow() });
      return realMeasure(name, a);
    }
    if (b === undefined) return realMeasure(name, a === undefined ? { start: 0, end: performanceNow() } : { start: a, end: performanceNow() });
    return realMeasure(name, a, b);
  };
}

// AbortSignal.timeout(ms) on the virtual timers, so that it keeps its order relative to setTimeout (G-0138).
function makeAbortTimeout(realTimeout, AC, DOMEx, timers) {
  return function timeout(ms) {
    if (STATE.testId === null || callerIsInfra()) return realTimeout(ms);
    const c = new AC();
    const t = timers.setTimeout(() => {
      let reason;
      try { reason = new DOMEx('The operation was aborted due to timeout', 'TimeoutError'); } catch { reason = new Error('The operation was aborted due to timeout'); reason.name = 'TimeoutError'; }
      c.abort(reason);
    }, ms);
    if (t && typeof t.unref === 'function') t.unref();
    return c.signal;
  };
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
  constructor(fn, args, delayMs, repeat, site, realm) {
    this._realm = realm;
    this._test = STATE.testId;
    this._ctx = concur.store(); // a concurrent test's timer fires in its context (src/concur.js)
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
  ref() { this._ref = true; if (this._handle && this._handle.ref) this._handle.ref(); if (this._watch && this._watch.ref) this._watch.ref(); DRIVER.rearm(); return this; }
  unref() { this._ref = false; if (this._handle && this._handle.unref) this._handle.unref(); if (this._watch && this._watch.unref) this._watch.unref(); DRIVER.rearm(); return this; }
  hasRef() { return this._ref; }
  refresh() {
    if (this._deadline) { if (this._active) DRIVER.armDeadline(this); return this; }
    if (this._active) { DRIVER.remove(this); DRIVER.schedule(this); }
    return this;
  }
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
    this.released = new Set(); // timers a finished test left pending, now real timers (releaseTest)
    this.deadlines = new Set(); // the runners' test and hook timeouts of the running test (runner deadlines)
    this.safePending = new Map(); // P1 prototype: real safe-timer handle -> test id (safeAdd)
    this.progress = 0; // virtual timers fired so far (a runner deadline's real watchdog waits while it grows)
  }

  /** A released timer is due in real time and has not run yet: the event loop must run it first. */
  releasedDue() {
    if (!this.released.size) return false;
    const now = realNowMs();
    for (const t of this.released) {
      if (t._destroyed || t._ranReleased) { this.released.delete(t); continue; }
      if (t._realDeadline <= now + 1) return true;
    }
    return false;
  }

  takeBaseline() {
    sched.takeBaseline();
  }

  ioPending() {
    return sched.isPending() || this.safePending.size > 0;
  }

  // P3 S3 prototype (P1): a runner safe timer that a test started and that is not a runner deadline (Vitest's
  // vi.waitFor / expect.poll intervals and timeouts) is real-time work the test waits for: while one is pending the
  // virtual timers run at real pace (as with pending I/O), so a long virtual timer does not jump past the poll.
  safeAdd(h, testId) {
    this.safePending.set(h, testId);
    this.rearm();
  }

  safeDone(h) {
    if (this.safePending.delete(h)) this.rearm();
  }

  // Runner deadlines -----------------------------------------------------------------------------------------
  // The runners' own test and hook timeouts (Vitest's withTimeout / TaskDeadline, jest-circus' callAsyncCircusFn)
  // run on the virtual timers (audit G-0144, NODE.md J15): a test whose virtual time stays within its timeout passes
  // however long it takes in real time (CPU time is not virtual time), a test whose virtual time passes it fails with
  // the runner's own timeout error at that virtual instant. A deadline is never what makes virtual time jump: it
  // fires virtually only when a timer of the test due later would fire. A test that truly hangs (no timer left, or
  // waiting for I/O that never comes) is caught by the deadline's real watchdog: the runner's timeout in real time
  // with no virtual timer fired meanwhile. Which of the two decided is recorded (`runner.timeout virtual|real`).
  // Deadlines are charged the virtual time without the adaptive tick's surplus (a render loop reading the clock
  // thousands of times does not use up a test's timeout).

  deadline(fn, ms, realm) {
    const t = new Timeout(fn, [], ms, false, '<runner>', realm || REAL);
    t._deadline = true;
    t._active = true;
    this.deadlines.add(t);
    BY_ID.set(t.id, t);
    this.armDeadline(t);
    return t;
  }

  armDeadline(t) {
    t._dueCharged = CLOCK.charged() + t._delayMs * NS_PER_MS;
    t._progress = this.progress;
    if (t._watch) REAL.clearTimeout(t._watch);
    t._watch = REAL.setTimeout(() => this.watchdog(t), t._delayMs);
    if (!t._ref && t._watch.unref) t._watch.unref();
  }

  watchdog(t) {
    t._watch = null;
    if (t._destroyed || !t._active) return;
    if (this.progress !== t._progress) {
      // virtual time moved on meanwhile: the test is not hanging
      t._progress = this.progress;
      t._watch = REAL.setTimeout(() => this.watchdog(t), t._delayMs);
      if (!t._ref && t._watch.unref) t._watch.unref();
      return;
    }
    this.fireDeadline(t, 'real');
  }

  /** Virtual instant (elapsed ns) at which deadline t is due. */
  deadlineDue(t) {
    return t._dueCharged + CLOCK.surplus;
  }

  nextDeadline() {
    let best = null;
    for (const d of this.deadlines) if (best === null || d._dueCharged < best._dueCharged || (d._dueCharged === best._dueCharged && d.id < best.id)) best = d;
    return best;
  }

  /** Whether deadline t has passed on the virtual clock (Vitest's check after a test or hook returned). */
  deadlinePassed(t) {
    return t._destroyed || CLOCK.charged() >= t._dueCharged;
  }

  fireDeadline(t, how) {
    if (t._destroyed) return;
    this.deadlines.delete(t);
    if (t._watch) { REAL.clearTimeout(t._watch); t._watch = null; }
    t._active = false;
    t._destroyed = true;
    BY_ID.delete(t.id);
    if (how === 'virtual') CLOCK.advanceTo(this.deadlineDue(t));
    STATE.recordAt('time', 'runner.timeout', '<runner>', `${how}:${t._delayMs}`);
    if (how === 'real' && STATE.onRealClock) STATE.onRealClock('the runner timeout fired on its real watchdog');
    t._fn.apply(undefined, t._args);
  }

  schedule(t) {
    t._due = CLOCK.elapsed + t._delayMs * NS_PER_MS;
    t._seq = this.seq++;
    t._realDeadline = realNowMs() + t._delayMs;
    t._graced = false;
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
    if (t._deadline) {
      this.deadlines.delete(t);
      if (t._watch) { REAL.clearTimeout(t._watch); t._watch = null; }
      t._active = false;
      t._destroyed = true;
      BY_ID.delete(t.id);
      return;
    }
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
      // pending I/O: wait for the real delay, but look again every few ms: once the I/O has completed the timers
      // go back to fast time (local I/O first, then timers)
      const wait = Math.max(0, this.queue[0]._realDeadline - realNowMs());
      const h = REAL.setTimeout(() => this.fireSlow(), Math.min(wait, SLOW_POLL_MS));
      if (!anyRef) h.unref();
      this.armed = { kind: 'timeout', handle: h };
    }
  }

  /** A slow-mode wake-up: fire the first timer once its real delay (plus a grace for just-started I/O) passed. */
  fireSlow() {
    this.armed = null;
    const t = this.queue[0];
    if (!t) return;
    if (this.fast()) { this.rearm(); return; }
    const now = realNowMs();
    if (t._realDeadline > now) { this.rearm(); return; }
    if (this.mode === 'virtual' && !t._graced && freshIO !== null && freshIO()) {
      t._graced = true;
      t._realDeadline = now + sched.graceFor(t._delayMs);
      this.rearm();
      return;
    }
    this.fire(false);
  }

  fire(fastMode) {
    this.armed = null;
    // Fast time only jumps when the event loop is otherwise idle: while other
    // setImmediate callbacks are pending (React act() / scheduler chains), wait
    // for them as the real delay would (found on apollo-client: a mocked
    // response delayed 20 ms arrived before act() had flushed the previous
    // render). Bounded, so that a setImmediate loop cannot starve the timers.
    // The same for a timer an earlier test left pending, released to real time and now due: it would have run
    // before this one in a real run (found on wouter under bun test: happy-dom's batched hashchange timer).
    if (fastMode && this.deferrals < MAX_DEFERRALS && (pendingImmediates() > 0 || this.releasedDue())) {
      this.deferrals += 1;
      const h = REAL.setImmediate(() => this.fire(true));
      if (!this.queue.some((x) => x._ref)) h.unref();
      this.armed = { kind: 'immediate', handle: h };
      return;
    }
    this.deferrals = 0;
    const head = this.queue[0];
    if (!head) return;
    // fast time was decided when the timer was armed: I/O started since then (a connection the test opened in the
    // same tick) is waited for first
    if (fastMode && !this.fast()) { this.rearm(); return; }
    // a runner deadline due no later than the next timer fires first (on the virtual clock)
    if (this.deadlines.size) {
      const d = this.nextDeadline();
      if (this.deadlineDue(d) <= head._due) {
        try { this.fireDeadline(d, 'virtual'); } finally { this.rearm(); }
        return;
      }
    }
    const t = this.queue.shift();
    this.progress += 1;
    if (!fastMode && this.mode === 'virtual' && t._test === STATE.testId && STATE.testId !== null) {
      // chosen before I/O that is still pending: a decision real time made (Level 1, recorded)
      const p = sched.pending();
      if (p.length) sched.timerChosen(t._site, p.length);
    }
    if (fastMode) {
      this.fastFired += 1;
      if (this.fastFired > this.budget && !this.budgetHit) {
        this.budgetHit = true;
        STATE.recordAt('time', 'setTimeout', '<detjs>', `budget-exhausted:${this.budget}`);
      }
    }
    t._active = false;
    try {
      // a concurrent test's timer runs in its own context: its clock jumps, its events, its callback
      if (concur.active()) concur.within(t._ctx && !t._ctx.done ? t._ctx : undefined, () => this.runTimer(t));
      else this.runTimer(t);
    } finally {
      if (t._repeat && !t._destroyed && !t._active) {
        const due = t._due + t._delayMs * NS_PER_MS;
        t._seq = this.seq++;
        t._due = due;
        t._realDeadline = realNowMs() + t._delayMs;
        t._graced = false;
        t._active = true;
        const q = this.queue;
        let i = 0;
        while (i < q.length && (q[i]._due < due || (q[i]._due === due && q[i]._seq < t._seq))) i++;
        q.splice(i, 0, t);
      }
      this.rearm();
    }
  }

  /** Fire timer `t` in the running context: the clock jumps to its due time, the event, the callback. */
  runTimer(t) {
    CLOCK.advanceTo(t._due);
    CLOCK.otherEvent();
    STATE.recordAt('time', t._repeat ? 'setInterval' : 'setTimeout', t._site, `fire:${CLOCK.rel(t._due)}`);
    if (!t._repeat) BY_ID.delete(t.id); // intervals are rescheduled after the callback
    if (onRead !== null) onRead(CLOCK.elapsed);
    t._fn.apply(undefined, t._args);
  }

  /**
   * A test ended: its pending virtual timers become real timers of their realm
   * with the real delay that remains. Fast virtual time must not fire a timer
   * leaked by a finished test (it would fire at once, during the next test,
   * instead of later or never: jsdom clears its timers at teardown).
   */
  releaseTest(testId) {
    for (const d of [...this.deadlines]) if (d._test === testId) this.clear(d); // a runner leaves none behind
    for (const [h, id] of [...this.safePending]) if (id === testId) this.safePending.delete(h); // P1: no carry-over
    const leaked = this.queue.filter((t) => t._test === testId);
    if (!leaked.length) return 0;
    this.queue = this.queue.filter((t) => t._test !== testId);
    for (const t of leaked) {
      t._active = false;
      const remaining = Math.max(0, t._realDeadline - realNowMs());
      const R = t._realm;
      this.released.add(t);
      const run = () => {
        t._ranReleased = true;
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

const MAX_DEFERRALS = 1000;
const SLOW_POLL_MS = 25;
// set by src/ioorder.js: whether an operation of the running test that just started (a file operation, a connection
// waiting for its first data) is still pending (the grace of the slow mode)
let freshIO = null;

function pendingImmediates() {
  let n = 0;
  for (const r of process.getActiveResourcesInfo()) if (r === 'Immediate') n += 1;
  return n;
}


const DRIVER = new Driver();

// per-test state of a concurrent test (src/concur.js): its virtual clock and its fast-firing budget
concur.register({
  name: 'clock',
  save: () => (CLOCK ? { e: CLOCK.elapsed, t: CLOCK.tick, k: CLOCK.streak, s: CLOCK.surplus, ts: CLOCK.testStart, ff: DRIVER.fastFired, bh: DRIVER.budgetHit } : null),
  restore: (x) => {
    if (!x || !CLOCK) return;
    CLOCK.elapsed = x.e; CLOCK.tick = x.t; CLOCK.streak = x.k; CLOCK.surplus = x.s; CLOCK.testStart = x.ts;
    DRIVER.fastFired = x.ff; DRIVER.budgetHit = x.bh;
  },
});

function makeSetTimeout(repeat, R) {
  const op = repeat ? 'setInterval' : 'setTimeout';
  const real = repeat ? R.setInterval : R.setTimeout;
  return function (fn, ms, ...args) {
    // Outside tests (module level, beforeAll, teardown) timers stay the realm's own.
    if (typeof fn !== 'function' || STATE.testId === null) return real(fn, ms, ...args);
    let site = '';
    if (STATE.config.sites) {
      site = STATE.quiet(() => sites.resolve());
      if (site === null) {
        // the runner's own timer: its test or hook timeout runs on the virtual clock (jest-circus' callAsyncCircusFn
        // captures the realm's setTimeout; G-0144)
        if (!repeat && CLOCK && DRIVER.mode === 'virtual' && require('./deadline').isDeadlineCaller()) return DRIVER.deadline(() => fn(...args), normDelay(ms), R);
        return real(fn, ms, ...args);
      }
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

// timers/promises.setInterval(ms, value, {signal, ref}): an async iterator on the virtual timers (audit G-1432)
function promisesSetInterval(ms, value, options = {}) {
  const signal = options && options.signal;
  let fired = 0;
  let waiter = null;
  let done = false;
  let failure = null;
  const t = TIMERS.setInterval(() => {
    fired += 1;
    if (waiter) { const w = waiter; waiter = null; fired -= 1; w.resolve({ value, done: false }); }
  }, ms);
  if (options && options.ref === false && t && t.unref) t.unref();
  const stop = () => { if (!done) { done = true; TIMERS.clearInterval(t); } };
  const onAbort = () => {
    failure = abortError(signal);
    stop();
    if (waiter) { const w = waiter; waiter = null; w.reject(failure); }
  };
  if (signal) {
    if (signal.aborted) onAbort();
    else signal.addEventListener('abort', onAbort, { once: true });
  }
  return {
    [Symbol.asyncIterator]() { return this; },
    next() {
      if (failure) return Promise.reject(failure);
      if (done) return Promise.resolve({ value: undefined, done: true });
      if (fired > 0) { fired -= 1; return Promise.resolve({ value, done: false }); }
      return new Promise((resolve, reject) => { waiter = { resolve, reject }; });
    },
    return() {
      stop();
      if (signal) signal.removeEventListener('abort', onAbort);
      if (waiter) { const w = waiter; waiter = null; w.resolve({ value: undefined, done: true }); }
      return Promise.resolve({ value: undefined, done: true });
    },
  };
}

// timers/promises.setImmediate: recorded like the callback form (audit G-2169)
function makePromisesSetImmediate(real) {
  return function setImmediate(value, options) {
    if (STATE.testId !== null) STATE.record('time', 'setImmediate', '');
    return real(value, options);
  };
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
  if (typeof out.mark === 'function') out.mark = wrapMark(out.mark);
  if (typeof out.measure === 'function') out.measure = wrapMeasure(out.measure);
  Object.defineProperty(out, 'timeOrigin', { get: timeOrigin, enumerable: true });
  Object.defineProperty(out, 'nodeTiming', { get: () => hostPerf.nodeTiming });
  Object.defineProperty(out, 'now', { value: performanceNow, writable: true, configurable: true, enumerable: true });
  return out;
}

/** Process-wide installation (once per process). */
function installProcess(patcher, cfg) {
  if (!CLOCK) {
    CLOCK = new VirtualClock(cfg.epochNs, cfg.tickNs, cfg.tickAdapt);
    if (cfg.tickAdapt) STATE.onOtherEvent = () => CLOCK.otherEvent();
    DRIVER.budget = cfg.timerBudget;
    DRIVER.mode = cfg.timers;
    STATE.onTestStart.push(() => { CLOCK.startTest(); DRIVER.startTest(); sched.startTest(); });
    require('./deadline').installClockHook();
    STATE.onTestEnd.push((id) => { DRIVER.releaseTest(id); });
  }
  patcher.set(process, 'hrtime', hrtime);
  patcher.set(process, 'uptime', uptime);
  // clocks this process now reads virtually (the cache capture no longer counts them as real-clock reads)
  STATE.virtualClocks = ['process.uptime()', 'performance.timeOrigin', 'Intl.DateTimeFormat#format'];
  // The host's performance object is also `require('perf_hooks').performance` (Jest: a test file that imports it
  // gets the host object, not its context's wrapper; G-0141). Runner frames keep the real clock (callerIsInfra).
  const hp = globalThis.performance;
  if (hp && !hp.__detjsPerf) {
    patcher.define(hp, 'now', performanceNow);
    if (typeof hp.mark === 'function') patcher.define(hp, 'mark', wrapMark(hp.mark.bind(hp)));
    if (typeof hp.measure === 'function') patcher.define(hp, 'measure', wrapMeasure(hp.measure.bind(hp)));
    try {
      Object.defineProperty(hp, 'timeOrigin', { get() { return callerIsInfra() ? REAL.timeOrigin : timeOrigin(); }, configurable: true, enumerable: true });
    } catch { /* not configurable */ }
    Object.defineProperty(hp, '__detjsPerf', { value: true, configurable: true });
  }
  if (cfg.controls.has('timers') && typeof AbortSignal === 'function' && typeof AbortSignal.timeout === 'function' && !AbortSignal.timeout.__detjs) {
    const f = makeAbortTimeout(AbortSignal.timeout.bind(AbortSignal), AbortController, globalThis.DOMException, TIMERS);
    Object.defineProperty(f, '__detjs', { value: true });
    patcher.set(AbortSignal, 'timeout', f);
  }
  if (cfg.controls.has('timers')) {
    const timers = require('node:timers');
    const tp = require('node:timers/promises');
    for (const k of ['setTimeout', 'setInterval', 'clearTimeout', 'clearInterval', 'setImmediate']) patcher.set(timers, k, TIMERS[k]);
    patcher.set(tp, 'setTimeout', promisesSetTimeout);
    patcher.set(tp, 'setInterval', promisesSetInterval);
    if (typeof tp.setImmediate === 'function') patcher.set(tp, 'setImmediate', makePromisesSetImmediate(tp.setImmediate));
    // timers/promises.scheduler.wait / yield (audit G-1433)
    if (tp.scheduler && typeof tp.scheduler.wait === 'function') {
      const sch = tp.scheduler;
      const realYield = typeof sch.yield === 'function' ? sch.yield.bind(sch) : null;
      patcher.define(sch, 'wait', function wait(delay, options) { return promisesSetTimeout(delay, undefined, options); });
      if (realYield) patcher.define(sch, 'yield', function yield_() { if (STATE.testId !== null) STATE.record('time', 'setImmediate', ''); return realYield(); });
    }
    // Atomics.wait with a timeout blocks for real time: the virtual clock advances by the timeout when it times out
    // (audit G-2184)
    installAtomicsWait(patcher, globalThis);
  }
}

function installAtomicsWait(patcher, g) {
  const A = g.Atomics;
  if (!A || typeof A.wait !== 'function' || A.wait.__detjs) return;
  const real = A.wait;
  const w = function wait(ta, index, value, timeout) {
    const r = real.call(this, ta, index, value, timeout);
    if (STATE.testId !== null && CLOCK && Number.isFinite(Number(timeout)) && Number(timeout) > 0) {
      if (r === 'timed-out') CLOCK.advanceTo(CLOCK.elapsed + Number(timeout) * NS_PER_MS);
      STATE.record('time', 'Atomics.wait', `${r}:${Number(timeout)}`);
    }
    return r;
  };
  Object.defineProperty(w, '__detjs', { value: true });
  patcher.set(A, 'wait', w);
}

// Intl.DateTimeFormat#format() / formatToParts() without a date format "now" from V8's own clock: give them the
// virtual clock (same family as audit G-0135; the cache keyed it as a real-clock read, R-009).
function installIntlNow(g) {
  const I = g.Intl;
  const P = I && I.DateTimeFormat && I.DateTimeFormat.prototype;
  if (!P || P.__detjsIntlNow) return;
  const D = g.Date && g.Date.__detjsReal ? g.Date : null;
  const now = () => (D ? D.now() : (CLOCK ? Math.floor(CLOCK.wallMs(readFor('Intl.DateTimeFormat'))) : Date.now()));
  try {
    const d = Object.getOwnPropertyDescriptor(P, 'format');
    if (d && typeof d.get === 'function') {
      Object.defineProperty(P, 'format', {
        configurable: true, enumerable: d.enumerable,
        get() { const f = d.get.call(this); return function format(date) { return f(date === undefined && !callerIsInfra() ? now() : date); }; },
      });
    }
    const fp = P.formatToParts;
    if (typeof fp === 'function') {
      Object.defineProperty(P, 'formatToParts', {
        configurable: true, writable: true,
        value: function formatToParts(date) { return fp.call(this, date === undefined && !callerIsInfra() ? now() : date); },
      });
    }
    Object.defineProperty(P, '__detjsIntlNow', { value: true });
  } catch { /* frozen intrinsics */ }
}

/** Installation into one realm (global object). */
function installRealm(patcher, g, cfg, { sameRealm }) {
  if (!(g.Date && g.Date.__detjsReal)) patcher.set(g, 'Date', makeDate(g.Date));
  installIntlNow(g);
  if (g.performance) {
    if (sameRealm) patcher.define(g.performance, 'now', performanceNow);
    else patcher.set(g, 'performance', wrapPerformance(g.performance));
  }
  if (g.process && g.process !== process && typeof g.process.hrtime === 'function') {
    patcher.set(g.process, 'hrtime', hrtime); // Jest gives every context its own process object
    if (typeof g.process.uptime === 'function') patcher.set(g.process, 'uptime', uptime);
  }
  if (cfg.controls.has('timers')) installAtomicsWait(patcher, g); // each vm context has its own Atomics
  if (cfg.controls.has('timers') && g.AbortSignal && typeof g.AbortSignal.timeout === 'function' && !g.AbortSignal.timeout.__detjs) {
    const f = makeAbortTimeout(g.AbortSignal.timeout.bind(g.AbortSignal), g.AbortController || AbortController, g.DOMException || globalThis.DOMException, TIMERS);
    Object.defineProperty(f, '__detjs', { value: true });
    patcher.set(g.AbortSignal, 'timeout', f);
  }
  if (cfg.controls.has('timers') && sameRealm) require('./deadline').installVitest(g);
  if (cfg.controls.has('timers')) {
    // The realm's own timers (jsdom's window timers in a Jest jsdom environment)
    // serve the timers created outside tests and the ones released at test end.
    const R = {};
    for (const k of ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'setImmediate']) {
      R[k] = typeof g[k] === 'function' && !g[k].__detjs ? g[k].bind(g) : REAL[k];
    }
    const T = sameRealm ? TIMERS : makeTimers(R);
    for (const k of Object.keys(T)) {
      if (typeof g[k] !== 'function') continue; // a bare vm context has no timers: none are added
      Object.defineProperty(T[k], '__detjs', { value: true });
      patcher.set(g, k, T[k]);
    }
  }
}

module.exports = {
  virtualNowMs, virtualNowNs,
  REAL, VirtualClock, installProcess, installRealm, TIMERS, DRIVER, Timeout, startFile, fakeNow, normDelay, realNowMs,
  get CLOCK() { return CLOCK; },
  setOnRead(f) { onRead = f; },
  setFreshIO(f) { freshIO = f; },
};
