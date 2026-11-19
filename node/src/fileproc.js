'use strict';
// Test-process side of the shells whose runner gives detjs no worker hooks of its own (`node --test`, Mocha):
// one object per test process that opens a test file (trace part, module-level seed, cache capture context),
// brackets its tests and, when the file is done, writes the file's cache capture for the main process
// (src/cache/proof.js reads <run dir>/cache/*.json, the same files the Vitest and Jest shells write).
const fs = require('node:fs');
const path = require('node:path');
const { performance } = require('node:perf_hooks');
const controls = require('./controls');

const { STATE } = controls;
const realNow = performance.now.bind(performance); // taken before the clock control replaces it

class FileProcess {
  /** `root`: project root; the cache capture is installed when the main process runs with --det-cache. */
  constructor(root) {
    this.root = root;
    this.c = controls.cfg();
    this.cap = null;
    this.fileId = null;
    this.t0 = 0;
    this.current = null; // {id, t0}
    this.counts = new Map(); // id -> occurrences (duplicate names get ` #n`)
    if (!this.c.active) return;
    controls.installProcess();
    controls.installRealm(globalThis, { sameRealm: true });
    if (process.env.DETJS_CACHE === '1') {
      this.cap = require('./cache/capture').CAPTURE;
      this.cap.install({ role: 'worker', root });
    }
  }

  get active() {
    return this.c.active;
  }

  fileIdOf(file) {
    return path.relative(this.root, path.resolve(file)).split(path.sep).join('/');
  }

  /** Start a test file (closes the previous one first: its capture is written). */
  open(fileId) {
    if (!this.c.active || this.fileId === fileId) return;
    if (this.fileId !== null) this.close({ ok: this.lastOk !== false });
    this.fileId = fileId;
    this.t0 = realNow();
    this.counts = new Map();
    controls.openFile(fileId, '');
    if (this.cap) {
      this.cap.resetFile();
      this.cap.setCtx('f', fileId);
    }
  }

  /** A unique id for a test of the open file (or of `fileId`) from its name path (run order numbers duplicates). */
  idFor(names, fileId = this.fileId) {
    const base = `${fileId}::${names.join('::')}`;
    const n = (this.counts.get(base) || 0) + 1;
    this.counts.set(base, n);
    return n === 1 ? base : `${base} #${n}`;
  }

  begin(id) {
    if (!this.c.active) return;
    if (this.current) this.end('interrupted');
    STATE.beginTest(id);
    this.current = { id, t0: realNow() };
    if (this.cap) this.cap.setCtx('t');
  }

  end(outcome) {
    if (!this.c.active || !this.current) return;
    const { id, t0 } = this.current;
    this.current = null;
    const fp = STATE.endTest(outcome);
    if (this.cap) {
      this.cap.testEnd(id, outcome, (realNow() - t0) / 1000, fp);
      this.cap.setCtx('f');
    }
  }

  /** Tests that never started (filtered, skipped by a failing hook): recorded as skipped. */
  skipped(id) {
    if (!this.c.active) return;
    this.begin(id);
    this.end('skipped');
  }

  /** End of the file: trace part flushed, cache capture written (`ok`: the runner saw no failure in the file). */
  close({ ok }) {
    if (!this.c.active || this.fileId === null) return;
    if (this.current) this.end('interrupted');
    controls.closeFile();
    const fileId = this.fileId;
    this.fileId = null;
    if (this.cap && this.c.dir) {
      try {
        const capture = this.cap.fileCapture({ fileId, project: '', label: fileId, ok: Boolean(ok), duration: (realNow() - this.t0) / 1000 });
        const dir = path.join(this.c.dir, 'cache');
        fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(path.join(dir, `${controls.partName(fileId, '').replace(/\.jsonl$/, '')}-${process.pid}.json`), JSON.stringify(capture));
      } catch (e) {
        process.stderr.write(`detjs cache: capture of ${fileId} not written: ${e && e.stack}\n`);
      }
      this.cap.resetFile();
      this.cap.setCtx('', '');
    }
  }
}

module.exports = { FileProcess, realNow };
