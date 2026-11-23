'use strict';
// AC5 of the spec "Engine P0: no false green" (B5): in a plain `--det` run (cache off), the tests a failing beforeAll
// keeps from ever reaching the runner's per-test hook are in the trace, with outcome `skipped` (Jest: see below). On bfaf70b4 they were
// written only by the cache capture (src/vitest/shell.js writeCapture, src/jest/runner.js), so with the cache off
// the trace had no record of them (MEASURED on ironcurtain: 120 tests missing from the trace).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP, readTrace } = require('./helpers');

const T = { timeout: 600000 };
const BODY = {
  vitest: "import { test, expect, describe, beforeAll } from 'vitest';",
  jest: '',
};
const SUITE = `
describe('suite', () => {
  beforeAll(() => { throw new Error('setup fails'); });
  test('first', () => { expect(1).toBe(1); });
  test('second', () => { expect(2).toBe(2); });
});
`;

function cleanEnv() {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_SEED', 'DETJS_CACHE_DIR', 'DETJS_HAZARD_RERUN', 'JEST_WORKER_ID', 'VITEST_POOL_ID', 'VITEST_WORKER_ID']) delete env[k];
  return env;
}

for (const runner of ['vitest', 'jest']) {
  test(`${runner}: a failing beforeAll leaves both tests in the trace as skipped (cache off)`, T, () => {
    const dir = path.join(TMP, 'trace-skipped', runner);
    fs.rmSync(dir, { recursive: true, force: true });
    fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: `trace-skipped-${runner}`, private: true }));
    const file = runner === 'vitest' ? 'tests/hook.test.mjs' : 'tests/hook.test.js';
    if (runner === 'vitest') fs.writeFileSync(path.join(dir, 'vitest.config.mjs'), "export default { test: { include: ['tests/**/*.test.mjs'] } };\n");
    else fs.writeFileSync(path.join(dir, 'jest.config.js'), "module.exports = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node' };\n");
    fs.writeFileSync(path.join(dir, file), `${BODY[runner]}\n${SUITE}`);
    const args = runner === 'vitest' ? ['run'] : [`--cacheDirectory=${path.join(dir, '.jest-cache')}`];
    const r = spawnSync(process.execPath, [BIN, runner, ...args, '--det'], { cwd: dir, encoding: 'utf8', env: cleanEnv(), timeout: 300000 });
    const show = `status=${r.status}\nstdout=${(r.stdout || '').slice(-2000)}\nstderr=${(r.stderr || '').slice(-2000)}`;
    assert.equal(r.status, 1, show); // the suite failed: its hook threw
    assert.ok(!fs.existsSync(path.join(dir, '.detjs', 'cache')), 'the cache must be off');
    const trace = readTrace(path.join(dir, '.detjs', 'trace.jsonl'));
    const got = Object.fromEntries(trace.tests.map((t) => [t.nodeid, t.outcome]));
    // Vitest: the two tests never reach onBeforeRunTask; on bfaf70b4 the trace had no record of them (MEASURED: 0
    // tests), now both are `skipped`.
    //
    // Jest 30 (circus): a failing beforeAll does NOT keep the tests from the per-test hook -- Jest dispatches
    // test_start/test_done for each and fails it with the hook's error, so the trace has both, as `failed`, on
    // bfaf70b4 already (MEASURED). AC5 asks `skipped` for Jest too; writing `skipped` over a failure Jest reported
    // would turn a red test into a non-failure, which B5 (only tests that never reached the hook) does not cover.
    // Founder decision (2026-11-23, relayed by the coordinator): for Jest the criterion is "both tests are in the
    // trace with the outcome Jest reports (failed)"; Vitest stays `skipped`.
    const want = runner === 'vitest' ? 'skipped' : 'failed';
    assert.deepEqual(got, { [`${file}::suite::first`]: want, [`${file}::suite::second`]: want }, show);
  });
}
