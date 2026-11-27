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
//   constructor (closed database), for each() on a finalized statement (a later virtual sleep then runs at real pace:
//   100 s of virtual sleep must take under 20 s); or a query still running when its test ends stops counting, also
//   across a skipped test, while the next test waits on it (alakajam tournament.service); or a call that never calls
//   back (in a test or a hook) makes a later test of its file fail instead of running at real pace (leak.test.mjs,
//   hooks.test.mjs: they must pass). Its release at the next file is test/p3-real-decisions.test.js (3).
// F4 (founder, 2026-11-27): an idle pooled connection, and a call that never calls back, each fail at the runner
//   deadline ("Test timed out in 5000ms") and the run ends (tests/deadline.test.mjs); fails_when the pending work
//   keeps the scheduler waiting past the deadline (the run hangs: killed after 240 s) or the run's wall time shows a
//   deadline that waited past its time.
// /review round 4 (uvu, one process for all files, test/fixtures/native-work-uvu): a query a hook started keeps
//   counting at the file's first test (fails_when takeBaseline at the first test releases it: virtual time jumps to
//   the test's 60 s guard timer and the guard wins); a call that never calls back stops counting when the next file
//   opens (fails_when the next file's 100 s of virtual sleep take 20 s or more of real time).
// no_claim: native calls without a callback (stmt.finalize()), the Database constructor's open, a node-sqlite3 that
//   was loaded before the engine's hooks, and other addons (listed in harness/p3_flips/NATIVE.md) are not covered.
//   Needs node-sqlite3 5.1.7 from the npm registry (installed once into test/.tmp/pkgs-sqlite3); if it cannot be
//   installed the test fails, it does not skip.
// Run: cd node && node --test --test-concurrency=1 test/native-work.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP, sqlite3Pkg } = require('./helpers');

const sqlite3 = sqlite3Pkg;

test('a node-sqlite3 query in flight is pending work: no virtual jump to the runner deadline', { timeout: 900000 }, () => {
  const src = path.join(__dirname, 'fixtures', 'native-work');
  const dir = path.join(TMP, 'native-work');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.cpSync(src, dir, { recursive: true });
  const env = { ...process.env, FIXTURE_SQLITE3: sqlite3() };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_EPOCH', 'DETJS_CACHE_DIR']) delete env[k];
  const plain = spawnSync(process.execPath, [path.join(__dirname, '..', 'node_modules', 'vitest', 'vitest.mjs'), 'run', '-t', 'in flight|statement methods'], { cwd: dir, encoding: 'utf8', env });
  assert.equal(plain.status, 0, `the plain run passes\n${plain.stdout}\n${plain.stderr}`);
  const leak = spawnSync(process.execPath, [BIN, 'vitest', 'run', 'tests/leak.test.mjs', '--det', '--det-workers=1'], { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  assert.equal(leak.status, 0, `a call that never calls back: the rest of its file passes\n${(leak.stdout || '').slice(-2000)}`);
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
  assert.ok(wall < 25, `the run took ${wall} s: a deadline waited past its time (each waiting test must end at its 5 s deadline)\n${text}`);
});

test('a call a hook started that never calls back: the tests of its file still pass (hooks.test.mjs)', { timeout: 900000 }, () => {
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
  assert.ok(wall < 60, `the hook file took ${wall} s (2 s of sleep at real pace expected)\n${text}`);
});

function uvuDir(name, files) {
  const { depsDir } = require('./runner-b-cases');
  const dir = path.join(TMP, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.cpSync(path.join(__dirname, 'fixtures', 'native-work-uvu'), dir, { recursive: true });
  fs.symlinkSync(path.join(depsDir(), 'node_modules'), path.join(dir, 'node_modules'));
  const env = { ...process.env, FIXTURE_SQLITE3: sqlite3() };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_EPOCH', 'DETJS_CACHE_DIR']) delete env[k];
  return { dir, env, files };
}

test('uvu: a query a hook started keeps counting at the file\'s first test', { timeout: 900000 }, () => {
  const { dir, env } = uvuDir('native-work-uvu-hook');
  const t0 = Date.now();
  const plain = spawnSync(process.execPath, [path.join(dir, 'node_modules', 'uvu', 'bin.js'), 'tests'], { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  const plainWall = (Date.now() - t0) / 1000;
  assert.equal(plain.status, 0, `the plain run passes\n${plain.stdout}\n${plain.stderr}`);
  assert.ok(plainWall > 1, `the query must run over 1 s for this test to mean anything (plain ${plainWall} s)`);
  const r = spawnSync(process.execPath, [BIN, 'uvu', '--det', 'tests'], { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  const text = `${(r.stdout || '').slice(-3000)}\n${(r.stderr || '').slice(-2000)}`;
  assert.equal(r.status, 0, `the --det run passes like the plain run (the query kept counting)\n${text}`);
});

test('uvu: a call that never calls back stops counting when the next file of the process opens', { timeout: 900000 }, () => {
  const { dir, env } = uvuDir('native-work-uvu-next');
  const t0 = Date.now();
  const r = spawnSync(process.execPath, [BIN, 'uvu', '--det', 'files'], { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  const wall = (Date.now() - t0) / 1000;
  const text = `${(r.stdout || '').slice(-3000)}\n${(r.stderr || '').slice(-2000)}`;
  assert.equal(r.status, 0, `both files pass\n${text}`);
  assert.match(text, /passed=2/, `both files' tests ran in this run\n${text}`);
  assert.ok(wall < 20, `the next file's 100 s of virtual sleep took ${wall} s of real time (the call was not released)\n${text}`);
});
