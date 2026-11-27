'use strict';
// Real-time decisions of the P3 timer rule and native work must be recorded (founder decision on the coordinator's
// /review of claude/p3-timers-merge @ 105cdcad, 2026-11-27, findings 1 and 2).
//
// protects: (1) a timer fired at real pace because a runner poll (P1, safePending) or a child-starting test (P2,
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
const { BIN, TMP } = require('./helpers');
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

const PKGS = path.join(TMP, 'pkgs-sqlite3');
function sqlite3() {
  if (!fs.existsSync(path.join(PKGS, 'node_modules', 'sqlite3', 'package.json'))) {
    fs.mkdirSync(PKGS, { recursive: true });
    fs.writeFileSync(path.join(PKGS, 'package.json'), JSON.stringify({ name: 'pkgs-sqlite3', private: true }));
    const r = spawnSync('npm', ['install', '--no-audit', '--no-fund', 'sqlite3@5.1.7'], { cwd: PKGS, encoding: 'utf8', timeout: 600000 });
    assert.equal(r.status, 0, `node-sqlite3 5.1.7 could not be installed\n${r.stdout}\n${r.stderr}`);
  }
  return path.join(PKGS, 'package.json');
}

function env() {
  const e = { ...process.env, FIXTURE_SQLITE3: sqlite3() };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_EPOCH', 'DETJS_CACHE_DIR']) delete e[k];
  return e;
}

test('(2) a still-running query keeps counting when a concurrent sibling ends', T, () => {
  const dir = fixture('p3-real', 'sibling-grace', {
    ...CONFIG,
    'tests/sibling.test.mjs': `import { test, expect } from 'vitest';
import { createRequire } from 'node:module';
const sqlite3 = createRequire(process.env.FIXTURE_SQLITE3)('sqlite3');
// about 4-5 s of real work: longer than the 3 s grace
const SLOW = 'WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x<30000000) SELECT sum(x) s FROM c';
test.concurrent('a slow query with a 60 s guard timer pending (as tarn) is not timed out', async () => {
  const db = new sqlite3.Database(':memory:');
  const guard = setTimeout(() => {}, 60000);
  const rows = await new Promise((res, rej) => db.all(SLOW, (e, r) => (e ? rej(e) : res(r))));
  clearTimeout(guard);
  expect(rows[0].s).toBe(450000015000000);
  await new Promise((r) => db.close(r));
}, 30000);
test.concurrent('a sibling that ends at once', () => { expect(1).toBe(1); });
`,
  });
  const r = spawnSync(process.execPath, [BIN, 'vitest', 'run', '--det', '--det-workers=1'],
    { cwd: dir, encoding: 'utf8', env: env(), timeout: 240000 });
  const text = `${(r.stdout || '').slice(-3000)}\n${(r.stderr || '').slice(-2000)}`;
  assert.equal(r.status, 0, `the --det run passes (the query kept counting)\n${text}`);
});
