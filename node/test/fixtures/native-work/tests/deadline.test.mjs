// F4 (founder decision, 2026-11-27): the pending work node-sqlite3 adds must never keep a test alive past its runner
// deadline. The first two tests wait for something that never comes: each must fail with the runner's timeout, and the
// run must end; the last two check that the tests after them still pass (the call that never calls back counts
// until the next file, so they run at real pace). node-sqlite3 is reached through FIXTURE_SQLITE3 (installed by the outer test).
import { test, expect } from 'vitest';
import { createRequire } from 'node:module';

const sqlite3 = createRequire(process.env.FIXTURE_SQLITE3)('sqlite3');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test('an idle pooled connection while the test waits forever: timed out at the deadline', async () => {
  const pool = new sqlite3.Database(':memory:');
  await new Promise((r) => pool.get('SELECT 1', r)); // the connection is now idle in the pool
  const acquireTimeout = setTimeout(() => {}, 60000); // a pool's guard timer, as tarn's
  await new Promise(() => {}); // never settles
  clearTimeout(acquireTimeout);
}, 5000);

test('a node-sqlite3 call that never calls back: timed out at the deadline', async () => {
  const db = new sqlite3.Database(':memory:');
  db.on('error', () => {});
  const bad = db.prepare('SELECT * FROM never_there'); // fails without a callback: its queued call is never called back
  bad.on('error', () => {});
  await new Promise((r) => bad.get(r)); // never settles, and counts as pending work
}, 5000);

test('the test after it', () => {});

test('then a 1 s sleep (at real pace) passes', async () => {
  await sleep(1000);
  expect(1).toBe(1);
}, 30000);
