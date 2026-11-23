'use strict';
// AC1 of the spec "Engine P0: no false green" (2026-11-22): regression tests of today's exit behaviour of detjs.
// (a)-(c) pass on bfaf70b4 and must keep passing after the exit rule moved to src/exit-status.js; (d) is the docs fix
// of B8 (fails on bfaf70b4: its help said "--det-workers ... default: serial").
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

const T = { timeout: 600000 };
const BASE = path.join(TMP, 'exit-regression');

function cleanEnv(extra = {}) {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_SEED', 'DETJS_CACHE_DIR',
    'DETJS_PINNED', 'DETJS_HAZARD_RERUN', 'DETJS_EARLY', 'TZ', 'LC_ALL', 'LANG', 'LANGUAGE', 'JEST_WORKER_ID', 'VITEST_POOL_ID', 'VITEST_WORKER_ID']) delete env[k];
  return { ...env, ...extra };
}

function dir(name, files) {
  const d = path.join(BASE, name);
  fs.rmSync(d, { recursive: true, force: true });
  fs.mkdirSync(d, { recursive: true });
  for (const [f, body] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(d, f)), { recursive: true });
    fs.writeFileSync(path.join(d, f), body);
  }
  return d;
}

function run(cwd, args, env = {}) {
  const r = spawnSync(process.execPath, [BIN, ...args], { cwd, encoding: 'utf8', env: cleanEnv(env), timeout: 300000 });
  return { ...r, show: `status=${r.status} signal=${r.signal}\nstdout=${(r.stdout || '').slice(-2000)}\nstderr=${(r.stderr || '').slice(-2000)}` };
}

test('AC1(a) detjs jest --det with no test files exits 1, and 0 with --passWithNoTests', T, () => {
  const d = dir('jest-empty', {
    'package.json': JSON.stringify({ name: 'exit-jest-empty', private: true }),
    'jest.config.js': `module.exports = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node' };\n`,
  });
  const cache = `--cacheDirectory=${path.join(d, '.jest-cache')}`;
  const none = run(d, ['jest', cache, '--det']);
  assert.equal(none.signal, null, none.show);
  assert.equal(none.status, 1, none.show);
  const pass = run(d, ['jest', cache, '--passWithNoTests', '--det']);
  assert.equal(pass.status, 0, pass.show);
});

test('AC1(b) detjs verify with one trace is a usage error: exit 2', T, () => {
  const d = dir('verify-one', {
    'one.jsonl': `${JSON.stringify({ type: 'header', format: 'detpy-trace', version: 1, encoding: 2, meta: {}, order: [] })}\n`,
  });
  const r = run(d, ['verify', 'one.jsonl']);
  assert.equal(r.status, 2, r.show);
  assert.match(r.stderr, /needs at least two traces/, r.show);
});

test('AC1(c) through the re-exec path, a test that SIGTERMs its process ends the parent detjs with SIGTERM', T, () => {
  // `--det-workers=1`: not wrapped (src/parallel-rerun.js shouldWrap), so the TZ/locale pinning re-exec of
  // bin/detjs.js is the outer path. TZ, LC_ALL, LANG and DETJS_PINNED are cleared in the environment (cleanEnv), so
  // the default pinning (TZ=UTC) needs the restart. `--pool=threads`: the test runs in a worker thread of the
  // re-executed detjs child, so its `process.kill(process.pid)` signals that child.
  //
  // The observable marker of the re-exec: the test writes its process.pid and process.ppid. Without a re-exec the
  // test's process is the detjs the test runner spawned (pid === r.pid); with it, the test's process is a child of
  // that detjs (ppid === r.pid, pid !== r.pid).
  //
  // Vitest 5's logger traps SIGTERM in its main process (Logger.addCleanupListeners: `process.once('SIGTERM')`, then
  // `process.exit()` with 143), so on bfaf70b4 the plain fixture ends the child with status 143, not with the signal
  // (MEASURED: status=143 signal=null). The fixture's globalSetup, which runs in that main process after the logger,
  // removes those listeners so that the signal really kills the detjs child -- the case B1 keeps: a signal that
  // killed the child is re-raised on the parent. (REPORT.md, AC1.)
  const d = dir('sigterm', {
    'package.json': JSON.stringify({ name: 'exit-sigterm', private: true, type: 'module' }),
    'vitest.config.mjs': "export default { test: { include: ['tests/**/*.test.mjs'], pool: 'threads', globalSetup: ['./untrap.mjs'] } };\n",
    'untrap.mjs': "export default function setup() { process.removeAllListeners('SIGTERM'); }\n",
    'tests/kill.test.mjs': [
      "import { test } from 'vitest'; import fs from 'node:fs'; import path from 'node:path';",
      "test('kills its own process', () => {",
      "  fs.writeFileSync(path.join(process.cwd(), 'pids.json'), JSON.stringify({ pid: process.pid, ppid: process.ppid }));",
      "  process.kill(process.pid, 'SIGTERM');",
      "});",
    ].join('\n'),
  });
  const r = run(d, ['vitest', 'run', '--pool=threads', '--det', '--det-workers=1']);
  const pids = JSON.parse(fs.readFileSync(path.join(d, 'pids.json'), 'utf8'));
  assert.notEqual(pids.pid, r.pid, `the test ran in the outer detjs: no re-exec happened\n${r.show}`);
  assert.equal(pids.ppid, r.pid, `the test's process is not a child of the outer detjs\n${r.show}`);
  assert.equal(r.signal, 'SIGTERM', r.show);
  assert.equal(r.status, null, r.show);
});

test("AC1(d) detjs vitest --det-help states that the --det-workers default is the machine's CPUs", T, () => {
  const r = run(BASE, ['vitest', '--det-help']);
  assert.equal(r.status, 0, r.show);
  const line = r.stdout.split('\n').findIndex((l) => l.trimStart().startsWith('--det-workers'));
  assert.ok(line >= 0, r.show);
  const text = r.stdout.split('\n').slice(line, line + 3).join(' ');
  assert.match(text, /default: (?:this|the) machine's CPUs/, text);
  assert.doesNotMatch(text, /default: serial/, text);
});
