'use strict';
// Native addon work as pending work (founder decision D2 = A, 2026-11-27; alakajam: 106 "Test timed out in 5000ms",
// 7 SQLITE_BUSY): node-sqlite3 runs its queries on the libuv thread pool and leaves no active resource, so the
// virtual driver saw nothing pending and jumped to a long guard timer past the runner's deadline. Its native calls
// with a callback now count as pending until the callback runs (src/sched.js, as for crypto and zlib).
// Fixture: test/fixtures/native-work.
//
// protects: a test waiting on a node-sqlite3 query, with a long timer of its own pending, is not timed out by a
//   virtual jump (the plain run passes); a failing query (error callback) also ends its pending work.
// fails_when: node-sqlite3's Database / Statement callbacks are not counted as pending; or a count is not released:
//   when the callback runs, for each() with only a row callback and no rows, for a statement that failed in its
//   constructor (closed database), for each() on a finalized statement, or a few real seconds after a test ended for
//   a call that never calls back, also one a hook started (a later virtual sleep then runs at real pace: 100 s of
//   virtual sleep must take under 20 s; the hook file 40 s under 15 s); or a query still running when its test ends
//   stops counting at once, also across a skipped test, while the next test waits on it (alakajam tournament.service).
// F4 (founder, 2026-11-27): an idle pooled connection, and a call that never calls back, each fail at the runner
//   deadline ("Test timed out in 5000ms") and the run ends (tests/deadline.test.mjs); fails_when the pending work
//   keeps the scheduler waiting past the deadline (the run hangs: killed after 240 s) or a later sleep stays slow.
// no_claim: native calls without a callback (stmt.finalize()), the Database constructor's open, a node-sqlite3 that
//   was loaded before the engine's hooks, and other addons (listed in harness/p3_flips/NATIVE.md) are not covered. Needs node-sqlite3 5.1.7 from the npm registry
//   (installed once into test/.tmp/pkgs-sqlite3); if it cannot be installed the test fails, it does not skip.
// Run: cd node && node --test --test-concurrency=1 test/native-work.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

const PKGS = path.join(TMP, 'pkgs-sqlite3');
function sqlite3() {
  const main = path.join(PKGS, 'node_modules', 'sqlite3', 'package.json');
  if (!fs.existsSync(main)) {
    fs.mkdirSync(PKGS, { recursive: true });
    fs.writeFileSync(path.join(PKGS, 'package.json'), JSON.stringify({ name: 'pkgs-sqlite3', private: true }));
    const r = spawnSync('npm', ['install', '--no-audit', '--no-fund', 'sqlite3@5.1.7'], { cwd: PKGS, encoding: 'utf8', timeout: 600000 });
    assert.equal(r.status, 0, `node-sqlite3 5.1.7 could not be installed\n${r.stdout}\n${r.stderr}`);
  }
  return path.join(PKGS, 'package.json');
}

test('a node-sqlite3 query in flight is pending work: no virtual jump to the runner deadline', { timeout: 900000 }, () => {
  const src = path.join(__dirname, 'fixtures', 'native-work');
  const dir = path.join(TMP, 'native-work');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.cpSync(src, dir, { recursive: true });
  const env = { ...process.env, FIXTURE_SQLITE3: sqlite3() };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_EPOCH', 'DETJS_CACHE_DIR']) delete env[k];
  const plain = spawnSync(process.execPath, [path.join(__dirname, '..', 'node_modules', 'vitest', 'vitest.mjs'), 'run', '-t', 'in flight|statement methods'], { cwd: dir, encoding: 'utf8', env });
  assert.equal(plain.status, 0, `the plain run passes\n${plain.stdout}\n${plain.stderr}`);
  const t0 = Date.now();
  const r = spawnSync(process.execPath, [BIN, 'vitest', 'run', 'tests/sqlite3.test.mjs', '--det', '--det-workers=1'], { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  const wall = (Date.now() - t0) / 1000;
  const text = `${(r.stdout || '').slice(-3000)}\n${(r.stderr || '').slice(-2000)}`;
  assert.equal(r.status, 0, `the --det run passes too\n${text}`);
  assert.ok(wall < 20, `100 s of virtual sleep took ${wall} s of real time (pending work not released)\n${text}`);
});

test('F4: an idle pooled connection and a never-settling call end at the runner deadline, never hang', { timeout: 900000 }, () => {
  const src = path.join(__dirname, 'fixtures', 'native-work');
  const dir = path.join(TMP, 'native-work-deadline');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.cpSync(src, dir, { recursive: true });
  const env = { ...process.env, FIXTURE_SQLITE3: sqlite3() };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_EPOCH', 'DETJS_CACHE_DIR']) delete env[k];
  const out = path.join(dir, 'outcomes.json');
  const t0 = Date.now();
  const r = spawnSync(process.execPath, [BIN, 'vitest', 'run', 'tests/deadline.test.mjs', '--det', '--det-workers=1', `--det-outcomes=${out}`], { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  const wall = (Date.now() - t0) / 1000;
  const text = `${(r.stdout || '').slice(-3000)}\n${(r.stderr || '').slice(-2000)}`;
  assert.equal(r.signal, null, `the run hung and was killed after 240 s\n${text}`);
  assert.notEqual(r.status, 0, `the two waiting tests must fail\n${text}`);
  const o = JSON.parse(fs.readFileSync(out, 'utf8'));
  const failed = Object.entries(o.outcomes).filter(([, v]) => v === 'failed').map(([k]) => k.split('::').pop()).sort();
  assert.deepEqual(failed, ['a node-sqlite3 call that never calls back: timed out at the deadline',
    'an idle pooled connection while the test waits forever: timed out at the deadline'], text);
  assert.equal((text.match(/Test timed out in 5000ms/g) || []).length >= 2, true, `both fail with the runner's timeout\n${text}`);
  assert.ok(wall < 25, `the run took ${wall} s: a deadline waited past its time, or the 20 s sleep ran at real pace\n${text}`);
});

test('a call a hook started that never calls back stops counting soon after (hooks.test.mjs)', { timeout: 900000 }, () => {
  const src = path.join(__dirname, 'fixtures', 'native-work');
  const dir = path.join(TMP, 'native-work-hooks');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.cpSync(src, dir, { recursive: true });
  const env = { ...process.env, FIXTURE_SQLITE3: sqlite3() };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_EPOCH', 'DETJS_CACHE_DIR']) delete env[k];
  const t0 = Date.now();
  const r = spawnSync(process.execPath, [BIN, 'vitest', 'run', 'tests/hooks.test.mjs', '--det', '--det-workers=1'], { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  const wall = (Date.now() - t0) / 1000;
  const text = `${(r.stdout || '').slice(-3000)}\n${(r.stderr || '').slice(-2000)}`;
  assert.equal(r.status, 0, `the --det run passes\n${text}`);
  assert.ok(wall < 15, `40 s of virtual sleep took ${wall} s of real time (the hook's call kept counting)\n${text}`);
});
