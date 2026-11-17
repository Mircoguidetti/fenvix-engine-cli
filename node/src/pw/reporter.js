'use strict';
// Playwright reporter added by `detjs playwright` (runs in the runner process):
// writes the shared trace of a Level 2 browser run, one test per Playwright
// test in execution order, with the events the worker recorded for it
// (<DETJS_DIR>/buckets/<testId>.jsonl: browser, network, app server) and the
// outcome as the last event. Same trace format and verifier as Level 0.
const fs = require('node:fs');
const path = require('node:path');
const native = require('../native');

const FS = '\u001f';
const RS = '\u001e';
const OUTCOME = { passed: 'passed', failed: 'failed', timedOut: 'failed', interrupted: 'error', skipped: 'skipped' };

class DetjsReporter {
  constructor() {
    this.order = [];
    this.results = new Map();
    this.root = process.env.DETJS_ROOT || process.cwd();
    this.dir = process.env.DETJS_DIR;
    this.trace = process.env.DETJS_PW_TRACE || path.join(this.root, '.detjs', 'trace.jsonl');
    this.meta = {};
    try { this.meta = JSON.parse(process.env.DETJS_PW_META || '{}'); } catch { this.meta = {}; }
  }

  printsToStdio() { return false; }

  onBegin(config) {
    this.pwVersion = config.version;
  }

  idOf(test) {
    const titles = test.titlePath().slice(3); // '', project, file, ...describes, title
    const file = path.relative(this.root, test.location.file).split(path.sep).join('/');
    const project = test.parent && test.parent.project ? test.parent.project().name : '';
    return `${file}::${titles.join('::')}${project ? ` [${project}]` : ''}`;
  }

  onTestBegin(test) {
    if (!this.results.has(test.id)) this.order.push(test);
  }

  onTestEnd(test, result) {
    if (!this.results.has(test.id) && !this.order.includes(test)) this.order.push(test);
    this.results.set(test.id, result);
  }

  async onEnd() {
    if (!this.dir) return;
    fs.mkdirSync(path.dirname(this.trace), { recursive: true });
    const rec = new native.Recorder(Number(process.env.DETJS_MAX_EVENTS || 10000));
    const ids = [];
    const seen = new Map();
    for (const t of this.order) {
      let id = this.idOf(t);
      const n = (seen.get(id) || 0) + 1;
      seen.set(id, n);
      if (n > 1) id = `${id} #${n}`;
      ids.push(id);
    }
    const meta = {
      ...this.meta,
      runtime: 'node',
      runtime_version: process.versions.node,
      runner: 'playwright',
      runner_version: this.pwVersion,
      level: 'L2-browser',
      serial: true,
      isolation: 'playwright --workers=1, fullyParallel off',
    };
    rec.open(this.trace, JSON.stringify(meta), ids);
    let i = 0;
    for (const t of this.order) {
      const id = ids[i];
      rec.beginTest(id, i);
      i++;
      const file = path.join(this.dir, 'buckets', `${t.id}.jsonl`);
      let lines = [];
      try { lines = fs.readFileSync(file, 'utf8').split('\n').filter(Boolean); } catch { /* no browser activity */ }
      const packed = [];
      for (const line of lines) {
        try {
          const [s, op, site, value] = JSON.parse(line);
          packed.push([s, op, site, value].join(FS));
        } catch { /* truncated line */ }
      }
      if (packed.length) rec.recordPacked(packed.join(RS));
      const r = this.results.get(t.id);
      rec.endTest(r ? OUTCOME[r.status] || r.status : 'error');
    }
    rec.close();
  }
}

module.exports = DetjsReporter;
