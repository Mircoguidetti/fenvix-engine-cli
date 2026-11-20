'use strict';
// One regression test per shell defect found by the harness whose fix came
// without a test (review R-005). Each test fails on the parent of the fix
// commit and passes from the fix on (checked by hand, recorded in
// docs/REPORT-node-l0-2.md).
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { project, run, failed, RUNNERS } = require('./helpers');

const T = { timeout: 300000 };
const has = (runner) => RUNNERS.includes(runner);

describe('regressions', () => {
  // a6d36ff (jotai): Vite refused to serve the detjs runner from outside the
  // project root when the project restricts server.fs: 0 files ran.
  test('vitest: a jsdom project (Vite serves the runner, server.fs restricted to the root) runs every file under --det', { ...T, skip: !has('vitest') }, () => {
    const dir = project('vitest', 'fs-allow', {
      a: "test('a', () => { expect(1).toBe(1); });",
      b: "test('b', () => { expect(2).toBe(2); });",
    });
    fs.writeFileSync(path.join(dir, 'vitest.config.mjs'),
      "export default { server: { fs: { strict: true, allow: ['.'] } }, test: { environment: 'jsdom', include: ['tests/**/*.test.mjs'] } };\n");
    const r = run('vitest', dir, ['--det']);
    assert.equal(Object.keys(r.outcomes).length, 2, `${r.stdout}\n${r.stderr}`);
    assert.deepEqual(failed(r), []);
    assert.equal(r.trace.tests.length, 2);
  });

  // 7c91f0e (react-testing-library): in band, a handle left open by a suite
  // kept the single Jest process alive forever.
  test('jest: a suite that leaves a server open does not keep the --det run alive', { ...T, skip: !has('jest') }, () => {
    const dir = project('jest', 'open-handle', {
      a: "test('leaves a server listening', async () => { const s = require('node:net').createServer(); await new Promise((r) => s.listen(0, '127.0.0.1', r)); expect(s.listening).toBe(true); });",
    });
    const r = run('jest', dir, ['--det']);
    assert.notEqual(r.status, null, 'the --det run did not exit (killed by the 120 s timeout)');
    assert.deepEqual(failed(r), []);
    assert.equal(r.trace.tests.length, 1);
  });

  // 8b67806 (matrix-js-sdk, immutable-js): Jest compiled the detjs testRunner
  // with the project's transform, which then failed on detjs's own files.
  test('jest: the project transform is not applied to detjs', { ...T, skip: !has('jest') }, () => {
    const dir = project('jest', 'strict-transform', {
      a: "test('a', () => { expect(1).toBe(1); });",
    }, { jest: { transform: { '\\.js$': '<rootDir>/strict-transform.js' } } });
    fs.writeFileSync(path.join(dir, 'strict-transform.js'), [
      "'use strict';",
      'const path = require(\'node:path\');',
      'module.exports = { process(src, file) {',
      '  if (path.relative(__dirname, file).startsWith(\'..\')) throw new Error(\'transformed outside the project: \' + file);',
      '  return { code: src };',
      '} };',
    ].join('\n'));
    const r = run('jest', dir, ['--det']);
    assert.equal(Object.keys(r.outcomes).length, 1, `${r.stdout}\n${r.stderr}`);
    assert.deepEqual(failed(r), []);
    assert.equal(r.trace.tests.length, 1);
  });

  // 8b67806 (babel): the in-process jest-cli run was awaited by detjs, which
  // added an `at async main (…/jest/cli.js)` frame to the async stacks seen by
  // code running in Jest's await chain (babel's stack-trace snapshots, under a
  // runner that awaits each test file). The probe is a runner of that kind.
  test('jest: no detjs frame in the async stack of a runner that awaits its tests', { ...T, skip: !has('jest') }, () => {
    const dir = project('jest', 'async-stack', {
      a: "test('a', () => { expect(1).toBe(1); });",
    }, { jest: { runner: '<rootDir>/stack-runner.js' } });
    fs.writeFileSync(path.join(dir, 'stack-runner.js'), [
      "'use strict';",
      "const { createEmptyTestResult } = require('@jest/test-result');",
      'class StackRunner {',
      '  constructor() { this.isSerial = true; }',
      '  async runTests(tests, watcher, onStart, onResult) {',
      '    for (const t of tests) {',
      '      await onStart(t);',
      '      await null;',
      '      Error.stackTraceLimit = 200;',
      "      const stack = new Error('probe').stack;",
      '      const bad = /src[\\/]jest[\\/]cli\.js/.test(stack);',
      '      const r = createEmptyTestResult();',
      '      r.testFilePath = t.path;',
      "      r.testResults = [{ ancestorTitles: [], title: 'async stack', fullName: 'async stack', status: bad ? 'failed' : 'passed',",
      '        failureMessages: bad ? [stack] : [], duration: 0, numPassingAsserts: 0, location: null }];',
      '      r.numPassingTests = bad ? 0 : 1;',
      '      r.numFailingTests = bad ? 1 : 0;',
      '      r.perfStats = { start: 0, end: 1, runtime: 1, slow: false };',
      '      await onResult(t, r);',
      '    }',
      '  }',
      '}',
      'module.exports = StackRunner;',
    ].join('\n'));
    const r = run('jest', dir, ['--det']);
    assert.equal(Object.keys(r.outcomes).length, 1, `${r.stdout}\n${r.stderr}`);
    assert.deepEqual(failed(r), [], r.stdout + r.stderr);
  });

  // 83516ab / a6d2fbd (babel, prettier): a custom Jest `runner` bypasses the
  // detjs testRunner hook; Level 0 silently did not apply. Now reported.
  test('jest: a custom runner is reported in stderr and in the trace header', { ...T, skip: !has('jest') }, () => {
    const dir = project('jest', 'custom-runner', {
      a: "test('a', () => { expect(1).toBe(1); });",
    }, { jest: { runner: '<rootDir>/my-runner.js' } });
    fs.writeFileSync(path.join(dir, 'my-runner.js'),
      "'use strict';\nconst m = require('jest-runner');\nmodule.exports = m.default || m;\n");
    const r = run('jest', dir, ['--det']);
    assert.match(r.stderr, /custom Jest runner/);
    assert.match(r.trace.header.meta.isolation, /my-runner\.js/);
  });

  // 50036b6: runner timers must stay real. Its parent did not have the defect
  // (a null-vs-undefined fall-through introduced and fixed while the call-site
  // capture was rewritten), so this test guards the behaviour, not a commit.
  for (const runner of RUNNERS) {
    test(`${runner}: a long virtual sleep is not cut by the runner's real test timeout`, T, () => {
      const dir = project(runner, 'runner-timers', {
        a: "test('sleeps 10 s of virtual time', async () => { await new Promise((r) => setTimeout(r, 10000)); expect(1).toBe(1); }, 3000);",
      });
      const r = run(runner, dir, ['--det']);
      assert.deepEqual(failed(r), [], r.stdout + r.stderr);
      assert.equal(Object.keys(r.outcomes).length, 1);
    });
  }
});
