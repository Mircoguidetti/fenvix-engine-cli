'use strict';
// Review r021 of claude/node-cache-proof: wrong reuses of the cache with proof (`detjs --det --det-cache`).
//
// Tests named F<n> are findings (they fail on claude/node-cache-proof, Node 22.23, Vitest 5.1, Jest 30.5); tests named
// `held:` are attacks that did not get through (they pass there and guard against regressions).
//
// Every test here has the same shape: run 1 records (passes), run 2 reuses every file (the cache works), one input
// of the test changes so that a fresh run FAILS, then run 3 with the cache must not reuse the file: its exit status
// must equal the fresh run's (no cache). On claude/node-cache-proof each of these reuses the stale pass.
const { test, describe, before } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

const T = { timeout: 600000 };
const RUNNERS = (process.env.DETJS_TEST_RUNNERS || 'vitest,jest').split(',');
const EXT = { vitest: '.test.mjs', jest: '.test.js' };
const HEAD = {
  vitest: "import { test, expect, afterAll, vi } from 'vitest'; import fs from 'node:fs'; import path from 'node:path';",
  jest: "const fs = require('node:fs'); const path = require('node:path');",
};

function write(dir, files) {
  for (const [name, body] of Object.entries(files)) {
    const p = path.join(dir, name);
    if (body === null) { fs.rmSync(p, { force: true, recursive: true }); continue; }
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, body);
  }
}

function fixture(runner, name, files, { vitestRaw = '', vitestTop = '', vitestTest = {}, jest = {}, pkg = {} } = {}) {
  const dir = path.join(TMP, 'review-r021', runner, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  write(dir, { 'package.json': JSON.stringify({ name: `r021-${name}`, private: true, ...pkg }) });
  if (runner === 'vitest') {
    const cfg = { include: ['tests/**/*.test.mjs'], ...vitestTest };
    write(dir, { 'vitest.config.mjs': `${vitestRaw}\nexport default { ${vitestTop} test: ${JSON.stringify(cfg)} };\n` });
  } else {
    const cfg = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node', ...jest };
    write(dir, { 'jest.config.js': `module.exports = ${JSON.stringify(cfg)};\n` });
  }
  write(dir, files);
  return dir;
}

function tfile(runner, name, body) {
  return { [`tests/${name}${EXT[runner]}`]: `${HEAD[runner]}\n${body}\n` };
}

function crun(runner, dir, { cache = true } = {}) {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS']) delete env[k];
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

function show(r) {
  return `status=${r.status}\nreused=${JSON.stringify(r.summary && r.summary.reused_files_list)}\nmisses=${JSON.stringify(r.summary && r.summary.misses)}\nstdout=${(r.stdout || '').slice(-1500)}\nstderr=${(r.stderr || '').slice(-1500)}`;
}

const reusedFiles = (r) => ((r.summary && r.summary.reused_files_list) || []).map((f) => f.split('@@')[0]);

/**
 * Record, reuse, change, then the cached run must agree with a fresh run (which fails after the change).
 * `change`: files to write (null removes) or a function.
 */
function noWrongReuse(runner, dir, file, change) {
  const r1 = crun(runner, dir);
  assert.equal(r1.status, 0, `run 1 (record) must pass\n${show(r1)}`);
  const r2 = crun(runner, dir);
  assert.equal(r2.status, 0, `run 2 must pass\n${show(r2)}`);
  assert.ok(reusedFiles(r2).includes(file), `run 2 must reuse ${file} (otherwise this test proves nothing)\n${show(r2)}`);
  if (typeof change === 'function') change(); else write(dir, change);
  // Vitest 5's own module cache (node_modules/.vitest-cache) can serve a stale transform to a fresh run; it is not
  // detjs' decision, so both the fresh and the cached run start without it
  const clearRunnerCache = () => fs.rmSync(path.join(dir, 'node_modules', '.vitest-cache'), { recursive: true, force: true });
  clearRunnerCache();
  const fresh = crun(runner, dir, { cache: false });
  clearRunnerCache();
  assert.notEqual(fresh.status, 0, `the change must make a fresh run fail (test precondition)\n${show(fresh)}`);
  const r3 = crun(runner, dir);
  assert.ok(!reusedFiles(r3).includes(file), `WRONG REUSE: ${file} reused after its input changed; a fresh run fails\n${show(r3)}`);
  assert.equal(r3.status, fresh.status, `cached run must agree with the fresh run\n${show(r3)}`);
}

before(() => fs.mkdirSync(path.join(TMP, 'review-r021'), { recursive: true }));

for (const runner of RUNNERS) {
  const F = (n) => `tests/${n}${EXT[runner]}`;
  describe(`r021 wrong reuse: ${runner}`, () => {
    test('F1a stat() result beyond the kind: a file size read with statSync', T, () => {
      const dir = fixture(runner, 'stat-size', {
        'data/blob.bin': 'abc',
        ...tfile(runner, 'size', "test('size', () => { expect(fs.statSync('data/blob.bin').size).toBe(3); });"),
      });
      noWrongReuse(runner, dir, F('size'), { 'data/blob.bin': 'abcd' });
    });

    test('F1b realpath() of a symbolic link: retargeting the link', T, () => {
      const dir = fixture(runner, 'realpath', {
        'data/one.txt': '1', 'data/two.txt': '2',
        ...tfile(runner, 'real', "test('real', () => { expect(path.basename(fs.realpathSync('data/current'))).toBe('one.txt'); });"),
      });
      fs.symlinkSync('one.txt', path.join(dir, 'data', 'current'));
      noWrongReuse(runner, dir, F('real'), () => {
        fs.rmSync(path.join(dir, 'data', 'current'));
        fs.symlinkSync('two.txt', path.join(dir, 'data', 'current'));
      });
    });

    test('F1c lstat(): a symbolic link replaced by a regular file', T, () => {
      const dir = fixture(runner, 'lstat', {
        'data/target.txt': 't',
        ...tfile(runner, 'lstat', "test('lstat', () => { expect(fs.lstatSync('data/entry').isSymbolicLink()).toBe(true); });"),
      });
      fs.symlinkSync('target.txt', path.join(dir, 'data', 'entry'));
      noWrongReuse(runner, dir, F('lstat'), () => {
        fs.rmSync(path.join(dir, 'data', 'entry'));
        write(dir, { 'data/entry': 't' });
      });
    });

    test('F2a recursive readdir: a new file in a subdirectory', T, () => {
      const dir = fixture(runner, 'readdir-recursive', {
        'fixtures/cases/a/one.json': '{}',
        ...tfile(runner, 'cases', "test('cases', () => { expect(fs.readdirSync('fixtures/cases', { recursive: true }).filter((f) => f.endsWith('.json')).length).toBe(1); });"),
      });
      noWrongReuse(runner, dir, F('cases'), { 'fixtures/cases/a/two.json': '{}' });
    });

    test('F2b readdir withFileTypes: an entry changes from file to directory', T, () => {
      const dir = fixture(runner, 'readdir-types', {
        'fixtures/x/item': 'file',
        ...tfile(runner, 'types', "test('types', () => { expect(fs.readdirSync('fixtures/x', { withFileTypes: true }).filter((e) => e.isFile()).length).toBe(1); });"),
      });
      noWrongReuse(runner, dir, F('types'), () => {
        fs.rmSync(path.join(dir, 'fixtures', 'x', 'item'));
        write(dir, { 'fixtures/x/item/inner': 'now a directory' });
      });
    });

    test('F3a fs.openAsBlob: content read without fs.readFile', T, () => {
      const dir = fixture(runner, 'open-as-blob', {
        'data/msg.txt': 'hello',
        ...tfile(runner, 'blob', "test('blob', async () => { const b = await fs.openAsBlob('data/msg.txt'); expect(await b.text()).toBe('hello'); });"),
      });
      noWrongReuse(runner, dir, F('blob'), { 'data/msg.txt': 'HELLO' });
    });

    test('F3b process.loadEnvFile: an env file outside the root configuration files', { ...T, skip: runner === 'jest' && 'Jest: process.env in a test file is a copy; loadEnvFile writes the real one' }, () => {
      const dir = fixture(runner, 'load-env-file', {
        'tests/fixtures/app.env': 'GREETING=hello\n',
        ...tfile(runner, 'envfile', "test('envfile', () => { process.loadEnvFile('tests/fixtures/app.env'); expect(process.env.GREETING).toBe('hello'); });"),
      });
      noWrongReuse(runner, dir, F('envfile'), { 'tests/fixtures/app.env': 'GREETING=bye\n' });
    });

    test('F4 fs.cpSync of a fixture, then the copy is read', T, () => {
      const dir = fixture(runner, 'cp-fixture', {
        'fixtures/tpl/config.json': '{"v":1}',
        ...tfile(runner, 'cp', [
          "test('cp', () => {",
          "  const dst = path.join('out', String(process.pid)); fs.rmSync(dst, { recursive: true, force: true });",
          "  fs.cpSync('fixtures/tpl', dst, { recursive: true });",
          "  expect(JSON.parse(fs.readFileSync(path.join(dst, 'config.json'), 'utf8')).v).toBe(1);",
          '});'].join('\n')),
      });
      noWrongReuse(runner, dir, F('cp'), { 'fixtures/tpl/config.json': '{"v":2}' });
    });

    test('held: a file read in afterAll (after the last test ended)', T, () => {
      const hook = runner === 'vitest' ? 'afterAll' : 'afterAll';
      const dir = fixture(runner, 'after-all', {
        'data/expected.txt': 'ok',
        ...tfile(runner, 'after', [
          "test('t', () => { expect(1).toBe(1); });",
          `${hook}(() => { if (fs.readFileSync('data/expected.txt', 'utf8') !== 'ok') throw new Error('teardown check failed'); });`].join('\n')),
      });
      noWrongReuse(runner, dir, F('after'), { 'data/expected.txt': 'changed' });
    });

    test('F8 a directory outside the project listed asynchronously by a glob library', T, () => {
      const outside = path.join(TMP, 'review-r021', 'outside-' + runner);
      fs.rmSync(outside, { recursive: true, force: true });
      write(outside, { 'one.txt': '1' });
      const imp = runner === 'vitest' ? "import { glob } from 'tinyglobby';" : "const { glob } = require('tinyglobby');";
      const dir = fixture(runner, 'outside-glob', {
        ...tfile(runner, 'outside', `${imp}\ntest('outside', async () => { expect((await glob(['*.txt'], { cwd: ${JSON.stringify(outside)} })).length).toBe(1); });`),
      });
      noWrongReuse(runner, dir, F('outside'), () => write(outside, { 'two.txt': '2' }));
    });

    test('held: fs.globSync: a new file matching the pattern', T, () => {
      const dir = fixture(runner, 'fs-glob', {
        'fixtures/g/one.json': '{}',
        ...tfile(runner, 'fglob', "test('fglob', () => { expect(fs.globSync('fixtures/g/*.json').length).toBe(1); });"),
      });
      noWrongReuse(runner, dir, F('fglob'), { 'fixtures/g/two.json': '{}' });
    });

    test('F3c node:sqlite opens a database file of the project', T, () => {
      const dir = fixture(runner, 'sqlite', {
        ...tfile(runner, 'db', [
          runner === 'vitest' ? "import { DatabaseSync } from 'node:sqlite';" : "const { DatabaseSync } = require('node:sqlite');",
          "test('db', () => { const db = new DatabaseSync('fixtures/data.db', { readOnly: true }); const n = db.prepare('select count(*) as n from t').get().n; db.close(); expect(n).toBe(1); });"].join('\n')),
      });
      const mk = (rows) => {
        const { DatabaseSync } = require('node:sqlite');
        const f = path.join(dir, 'fixtures', 'data.db');
        fs.mkdirSync(path.dirname(f), { recursive: true });
        fs.rmSync(f, { force: true });
        const db = new DatabaseSync(f);
        db.exec('create table t (x)');
        for (let i = 0; i < rows; i++) db.exec(`insert into t values (${i})`);
        db.close();
      };
      mk(1);
      noWrongReuse(runner, dir, F('db'), () => mk(2));
    });

    test('F5 an optional module loaded with a caught dynamic import: the module appears', T, () => {
      const body = runner === 'vitest'
        ? "test('opt', async () => { let v = 'none'; try { v = (await import('../src/optional.mjs')).v; } catch {} expect(v).toBe('none'); });"
        : "test('opt', () => { let v = 'none'; try { v = require('../src/optional.js').v; } catch {} expect(v).toBe('none'); });";
      const dir = fixture(runner, 'optional-import', { 'src/.keep': '', ...tfile(runner, 'opt', body) });
      noWrongReuse(runner, dir, F('opt'), runner === 'vitest' ? { 'src/optional.mjs': "export const v = 'here';\n" } : { 'src/optional.js': "module.exports.v = 'here';\n" });
    });
  });
}

describe('r021 wrong reuse: Vitest specific', () => {
  const runner = 'vitest';
  const F = (n) => `tests/${n}.test.mjs`;

  test('F6 import.meta.glob: a new file matching the glob', T, () => {
    const dir = fixture(runner, 'import-meta-glob', {
      'fixtures/cases/one.json': '{"n":1}',
      ...tfile(runner, 'glob', "const cases = import.meta.glob('../fixtures/cases/*.json', { eager: true });\ntest('glob', () => { expect(Object.keys(cases).length).toBe(1); });"),
    });
    noWrongReuse(runner, dir, F('glob'), { 'fixtures/cases/two.json': '{"n":2}' });
  });

  test('F7a vi.mock automock: a __mocks__ file added next to the mocked module', T, () => {
    const dir = fixture(runner, 'vi-mocks-dir', {
      'src/dep.mjs': 'export const v = () => 1;\n',
      ...tfile(runner, 'mocked', "import { v } from '../src/dep.mjs';\nvi.mock('../src/dep.mjs');\ntest('mocked', () => { expect(v()).toBe(undefined); });"),
    });
    noWrongReuse(runner, dir, F('mocked'), { 'src/__mocks__/dep.mjs': 'export const v = () => 42;\n' });
  });
});

describe('r021 wrong reuse: Vitest transforms and environment', () => {
  const runner = 'vitest';
  const F = (n) => `tests/${n}.test.mjs`;

  test('held: a Vite plugin from a workspace package linked into node_modules: its transform changes', T, () => {
    const plugin = (n) => `export default function answer() { return { name: 'answer', transform(code, id) { return id.endsWith('.test.mjs') ? code.replaceAll('__ANSWER__', '${n}') : null; } }; }\n`;
    const dir = fixture(runner, 'linked-plugin', {
      'packages/vite-plugin-answer/package.json': JSON.stringify({ name: 'vite-plugin-answer', type: 'module', main: 'index.mjs' }),
      'packages/vite-plugin-answer/index.mjs': plugin(1),
      ...tfile(runner, 'answer', "test('answer', () => { expect(__ANSWER__).toBe(1); });"),
    }, { vitestRaw: "import answer from 'vite-plugin-answer';", vitestTop: 'plugins: [answer()],' });
    fs.mkdirSync(path.join(dir, 'node_modules'), { recursive: true });
    fs.symlinkSync('../packages/vite-plugin-answer', path.join(dir, 'node_modules', 'vite-plugin-answer'));
    noWrongReuse(runner, dir, F('answer'), { 'packages/vite-plugin-answer/index.mjs': plugin(2) });
  });

  test('held: import.meta.env from an envDir below the root', T, () => {
    const dir = fixture(runner, 'env-dir', {
      'config/env/.env': 'VITE_GREETING=hello\n',
      ...tfile(runner, 'menv', "test('menv', () => { expect(import.meta.env.VITE_GREETING).toBe('hello'); });"),
    }, { vitestTop: "envDir: 'config/env'," });
    noWrongReuse(runner, dir, F('menv'), { 'config/env/.env': 'VITE_GREETING=bye\n' });
  });
});

describe('r021 wrong reuse: Jest specific', () => {
  const runner = 'jest';
  const F = (n) => `tests/${n}.test.js`;

  test('held: jest.mock automock: a __mocks__ file added next to the mocked module', T, () => {
    const dir = fixture(runner, 'jest-mocks-dir', {
      'src/dep.js': 'module.exports.v = () => 1;\n',
      ...tfile(runner, 'mocked', "jest.mock('../src/dep.js');\nconst { v } = require('../src/dep.js');\ntest('mocked', () => { expect(v()).toBe(undefined); });"),
    });
    noWrongReuse(runner, dir, F('mocked'), { 'src/__mocks__/dep.js': 'module.exports.v = () => 42;\n' });
  });

  test('held: an environment variable read by an installed library in a promise callback', T, () => {
    const dir = fixture(runner, 'lib-async-env', {
      'node_modules/lazy-flag/package.json': '{"name":"lazy-flag","main":"index.js"}',
      'node_modules/lazy-flag/index.js': 'module.exports = () => Promise.resolve().then(() => process.env.R021_FLAG || "off");\n',
      ...tfile(runner, 'flag', "const flag = require('lazy-flag');\ntest('flag', async () => { expect(await flag()).toBe('off'); });"),
    });
    const prev = process.env.R021_FLAG;
    try {
      noWrongReuse(runner, dir, F('flag'), () => { process.env.R021_FLAG = 'on'; });
    } finally {
      if (prev === undefined) delete process.env.R021_FLAG; else process.env.R021_FLAG = prev;
    }
  });

  test('F7b root __mocks__ for an installed package is applied without jest.mock', T, () => {
    const dir = fixture(runner, 'jest-node-module-mock', {
      'node_modules/leftpad-x/package.json': '{"name":"leftpad-x","main":"index.js"}',
      'node_modules/leftpad-x/index.js': 'module.exports = () => "real";\n',
      ...tfile(runner, 'pkg', "const lp = require('leftpad-x');\ntest('pkg', () => { expect(lp()).toBe('real'); });"),
    }, { jest: { roots: ['<rootDir>'] } });
    noWrongReuse(runner, dir, F('pkg'), { '__mocks__/leftpad-x.js': 'module.exports = () => "mock";\n' });
  });
});
