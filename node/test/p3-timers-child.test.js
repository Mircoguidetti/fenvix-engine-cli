'use strict';
// P3 timers P2 (founder decision D1 = A, 2026-11-27): a short timer of a test that started a child process runs at real pace (src/clock.js
// childPaced, src/children.js). Red test: test (b), test/host-values-timers.test.js (detached.test.mjs). Fixture
// for the guards: test/fixtures/timers-child.
//
// protects: virtual time stays fast where the P2 rule must not apply: a long timer of a test that started a child,
//   and every timer of the next test.
// fails_when: a long timer (> the pacing bound) of a child-starting test runs at real pace; or the pacing outlives
//   the test that started the child.
//   Guard (2) also catches a pacing set not reset at test end (the next test's short timers would be paced); guards
//   (3) and (4) check the asynchronous spawn and the Worker paths pace like spawnSync.
// no_claim: that a test's short timers are virtual after it started a child (they are paced on purpose); concurrent
//   tests (test.concurrent) are not covered. The wall bound is generous (30 s of virtual sleep must take under 8 s of
//   real time).
// Run: cd node && node --test --test-concurrency=1 test/p3-timers-child.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

test('after a child process, long timers and the next test stay virtual', { timeout: 300000 }, () => {
  const src = path.join(__dirname, 'fixtures', 'timers-child');
  const dir = path.join(TMP, 'p3', 'timers-child');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.cpSync(src, dir, { recursive: true });
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_EPOCH', 'DETJS_CACHE_DIR']) delete env[k];
  const t0 = Date.now();
  const r = spawnSync(process.execPath, [BIN, 'vitest', 'run', '--det', '--det-workers=1'], { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  const wall = (Date.now() - t0) / 1000;
  const text = `${(r.stdout || '').slice(-3000)}\n${(r.stderr || '').slice(-2000)}`;
  assert.equal(r.status, 0, `the --det run passes\n${text}`);
  assert.ok(wall < 8, `30 s of virtual sleep took ${wall} s of real time (virtual time ran at real pace)\n${text}`);
});
