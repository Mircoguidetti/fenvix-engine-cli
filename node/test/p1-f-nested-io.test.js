'use strict';
// P1 F (docs/DESIGN-P1.md section F): one awaited file call is one operation for the I/O ordering (src/ioorder.js),
// not several overlapping ones. The steps an operation takes itself -- the engine's own mkdtemp calling mkdir
// (src/facts.js), Node's callback writeFile calling the exported fs.open / fs.write / fs.close, graceful-fs's
// global fs.close wrapper called from inside writeFile -- were tracked as operations of the test: the test was marked
// `uncontrolled.io` (NOT PROVEN) and a step queued behind its own parent waited for the 200 ms hold (`io.release`).
//
// protects=a sequentially awaited file call never makes a test NOT PROVEN, nor waits for the hold;
// fails_when=a test that awaits each call (mkdtemp, writeFile, appendFile, graceful-fs writeFile) carries
//   `uncontrolled.io` or `io.release`, or two truly concurrent reads no longer carry `uncontrolled.io`;
// no_claim=network I/O (a connection overlapping a file operation) is not covered here.
// Red on the trunk (e7338950): the sequential tests carry `uncontrolled.io` (and writeFile `io.release`).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { fixture, crun, show } = require('./runner-helpers');

const T = { timeout: 300000 };
const GFS = JSON.stringify(require.resolve('graceful-fs'));
const HEAD = `import { test } from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
const gfs = createRequire(import.meta.url)(${GFS});
const cb = (f) => new Promise((res, rej) => f((e, v) => (e ? rej(e) : res(v))));
`;
const CASES = {
  'mkdtemp (the engine names it, through mkdir)': `test('t', async () => { await fs.promises.mkdtemp(path.join(os.tmpdir(), 'p1f-')); });`,
  'callback writeFile (open, write, close inside)': `test('t', async () => { const d = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'p1f-')); await cb((k) => fs.writeFile(path.join(d, 'a'), 'x', k)); });`,
  'callback appendFile (writeFile inside)': `test('t', async () => { const d = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'p1f-')); await cb((k) => fs.appendFile(path.join(d, 'a'), 'x', k)); });`,
  'graceful-fs writeFile (its global fs.close inside)': `test('t', async () => { const d = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'p1f-')); await cb((k) => gfs.writeFile(path.join(d, 'a'), 'x', k)); await cb((k) => gfs.writeFile(path.join(d, 'b'), 'y', k)); });`,
  'sequential promise calls': `test('t', async () => { const d = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'p1f-')); const p = path.join(d, 'a'); await fs.promises.writeFile(p, 'x'); await fs.promises.readFile(p); await fs.promises.stat(p); await fs.promises.rm(d, { recursive: true }); });`,
};

function events(dir) {
  const out = {};
  for (const l of fs.readFileSync(path.join(dir, '.detjs', 'trace.jsonl'), 'utf8').split('\n')) {
    if (!l.startsWith('{"type":"test"')) continue;
    const j = JSON.parse(l);
    out[j.nodeid] = j.events || [];
  }
  return out;
}

for (const [name, body] of Object.entries(CASES)) {
  test(`P1 F: ${name} is one operation (no uncontrolled.io, no io.release)`, T, () => {
    const dir = fixture('p1f', name.replace(/[^a-z0-9]+/gi, '-'), { 'tests/a.test.mjs': `${HEAD}${body}\n` });
    const r = crun('node-test', dir, [], { cache: false });
    assert.equal(r.status, 0, show(r));
    const ev = Object.values(events(dir)).flat();
    assert.ok(ev.length > 0, `no events recorded\n${show(r)}`);
    const bad = ev.filter((e) => e.o === 'uncontrolled.io' || e.o === 'io.release' || e.o === 'io.complete');
    assert.deepEqual(bad, [], `${name}: the steps of one call were seen as concurrent operations`);
  });
}

// acceptance 2: real concurrency is still seen
test('P1 F: two reads in flight at once still mark the test uncontrolled.io (NOT PROVEN)', T, () => {
  // mkdtempSync, not the promise form: this guard must hold on the trunk too (there, an awaited fs.promises.mkdtemp
  // before the reads leaves a completion held for good and node:test cancels the test, MEASURED on e7338950)
  const body = `test('t', async () => { const d = fs.mkdtempSync(path.join(os.tmpdir(), 'p1f-'));
    fs.writeFileSync(path.join(d, 'a'), 'a'.repeat(1 << 20)); fs.writeFileSync(path.join(d, 'b'), 'b');
    await Promise.all([fs.promises.readFile(path.join(d, 'a')), fs.promises.readFile(path.join(d, 'b'))]);
    await Promise.all([cb((k) => fs.readFile(path.join(d, 'a'), k)), cb((k) => gfs.readFile(path.join(d, 'b'), k))]); });`;
  const dir = fixture('p1f', 'concurrent', { 'tests/a.test.mjs': `${HEAD}${body}\n` });
  const r = crun('node-test', dir, [], { cache: false });
  assert.equal(r.status, 0, show(r));
  const ev = Object.values(events(dir)).flat();
  assert.ok(ev.some((e) => e.o === 'uncontrolled.io'), `concurrent reads must stay uncontrolled.io\n${JSON.stringify(ev.map((e) => e.o))}`);
  assert.ok(ev.filter((e) => e.o === 'io.complete').length >= 2, 'each overlapping completion is an io.complete event');
  const traces = [0, 1].map((i) => {
    crun('node-test', dir, [], { cache: false });
    const p = path.join(dir, `t${i}.jsonl`);
    fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), p);
    return p;
  });
  const rep = JSON.parse(require('../src/native').verify(traces));
  assert.equal(rep.summary.stable, 0, `a test with concurrent I/O is never IDENTICAL\n${JSON.stringify(rep.tests)}`);
});
