'use strict';
// Real-time decisions of the P3 timer rule and native work must be recorded (founder decision on the coordinator's
// /review of claude/p3-timers-merge @ 105cdcad, 2026-11-27, findings 1 and 2).
//
// protects: (1) P1 and (1b) P2: a timer fired at real pace because a runner poll (P1, safePending) or a child-starting test (P2,
//   childPaced) keeps the driver slow is a decision real time made: the test's result is not reused by --det-cache;
//   (2) a node-sqlite3 call still in flight keeps counting for as long as it runs, whatever ends meanwhile (no
//   real-time grace: (2), (5), (6)); one that never calls back counts until the next file opens, also past the
//   file's first test (3); (3b) the once-per-reason cache flag is per test (concurrent tests too).
// fails_when: fire(false) runs for safePending / childPaced without recording the choice (run 2 reuses the file);
//   or a still-running query stops counting before it ends (virtual time jumps to the 60 s guard timer and the
//   waiting test times out: a wrong red the plain run does not have).
// no_claim: other real-time sources (they have their own tests); a plain test file is reused (the control shows the
//   cache works). (1b) and (2b) cannot fail first: a child process or worker start already keeps a test out of the
//   cache ("subprocess" / "worker thread"), and a call that never calls back already makes its file's timers fire with
//   work pending (recorded); they guard that this stays so. Needs node-sqlite3 5.1.7 (installed once into test/.tmp/pkgs-sqlite3, as test/native-work.test.js).
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
  const dir = fixture('p3-real', 'sibling-concurrent', {
    ...CONFIG,
    'tests/sibling.test.mjs': `import { test, expect } from 'vitest';
import { createRequire } from 'node:module';
const sqlite3 = createRequire(process.env.FIXTURE_SQLITE3)('sqlite3');
// several seconds of real work (the outer test checks it runs over 4.5 s in the plain run)
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
  assert.ok(plainWall > 4.5, `the query must run over 4.5 s (longer than the 3 s grace an earlier version had) for this test to mean anything: the plain run took ${plainWall} s`);
  const r = spawnSync(process.execPath, [BIN, 'vitest', 'run', '--det', '--det-workers=1'],
    { cwd: dir, encoding: 'utf8', env: env(), timeout: 240000 });
  const text = `${(r.stdout || '').slice(-3000)}\n${(r.stderr || '').slice(-2000)}`;
  assert.equal(r.status, 0, `the --det run passes (the query kept counting)\n${text}`);
});

test('(2b) a node-sqlite3 call that never calls back: the rest of its file runs at real pace and is not reused', T, () => {
  const dir = fixture('p3-real', 'never-calls-back', {
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
test('runs while that call is still counted (its timers fire at real pace)', async () => { await sleep(1000); }, 30000);
`,
  });
  const e = { FIXTURE_SQLITE3: sqlite3Pkg() };
  const r1 = crun('vitest', dir, ['run'], { env: e });
  assert.equal(r1.status, 0, show(r1));
  const r2 = crun('vitest', dir, ['run'], { env: e });
  assert.ok(reused(r2).includes('tests/control.test.mjs'), `the control file is reused\n${show(r2)}`);
  assert.ok(!reused(r2).includes('tests/expire.test.mjs'), `WRONG REUSE: the file ran its timers at real pace while the call counted\n${show(r2)}`);
});

// Unit level (a fake node-sqlite3 binding): a call that never calls back keeps counting while any test may still wait on
// it, whatever ends meanwhile (its own test, another test), also at the first test of a file (takeBaseline: a call the
// file's module scope or hooks started may be the one its first test waits on), and stops counting when the next test
// file opens (releaseFileWork, from src/controls.js openFile).
const NO_GRACE_MS = 3500; // longer than the 3 s grace an earlier version had
test('(3) a native call that never calls back counts until the next file opens, not only until its first test', { timeout: 60000 }, async () => {
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
    new b.Database().exec('x', () => {});
    for (const f of STATE.onTestEnd) f('unit-A'); // its test ends
    STATE.testId = 'unit-B';
    for (const f of STATE.onTestEnd) f('unit-B'); // and another one
    STATE.testId = null;
    await new Promise((r) => setTimeout(r, NO_GRACE_MS));
    assert.ok(sched.isPending(), `the call still counts ${NO_GRACE_MS} ms after two test ends (no real-time grace)`);
    sched.takeBaseline(); // a file's first test (src/runners/common.js begin): its hooks' calls are not released
    assert.ok(sched.isPending(), 'the call still counts after takeBaseline (the first test may wait on it)');
    sched.releaseFileWork(); // the next test file opens
    assert.ok(!sched.isPending(), 'the call stops counting when the next file opens');
  } finally {
    STATE.testId = saved;
  }
});

// /review round 4 (8b59fa8f..aa9f2342): the once-per-reason cache flag was one set for every test, so a concurrent
// test lost its flag when another test had flagged the same reason first.
test('(3b) the once-per-reason flag of a timer chosen by real time is per test, also for concurrent tests', { timeout: 60000 }, () => {
  const sched = require('../src/sched');
  const concur = require('../src/concur');
  const { STATE } = require('../src/state');
  const saved = STATE.onRealClock;
  const got = [];
  let who = null;
  const A = concur.create('unit-cA', () => sched.startTest());
  const B = concur.create('unit-cB', () => sched.startTest());
  try {
    STATE.onRealClock = (why) => { got.push(`${who}:${why}`); };
    concur.within(A, () => {}); // both tests started
    concur.within(B, () => {});
    concur.within(A, () => { who = 'A'; sched.timerChosen('s', 0, 'R'); });
    concur.within(B, () => { who = 'B'; sched.timerChosen('s', 0, 'R'); });
    concur.within(A, () => { who = 'A'; sched.timerChosen('s', 0, 'R'); }); // once per test and reason
    assert.deepEqual(got, ['A:R', 'B:R']);
  } finally {
    STATE.onRealClock = saved;
    concur.finish(A);
    concur.finish(B);
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
  const why = JSON.stringify((r1.summary && r1.summary.not_cached_detail) || {});
  assert.match(why, /fired at real pace while a runner poll/, `run 1 names the runner poll as the reason\n${show(r1)}`);
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
}, 120000);
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
}, 120000);
`,
  });
  plainAndDet(dir, 5, '(6)');
});
