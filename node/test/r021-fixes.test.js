'use strict';
// Fixes of review r021 beyond the reviewer's own cases: the reverse directions and neighbours of each hole.
// Same shape as test/review-r021.test.js: record, reuse, change one input so a fresh run fails, then the cached run
// must not reuse the file. `notCached` cases: the input cannot be keyed, so the file is never reused.
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
  vitest: "import { test, expect } from 'vitest'; import fs from 'node:fs'; import path from 'node:path';",
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

function fixture(runner, name, files, { vitestRaw = '', vitestTop = '' } = {}) {
  const dir = path.join(TMP, 'r021-fixes', runner, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  write(dir, { 'package.json': JSON.stringify({ name: `r021f-${name}`, private: true }) });
  if (runner === 'vitest') {
    write(dir, { 'vitest.config.mjs': `${vitestRaw}\nexport default { ${vitestTop} test: ${JSON.stringify({ include: ['tests/**/*.test.mjs'] })} };\n` });
  } else {
    write(dir, { 'jest.config.js': `module.exports = ${JSON.stringify({ testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node' })};\n` });
  }
  write(dir, files);
  return dir;
}

const tfile = (runner, name, body) => ({ [`tests/${name}${EXT[runner]}`]: `${HEAD[runner]}\n${body}\n` });

function crun(runner, dir, { cache = true } = {}) {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS']) delete env[k];
  const out = path.join(dir, '.detjs', 'out.json');
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

const show = (r) => `status=${r.status}\nsummary=${JSON.stringify(r.summary && { reused: r.summary.reused_files_list, misses: r.summary.misses, nc: r.summary.not_cached_detail })}\nstdout=${(r.stdout || '').slice(-1200)}\nstderr=${(r.stderr || '').slice(-1200)}`;
const reused = (r) => ((r.summary && r.summary.reused_files_list) || []).map((f) => f.split('@@')[0]);

function noWrongReuse(runner, dir, file, change) {
  const r1 = crun(runner, dir);
  assert.equal(r1.status, 0, `run 1 must pass\n${show(r1)}`);
  const r2 = crun(runner, dir);
  assert.ok(reused(r2).includes(file), `run 2 must reuse ${file}\n${show(r2)}`);
  if (typeof change === 'function') change(); else write(dir, change);
  const clear = () => fs.rmSync(path.join(dir, 'node_modules', '.vitest-cache'), { recursive: true, force: true });
  clear();
  const fresh = crun(runner, dir, { cache: false });
  clear();
  assert.notEqual(fresh.status, 0, `the change must make a fresh run fail\n${show(fresh)}`);
  const r3 = crun(runner, dir);
  assert.ok(!reused(r3).includes(file), `WRONG REUSE of ${file}\n${show(r3)}`);
  assert.equal(r3.status, fresh.status);
}

function notCached(runner, dir, file, why) {
  const r1 = crun(runner, dir);
  assert.equal(r1.status, 0, `run 1 must pass\n${show(r1)}`);
  const r2 = crun(runner, dir);
  assert.equal(r2.status, 0, show(r2));
  assert.ok(!reused(r2).includes(file), `${file} must not be reused\n${show(r2)}`);
  const detail = JSON.stringify(r1.summary && r1.summary.not_cached_detail);
  assert.ok(detail.includes(why), `not cached because of ${why}\n${show(r1)}`);
}

before(() => fs.mkdirSync(path.join(TMP, 'r021-fixes'), { recursive: true }));

for (const runner of RUNNERS) {
  const F = (n) => `tests/${n}${EXT[runner]}`;
  describe(`r021 fixes: ${runner}`, () => {
    test('lstat(): a regular file replaced by a link to a file (the kind following links stays "file")', T, () => {
      const dir = fixture(runner, 'lstat-file-to-link', {
        'data/target.txt': 't', 'data/entry': 't',
        ...tfile(runner, 'lstat', "test('lstat', () => { expect(fs.lstatSync('data/entry').isSymbolicLink()).toBe(false); });"),
      });
      noWrongReuse(runner, dir, F('lstat'), () => {
        fs.rmSync(path.join(dir, 'data', 'entry'));
        fs.symlinkSync('target.txt', path.join(dir, 'data', 'entry'));
      });
    });

    test('stat() mode: a file made executable', T, () => {
      const dir = fixture(runner, 'stat-mode', {
        'bin/tool': '#!/bin/sh\n',
        ...tfile(runner, 'mode', "test('mode', () => { expect(fs.statSync('bin/tool').mode & 0o111).toBe(0); });"),
      });
      fs.chmodSync(path.join(dir, 'bin', 'tool'), 0o644);
      noWrongReuse(runner, dir, F('mode'), () => fs.chmodSync(path.join(dir, 'bin', 'tool'), 0o755));
    });

    test('stat() async (promises): size', T, () => {
      const dir = fixture(runner, 'stat-async', {
        'data/blob.bin': 'abc',
        ...tfile(runner, 'asize', "test('asize', async () => { expect((await fs.promises.stat('data/blob.bin')).size).toBe(3); });"),
      });
      noWrongReuse(runner, dir, F('asize'), { 'data/blob.bin': 'abcd' });
    });

    test('stat() mtime read by the test: not cacheable', T, () => {
      const dir = fixture(runner, 'stat-mtime', {
        'data/a.txt': 'a',
        ...tfile(runner, 'mtime', "test('mtime', () => { expect(fs.statSync('data/a.txt').mtimeMs > 0).toBe(true); });"),
      });
      notCached(runner, dir, F('mtime'), 'mtimeMs');
    });

    test('readdir recursive with file types: an entry type changes deep below', T, () => {
      const dir = fixture(runner, 'readdir-rec-types', {
        'fixtures/t/a/item': 'file',
        ...tfile(runner, 'rtypes', "test('rtypes', () => { expect(fs.readdirSync('fixtures/t', { recursive: true, withFileTypes: true }).filter((e) => e.isFile()).length).toBe(1); });"),
      });
      noWrongReuse(runner, dir, F('rtypes'), () => {
        fs.rmSync(path.join(dir, 'fixtures', 't', 'a', 'item'));
        fs.mkdirSync(path.join(dir, 'fixtures', 't', 'a', 'item'));
      });
    });

    test('opendir: an entry changes from file to directory', T, () => {
      const dir = fixture(runner, 'opendir-types', {
        'fixtures/o/item': 'file',
        ...tfile(runner, 'odir', "test('odir', () => { const d = fs.opendirSync('fixtures/o'); let n = 0; let e; while ((e = d.readSync())) if (e.isFile()) n++; d.closeSync(); expect(n).toBe(1); });"),
      });
      noWrongReuse(runner, dir, F('odir'), () => {
        fs.rmSync(path.join(dir, 'fixtures', 'o', 'item'));
        fs.mkdirSync(path.join(dir, 'fixtures', 'o', 'item'));
      });
    });

    test('fs.promises.cp of a fixture tree, then the copy is read', T, () => {
      const dir = fixture(runner, 'cp-async', {
        'fixtures/tpl/deep/config.json': '{"v":1}',
        ...tfile(runner, 'acp', [
          "test('acp', async () => {",
          "  const dst = path.join('out', 'a' + String(process.pid)); fs.rmSync(dst, { recursive: true, force: true });",
          "  await fs.promises.cp('fixtures/tpl', dst, { recursive: true });",
          "  expect(JSON.parse(fs.readFileSync(path.join(dst, 'deep', 'config.json'), 'utf8')).v).toBe(1);",
          '});'].join('\n')),
      });
      noWrongReuse(runner, dir, F('acp'), { 'fixtures/tpl/deep/config.json': '{"v":2}' });
    });

    test('node:sqlite read-only database: keyed by content (reused, then rerun on change)', T, () => {
      const dir = fixture(runner, 'sqlite-ro', {
        ...tfile(runner, 'rodb', [
          runner === 'vitest' ? "import { DatabaseSync } from 'node:sqlite';" : "const { DatabaseSync } = require('node:sqlite');",
          "test('rodb', () => { const db = new DatabaseSync('fixtures/r.db', { readOnly: true }); const n = db.prepare('select count(*) as n from t').get().n; db.close(); expect(n).toBe(1); });"].join('\n')),
      });
      const mk = (rows) => {
        const { DatabaseSync } = require('node:sqlite');
        const f = path.join(dir, 'fixtures', 'r.db');
        fs.mkdirSync(path.dirname(f), { recursive: true });
        fs.rmSync(f, { force: true });
        const db = new DatabaseSync(f);
        db.exec('create table t (x)');
        for (let i = 0; i < rows; i++) db.exec(`insert into t values (${i})`);
        db.close();
      };
      mk(1);
      noWrongReuse(runner, dir, F('rodb'), () => mk(2));
    });

    test('a bare optional module that cannot be resolved from project code: not cacheable', T, () => {
      const body = runner === 'vitest'
        ? "test('bare', async () => { let v = 'none'; try { v = (await import('r021-not-installed')).v; } catch {} expect(v).toBe('none'); });"
        : "test('bare', () => { let v = 'none'; try { v = require('r021-not-installed').v; } catch {} expect(v).toBe('none'); });";
      const dir = fixture(runner, 'bare-optional', tfile(runner, 'bare', body));
      notCached(runner, dir, F('bare'), 'r021-not-installed');
    });

    test('an optional module next to the test, imported without its extension', T, () => {
      const body = runner === 'vitest'
        ? "test('noext', async () => { let v = 'none'; try { v = (await import('./helper')).v; } catch {} expect(v).toBe('none'); });"
        : "test('noext', () => { let v = 'none'; try { v = require('./helper').v; } catch {} expect(v).toBe('none'); });";
      const dir = fixture(runner, 'optional-noext', tfile(runner, 'noext', body));
      noWrongReuse(runner, dir, F('noext'), runner === 'vitest' ? { 'tests/helper.mjs': "export const v = 'here';\n" } : { 'tests/helper.js': "module.exports.v = 'here';\n" });
    });
  });
}

describe('r021 fixes: Vitest specific', () => {
  const runner = 'vitest';
  const F = (n) => `tests/${n}.test.mjs`;

  test('import.meta.glob with ** : a new file two levels below the base', T, () => {
    const dir = fixture(runner, 'import-meta-glob-deep', {
      'fixtures/cases/a/one.json': '{"n":1}',
      ...tfile(runner, 'dglob', "const cases = import.meta.glob('../fixtures/cases/**/*.json', { eager: true });\ntest('dglob', () => { expect(Object.keys(cases).length).toBe(1); });"),
    });
    noWrongReuse(runner, dir, F('dglob'), { 'fixtures/cases/a/b/two.json': '{"n":2}' });
  });

  test('import.meta.glob through an alias (resolved by the Vite configuration): not cacheable', T, () => {
    const dir = fixture(runner, 'import-meta-glob-alias', {
      'fixtures/cases/one.json': '{"n":1}',
      ...tfile(runner, 'xglob', "const cases = import.meta.glob('@fx/*.json', { eager: true });\ntest('xglob', () => { expect(Object.keys(cases).length).toBe(1); });"),
    }, { vitestTop: "resolve: { alias: { '@fx': new URL('./fixtures/cases', import.meta.url).pathname } }," });
    notCached(runner, dir, F('xglob'), 'import.meta.glob');
  });

  test('vi.mock of an installed package with a root __mocks__ file added', T, () => {
    const dir = fixture(runner, 'vi-root-mocks', {
      'node_modules/leftpad-y/package.json': '{"name":"leftpad-y","main":"index.js"}',
      'node_modules/leftpad-y/index.js': 'module.exports = () => "real";\n',
      ...tfile(runner, 'rmock', "import { vi } from 'vitest';\nimport lp from 'leftpad-y';\nvi.mock('leftpad-y');\ntest('rmock', () => { expect(lp()).toBe(undefined); });"),
    });
    noWrongReuse(runner, dir, F('rmock'), { '__mocks__/leftpad-y.js': 'module.exports = () => "mock";\n' });
  });

  test('a third-party Vite plugin whose transform lists a project directory', T, () => {
    const plugin = [
      "import fs from 'node:fs'; import path from 'node:path';",
      "export default function count() { return { name: 'count', transform(code, id) {",
      "  if (!id.endsWith('.test.mjs')) return null;",
      "  const n = fs.readdirSync(path.join(process.cwd(), 'content')).length;",
      "  return code.replaceAll('__COUNT__', String(n)); } }; }",
    ].join('\n');
    const dir = fixture(runner, 'plugin-listing', {
      'node_modules/vite-plugin-count/package.json': JSON.stringify({ name: 'vite-plugin-count', type: 'module', main: 'index.mjs' }),
      'node_modules/vite-plugin-count/index.mjs': plugin,
      'content/one.md': '# one',
      ...tfile(runner, 'count', "test('count', () => { expect(__COUNT__).toBe(1); });"),
    }, { vitestRaw: "import count from 'vite-plugin-count';", vitestTop: 'plugins: [count()],' });
    noWrongReuse(runner, dir, F('count'), { 'content/two.md': '# two' });
  });
});
