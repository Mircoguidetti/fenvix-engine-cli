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
// The fail-safe for the test's own code run inside an operation (fs.cp filter, writeFile from an iterable) is the last
// part of this file.
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

// Fail-safe of 2026-11-24 (founder decision D1 = C, eng review of the P1 merge): F treats everything that runs inside a
// tracked file operation as a step of it. Some operations run the test's own code there: the `filter` of `fs.cp`, and
// the iterable a `fs.promises.writeFile` / `appendFile` draws its data from. The file I/O that code starts is the
// test's, not a step of the copy or the write, and it is neither tracked nor ordered.
// protects=I/O started by the test's own code inside a file operation's callback marks the test uncontrolled.io (NOT
//   PROVEN); fails_when=such I/O leaves no uncontrolled.io (red on 0358ea4), or a filter / iterable that starts no I/O
//   marks it (a false alarm), or verify calls two such runs IDENTICAL;
// no_claim=the exact fix (tracking that I/O as the test's own operations) is a follow-up; a Readable stream passed as
//   the data (its reads are Node's stream code) and fs.cpSync are not covered.
const USER_CB = {
  'fs.promises.cp filter that stats a file': `test('t', async () => { const d = fs.mkdtempSync(path.join(os.tmpdir(), 'p1f-'));
    fs.mkdirSync(path.join(d, 's')); fs.writeFileSync(path.join(d, 's', 'x'), 'x');
    await fs.promises.cp(path.join(d, 's'), path.join(d, 'o'), { recursive: true, filter: async (src) => { await fs.promises.stat(src); return true; } }); });`,
  'callback fs.cp filter that reads a file': `test('t', async () => { const d = fs.mkdtempSync(path.join(os.tmpdir(), 'p1f-'));
    fs.mkdirSync(path.join(d, 's')); fs.writeFileSync(path.join(d, 's', 'x'), 'x');
    await cb((k) => fs.cp(path.join(d, 's'), path.join(d, 'o'), { recursive: true, filter: (src) => cb((j) => fs.access(src, j)).then(() => true) }, k)); });`,
  'fs.promises.writeFile from an async iterable that reads a file': `test('t', async () => { const d = fs.mkdtempSync(path.join(os.tmpdir(), 'p1f-'));
    fs.writeFileSync(path.join(d, 'in'), 'abc');
    async function* gen() { yield await fs.promises.readFile(path.join(d, 'in')); yield 'z'; }
    await fs.promises.writeFile(path.join(d, 'out'), gen()); });`,
  'fs.promises.appendFile from an async iterable that reads a file': `test('t', async () => { const d = fs.mkdtempSync(path.join(os.tmpdir(), 'p1f-'));
    fs.writeFileSync(path.join(d, 'in'), 'abc');
    async function* gen() { yield await fs.promises.readFile(path.join(d, 'in')); }
    await fs.promises.appendFile(path.join(d, 'out'), gen()); });`,
};
for (const [name, body] of Object.entries(USER_CB)) {
  test(`P1 F fail-safe: ${name}: the test is marked uncontrolled.io (NOT PROVEN)`, T, () => {
    const dir = fixture('p1f', `user-${name.replace(/[^a-z0-9]+/gi, '-')}`, { 'tests/a.test.mjs': `${HEAD}${body}\n` });
    const traces = [0, 1].map((i) => {
      const r = crun('node-test', dir, [], { cache: false });
      assert.equal(r.status, 0, show(r));
      const p = path.join(dir, `t${i}.jsonl`);
      fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), p);
      return p;
    });
    const ev = Object.values(events(dir)).flat();
    assert.ok(ev.some((e) => e.o === 'uncontrolled.io'), `${name}: I/O of the test's own code inside the operation\n${JSON.stringify(ev.map((e) => `${e.o} ${e.d || ''}`))}`);
    const rep = JSON.parse(require('../src/native').verify(traces));
    assert.equal(rep.summary.stable, 0, `never IDENTICAL\n${JSON.stringify(rep.tests)}`);
  });
}
// no false alarm: the same operations with a filter / an iterable that starts no I/O
const USER_CB_QUIET = {
  'fs.promises.cp with a filter that starts no I/O': `test('t', async () => { const d = fs.mkdtempSync(path.join(os.tmpdir(), 'p1f-'));
    fs.mkdirSync(path.join(d, 's')); fs.writeFileSync(path.join(d, 's', 'x'), 'x');
    await fs.promises.cp(path.join(d, 's'), path.join(d, 'o'), { recursive: true, filter: (src) => !src.endsWith('.tmp') }); });`,
  'fs.promises.writeFile from an async iterable that starts no I/O': `test('t', async () => { const d = fs.mkdtempSync(path.join(os.tmpdir(), 'p1f-'));
    async function* gen() { yield 'a'; yield 'b'; }
    await fs.promises.writeFile(path.join(d, 'out'), gen()); });`,
};
for (const [name, body] of Object.entries(USER_CB_QUIET)) {
  test(`P1 F fail-safe: ${name}: no uncontrolled.io`, T, () => {
    const dir = fixture('p1f', `quiet-${name.replace(/[^a-z0-9]+/gi, '-')}`, { 'tests/a.test.mjs': `${HEAD}${body}\n` });
    const r = crun('node-test', dir, [], { cache: false });
    assert.equal(r.status, 0, show(r));
    const ev = Object.values(events(dir)).flat();
    const bad = ev.filter((e) => e.o === 'uncontrolled.io' || e.o === 'io.release');
    assert.deepEqual(bad, [], `${name}: a false alarm`);
  });
}
