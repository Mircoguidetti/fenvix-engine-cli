'use strict';
// Jest with the jsdom environment: globals such as `crypto` and `performance`
// are accessors on the jsdom window (found on mobx by the harness: the realm
// installation threw and every suite failed). The controls must apply and the
// suite must pass with and without --det.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { project, run, failed } = require('./helpers');

const SUITE = `
test('jsdom globals under control', () => {
  const a = Math.random();
  expect(a >= 0 && a < 1).toBe(true);
  expect(typeof crypto.getRandomValues).toBe('function');
  expect(typeof performance.now()).toBe('number');
  expect(new Date() instanceof Date).toBe(true);
  expect(typeof document.createElement('div').getBoundingClientRect).toBe('function');
});
test('leaks a timer that throws after the test (dom-testing-library waitFor pattern)', () => {
  setTimeout(() => { throw new Error('late timer'); }, 60000);
});
test('jsdom timers', async () => {
  const t0 = Date.now();
  await new Promise((r) => setTimeout(r, 2000));
  expect(Date.now() - t0).toBeGreaterThanOrEqual(2000);
}, 10000);
`;

test('jest jsdom environment: controls apply, outcomes unchanged', { timeout: 120000 }, () => {
  const dir = project('jest', 'jsdom', { suite: SUITE }, { jest: { testEnvironment: 'jsdom' } });
  const normal = run('jest', dir);
  const det = run('jest', dir, ['--det']);
  for (const [m, r] of Object.entries({ normal, det })) {
    assert.equal(Object.keys(r.outcomes).length, 3, `${m}\n${r.stdout}\n${r.stderr}`);
    assert.deepEqual(failed(r), [], `${m}\n${r.stdout}\n${r.stderr}`);
  }
  const ops = det.trace.tests.flatMap((t) => t.events.map((e) => e.o));
  for (const op of ['Math.random', 'performance.now', 'Date', 'setTimeout']) assert.ok(ops.includes(op), op);
});
