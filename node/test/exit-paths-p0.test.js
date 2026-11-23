'use strict';
// AC6 of the spec "Engine P0: no false green" (B1, B7): a suite with one failing test exits 1 through each of the
// three exit paths of bin/detjs.js, prints exactly one `detjs: status:` line, and its trace header carries the
// same counts (`meta.status`, failed=1):
//   * normal path: `--det-workers=1` (not wrapped) with TZ/locale already pinned in the environment (no restart);
//   * re-exec path: the same with TZ/LC_ALL/LANG/DETJS_PINNED cleared, so bin/detjs.js restarts itself to pin them;
//   * wrapper path, with a hazard: two lanes forced with `--det-plan` (as test/parallel-p041.test.js does) over two
//     files that both write one file; the wrapper re-runs both in one lane and writes the merged trace itself;
//   * wrapper path, no hazard: the same lanes over files that share nothing; the pass-1 child's trace is final.
// The exit codes already held on bfaf70b4 (they guard the refactor); the status line and field are new.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP, readTrace } = require('./helpers');

const T = { timeout: 600000 };

function cleanEnv(extra) {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_SEED', 'DETJS_CACHE_DIR',
    'DETJS_PINNED', 'DETJS_HAZARD_RERUN', 'DETJS_HAZARD_PASS', 'DETJS_EARLY', 'TZ', 'LC_ALL', 'LANG', 'LANGUAGE',
    'JEST_WORKER_ID', 'VITEST_POOL_ID', 'VITEST_WORKER_ID']) delete env[k];
  return { ...env, ...extra };
}

function project(name, files) {
  const dir = path.join(TMP, 'exit-paths', name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: `exit-paths-${name}`, private: true }));
  fs.writeFileSync(path.join(dir, 'vitest.config.mjs'), "export default { test: { include: ['tests/**/*.test.mjs'] } };\n");
  const head = "import { test, expect } from 'vitest'; import fs from 'node:fs'; import path from 'node:path';";
  for (const [f, body] of Object.entries(files)) fs.writeFileSync(path.join(dir, 'tests', f), `${head}\n${body}\n`);
  fs.writeFileSync(path.join(dir, 'plan.json'), JSON.stringify({ lanes: Object.keys(files).map((f) => [`tests/${f}`]) }));
  return dir;
}

function run(dir, args, env) {
  fs.rmSync(path.join(dir, '.detjs'), { recursive: true, force: true });
  const r = spawnSync(process.execPath, [BIN, 'vitest', 'run', '--det', ...args], { cwd: dir, encoding: 'utf8', env: cleanEnv(env), timeout: 300000 });
  let trace = null;
  try { trace = readTrace(path.join(dir, '.detjs', 'trace.jsonl')); } catch { /* none */ }
  return { ...r, trace, show: `status=${r.status} signal=${r.signal}\nstdout=${(r.stdout || '').slice(-2500)}\nstderr=${(r.stderr || '').slice(-2500)}` };
}

const PINNED = { TZ: 'UTC', LC_ALL: 'C.UTF-8', LANG: 'C.UTF-8' };
const ONE_FAILS = {
  'a.test.mjs': "test('fails', () => { expect(1).toBe(2); });",
  'b.test.mjs': "test('passes', () => { expect(1).toBe(1); });",
};

function assertOneFailed(r, { passed }) {
  assert.equal(r.status, 1, r.show);
  const lines = `${r.stdout}\n${r.stderr}`.split('\n').filter((l) => l.startsWith('detjs: status:'));
  assert.equal(lines.length, 1, `exactly one status line: ${JSON.stringify(lines)}\n${r.show}`);
  assert.equal(lines[0], `detjs: status: failed=1 not_proven=0 passed=${passed} skipped=0`, r.show);
  assert.ok(r.stderr.split('\n').includes(lines[0]), `the status line is on stderr\n${r.show}`);
  assert.ok(r.trace, r.show);
  assert.deepEqual(r.trace.header.meta.status, { failed: 1, not_proven: 0, passed, skipped: 0 }, r.show);
}

test('normal path: one failing test exits 1, one status line, status in the trace header', T, () => {
  const dir = project('normal', ONE_FAILS);
  const r = run(dir, ['--det-workers=1'], PINNED);
  assert.doesNotMatch(r.stderr, /run again in one lane/, r.show);
  assertOneFailed(r, { passed: 1 });
});

test('re-exec path: the same through the TZ/locale restart', T, () => {
  const dir = project('reexec', {
    ...ONE_FAILS,
    // marker of the restart: the pinned TZ reaches the test although the environment had none
    'c.test.mjs': "test('sees the pinned TZ', () => { fs.writeFileSync(path.join(process.cwd(), 'tz.txt'), String(process.env.TZ)); });",
  });
  const r = run(dir, ['--det-workers=1'], {});
  assert.equal(fs.readFileSync(path.join(dir, 'tz.txt'), 'utf8'), 'UTC', r.show);
  assertOneFailed(r, { passed: 2 });
});

test('wrapper path with a hazard: the wrapper merges, prints the one status line and exits 1', T, () => {
  const dir = project('wrapper-hazard', {
    'a.test.mjs': "test('fails', () => { fs.writeFileSync(path.join(process.cwd(), 'shared.txt'), 'a'); expect(1).toBe(2); });",
    'b.test.mjs': "test('passes', () => { fs.writeFileSync(path.join(process.cwd(), 'shared.txt'), 'b'); expect(1).toBe(1); });",
  });
  const r = run(dir, ['--det-plan=plan.json'], PINNED);
  assert.match(r.stderr, /run again in one lane/, r.show);
  assert.ok(r.trace.header.meta.hazard_rerun && r.trace.header.meta.hazard_rerun.complete, r.show);
  assertOneFailed(r, { passed: 1 });
});

test('wrapper path with no hazard: the pass-1 child writes the final trace and prints the one status line', T, () => {
  const dir = project('wrapper-clean', ONE_FAILS);
  const r = run(dir, ['--det-plan=plan.json'], PINNED);
  assert.doesNotMatch(r.stderr, /run again in one lane/, r.show);
  assert.match(r.stdout, /parallel execution in 2 lanes/, r.show);
  assertOneFailed(r, { passed: 1 });
});

// /review (2026-11-23), CONFIRMED by a live probe on bfaf70b4 and on this branch before the fix: a hazard failure the
// one-lane re-run clears, plus a third file that fails to load (no test record), exited 0 although Vitest reported
// the file FAIL. Pass 1's red must stand when part of it is outside the re-run files.
test('wrapper path: a file that fails to load outside the hazard files keeps the run red', T, () => {
  const body = (n) => `
const LOG = path.join(process.cwd(), 'shared.log');
const lines = () => { try { return fs.readFileSync(LOG, 'utf8').trim().split('\\n'); } catch { return []; } };
test('${n} writes a contiguous block', () => {
  fs.appendFileSync(LOG, '${n}-start\\n');
  const sab = new Int32Array(new SharedArrayBuffer(4));
  for (let i = 0; i < 60; i++) {
    if (lines().some((l) => l.endsWith('-start') && !l.startsWith('${n}'))) break;
    Atomics.wait(sab, 0, 0, 50);
  }
  fs.appendFileSync(LOG, '${n}-end\\n');
  expect(lines().slice(-2)).toEqual(['${n}-start', '${n}-end']);
});`;
  const dir = project('wrapper-load-failure', {
    'x.test.mjs': body('X'),
    'y.test.mjs': body('Y'),
    'z.test.mjs': "throw new Error('this file fails to load');\ntest('never runs', () => {});",
  });
  fs.rmSync(path.join(dir, 'shared.log'), { force: true });
  const r = run(dir, ['--det-plan=plan.json'], PINNED);
  assert.match(r.stderr, /run again in one lane/, r.show);
  assert.ok(r.trace.header.meta.file_failures.files.includes('tests/z.test.mjs'), r.show);
  assert.equal(r.status, 1, r.show);
  assert.equal(`${r.stdout}\n${r.stderr}`.split('\n').filter((l) => l.startsWith('detjs: status:')).length, 1, r.show);
});

// /review pass 2 (2026-11-23): a describe-level beforeAll failure outside the hazard files leaves its tests with no
// record of their own (B5 writes them `skipped`) and no file error -- the side data's `error` states make it a file
// failure, so the run stays red.
test('wrapper path: a beforeAll failure outside the hazard files keeps the run red', T, () => {
  const body = (n) => `
const LOG = path.join(process.cwd(), 'shared.log');
const lines = () => { try { return fs.readFileSync(LOG, 'utf8').trim().split('\\n'); } catch { return []; } };
test('${n} writes a contiguous block', () => {
  fs.appendFileSync(LOG, '${n}-start\\n');
  const sab = new Int32Array(new SharedArrayBuffer(4));
  for (let i = 0; i < 60; i++) {
    if (lines().some((l) => l.endsWith('-start') && !l.startsWith('${n}'))) break;
    Atomics.wait(sab, 0, 0, 50);
  }
  fs.appendFileSync(LOG, '${n}-end\\n');
  expect(lines().slice(-2)).toEqual(['${n}-start', '${n}-end']);
});`;
  const dir = project('wrapper-hook-failure', {
    'x.test.mjs': body('X'),
    'y.test.mjs': body('Y'),
    'z.test.mjs': "import { describe, beforeAll } from 'vitest';\ndescribe('d', () => {\n  beforeAll(() => { throw new Error('setup fails'); });\n  test('one', () => {});\n  test('two', () => {});\n});",
    // a nested afterAll failure: the test itself passed, the error is on the suite (Vitest's main process marks the
    // file failed; the side data does not see it)
    'w.test.mjs': "import { describe, afterAll } from 'vitest';\ndescribe('outer', () => { describe('inner', () => {\n  afterAll(() => { throw new Error('teardown fails'); });\n  test('passes', () => {});\n}); });",
  });
  fs.rmSync(path.join(dir, 'shared.log'), { force: true });
  const r = run(dir, ['--det-plan=plan.json'], PINNED);
  assert.match(r.stderr, /run again in one lane/, r.show);
  assert.ok(r.trace.header.meta.file_failures.files.includes('tests/z.test.mjs'), r.show);
  assert.ok(r.trace.header.meta.file_failures.files.includes('tests/w.test.mjs'), r.show);
  assert.equal(r.status, 1, r.show);
});

test('--det-isolate: the parent prints the one status line and carries the counts', T, () => {
  const dir = project('isolate', ONE_FAILS);
  const r = run(dir, ['--det-isolate'], PINNED);
  assertOneFailed(r, { passed: 1 });
});

test('mocha: two failing tests exit 1, not 2 (2 is reserved for detjs usage and internal errors)', T, () => {
  const dir = path.join(TMP, 'exit-paths', 'mocha-two');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 't'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: 'exit-paths-mocha', private: true }));
  fs.writeFileSync(path.join(dir, 't', 'a.test.js'), "const assert = require('node:assert');\nit('a', () => assert.equal(1, 2));\nit('b', () => assert.equal(1, 2));\nit('c', () => {});\n");
  const r = spawnSync(process.execPath, [BIN, 'mocha', '--det', 't/a.test.js'], { cwd: dir, encoding: 'utf8', env: cleanEnv(PINNED), timeout: 300000 });
  const show = `status=${r.status}\nstderr=${(r.stderr || '').slice(-2000)}`;
  assert.equal(r.status, 1, show);
  assert.match(r.stderr, /^detjs: status: failed=2 not_proven=0 passed=1 skipped=0$/m, show);
});

test('jest --forceExit: the counts still decide the exit code and the line is printed once', T, () => {
  const dir = path.join(TMP, 'exit-paths', 'jest-force-exit');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: 'exit-paths-jest', private: true }));
  fs.writeFileSync(path.join(dir, 'jest.config.js'), "module.exports = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node' };\n");
  fs.writeFileSync(path.join(dir, 'tests', 'a.test.js'), "test('fails', () => { expect(1).toBe(2); });\ntest('passes', () => {});\n");
  const r = spawnSync(process.execPath, [BIN, 'jest', `--cacheDirectory=${path.join(dir, '.jc')}`, '--forceExit', '--det', '--det-workers=1'],
    { cwd: dir, encoding: 'utf8', env: cleanEnv(PINNED), timeout: 300000 });
  const show = `status=${r.status}\nstderr=${(r.stderr || '').slice(-2000)}`;
  assert.equal(r.status, 1, show);
  assert.equal(`${r.stdout}\n${r.stderr}`.split('\n').filter((l) => l.startsWith('detjs: status:')).length, 1, show);
});

// /review pass 3: Jest --det-isolate ignored a collection run that failed when other files had tests to collect
test('jest --det-isolate: a file that fails to load keeps the run red', T, () => {
  const dir = path.join(TMP, 'exit-paths', 'jest-isolate-load');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: 'exit-paths-jest-isolate', private: true }));
  fs.writeFileSync(path.join(dir, 'jest.config.js'), "module.exports = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node' };\n");
  fs.writeFileSync(path.join(dir, 'tests', 'a.test.js'), "test('passes', () => {});\n");
  fs.writeFileSync(path.join(dir, 'tests', 'b.test.js'), "throw new Error('this file fails to load');\n");
  const r = spawnSync(process.execPath, [BIN, 'jest', `--cacheDirectory=${path.join(dir, '.jc')}`, '--det', '--det-isolate'],
    { cwd: dir, encoding: 'utf8', env: cleanEnv(PINNED), timeout: 300000 });
  const show = `status=${r.status}\nstdout=${(r.stdout || '').slice(-1500)}\nstderr=${(r.stderr || '').slice(-2000)}`;
  assert.equal(r.status, 1, show);
  assert.match(r.stderr, /the collection run failed/, show);
});
