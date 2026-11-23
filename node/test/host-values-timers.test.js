'use strict';
// Spec "Engine: --det uses the machine's values by default" (2026-11-23), regression test (b): virtual timers
// while the test waits on something real. Fixture: test/fixtures/timers-waiting (two shapes of codex-multi-auth
// b9886168 flips, diagnosed in harness/det_host_values/REPORT.md).
//
// protects: a test that waits on something the virtual driver does not count (the runner's own polling timers, a
//   file written by a detached process) is not failed by a virtual timeout while the plain run passes.
// fails_when: the driver fast-forwards virtual time to the runner deadline while the test still waits.
// no_claim: Vitest 5.0.5's TaskDeadline start-time read (the cascade that fails every later test of a file on
//   codex-multi-auth) is not covered: the engine's own Vitest (5.1.0) does not have that frame name; it is checked
//   on the real file (REPORT.md, `pins.py variants`).
// Run: cd node && node --test --test-concurrency=1 test/host-values-timers.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

test('(b) a test waiting on real work is not timed out by the virtual clock', { timeout: 300000 }, () => {
  const src = path.join(__dirname, 'fixtures', 'timers-waiting');
  const dir = path.join(TMP, 'host-values', 'timers-waiting');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.cpSync(src, dir, { recursive: true });
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_EPOCH', 'DETJS_CACHE_DIR']) delete env[k];
  const plain = spawnSync(process.execPath, [path.join(__dirname, '..', 'node_modules', 'vitest', 'vitest.mjs'), 'run'], { cwd: dir, encoding: 'utf8', env });
  assert.equal(plain.status, 0, `the plain run passes\n${plain.stdout}\n${plain.stderr}`);
  const r = spawnSync(process.execPath, [BIN, 'vitest', 'run', '--det', '--det-workers=1'], { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  assert.equal(r.status, 0, `the --det run passes too\n${(r.stdout || '').slice(-3000)}\n${(r.stderr || '').slice(-2000)}`);
});
