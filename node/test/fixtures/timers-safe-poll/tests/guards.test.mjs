// Guards of P1 (the outer test times this file): virtual time must still run fast where nothing real is awaited.
// (1) the runner's own test timeout is a safe timer too, but a runner deadline: it must not count as pending work;
// (2) a safe timer a test leaves behind (an un-awaited vi.waitFor) must not slow the next test (dropped at test end);
// (3) a vi.waitFor / expect.poll that resolved no longer counts (its timers are untracked when they run or are cleared);
// (4) a hook timeout is a runner deadline too (a 20 s virtual sleep in beforeEach stays fast).
import { test, expect, vi, describe, beforeEach } from 'vitest';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test('a 20 s virtual sleep under a 30 s test timeout', async () => {
  await sleep(20000);
  expect(1).toBe(1);
}, 30000);

test('leaves a vi.waitFor polling behind', () => {
  vi.waitFor(() => { throw new Error('never'); }, { timeout: 120000, interval: 50 }).catch(() => {});
});

test('the next test sleeps 20 s virtually', async () => {
  await sleep(20000);
  expect(1).toBe(1);
}, 30000);

test('a resolved vi.waitFor and expect.poll, then a 20 s virtual sleep', async () => {
  let ready = false;
  setImmediate(() => { ready = true; });
  await vi.waitFor(() => expect(ready).toBe(true));
  await expect.poll(() => ready).toBe(true);
  await sleep(20000);
  expect(1).toBe(1);
}, 30000);

describe('a hook deadline', () => {
  beforeEach(async () => { await sleep(20000); }, 30000);
  test('runs after a 20 s virtual beforeEach sleep', () => { expect(1).toBe(1); });
});
