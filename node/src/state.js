'use strict';
// Process-wide state shared by the controls and the runner shells.
const native = require('./native');
const sites = require('./sites');
const { wire } = require('./wire');
const concur = require('./concur');

const { AsyncLocalStorage } = require('node:async_hooks');

// the site of the user call that started asynchronous work inside Node (fs.glob's directory reads): events of that
// work without a user frame of their own are given that site (audit G-1481)
const AMBIENT = new AsyncLocalStorage();
const FS = '\u001f';
const RS = '\u001e';
const FLUSH_AT = 256;

class State {
  constructor() {
    this.config = null;
    this.recorder = null; // native.Recorder of the current test file (one trace part per file)
    this._testId = null; // id of the running test, null outside tests (the `testId` accessor: concurrent tests)
    this.testIndex = 0;
    this.buffer = [];
    this.deferred = false; // a concurrent test: its events stay in its buffer until it ends (src/concur.js)
    this.quietDepth = 0;
    this.onOtherEvent = null; // set by the clock (adaptive tick)
    this.onTestStart = [];
    this.onTestEnd = [];
    this.installed = [];
    this.notes = [];
    this.onEvent = null; // set by the cache capture (src/cache/capture.js)
    this.onRealClock = null; // set by the cache capture: a read of a clock Level 0 does not virtualize
  }

  /** The running test: with concurrent tests running, the test whose asynchronous work is running (src/concur.js). */
  get testId() {
    concur.sync();
    return this._testId;
  }

  set testId(v) {
    this._testId = v;
  }

  /**
   * Record one event of the running test. `callSite`: the site resolved when the operation was started (an event
   * emitted later, from a callback or after an await, has no caller of its own on the stack: audit G-1481); used
   * unless it is `<node>` and the stack at the event names a better one.
   */
  record(source, op, value, callSite) {
    if (source !== 'time' && this.onOtherEvent) this.onOtherEvent();
    if (this.testId === null || this.quietDepth > 0 || this.recorder === null) {
      if (this.onEvent !== null && this.quietDepth === 0) this.onEvent(source, value, op);
      return;
    }
    let site = '';
    if (this.config.sites) {
      if (callSite !== undefined && callSite !== '<node>') site = callSite;
      else {
        this.quietDepth++;
        try { site = sites.resolve(); } finally { this.quietDepth--; }
        if (site === '<node>' && callSite !== undefined) site = callSite;
        if (site === '<node>') { const amb = AMBIENT.getStore(); if (amb !== undefined) site = amb; }
      }
      if (site === null) return; // runner infrastructure
    }
    if (this.onEvent !== null) this.onEvent(source, value, op);
    this.buffer.push(source + FS + op + FS + site + FS + value);
    if (this.buffer.length >= FLUSH_AT) this.flush();
  }

  /** Record with an explicit site (used by detjs itself). */
  recordAt(source, op, site, value) {
    if (this.onEvent !== null && this.quietDepth === 0) this.onEvent(source, value, op);
    if (this.testId === null || this.recorder === null) return;
    this.buffer.push(source + FS + op + FS + site + FS + value);
  }

  flush() {
    if (this.deferred) return; // a concurrent test's events are written when it ends
    if (this.buffer.length && this.recorder) this.recorder.recordPacked(this.buffer.join(RS));
    this.buffer.length = 0;
  }

  /** The site of the caller now, for an event recorded later (`record(..., callSite)`); undefined when not needed. */
  callSite() {
    if (this.testId === null || this.quietDepth > 0 || !this.config || !this.config.sites) return undefined;
    this.quietDepth++;
    try { return sites.resolve(); } finally { this.quietDepth--; }
  }

  /** Run fn (and the asynchronous work it starts) with `site` as the site of events that have no user frame. */
  withSite(site, fn) {
    if (site === undefined || site === null || site === '<node>') return fn();
    return AMBIENT.run(site, fn);
  }

  /** Run fn without recording events (detjs' own use of patched APIs). */
  quiet(fn) {
    this.quietDepth++;
    try { return fn(); } finally { this.quietDepth--; }
  }

  beginTest(id) {
    if (this.testId !== null) this.endTest('interrupted');
    this.flush();
    // the id as the core gets every string: well-formed, injectively (src/wire.js)
    if (this.recorder) this.recorder.beginTest(wire(id), this.testIndex);
    this.testIndex++;
    this.testId = id;
    for (const f of this.onTestStart) f(id);
  }

  /**
   * The per-test state of a concurrent test, set up the first time its context runs (src/concur.js): as a serial test
   * start, but its events stay in its own buffer.
   */
  initConcurrent(id) {
    this._testId = id;
    this.buffer = [];
    this.deferred = true;
    for (const f of this.onTestStart) f(id);
  }

  endTest(outcome) {
    if (this.testId === null) return null;
    if (this.deferred) {
      // a concurrent test: its hooks, the mark that it ran interleaved with others, then the test in one piece. (How
      // often it was resumed is not recorded: with a sibling waiting on real I/O it changes from run to run, while the
      // test's own events do not.)
      const id = this._testId;
      for (const f of this.onTestEnd) f(id);
      this.buffer.push(`sched${FS}sched.concurrent${FS}<detjs>${FS}interleaved`);
      let fp = null;
      if (this.recorder) {
        this.recorder.beginTest(wire(id), this.testIndex);
        if (this.buffer.length) this.recorder.recordPacked(this.buffer.join(RS));
        fp = this.recorder.endTest(outcome);
      }
      this.testIndex++;
      this.buffer = [];
      this._testId = null;
      this.deferred = false;
      return fp;
    }
    for (const f of this.onTestEnd) f(this.testId);
    this.flush();
    this.testId = null;
    return this.recorder ? this.recorder.endTest(outcome) : null;
  }

  digest(data) {
    return native.digest(data);
  }

  digestNames(names) {
    const parts = names.map((n) => (Buffer.isBuffer(n) ? n : Buffer.from(String(n), 'utf8')));
    const joined = [];
    parts.forEach((p, i) => { if (i) joined.push(Buffer.from([0])); joined.push(p); });
    return native.digest(Buffer.concat(joined));
  }
}

const KEY = Symbol.for('detjs.state');
const STATE = globalThis[KEY] || (globalThis[KEY] = new State());
if (!STATE.__concurRegistered) {
  STATE.__concurRegistered = true;
  concur.register({
    name: 'state',
    save: () => ({ t: STATE._testId, b: STATE.buffer, d: STATE.deferred }),
    restore: (x) => { STATE._testId = x.t; STATE.buffer = x.b; STATE.deferred = x.d; },
  });
}
module.exports = { STATE, State };
