// A node-sqlite3 call that never calls back (a statement that failed without a callback): it counts as pending work
// until the next test file starts, so the rest of this file runs its timers at real pace; it never changes an
// outcome (coordinator /review, 2026-11-27: no real-time grace while a test may still wait on it).
import { test } from 'vitest';
import { createRequire } from 'node:module';

const sqlite3 = createRequire(process.env.FIXTURE_SQLITE3)('sqlite3');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test('a statement prepared without a callback that fails: its queued call never calls back', async () => {
  const db = new sqlite3.Database(':memory:');
  db.on('error', () => {});
  const bad = db.prepare('SELECT * FROM missing_three');
  bad.on('error', () => {});
  bad.get(() => {});
  await new Promise((r) => setImmediate(r));
}, 30000);

test('the rest of the file runs at real pace and passes (the call counts until the next file)', async () => { await sleep(1000); }, 30000);
