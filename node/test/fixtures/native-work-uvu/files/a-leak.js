// A node-sqlite3 call that never calls back (a statement that failed without a callback): it counts as pending work
// for the rest of this file.
const { test } = require('uvu');
const { createRequire } = require('node:module');

const sqlite3 = createRequire(process.env.FIXTURE_SQLITE3)('sqlite3');

test('a statement prepared without a callback that fails: its queued call never calls back', async () => {
  const db = new sqlite3.Database(':memory:');
  db.on('error', () => {});
  const bad = db.prepare('SELECT * FROM missing_four');
  bad.on('error', () => {});
  bad.get(() => {});
  await new Promise((r) => setImmediate(r));
});

test.run();
