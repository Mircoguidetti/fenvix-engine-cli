'use strict';
// --det-isolate keeps every per-test session's run-level signals (spec "false greens on release-1", Phase B).
// Before the fix the final header was the first session's: a read outside any test in a later file, or a later
// session whose sensor could not start, was dropped and the run could be green without proof.
//
// The absent sensor is forced the way the engine's own tests do it: FENVIX_NO_PROVABLE_SENSOR (src/provable.js
// install; tests/test_provable_general_rule.py:125), set only in the session of the second file by a --require hook
// through NODE_OPTIONS (the mechanism of node/test/big-trace.test.js:268).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

const T = { timeout: 300000 };
const A = "import { test, expect } from 'vitest';\ntest('a', () => { expect(1).toBe(1); });\n";
const B_READ = "import { test, expect } from 'vitest';\nconst ws = process.env.GITHUB_WORKSPACE;\nconst foo = process.env.ISO_SIGNAL_FOO;\n"
  + "test('b', () => { expect(typeof ws).toBe('string'); expect(typeof foo).toBe('string'); });\n";
const B_CLEAN = "import { test, expect } from 'vitest';\ntest('b', () => { expect(2).toBe(2); });\n";
// sets the switch in the session that runs tests/b.test.mjs (its argv names the file); its workers inherit it
const HOOK = "if (process.argv.some((a) => a.endsWith('b.test.mjs'))) process.env.FENVIX_NO_PROVABLE_SENSOR = '1';\n";

function project(name, b) {
  const dir = path.join(TMP, 'isolate-signals', name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: `fixture-${name}`, private: true, type: 'module' }));
  fs.writeFileSync(path.join(dir, 'vitest.config.mjs'), "export default { test: { include: ['tests/**/*.test.mjs'] } };\n");
  fs.writeFileSync(path.join(dir, 'tests', 'a.test.mjs'), A);
  fs.writeFileSync(path.join(dir, 'tests', 'b.test.mjs'), b);
  fs.writeFileSync(path.join(dir, 'hook.cjs'), HOOK);
  return dir;
}

function run(dir, extra = [], env = {}) {
  const e = { ...process.env, GITHUB_WORKSPACE: '/w/one', ISO_SIGNAL_FOO: 'one', ...env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_TEST_CONTEXT', 'FENVIX_NO_PROVABLE_SENSOR']) delete e[k];
  if (!env.NODE_OPTIONS) delete e.NODE_OPTIONS;
  const r = spawnSync(process.execPath, [BIN, 'vitest', 'run', '--det', '--det-isolate', ...extra], { cwd: dir, env: e, encoding: 'utf8', maxBuffer: 64 << 20 });
  const tr = path.join(dir, '.detjs', 'trace.jsonl');
  const meta = fs.existsSync(tr) ? JSON.parse(fs.readFileSync(tr, 'utf8').split('\n')[0]).meta : null;
  return { status: r.status, meta, show: `exit ${r.status}\n${(r.stdout || '').slice(-3000)}\n${(r.stderr || '').slice(-3000)}` };
}

test('protects=a module-top-level read of a CI-volatile variable (not_proven_outside_tests) and of an ordinary variable (env_read_outside_tests) in the SECOND per-test session is in the final header; fails_when=the final header is the first session\'s, empty of both reads (release-1 6e79a62c); no_claim=the verifier\'s use of the entries (crates/detpy-core/src/verify.rs) and the runner\'s (runner-proof)', T, () => {
  const dir = project('top-level-read', B_READ);
  const r = run(dir);
  assert.equal(r.status, 0, r.show);
  assert.ok(r.meta, r.show);
  assert.ok(r.meta.not_proven_outside_tests.some((x) => /^env:GITHUB_WORKSPACE=[0-9a-f]+@tests\/b\.test\.mjs$/.test(x)), JSON.stringify(r.meta.not_proven_outside_tests));
  assert.ok(r.meta.env_read_outside_tests.includes('ISO_SIGNAL_FOO'), JSON.stringify(r.meta.env_read_outside_tests));
});

test('protects=a second per-test session whose sensor is absent makes the final header carry provable_absent and no provable; fails_when=the first session\'s provable is kept (release-1 6e79a62c); no_claim=how a sensor fails to start in the field (forced: FENVIX_NO_PROVABLE_SENSOR in that session only)', T, () => {
  const dir = project('absent-sensor', B_CLEAN);
  const r = run(dir, [], { NODE_OPTIONS: `--require ${path.join(dir, 'hook.cjs')}` });
  assert.ok(r.meta, r.show);
  assert.equal(r.meta.provable, undefined, JSON.stringify(r.meta.provable));
  assert.match(String(r.meta.provable_absent), /FENVIX_NO_PROVABLE_SENSOR/, r.show);
});

test('protects=positive control (gate note 1): a clean two-session run (no read outside tests, the same sensor in both) keeps provable, gets parallel {workers: 1, isolate: true} and is green; fails_when=the merge loses provable or turns a clean run red; no_claim=a run with --det-cache (a fully reused session declares cache-reuse/1: isolate-meta.test.js)', T, () => {
  const dir = project('clean', B_CLEAN);
  const r = run(dir);
  assert.equal(r.status, 0, r.show);
  assert.ok(r.meta, r.show);
  assert.equal(r.meta.provable && r.meta.provable.sensor, 'node-surface/1', r.show);
  assert.equal(r.meta.provable_absent, undefined, r.show);
  assert.deepEqual(r.meta.not_proven_outside_tests, []);
  assert.deepEqual(r.meta.parallel, { workers: 1, isolate: true });
  assert.deepEqual(r.meta.files, ['tests/a.test.mjs', 'tests/b.test.mjs']);
});
