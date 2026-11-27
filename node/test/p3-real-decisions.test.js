'use strict';
// Real-time decisions of the P3 timer rule and native work must be recorded (founder decision on the coordinator's
// /review of claude/p3-timers-merge @ 105cdcad, 2026-11-27, findings 1 and 2).
//
// protects: (1) P1 and (1b) P2: a timer fired at real pace because a runner poll (P1, safePending) or a child-starting test (P2,
//   childPaced) keeps the driver slow is a decision real time made: the test's result is not reused by --det-cache;
//   (2) a node-sqlite3 call still in flight keeps counting when another test (a concurrent sibling) ends: the 3 s
//   real-time grace starts only when the test that started the call ends.
// fails_when: fire(false) runs for safePending / childPaced without recording the choice (run 2 reuses the file);
//   or a sibling's end starts the grace of a still-running query (virtual time jumps to the 60 s guard timer and the
//   waiting test times out).
// no_claim: other real-time sources (they have their own tests); a plain test file is reused (the control shows the
//   cache works). Needs node-sqlite3 5.1.7 (installed once into test/.tmp/pkgs-sqlite3, as test/native-work.test.js).
// Run: cd node && node --test --test-concurrency=1 test/p3-real-decisions.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, sqlite3Pkg } = require('./helpers');
const { fixture, crun, show, reused } = require('./runner-helpers');

const T = { timeout: 600000 };
const CONFIG = { 'vitest.config.mjs': "export default { test: { include: ['tests/**/*.test.mjs'], fileParallelism: false } };\n" };
const CONTROL = { 'tests/control.test.mjs': "import { test, expect } from 'vitest';\ntest('control', () => { expect(1 + 1).toBe(2); });\n" };

test('(1) P1: a vi.waitFor racing a test timer is decided by real time and not reused', T, () => {
  const dir = fixture('p3-real', 'p1-race', {
    ...CONFIG, ...CONTROL,
    'tests/race.test.mjs': `import { test, vi } from 'vitest';
test('a vi.waitFor racing a 50 ms test timer', async () => {
  let flag = 0;
  setTimeout(() => { flag = 1; }, 50);
  await vi.waitFor(() => { if (!flag) throw new Error('not yet'); }, { interval: 50, timeout: 60 }).catch(() => {});
});
`,
  });
  const r1 = crun('vitest', dir, ['run']);
  assert.equal(r1.status, 0, show(r1));
  const r2 = crun('vitest', dir, ['run']);
  assert.ok(reused(r2).includes('tests/control.test.mjs'), `the control file is reused\n${show(r2)}`);
  assert.ok(!reused(r2).includes('tests/race.test.mjs'), `WRONG REUSE: real time decided the race\n${show(r2)}`);
  const why = JSON.stringify((r1.summary && r1.summary.not_cached_detail) || {});
  assert.match(why, /fired at real pace while a runner poll/, `run 1 names the runner poll as the reason\n${show(r1)}`);
});

test('(1b) P2: short timers paced after a child process are decided by real time and not reused', T, () => {
  const dir = fixture('p3-real', 'p2-paced', {
    ...CONFIG, ...CONTROL,
    'tests/paced.test.mjs': `import { test } from 'vitest';
import { spawnSync } from 'node:child_process';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
test('a child, then short timers at real pace', async () => {
  spawnSync(process.execPath, ['-e', '0']);
  for (let i = 0; i < 3; i++) await sleep(20);
});
`,
  });
  const r1 = crun('vitest', dir, ['run']);
  assert.equal(r1.status, 0, show(r1));
  const r2 = crun('vitest', dir, ['run']);
  assert.ok(reused(r2).includes('tests/control.test.mjs'), `the control file is reused\n${show(r2)}`);
  assert.ok(!reused(r2).includes('tests/paced.test.mjs'), `WRONG REUSE: the paced timers ran at real pace\n${show(r2)}`);
});


function env() {
  const e = { ...process.env, FIXTURE_SQLITE3: sqlite3Pkg() };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_EPOCH', 'DETJS_CACHE_DIR']) delete e[k];
  return e;
}

test('(2) a still-running query keeps counting when a concurrent sibling ends', T, () => {
  const dir = fixture('p3-real', 'sibling-grace', {
    ...CONFIG,
    'tests/sibling.test.mjs': `import { test, expect } from 'vitest';
import { createRequire } from 'node:module';
const sqlite3 = createRequire(process.env.FIXTURE_SQLITE3)('sqlite3');
// several seconds of real work: longer than the 3 s grace (the outer test checks it in the plain run)
const SLOW = 'WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x<50000000) SELECT sum(x) s FROM c';
test.concurrent('a slow query with a 60 s guard timer pending (as tarn) is not timed out', async () => {
  const db = new sqlite3.Database(':memory:');
  const guard = setTimeout(() => {}, 60000);
  const rows = await new Promise((res, rej) => db.all(SLOW, (e, r) => (e ? rej(e) : res(r))));
  clearTimeout(guard);
  expect(rows[0].s).toBe(1250000025000000);
  await new Promise((r) => db.close(r));
}, 30000);
test.concurrent('a sibling that ends at once', () => { expect(1).toBe(1); });
`,
  });
  const t0 = Date.now();
  const plain = spawnSync(process.execPath, [path.join(__dirname, '..', 'node_modules', 'vitest', 'vitest.mjs'), 'run', '-t', 'slow query'], { cwd: dir, encoding: 'utf8', env: env(), timeout: 240000 });
  const plainWall = (Date.now() - t0) / 1000;
  assert.equal(plain.status, 0, `the plain run passes\n${plain.stdout}\n${plain.stderr}`);
  assert.ok(plainWall > 4.5, `the query must outlast the 3 s grace for this test to mean anything: the plain run took ${plainWall} s`);
  const r = spawnSync(process.execPath, [BIN, 'vitest', 'run', '--det', '--det-workers=1'],
    { cwd: dir, encoding: 'utf8', env: env(), timeout: 240000 });
  const text = `${(r.stdout || '').slice(-3000)}\n${(r.stderr || '').slice(-2000)}`;
  assert.equal(r.status, 0, `the --det run passes (the query kept counting)\n${text}`);
});

test('(2b) a node-sqlite3 call whose grace ends while still in flight: the file is not reused', T, () => {
  const dir = fixture('p3-real', 'grace-expiry', {
    ...CONFIG, ...CONTROL,
    'tests/expire.test.mjs': `import { test } from 'vitest';
import { createRequire } from 'node:module';
const sqlite3 = createRequire(process.env.FIXTURE_SQLITE3)('sqlite3');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
test('starts a call that never calls back', () => {
  const db = new sqlite3.Database(':memory:');
  db.on('error', () => {});
  const bad = db.prepare('SELECT * FROM never_there');
  bad.on('error', () => {});
  bad.get(() => {});
});
test('runs while that call is still counted, until its grace ends', async () => { await sleep(5000); }, 30000);
`,
  });
  const e = { FIXTURE_SQLITE3: sqlite3Pkg() };
  const r1 = crun('vitest', dir, ['run'], { env: e });
  assert.equal(r1.status, 0, show(r1));
  const r2 = crun('vitest', dir, ['run'], { env: e });
  assert.ok(reused(r2).includes('tests/control.test.mjs'), `the control file is reused\n${show(r2)}`);
  assert.ok(!reused(r2).includes('tests/expire.test.mjs'), `WRONG REUSE: real time decided when the call stopped counting\n${show(r2)}`);
});

// Unit level (a fake node-sqlite3 binding): a call whose owning test already ended (adversarial F1: issued from held
// I/O delivered during that test's end) and a call whose owner never ends both still stop counting in bounded time.
test('(3) a native call whose owner already ended, or never ends, still stops counting', { timeout: 60000 }, async () => {
  const sched = require('../src/sched');
  const { STATE } = require('../src/state');
  const patcher = { set(o, k, v) { o[k] = v; } };
  function Database() {}
  Database.prototype.exec = function exec() { /* never calls back */ };
  function Statement() {}
  const b = { Database, Statement, OPEN_READWRITE: 2 };
  sched.nativeWork(patcher, b);
  const saved = STATE.testId;
  try {
    STATE.testId = 'unit-A';
    sched.releaseTestWork('unit-A'); // A's end sweep ran ...
    new b.Database().exec('x', () => {}); // ... then a call is issued while STATE.testId is still A
    STATE.testId = null;
    assert.ok(sched.isPending(), 'the call counts');
    sched.releaseTestWork('unit-B'); // the next test end
    await new Promise((r) => setTimeout(r, 3500));
    assert.ok(!sched.isPending(), 'a call whose owner had already ended stops counting 3 s after the next test end');
    STATE.testId = 'unit-C';
    new b.Database().exec('y', () => {}); // owner C, whose end never comes
    STATE.testId = null;
    sched.releaseTestWork('unit-D');
    await new Promise((r) => setTimeout(r, 3500));
    assert.ok(sched.isPending(), 'another test end gives a still-owned call more time than its own end does');
    await new Promise((r) => setTimeout(r, 9000));
    assert.ok(!sched.isPending(), 'a call whose owner never ends stops counting 12 s after another test end');
  } finally {
    STATE.testId = saved;
  }
});

// Coordinator /review of 105cdcad..8b59fa8f (2026-11-27): (4) CRITICAL 1 with test.concurrent; (5) and (6) CRITICAL 2:
// a query still running must keep counting for as long as it runs, whatever ends meanwhile (no real-time grace).
test('(4) P1 with test.concurrent: a vi.waitFor racing a test timer is not reused', T, () => {
  const dir = fixture('p3-real', 'p1-race-concurrent', {
    ...CONFIG, ...CONTROL,
    'tests/race.test.mjs': `import { test, vi } from 'vitest';
test.concurrent('a vi.waitFor racing a 50 ms test timer', async () => {
  let flag = 0;
  setTimeout(() => { flag = 1; }, 50);
  await vi.waitFor(() => { if (!flag) throw new Error('not yet'); }, { interval: 50, timeout: 60 }).catch(() => {});
});
test.concurrent('a sibling', async () => { await new Promise((r) => setTimeout(r, 10)); });
`,
  });
  const r1 = crun('vitest', dir, ['run']);
  assert.equal(r1.status, 0, show(r1));
  const r2 = crun('vitest', dir, ['run']);
  assert.ok(reused(r2).includes('tests/control.test.mjs'), `the control file is reused\n${show(r2)}`);
  assert.ok(!reused(r2).includes('tests/race.test.mjs'), `WRONG REUSE: real time decided the race of a concurrent test\n${show(r2)}`);
});

// count(*) over a recursive CTE: tens of seconds of real work without an integer overflow
const LONG = (n) => `WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x<${n}) SELECT count(*) n FROM c`;

function plainAndDet(dir, minPlain, label) {
  const t0 = Date.now();
  const plain = spawnSync(process.execPath, [path.join(__dirname, '..', 'node_modules', 'vitest', 'vitest.mjs'), 'run'], { cwd: dir, encoding: 'utf8', env: env(), timeout: 300000 });
  const plainWall = (Date.now() - t0) / 1000;
  assert.equal(plain.status, 0, `the plain run passes\n${plain.stdout}\n${plain.stderr}`);
  assert.ok(plainWall > minPlain, `${label}: the query must run longer than ${minPlain} s for this test to mean anything (plain ${plainWall} s)`);
  const r = spawnSync(process.execPath, [BIN, 'vitest', 'run', '--det', '--det-workers=1'], { cwd: dir, encoding: 'utf8', env: env(), timeout: 300000 });
  const text = `${(r.stdout || '').slice(-3000)}\n${(r.stderr || '').slice(-2000)}`;
  assert.equal(r.status, 0, `${label}: the --det run passes like the plain run (no wrong red)\n${text}`);
}

test('(5) a concurrent query running longer than 12 s keeps counting when its sibling ends', T, () => {
  const dir = fixture('p3-real', 'sibling-long', {
    ...CONFIG,
    'tests/sibling.test.mjs': `import { test, expect } from 'vitest';
import { createRequire } from 'node:module';
const sqlite3 = createRequire(process.env.FIXTURE_SQLITE3)('sqlite3');
test.concurrent('a long query with a 60 s guard timer pending is not timed out', async () => {
  const db = new sqlite3.Database(':memory:');
  const guard = setTimeout(() => {}, 60000);
  const rows = await new Promise((res, rej) => db.all(${JSON.stringify(LONG(150000000))}, (e, r) => (e ? rej(e) : res(r))));
  clearTimeout(guard);
  expect(rows[0].n).toBe(150000000);
  await new Promise((r) => db.close(r));
}, 55000);
test.concurrent('a sibling that ends at once', () => { expect(1).toBe(1); });
`,
  });
  plainAndDet(dir, 14, '(5)');
});

test('(6) a query still running when its test ends keeps counting while the next test waits for it', T, () => {
  const dir = fixture('p3-real', 'carry-long', {
    ...CONFIG,
    'tests/carry.test.mjs': `import { test, expect } from 'vitest';
import { createRequire } from 'node:module';
const sqlite3 = createRequire(process.env.FIXTURE_SQLITE3)('sqlite3');
let connectionFree = null;
test('leaves a long query running on the pool connection', () => {
  const db = new sqlite3.Database(':memory:');
  connectionFree = new Promise((r) => db.all(${JSON.stringify(LONG(60000000))}, () => db.close(r)));
});
test('the next test waits for that connection with a 60 s guard timer pending (as tarn)', async () => {
  const guard = setTimeout(() => {}, 60000);
  await connectionFree;
  clearTimeout(guard);
  expect(1).toBe(1);
}, 40000);
`,
  });
  plainAndDet(dir, 5, '(6)');
});
