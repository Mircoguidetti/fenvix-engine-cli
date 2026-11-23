'use strict';
// B7 of the spec "Engine P0: no false green", unit level: which process prints the status line
// (src/session.js printsStatus) and how the counts get into the trace header (stampStatus). Added by /review
// (2026-11-23): the suppression branches had no test of their own.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { TMP } = require('./helpers');
const { printsStatus, stampStatus } = require('../src/session');

test('printsStatus: only the process that writes the final trace prints', () => {
  const hazard = { parallel: { hazards: [{ a: 'x.test.mjs', b: 'y.test.mjs' }] } };
  assert.equal(printsStatus({}, {}), true);
  assert.equal(printsStatus({}, { DETJS_ISOLATE_CHILD: '1' }), false);
  assert.equal(printsStatus({}, { DETJS_HAZARD_RERUN: '1', DETJS_HAZARD_PASS: '2' }), false);
  assert.equal(printsStatus(hazard, { DETJS_HAZARD_RERUN: '1', DETJS_HAZARD_PASS: '1' }), false);
  assert.equal(printsStatus({}, { DETJS_HAZARD_RERUN: '1', DETJS_HAZARD_PASS: '1' }), true);
  // the user's own DETJS_HAZARD_RERUN=1 (it switches the wrapper off): this run's trace is the final one
  assert.equal(printsStatus(hazard, { DETJS_HAZARD_RERUN: '1' }), true);
});

test('stampStatus: counts into meta.status, other header bytes unchanged; unreadable trace gives null', () => {
  const dir = path.join(TMP, 'status-line');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  const p = path.join(dir, 'trace.jsonl');
  const header = '{"type":"header","format":"detpy-trace","version":1,"encoding":2,"meta":{"seed":0},"order":[]}';
  const lines = [header, '{"type":"test","nodeid":"a","outcome":"passed"}', '{"type":"test","nodeid":"b","outcome":"failed"}',
    '{"type":"test","nodeid":"c","outcome":"todo"}', '{"type":"test" broken', '{"type":"footer","n_tests":4}'];
  fs.writeFileSync(p, `${lines.join('\n')}\n`);
  const st = stampStatus(p);
  // the unparseable test line counts as failed: no count is ever lowered by a line detjs cannot read
  assert.deepEqual(st, { failed: 2, not_proven: 0, passed: 1, skipped: 1 });
  const out = fs.readFileSync(p, 'utf8').split('\n');
  assert.equal(out[0], header.replace('"meta":{', `"meta":{"status":${JSON.stringify(st)},`));
  assert.deepEqual(out.slice(1), [...lines.slice(1), '']);
  assert.deepEqual(fs.readdirSync(dir), ['trace.jsonl'], 'no temporary file is left');
  assert.equal(stampStatus(path.join(dir, 'absent.jsonl')), null);
});

test('fileFailures: file errors and error/failed states; unreadable side data is not known', () => {
  const { fileFailures } = require('../src/session');
  const dir = path.join(TMP, 'status-line-side');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'side'), { recursive: true });
  const side = (n, o) => fs.writeFileSync(path.join(dir, 'side', `${n}.json`), JSON.stringify(o));
  side('a', { file: 'a.test.mjs', file_error: ['Error', 'collect', 'boom'], states: {} });
  side('b', { file: 'b.test.mjs', file_error: null, states: { 'b.test.mjs::t': 'error' } });
  side('c', { file: 'c.test.mjs', file_error: null, states: { 'c.test.mjs::t': 'passed' } });
  // Vitest: the main process's verdict plus the side data; unknown without the verdict or the unhandled count
  assert.deepEqual(fileFailures(dir, { runner: 'vitest', unhandled_errors: 0, runner_failed_files: ['n.test.mjs'] }),
    { known: true, files: ['a.test.mjs', 'b.test.mjs', 'n.test.mjs'], unhandled: 0 });
  assert.equal(fileFailures(dir, { runner: 'vitest', unhandled_errors: 0 }).known, false);
  assert.equal(fileFailures(dir, { runner: 'vitest', runner_failed_files: [] }).known, false);
  // Jest: known only when every file of the run left side data
  const parts = ['a', 'b', 'c'].map((n) => ({ fileId: `${n}.test.mjs`, part: `${n}.jsonl` }));
  assert.equal(fileFailures(dir, { runner: 'jest' }, parts).known, true);
  assert.equal(fileFailures(dir, { runner: 'jest' }, [...parts, { fileId: 'e.test.mjs', part: 'e.jsonl' }]).known, false);
  assert.equal(fileFailures(dir, { runner: 'node-test' }).known, false);
  fs.writeFileSync(path.join(dir, 'side', 'd.json'), '{not json');
  assert.equal(fileFailures(dir, { runner: 'vitest', unhandled_errors: 0, runner_failed_files: [] }).known, false);
});
