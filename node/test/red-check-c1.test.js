'use strict';
// Spec C1 (idea 3, "is this red real?"), engine part: what each Node shell writes beyond the trace for the runner to
// send per test -- the real elapsed time of every test bracket (`durations`), the failure record of node-test and
// Mocha tests (`exceptions`, as Vitest and Jest already wrote), and the cause of an error whose own message hides it.
// Run: cd node && node --test --test-concurrency=1 test/red-check-c1.test.js
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { project, BIN } = require('./helpers');
const { fixture, crun, show } = require('./runner-helpers');
const repro = require('../src/repro');

const T = { timeout: 300000 };
const SLOW_MS = 60;

// A test that blocks the process for SLOW_MS of real time (Atomics.wait: no clock or timer the engine virtualizes),
// one that fails on a node:assert assertion, one that passes.
const bodyOf = (it) => [
  `${it}('slow', () => { Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ${SLOW_MS}); });`,
  `${it}('fails', () => { assertMod.strictEqual(1, 2); });`,
  `${it}('passes', () => { assertMod.ok(true); });`,
].join('\n');

function detRun(runner, dir, args) {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT']) delete env[k];
  const r = spawnSync(process.execPath, [BIN, runner, ...(runner === 'vitest' ? ['run'] : []), '--det', ...args],
    { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  return { status: r.status, out: `${r.stdout}\n${r.stderr}` };
}

const readOutcomes = (dir) => JSON.parse(fs.readFileSync(path.join(dir, 'o.json'), 'utf8'));
const lineOf = (dir, file, needle) => fs.readFileSync(path.join(dir, file), 'utf8').split('\n').findIndex((l) => l.includes(needle)) + 1;

/** The fixture of `runner` and its outcomes file after one --det run with --det-outcomes. */
function runShell(runner) {
  if (runner === 'vitest' || runner === 'jest') {
    const imp = runner === 'vitest' ? "import assertMod from 'node:assert';" : "const assertMod = require('node:assert');";
    const dir = project(runner, 'c1-durations', { a: `${imp}\n${bodyOf('test')}` });
    const file = `tests/a${runner === 'vitest' ? '.test.mjs' : '.test.js'}`;
    const r = detRun(runner, dir, ['--det-outcomes=o.json']);
    assert.equal(r.status, 1, r.out);
    return { dir, file, o: readOutcomes(dir) };
  }
  if (runner === 'node-test') {
    const file = 'test/a.test.js';
    const dir = fixture('c1', 'node-test-durations', { [file]: `const { test } = require('node:test'); const assertMod = require('node:assert');\n${bodyOf('test')}\n` });
    const r = crun('node-test', dir, [], { cache: false, det: ['--det', '--det-outcomes=o.json'] });
    assert.equal(r.status, 1, show(r));
    return { dir, file, o: readOutcomes(dir) };
  }
  const file = 'test/a.spec.cjs';
  const dir = fixture('c1', 'mocha-durations', { [file]: `const assertMod = require('node:assert');\n${bodyOf('it')}\n` });
  const r = crun('mocha', dir, [file], { cache: false, det: ['--det', '--det-outcomes=o.json'] });
  assert.equal(r.status, 1, show(r));
  return { dir, file, o: readOutcomes(dir) };
}

describe('C1: side-record fields of every Node shell, in the --det-outcomes file', () => {
  const seen = {};
  for (const runner of ['vitest', 'jest', 'node-test', 'mocha']) {
    test(`${runner}: durations from the real clock, a failure record for the failed test`, T, () => {
      // protects: per-test durationMs and the failure record the runner sends (spec C1 1.1)
      // fails_when: a shell writes no durations, reads the virtual clock (a 60 ms real block then reads ~0), or a
      //   node-test/Mocha failure has no exception record
      // no_claim: durations are wall time of the bracket (hooks included), not CPU time
      const { dir, file, o } = runShell(runner);
      const id = (n) => `${file}::${n}`;
      assert.deepEqual([...o.order].sort(), [id('fails'), id('passes'), id('slow')].sort());
      for (const t of o.order) {
        assert.ok(Number.isInteger(o.durations[t]) && o.durations[t] >= 1, `${t}: durationMs ${o.durations[t]}`);
      }
      assert.ok(o.durations[id('slow')] >= SLOW_MS, `slow: ${o.durations[id('slow')]} ms < ${SLOW_MS} (real block)`);
      assert.equal(o.outcomes[id('fails')], 'failed');
      const e = o.exceptions[id('fails')];
      assert.ok(Array.isArray(e), `${runner}: no failure record: ${JSON.stringify(o.exceptions)}`);
      assert.equal(e[1], 'call');
      seen[runner] = e;
      // Jest (unchanged by C1): jest-circus hands the shell its own reformatted copy of a node:assert error (no
      // name, no stack frame in the file): only the record's presence and phase are claimed for it
      if (runner === 'jest') return;
      assert.equal(e[0], 'AssertionError');
      assert.equal(e[1], 'call');
      assert.match(e[2], /1 !== 2/);
      assert.equal(e[3], `${file}:${lineOf(dir, file, "'fails'")}`);
      assert.equal(o.exceptions[id('passes')], undefined);
    });
  }

  test('node-test failure record: the same type and location as Vitest for the same assertion', T, (t) => {
    // protects: spec C1 criterion 3 (node-test unwraps ERR_TEST_FAILURE to the test's own error)
    // fails_when: node-test records the wrapper (type Error, location inside node:test) instead of the assertion
    // no_claim: Node versions without TestContext.error write no record (the runner's fallback applies)
    if (!seen.vitest || !seen['node-test']) { t.skip('needs the vitest and node-test cases of this file'); return; }
    assert.equal(seen['node-test'][0], seen.vitest[0]);
    assert.equal(seen['node-test'][1], seen.vitest[1]);
    // both locations are the assertion's own line in the test file (checked per runner above), not a frame in node:test
    for (const e of [seen['node-test'], seen.vitest]) assert.match(e[3], /^(test|tests)\/a\.test\.m?js:\d+$/);
  });

  test('vitest: a fetch() refused by the closed network carries the engine block as its cause', T, () => {
    // protects: the failure message idea 3 reads to tell an environment-caused red (spec C1 1.1, error cause)
    // fails_when: the record keeps only "fetch failed"
    // no_claim: the record is not a verdict
    const dir = project('vitest', 'c1-fetch-cause', { a: "test('net', async () => { await fetch('http://example.com/'); });" });
    const r = detRun('vitest', dir, ['--det-net=closed', '--det-outcomes=o.json']);
    assert.equal(r.status, 1, r.out);
    const o = readOutcomes(dir);
    const e = o.exceptions['tests/a.test.mjs::net'];
    assert.ok(e, JSON.stringify(o.exceptions));
    assert.match(e[2], /^fetch failed \/ cause: detjs: network access to \S*example\.com\S* blocked \(/);
    assert.ok(e[2].length <= 200);
  });
});

describe('C1: exceptionOf with a cause (unit)', () => {
  test('a cause the message does not contain is appended within 200 characters; one it contains is not', () => {
    // protects: the cause rule of spec C1 1.1
    // fails_when: causes are dropped, repeated, or push the text past 200 characters
    // no_claim: only the first cause level is read
    const blocked = 'detjs: network access to example.com:443 blocked (closed network)';
    const e = new TypeError('fetch failed', { cause: new Error(blocked) });
    const r = repro.exceptionOf(e, 'call', process.cwd());
    assert.deepEqual(r.slice(0, 3), ['TypeError', 'call', `fetch failed / cause: ${blocked}`]);
    const same = repro.exceptionOf(new Error(`x: ${blocked}`, { cause: new Error(blocked) }), 'call', process.cwd());
    assert.equal(same[2], `x: ${blocked}`);
    const long = repro.exceptionOf(new Error('m'.repeat(400), { cause: new Error(blocked) }), 'call', process.cwd());
    assert.equal(long[2].length, 200);
    assert.ok(long[2].endsWith(` / cause: ${blocked}`), long[2]);
    assert.deepEqual(repro.exceptionOf(new Error('plain'), 'setup', process.cwd()).slice(0, 3), ['Error', 'setup', 'plain']);
  });

  test('location: an absolute frame, and a frame Mocha made relative to the working directory', () => {
    // protects: the `location` of Mocha failures (Mocha's stack filter strips the working directory)
    // fails_when: a relative frame is read as the absolute path of its last segment (location '') or an absolute one
    //   stops matching
    // no_claim: frames of other working directories than the root's
    const root = process.cwd();
    const err = (stack) => Object.assign(new Error('x'), { stack });
    assert.equal(repro.exceptionOf(err(`Error: x\n    at Context.<anonymous> (test/b.spec.cjs:2:31)\n    at process.processImmediate (node:internal/timers:484:21)`), 'call', root)[3], 'test/b.spec.cjs:2');
    assert.equal(repro.exceptionOf(err(`Error: x\n    at f (${root}/tests/a.test.js:7:3)`), 'call', root)[3], 'tests/a.test.js:7');
    assert.equal(repro.exceptionOf(err(`Error: x\n    at ${root}/tests/a.test.js:9:1`), 'call', root)[3], 'tests/a.test.js:9');
    assert.equal(repro.exceptionOf(err('Error: x\n    at f (node_modules/x/y.js:1:1)\n    at node:internal/timers:1:1'), 'call', root)[3], '');
  });
});
