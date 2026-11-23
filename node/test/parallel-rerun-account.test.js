'use strict';
// AC4(a) of the spec "Engine P0: no false green" (B3, B4): src/parallel-rerun.js `accountRerun`, the pure decision
// of the hazard re-run -- which first-pass tests it accounted for, and which are NOT PROVEN. Synthetic inputs.
// On bfaf70b4 the function did not exist (the decision was inline in main()) and `fileOf` kept `<file>@@<project>`.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { accountRerun, fileOf, hazardFiles, labelFile, wrapperRunnerCode, firstRedInHazardFiles } = require('../src/parallel-rerun');

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

test('the bfaf70b4 defect: a project-qualified id is wanted, and with no re-run record of it is NOT PROVEN', () => {
  const first = [rec('tests/x.test.mjs@@main::a')];
  const r = accountRerun(first, [], ['tests/x.test.mjs']);
  assert.equal(r.want.length, 1);
  assert.equal(r.complete, false);
  assert.deepEqual(r.notProven, ['tests/x.test.mjs@@main::a']);
});

test('wrapperRunnerCode: pass 1\'s code counts unless all of its red is inside the re-run files', () => {
  assert.equal(wrapperRunnerCode(0, 0, true, true), 0);
  assert.equal(wrapperRunnerCode(1, 0, true, true), 0); // all of pass 1's red was re-examined and cleared
  assert.equal(wrapperRunnerCode(1, 0, false, true), 1); // red outside the re-run (a file that failed to load, ...)
  assert.equal(wrapperRunnerCode(0, 1, true, true), 1);
  assert.equal(wrapperRunnerCode(1, 2, true, true), 2);
  assert.equal(wrapperRunnerCode(2, 0, true, true), 2);
  assert.equal(wrapperRunnerCode(0, 0, true, false), 1); // the re-run left no trace
});

// /review (2026-11-23): the false green the wrapper had on bfaf70b4 and on this branch before the fix -- a file
// that failed to load (no test record) next to a hazard failure the re-run cleared gave exit 0.
test('firstRedInHazardFiles: only a red that is all inside the hazard files, as the shell reports it', () => {
  const files = ['a.test.mjs', 'b.test.mjs'];
  const ok = { meta: { file_failures: { known: true, files: [], unhandled: 0 } } };
  const recs = [rec('a.test.mjs::t', 'failed'), rec('c.test.mjs::u')];
  assert.equal(firstRedInHazardFiles(ok, recs, files), true);
  // a failed test outside the hazard files
  assert.equal(firstRedInHazardFiles(ok, [...recs, rec('c.test.mjs::v', 'failed')], files), false);
  // a file failure outside the hazard files (failed to load: no test record at all)
  assert.equal(firstRedInHazardFiles({ meta: { file_failures: { known: true, files: ['z.test.mjs'], unhandled: 0 } } }, recs, files), false);
  // a file failure inside them, also as a project label
  assert.equal(firstRedInHazardFiles({ meta: { file_failures: { known: true, files: ['b.test.mjs'], unhandled: 0 } } }, recs, files), true);
  // an error outside any file
  assert.equal(firstRedInHazardFiles({ meta: { file_failures: { known: true, files: [], unhandled: 1 } } }, recs, files), false);
  // a shell that cannot report file failures (node-test), or an older trace: not proven, the code stays
  assert.equal(firstRedInHazardFiles({ meta: { file_failures: { known: false, files: [], unhandled: 0 } } }, recs, files), false);
  assert.equal(firstRedInHazardFiles({ meta: {} }, recs, files), false);
});
