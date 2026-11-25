'use strict';
// P1 E (docs/DESIGN-P1.md section E): `fs.stat` / `fs.lstat` (src/outside.js) and `fs.readdir` (src/fsorder.js) events
// were recorded at the REAL completion of each call: those wrappers sat below src/ioorder.js, which delivers the
// completions of a test's concurrent file operations in start order, and fsorder.js even called the functions it had
// captured at require time, bypassing ioorder. Two runs with the same calls and the same answers then recorded them in
// different orders, a different fingerprint. E installs both above ioorder, fsorder wrapping what is installed then.
//
// protects=concurrent stat / lstat / readdir calls are recorded in the order the test started them, whatever order the
//   thread pool completes them in;
// fails_when=a batch of concurrent calls is recorded out of start order, or a stat answer that differs between two runs
//   (a file's size) is no longer seen by verify;
// no_claim=a completion released by the 200 ms hold (`io.release`) is in real order and stays NOT PROVEN.
// Second case (added after the per-item measurement showed the rest on claudekit): the lstat / readdir steps of Node's
// own recursive removal (fs.rm / fs.promises.rm, node:internal/fs/rimraf) are steps of that call, not observations
// of the test, and are not ordered; they were recorded in completion order. They are no longer recorded.
// Red on the trunk (e7338950): in 5 of 5 probe runs, 2 to 6 of the 12 batches were recorded out of order.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const native = require('../src/native');
const { fixture, crun, show } = require('./runner-helpers');

const T = { timeout: 600000 };
const N = 128;
const BODY = `import { test } from 'node:test'; import fs from 'node:fs'; import path from 'node:path';
test('t', async () => {
  const d = process.env.P1E_DIR; const names = []; const dirs = [];
  for (let i = 0; i < ${N}; i++) names.push(path.join(d, 'f' + String(i).padStart(3, '0')));
  for (let i = 0; i < 32; i++) dirs.push(path.join(d, 'd' + String(i).padStart(3, '0')));
  for (let k = 0; k < 4; k++) {
    await Promise.all(names.map((n) => fs.promises.stat(n)));
    await Promise.all(names.map((n) => new Promise((r) => fs.stat(n, r))));
    await Promise.all(names.map((n) => new Promise((r) => fs.lstat(n, r))));
    await Promise.all(dirs.map((n) => new Promise((r) => fs.readdir(n, r))));
    await Promise.all(dirs.map((n) => fs.promises.readdir(n)));
  }
});
`;

function setup() {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'p1e-'));
  for (let i = 0; i < N; i++) fs.writeFileSync(path.join(d, `f${String(i).padStart(3, '0')}`), 'x'.repeat(i));
  for (let i = 0; i < 32; i++) { fs.mkdirSync(path.join(d, `d${String(i).padStart(3, '0')}`)); fs.writeFileSync(path.join(d, `d${String(i).padStart(3, '0')}`, `e${i}`), ''); }
  return d;
}

function batches(dir) {
  for (const l of fs.readFileSync(path.join(dir, '.detjs', 'trace.jsonl'), 'utf8').split('\n')) {
    if (!l.startsWith('{"type":"test"')) continue;
    const ev = JSON.parse(l).events || [];
    const name = (e) => e.v.split('|')[0].split('/').pop();
    const stats = ev.filter((e) => e.o === 'fs.stat').map(name);
    const lists = ev.filter((e) => /^fs\.(promises\.)?readdir$/.test(e.o)).map(name);
    return { stats, lists };
  }
  return { stats: [], lists: [] };
}

test('P1 E: concurrent stat / lstat / readdir events are recorded in start order', T, () => {
  const dir = fixture('p1e', 'order', { 'tests/a.test.mjs': BODY });
  for (let run = 0; run < 3; run++) {
    const r = crun('node-test', dir, [], { cache: false, env: { P1E_DIR: setup() } });
    assert.equal(r.status, 0, show(r));
    const { stats, lists } = batches(dir);
    assert.equal(stats.length, N * 12, 'every stat is an event');
    assert.equal(lists.length, 32 * 8, 'every readdir is an event');
    for (let i = 0; i < stats.length; i += N) {
      const b = stats.slice(i, i + N);
      assert.deepEqual(b, [...b].sort(), `stat batch ${i / N} of run ${run} recorded out of start order`);
    }
    for (let i = 0; i < lists.length; i += 32) {
      const b = lists.slice(i, i + 32);
      assert.deepEqual(b, [...b].sort(), `readdir batch ${i / 32} of run ${run} recorded out of start order`);
    }
  }
});

// a stat answer that differs between the runs is still a divergence
test('P1 E: a file whose size differs between two runs is never called stable', T, () => {
  const dir = fixture('p1e', 'differs', { 'tests/a.test.mjs': BODY });
  const d = setup();
  const traces = [0, 1].map((i) => {
    // the same directory (the same P1E_DIR input): only the size of one file differs
    fs.writeFileSync(path.join(d, 'f007'), 'x'.repeat(7 + i));
    const r = crun('node-test', dir, [], { cache: false, env: { P1E_DIR: d } });
    assert.equal(r.status, 0, show(r));
    const p = path.join(dir, `t${i}.jsonl`);
    fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), p);
    return p;
  });
  const rep = JSON.parse(native.verify(traces));
  assert.equal(rep.summary.stable, 0, JSON.stringify(rep.tests));
});

test('P1 E: the internal steps of a recursive fs.rm are not recorded (only what the test itself observes)', T, () => {
  const body = `import { test } from 'node:test'; import fs from 'node:fs'; import path from 'node:path';
test('t', async () => {
  for (const k of ['p', 'c']) {
    const d = path.join(process.env.P1E_DIR, 'tree-' + k);
    for (let i = 0; i < 16; i++) { fs.mkdirSync(path.join(d, 'd' + i), { recursive: true }); for (let j = 0; j < 8; j++) fs.writeFileSync(path.join(d, 'd' + i, 'f' + j), 'x'); }
    if (k === 'p') await fs.promises.rm(d, { recursive: true });
    else await new Promise((r, e) => fs.rm(d, { recursive: true }, (x) => (x ? e(x) : r())));
  }
  await fs.promises.stat(process.env.P1E_DIR);
});
`;
  const dir = fixture('p1e', 'rm', { 'tests/a.test.mjs': body });
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'p1e-rm-'));
  const r = crun('node-test', dir, [], { cache: false, env: { P1E_DIR: d } });
  assert.equal(r.status, 0, show(r));
  const l = fs.readFileSync(path.join(dir, '.detjs', 'trace.jsonl'), 'utf8').split('\n').find((x) => x.startsWith('{"type":"test"'));
  const ev = JSON.parse(l).events || [];
  // the root's one stat (fs.rm validating its target, sequential) stays; the concurrent steps inside the tree go
  const inTree = ev.filter((e) => /^fs\.(stat|readdir|promises\.readdir)$/.test(e.o) && /tree-[pc]\//.test(e.v));
  assert.deepEqual(inTree.map((e) => `${e.o} ${e.v}`), [], 'the removal\'s own steps are not events');
  assert.ok(ev.some((e) => e.o === 'fs.stat'), 'the test\'s own stat is still an event');
});
