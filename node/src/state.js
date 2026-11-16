'use strict';
// Process-wide state shared by the controls and the runner shells.
const native = require('./native');
const sites = require('./sites');

const FS = '\u001f';
const RS = '\u001e';
const FLUSH_AT = 256;

class State {
  constructor() {
    this.config = null;
    this.recorder = null; // native.Recorder of the current test file (one trace part per file)
    this.testId = null; // id of the running test, null outside tests
    this.testIndex = 0;
    this.buffer = [];
    this.quietDepth = 0;
    this.onOtherEvent = null; // set by the clock (adaptive tick)
    this.onTestStart = [];
    this.onTestEnd = [];
    this.installed = [];
    this.notes = [];
  }

  /** Record one event of the running test. */
  record(source, op, value) {
    if (source !== 'time' && this.onOtherEvent) this.onOtherEvent();
    if (this.testId === null || this.quietDepth > 0 || this.recorder === null) return;
    let site = '';
    if (this.config.sites) {
      this.quietDepth++;
      try { site = sites.resolve(); } finally { this.quietDepth--; }
      if (site === null) return; // runner infrastructure
    }
    this.buffer.push(source + FS + op + FS + site + FS + value);
    if (this.buffer.length >= FLUSH_AT) this.flush();
  }

  /** Record with an explicit site (used by detjs itself). */
  recordAt(source, op, site, value) {
    if (this.testId === null || this.recorder === null) return;
    this.buffer.push(source + FS + op + FS + site + FS + value);
  }

  flush() {
    if (this.buffer.length && this.recorder) this.recorder.recordPacked(this.buffer.join(RS));
    this.buffer.length = 0;
  }

  /** Run fn without recording events (detjs' own use of patched APIs). */
  quiet(fn) {
    this.quietDepth++;
    try { return fn(); } finally { this.quietDepth--; }
  }

  beginTest(id) {
    if (this.testId !== null) this.endTest('interrupted');
    this.flush();
    if (this.recorder) this.recorder.beginTest(id, this.testIndex);
    this.testIndex++;
    this.testId = id;
    for (const f of this.onTestStart) f(id);
  }

  endTest(outcome) {
    if (this.testId === null) return null;
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
module.exports = { STATE, State };
