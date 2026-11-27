// A node-sqlite3 call started outside a test (a beforeAll hook) that never calls back must not keep the driver at
// real pace for the rest of the worker: it stops counting a few real seconds after the next test ends.
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

test('then 2 x 20 s of virtual sleep stays virtual', async () => {
  await sleep(20000);
  await sleep(20000);
}, 60000);
