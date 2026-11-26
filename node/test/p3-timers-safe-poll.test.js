'use strict';
// P3 timers P1 (founder decision A on the S3 prototype, 2026-11-26): Vitest's safe timers that a test starts and that
// are not runner deadlines (vi.waitFor / expect.poll polling and timeouts) count as pending work of the virtual
// timer driver (src/clock.js ioPending, src/deadline.js installVitest). Fixture: test/fixtures/timers-safe-poll.
//
// protects: a test that polls with vi.waitFor or expect.poll while an unrelated long timer of its own is pending is
//   not failed by a virtual jump to that timer past the runner's 5000 ms deadline (the plain run passes).
// fails_when: the driver fast-forwards virtual time while a runner poll is pending; or the runner's own test timeout
//   or a hook timeout is counted as pending work (a virtual sleep then runs at real pace); or a safe timer a finished
//   test left behind keeps the next test at real pace; or a poll that resolved is still counted (its timers are not
//   untracked when they run or are cleared).
// no_claim: a test that polls with its own setTimeout loop for something real it holds no handle to (a file a
//   detached process writes, test (b)'s detached.test.mjs) is not covered: its timers are virtual, not safe timers
//   (P2). The wall bounds below are generous (80 s of virtual sleep must take under 15 s of real
//   time; one 20 s sleep run at real pace already exceeds it).
// Run: cd node && node --test --test-concurrency=1 test/p3-timers-safe-poll.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

function fixture() {
  const src = path.join(__dirname, 'fixtures', 'timers-safe-poll');
  const dir = path.join(TMP, 'p3', 'timers-safe-poll');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.cpSync(src, dir, { recursive: true });
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_EPOCH', 'DETJS_CACHE_DIR']) delete env[k];
  return { dir, env };
}

function det(file) {
  const { dir, env } = fixture();
  const out = path.join(dir, 'outcomes.json');
  const t0 = Date.now();
  const r = spawnSync(process.execPath, [BIN, 'vitest', 'run', file, '--det', '--det-workers=1', `--det-outcomes=${out}`],
    { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  const wall = (Date.now() - t0) / 1000;
  const text = `${(r.stdout || '').slice(-3000)}\n${(r.stderr || '').slice(-2000)}`;
  return { r, wall, text };
}

test('vi.waitFor and expect.poll with a long test timer pending pass under --det, as in the plain run', { timeout: 300000 }, () => {
  const { dir, env } = fixture();
  const plain = spawnSync(process.execPath, [path.join(__dirname, '..', 'node_modules', 'vitest', 'vitest.mjs'), 'run', 'tests/poll.test.mjs'],
    { cwd: dir, encoding: 'utf8', env });
  assert.equal(plain.status, 0, `the plain run passes\n${plain.stdout}\n${plain.stderr}`);
  const { r, text } = det('tests/poll.test.mjs');
  assert.equal(r.status, 0, `the --det run passes too\n${text}`);
});

test('runner deadlines (test and hook timeouts) are not pending work, and a resolved or left-behind poll is not either', { timeout: 300000 }, () => {
  const { r, wall, text } = det('tests/guards.test.mjs');
  assert.equal(r.status, 0, `the --det run passes\n${text}`);
  assert.ok(wall < 15, `80 s of virtual sleep took ${wall} s of real time (virtual time ran at real pace)\n${text}`);
});
