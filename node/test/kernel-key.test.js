'use strict';
// The kernel is part of the Node cache's runtime key on every platform (spec "false greens on release-1", founder
// decision 2026-11-25; the Node half of review R-056 W5). Before, on Linux it was keyed only when a test read
// os.release() itself: a test that read it through process.report was reused under another kernel.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

const T = { timeout: 300000 };
// the kernel can be faked here: setarch runs a program under --uname-2.6 (not only `setarch --version`: on another
// architecture or under a seccomp policy that blocks personality() the faked runs fail before Vitest starts, and the
// test would pass without testing anything -- /review testing)
const canFake = process.arch === 'x64'
  && spawnSync('setarch', ['x86_64', '--uname-2.6', process.execPath, '-p', 'require("os").release()'], { encoding: 'utf8' }).stdout.trim().startsWith('2.6');

test('protects=a cached Vitest test that reads the kernel release through process.report is rerun when the kernel differs (setarch --uname-2.6), and fails as uncached --det does; fails_when=the result is reused with proof (release-1 24962a94 and this branch at ca0bbb9c: MEASURED); no_claim=other machine facts', { ...T, skip: !canFake && 'needs setarch x86_64 --uname-2.6' }, () => {
  const dir = path.join(TMP, 'kernel-key', 'report');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: 'fixture-kernel', private: true, type: 'module' }));
  fs.writeFileSync(path.join(dir, 'vitest.config.mjs'), "export default { test: { include: ['tests/**/*.test.mjs'] } };\n");
  fs.writeFileSync(path.join(dir, 'tests', 'k.test.mjs'), "import { test, expect } from 'vitest';\n"
    + "test('k', () => { expect(process.report.getReport().header.osRelease.startsWith('2.6')).toBe(false); });\n");
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_TEST_CONTEXT', 'NODE_OPTIONS']) delete env[k];
  const args = [BIN, 'vitest', 'run', '--det', `--det-cache=${path.join(dir, '.c')}`];
  const cold = spawnSync(process.execPath, args, { cwd: dir, env, encoding: 'utf8' });
  assert.equal(cold.status, 0, cold.stdout + cold.stderr);
  const warm = spawnSync('setarch', ['x86_64', '--uname-2.6', process.execPath, ...args], { cwd: dir, env, encoding: 'utf8' });
  const uncached = spawnSync('setarch', ['x86_64', '--uname-2.6', process.execPath, BIN, 'vitest', 'run', '--det'], { cwd: dir, env, encoding: 'utf8' });
  assert.notEqual(uncached.status, 0, 'precondition: uncached --det fails under the other kernel');
  // both failed on test k itself, under Vitest (not before it started)
  assert.match(uncached.stdout + uncached.stderr, /k\.test\.mjs/, `precondition: Vitest ran k\n${uncached.stdout}\n${uncached.stderr}`);
  assert.notEqual(warm.status, 0, `the cached run must not reuse the pass\n${warm.stdout}\n${warm.stderr}`);
  assert.match(warm.stdout + warm.stderr, /k\.test\.mjs/, `the cached run ran k\n${warm.stdout}\n${warm.stderr}`);
  assert.doesNotMatch(warm.stdout, /reused with proof [1-9]/, warm.stdout);
});
