'use strict';
// Review r021b (last round) of claude/node-cache-proof after the r021 fixes. Same shape as review-r021.test.js:
// record (pass), reuse (the file must be reused), change one input so that a fresh run fails, then the cached run
// must not reuse the file and must agree with the fresh run. Tests named `G<n>` fail on claude/node-cache-proof
// (ea5bba6); `held:` attacks did not get through; `held (not cacheable):` were refused reuse, which is sound.
// Run: cd node && node --test --test-concurrency=1 test/review-r021b.test.js (R021B_ONLY=<regex> for a subset).
const { test, describe, before } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

const T = { timeout: 600000 };
const RUNNERS = (process.env.DETJS_TEST_RUNNERS || 'vitest,jest').split(',');
const ONLY = process.env.R021B_ONLY ? new RegExp(process.env.R021B_ONLY) : null;
const EXT = { vitest: '.test.mjs', jest: '.test.js' };
const HEAD = {
  vitest: "import { test, expect, vi } from 'vitest'; import fs from 'node:fs'; import path from 'node:path'; import util from 'node:util';",
  jest: "const fs = require('node:fs'); const path = require('node:path'); const util = require('node:util');",
};

function write(dir, files) {
  for (const [name, body] of Object.entries(files)) {
    const p = path.join(dir, name);
    if (body === null) { fs.rmSync(p, { force: true, recursive: true }); continue; }
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, body);
  }
}

function fixture(runner, name, files, { vitestRaw = '', vitestTop = '', vitestTest = {}, jest = {}, jestRaw = null, pkg = {} } = {}) {
  const dir = path.join(TMP, 'review-r021b', runner, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  write(dir, { 'package.json': JSON.stringify({ name: `r021b-${name}`, private: true, ...pkg }) });
  if (runner === 'vitest') {
    const cfg = { include: ['tests/**/*.test.mjs'], ...vitestTest };
    write(dir, { 'vitest.config.mjs': `${vitestRaw}\nexport default { ${vitestTop} test: ${JSON.stringify(cfg)} };\n` });
  } else {
    const cfg = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node', ...jest };
    write(dir, { 'jest.config.js': jestRaw || `module.exports = ${JSON.stringify(cfg)};\n` });
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

const show = (r) => `status=${r.status}\nreused=${JSON.stringify(r.summary && r.summary.reused_files_list)}\nmisses=${JSON.stringify(r.summary && r.summary.misses)}\nstdout=${(r.stdout || '').slice(-1500)}\nstderr=${(r.stderr || '').slice(-1500)}`;
const reusedFiles = (r) => ((r.summary && r.summary.reused_files_list) || []).map((f) => f.split('@@')[0]);

/** `env1`: environment of runs 1-2; `env2`: of the fresh and the cached run after the change. */
function noWrongReuse(runner, dir, file, change, { env1 = {}, env2 = env1, mayRefuse = false } = {}) {
  const r1 = crun(runner, dir, { env: env1 });
  assert.equal(r1.status, 0, `run 1 (record) must pass\n${show(r1)}`);
  const r2 = crun(runner, dir, { env: env1 });
  assert.equal(r2.status, 0, `run 2 must pass\n${show(r2)}`);
  // mayRefuse: not reusing at all (not cacheable) is a sound answer to this attack
  if (mayRefuse && !reusedFiles(r2).includes(file)) return;
  assert.ok(reusedFiles(r2).includes(file), `run 2 must reuse ${file} (otherwise this test proves nothing)\n${show(r2)}`);
  if (typeof change === 'function') change(); else write(dir, change);
  const clearRunnerCache = () => fs.rmSync(path.join(dir, 'node_modules', '.vitest-cache'), { recursive: true, force: true });
  clearRunnerCache();
  const fresh = crun(runner, dir, { cache: false, env: env2 });
  clearRunnerCache();
  assert.notEqual(fresh.status, 0, `the change must make a fresh run fail (test precondition)\n${show(fresh)}`);
  const r3 = crun(runner, dir, { env: env2 });
  assert.ok(!reusedFiles(r3).includes(file), `WRONG REUSE: ${file} reused after its input changed; a fresh run fails\n${show(r3)}`);
  assert.equal(r3.status, fresh.status, `cached run must agree with the fresh run\n${show(r3)}`);
}

before(() => fs.mkdirSync(path.join(TMP, 'review-r021b'), { recursive: true }));
const t = (name, opts, fn) => test(name, ONLY && !ONLY.test(name) ? { ...opts, skip: 'R021B_ONLY' } : opts, fn);

for (const runner of RUNNERS) {
  const F = (n) => `tests/${n}${EXT[runner]}`;
  describe(`r021b: ${runner}`, () => {
    t('held: Stats field read by the expect matcher: toMatchObject({ size })', T, () => {
      const dir = fixture(runner, 'stat-match', {
        'data/blob.bin': 'abc',
        ...tfile(runner, 'smatch', "test('smatch', () => { expect(fs.statSync('data/blob.bin')).toMatchObject({ size: 3 }); });"),
      });
      noWrongReuse(runner, dir, F('smatch'), { 'data/blob.bin': 'abcd' });
    });

    t('G1a Stats field read through a property descriptor', T, () => {
      const dir = fixture(runner, 'stat-desc', {
        'data/blob.bin': 'abc',
        ...tfile(runner, 'sdesc', "test('sdesc', () => { expect(Object.getOwnPropertyDescriptor(fs.statSync('data/blob.bin'), 'size').value).toBe(3); });"),
      });
      noWrongReuse(runner, dir, F('sdesc'), { 'data/blob.bin': 'abcd' });
    });

    t('G1b Stats fields read by util.inspect', T, () => {
      const dir = fixture(runner, 'stat-inspect', {
        'data/blob.bin': 'abc',
        ...tfile(runner, 'sinsp', "test('sinsp', () => { expect(util.inspect(fs.statSync('data/blob.bin'))).toContain('size: 3,'); });"),
      });
      noWrongReuse(runner, dir, F('sinsp'), { 'data/blob.bin': 'abcd' });
    });

    t('held (not cacheable): Stats spread and JSON.stringify', T, () => {
      const dir = fixture(runner, 'stat-spread', {
        'data/blob.bin': 'abc',
        ...tfile(runner, 'sspread', "test('sspread', () => { const { size } = { ...fs.statSync('data/blob.bin') }; expect(size).toBe(3); expect(JSON.parse(JSON.stringify(fs.statSync('data/blob.bin'))).size).toBe(3); });"),
      });
      noWrongReuse(runner, dir, F('sspread'), { 'data/blob.bin': 'abcd' }, { mayRefuse: true });
    });

    t('held: FileHandle: fs.promises.open then stat().size and readFile', T, () => {
      const dir = fixture(runner, 'fh', {
        'data/blob.bin': 'abc',
        ...tfile(runner, 'fh', "test('fh', async () => { const h = await fs.promises.open('data/blob.bin'); const s = (await h.stat()).size; const c = String(await h.readFile()); await h.close(); expect([s, c]).toEqual([3, 'abc']); });"),
      });
      noWrongReuse(runner, dir, F('fh'), { 'data/blob.bin': 'abcd' });
    });

    t('held: fstat on the descriptor of a read stream', T, () => {
      const dir = fixture(runner, 'stream-fstat', {
        'data/blob.bin': 'abc',
        ...tfile(runner, 'sfst', "test('sfst', async () => { const s = fs.createReadStream('data/blob.bin', { start: 0, end: 0 }); const fd = await new Promise((r) => s.on('open', r)); const n = fs.fstatSync(fd).size; s.destroy(); expect(n).toBe(3); });"),
      });
      noWrongReuse(runner, dir, F('sfst'), { 'data/blob.bin': 'abcd' });
    });


    t('G3a recursive readdir follows a link to a directory outside the listed tree: a new file there', T, () => {
      const dir = fixture(runner, 'rlink', {
        'other/x.json': '{}', 'tree/keep.txt': '',
        ...tfile(runner, 'rl', "test('rl', () => { expect(fs.readdirSync('tree', { recursive: true }).filter((f) => f.endsWith('.json')).length).toBe(1); });"),
      });
      fs.symlinkSync('../other', path.join(dir, 'tree', 'link'));
      noWrongReuse(runner, dir, F('rl'), { 'other/y.json': '{}' });
    });

    t('G3b fs.promises.readdir recursive through a link to a directory', T, () => {
      const dir = fixture(runner, 'rlinkp', {
        'other/x.json': '{}', 'tree/keep.txt': '',
        ...tfile(runner, 'rlp', "test('rlp', async () => { expect((await fs.promises.readdir('tree', { recursive: true })).filter((f) => f.endsWith('.json')).length).toBe(1); });"),
      });
      fs.symlinkSync('../other', path.join(dir, 'tree', 'link'));
      noWrongReuse(runner, dir, F('rlp'), { 'other/y.json': '{}' });
    });

    t('G2 structuredClone of a Stats object behaves as without the cache', T, () => {
      const dir = fixture(runner, 'sclone', {
        'data/blob.bin': 'abc',
        ...tfile(runner, 'scl', "test('scl', () => { expect(structuredClone(fs.statSync('data/blob.bin')).size).toBe(3); });"),
      });
      const plain = crun(runner, dir, { cache: false });
      assert.equal(plain.status, 0, `without the cache the test passes\n${show(plain)}`);
      const cached = crun(runner, dir);
      assert.equal(cached.status, 0, `with the cache (capture run) the outcome must be the same\n${show(cached)}`);
    });

    t('held: globalSetup lists a directory outside the project with an async glob library', T, () => {
      const outside = path.join(TMP, 'review-r021b', `${runner}-outside-gs`);
      fs.rmSync(outside, { recursive: true, force: true });
      fs.mkdirSync(outside, { recursive: true });
      fs.writeFileSync(path.join(outside, 'one.txt'), '1');
      const gs = runner === 'vitest'
        ? `import { glob } from 'tinyglobby';\nexport default async function () { process.env.R021B_N = String((await glob(['*.txt'], { cwd: ${JSON.stringify(outside)} })).length); }\n`
        : `const { glob } = require('tinyglobby');\nmodule.exports = async () => { process.env.R021B_N = String((await glob(['*.txt'], { cwd: ${JSON.stringify(outside)} })).length); };\n`;
      const dir = fixture(runner, 'gsoutside', {
        [runner === 'vitest' ? 'setup/global.mjs' : 'setup/global.js']: gs,
        ...tfile(runner, 'gso', "test('gso', () => { expect(process.env.R021B_N).toBe('1'); });"),
      }, { vitestTest: { globalSetup: ['setup/global.mjs'] }, jest: { globalSetup: '<rootDir>/setup/global.js' } });
      noWrongReuse(runner, dir, F('gso'), () => fs.writeFileSync(path.join(outside, 'two.txt'), '2'));
    });

    t('held (not cacheable): cpSync of a tree that holds a symbolic link loop, then the copy is read', T, () => {
      const dir = fixture(runner, 'cploop', {
        'fixtures/tpl/config.json': '{"v":1}',
        ...tfile(runner, 'cpl', "test('cpl', () => { const d = path.join('out', String(process.pid)); fs.cpSync('fixtures/tpl', d, { recursive: true }); expect(JSON.parse(fs.readFileSync(path.join(d, 'config.json'), 'utf8')).v).toBe(1); });"),
      });
      fs.symlinkSync('..', path.join(dir, 'fixtures', 'tpl', 'loop'));
      noWrongReuse(runner, dir, F('cpl'), { 'fixtures/tpl/config.json': '{"v":2}' }, { mayRefuse: true });
    });

    t('held: snapshot file edited (__snapshots__)', T, () => {
      const snap = runner === 'vitest'
        ? '// Vitest Snapshot v1, https://vitest.dev/guide/snapshot.html\n\nexports[`snap 1`] = `"abc"`;\n'
        : '// Jest Snapshot v1, https://jestjs.io/docs/snapshot-testing\n\nexports[`snap 1`] = `"abc"`;\n';
      const dir = fixture(runner, 'snap', {
        [`tests/__snapshots__/snap${EXT[runner]}.snap`]: snap,
        ...tfile(runner, 'snap', "test('snap', () => { expect('abc').toMatchSnapshot(); });"),
      });
      noWrongReuse(runner, dir, F('snap'), { [`tests/__snapshots__/snap${EXT[runner]}.snap`]: snap.replace('"abc"', '"abd"') });
    });

    t('held: a test-config value read from a file by a dynamic config', T, () => {
      const raw = runner === 'vitest'
        ? null
        : "const fs = require('node:fs');\nmodule.exports = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node', globals: { MODE: fs.readFileSync(__dirname + '/mode.txt', 'utf8').trim() } };\n";
      const dir = fixture(runner, 'dyncfg', {
        'mode.txt': 'a',
        ...(runner === 'vitest' ? { 'vitest.config.mjs': "import fs from 'node:fs';\nexport default { define: { __MODE__: JSON.stringify(fs.readFileSync(new URL('./mode.txt', import.meta.url), 'utf8').trim()) }, test: { include: ['tests/**/*.test.mjs'] } };\n" } : {}),
        ...tfile(runner, 'dcfg', runner === 'vitest' ? "test('dcfg', () => { expect(__MODE__).toBe('a'); });" : "test('dcfg', () => { expect(globalThis.MODE).toBe('a'); });"),
      }, { jestRaw: raw });
      noWrongReuse(runner, dir, F('dcfg'), { 'mode.txt': 'b' });
    });

    t('held: a test-config value from an environment variable read by a dynamic config', T, () => {
      const raw = runner === 'vitest' ? null
        : "module.exports = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node', globals: { MODE: process.env.R021B_MODE || 'a' } };\n";
      const dir = fixture(runner, 'envcfg', {
        ...(runner === 'vitest' ? { 'vitest.config.mjs': "export default { define: { __MODE__: JSON.stringify(process.env.R021B_MODE || 'a') }, test: { include: ['tests/**/*.test.mjs'] } };\n" } : {}),
        ...tfile(runner, 'ecfg', runner === 'vitest' ? "test('ecfg', () => { expect(__MODE__).toBe('a'); });" : "test('ecfg', () => { expect(globalThis.MODE).toBe('a'); });"),
      }, { jestRaw: raw });
      noWrongReuse(runner, dir, F('ecfg'), () => {}, { env1: {}, env2: { R021B_MODE: 'b' } });
    });

    t('held: globalSetup reads a file and passes it to tests through process.env', T, () => {
      const gs = runner === 'vitest'
        ? "import fs from 'node:fs';\nexport default function () { process.env.R021B_GS = fs.readFileSync('gs.txt', 'utf8').trim(); }\n"
        : "const fs = require('node:fs');\nmodule.exports = async () => { process.env.R021B_GS = fs.readFileSync('gs.txt', 'utf8').trim(); };\n";
      const dir = fixture(runner, 'gsetup', {
        'gs.txt': 'a',
        [runner === 'vitest' ? 'setup/global.mjs' : 'setup/global.js']: gs,
        ...tfile(runner, 'gs', "test('gs', () => { expect(process.env.R021B_GS).toBe('a'); });"),
      }, { vitestTest: { globalSetup: ['setup/global.mjs'] }, jest: { globalSetup: '<rootDir>/setup/global.js' } });
      noWrongReuse(runner, dir, F('gs'), { 'gs.txt': 'b' });
    });

    t('held: package.json "imports" map retargeted', T, () => {
      const ext = runner === 'vitest' ? 'mjs' : 'js';
      const body = (v) => (runner === 'vitest' ? `export const v = ${v};\n` : `exports.v = ${v};\n`);
      const dir = fixture(runner, 'imports', {
        [`src/a.${ext}`]: body(1), [`src/b.${ext}`]: body(2),
        ...tfile(runner, 'imp', runner === 'vitest' ? "import { v } from '#dep';\ntest('imp', () => { expect(v).toBe(1); });"
          : "const { v } = require('#dep');\ntest('imp', () => { expect(v).toBe(1); });"),
      }, { pkg: { imports: { '#dep': `./src/a.${ext}` } } });
      noWrongReuse(runner, dir, F('imp'), { 'package.json': JSON.stringify({ name: 'r021b-imports', private: true, imports: { '#dep': `./src/b.${ext}` } }) });
    });

    t('held: dotenv-style read through process.cwd(): .env content', T, () => {
      const dir = fixture(runner, 'cwdenv', {
        '.env': 'GREETING=hello\n',
        ...tfile(runner, 'cenv', "test('cenv', () => { const m = Object.fromEntries(fs.readFileSync(path.join(process.cwd(), '.env'), 'utf8').trim().split('\\n').map((l) => l.split('='))); expect(m.GREETING).toBe('hello'); });"),
      });
      noWrongReuse(runner, dir, F('cenv'), { '.env': 'GREETING=bye\n' });
    });

    t('held (not cacheable): a loopback HTTP service whose response changes', T, () => {
      const dir = fixture(runner, 'loopback', {
        'svc.txt': 'a',
        ...tfile(runner, 'lb', `const http = ${runner === 'vitest' ? "(await import('node:http')).default" : "require('node:http')"};
test('lb', async () => {
  const srv = http.createServer((q, s) => s.end(fs.readFileSync(${JSON.stringify('PLACEHOLDER')}, 'utf8')));
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  const body = await new Promise((r) => http.get({ host: '127.0.0.1', port: srv.address().port }, (res) => { let d = ''; res.on('data', (c) => { d += c; }); res.on('end', () => r(d)); }));
  srv.close();
  expect(body).toBe('a');
});`.replace('"PLACEHOLDER"', 'process.env.R021B_SVC')),
      });
      // the file is outside the project: only the loopback socket links it to the test
      const outside = path.join(TMP, 'review-r021b', `${runner}-svc.txt`);
      fs.writeFileSync(outside, 'a');
      noWrongReuse(runner, dir, F('lb'), () => fs.writeFileSync(outside, 'b'), { env1: { R021B_SVC: outside }, mayRefuse: true });
    });
  });
}

describe('r021b: vitest only', { skip: !RUNNERS.includes('vitest') }, () => {
  const runner = 'vitest';
  const F = (n) => `tests/${n}.test.mjs`;
  t('held: import.meta.glob with a brace pattern: a new file in the second branch', T, () => {
    const dir = fixture(runner, 'glob-brace', {
      'fixtures/a/one.json': '{}',
      ...tfile(runner, 'gb', "const m = import.meta.glob('../fixtures/{a,b}/*.json', { eager: true });\ntest('gb', () => { expect(Object.keys(m).length).toBe(1); });"),
    });
    noWrongReuse(runner, dir, F('gb'), { 'fixtures/b/two.json': '{}' });
  });

  t('held: import.meta.glob with a template literal pattern', T, () => {
    const dir = fixture(runner, 'glob-tpl', {
      'fixtures/c/one.json': '{}',
      ...tfile(runner, 'gt', "const m = import.meta.glob(`../fixtures/c/*.json`, { eager: true });\ntest('gt', () => { expect(Object.keys(m).length).toBe(1); });"),
    });
    noWrongReuse(runner, dir, F('gt'), { 'fixtures/c/two.json': '{}' });
  });

  t('held: import.meta.glob with a negative pattern: the excluded file is renamed', T, () => {
    const dir = fixture(runner, 'glob-neg', {
      'fixtures/n/one.json': '{}', 'fixtures/n/skip.json': '{}',
      ...tfile(runner, 'gn', "const m = import.meta.glob(['../fixtures/n/*.json', '!../fixtures/n/skip.json'], { eager: true });\ntest('gn', () => { expect(Object.keys(m).length).toBe(1); });"),
    });
    noWrongReuse(runner, dir, F('gn'), () => fs.renameSync(path.join(dir, 'fixtures/n/skip.json'), path.join(dir, 'fixtures/n/kept.json')));
  });

  t('held: import.meta.glob in a helper module (not the test file), query ?raw', T, () => {
    const dir = fixture(runner, 'glob-helper', {
      'fixtures/h/one.txt': 'x',
      'src/load.mjs': "export const all = import.meta.glob('../fixtures/h/*.txt', { query: '?raw', import: 'default', eager: true });\n",
      ...tfile(runner, 'gh', "import { all } from '../src/load.mjs';\ntest('gh', () => { expect(Object.values(all).join()).toBe('x'); });"),
    });
    noWrongReuse(runner, dir, F('gh'), { 'fixtures/h/one.txt': 'y' });
  });

  t('held: vi.mock of a scoped package with a root __mocks__ file added', T, () => {
    const dir = fixture(runner, 'mock-scoped', {
      'node_modules/@r021b/pkg/package.json': JSON.stringify({ name: '@r021b/pkg', version: '1.0.0', main: 'index.js' }),
      'node_modules/@r021b/pkg/index.js': "exports.who = () => 'real';\n",
      '__mocks__/@r021b/.keep': '',
      ...tfile(runner, 'ms', "import { who } from '@r021b/pkg';\nvi.mock('@r021b/pkg');\ntest('ms', () => { expect(who()).toBe(undefined); });"),
    });
    noWrongReuse(runner, dir, F('ms'), { '__mocks__/@r021b/pkg.js': "export const who = () => 'mock';\n" });
  });

  t('G4 a preload module from execArgv reads a file before the capture', T, () => {
    const dir = fixture(runner, 'preload', {
      'pre.txt': 'a',
      'pre.mjs': "import fs from 'node:fs';\nglobalThis.__PRE__ = fs.readFileSync(new URL('./pre.txt', import.meta.url), 'utf8').trim();\n",
      ...tfile(runner, 'pre', "test('pre', () => { expect(globalThis.__PRE__).toBe('a'); });"),
    }, { vitestTest: { pool: 'forks', execArgv: ['--import', './pre.mjs'] } });
    noWrongReuse(runner, dir, F('pre'), { 'pre.txt': 'b' });
  });
});

describe('r021b: jest only', { skip: !RUNNERS.includes('jest') }, () => {
  const runner = 'jest';
  const F = (n) => `tests/${n}.test.js`;
  t('held: moduleNameMapper retargeted through a file read by jest.config.js', T, () => {
    const raw = "const fs = require('node:fs');\nmodule.exports = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node', moduleNameMapper: { '^@dep$': '<rootDir>/src/' + fs.readFileSync(__dirname + '/target.txt', 'utf8').trim() + '.js' } };\n";
    const dir = fixture(runner, 'mapper', {
      'target.txt': 'a', 'src/a.js': 'exports.v = 1;\n', 'src/b.js': 'exports.v = 2;\n',
      ...tfile(runner, 'map', "const { v } = require('@dep');\ntest('map', () => { expect(v).toBe(1); });"),
    }, { jestRaw: raw });
    noWrongReuse(runner, dir, F('map'), { 'target.txt': 'b' });
  });

  t('held: a custom testEnvironment reads a file in its constructor', T, () => {
    const dir = fixture(runner, 'customenv', {
      'env.txt': 'a',
      'env.js': "const { TestEnvironment } = require('jest-environment-node');\nconst fs = require('node:fs');\nmodule.exports = class extends TestEnvironment { constructor(c, x) { super(c, x); this.global.__ENVTXT__ = fs.readFileSync(__dirname + '/env.txt', 'utf8').trim(); } };\n",
      ...tfile(runner, 'cenv', "test('cenv', () => { expect(globalThis.__ENVTXT__).toBe('a'); });"),
    }, { jest: { testEnvironment: '<rootDir>/env.js' } });
    noWrongReuse(runner, dir, F('cenv'), { 'env.txt': 'b' });
  });

  t('held: automock: true with a __mocks__ file added under roots', T, () => {
    const dir = fixture(runner, 'automock', {
      'src/dep.js': "exports.v = () => 'real';\n",
      ...tfile(runner, 'am', "const { v } = require('../src/dep.js');\ntest('am', () => { expect(v()).toBe(undefined); });"),
    }, { jest: { automock: true } });
    noWrongReuse(runner, dir, F('am'), { 'src/__mocks__/dep.js': "exports.v = () => 'mock';\n" });
  });
});
