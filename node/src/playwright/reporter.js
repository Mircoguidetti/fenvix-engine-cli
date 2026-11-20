'use strict';
// Reporter added by `detjs playwright --det` (src/playwright/config.js), in Playwright Test's main process.
//
// preprocess (Playwright >= 1.56, before the tests are grouped and sent to the worker):
//   * test ids: `<file relative to the root>::<describe>::...::<title>` (` #2` for a duplicate in a file;
//     ` [<project>]` appended for a named project, as Playwright and the Block 1 harness name them), the ids of the
//     other detjs shells;
//   * order: files sorted by path, tests in declaration order; with a seed (--det-seed / --det-order-seed) the
//     hierarchical shuffle of the other shells (files -> describe blocks -> tests, native shuffleIndices);
//   * --det-order: the listed tests only, files and describe blocks in the order of their first listed test
//     (src/repro.js); --det-collect: the order is recorded and every test excluded;
//   * the map Playwright test id -> detjs id, read by the workers (src/playwright/worker.js) to bracket each test.
// onTestBegin / onTestEnd: the executed order, outcomes and errors (the per-file data src/repro.js merges).
const fs = require('node:fs');
const path = require('node:path');
const config = require('../config');
const native = require('../native');
const repro = require('../repro');

const ROOT = process.env.DETJS_ROOT || process.cwd();

function partName(fileId) {
  return `${native.digest(fileId).slice(0, 16)}.jsonl`;
}

function fileIdOf(file) {
  return path.relative(ROOT, file).split(path.sep).join('/');
}

function outcomeOf(status, expected) {
  if (status === 'skipped') return 'skipped';
  if (status === 'interrupted') return 'error';
  return status === expected ? 'passed' : 'failed';
}

function errorOf(e, phase) {
  if (!e) return ['unknown', phase, '', ''];
  const msg = String(e.message || e.value || '').replace(/\u001b\[[0-9;]*[A-Za-z]/g, '');
  const m = /^\s*([A-Za-z_$][\w$]*(?:Error|Exception))\b:?/.exec(msg);
  const name = m ? m[1] : 'Error';
  const body = msg.replace(new RegExp(`^\\s*${name}:\\s*`), '');
  const text = body.split('\n').map((l) => l.trim()).filter(Boolean).slice(0, 4).join(' / ').slice(0, 200);
  const where = e.location && e.location.file ? `${fileIdOf(e.location.file)}:${e.location.line}` : '';
  return [name, phase, text, where];
}

class DetjsReporter {
  constructor() {
    this.cfg = config.fromEnv();
    this.dir = process.env.DETJS_DIR || null;
    this.ids = new Map(); // Playwright test -> detjs id
    this.fileOf = new Map(); // detjs id -> fileId
    this.collected = new Map(); // fileId -> ids in run order
    this.begun = [];
    this.states = {};
    this.exceptions = {};
    this.fileErrors = {};
  }

  printsToStdio() {
    return false;
  }

  preprocess({ suite: root, testRun }) {
    if (!this.dir) return;
    const projects = root.suites || [];
    const multi = projects.filter((p) => p.allTests().length).length > 1;
    for (const p of projects) {
      for (const f of p.suites || []) {
        const fileId = fileIdOf(f.location ? f.location.file : f.title);
        const flat = [];
        const walk = (s, titles) => {
          for (const e of entries(s)) {
            if (isSuite(e)) walk(e, [...titles, e.title]);
            else flat.push([e, `${fileId}::${[...titles, e.title].join('::')}`]);
          }
        };
        walk(f, []);
        const unique = uniqueIds(flat.map(([, id]) => id));
        flat.forEach(([t], i) => {
          const id = repro.wf(p.title ? `${unique[i]} [${p.title}]` : unique[i]);
          this.ids.set(t, id);
          this.fileOf.set(id, fileId);
        });
      }
    }
    const c = this.cfg;
    const shuffle = c.shuffle && c.controls.has('order');
    const plan = repro.plan();
    for (const p of projects) {
      const files = entries(p);
      if (!Array.isArray(files)) throw new Error('detjs playwright: this Playwright has no suite entries (need Playwright Test >= 1.56)');
      const key = (f) => fileIdOf(f.location ? f.location.file : f.title);
      const sorted = [...files].sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0));
      let ordered = sorted;
      if (shuffle) {
        ordered = native.shuffleIndices(sorted.length, c.orderSeed, multi ? p.title : '').map((i) => sorted[i]);
        for (const f of ordered) shuffleTree(f, c.orderSeed, key(f));
      }
      files.splice(0, files.length, ...ordered);
    }
    if (plan) {
      for (const t of root.allTests()) {
        if (plan.index.has(this.ids.get(t))) continue;
        try { testRun.exclude(t); } catch { /* setup / teardown projects always run in full */ }
      }
      for (const p of root.suites || []) {
        repro.filterTree(entries(p), (t) => (isSuite(t) ? null : this.ids.get(t) || null), (t) => (isSuite(t) ? entries(t) : null), plan);
      }
    }
    for (const t of root.allTests()) {
      const id = this.ids.get(t);
      const fileId = this.fileOf.get(id);
      if (!this.collected.has(fileId)) this.collected.set(fileId, []);
      this.collected.get(fileId).push(id);
    }
    // rank: the position in the run order; the worker runs a file's tests by it (it loads the file again, in
    // declaration order)
    const rank = new Map(root.allTests().map((t, i) => [t, i]));
    const map = {};
    for (const [t, id] of this.ids) map[t.id] = { id, file: this.fileOf.get(id), rank: rank.has(t) ? rank.get(t) : null };
    fs.writeFileSync(path.join(this.dir, 'pw-ids.json'), JSON.stringify(map));
    if (process.env.DETJS_COLLECT === '1') {
      for (const p of root.suites || []) {
        for (const f of [...(p.suites || [])]) {
          try { testRun.exclude(f); } catch { /* setup / teardown projects */ }
        }
      }
    }
  }

  onTestBegin(test) {
    const id = this.ids.get(test);
    if (id && this.begun[this.begun.length - 1] !== id) this.begun.push(id);
  }

  onTestEnd(test, result) {
    const id = this.ids.get(test);
    if (!id) return;
    const o = outcomeOf(result.status, test.expectedStatus);
    this.states[id] = o;
    if ((o === 'failed' || o === 'error') && result.errors && result.errors.length) this.exceptions[id] = errorOf(result.errors[0], 'call');
    else delete this.exceptions[id];
  }

  onError(error) {
    const file = error && error.location && error.location.file;
    if (file) this.fileErrors[fileIdOf(file)] = errorOf(error, 'collect');
  }

  onEnd() {
    if (!this.dir) return;
    const files = new Set([...this.collected.keys(), ...Object.keys(this.fileErrors)]);
    for (const fileId of files) {
      const ids = this.collected.get(fileId) || [];
      const states = {};
      const exceptions = {};
      for (const id of ids) {
        if (id in this.states) states[id] = this.states[id];
        if (id in this.exceptions) exceptions[id] = this.exceptions[id];
      }
      repro.writeSide(this.dir, partName(fileId), { file: fileId, project: '', collected: ids, states, exceptions, file_error: this.fileErrors[fileId] || null });
    }
    fs.writeFileSync(path.join(this.dir, 'pw-run.json'), JSON.stringify({
      begun: this.begun,
      files: [...this.collected.keys(), ...Object.keys(this.fileErrors).filter((f) => !this.collected.has(f))],
    }));
  }
}

function entries(s) {
  return s && s._entries;
}

function isSuite(e) {
  return Array.isArray(e && e._entries);
}

function uniqueIds(ids) {
  const seen = new Map();
  return ids.map((id) => {
    const n = (seen.get(id) || 0) + 1;
    seen.set(id, n);
    return n === 1 ? id : `${id} #${n}`;
  });
}

/** The hierarchical shuffle of the other shells (controls.shuffleTree), on a Playwright file suite. */
function shuffleTree(s, seed, key) {
  const list = entries(s);
  const perm = native.shuffleIndices(list.length, seed, key);
  const out = perm.map((i) => list[i]);
  list.splice(0, list.length, ...out);
  for (const e of out) if (isSuite(e)) shuffleTree(e, seed, `${key}::${e.title}`);
}

module.exports = DetjsReporter;
module.exports.partName = partName;
