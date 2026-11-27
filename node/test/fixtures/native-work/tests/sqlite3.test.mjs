// Shape of alakajam's specs (P3 alakajam cause, 2026-11-27): a node-sqlite3 query runs on the libuv thread pool and
// leaves no active resource, while a pool's long guard timer is pending (tarn's 60 s acquire timeout); the suite's
// timeout is 5000 ms. node-sqlite3 is reached through FIXTURE_SQLITE3 (installed by the outer test).
import { test, expect } from 'vitest';
import { createRequire } from 'node:module';

const sqlite3 = createRequire(process.env.FIXTURE_SQLITE3)('sqlite3');
const SLOW = 'WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x<2000000) SELECT sum(x) s FROM c';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const all = (db, sql) => new Promise((res, rej) => db.all(sql, (e, rows) => (e ? rej(e) : res(rows))));

test('a query in flight with a 60 s guard timer pending is not timed out', async () => {
  const db = new sqlite3.Database(':memory:');
  const guard = setTimeout(() => {}, 60000);
  for (let i = 0; i < 3; i++) expect((await all(db, SLOW))[0].s).toBe(2000001000000);
  clearTimeout(guard);
  await new Promise((r) => db.close(r));
}, 5000);

test('statement methods, exec and an error callback count too', async () => {
  const db = new sqlite3.Database(':memory:');
  const guard = setTimeout(() => {}, 60000);
  await new Promise((res, rej) => db.exec('CREATE TABLE t(x)', (e) => (e ? rej(e) : res())));
  const st = db.prepare('INSERT INTO t VALUES (?)');
  await new Promise((res, rej) => st.run(1, (e) => (e ? rej(e) : res())));
  await new Promise((r) => st.finalize(r));
  await expect(all(db, 'SELECT * FROM missing_table')).rejects.toThrow(/no such table/);
  expect((await all(db, SLOW))[0].s).toBe(2000001000000);
  clearTimeout(guard);
  await new Promise((r) => db.close(r));
}, 5000);

test('after the queries a 20 s virtual sleep stays virtual (the pending work is released)', async () => {
  const db = new sqlite3.Database(':memory:');
  expect((await all(db, 'SELECT 1 AS one'))[0].one).toBe(1);
  await new Promise((r) => db.close(r));
  await sleep(20000);
}, 30000);

// alakajam tournament.service (2026-11-27, on 881e56b6): a test ends while its query still runs on the pool's only
// connection; the next test waits for that connection (tarn's queue: no sqlite3 call of its own yet) with a long
// guard timer pending. The query in flight must still count in the next test.
let connectionFree = null;
test('leaves a slow query running on the pool connection', () => {
  const db = new sqlite3.Database(':memory:');
  connectionFree = new Promise((r) => db.all(SLOW, () => db.close(r)));
});

test.skip('a skipped test in between does not end the query\'s pending work', () => {});

test('the next test waits for that connection with a 60 s guard timer pending and is not timed out', async () => {
  const guard = setTimeout(() => {}, 60000);
  await connectionFree;
  clearTimeout(guard);
}, 5000);

test('each with only a row callback and zero rows releases its pending work (20 s sleep after it stays virtual)', async () => {
  const db = new sqlite3.Database(':memory:');
  await new Promise((r) => db.exec('CREATE TABLE e(x)', r));
  db.each('SELECT * FROM e', () => {});
  await new Promise((r) => db.wait(r));
  await new Promise((r) => db.close(r));
  await sleep(20000);
}, 30000);

test('each() on a finalized statement (only its row callback is called, with an error) releases its pending work', async () => {
  const db = new sqlite3.Database(':memory:');
  const st = db.prepare('SELECT 1');
  await new Promise((r) => st.finalize(r));
  await new Promise((r) => st.each((e) => { if (e) r(); }));
  await new Promise((r) => db.close(r));
  await sleep(20000);
}, 30000);

test('a query on a closed database (its statement fails in the constructor) releases its pending work', async () => {
  const db = new sqlite3.Database(':memory:');
  await new Promise((r) => db.close(r));
  await expect(new Promise((res, rej) => db.get('SELECT 1', (e) => (e ? rej(e) : res())))).rejects.toThrow(/closed/i);
  await sleep(20000);
}, 30000);

test('a statement prepared without a callback that fails: its queued call never calls back', async () => {
  const db = new sqlite3.Database(':memory:');
  db.on('error', () => {});
  const bad = db.prepare('SELECT * FROM missing_three');
  bad.on('error', () => {});
  bad.get(() => {});
  await new Promise((r) => setImmediate(r));
}, 30000);

test('the test after it: that call stops counting a few real seconds after its test ended', async () => { await sleep(20000); }, 30000);

test('the next test: a 20 s virtual sleep stays virtual', async () => {
  await sleep(20000);
}, 30000);
