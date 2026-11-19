'use strict';
// Test-process side shared by the Bun and Deno preloads: the per-test bracket (trace part of the file, capture
// context) and the capture file written when the file is done. Runs inside the test runtime, one file per process.
const path = require('node:path');
const controls = require('../controls');
const clock = require('../clock');

const { STATE } = controls;

class Bracket {
  /** @param fileId path of the test file relative to the root; @param cap the capture (null without --det-cache) */
  constructor(fileId, cap) {
    this.fileId = fileId;
    this.cap = cap;
    this.cfg = controls.cfg();
    this.counts = new Map(); // id -> registrations seen (unique ids: `name #2`)
    this.current = null; // {id, t0}
    this.outcomes = [];
    this.done = false;
    this.anyFailed = false;
    this.t0 = clock.REAL.perfNow();
    controls.openFile(fileId, '');
    if (cap) {
      cap.resetFile();
      cap.setCtx('f', fileId);
    }
  }

  /** A unique id for a test registered as `parts` (describe names, then the test name). */
  register(parts) {
    const base = [this.fileId, ...parts].join('::');
    const n = (this.counts.get(base) || 0) + 1;
    this.counts.set(base, n);
    return n === 1 ? base : `${base} #${n}`;
  }

  begin(id) {
    if (this.current) this.end(this.current.id, 'interrupted');
    STATE.beginTest(id);
    this.current = { id, t0: clock.REAL.perfNow() };
    if (this.cap) this.cap.setCtx('t');
  }

  end(id, outcome) {
    if (!this.current || this.current.id !== id) return;
    const dur = (clock.REAL.perfNow() - this.current.t0) / 1000;
    this.current = null;
    const fp = STATE.endTest(outcome);
    if (outcome !== 'passed' && outcome !== 'skipped') this.anyFailed = true;
    this.outcomes.push([id, outcome]);
    if (this.cap) {
      this.cap.testEnd(id, outcome, dur, fp, this.modules ? this.modules() : undefined);
      this.cap.setCtx('f');
    }
  }

  /**
   * Wrap a test body so that it runs inside the bracket of `id`. Keeps the arity (runners look at `fn.length`
   * for a `done` callback) and the callback style.
   */
  wrap(id, fn) {
    if (typeof fn !== 'function') return fn;
    const self = this;
    const run = function (...args) {
      self.begin(id);
      if (fn.length > 0 && typeof args[0] === 'function' && self.doneStyle) {
        const done = args[0];
        args[0] = function (err) {
          self.end(id, err ? 'failed' : 'passed');
          return done.apply(this, arguments);
        };
        try {
          return fn.apply(this, args);
        } catch (e) {
          self.end(id, 'failed');
          throw e;
        }
      }
      let r;
      try {
        r = fn.apply(this, args);
      } catch (e) {
        self.end(id, 'failed');
        throw e;
      }
      if (r && typeof r.then === 'function') {
        return r.then((v) => { self.end(id, 'passed'); return v; }, (e) => { self.end(id, 'failed'); throw e; });
      }
      self.end(id, 'passed');
      return r;
    };
    Object.defineProperty(run, 'length', { value: fn.length });
    Object.defineProperty(run, 'name', { value: fn.name, configurable: true });
    return run;
  }

  /** The file is done (the runner's last hook ran): close the trace part, write the capture. */
  finish() {
    if (this.done) return;
    this.done = true;
    if (this.current) this.end(this.current.id, 'interrupted');
    controls.closeFile();
    const c = this.cfg;
    if (!this.cap || !c.dir) return;
    const cap = this.cap;
    try {
      const info = { fileId: this.fileId, project: '', label: this.fileId, ok: !this.anyFailed,
        duration: (clock.REAL.perfNow() - this.t0) / 1000, runtime: this.runtimeName || null };
      const capture = cap.fileCapture(info, this.modules ? this.modules() : undefined);
      if (this.extraCapture) Object.assign(capture, this.extraCapture());
      cap.busy++;
      try {
        STATE.quiet(() => controls.writeJson(path.join(c.dir, 'cache',
          `${controls.partName(this.fileId, '').replace(/\.jsonl$/, '')}-${process.pid}.json`), capture));
      } finally {
        cap.busy--;
      }
    } catch (e) {
      process.stderr.write(`detjs cache: capture of ${this.fileId} not written: ${e && e.stack}\n`);
    }
  }
}

module.exports = { Bracket };
