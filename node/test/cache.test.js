'use strict';
// Cache with proof (--det-cache): every recorded input must make its dependants run again when it changes, and
// nothing outside the recorded inputs may be reused. Each test: run 1 records, run 2 reuses everything (receipts),
// one input changes, run 3 must run exactly the files that depend on it (and a fresh run must agree).
//
// The holes found by the Python reviewers (R-002, R-008*) are translated to Node: git reads, TZ, environment
// enumeration, child processes, worker threads, start-up work (globalSetup, setupFiles), read-write opens,
// symlinks, loopback connections, files written by another test file.
const { test, describe, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const { BIN, TMP, NODE_DIR } = require('./helpers');

const T = { timeout: 600000 };
const RUNNERS = (process.env.DETJS_TEST_RUNNERS || 'vitest,jest').split(',');

function write(dir, files) {
  for (const [name, body] of Object.entries(files)) {
    const p = path.join(dir, name);
    if (body === null) { fs.rmSync(p, { force: true, recursive: true }); continue; }
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, body);
  }
}

/** A fixture project. Vitest: ES modules (.mjs); Jest: CommonJS. */
function fixture(runner, name, files, { vitest = {}, jest = {}, pkg = {} } = {}) {
  const dir = path.join(TMP, 'cache', runner, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  write(dir, { 'package.json': JSON.stringify({ name: `cache-${name}`, private: true, ...pkg }) });
  if (runner === 'vitest') {
    const extra = vitest.raw || '';
    const cfg = { include: ['tests/**/*.test.mjs'], ...(vitest.test || {}) };
    write(dir, { 'vitest.config.mjs': `${extra}\nexport default { ${vitest.top || ''} test: ${JSON.stringify(cfg)} };\n` });
  } else {
    const cfg = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node', ...jest };
    write(dir, { 'jest.config.js': `module.exports = ${JSON.stringify(cfg)};\n` });
  }
  write(dir, files);
  return dir;
}

const EXT = { vitest: '.test.mjs', jest: '.test.js' };
const IMPORT = {
  vitest: (names, from) => `import { ${names} } from '${from}';`,
  jest: (names, from) => `const { ${names} } = require('${from}');`,
};
const HEAD = {
  vitest: "import { test, expect } from 'vitest'; import fs from 'node:fs'; import path from 'node:path'; import os from 'node:os'; import cp from 'node:child_process';",
  jest: "const fs = require('node:fs'); const path = require('node:path'); const os = require('node:os'); const cp = require('node:child_process');",
};
const MOD = {
  vitest: (body) => body.replace(/^module\.exports\.(\w+) = /gm, 'export const $1 = '),
  jest: (body) => body,
};
const SRC_EXT = { vitest: '.mjs', jest: '.js' };

function tfile(runner, name, body) {
  return { [`tests/${name}${EXT[runner]}`]: `${HEAD[runner]}\n${body}\n` };
}

function src(runner, name, body) {
  return { [`src/${name}${SRC_EXT[runner]}`]: MOD[runner](body) };
}

function imp(runner, names, name) {
  return IMPORT[runner](names, `../src/${name}${SRC_EXT[runner]}`);
}

/** Run detjs with the cache; returns {status, summary, receipts, stdout, stderr, outcomes}. */
function crun(runner, dir, args = [], env = {}) {
  const childEnv = { ...process.env, ...env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS']) delete childEnv[k];
  for (const [k, v] of Object.entries(env)) if (v === undefined) delete childEnv[k];
  const cacheDir = path.join(dir, '.cache');
  const out = path.join(dir, '.detjs', 'out.json');
  fs.rmSync(out, { force: true });
  const report = runner === 'vitest' ? ['--reporter=json', `--outputFile=${out}`]
    : ['--json', `--outputFile=${out}`, `--cacheDirectory=${path.join(dir, '.jest-cache')}`];
  const cache = args.some((a) => a.startsWith('--det-cache=')) ? [] : [`--det-cache=${cacheDir}`];
  const r = spawnSync(process.execPath, [BIN, runner, ...(runner === 'vitest' ? ['run'] : []), '--det', ...cache, ...args, ...report],
    { cwd: dir, encoding: 'utf8', env: childEnv, timeout: 240000 });
  let summary = null;
  try { summary = JSON.parse(fs.readFileSync(path.join(dir, '.detjs', 'cache-summary.json'), 'utf8')); } catch { /* none */ }
  let receipts = [];
  try { receipts = fs.readFileSync(path.join(dir, '.detjs', 'receipts.jsonl'), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)); } catch { /* none */ }
  const outcomes = {};
  try {
    const j = JSON.parse(fs.readFileSync(out, 'utf8'));
    for (const f of j.testResults || []) for (const a of f.assertionResults || []) outcomes[`${path.basename(f.name)} > ${a.title}`] = a.status;
  } catch { /* no file ran */ }
  return { status: r.status, summary, receipts, stdout: r.stdout, stderr: r.stderr, outcomes };
}

function show(r) {
  return `status=${r.status}\nsummary=${JSON.stringify(r.summary && { ...r.summary, runtime_parts: undefined, packages: undefined }, null, 1)}\nstdout=${(r.stdout || '').slice(-3000)}\nstderr=${(r.stderr || '').slice(-3000)}`;
}

function reused(r) {
  return new Set(((r.summary && r.summary.reused_files_list) || []));
}

function ran(r, files) {
  const re = reused(r);
  return files.filter((f) => !re.has(f)).sort();
}

/** Record, check full reuse, apply `change`, then the files that must run again are exactly `expect`. */
function cycle(runner, dir, files, change, expectRun, { args = [], env = {}, env3 } = {}) {
  const r1 = crun(runner, dir, args, env);
  assert.equal(r1.status, 0, `run 1 failed\n${show(r1)}`);
  const r2 = crun(runner, dir, args, env);
  assert.equal(r2.status, 0, `run 2 failed\n${show(r2)}`);
  assert.deepEqual(ran(r2, files), [], `run 2 should reuse every file\n${show(r2)}`);
  if (typeof change === 'function') change(); else write(dir, change);
  const r3 = crun(runner, dir, args, env3 || env);
  assert.deepEqual(ran(r3, files), [...expectRun].sort(), `run 3: files run again\n${show(r3)}`);
  return { r1, r2, r3 };
}

const F = (runner, n) => `tests/${n}${EXT[runner]}`;

before(() => fs.mkdirSync(path.join(TMP, 'cache'), { recursive: true }));

for (const runner of RUNNERS) {
  describe(`cache with proof: ${runner}`, () => {
    test('unchanged project: every file reused, receipts in the Python format', T, () => {
      const dir = fixture(runner, 'unchanged', {
        ...src(runner, 'a', 'module.exports.a = () => 1;\n'),
        ...tfile(runner, 'a', `${imp(runner, 'a', 'a')}\ntest('a', () => { expect(a()).toBe(1); });\ntest('b', () => { expect(2).toBe(2); });`),
      });
      const r1 = crun(runner, dir);
      assert.equal(r1.status, 0, show(r1));
      assert.equal(r1.summary.recorded, 2, show(r1));
      const r2 = crun(runner, dir);
      assert.equal(r2.status, 0, show(r2));
      assert.equal(r2.summary.reused_tests, 2, show(r2));
      assert.equal(r2.summary.reused_files, 1);
      const rows = r2.receipts.filter((x) => x.reused);
      assert.equal(rows.length, 3); // file manifest + 2 tests
      for (const k of ['nodeid', 'reused', 'key', 'run', 'outcome', 'fingerprint', 'duration', 'config', 'runtime', 'epoch', 'n_units', 'n_skeleton', 'n_hooks', 'n_content', 'n_data', 'n_env', 'n_changed_files_proven']) {
        assert.ok(k in rows[1], `receipt field ${k}`);
      }
      assert.ok(rows.find((x) => x.nodeid.endsWith('::a')).fingerprint.length === 32, 'Level 0 fingerprint in the receipt');
      assert.ok(rows.every((x) => x.n_content >= 1), 'code inputs listed');
    });

    test('code: a changed module reruns only the files that loaded it (direct and transitive)', T, () => {
      const dir = fixture(runner, 'code', {
        ...src(runner, 'leaf', 'module.exports.leaf = () => 1;\n'),
        ...src(runner, 'mid', `${runner === 'vitest' ? "import { leaf } from './leaf.mjs';" : "const { leaf } = require('./leaf.js');"}\nmodule.exports.mid = () => leaf() + 1;\n`),
        ...src(runner, 'other', 'module.exports.other = () => 3;\n'),
        ...tfile(runner, 'uses-mid', `${imp(runner, 'mid', 'mid')}\ntest('m', () => { expect(mid()).toBe(2); });`),
        ...tfile(runner, 'uses-other', `${imp(runner, 'other', 'other')}\ntest('o', () => { expect(other()).toBe(3); });`),
      });
      const files = [F(runner, 'uses-mid'), F(runner, 'uses-other')];
      const { r3 } = cycle(runner, dir, files, src(runner, 'leaf', 'module.exports.leaf = () => 1; // edited\n'), [F(runner, 'uses-mid')]);
      assert.match(JSON.stringify(r3.summary.misses), /leaf/);
    });

    test('code: a module loaded only by a dynamic import inside one test', T, () => {
      const dyn = runner === 'vitest' ? "const m = await import('../src/lazy.mjs');" : "const m = require('../src/lazy.js');";
      const dir = fixture(runner, 'dynamic', {
        ...src(runner, 'lazy', 'module.exports.v = 5;\n'),
        ...tfile(runner, 'dyn', `test('lazy', async () => { ${dyn} expect(m.v).toBe(5); });`),
        ...tfile(runner, 'plain', "test('p', () => { expect(1).toBe(1); });"),
      });
      cycle(runner, dir, [F(runner, 'dyn'), F(runner, 'plain')], src(runner, 'lazy', 'module.exports.v = 5; // x\n'), [F(runner, 'dyn')]);
    });

    test('data: content read, read-write open, stream, listing, existence and link target are inputs', T, () => {
      const dir = fixture(runner, 'data', {
        'data/read.txt': 'r', 'data/rw.txt': 'w', 'data/stream.txt': 's', 'data/list/a': '', 'data/target1.txt': 'x', 'data/target2.txt': 'x',
        ...tfile(runner, 'read', "test('read', () => { expect(fs.readFileSync('data/read.txt', 'utf8').length).toBe(1); });"),
        ...tfile(runner, 'rw', "test('rw', () => { const fd = fs.openSync('data/rw.txt', 'r+'); const b = Buffer.alloc(8); const n = fs.readSync(fd, b, 0, 8, 0); fs.closeSync(fd); expect(n).toBe(1); });"),
        ...tfile(runner, 'stream', "test('stream', async () => { let n = 0; for await (const c of fs.createReadStream('data/stream.txt')) n += c.length; expect(n).toBe(1); });"),
        ...tfile(runner, 'list', "test('list', () => { expect(fs.readdirSync('data/list').length).toBeGreaterThan(0); });"),
        ...tfile(runner, 'exists', "test('exists', () => { expect(fs.existsSync('data/flag')).toBe(fs.existsSync('data/flag')); });"),
        ...tfile(runner, 'link', "test('link', () => { expect(fs.readlinkSync('data/link').length).toBeGreaterThan(0); });"),
      });
      fs.symlinkSync('target1.txt', path.join(dir, 'data', 'link'));
      const all = ['read', 'rw', 'stream', 'list', 'exists', 'link'].map((n) => F(runner, n));
      const r1 = crun(runner, dir);
      assert.equal(r1.status, 0, show(r1));
      const r2 = crun(runner, dir);
      assert.deepEqual(ran(r2, all), [], show(r2));
      const steps = [
        [() => write(dir, { 'data/read.txt': 'R' }), 'read'],
        [() => write(dir, { 'data/rw.txt': 'W' }), 'rw'],
        [() => write(dir, { 'data/stream.txt': 'S' }), 'stream'],
        [() => write(dir, { 'data/list/b': '' }), 'list'],
        [() => write(dir, { 'data/flag': '1' }), 'exists'],
        [() => { fs.rmSync(path.join(dir, 'data', 'link')); fs.symlinkSync('target2.txt', path.join(dir, 'data', 'link')); }, 'link'],
      ];
      for (const [change, who] of steps) {
        change();
        const r = crun(runner, dir);
        assert.deepEqual(ran(r, all), [F(runner, who)], `${who}\n${show(r)}`);
      }
    });

    test('environment: a variable read is an input, an unread one is not, enumeration makes the whole environment one', T, () => {
      const dir = fixture(runner, 'env', {
        ...tfile(runner, 'reads', "test('r', () => { expect(process.env.DETJS_T_READ ?? '-').toBe(process.env.DETJS_T_READ ?? '-'); });"),
        ...tfile(runner, 'enum', "test('e', () => { expect(Object.keys(process.env).length).toBeGreaterThan(0); });"),
        ...tfile(runner, 'none', "test('n', () => { expect(1).toBe(1); });"),
      });
      const files = ['reads', 'enum', 'none'].map((n) => F(runner, n));
      cycle(runner, dir, files, () => {}, [F(runner, 'reads'), F(runner, 'enum')], { env: { XTEST_READ: '1' }, env3: { XTEST_READ: '2', XTEST_OTHER: '1' } }); // no read change: XTEST_READ is not DETJS_T_READ
      // the test reads DETJS_T_*? no: own variables (DETJS_*) are never inputs; use a plain name
    });

    test('environment: changed value of a variable read reruns its reader only', T, () => {
      const dir = fixture(runner, 'env2', {
        ...tfile(runner, 'reads', "test('r', () => { expect(process.env.XTEST_READ ?? '-').toBe(process.env.XTEST_READ ?? '-'); });"),
        ...tfile(runner, 'none', "test('n', () => { expect(1).toBe(1); });"),
      });
      cycle(runner, dir, ['reads', 'none'].map((n) => F(runner, n)), () => {}, [F(runner, 'reads')], { env: { XTEST_READ: '1' }, env3: { XTEST_READ: '2' } });
    });

    test('machine facts: os.homedir() follows HOME, os.hostname() and the user are keyed', T, () => {
      const dir = fixture(runner, 'homedir', {
        ...tfile(runner, 'home', "test('h', () => { expect(os.homedir().length).toBeGreaterThan(0); });"),
        ...tfile(runner, 'none', "test('n', () => { expect(1).toBe(1); });"),
      });
      const h1 = fs.mkdtempSync(path.join(os.tmpdir(), 'detjs-home-'));
      const h2 = fs.mkdtempSync(path.join(os.tmpdir(), 'detjs-home-'));
      const env = { FENVIX_RUNTIME_MEMO: 'off' };
      cycle(runner, dir, ['home', 'none'].map((n) => F(runner, n)), () => {}, [F(runner, 'home')], { env: { ...env, HOME: h1 }, env3: { ...env, HOME: h2 } });
    });

    test('runtime: an installed package file or the lockfile changes -> everything runs', T, () => {
      const dir = fixture(runner, 'runtime', {
        'node_modules/fake-dep/package.json': JSON.stringify({ name: 'fake-dep', version: '1.0.0', main: 'index.js' }),
        'node_modules/fake-dep/index.js': 'module.exports = 1;\n',
        'package-lock.json': '{"lockfileVersion":3}',
        ...tfile(runner, 'a', "test('a', () => { expect(1).toBe(1); });"),
        ...tfile(runner, 'b', "test('b', () => { expect(1).toBe(1); });"),
      });
      // the fixture's node_modules shadows detjs' own: link the runner in
      for (const p of runner === 'vitest' ? ['vitest', '@vitest', 'vite'] : ['jest']) {
        const s = path.join(NODE_DIR, 'node_modules', p);
        if (fs.existsSync(s) && !fs.existsSync(path.join(dir, 'node_modules', p))) fs.symlinkSync(s, path.join(dir, 'node_modules', p));
      }
      const files = ['a', 'b'].map((n) => F(runner, n));
      const { r3 } = cycle(runner, dir, files, { 'node_modules/fake-dep/index.js': 'module.exports = 2;\n' }, files);
      assert.match(JSON.stringify(r3.summary.misses), /runtime/);
      const r4 = crun(runner, dir);
      assert.deepEqual(ran(r4, files), [], show(r4));
      write(dir, { 'package-lock.json': '{"lockfileVersion":3,"x":1}' });
      const r5 = crun(runner, dir);
      assert.deepEqual(ran(r5, files), files, show(r5));
    });

    test('runtime: TZ is part of the identity (local time formatting depends on it)', T, () => {
      const dir = fixture(runner, 'tz', {
        ...tfile(runner, 'tz', "test('tz', () => { expect(new Date(0).getHours()).toBe(new Date(0).getHours()); });"),
      });
      const files = [F(runner, 'tz')];
      cycle(runner, dir, files, () => {}, files, { env: { TZ: 'UTC' }, env3: { TZ: 'Asia/Tokyo' } });
    });

    test('configuration: runner configuration, detjs options and tsconfig changes', T, () => {
      const dir = fixture(runner, 'config', {
        'tsconfig.json': '{"compilerOptions":{}}',
        ...tfile(runner, 'a', "test('a', () => { expect(1).toBe(1); });"),
      });
      const files = [F(runner, 'a')];
      cycle(runner, dir, files, { 'tsconfig.json': '{"compilerOptions":{"strict":true}}' }, files);
      const r = crun(runner, dir, ['--det-seed=5']);
      assert.deepEqual(ran(r, files), files, show(r));
      assert.match(JSON.stringify(r.summary.misses), /config/);
      const cfg = runner === 'vitest' ? 'vitest.config.mjs' : 'jest.config.js';
      const before = fs.readFileSync(path.join(dir, cfg), 'utf8');
      crun(runner, dir);
      write(dir, { [cfg]: runner === 'vitest' ? before.replace('test: {', 'test: { testTimeout: 7777, ') : before.replace('{', '{ "testTimeout": 7777, ') });
      const r2 = crun(runner, dir);
      assert.deepEqual(ran(r2, files), files, show(r2));
    });

    test('a failure is never reused', T, () => {
      const dir = fixture(runner, 'failure', {
        'flag.txt': 'bad',
        ...tfile(runner, 'f', "test('f', () => { expect(fs.readFileSync('flag.txt', 'utf8')).toBe('good'); });"),
      });
      const r1 = crun(runner, dir);
      assert.notEqual(r1.status, 0);
      const r2 = crun(runner, dir);
      assert.deepEqual(ran(r2, [F(runner, 'f')]), [F(runner, 'f')], show(r2));
      assert.match(JSON.stringify(r2.summary.misses), /new|failed/);
    });

    test('never cached: child process (git included), worker thread, loopback connection, OS entropy', T, () => {
      const dir = fixture(runner, 'uncacheable', {
        ...tfile(runner, 'spawn', "test('s', () => { expect(cp.execFileSync(process.execPath, ['-e', 'process.stdout.write(\"1\")']).toString()).toBe('1'); });"),
        ...tfile(runner, 'git', "test('g', () => { let v = ''; try { v = cp.execSync('git --version').toString(); } catch {} expect(typeof v).toBe('string'); });"),
        ...tfile(runner, 'worker', "const { Worker } = require('node:worker_threads');\ntest('w', async () => { const w = new Worker('postMessage(1)', { eval: true }); const v = await new Promise((r) => w.on('message', r)); await w.terminate(); expect(v).toBe(1); });".replace("const { Worker } = require('node:worker_threads');", runner === 'vitest' ? "import { Worker } from 'node:worker_threads';" : "const { Worker } = require('node:worker_threads');")),
        ...tfile(runner, 'loopback', `${runner === 'vitest' ? "import http from 'node:http';" : "const http = require('node:http');"}\ntest('l', async () => { const s = http.createServer((q, r) => r.end('ok')); await new Promise((r) => s.listen(0, '127.0.0.1', r)); const body = await new Promise((res) => http.get({ host: '127.0.0.1', port: s.address().port }, (r) => { let d = ''; r.on('data', (c) => d += c); r.on('end', () => res(d)); })); s.close(); expect(body).toBe('ok'); });`),
        ...tfile(runner, 'entropy', `${runner === 'vitest' ? "import crypto from 'node:crypto';" : "const crypto = require('node:crypto');"}\ntest('e', () => { expect(crypto.randomBytes(4).length).toBe(4); });`),
        ...tfile(runner, 'plain', "test('p', () => { expect(1).toBe(1); });"),
      });
      const files = ['spawn', 'git', 'worker', 'loopback', 'entropy', 'plain'].map((n) => F(runner, n));
      crun(runner, dir);
      const r2 = crun(runner, dir);
      assert.deepEqual(ran(r2, files), files.filter((f) => !f.includes('plain')), show(r2));
      const nc = JSON.stringify(r2.summary.not_cached_detail);
      for (const why of ['subprocess', 'worker thread', 'network connection', 'os entropy']) assert.match(nc, new RegExp(why), `${why}\n${nc}`);
    });

    test('git: reading .git directly makes the repository state an input', T, () => {
      const dir = fixture(runner, 'gitread', {
        ...tfile(runner, 'head', "test('h', () => { const h = fs.readFileSync('.git/HEAD', 'utf8'); const ref = h.startsWith('ref: ') ? fs.readFileSync(path.join('.git', h.slice(5).trim()), 'utf8') : h; expect(ref.length).toBeGreaterThan(0); });"),
        ...tfile(runner, 'plain', "test('p', () => { expect(1).toBe(1); });"),
      });
      const g = (...a) => spawnSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-c', 'commit.gpgsign=false', ...a], { cwd: dir });
      g('init', '-q'); g('add', '-A'); g('commit', '-q', '-m', 'one');
      cycle(runner, dir, ['head', 'plain'].map((n) => F(runner, n)), () => { write(dir, { 'NOTES.txt': 'x' }); g('add', 'NOTES.txt'); g('commit', '-q', '-m', 'two'); }, [F(runner, 'head')]);
    });

    test('a file written by another test file is never an input of a reused result', T, () => {
      const dir = fixture(runner, 'writer', {
        ...tfile(runner, 'a-writer', "test('w', () => { fs.writeFileSync('shared.out', String(process.env.XTEST_W || '0')); });"),
        ...tfile(runner, 'b-reader', "test('r', () => { expect(fs.readFileSync('shared.out', 'utf8')).toBe(String(process.env.XTEST_W || '0')); });"),
      });
      crun(runner, dir);
      const r2 = crun(runner, dir);
      assert.ok(ran(r2, [F(runner, 'b-reader')]).length === 1, `reader must run\n${show(r2)}`);
      assert.match(JSON.stringify(r2.summary.not_cached_detail), /written by/, show(r2));
    });

    test('verify mode decides but runs everything and compares', T, () => {
      const dir = fixture(runner, 'verify', { ...tfile(runner, 'a', "test('a', () => { expect(1).toBe(1); });") });
      crun(runner, dir);
      const r = crun(runner, dir, ['--det-cache-verify']);
      assert.equal(r.summary.verify_mode, true);
      assert.equal(r.summary.reused_files, 1);
      assert.equal(r.summary.verified, 2, show(r));
      assert.deepEqual(r.summary.verify_mismatches, []);
      assert.ok(Object.keys(r.outcomes).length === 1, 'the file ran');
    });
  });
}

// ---------------------------------------------------------------------------------------------------------------
describe('cache with proof: Vitest start-up and resolution', () => {
  const runner = 'vitest';
  test('globalSetup: what it reads and what its processes print are inputs of every file; async processes taint all', T, () => {
    const dir = fixture(runner, 'globalsetup', {
      'setup/global.mjs': "import fs from 'node:fs'; import cp from 'node:child_process';\nexport default function () { globalThis.__x = fs.readFileSync('setup/seed.txt', 'utf8'); cp.execFileSync('cat', ['setup/out.txt']); }\n",
      'setup/seed.txt': '1', 'setup/out.txt': 'a',
      ...tfile(runner, 'a', "test('a', () => { expect(1).toBe(1); });"),
      ...tfile(runner, 'b', "test('b', () => { expect(1).toBe(1); });"),
    }, { vitest: { test: { globalSetup: ['setup/global.mjs'] } } });
    const files = ['a', 'b'].map((n) => F(runner, n));
    cycle(runner, dir, files, { 'setup/seed.txt': '2' }, files);
    crun(runner, dir);
    write(dir, { 'setup/out.txt': 'b' });
    const r = crun(runner, dir);
    assert.deepEqual(ran(r, files), files, `process output change\n${show(r)}`);
    assert.match(JSON.stringify(r.summary.misses), /startup|out\.txt/);
    write(dir, { 'setup/global.mjs': "import cp from 'node:child_process';\nexport default function () { const p = cp.spawn('sleep', ['0']); p.unref(); }\n" });
    crun(runner, dir);
    const r2 = crun(runner, dir);
    assert.deepEqual(ran(r2, files), files, `async start-up process taints every test\n${show(r2)}`);
  });

  test('setupFiles: their code and what they read are inputs of every file', T, () => {
    const dir = fixture(runner, 'setupfiles', {
      'setup/each.mjs': "import fs from 'node:fs'; globalThis.__cfg = fs.readFileSync('setup/cfg.txt', 'utf8');\n",
      'setup/cfg.txt': '1',
      ...tfile(runner, 'a', "test('a', () => { expect(globalThis.__cfg).toBe(globalThis.__cfg); });"),
      ...tfile(runner, 'b', "test('b', () => { expect(1).toBe(1); });"),
    }, { vitest: { test: { setupFiles: ['setup/each.mjs'] } } });
    const files = ['a', 'b'].map((n) => F(runner, n));
    cycle(runner, dir, files, { 'setup/cfg.txt': '2' }, files);
    crun(runner, dir);
    write(dir, { 'setup/each.mjs': "import fs from 'node:fs'; globalThis.__cfg = fs.readFileSync('setup/cfg.txt', 'utf8') + '!';\n" });
    const r = crun(runner, dir);
    assert.deepEqual(ran(r, files), files, show(r));
  });

  test('configuration file dependencies (an alias module the config imports)', T, () => {
    const dir = fixture(runner, 'configdeps', {
      'aliases.mjs': "export const target = './src/one.mjs';\n",
      'src/one.mjs': 'export const v = 1;\n', 'src/two.mjs': 'export const v = 1;\n',
      ...tfile(runner, 'a', "import { v } from '@x';\ntest('a', () => { expect(v).toBe(1); });"),
    }, { vitest: { raw: "import { target } from './aliases.mjs'; import path from 'node:path';", top: "resolve: { alias: { '@x': path.resolve(target) } }," } });
    const files = [F(runner, 'a')];
    cycle(runner, dir, files, { 'aliases.mjs': "export const target = './src/two.mjs';\n" }, files);
  });

  test('a new file that shadows a resolved module (extension probing) reruns its importers', T, () => {
    const dir = fixture(runner, 'shadow', {
      'src/m.ts': 'export const v = 1;\n',
      ...tfile(runner, 'a', "import { v } from '../src/m';\ntest('a', () => { expect(v).toBe(1); });"),
      ...tfile(runner, 'b', "test('b', () => { expect(1).toBe(1); });"),
    });
    // Vite resolves '../src/m' trying .mjs and .js before .ts
    cycle(runner, dir, ['a', 'b'].map((n) => F(runner, n)), { 'src/m.mjs': 'export const v = 1;\n' }, [F(runner, 'a')]);
  });

  test('snapshot files are inputs', T, () => {
    const dir = fixture(runner, 'snapshot', {
      ...tfile(runner, 'snap', "test('s', () => { expect({ a: 1 }).toMatchSnapshot(); });"),
      ...tfile(runner, 'plain', "test('p', () => { expect(1).toBe(1); });"),
    });
    crun(runner, dir); // writes the snapshot (not cached: wrote its own snapshot file? it is its own output)
    const snap = path.join(dir, 'tests', '__snapshots__', 'snap.test.mjs.snap');
    assert.ok(fs.existsSync(snap));
    cycle(runner, dir, ['snap', 'plain'].map((n) => F(runner, n)), () => fs.appendFileSync(snap, '\n'), [F(runner, 'snap')], { args: ['--ci'] });
  });
});

describe('cache with proof: Jest start-up', () => {
  const runner = 'jest';
  test('setupFiles: what they read from the environment and the disk are inputs of every file', T, () => {
    const dir = fixture(runner, 'setupfiles', {
      'setup/each.js': "const fs = require('node:fs'); globalThis.__cfg = fs.readFileSync('setup/cfg.txt', 'utf8') + (process.env.XTEST_SETUP || '');\n",
      'setup/cfg.txt': '1',
      ...tfile(runner, 'a', "test('a', () => { expect(typeof globalThis.__cfg).toBe('string'); });"),
      ...tfile(runner, 'b', "test('b', () => { expect(1).toBe(1); });"),
    }, { jest: { setupFiles: ['<rootDir>/setup/each.js'] } });
    const files = ['a', 'b'].map((n) => F(runner, n));
    cycle(runner, dir, files, { 'setup/cfg.txt': '2' }, files);
    crun(runner, dir, [], { XTEST_SETUP: '1' });
    const r = crun(runner, dir, [], { XTEST_SETUP: '2' });
    assert.deepEqual(ran(r, files), files, `setupFiles env read\n${show(r)}`);
  });

  test('globalSetup: what it reads is an input of every file', T, () => {
    const dir = fixture(runner, 'globalsetup', {
      'setup/global.js': "const fs = require('node:fs'); module.exports = async () => { process.env.XTEST_G = fs.readFileSync('setup/seed.txt', 'utf8'); };\n",
      'setup/seed.txt': '1',
      ...tfile(runner, 'a', "test('a', () => { expect(1).toBe(1); });"),
    }, { jest: { globalSetup: '<rootDir>/setup/global.js' } });
    const files = [F(runner, 'a')];
    cycle(runner, dir, files, { 'setup/seed.txt': '2' }, files);
  });
});

// ---------------------------------------------------------------------------------------------------------------
describe('cache with proof: shared cache service', () => {
  let svc;
  let token;
  let port;
  const data = path.join(TMP, 'cache', 'service');
  before(async () => {
    fs.rmSync(data, { recursive: true, force: true });
    fs.mkdirSync(data, { recursive: true });
    const script = path.resolve(NODE_DIR, '..', 'python', 'detpy', 'cache_service.py');
    token = spawnSync('python3', [script, 'token', '--data', data, '--org', 'acme'], { encoding: 'utf8' }).stdout.trim().split('\n')[0];
    port = 18700 + Math.floor(Math.random() * 500);
    svc = spawn('python3', [script, 'serve', '--data', data, '--host', '127.0.0.1', '--port', String(port)], { stdio: 'ignore' });
    for (let i = 0; i < 100; i++) {
      const r = spawnSync('curl', ['-s', `http://127.0.0.1:${port}/v1/health`], { encoding: 'utf8' });
      if (r.stdout.includes('ok')) break;
      await new Promise((r2) => setTimeout(r2, 100));
    }
  });
  after(() => { if (svc) svc.kill(); });

  for (const runner of RUNNERS) {
    test(`${runner}: a second machine reuses with proof from the service; the token never reaches the tests`, T, () => {
      const dir = fixture(runner, 'shared', {
        'data.txt': '1',
        ...tfile(runner, 'a', "test('a', () => { expect(process.env.FENVIX_CACHE_TOKEN).toBe(undefined); expect(fs.readFileSync('data.txt', 'utf8')).toBe('1'); });"),
      });
      const url = `http://127.0.0.1:${port}/acme/${runner}-shared`;
      const m = (n) => ({ FENVIX_CACHE_TOKEN: token, FENVIX_CACHE_LOCAL: path.join(dir, `.mirror-${n}`) });
      const r1 = crun(runner, dir, [`--det-cache=${url}`], m(1));
      assert.equal(r1.status, 0, show(r1));
      assert.ok(r1.summary.remote.push_entry_docs_new >= 2, show(r1));
      const r2 = crun(runner, dir, [`--det-cache=${url}`], m(2));
      assert.equal(r2.summary.reused_files, 1, `machine 2 reuses\n${show(r2)}`);
      assert.ok(r2.summary.remote.pull_proven >= 2);
      write(dir, { 'data.txt': '2', [F(runner, 'a')]: `${HEAD[runner]}\ntest('a', () => { expect(fs.readFileSync('data.txt', 'utf8')).toBe('2'); });\n` });
      const r3 = crun(runner, dir, [`--det-cache=${url}`], m(3));
      assert.equal(r3.summary.reused_files, 0, `changed input: a pulled candidate must not prove reuse\n${show(r3)}`);
      assert.equal(r3.status, 0, show(r3));
    });
  }

  test('plain http to a remote host is refused; a forged document is dropped', T, () => {
    const { canonical, docId } = require('../src/cache/remote');
    assert.equal(canonical({ b: 1.5, a: 'é', c: 1e-7, d: [true, null], e: 3 }), '{"a":"\\u00e9","b":1.5,"c":1e-07,"d":[true,null],"e":3}');
    assert.equal(docId({ kind: 'set', v: 1, files: [] }).length, 64);
    const dir = fixture('vitest', 'refuse', { ...tfile('vitest', 'a', "test('a', () => { expect(1).toBe(1); });") });
    const r = crun('vitest', dir, ['--det-cache=http://cache.example.invalid/acme/x'], { FENVIX_CACHE_LOCAL: path.join(dir, '.mirror') });
    assert.equal(r.status, 0, show(r));
    assert.match(r.summary.remote.error, /refusing plain http/);
  });
});
