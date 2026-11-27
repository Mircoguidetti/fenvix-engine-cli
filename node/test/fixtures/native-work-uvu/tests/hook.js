// A node-sqlite3 query a hook started (uvu's before hook, run before the file's first test): the first test waits on
// it with a 60 s guard timer pending (as tarn). The file's first test (src/runners/common.js begin, takeBaseline) must
// not stop the query from counting as pending work, or virtual time jumps to the guard (/review round 4).
const { test } = require('uvu');
const assert = require('uvu/assert');
const { createRequire } = require('node:module');

const sqlite3 = createRequire(process.env.FIXTURE_SQLITE3)('sqlite3');
const LONG = 'WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 30000000) SELECT count(*) AS n FROM c';
let query;

test.before(() => {
  const db = new sqlite3.Database(':memory:');
  query = new Promise((res, rej) => db.get(LONG, (e) => (e ? rej(e) : res('query'))));
});

test('the first test waits on the query its hook started, a 60 s guard timer pending', async () => {
  let g;
  const guard = new Promise((r) => { g = setTimeout(() => r('guard'), 60000); });
  const first = await Promise.race([query, guard]);
  clearTimeout(g);
  assert.is(first, 'query');
});

test.run();
