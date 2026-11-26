'use strict';
// P3 (spec "classify and remove the outcome flips under --det alone", step C): detjs puts the project's
// node_modules/.bin directories on PATH, as npx and npm scripts do for the runner it replaces. Found on ironcurtain
// (harness/p3_flips, 10 skipped-in-det cases: `spawn mcp-server-filesystem ENOENT` in beforeAll, cause wrapper).
//
// protects: a test that starts a project bin by its bare name finds it under `detjs vitest run` (with and without
//   --det), when detjs is started directly rather than through npx or an npm script.
// fails_when: detjs starts Vitest with the caller's PATH only, so the bin is not found (ENOENT) and the test fails.
// no_claim: jest and mocha entry points (same shape, not measured on a customer repo in P3); PATH order beyond
//   "nearest node_modules/.bin first, the caller's PATH after"; Windows PATH spelling.
// Run: cd node && node --test --test-concurrency=1 test/p3-bin-on-path.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

function setup() {
  const dir = path.join(TMP, 'p3', 'bin-on-path');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.cpSync(path.join(__dirname, 'fixtures', 'bin-on-path'), dir, { recursive: true });
  const bin = path.join(dir, 'node_modules', '.bin');
  fs.mkdirSync(bin, { recursive: true });
  fs.writeFileSync(path.join(bin, 'detjs-fixture-tool'), '#!/bin/sh\necho "tool ran"\n', { mode: 0o755 });
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_EPOCH', 'DETJS_CACHE_DIR']) delete env[k];
  // the caller's PATH without any node_modules/.bin (as from a shell, not from npx or an npm script)
  env.PATH = (env.PATH || '').split(path.delimiter).filter((p) => !p.includes(`node_modules${path.sep}.bin`)).join(path.delimiter);
  return { dir, env };
}

for (const det of [true, false]) {
  test(`detjs vitest run${det ? ' --det' : ''} finds a project bin by its bare name`, { timeout: 240000 }, () => {
    const { dir, env } = setup();
    const args = [BIN, 'vitest', 'run', ...(det ? ['--det', '--det-workers=1'] : [])];
    const r = spawnSync(process.execPath, args, { cwd: dir, encoding: 'utf8', env, timeout: 200000 });
    assert.equal(r.status, 0, `the run passes\n${(r.stdout || '').slice(-3000)}\n${(r.stderr || '').slice(-2000)}`);
  });
}
