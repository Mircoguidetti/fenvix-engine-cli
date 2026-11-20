'use strict';
// Fixes of review r021b (G1-G4), beyond the reviewer's own cases (test/review-r021b.test.js): other ways to read a
// Stats object or the environment without a getter or a trap, value-keyed Stats fields, recursive listings through
// links with every API, and user code that runs before the runner (preloads from execArgv and NODE_OPTIONS, a
// custom Vitest environment).
// Shape (as in the review): record, reuse, change one input so that a fresh run fails, then the cached run must
// not reuse the file and must agree with the fresh run. `same:` cases compare a run without the cache with a
// capture run; `keeps:` cases check that a change that cannot alter the result does not stop reuse.
// Run: cd node && node --test --test-concurrency=1 test/r021b-fixes.test.js (R021BF_ONLY=<regex> for a subset).
const { test, describe, before } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

const T = { timeout: 600000 };
const RUNNERS = (process.env.DETJS_TEST_RUNNERS || 'vitest,jest').split(',');
const ONLY = process.env.R021BF_ONLY ? new RegExp(process.env.R021BF_ONLY) : null;
const EXT = { vitest: '.test.mjs', jest: '.test.js' };
const HEAD = {
  vitest: "import { test, expect } from 'vitest'; import fs from 'node:fs'; import path from 'node:path'; import util from 'node:util'; import v8 from 'node:v8';",
  jest: "const fs = require('node:fs'); const path = require('node:path'); const util = require('node:util'); const v8 = require('node:v8');",
};

function write(dir, files) {
  for (const [name, body] of Object.entries(files)) {
    const p = path.join(dir, name);
    if (body === null) { fs.rmSync(p, { force: true, recursive: true }); continue; }
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, body);
  }
}

function fixture(runner, name, files, { vitestTest = {}, jest = {}, pkg = {} } = {}) {
  const dir = path.join(TMP, 'r021b-fixes', runner, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  write(dir, { 'package.json': JSON.stringify({ name: `r021bf-${name}`, private: true, ...pkg }) });
  if (runner === 'vitest') {
    write(dir, { 'vitest.config.mjs': `export default { test: ${JSON.stringify({ include: ['tests/**/*.test.mjs'], ...vitestTest })} };\n` });
  } else {
    write(dir, { 'jest.config.js': `module.exports = ${JSON.stringify({ testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node', ...jest })};\n` });
  }
  write(dir, files);
  return dir;
}

const tfile = (runner, name, body) => ({ [`tests/${name}${EXT[runner]}`]: `${HEAD[runner]}\n${body}\n` });

function crun(runner, dir, { cache = true, env: extra = {} } = {}) {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS']) delete env[k];
  Object.assign(env, extra);
  const out = path.join(dir, '.detjs', 'out.json');
  fs.rmSync(out, { force: true });
  fs.rmSync(path.join(dir, '.detjs', 'cache-summary.json'), { force: true });
  const report = runner === 'vitest' ? ['--reporter=json', `--outputFile=${out}`]
    : ['--json', `--outputFile=${out}`, `--cacheDirectory=${path.join(dir, '.jest-cache')}`];
  const c = cache ? [`--det-cache=${path.join(dir, '.cache')}`] : [];
  const r = spawnSync(process.execPath, [BIN, runner, ...(runner === 'vitest' ? ['run'] : []), '--det', ...c, ...report],
    { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  let summary = null;
  try { summary = JSON.parse(fs.readFileSync(path.join(dir, '.detjs', 'cache-summary.json'), 'utf8')); } catch { /* none */ }
  return { status: r.status, summary, stdout: r.stdout, stderr: r.stderr };
}

const show = (r) => `status=${r.status}\nreused=${JSON.stringify(r.summary && r.summary.reused_files_list)}\nmisses=${JSON.stringify(r.summary && r.summary.misses)}\nnot_cached=${JSON.stringify(r.summary && r.summary.not_cacheable)}\nstdout=${(r.stdout || '').slice(-1500)}\nstderr=${(r.stderr || '').slice(-2500)}`;
const reusedFiles = (r) => ((r.summary && r.summary.reused_files_list) || []).map((f) => f.split('@@')[0]);

function noWrongReuse(runner, dir, file, change, { env1 = {}, env2 = env1, mayRefuse = false } = {}) {
  const r1 = crun(runner, dir, { env: env1 });
  assert.equal(r1.status, 0, `run 1 (record) must pass\n${show(r1)}`);
  const r2 = crun(runner, dir, { env: env1 });
  assert.equal(r2.status, 0, `run 2 must pass\n${show(r2)}`);
  if (mayRefuse && !reusedFiles(r2).includes(file)) return 'refused';
  assert.ok(reusedFiles(r2).includes(file), `run 2 must reuse ${file} (otherwise this test proves nothing)\n${show(r2)}`);
  if (typeof change === 'function') change(); else write(dir, change);
  fs.rmSync(path.join(dir, 'node_modules', '.vitest-cache'), { recursive: true, force: true });
  const fresh = crun(runner, dir, { cache: false, env: env2 });
  assert.notEqual(fresh.status, 0, `the change must make a fresh run fail (test precondition)\n${show(fresh)}`);
  const r3 = crun(runner, dir, { env: env2 });
  assert.ok(!reusedFiles(r3).includes(file), `WRONG REUSE: ${file} reused after its input changed; a fresh run fails\n${show(r3)}`);
  assert.equal(r3.status, fresh.status, `cached run must agree with the fresh run\n${show(r3)}`);
  return 'rerun';
}

/** The same outcome with and without the cache (the capture run is the run it measures). */
function sameOutcome(runner, dir, { env = {} } = {}) {
  const plain = crun(runner, dir, { cache: false, env });
  assert.equal(plain.status, 0, `without the cache the test passes\n${show(plain)}`);
  const cached = crun(runner, dir, { env });
  assert.equal(cached.status, 0, `with the cache (capture run) the outcome must be the same\n${show(cached)}`);
  return cached;
}

/** A change the result cannot depend on keeps the file reused. */
function keepsReuse(runner, dir, file, change) {
  const r1 = crun(runner, dir);
  assert.equal(r1.status, 0, `run 1 (record) must pass\n${show(r1)}`);
  if (typeof change === 'function') change(); else write(dir, change);
  const r2 = crun(runner, dir);
  assert.equal(r2.status, 0, `run 2 must pass\n${show(r2)}`);
  assert.ok(reusedFiles(r2).includes(file), `${file} must still be reused\n${show(r2)}`);
}

before(() => fs.mkdirSync(path.join(TMP, 'r021b-fixes'), { recursive: true }));
const t = (name, opts, fn) => test(name, ONLY && !ONLY.test(name) ? { ...opts, skip: 'R021BF_ONLY' } : opts, fn);

for (const runner of RUNNERS) {
  const F = (n) => `tests/${n}${EXT[runner]}`;
  describe(`r021b fixes: ${runner}`, () => {
    // -- G1 / G2: Stats objects --------------------------------------------------------------------------------
    t('G1 Object.getOwnPropertyDescriptors(st).size.value', T, () => {
      const dir = fixture(runner, 'descs', {
        'data/blob.bin': 'abc',
        ...tfile(runner, 'descs', "test('descs', () => { expect(Object.getOwnPropertyDescriptors(fs.statSync('data/blob.bin')).size.value).toBe(3); });"),
      });
      noWrongReuse(runner, dir, F('descs'), { 'data/blob.bin': 'abcd' });
    });

    t('G1 Reflect.getOwnPropertyDescriptor(st, "size") from a callback stat', T, () => {
      const dir = fixture(runner, 'rdesc', {
        'data/blob.bin': 'abc',
        ...tfile(runner, 'rdesc', "test('rdesc', async () => { const st = await new Promise((r, j) => fs.stat('data/blob.bin', (e, s) => (e ? j(e) : r(s)))); expect(Reflect.getOwnPropertyDescriptor(st, 'size').value).toBe(3); });"),
      });
      noWrongReuse(runner, dir, F('rdesc'), { 'data/blob.bin': 'abcd' });
    });

    t('G1 util.format("%o") and console.log of a Stats object (inspect paths)', T, () => {
      const dir = fixture(runner, 'fmt', {
        'data/blob.bin': 'abc',
        ...tfile(runner, 'fmt', "test('fmt', async () => { const st = await fs.promises.stat('data/blob.bin'); console.log(st); expect(util.format('%o', st)).toContain('size: 3'); });"),
      });
      noWrongReuse(runner, dir, F('fmt'), { 'data/blob.bin': 'abcd' });
    });

    t('G2 same: a Stats object is a plain fs.Stats (prototype, isProxy, inspect, clone, serialize, descriptors)', T, () => {
      const dir = fixture(runner, 'plain', {
        'data/blob.bin': 'abc',
        ...tfile(runner, 'plain', `test('plain', () => {
  const st = fs.statSync('data/blob.bin');
  expect(Object.getPrototypeOf(st)).toBe(fs.Stats.prototype);
  expect(st instanceof fs.Stats).toBe(true);
  expect(util.types.isProxy(st)).toBe(false);
  expect(st.isFile()).toBe(true);
  const plain = Object.assign(Object.create(fs.Stats.prototype), { ...st });
  expect(util.inspect(st)).toBe(util.inspect(plain));
  expect(util.inspect(st, { showHidden: true })).toBe(util.inspect(plain, { showHidden: true }));
  expect(Object.keys(st)).toEqual(Object.keys(plain));
  expect(Object.getOwnPropertyDescriptor(st, 'size')).toEqual({ value: 3, writable: true, enumerable: true, configurable: true });
  expect(structuredClone(st)).toEqual({ ...plain });
  expect(v8.deserialize(v8.serialize(st))).toEqual({ ...plain });
  st.size = 99;
  expect(st.size).toBe(99);
  expect(Object.getOwnPropertyDescriptor(st, 'size').value).toBe(99);
  const b = fs.statSync('data/blob.bin', { bigint: true });
  expect(typeof b.size).toBe('bigint');
  expect(util.inspect(b)).toContain('size: 3n');
});`),
      });
      sameOutcome(runner, dir);
    });

    t('G1 an mtime read is keyed by its value: utimes changes it', T, () => {
      const dir = fixture(runner, 'mtime', {
        'data/f.txt': 'x',
        ...tfile(runner, 'mt', "test('mt', () => { expect(fs.statSync('data/f.txt').mtimeMs).toBe(1000000000); });"),
      });
      fs.utimesSync(path.join(dir, 'data/f.txt'), 1000000, 1000000);
      noWrongReuse(runner, dir, F('mt'), () => fs.utimesSync(path.join(dir, 'data/f.txt'), 1000000, 2000000));
    });

    t('G1 lstat: the inode of a link (not of its target) is keyed', T, () => {
      const dir = fixture(runner, 'lino', {
        'data/a.txt': 'a', 'data/b.txt': 'b',
        ...tfile(runner, 'lino', "test('lino', () => { expect(fs.lstatSync('data/cur').ino).toBe(Number(fs.readFileSync('ino.txt', 'utf8'))); });"),
      });
      fs.symlinkSync('a.txt', path.join(dir, 'data/cur'));
      fs.writeFileSync(path.join(dir, 'ino.txt'), String(fs.lstatSync(path.join(dir, 'data/cur')).ino));
      noWrongReuse(runner, dir, F('lino'), () => { fs.rmSync(path.join(dir, 'data/cur')); fs.writeFileSync(path.join(dir, 'data/tmp'), ''); fs.symlinkSync('b.txt', path.join(dir, 'data/cur')); });
    });

    t('keeps: isFile() of a Stats object does not make its size an input', T, () => {
      const dir = fixture(runner, 'isfile', {
        'data/blob.bin': 'abc',
        ...tfile(runner, 'isf', "test('isf', () => { expect(fs.statSync('data/blob.bin').isFile()).toBe(true); });"),
      });
      keepsReuse(runner, dir, F('isf'), { 'data/blob.bin': 'abcdef' });
    });

    // -- the environment Proxy (same class of hole) ---------------------------------------------------------------
    t('env: util.inspect(process.env) records the whole environment', T, () => {
      const dir = fixture(runner, 'envinsp', {
        ...tfile(runner, 'ei', "test('ei', () => { expect(util.inspect(process.env)).toContain(\"R021BF_X: 'a'\"); });"),
      });
      noWrongReuse(runner, dir, F('ei'), () => {}, { env1: { R021BF_X: 'a' }, env2: { R021BF_X: 'b' } });
    });

    // -- G3: recursive listings ---------------------------------------------------------------------------------
    t('G3 callback readdir recursive through a link to a directory', T, () => {
      const dir = fixture(runner, 'rcb', {
        'other/x.json': '{}', 'tree/keep.txt': '',
        ...tfile(runner, 'rcb', "test('rcb', async () => { const l = await new Promise((r, j) => fs.readdir('tree', { recursive: true }, (e, x) => (e ? j(e) : r(x)))); expect(l.filter((f) => f.endsWith('.json')).length).toBe(1); });"),
      });
      fs.symlinkSync('../other', path.join(dir, 'tree', 'link'));
      noWrongReuse(runner, dir, F('rcb'), { 'other/y.json': '{}' });
    });

    t('G3 readdirSync recursive withFileTypes through a link to a directory', T, () => {
      const dir = fixture(runner, 'rtyped', {
        'other/x.json': '{}', 'tree/keep.txt': '',
        ...tfile(runner, 'rty', "test('rty', () => { expect(fs.readdirSync('tree', { recursive: true, withFileTypes: true }).filter((d) => d.name.endsWith('.json')).length).toBe(1); });"),
      });
      fs.symlinkSync('../other', path.join(dir, 'tree', 'link'));
      noWrongReuse(runner, dir, F('rty'), { 'other/y.json': '{}' });
    });

    t('G3 a link inside the tree retargeted to another directory', T, () => {
      const dir = fixture(runner, 'rretarget', {
        'one/x.json': '{}', 'two/x.json': '{}', 'two/y.json': '{}', 'tree/keep.txt': '',
        ...tfile(runner, 'rre', "test('rre', () => { expect(fs.readdirSync('tree', { recursive: true }).filter((f) => f.endsWith('.json')).length).toBe(1); });"),
      });
      fs.symlinkSync('../one', path.join(dir, 'tree', 'link'));
      noWrongReuse(runner, dir, F('rre'), () => { fs.rmSync(path.join(dir, 'tree', 'link')); fs.symlinkSync('../two', path.join(dir, 'tree', 'link')); });
    });

    t('G3 a cycle through a link: a new entry below it', T, () => {
      const dir = fixture(runner, 'rcycle', {
        'tree/a/f.txt': '',
        ...tfile(runner, 'rcy', "test('rcy', () => { expect(fs.readdirSync('tree', { recursive: true }).filter((f) => f.endsWith('g.txt')).length).toBe(0); });"),
      });
      fs.symlinkSync('..', path.join(dir, 'tree', 'a', 'up'));
      noWrongReuse(runner, dir, F('rcy'), { 'tree/a/g.txt': '' });
    });

    t('keeps: fs.promises.readdir withFileTypes does not follow links: a file added behind one', T, () => {
      const dir = fixture(runner, 'rnofollow', {
        'other/x.json': '{}', 'tree/keep.txt': '',
        ...tfile(runner, 'rnf', "test('rnf', async () => { expect((await fs.promises.readdir('tree', { recursive: true, withFileTypes: true })).length).toBe(2); });"),
      });
      fs.symlinkSync('../other', path.join(dir, 'tree', 'link'));
      keepsReuse(runner, dir, F('rnf'), { 'other/y.json': '{}' });
    });

    // -- G4: code that runs before the runner -------------------------------------------------------------------
    t('G4 a NODE_OPTIONS --require preload reads a file (main process and workers)', T, () => {
      const dir = fixture(runner, 'nopre', {
        'pre.txt': 'a',
        'pre.cjs': "globalThis.__NOPRE__ = require('node:fs').readFileSync(require('node:path').join(__dirname, 'pre.txt'), 'utf8').trim();\nprocess.env.R021BF_PRE = globalThis.__NOPRE__;\n",
        ...tfile(runner, 'nop', "test('nop', () => { expect(process.env.R021BF_PRE).toBe('a'); });"),
      });
      const env = { NODE_OPTIONS: `--require ${path.join(dir, 'pre.cjs')}` };
      noWrongReuse(runner, dir, F('nop'), { 'pre.txt': 'b' }, { env1: env });
    });

    t('G4 a preload that reads the clock makes the tests not cacheable', T, () => {
      const dir = fixture(runner, 'preclock', {
        'pre.cjs': "process.env.R021BF_T = String(Date.now() % 2 === 0 ? 'even' : 'odd');\n",
        ...tfile(runner, 'pcl', "test('pcl', () => { expect(['even', 'odd']).toContain(process.env.R021BF_T); });"),
      });
      const env = { NODE_OPTIONS: `--require ${path.join(dir, 'pre.cjs')}` };
      const r1 = crun(runner, dir, { env });
      assert.equal(r1.status, 0, show(r1));
      const r2 = crun(runner, dir, { env });
      assert.equal(r2.status, 0, show(r2));
      assert.ok(!reusedFiles(r2).includes(F('pcl')), `a test after a clock read by a preload is not reused\n${show(r2)}`);
    });
  });
}

describe('r021b fixes: vitest only', { skip: !RUNNERS.includes('vitest') }, () => {
  const runner = 'vitest';
  const F = (n) => `tests/${n}.test.mjs`;
  // Jest's test environment has its own copy of process.env (not cloneable, with or without the cache)
  t('env same: structuredClone, isProxy and descriptors of process.env behave as without the cache', T, () => {
    const dir = fixture(runner, 'envsame', {
      ...tfile(runner, 'es', `test('es', () => {
expect(structuredClone(process.env).R021BF_Y).toBe('y');
expect(structuredClone({ e: process.env }).e.R021BF_Y).toBe('y');
expect(util.types.isProxy(process.env)).toBe(false);
expect(Object.getOwnPropertyDescriptor(process.env, 'R021BF_Y').value).toBe('y');
expect(util.inspect(process.env)).toContain("R021BF_Y: 'y'");
});`),
    });
    sameOutcome(runner, dir, { env: { R021BF_Y: 'y' } });
  });

  t('env: structuredClone(process.env) records the whole environment', T, () => {
    const dir = fixture(runner, 'envclone', {
      ...tfile(runner, 'ec', "test('ec', () => { expect(Object.keys(structuredClone(process.env)).filter((k) => k.startsWith('R021BF_')).length).toBe(1); });"),
    });
    noWrongReuse(runner, dir, F('ec'), () => {}, { env1: { R021BF_Z: '1' }, env2: { R021BF_Z: '1', R021BF_W: '2' } });
  });

  t('G4 an execArgv --require (CommonJS) preload reads a file', T, () => {
    const dir = fixture(runner, 'reqpre', {
      'pre.txt': 'a',
      'pre.cjs': "globalThis.__PRE__ = require('node:fs').readFileSync(require('node:path').join(__dirname, 'pre.txt'), 'utf8').trim();\n",
      ...tfile(runner, 'rp', "test('rp', () => { expect(globalThis.__PRE__).toBe('a'); });"),
    }, { vitestTest: { pool: 'forks', execArgv: ['--require', './pre.cjs'] } });
    noWrongReuse(runner, dir, F('rp'), { 'pre.txt': 'b' });
  });

  t('G4 an execArgv --import preload imports a module whose content changes', T, () => {
    const dir = fixture(runner, 'imppre', {
      'lib/val.mjs': 'export default 1;\n',
      'pre.mjs': "import v from './lib/val.mjs';\nglobalThis.__PREV__ = v;\n",
      ...tfile(runner, 'ip', "test('ip', () => { expect(globalThis.__PREV__).toBe(1); });"),
    }, { vitestTest: { pool: 'forks', execArgv: ['--import', './pre.mjs'] } });
    noWrongReuse(runner, dir, F('ip'), { 'lib/val.mjs': 'export default 2;\n' });
  });

  t('G4 a preload with the threads pool (--require in worker threads)', T, () => {
    const dir = fixture(runner, 'thrpre', {
      'pre.txt': 'a',
      'pre.cjs': "globalThis.__TPRE__ = require('node:fs').readFileSync(require('node:path').join(__dirname, 'pre.txt'), 'utf8').trim();\n",
      ...tfile(runner, 'tp', "test('tp', () => { expect(globalThis.__TPRE__).toBe('a'); });"),
    }, { vitestTest: { pool: 'threads', execArgv: ['--require', './pre.cjs'] } });
    noWrongReuse(runner, dir, F('tp'), { 'pre.txt': 'b' });
  });

  t('G4 a custom test environment reads a file in setup (before the runner)', T, () => {
    const dir = fixture(runner, 'customenv', {
      'env.txt': 'a',
      'env/custom.mjs': "import fs from 'node:fs';\nexport default { name: 'custom', viteEnvironment: 'ssr', setup(g) { g.__ENVTXT__ = fs.readFileSync(new URL('../env.txt', import.meta.url), 'utf8').trim(); return { teardown() {} }; } };\n",
      ...tfile(runner, 'ce', "test('ce', () => { expect(globalThis.__ENVTXT__).toBe('a'); });"),
    }, { vitestTest: { environment: './env/custom.mjs' } });
    noWrongReuse(runner, dir, F('ce'), { 'env.txt': 'b' });
  });

  t('G4 a custom test environment (a package) named by a file pragma reads a project file in setup', T, () => {
    const dir = fixture(runner, 'pragmaenv', {
      'env.txt': 'a',
      'node_modules/vitest-environment-custom/package.json': JSON.stringify({ name: 'vitest-environment-custom', version: '1.0.0', type: 'module', main: 'index.js' }),
      'node_modules/vitest-environment-custom/index.js': "import fs from 'node:fs';\nimport path from 'node:path';\nexport default { name: 'custom', viteEnvironment: 'ssr', setup(g) { g.__ENVTXT__ = fs.readFileSync(path.join(process.cwd(), 'env.txt'), 'utf8').trim(); return { teardown() {} }; } };\n",
      'tests/pe.test.mjs': "// @vitest-environment custom\nimport { test, expect } from 'vitest';\ntest('pe', () => { expect(globalThis.__ENVTXT__).toBe('a'); });\n",
    });
    noWrongReuse(runner, dir, F('pe'), { 'env.txt': 'b' });
  });

  t('G4 an execArgv --experimental-loader makes the tests not cacheable', T, () => {
    const dir = fixture(runner, 'loader', {
      'ld.mjs': 'export async function resolve(s, c, n) { return n(s, c); }\n',
      ...tfile(runner, 'ld', "test('ld', () => { expect(1).toBe(1); });"),
    }, { vitestTest: { pool: 'forks', execArgv: ['--experimental-loader', './ld.mjs'] } });
    const r1 = crun(runner, dir);
    assert.equal(r1.status, 0, show(r1));
    const r2 = crun(runner, dir);
    assert.ok(!reusedFiles(r2).includes(F('ld')), `an off-thread loader: not reused\n${show(r2)}`);
  });
});

describe('r021b fixes: jest only', { skip: !RUNNERS.includes('jest') }, () => {
  const runner = 'jest';
  const F = (n) => `tests/${n}.test.js`;
  t('G4 Jest setupFiles reads a file (held before; kept)', T, () => {
    const dir = fixture(runner, 'setupfiles', {
      'sf.txt': 'a',
      'setup.js': "globalThis.__SF__ = require('node:fs').readFileSync(require('node:path').join(__dirname, 'sf.txt'), 'utf8').trim();\n",
      ...tfile(runner, 'sf', "test('sf', () => { expect(globalThis.__SF__).toBe('a'); });"),
    }, { jest: { setupFiles: ['<rootDir>/setup.js'] } });
    noWrongReuse(runner, dir, F('sf'), { 'sf.txt': 'b' });
  });
});
