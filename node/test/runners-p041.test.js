'use strict';
// P-041 package JS-02 / F-06: the Vitest and Jest shells (audit 2026-11-20). Each gap has its regression test; every
// test fails on the code before the fix (8e972f0: DETJS_P041_BIN=<old bin/detjs.js> runs this file against it).
//
//   Jest      G-1312 G-1436 G-1466 setupFiles under the controls   G-1467 jest-jasmine2 brackets
//             G-0453 G-1588 G-0402 custom runners (Level 0, not-covered report, cache)
//             G-1290 decision after globalSetup   G-2180 no forced exit   G-2183 watch refused
//   Vitest    G-1437 G-1476 project runner composed   G-0461 vm pools   G-1475 isolate=false (clock, cache group)
//             G-2183 watch refused
//   both      G-2162 DETJS_* hidden from tests   G-2164 argv / execArgv   G-1477 read-only node_modules
//
// Runner versions other than the ones in node/node_modules (Vitest 5, Jest 30) are installed once, pinned, into
// DETJS_P041_DEPS (default node/test/.tmp/p041-deps/<name>); fixtures live below them so that they resolve there.
// Run: cd node && node --test test/runners-p041.test.js
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const helpers = require('./helpers');
const { write, show, reused, trace } = require('./runner-helpers');

const BIN = process.env.DETJS_P041_BIN || helpers.BIN;
const T = { timeout: 900000 };
const DEPS = process.env.DETJS_P041_DEPS || path.join(helpers.TMP, 'p041-deps');
const NODE_DIR = path.resolve(__dirname, '..');

const PINS = {
  vitest3: ['vitest@3.2.7'],
  vitest4: ['vitest@4.1.12'],
  jest30x: ['jest-light-runner@0.8.2', 'jest-jasmine2@30.5.2'],
  jest29: ['jest@29.7.0', 'jest-jasmine2@29.7.0'],
};

/** The pinned runner set `name` (installed on first use); fixtures are created below it. */
function deps(name) {
  const dir = path.join(DEPS, name);
  const want = PINS[name].map((s) => s.slice(0, s.lastIndexOf('@')));
  if (want.some((n) => !fs.existsSync(path.join(dir, 'node_modules', n, 'package.json')))) {
    fs.mkdirSync(dir, { recursive: true });
    if (!fs.existsSync(path.join(dir, 'package.json'))) fs.writeFileSync(path.join(dir, 'package.json'), `{"name":"p041-${name}","private":true}`);
    const r = spawnSync('npm', ['install', '--no-audit', '--no-fund', '--legacy-peer-deps', ...PINS[name]], { cwd: dir, encoding: 'utf8', timeout: 600000 });
    if (r.status !== 0) throw new Error(`npm install ${PINS[name].join(' ')} failed: ${r.stderr}`);
  }
  return dir;
}

/** A fixture project `name` with `files`, under `base` (default: the test temporary directory). */
function proj(name, files, base = path.join(helpers.TMP, 'p041-runners')) {
  const dir = path.join(base, 'fx', name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  write(dir, { 'package.json': JSON.stringify({ name: `p041-${name}`, private: true }), ...files });
  return dir;
}

function cleanEnv(extra = {}) {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'DETJS_SEED', 'DETJS_CACHE_DIR', 'DETJS_SHIM_DIRS']) delete env[k];
  return { ...env, CI: '1', ...extra };
}

/** One detjs run. */
function run(runner, dir, args = [], { cache = false, det = ['--det'], env = {}, timeout = 300000 } = {}) {
  fs.rmSync(path.join(dir, '.detjs', 'cache-summary.json'), { force: true });
  const c = cache ? [`--det-cache=${path.join(dir, '.cache')}`] : [];
  const r = spawnSync(process.execPath, [BIN, runner, ...det, ...c, ...args], { cwd: dir, encoding: 'utf8', env: cleanEnv(env), timeout });
  let summary = null;
  try { summary = JSON.parse(fs.readFileSync(path.join(dir, '.detjs', 'cache-summary.json'), 'utf8')); } catch { /* none */ }
  return { status: r.status, signal: r.signal, error: r.error, summary, stdout: r.stdout || '', stderr: r.stderr || '' };
}
const vrun = (dir, a = [], o = {}) => run('vitest', dir, ['run', ...a], o);
const jrun = (dir, a = [], o = {}) => run('jest', dir, a, o);
const out = (dir, name = 'out') => JSON.parse(fs.readFileSync(path.join(dir, `${name}.json`), 'utf8'));
const verifyTraces = (a, b) => spawnSync(process.execPath, [BIN, 'verify', a, b, '--json'], { encoding: 'utf8' });
const EPOCH = Date.parse('2025-01-01T00:00:00Z');

function receipts(dir) {
  try { return fs.readFileSync(path.join(dir, '.detjs', 'receipts.jsonl'), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)); } catch { return []; }
}

// ---------------------------------------------------------------------------------------------------------------
describe('Jest: setupFiles run under the controls (G-1312, G-1436, G-1466)', () => {
  test('setupFiles see the virtual clock and the seeded generators; legacy fake timers restore the virtual timers', T, () => {
    const dir = proj('jest-setupfiles', {
      'jest.config.js': "module.exports = { testMatch: ['**/t/**/*.test.js'], testEnvironment: 'node', setupFiles: ['./setup.js'] };\n",
      'setup.js': "global.SETUP = { now: Date.now(), r: Math.random(), uuid: crypto.randomUUID() };\n",
      't/a.test.js': `const fs = require('fs');
test('values', async () => {
  jest.useFakeTimers({ legacyFakeTimers: true });
  jest.useRealTimers();
  const t0 = Date.now();
  await new Promise((r) => setTimeout(r, 50));
  fs.writeFileSync('out.json', JSON.stringify({ ...SETUP, waited: Date.now() - t0 }));
});
`,
    });
    const r1 = jrun(dir);
    assert.equal(r1.status, 0, show(r1));
    const a = out(dir);
    assert.equal(a.now, EPOCH, `setupFiles read the virtual clock: ${JSON.stringify(a)}`);
    assert.ok(a.waited >= 50, `after legacy fake timers, setTimeout is virtual again (the clock jumps to the due time): ${JSON.stringify(a)}`);
    const r2 = jrun(dir);
    assert.equal(r2.status, 0, show(r2));
    assert.deepEqual(out(dir), a, 'setupFiles draw the same values in every run');
    // parallel lanes: Jest's worker processes wrap the environments as well
    write(dir, { 't/b.test.js': fs.readFileSync(path.join(dir, 't/a.test.js'), 'utf8').replace("'out.json'", "'out-b.json'") });
    const r3 = jrun(dir, [], { det: ['--det', '--det-workers=2'] });
    assert.equal(r3.status, 0, show(r3));
    assert.doesNotMatch(r3.stderr, /setupFiles ran before/, show(r3));
    assert.equal(out(dir, 'out-b').now, EPOCH);
  });
});

describe('Jest: jest-jasmine2 gets per-test brackets (G-1467)', () => {
  test('each spec is a test of the trace, beforeEach included; two runs identical; --det-seed shuffles specs', T, () => {
    const dir = proj('jasmine', {
      'jest.config.js': "module.exports = { testMatch: ['**/t/**/*.test.js'], testEnvironment: 'node', testRunner: 'jest-jasmine2' };\n",
      't/a.test.js': `const fs = require('fs'); const o = {};
describe('d', () => {
  beforeEach(() => { o.be = (o.be || []).concat(Math.random()); });
  it('one', () => { o.one = Math.random(); });
  it('two', () => { o.two = Date.now(); });
  it('three', () => {});
});
afterAll(() => fs.writeFileSync('out.json', JSON.stringify(o)));
`,
    }, deps('jest30x'));
    const r1 = jrun(dir);
    assert.equal(r1.status, 0, show(r1));
    const t1 = trace(dir);
    assert.deepEqual(t1.order, ['t/a.test.js::d::one', 't/a.test.js::d::two', 't/a.test.js::d::three'], show(r1));
    const ev = JSON.stringify(t1.tests['t/a.test.js::d::one'].events);
    assert.equal((ev.match(/Math\.random/g) || []).length, 2, `beforeEach and the spec's own draw are in the spec's bracket: ${ev}`);
    assert.ok(!/jest-jasmine2/.test(JSON.stringify(t1.tests)), 'jasmine\'s own timers are runner infrastructure');
    fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), path.join(dir, 'r1.jsonl'));
    const r2 = jrun(dir);
    assert.equal(r2.status, 0, show(r2));
    const v = JSON.parse(verifyTraces(path.join(dir, 'r1.jsonl'), path.join(dir, '.detjs', 'trace.jsonl')).stdout);
    assert.equal(v.summary.stable, 3, JSON.stringify(v.summary));
    const orders = new Set();
    for (const seed of [1, 2, 3, 4, 5]) {
      const r = jrun(dir, [], { det: ['--det', `--det-seed=${seed}`] });
      assert.equal(r.status, 0, show(r));
      orders.add(trace(dir).order.join(','));
    }
    assert.ok(orders.size > 1, `seeds shuffle the specs: ${[...orders]}`);
  });
});

describe('Jest: custom runners (G-0453, G-1588, G-0402)', () => {
  const lightFiles = () => ({
    'package.json': JSON.stringify({ name: 'p041-light', private: true, type: 'module' }),
    'jest.config.js': "export default { testMatch: ['**/t/**/*.test.js'], runner: 'jest-light-runner' };\n",
    'helper.js': "export const helper = () => 'v1';\n",
    't/a.test.js': `import fs from 'node:fs';
import { helper } from '../helper.js';
const mod = Math.random();
const o = {};
describe('d', () => {
  beforeEach(() => { o.be = (o.be || []).concat(Math.random()); });
  test('one', () => { o.one = Math.random(); o.mod = mod; });
  test('two', async () => { const t0 = Date.now(); await new Promise((r) => setTimeout(r, 20)); o.two = Date.now(); o.waited = o.two - t0; expect(helper()).toBe('v1'); });
});
afterAll(() => fs.writeFileSync('out.json', JSON.stringify(o)));
`,
    't/b.test.js': "test('b', () => { expect(Math.random()).toBeLessThan(2); });\n",
  });

  test('jest-light-runner: every test bracketed, controlled, identical in two runs', T, () => {
    const dir = proj('light', lightFiles(), deps('jest30x'));
    const r1 = jrun(dir);
    assert.equal(r1.status, 0, show(r1));
    const t1 = trace(dir);
    assert.deepEqual(t1.order, ['t/a.test.js::d::one', 't/a.test.js::d::two', 't/b.test.js::b'], show(r1));
    const o = out(dir);
    assert.ok(o.two >= EPOCH && o.two < EPOCH + 60000 && o.waited >= 20, `virtual clock and timers: ${JSON.stringify(o)}`);
    assert.doesNotMatch(r1.stderr, /NOT covered/);
    fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), path.join(dir, 'r1.jsonl'));
    const r2 = jrun(dir);
    assert.equal(r2.status, 0, show(r2));
    assert.deepEqual(out(dir), o, 'same values (module level included)');
    const v = JSON.parse(verifyTraces(path.join(dir, 'r1.jsonl'), path.join(dir, '.detjs', 'trace.jsonl')).stdout);
    assert.equal(v.summary.stable, 3, JSON.stringify(v.summary));
    const r3 = jrun(dir, [], { det: ['--det', '--det-seed=7'] });
    assert.equal(r3.status, 0, show(r3));
    assert.equal(trace(dir).order.length, 3);
  });

  test('a runner that is not a test runner (lint style): reported NOT covered, verify never identical, never cached', T, () => {
    const dir = proj('lint-runner', {
      'jest.config.js': "module.exports = { testMatch: ['**/t/**/*.test.js'], runner: './lint-runner.js' };\n",
      'lint-runner.js': `'use strict';
const { createEmptyTestResult } = require(require.resolve('@jest/test-result', { paths: [require.resolve('jest')] }));
module.exports = class LintRunner {
  constructor(globalConfig) { this.globalConfig = globalConfig; }
  async runTests(tests, watcher, onStart, onResult) {
    for (const t of tests) {
      await onStart(t);
      const r = { ...createEmptyTestResult(), testFilePath: t.path, numPassingTests: 1,
        testResults: [{ ancestorTitles: [], title: 'lint', fullName: 'lint', status: 'passed', duration: 0, failureMessages: [], numPassingAsserts: 0, failureDetails: [] }] };
      await onResult(t, r);
    }
  }
};
`,
      't/a.test.js': 'const x = 1;\n',
    });
    const r1 = jrun(dir, [], { cache: true });
    assert.equal(r1.status, 0, show(r1));
    assert.match(r1.stderr, /NOT covered by Level 0/, show(r1));
    const t1 = trace(dir);
    assert.deepEqual(t1.order, ['t/a.test.js::lint'], show(r1));
    assert.match(JSON.stringify(t1.tests['t/a.test.js::lint'].events), /uncontrolled\.level0/);
    fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), path.join(dir, 'r1.jsonl'));
    const r2 = jrun(dir, [], { cache: true });
    assert.equal(r2.status, 0, show(r2));
    assert.ok(!reused(r2).includes('t/a.test.js'), `never reused\n${show(r2)}`);
    const v = JSON.parse(verifyTraces(path.join(dir, 'r1.jsonl'), path.join(dir, '.detjs', 'trace.jsonl')).stdout);
    assert.equal(v.summary.stable, 0, `verify never calls it identical: ${JSON.stringify(v.summary)}`);
  });

  test('jest-light-runner with the cache: reused as one group, no wrong reuse when a dependency changes', T, () => {
    const dir = proj('light-cache', lightFiles(), deps('jest30x'));
    const r1 = jrun(dir, [], { cache: true });
    assert.equal(r1.status, 0, show(r1));
    const r2 = jrun(dir, [], { cache: true });
    assert.equal(r2.status, 0, show(r2));
    assert.deepEqual(reused(r2).sort(), ['t/a.test.js', 't/b.test.js'], show(r2));
    // b changes: a could be reused alone, but the group runs together
    write(dir, { 't/b.test.js': "test('b', () => { expect(Math.random()).toBeLessThan(3); });\n" });
    const r3 = jrun(dir, [], { cache: true });
    assert.equal(r3.status, 0, show(r3));
    assert.deepEqual(reused(r3), [], show(r3));
    assert.match(JSON.stringify(r3.summary), /group/, show(r3));
    // a dependency of a changes so that a fresh run fails: never reused
    const r4 = jrun(dir, [], { cache: true });
    assert.deepEqual(reused(r4).sort(), ['t/a.test.js', 't/b.test.js'], show(r4));
    write(dir, { 'helper.js': "export const helper = () => 'v2';\n" });
    const fresh = jrun(dir);
    assert.notEqual(fresh.status, 0, show(fresh));
    const r5 = jrun(dir, [], { cache: true });
    assert.ok(!reused(r5).includes('t/a.test.js'), `WRONG REUSE\n${show(r5)}`);
    assert.notEqual(r5.status, 0, show(r5));
  });
});

describe('Jest: the reuse decision is made after globalSetup (G-1290)', () => {
  test('a globalSetup that runs a process: reused; its output changes: not reused', T, () => {
    const dir = proj('globalsetup', {
      'jest.config.js': "module.exports = { testMatch: ['**/t/**/*.test.js'], testEnvironment: 'node', globalSetup: './gs.js' };\n",
      'gs.js': "const { execFileSync } = require('child_process');\nmodule.exports = async () => { process.env.GS_VALUE = execFileSync('cat', ['data.txt'], { encoding: 'utf8' }).trim(); };\n",
      'data.txt': 'v1\n',
      't/a.test.js': "test('a', () => { expect(process.env.GS_VALUE).toBe('v1'); });\n",
    });
    const r1 = jrun(dir, [], { cache: true });
    assert.equal(r1.status, 0, show(r1));
    const r2 = jrun(dir, [], { cache: true });
    assert.equal(r2.status, 0, show(r2));
    assert.ok(reused(r2).includes('t/a.test.js'), `run 2 must reuse\n${show(r2)}`);
    write(dir, { 'data.txt': 'v2\n' });
    const fresh = jrun(dir);
    assert.notEqual(fresh.status, 0, show(fresh));
    const r3 = jrun(dir, [], { cache: true });
    assert.ok(!reused(r3).includes('t/a.test.js'), `WRONG REUSE\n${show(r3)}`);
    assert.notEqual(r3.status, 0, show(r3));
  });
});

describe('Jest: exit without --forceExit (G-2180)', () => {
  test('a clean suite: no forced exit message; a suite leaving a handle: named, and the process exits with the status', T, () => {
    const dir = proj('forceexit', {
      'jest.config.js': "module.exports = { testMatch: ['**/t/**/*.test.js'], testEnvironment: 'node' };\n",
      't/a.test.js': "test('a', () => {});\n",
    });
    const r1 = jrun(dir);
    assert.equal(r1.status, 0, show(r1));
    assert.doesNotMatch(r1.stderr + r1.stdout, /Force exiting Jest/, show(r1));
    assert.doesNotMatch(r1.stderr, /open handles/);
    write(dir, { 't/b.test.js': "const http = require('http'); test('leak', async () => { await new Promise((r) => http.createServer().listen(0, '127.0.0.1', r)); });\n" });
    const r2 = jrun(dir, [], { timeout: 120000 });
    assert.equal(r2.status, 0, show(r2));
    assert.match(r2.stderr, /open handles .*TCPServerWrap/, show(r2));
    assert.doesNotMatch(r2.stderr + r2.stdout, /Force exiting Jest/);
  });
});

describe('watch mode under --det is refused with a message (G-2183)', () => {
  test('vitest watch / jest --watch', T, () => {
    const v = proj('watch-vitest', { 'a.test.mjs': "import { test } from 'vitest'; test('a', () => {});\n" });
    const r1 = run('vitest', v, ['watch'], { timeout: 60000 });
    assert.equal(r1.status, 2, show(r1));
    assert.match(r1.stderr, /watch mode is not supported under --det/);
    const r1b = run('vitest', v, ['--watch'], { timeout: 60000 });
    assert.equal(r1b.status, 2, show(r1b));
    const j = proj('watch-jest', { 'jest.config.js': "module.exports = { testEnvironment: 'node' };\n", 'a.test.js': "test('a', () => {});\n" });
    for (const flag of ['--watch', '--watchAll']) {
      const r2 = run('jest', j, [flag], { timeout: 60000 });
      assert.equal(r2.status, 2, show(r2));
      assert.match(r2.stderr, /watch mode is not supported under --det/);
    }
  });
});

// ---------------------------------------------------------------------------------------------------------------
describe('both: what test code sees of detjs (G-2162, G-2164)', () => {
  const body = (head) => `${head}
test('env', () => {
  const child = execFileSync(process.execPath, ['-e', 'process.stdout.write(String(Boolean(process.env.DETJS_ROOT)))'], { encoding: 'utf8' });
  fs.writeFileSync('out.json', JSON.stringify({ keys: Object.keys(process.env).filter((k) => /^DETJS/.test(k)), det: process.env.DETJS === undefined, has: 'DETJS_DIR' in process.env,
    inspect: /DETJS/.test(require('util').inspect(process.env)), json: /DETJS/.test(JSON.stringify(process.env)), child, argv: process.argv, execArgv: process.execArgv }));
});
`;
  test('vitest: no DETJS_* for test code, children still get them; worker execArgv without detjs preloads', T, () => {
    const dir = proj('env-vitest', {
      'vitest.config.mjs': "export default { test: { include: ['t/**/*.test.mjs'], execArgv: ['--require', './pre.cjs'], poolOptions: { forks: { execArgv: ['--require', './pre.cjs'] } } } };\n",
      'pre.cjs': 'globalThis.PRE = 1;\n',
      't/a.test.mjs': body("import { test } from 'vitest'; import fs from 'node:fs'; import { execFileSync } from 'node:child_process'; import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);"),
    });
    const plain = run('vitest', dir, ['run'], { det: [] });
    assert.equal(plain.status, 0, show(plain));
    const p = out(dir);
    const r = vrun(dir, [], { cache: true });
    assert.equal(r.status, 0, show(r));
    const o = out(dir);
    assert.deepEqual(o.keys, [], JSON.stringify(o));
    assert.equal(o.det, true);
    assert.equal(o.has, false);
    assert.equal(o.inspect, false);
    assert.equal(o.json, false);
    assert.equal(o.child, 'true', 'a child process still inherits detjs\' variables');
    assert.deepEqual(o.execArgv, p.execArgv, 'the worker\'s execArgv is the one of a plain run');
    assert.deepEqual(o.argv, p.argv);
  });

  test('jest: no DETJS_* for test code, children still get them; process.argv is the in-band jest command line', T, () => {
    const dir = proj('env-jest', {
      'jest.config.js': "module.exports = { testMatch: ['**/t/**/*.test.js'], testEnvironment: 'node' };\n",
      't/a.test.js': body("const fs = require('fs'); const { execFileSync } = require('child_process');"),
    });
    const r = jrun(dir, ['t/a.test.js']);
    assert.equal(r.status, 0, show(r));
    const o = out(dir);
    assert.deepEqual(o.keys, [], JSON.stringify(o));
    assert.equal(o.det, true);
    assert.equal(o.has, false);
    assert.equal(o.inspect, false);
    assert.equal(o.child, 'true');
    const plain = run('jest', dir, ['t/a.test.js'], { det: [] });
    assert.equal(plain.status, 0, show(plain));
    const p = out(dir);
    assert.deepEqual(o.argv, p.argv, 'in band, plain jest shows [node, jest bin, ...args]');
    assert.ok(!o.argv.includes('--det'));
  });
});

describe('both: a read-only node_modules (G-1477)', () => {
  const immutable = (dir, on) => spawnSync('chattr', [on ? '+i' : '-i', path.join(dir, 'node_modules')], { encoding: 'utf8' });

  test('the runner shim goes to a temporary node_modules; no writable place at all: a clear message', T, (t) => {
    const v = proj('ro-vitest', { 'a.test.mjs': "import { test, expect } from 'vitest'; test('a', () => { expect(Date.now()).toBe(1735689600000); });\n", node_modules: null });
    const j = proj('ro-jest', { 'jest.config.js': "module.exports = { testEnvironment: 'node' };\n", 'a.test.js': "test('a', () => { expect(Date.now()).toBe(1735689600000); });\n" });
    for (const d of [v, j]) fs.mkdirSync(path.join(d, 'node_modules'), { recursive: true });
    if (immutable(v, true).status !== 0) { t.skip('chattr +i not available (needs root on ext4)'); return; }
    try {
      immutable(j, true);
      const r1 = vrun(v);
      assert.equal(r1.status, 0, show(r1));
      assert.equal(trace(v).order.length, 1);
      const r2 = jrun(j);
      assert.equal(r2.status, 0, show(r2));
      assert.equal(trace(j).order.length, 1);
      const none = jrun(j, [], { env: { DETJS_SHIM_DIRS: [path.join(j, 'node_modules', '.detjs'), path.join(v, 'node_modules', '.detjs')].join(path.delimiter) } });
      assert.equal(none.status, 2, show(none));
      assert.match(none.stderr, /cannot write the runner shim .*needs one writable directory whose path contains node_modules/, show(none));
    } finally {
      immutable(v, false);
      immutable(j, false);
    }
  });
});

// ---------------------------------------------------------------------------------------------------------------
const VITESTS = [['5', null], ['3', 'vitest3'], ['4', 'vitest4']].filter(([v]) => (process.env.DETJS_P041_VITEST || '5,3,4').split(',').includes(v));

for (const [major, dep] of VITESTS) {
  const base = () => (dep ? path.join(deps(dep), `v${major}`) : path.join(helpers.TMP, 'p041-runners', `v${major}`));

  describe(`vitest ${major}: the project's own runner is composed with detjs' (G-1437, G-1476)`, () => {
    test('the project runner\'s hooks run and Level 0 is active; its file is keyed by the cache', T, () => {
      const imp = major === '3' || major === '4' ? "import { VitestTestRunner as Base } from 'vitest/runners';" : "import { TestRunner as Base } from 'vitest';";
      const dir = proj('own-runner', {
        'package.json': JSON.stringify({ name: 'p041-own-runner', private: true, type: 'module' }),
        'vitest.config.mjs': "export default { test: { include: ['t/**/*.test.ts'], runner: './my-runner.ts' } };\n",
        'my-runner.ts': `${imp}\nexport default class MyRunner extends Base {\n  async onBeforeRunTask(test: any) { (globalThis as any).__mine = ((globalThis as any).__mine || 0) + 1; await super.onBeforeRunTask?.(test); }\n}\n`,
        't/a.test.ts': "import { test, expect } from 'vitest';\ntest('a', () => { expect((globalThis as any).__mine).toBe(1); expect(Date.now()).toBe(1735689600000); });\n",
      }, base());
      const det = ['--det', '--det-epoch=2025-01-01T00:00:00Z'];
      const r1 = vrun(dir, [], { cache: true, det });
      assert.equal(r1.status, 0, show(r1));
      assert.equal(trace(dir).order.length, 1, show(r1));
      const r2 = vrun(dir, [], { cache: true, det });
      assert.ok(reused(r2).includes('t/a.test.ts'), show(r2));
      write(dir, { 'my-runner.ts': `${imp}\nexport default class MyRunner extends Base {}\n` });
      const fresh = vrun(dir, [], { det });
      assert.notEqual(fresh.status, 0, show(fresh));
      const r3 = vrun(dir, [], { cache: true, det });
      assert.ok(!reused(r3).includes('t/a.test.ts'), `WRONG REUSE\n${show(r3)}`);
    });
  });

  describe(`vitest ${major}: vm pools get the realm controls (G-0461)`, () => {
    test('vmThreads and vmForks give the same values as threads, named imports of node:timers included', T, () => {
      const files = {
        'package.json': JSON.stringify({ name: 'p041-vm', private: true, type: 'module' }),
        'vitest.config.mjs': "export default { test: { include: ['t/**/*.test.mjs'], pool: process.env.POOL } };\n",
        'body.mjs': `import { test } from 'vitest';
import fs from 'node:fs';
import nodeCrypto from 'node:crypto';
import { setTimeout as nodeSetTimeout } from 'node:timers';
import { setTimeout as sleep } from 'node:timers/promises';
export function body(name) {
  const mod = Math.random();
  test(name, async () => {
    const t0 = Date.now();
    await new Promise((r) => nodeSetTimeout(r, 20));
    await sleep(10);
    const o = { mod, r: Math.random(), waited: Date.now() - t0, d: new Date().toISOString(), uuid: crypto.randomUUID(), nuuid: nodeCrypto.randomUUID(), perf: performance.now(), dir: fs.readdirSync('t') };
    fs.mkdirSync('out', { recursive: true });
    fs.writeFileSync('out/' + name + '-' + process.env.POOL + '.json', JSON.stringify(o));
  });
}
`,
        't/a.test.mjs': "import { body } from '../body.mjs'; body('a');\n",
        't/b.test.mjs': "import { body } from '../body.mjs'; body('b');\n",
      };
      const dir = proj('vm', files, base());
      const got = {};
      for (const pool of ['threads', 'vmThreads', 'vmForks']) {
        const r = vrun(dir, [], { env: { POOL: pool } });
        assert.equal(r.status, 0, show(r));
        for (const n of ['a', 'b']) got[`${n}-${pool}`] = out(path.join(dir, 'out'), `${n}-${pool}`);
      }
      for (const n of ['a', 'b']) {
        assert.ok(got[`${n}-threads`].waited >= 30, JSON.stringify(got[`${n}-threads`]));
        assert.deepEqual(got[`${n}-vmThreads`], got[`${n}-threads`], `vmThreads ${n}`);
        assert.deepEqual(got[`${n}-vmForks`], got[`${n}-threads`], `vmForks ${n}`);
      }
    });
  });

  describe(`vitest ${major}: isolate=false (G-1475)`, () => {
    const files = (extra = {}) => ({
      'vitest.config.mjs': "export default { test: { include: ['t/**/*.test.mjs'], isolate: process.env.ISO !== '0', poolOptions: { forks: { isolate: process.env.ISO !== '0' }, threads: { isolate: process.env.ISO !== '0' } } } };\n",
      'shared.mjs': 'export const state = { files: [] };\n',
      'out/.keep': '', // (a directory one file creates and the next reads makes that file not cached)
      't/a.test.mjs': "import { test } from 'vitest'; import { state } from '../shared.mjs'; import fs from 'node:fs'; const mod = [Math.random(), Date.now()]; test('a', async () => { await new Promise((r) => setTimeout(r, 30)); state.files.push('a'); fs.mkdirSync('out', { recursive: true }); fs.writeFileSync('out/a-' + process.env.ISO + '.json', JSON.stringify({ mod, now: Date.now() })); });\n",
      't/b.test.mjs': "import { test, expect } from 'vitest'; import { state } from '../shared.mjs'; import fs from 'node:fs'; const mod = [Math.random(), Date.now()]; test('b', () => { fs.mkdirSync('out', { recursive: true }); fs.writeFileSync('out/b-' + process.env.ISO + '.json', JSON.stringify({ mod, now: Date.now() })); if (process.env.ISO === '0') expect(state.files).toEqual(['a']); });\n",
      ...extra,
    });

    test('module-level values of each file are those of an isolated run', T, () => {
      const dir = proj('noiso-values', files(), base());
      for (const iso of ['1', '0']) {
        const r = vrun(dir, [], { env: { ISO: iso } });
        assert.equal(r.status, 0, show(r));
      }
      for (const n of ['a', 'b']) assert.deepEqual(out(path.join(dir, 'out'), `${n}-0`), out(path.join(dir, 'out'), `${n}-1`), n);
    });

    test('cached as one group: reused together, run together, keyed by the group; no wrong reuse of carried state', T, () => {
      const dir = proj('noiso-cache', files(), base());
      const env = { ISO: '0' };
      const r1 = vrun(dir, [], { cache: true, env });
      assert.equal(r1.status, 0, show(r1));
      const r2 = vrun(dir, [], { cache: true, env });
      assert.deepEqual(reused(r2).sort(), ['t/a.test.mjs', 't/b.test.mjs'], `${show(r1)}\n----\n${show(r2)}`);
      // a subset is another group: nothing reused
      const r3 = vrun(dir, ['t/b.test.mjs'], { cache: true, env });
      assert.ok(!reused(r3).includes('t/b.test.mjs'), show(r3));
      // (the subset run re-recorded b under its own group: the full group runs once more, then is reused)
      const r4a = vrun(dir, [], { cache: true, env });
      assert.ok(!reused(r4a).includes('t/b.test.mjs'), show(r4a));
      // a changes the state b depends on: a fresh run of b fails; b must not be reused
      const r4 = vrun(dir, [], { cache: true, env });
      assert.deepEqual(reused(r4).sort(), ['t/a.test.mjs', 't/b.test.mjs'], show(r4));
      write(dir, { 't/a.test.mjs': "import { test } from 'vitest'; import { state } from '../shared.mjs'; test('a', () => { state.files.push('A'); });\n" });
      const fresh = vrun(dir, [], { env });
      assert.notEqual(fresh.status, 0, show(fresh));
      const r5 = vrun(dir, [], { cache: true, env });
      assert.ok(!reused(r5).includes('t/b.test.mjs'), `WRONG REUSE\n${show(r5)}`);
      assert.notEqual(r5.status, 0, show(r5));
      assert.ok(receipts(dir).length > 0);
    });
  });
}
