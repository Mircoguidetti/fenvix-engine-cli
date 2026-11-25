'use strict';
// Shared fixture for the fault-injection tests of cache measurement B (B1 step 2: node/test/cache-fault-*.test.js).
// A seed run stores a passing file; exactly one input the file's test read changes; the cached run must report that
// file a miss and run it. Each channel has its own test file; this module only builds and runs the fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

const RUNNERS = (process.env.DETJS_TEST_RUNNERS || 'vitest,jest').split(',');
const EXT = { vitest: '.test.mjs', jest: '.test.js' };
const HEAD = {
  vitest: "import { test, expect } from 'vitest'; import fs from 'node:fs';",
  jest: "const fs = require('node:fs');",
};

function write(dir, files) {
  for (const [name, body] of Object.entries(files)) {
    const p = path.isAbsolute(name) ? name : path.join(dir, name);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, body);
  }
}

/** A project with tests/target (the file whose input changes) and tests/other (reads nothing of it). */
function project(runner, name, targetBody, extra = {}) {
  const dir = path.join(TMP, 'cache-fault', runner, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  write(dir, { 'package.json': JSON.stringify({ name: `fault-${name}`, private: true }) });
  if (runner === 'vitest') write(dir, { 'vitest.config.mjs': "export default { test: { include: ['tests/**/*.test.mjs'] } };\n" });
  else write(dir, { 'jest.config.js': "module.exports = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node' };\n" });
  write(dir, {
    [`tests/target${EXT[runner]}`]: `${HEAD[runner]}\n${targetBody(runner)}\n`,
    [`tests/other${EXT[runner]}`]: `${HEAD[runner]}\ntest('other', () => { expect(1 + 1).toBe(2); });\n`,
    ...extra,
  });
  return dir;
}

function run(runner, dir, { args = [], env = {} } = {}) {
  const childEnv = { ...process.env, ...env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS']) delete childEnv[k];
  const sum = path.join(dir, '.detjs', 'cache-summary.json');
  fs.rmSync(sum, { force: true });
  const jestCache = runner === 'jest' ? [`--cacheDirectory=${path.join(dir, '.jest-cache')}`] : [];
  const r = spawnSync(process.execPath, [BIN, runner, ...(runner === 'vitest' ? ['run'] : []), '--det', '--det-workers=1',
    `--det-cache=${path.join(dir, '.c')}`, ...jestCache, ...args], { cwd: dir, encoding: 'utf8', env: childEnv, timeout: 240000 });
  let summary = null;
  try { summary = JSON.parse(fs.readFileSync(sum, 'utf8')); } catch { /* none */ }
  return { status: r.status, summary, out: `status=${r.status}\n${(r.stdout || '').slice(-3000)}\n${(r.stderr || '').slice(-3000)}` };
}

function reused(r) {
  return new Set(((r.summary && r.summary.reused_files_list) || []).map((f) => f.split('@@')[0]));
}

/**
 * seed (stores both files), check (unchanged: both reused), change(), cached run: target must be a miss and run
 * (expectMiss) or a hit (negative). Options: seedOpts / cachedOpts for the runs' args and env; otherReused: false when
 * the change is global (a configuration file makes every file a miss).
 */
function cycle(runner, dir, change, { expectMiss = true, otherReused = true, seedOpts = {}, cachedOpts = null } = {}) {
  const target = `tests/target${EXT[runner]}`;
  const r1 = run(runner, dir, seedOpts);
  assert.equal(r1.status, 0, `seed\n${r1.out}`);
  assert.ok(r1.summary && r1.summary.recorded >= 2, `seed records both files\n${r1.out}`);
  const r2 = run(runner, dir, seedOpts);
  assert.ok(reused(r2).has(target), `unchanged: target reused\n${r2.out}`);
  change();
  const r3 = run(runner, dir, cachedOpts || seedOpts);
  assert.equal(r3.status, 0, `cached run\n${r3.out}`);
  if (expectMiss) {
    assert.ok(!reused(r3).has(target), `the changed input must make ${target} a miss; the run reported a hit\n${r3.out}`);
    assert.ok(Object.keys(r3.summary.misses).some((m) => m.startsWith(target)), `a miss recorded for ${target}\n${r3.out}`);
    if (otherReused) assert.ok(reused(r3).has(`tests/other${EXT[runner]}`), `the other file, whose inputs did not change, is reused\n${r3.out}`);
  } else {
    assert.ok(reused(r3).has(target), `a file no test read changed: ${target} must be reused\n${r3.out}`);
  }
  return r3;
}

module.exports = { RUNNERS, EXT, project, run, cycle, write, TMP };
