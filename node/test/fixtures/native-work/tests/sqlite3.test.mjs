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
  // prepared without a callback: the error is an 'error' event, and the queued call is never called back
  const bad = db.prepare('SELECT * FROM missing_too');
  await new Promise((r) => { bad.on('error', () => r()); bad.all(() => {}); });
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
