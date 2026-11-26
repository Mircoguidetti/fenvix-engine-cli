'use strict';
// AC4(a) of the spec "Engine P0: no false green" (B3, B4): src/parallel-rerun.js `accountRerun`, the pure decision
// of the hazard re-run -- which first-pass tests it accounted for, and which are NOT PROVEN. Synthetic inputs.
// On bfaf70b4 the function did not exist (the decision was inline in main()) and `fileOf` kept `<file>@@<project>`.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { accountRerun, fileOf, hazardFiles, labelFile, wrapperRunnerCode, rerunArgs } = require('../src/parallel-rerun');

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
  // changed (proof to the customer, B1): the cause names the file and the one-lane re-run, and says how many tests
  assert.deepEqual(r.notProvenFiles, [{ file: 'a.test.js', cause: 'a.test.js: the one-lane re-run ran 0 of its 2 test(s)', tests: 2 }]);
});

test('B3: a missing re-run trace makes every first-pass test of the hazard files NOT PROVEN', () => {
  const first = [rec('a.test.js::1'), rec('b.test.js::1'), rec('c.test.js::1')];
  const r = accountRerun(first, null, ['a.test.js', 'b.test.js']);
  assert.equal(r.complete, false);
  assert.deepEqual(r.notProven, ['a.test.js::1', 'b.test.js::1']);
  assert.deepEqual(r.notProvenFiles.map((x) => x.file), ['a.test.js', 'b.test.js']);
  // changed (proof to the customer, B1): the cause names the file and the one-lane re-run
  assert.deepEqual(r.notProvenFiles.map((x) => x.cause), ['a.test.js: the one-lane re-run left no trace', 'b.test.js: the one-lane re-run left no trace']);
  assert.deepEqual(r.notProvenFiles.map((x) => x.tests), [1, 1]);
});

test('appendix 4: a partly accounted re-run makes the unaccounted tests NOT PROVEN', () => {
  const first = [rec('a.test.js::1'), rec('a.test.js::2'), rec('a.test.js::3')];
  const r = accountRerun(first, [rec('a.test.js::2')], ['a.test.js']);
  assert.equal(r.complete, false);
  assert.deepEqual(r.notProven, ['a.test.js::1', 'a.test.js::3']);
  // changed (proof to the customer, B1): the cause names the file and the one-lane re-run, and says how many tests
  assert.deepEqual(r.notProvenFiles, [{ file: 'a.test.js', cause: 'a.test.js: the one-lane re-run ran 1 of its 3 test(s)', tests: 2 }]);
});

test('the bfaf70b4 defect: a project-qualified id is wanted, and with no re-run record of it is NOT PROVEN', () => {
  const first = [rec('tests/x.test.mjs@@main::a')];
  const r = accountRerun(first, [], ['tests/x.test.mjs']);
  assert.equal(r.want.length, 1);
  assert.equal(r.complete, false);
  assert.deepEqual(r.notProven, ['tests/x.test.mjs@@main::a']);
});

test('wrapperRunnerCode: the re-run may raise the first pass\'s code, never lower it (default-deny)', () => {
  assert.equal(wrapperRunnerCode(0, 0, true), 0);
  assert.equal(wrapperRunnerCode(1, 0, true), 1); // a red first pass stays red, whatever the re-run shows
  assert.equal(wrapperRunnerCode(3, 0, true), 3);
  assert.equal(wrapperRunnerCode(0, 1, true), 1);
  assert.equal(wrapperRunnerCode(1, 2, true), 2);
  assert.equal(wrapperRunnerCode(2, 0, true), 2);
  assert.equal(wrapperRunnerCode(0, 0, false), 1); // the re-run left no trace
});

// /review pass 3: the second pass runs exactly the hazard files -- the user's own file selectors are not inherited
test('rerunArgs drops the runners\' file selectors (shard, changed, related, only-failures)', () => {
  assert.deepEqual(rerunArgs(['run', '--shard=1/2', '--det', '--changed', 'HEAD~1', '--bail=1', '-t', 'x']), ['run', '--det', '--bail=1', '-t', 'x']);
  assert.deepEqual(rerunArgs(['--shard', '2/3', '-o', '--onlyFailures', '--findRelatedTests', '--det']), ['--det']);
  assert.deepEqual(rerunArgs(['--changedSince', 'main', '--related', 'src/a.js', '--lastCommit', '--det-trace', 't.jsonl', '--det']), ['--det']);
});

// /review (2026-11-23): a record detjs wrote for a test that never started in the re-run (B5) is not a re-run of it
test('accountRerun: a never-started record in the re-run does not account for the test', () => {
  const first = [rec('a.test.js::1'), rec('a.test.js::2')];
  const never = { nodeid: 'a.test.js::2', outcome: 'skipped', events: [{ s: 'sched', o: 'sched.never_started', v: '' }] };
  const r = accountRerun(first, [rec('a.test.js::1'), never], ['a.test.js']);
  assert.equal(r.complete, false);
  assert.deepEqual(r.notProven, ['a.test.js::2']);
});

// /review (2026-11-23): Jest --det-isolate's per-test filter, built from the detjs id
test('isolate namePattern: " #n" stripped only for a real duplicate, "::" inside a name matched', () => {
  const { namePattern } = require('../src/isolate');
  const ids = new Set(['f::regression for issue #42', 'f::d::x', 'f::d::x #2', 'f::Parser::parse throws']);
  const m = (id, name) => new RegExp(`^${namePattern(id, ids)}$`).test(name);
  assert.equal(m('f::regression for issue #42', 'regression for issue #42'), true);
  assert.equal(m('f::regression for issue #42', 'regression for issue'), false);
  assert.equal(m('f::d::x #2', 'd x'), true); // the duplicate runs under its shared name
  assert.equal(m('f::Parser::parse throws', 'Parser::parse throws'), true); // a test named with '::'
  assert.equal(m('f::Parser::parse throws', 'Parser parse throws'), true); // or a describe 'Parser'
});

// protects=each NOT PROVEN file entry carries how many of its tests are NOT PROVEN, and those counts add up to the
// unaccounted tests (the runner sums them into proof.not_proven_causes); fails_when=a count is missing, off, or the
// sum differs; no_claim=the re-run itself (main(), see the parallel-p041 tests).
test('B1: notProvenFiles[].tests sum to the unaccounted tests, one entry per file, want.length counts the hazard files only', () => {
  const first = [rec('a.test.js::1'), rec('a.test.js::2'), rec('b.test.js::1'), rec('b.test.js::2'), rec('b.test.js::3'), rec('c.test.js::1')];
  const r = accountRerun(first, [rec('a.test.js::2')], ['a.test.js', 'b.test.js']);
  assert.equal(r.want.length, 5); // what main() writes as meta.hazard_rerun.tests
  assert.deepEqual(r.notProvenFiles.map((x) => [x.file, x.tests]), [['a.test.js', 1], ['b.test.js', 3]]);
  assert.equal(r.notProvenFiles.reduce((a, x) => a + x.tests, 0), r.unaccounted.length);
  assert.match(r.notProvenFiles[1].cause, /^b\.test\.js: the one-lane re-run ran 0 of its 3 test\(s\)$/);
});

// founder decision 2026-11-26 ("alakajam A"): alakajam's server/core/rate-limiter.spec.ts is a whole-file describe.skip.
// Its tests never start in the first pass nor in the one-lane re-run (B5 never-started records both times), and the
// re-run was NOT PROVEN / incomplete because a never-started re-run record never accounts for a test.
// protects=a test that never started in the first pass is accounted for by a re-run record of it (never started
// again); fails_when=such a file makes the re-run incomplete; no_claim=a test the first pass RAN still needs a re-run
// record that ran (the test above, unchanged)
test('accountRerun: a test that never started in the first pass is accounted for by its never-started re-run record', () => {
  const never = (id) => ({ nodeid: id, outcome: 'skipped', never_started: true });
  const first = [rec('a.test.js::1'), never('a.test.js::skipped 1'), never('a.test.js::skipped 2')];
  const r = accountRerun(first, [rec('a.test.js::1'), never('a.test.js::skipped 1'), never('a.test.js::skipped 2')], ['a.test.js']);
  assert.equal(r.complete, true);
  assert.deepEqual(r.notProven, []);
  // a never-started first-pass test the re-run does not report at all is still NOT PROVEN
  const r2 = accountRerun(first, [rec('a.test.js::1'), never('a.test.js::skipped 1')], ['a.test.js']);
  assert.equal(r2.complete, false);
  assert.deepEqual(r2.notProven, ['a.test.js::skipped 2']);
});
