'use strict';
// AC2 of the spec "Engine P0: no false green": every row of the shared fixture test/fixtures/exit-cases.json against
// src/exit-status.js. The verifyExit rows are also checked against Python's verify_exit_code
// (tests/test_exit_status_contract.py), so Node and Python verify share one rule.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const xs = require('../src/exit-status');

const ROWS = require(path.join(__dirname, 'fixtures', 'exit-cases.json'));

test('the fixture has the rows the spec requires', () => {
  assert.equal(ROWS.filter((r) => r.fn === 'runExit').length >= 7, true);
  assert.equal(ROWS.filter((r) => r.fn === 'verifyExit').length >= 7, true);
  for (const r of ROWS) assert.ok(r.fn === 'runExit' || r.fn === 'verifyExit', JSON.stringify(r));
});

for (const row of ROWS) {
  test(`${row.fn}: ${row.case} -> ${row.expected}`, () => {
    assert.equal(xs[row.fn](row.input), row.expected, JSON.stringify(row));
    if (row.fn === 'verifyExit') assert.equal(xs.verifyStatus(row.input), row.status, JSON.stringify(row));
  });
}

test('countStatus partitions records; NOT PROVEN tests are counted there only', () => {
  const recs = [
    { nodeid: 'a', outcome: 'passed' }, { nodeid: 'b', outcome: 'failed' }, { nodeid: 'c', outcome: 'error' },
    { nodeid: 'd', outcome: 'skipped' }, { nodeid: 'e', outcome: 'todo' }, { nodeid: 'f', outcome: 'passed' },
  ];
  assert.deepEqual(xs.countStatus(recs), { failed: 2, not_proven: 0, passed: 2, skipped: 2 });
  assert.deepEqual(xs.countStatus(recs, ['f', 'b']), { failed: 1, not_proven: 2, passed: 1, skipped: 2 });
  assert.equal(xs.statusLine({ failed: 1, not_proven: 2, passed: 3, skipped: 4 }), 'detjs: status: failed=1 not_proven=2 passed=3 skipped=4');
  // an outcome outside passed/skipped/todo (a test whose file ended while it ran) is never green: counted failed
  assert.deepEqual(xs.countStatus([{ nodeid: 'i', outcome: 'interrupted' }]), { failed: 1, not_proven: 0, passed: 0, skipped: 0 });
  assert.equal(xs.runExit(xs.countStatus([{ nodeid: 'i', outcome: 'interrupted' }])), 1);
});

test('record() applies the rule to process.exitCode at once (a runner that ends the process itself)', () => {
  const saved = process.exitCode;
  try {
    process.exitCode = 0;
    xs.record({ failed: 1, not_proven: 0, passed: 0, skipped: 0 });
    assert.equal(process.exitCode, 1);
    process.exitCode = 2;
    xs.record({ failed: 0, not_proven: 0, passed: 1, skipped: 0 });
    assert.equal(process.exitCode, 2);
    process.exitCode = undefined;
    xs.record({ failed: 0, not_proven: 0, passed: 1, skipped: 0 });
    assert.equal(process.exitCode, 0);
    assert.deepEqual(xs.recordedStatus(), { failed: 0, not_proven: 0, passed: 1, skipped: 0 });
  } finally {
    process.exitCode = saved;
    xs.record(null);
  }
});
