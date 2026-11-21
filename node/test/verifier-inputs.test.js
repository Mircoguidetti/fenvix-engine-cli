'use strict';
// F-03 (audit G-0139, G-0140 and their family on Node): the trace header records the run inputs (time zone,
// locale, environment variables as digests, seed, clock, network, runtime) and `verify` never reports two runs
// identical when one of them differs, naming the input as the first divergent event.
// Run: cd node && node --test test/verifier-inputs.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const native = require('../src/native');
const { fixture, crun, show } = require('./runner-helpers');

const T = { timeout: 600000 };
const BODY = "import { test } from 'node:test'; import assert from 'node:assert/strict';\n"
  + "test('local date', () => { assert.ok(String(new Date()).length > 0); });\n"
  + "test('plain', () => { assert.ok(true); });\n";

function runTo(dir, name, env, det = ['--det']) {
  const r = crun('node-test', dir, [], { cache: false, det, env });
  assert.equal(r.status, 0, show(r));
  const dst = path.join(dir, `${name}.jsonl`);
  fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), dst);
  return dst;
}

test('the header records the run inputs; same inputs are identical', T, () => {
  const dir = fixture('verifier-inputs', 'same', { 'tests/a.test.mjs': BODY });
  const a = runTo(dir, 'a', { TZ: 'UTC' });
  const b = runTo(dir, 'b', { TZ: 'UTC' });
  const hdr = JSON.parse(fs.readFileSync(a, 'utf8').split('\n')[0]).meta;
  for (const k of ['runtime', 'runner', 'seed', 'clock', 'tz', 'locale', 'network', 'entropy']) assert.ok(k in hdr.inputs, k);
  assert.ok(Object.keys(hdr.inputs).some((k) => k.startsWith('env:')));
  const rep = JSON.parse(native.verify([a, b]));
  assert.equal(rep.summary.stable, rep.summary.tests, JSON.stringify(rep.input_differences));
  assert.equal(rep.summary.inputs_recorded, true);
});

// tz: the job's own time zone, kept with --det-tz=keep (by default --det pins TZ=UTC: next test)
for (const [name, envA, envB, reason, det] of [
  ['tz', { TZ: 'UTC' }, { TZ: 'Asia/Tokyo' }, 'tz', ['--det', '--det-tz=keep']],
  ['env', { TZ: 'UTC', NODE_TRUTH_FLAG: 'a' }, { TZ: 'UTC', NODE_TRUTH_FLAG: 'b' }, 'env', undefined],
  ['seed', { TZ: 'UTC', DETJS_SEED: '1' }, { TZ: 'UTC', DETJS_SEED: '2' }, 'seed', undefined],
]) {
  test(`runs differing only in ${name} are divergent and name it`, T, () => {
    // env: the tests read the variable (a variable no test reads keeps them identical: 'no test reads' below)
    const body = name === 'env'
      ? BODY.replace(/test\('(local date|plain)', \(\) => \{/g, "test('$1', () => { void process.env.NODE_TRUTH_FLAG;")
      : BODY;
    const dir = fixture('verifier-inputs', name, { 'tests/a.test.mjs': body });
    const a = runTo(dir, 'a', envA, det);
    const b = runTo(dir, 'b', envB, det);
    const rep = JSON.parse(native.verify([a, b]));
    assert.equal(rep.summary.stable, 0, JSON.stringify(rep.summary));
    assert.equal(rep.input_differences[0].reason, reason, JSON.stringify(rep.input_differences));
    for (const t of rep.tests) assert.equal(t.divergence.reason, reason, t.nodeid);
    // design A: a differing environment variable the tests read is `input-differs`, never `diverged`
    if (name === 'env') for (const t of rep.tests) assert.equal(t.status, 'input-differs', t.nodeid);
  });
}

test('CI-volatile variables are never inputs (design A): runs differing only in them are identical', T, () => {
  const dir = fixture('verifier-inputs', 'volatile', { 'tests/a.test.mjs': BODY });
  const a = runTo(dir, 'a', { TZ: 'UTC', GITHUB_RUN_ID: '11', RUNNER_TEMP: '/tmp/r1', EXAM_OUT: '/o/1', FENVIX_VOLATILE_ENV: 'EXAM_*' });
  const b = runTo(dir, 'b', { TZ: 'UTC', GITHUB_RUN_ID: '22', RUNNER_TEMP: '/tmp/r2', EXAM_OUT: '/o/2', FENVIX_VOLATILE_ENV: 'EXAM_*', HTTPS_PROXY: 'http://127.0.0.1:9', SUDO_USER: 'exam' });
  const rep = JSON.parse(native.verify([a, b]));
  assert.equal(rep.summary.stable, rep.summary.tests, JSON.stringify(rep.input_differences));
  const hdr = JSON.parse(fs.readFileSync(a, 'utf8').split('\n')[0]).meta;
  for (const k of ['env:GITHUB_RUN_ID', 'env:RUNNER_TEMP', 'env:EXAM_OUT', 'env:HTTPS_PROXY', 'env:SUDO_USER']) assert.ok(!(k in hdr.inputs), k);
});

test('the CPU count is pinned under --det (design A); the engine keeps the real one', T, () => {
  const dir = fixture('verifier-inputs', 'cpus', {
    'tests/a.test.mjs': "import { test } from 'node:test'; import os from 'node:os';\n"
      + "test('cpus', () => { console.log(`CPU ${os.cpus().length} ${os.availableParallelism()}`); });\n",
  });
  const r = crun('node-test', dir, [], { cache: false, det: ['--det'], env: {} });
  assert.equal(r.status, 0, show(r));
  assert.match(String(r.stdout), /CPU 2 2/, show(r));
  const volatile = require('../src/volatile');
  assert.equal(volatile.realParallelism(), require('node:os').availableParallelism());
});

// review P1 #7, coordinator decision option A: by default --det pins TZ=UTC and the locale (C.UTF-8) whatever the
// environment sets, so two runs under different TZ / LANG are the same run: identical, with identical inputs
test('by default the time zone and the locale are pinned: runs under different TZ and LANG are identical', T, () => {
  const dir = fixture('verifier-inputs', 'tz-pinned', { 'tests/a.test.mjs': BODY });
  const a = runTo(dir, 'a', { TZ: 'UTC', LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8' });
  const b = runTo(dir, 'b', { TZ: 'Asia/Tokyo', LANG: 'de_DE.UTF-8', LC_ALL: 'de_DE.UTF-8' });
  const rep = JSON.parse(native.verify([a, b]));
  assert.equal(rep.summary.stable, rep.summary.tests, JSON.stringify(rep.input_differences));
  for (const t of ['tz', 'locale']) assert.ok(!rep.input_differences.some((d) => d.reason === t), JSON.stringify(rep.input_differences));
});

// HANDOFF P-041 "verifier: constant uncontrolled.* values": a test that runs a child process records a constant
// `uncontrolled.child` event (no per-run nonce, so its replays keep one fingerprint); the verifier never reports it
// identical and names the source; a test without such a source is stable.
test('a constant uncontrolled source: same fingerprint in both runs, never identical, the source named', T, () => {
  const body = "import { test } from 'node:test'; import assert from 'node:assert/strict'; import cp from 'node:child_process';\n"
    + "test('child', () => { assert.equal(cp.execFileSync(process.execPath, ['-e', 'process.stdout.write(\"1\")']).toString(), '1'); });\n"
    + "test('plain', () => { assert.ok(true); });\n";
  const dir = fixture('verifier-inputs', 'uncontrolled', { 'tests/a.test.mjs': body });
  const a = runTo(dir, 'a', { TZ: 'UTC' });
  const b = runTo(dir, 'b', { TZ: 'UTC' });
  const tests = (f) => Object.fromEntries(fs.readFileSync(f, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l))
    .filter((j) => j.type === 'test').map((j) => [j.nodeid.split('::').pop(), j]));
  const ta = tests(a);
  const tb = tests(b);
  assert.ok(ta.child.events.some((e) => e.o === 'uncontrolled.child'), JSON.stringify(ta.child.events));
  assert.equal(ta.child.fingerprint, tb.child.fingerprint, 'no per-run value in the event');
  const rep = JSON.parse(native.verify([a, b]));
  const by = Object.fromEntries(rep.tests.map((t) => [t.nodeid.split('::').pop(), t]));
  assert.equal(by.plain.status, 'stable', JSON.stringify(by.plain));
  assert.notEqual(by.child.status, 'stable', JSON.stringify(by.child));
  assert.equal(by.child.divergence.reason, 'child', JSON.stringify(by.child));
});

// R-050 N1, the other side: a file outside the project read with the same contents in both runs keeps the test
// identical (the event carries path and digest, no run-dependent value); the same on Vitest and Jest
for (const runner of ['node-test', 'vitest', 'jest']) {
  test(`${runner}: an outside file with the same contents in both runs: identical; different contents: divergent`, T, () => {
    const os = require('node:os');
    const ext = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'vi-outside-')), 'cfg.txt');
    const files = runner === 'node-test'
      ? { 'tests/o.test.mjs': `import { test } from 'node:test'; import fs from 'node:fs';\ntest('reads', () => { fs.readFileSync(${JSON.stringify(ext)}, 'utf8'); });\n` }
      : runner === 'vitest'
        ? { 'tests/o.test.mjs': `import { test } from 'vitest'; import fs from 'node:fs';\ntest('reads', async () => { await fs.promises.readFile(${JSON.stringify(ext)}, 'utf8'); });\n`, 'vitest.config.mjs': "export default { test: { include: ['tests/**/*.test.mjs'] } };\n" }
        : { 'tests/o.test.js': `const fs = require('node:fs');\ntest('reads', () => { const fd = fs.openSync(${JSON.stringify(ext)}, 'r'); const b = Buffer.alloc(8); fs.readSync(fd, b); fs.closeSync(fd); });\n`, 'jest.config.js': "module.exports = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node' };\n" };
    const dir = fixture('verifier-inputs', `outside-${runner}`, files);
    const runOnce = (name, content) => {
      fs.writeFileSync(ext, content);
      const r = crun(runner, dir, runner === 'vitest' ? ['run'] : [], { cache: false, env: { TZ: 'UTC' } });
      assert.equal(r.status, 0, show(r));
      const dst = path.join(dir, `${name}.jsonl`);
      fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), dst);
      return dst;
    };
    const a = runOnce('a', 'same');
    const b = runOnce('b', 'same');
    const c = runOnce('c', 'other');
    const same = JSON.parse(native.verify([a, b]));
    assert.equal(same.summary.stable, same.summary.tests, JSON.stringify(same.summary));
    const diff = JSON.parse(native.verify([a, c]));
    assert.equal(diff.summary.stable, 0, JSON.stringify(diff.summary));
  });
}

// exam F-01.hostname.pinned.node: the second run under sudo has other USER/LOGNAME, which no test reads. The header
// says the tests' environment reads are recorded, so only the tests that read a differing variable are
// input-differs; the others stay identical
for (const runner of ['node-test', 'vitest']) {
  test(`${runner}: a variable that differs between the runs but no test reads keeps the tests identical`, T, () => {
    const files = runner === 'node-test'
      ? { 'tests/e.test.mjs': "import { test } from 'node:test';\ntest('reads', () => { void process.env.EXAM_READ; });\ntest('plain', () => {});\n" }
      : { 'tests/e.test.mjs': "import { test } from 'vitest';\ntest('reads', () => { void process.env.EXAM_READ; });\ntest('plain', () => {});\n",
        'vitest.config.mjs': "export default { test: { include: ['tests/**/*.test.mjs'] } };\n" };
    const dir = fixture('verifier-inputs', `unread-${runner}`, files);
    const run = (name, env) => {
      const r = crun(runner, dir, runner === 'vitest' ? ['run'] : [], { cache: false, env: { TZ: 'UTC', ...env } });
      assert.equal(r.status, 0, show(r));
      const dst = path.join(dir, `${name}.jsonl`);
      fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), dst);
      return dst;
    };
    const a = run('a', { EXAM_READ: '1', EXAM_UNREAD: 'x' });
    const b = run('b', { EXAM_READ: '1', EXAM_UNREAD: 'y' });
    assert.equal(JSON.parse(fs.readFileSync(a, 'utf8').split('\n')[0]).meta.env_reads_recorded, true);
    const same = JSON.parse(native.verify([a, b]));
    assert.equal(same.summary.stable, same.summary.tests, JSON.stringify(same.tests));
    const c = run('c', { EXAM_READ: '2', EXAM_UNREAD: 'x' });
    const diff = JSON.parse(native.verify([a, c]));
    const by = Object.fromEntries(diff.tests.map((t) => [t.nodeid.split('::').pop(), t.status]));
    assert.equal(by.plain, 'stable', JSON.stringify(diff.tests));
    assert.equal(by.reads, 'input-differs', JSON.stringify(diff.tests));
  });
}
