// A node-sqlite3 call started outside a test (a beforeAll hook) that never calls back counts as pending work until the
// next test file starts: the tests of this file still pass, at real pace (no real-time grace, no wrong red).
import { test, expect, beforeAll } from 'vitest';
import { createRequire } from 'node:module';

const sqlite3 = createRequire(process.env.FIXTURE_SQLITE3)('sqlite3');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

beforeAll(() => {
  const db = new sqlite3.Database(':memory:');
  db.on('error', () => {});
  const bad = db.prepare('SELECT * FROM not_in_a_hook_either'); // fails without a callback: get() never calls back
  bad.on('error', () => {});
  bad.get(() => {});
});

test('a first test', () => { expect(1).toBe(1); });

test('then 2 x 1 s of sleep (at real pace) passes', async () => {
  await sleep(1000);
  await sleep(1000);
}, 60000);
