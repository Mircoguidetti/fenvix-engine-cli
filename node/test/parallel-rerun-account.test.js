'use strict';
// AC4(a) of the spec "Engine P0: no false green" (B3, B4): src/parallel-rerun.js `accountRerun`, the pure decision
// of the hazard re-run -- which first-pass tests it accounted for, and which are NOT PROVEN. Synthetic inputs.
// On bfaf70b4 the function did not exist (the decision was inline in main()) and `fileOf` kept `<file>@@<project>`.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { accountRerun, fileOf, hazardFiles, labelFile, wrapperRunnerCode } = require('../src/parallel-rerun');

const rec = (nodeid, outcome = 'passed') => ({ nodeid, outcome });

test('B4: project-qualified ids of a named Vitest project match their hazard file', () => {
  assert.equal(fileOf('tests/x.test.mjs@@main::suite::t'), 'tests/x.test.mjs');
  assert.equal(fileOf('tests/x.test.mjs::t'), 'tests/x.test.mjs');
  assert.equal(labelFile('main|tests/x.test.mjs'), 'tests/x.test.mjs');
  // a hazard between two lane labels of a named project names the files
  assert.deepEqual(hazardFiles({ meta: { parallel: { hazards: [{ a: 'main|tests/y.test.mjs', b: 'main|tests/x.test.mjs' }] } } }),
    ['tests/x.test.mjs', 'tests/y.test.mjs']);
  const first = [rec('tests/x.test.mjs@@main::a', 'failed'), rec('tests/x.test.mjs@@main::b'), rec('tests/z.test.mjs@@main::c')];
  const rerun = [rec('tests/x.test.mjs@@main::a'), rec('tests/x.test.mjs@@main::b')];
  const r = accountRerun(first, rerun, ['tests/x.test.mjs']);
  assert.deepEqual(r.want, ['tests/x.test.mjs@@main::a', 'tests/x.test.mjs@@main::b']);
  assert.deepEqual(r.unaccounted, []);
  assert.equal(r.complete, true);
  assert.deepEqual(r.notProven, []);
  assert.deepEqual(r.notProvenFiles, []);
});

test('B3: a hazard file with 0 matching re-run tests yields its first-pass tests as NOT PROVEN', () => {
  const first = [rec('a.test.js::1'), rec('a.test.js::2', 'failed'), rec('b.test.js::1'), rec('c.test.js::1')];
  const rerun = [rec('b.test.js::1')];
  const r = accountRerun(first, rerun, ['a.test.js', 'b.test.js']);
  assert.equal(r.complete, false);
  assert.deepEqual(r.notProven, ['a.test.js::1', 'a.test.js::2']);
  assert.deepEqual(r.notProvenFiles, [{ file: 'a.test.js', cause: 'it ran 0 of its 2 test(s)' }]);
});

test('B3: a missing re-run trace makes every first-pass test of the hazard files NOT PROVEN', () => {
  const first = [rec('a.test.js::1'), rec('b.test.js::1'), rec('c.test.js::1')];
  const r = accountRerun(first, null, ['a.test.js', 'b.test.js']);
  assert.equal(r.complete, false);
  assert.deepEqual(r.notProven, ['a.test.js::1', 'b.test.js::1']);
  assert.deepEqual(r.notProvenFiles.map((x) => x.file), ['a.test.js', 'b.test.js']);
  assert.ok(r.notProvenFiles.every((x) => x.cause === 'its trace is missing'));
});

test('appendix 4: a partly accounted re-run makes the unaccounted tests NOT PROVEN', () => {
  const first = [rec('a.test.js::1'), rec('a.test.js::2'), rec('a.test.js::3')];
  const r = accountRerun(first, [rec('a.test.js::2')], ['a.test.js']);
  assert.equal(r.complete, false);
  assert.deepEqual(r.notProven, ['a.test.js::1', 'a.test.js::3']);
  assert.deepEqual(r.notProvenFiles, [{ file: 'a.test.js', cause: 'it ran 1 of its 3 test(s)' }]);
});

test('the bfaf70b4 defect: the old fileOf gave 0 wanted tests for a named project, so "complete" with 0 of 0', () => {
  const oldFileOf = (id) => String(id).split('::', 1)[0];
  const first = [rec('tests/x.test.mjs@@main::a')];
  assert.equal(first.filter((t) => oldFileOf(t.nodeid) === 'tests/x.test.mjs').length, 0);
  // the new decision wants the test and, with no re-run record of it, does not call the re-run complete
  const r = accountRerun(first, [], ['tests/x.test.mjs']);
  assert.equal(r.want.length, 1);
  assert.equal(r.complete, false);
  assert.deepEqual(r.notProven, ['tests/x.test.mjs@@main::a']);
});

test('wrapperRunnerCode: a pass code counts when no test outcome explains it', () => {
  assert.equal(wrapperRunnerCode(0, 0, 0, true), 0);
  assert.equal(wrapperRunnerCode(1, 0, 2, true), 0); // pass 1 red because of its failed tests: decided by the counts
  assert.equal(wrapperRunnerCode(1, 0, 0, true), 1); // pass 1 red with no failed test
  assert.equal(wrapperRunnerCode(0, 1, 0, true), 1);
  assert.equal(wrapperRunnerCode(1, 2, 3, true), 2);
  assert.equal(wrapperRunnerCode(0, 0, 0, false), 1); // the re-run left no trace
});
