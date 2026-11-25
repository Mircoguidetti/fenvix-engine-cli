'use strict';
// Cache measurement B, B1 step 1: what a verify mismatch reports, read from the summary JSON (never the printed lines).
//
// protects=  the B harness's classification of a mismatch: for each test the cache would reuse as passing while the
//            fresh run fails, the summary names the inputs the reused entry was recorded with, and a would-be-reused
//            result the fresh run never compared is listed, not silently counted as verified.
// fails_when= a mismatch lacks verify_mismatch_inputs (env, data, config, runtime, run), the exit code of the verify
//            run does not come from the fresh run (0 on a fresh failure), or verify_unchecked is missing or lists a
//            compared result.
// no_claim=  that mismatches are rare, or that the inputs listed are complete (the key holds what was observed).
// The mismatch is made with DETJS_CACHE_SKIP_DIRS (a documented non-input): the data file changes without the key.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

function run(dir, args) {
  const env = { ...process.env, DETJS_CACHE_SKIP_DIRS: path.join(dir, 'data') };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS']) delete env[k];
  const r = spawnSync(process.execPath, [BIN, 'vitest', 'run', '--det', '--det-workers=1', `--det-cache=${path.join(dir, '.c')}`, ...args],
    { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  const summary = JSON.parse(fs.readFileSync(path.join(dir, '.detjs', 'cache-summary.json'), 'utf8'));
  return { status: r.status, summary, out: `${r.stdout}\n${r.stderr}` };
}

test('verify mismatch: recorded inputs of the reused entry, exit code of the fresh run, unchecked list', { timeout: 600000 }, () => {
  const dir = path.join(TMP, 'cache-b1-summary');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.mkdirSync(path.join(dir, 'data'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), '{"name":"b1-summary","private":true}');
  fs.writeFileSync(path.join(dir, 'vitest.config.mjs'), "export default { test: { include: ['tests/**/*.test.mjs'] } };\n");
  fs.writeFileSync(path.join(dir, 'data', 'v.txt'), 'ok\n');
  fs.writeFileSync(path.join(dir, 'tests', 'a.test.mjs'), "import { test, expect } from 'vitest'; import fs from 'node:fs';\n"
    + "test('reads data', () => { expect(process.env.HOME !== undefined).toBe(true); expect(fs.readFileSync('data/v.txt', 'utf8').trim()).toBe('ok'); });\n");
  fs.writeFileSync(path.join(dir, 'tests', 'b.test.mjs'), "import { test, expect } from 'vitest';\ntest('b', () => { expect(1).toBe(1); });\n");
  const r1 = run(dir, []);
  assert.equal(r1.status, 0, r1.out);
  // unchanged: verify compares every would-be-reused result, nothing unchecked
  const r2 = run(dir, ['--det-cache-verify']);
  assert.equal(r2.status, 0, r2.out);
  assert.equal(r2.summary.verify_mismatches_tests, 0, r2.out);
  assert.deepEqual(r2.summary.verify_unchecked, [], r2.out);
  assert.ok(r2.summary.verified >= 4, r2.out);
  fs.writeFileSync(path.join(dir, 'data', 'v.txt'), 'changed\n');
  const r3 = run(dir, ['--det-cache-verify']);
  assert.equal(r3.status, 1, `the fresh run failed: the exit code is the runner's\n${r3.out}`);
  assert.equal(r3.summary.verify_mismatches_tests, 1, r3.out);
  const nid = 'tests/a.test.mjs::reads data';
  const inp = r3.summary.verify_mismatch_inputs[nid];
  assert.ok(inp, `inputs of ${nid}\n${JSON.stringify(r3.summary, null, 1)}`);
  assert.equal(inp.outcome, 'passed');
  for (const k of ['run', 'key', 'config', 'runtime', 'env', 'data']) assert.ok(k in inp, `${k} in ${JSON.stringify(inp)}`);
  assert.ok(inp.env.some(([name]) => name === 'HOME'), JSON.stringify(inp.env));
  assert.ok(r3.summary.runtime_parts, 'runtime parts');
  assert.deepEqual(r3.summary.verify_unchecked, [], r3.out);
});
