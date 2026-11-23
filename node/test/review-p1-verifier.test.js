'use strict';
// Review P1 (rows F-01, F-02, F-03, F-18; audit G-0139, G-0448 and the Node members of the G-0180 family:
// G-0124/G-0125, G-0132..G-0137, G-0150, G-0152). Every test here FAILS on release-1 @ 71f8081: they are findings,
// not fixes. Run: cd node && node --test --test-concurrency=1 test/review-p1-verifier.test.js
//
// Shape of the verifier tests: run the same suite twice under --det with identical inputs; every test writes the
// value it observed to a side file. When a value differs between the two runs, `verify` must not report that test
// identical (F-03: "never say same when the runs differ").
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const native = require('../src/native');
const { fixture, crun, show } = require('./runner-helpers');

const T = { timeout: 900000 };

const PROBES = {
  'process.uptime': 'out(process.uptime());',
  'performance.timeOrigin': 'out(performance.timeOrigin);',
  'performance.mark': "out(performance.mark('x').startTime);",
  'crypto.randomFill async': 'const b = Buffer.alloc(8); await new Promise((r) => crypto.randomFill(b, r)); out(b.toString("hex"));',
  'crypto.randomInt callback': 'out(await new Promise((r) => crypto.randomInt(1e9, (e, n) => r(n))));',
  'vm.runInNewContext': "out(vm.runInNewContext('Math.random()'));",
  'worker_threads': "const w = new Worker('require(\"node:worker_threads\").parentPort.postMessage(Math.random())', { eval: true }); out(await new Promise((r) => w.on('message', r))); await w.terminate();",
  'child_process': "out(spawnSync(process.execPath, ['-e', 'console.log(Math.random())']).stdout.toString().trim());",
  '/dev/urandom': "const fd = fs.openSync('/dev/urandom', 'r'); const b = Buffer.alloc(8); fs.readSync(fd, b); fs.closeSync(fd); out(b.toString('hex'));",
  'process.pid': 'out(process.pid);',
  'crypto.subtle.generateKey': "const k = await crypto.subtle.generateKey({ name: 'HMAC', hash: 'SHA-256' }, true, ['sign']); out(Buffer.from(await crypto.subtle.exportKey('raw', k)).toString('hex'));",
};

function suite(outFile) {
  const head = "import { test } from 'node:test'; import fs from 'node:fs'; import crypto from 'node:crypto';\n"
    + "import vm from 'node:vm'; import { Worker } from 'node:worker_threads'; import { spawnSync } from 'node:child_process';\n";
  const body = Object.entries(PROBES).map(([name, code]) => `test(${JSON.stringify(name)}, async () => {\n`
    + `  const out = (v) => fs.appendFileSync(${JSON.stringify(outFile)}, JSON.stringify([${JSON.stringify(name)}, v]) + '\\n');\n`
    + `  ${code}\n});\n`).join('');
  return head + body;
}

function runTwice(dir, outFile) {
  const traces = [];
  const values = [];
  for (const i of [1, 2]) {
    fs.rmSync(outFile, { force: true });
    const r = crun('node-test', dir, [], { cache: false, env: { TZ: 'UTC' } });
    assert.equal(r.status, 0, show(r));
    const t = path.join(dir, `run${i}.jsonl`);
    fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), t);
    traces.push(t);
    const v = {};
    for (const line of fs.readFileSync(outFile, 'utf8').trim().split('\n')) { const [k, x] = JSON.parse(line); v[k] = x; }
    values.push(v);
  }
  return { traces, values };
}

// F-03 / F-01: the verifier says IDENTICAL for runs whose observed values differ (G-0135, G-0136, G-0137, G-0132,
// G-0133, G-0134, G-0152, G-0124/G-0125 and two sources the audit did not list: /dev/urandom read as a file,
// process.pid, WebCrypto keys).
test('F-03: no test whose observed value differs between two --det runs is reported identical', T, () => {
  const dir = fixture('review-p1', 'leaks', {});
  const outFile = path.join(dir, 'observed.jsonl');
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'tests', 'leaks.test.mjs'), suite(outFile));
  const { traces, values } = runTwice(dir, outFile);
  const rep = JSON.parse(native.verify(traces));
  const wrong = [];
  for (const t of rep.tests) {
    const name = t.nodeid.split('::').pop();
    const differs = JSON.stringify(values[0][name]) !== JSON.stringify(values[1][name]);
    if (differs && t.status === 'stable') wrong.push(`${name}: ${JSON.stringify(values[0][name])} vs ${JSON.stringify(values[1][name])}`);
  }
  assert.deepEqual(wrong, [], `verify reported these tests identical although their values differed:\n${wrong.join('\n')}`);
});

// G-0150: completion order of concurrent fs.readFile calls; 6 runs.
test('F-03: a concurrent fs.readFile completion order that differs between runs is not reported identical', T, () => {
  const outFile = path.join(fixture('review-p1', 'race-out', {}), 'order.txt');
  const dir = fixture('review-p1', 'race', {
    'tests/race.test.mjs': "import { test } from 'node:test'; import fs from 'node:fs';\n"
      + "test('fs race', async () => {\n"
      + "  const d = fs.mkdtempSync('/tmp/p1race');\n"
      + "  for (let i = 0; i < 8; i++) fs.writeFileSync(`${d}/${i}`, 'x'.repeat(200000 * (i % 3 + 1)));\n"
      + "  const order = [];\n"
      + "  await Promise.all([...Array(8).keys()].map((i) => fs.promises.readFile(`${d}/${i}`).then(() => order.push(i))));\n"
      + `  fs.appendFileSync(${JSON.stringify(outFile)}, order.join('') + '\\n');\n`
      + '});\n',
  });
  fs.rmSync(outFile, { force: true });
  const traces = [];
  for (let i = 0; i < 6; i++) {
    const r = crun('node-test', dir, [], { cache: false, env: { TZ: 'UTC' } });
    assert.equal(r.status, 0, show(r));
    const t = path.join(dir, `r${i}.jsonl`);
    fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), t);
    traces.push(t);
  }
  const orders = new Set(fs.readFileSync(outFile, 'utf8').trim().split('\n'));
  const rep = JSON.parse(native.verify(traces));
  if (orders.size > 1) {
    assert.equal(rep.summary.stable, 0, `orders ${[...orders].join(', ')} but verify: ${JSON.stringify(rep.summary)}`);
  }
});

// F-01 (G-0139, G-0140): the time zone and the locale are recorded now, but not controlled: the same test passes
// under one machine time zone and fails under another, under --det.
test('F-01: --det pins the time zone and the locale (same result whatever the machine sets)', T, () => {
  const dir = fixture('review-p1', 'tz', {
    'tests/tz.test.mjs': "import { test } from 'node:test'; import assert from 'node:assert/strict';\n"
      + "test('local hour of the epoch', () => { assert.equal(new Date(0).getHours(), 0); });\n"
      + "test('number format', () => { assert.equal((1234.5).toLocaleString(), '1,234.5'); });\n",
  });
  // the pin is asked for: opt-out of the keep default (spec 2026-11-23)
  const det = ['--det', '--det-tz=UTC', '--det-locale=C.UTF-8'];
  const a = crun('node-test', dir, [], { cache: false, det, env: { TZ: 'UTC', LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8' } });
  const b = crun('node-test', dir, [], { cache: false, det, env: { TZ: 'Asia/Tokyo', LANG: 'de_DE.UTF-8', LC_ALL: 'de_DE.UTF-8' } });
  assert.equal(a.status, 0, show(a));
  assert.equal(b.status, a.status, `under TZ=Asia/Tokyo LANG=de_DE the --det run ${b.status === 0 ? 'passes' : 'fails'}:\n${show(b)}`);
});

// F-02 (G-0448): fenvix repro / explore / replay for Node runners.
test('F-02: fenvix repro works for a Vitest, Jest and node:test test', T, () => {
  const py = process.env.FENVIX_PYTHON || 'python3';
  const dir = fixture('review-p1', 'repro', {
    'tests/a.test.mjs': "import { test } from 'node:test'; import assert from 'node:assert/strict';\n"
      + "test('flaky', () => { assert.ok(Math.random() > 0.3); });\n",
  });
  const out = [];
  for (const runner of ['vitest', 'jest', 'node-test']) {
    const r = spawnSync(py, ['-m', 'detpy.fenvix', 'repro', 'tests/a.test.mjs::flaky', '--runner', runner, '--seeds', '5',
      '--confirm', '2'], { cwd: dir, encoding: 'utf8', timeout: 600000 });
    if (r.status === 2 || /not available|unknown runner/.test(r.stderr || '')) out.push(`${runner}: exit ${r.status}: ${(r.stderr || '').trim()}`);
  }
  assert.deepEqual(out, [], out.join('\n'));
});
