'use strict';
// Control and adversarial tests shared by the tap, AVA, Jasmine and uvu shells (node/test/runner-<name>.test.js).
//
// Every adversarial test has the shape of review r021's: run 1 records (passes), run 2 reuses the file (the cache
// works), ONE input changes so that a fresh run FAILS, run 3 with the cache must not reuse the file and must agree
// with the fresh run. "never cached" tests: run 2 must run the file again (no entry recorded).
//
// The runners are installed once (pinned versions) into DETJS_RUNNERS_B_DEPS (default node/test/.tmp/runners-b-deps)
// and linked into each fixture project.
const { test, describe, before } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

const T = { timeout: 900000 };
const DEPS = {
  tap: '21.8.1', ava: '8.4.0', jasmine: '7.0.0', uvu: '0.5.6', tsx: '4.23.15', tinyglobby: '0.2.15',
};
const ROOT = path.join(TMP, 'runners-b');

function depsDir() {
  const dir = process.env.DETJS_RUNNERS_B_DEPS || path.join(TMP, 'runners-b-deps');
  const missing = Object.keys(DEPS).filter((n) => !fs.existsSync(path.join(dir, 'node_modules', n, 'package.json')));
  if (missing.length) {
    fs.mkdirSync(dir, { recursive: true });
    if (!fs.existsSync(path.join(dir, 'package.json'))) fs.writeFileSync(path.join(dir, 'package.json'), '{"name":"runners-b-deps","private":true}');
    const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
    const r = spawnSync(npm, ['install', '--no-audit', '--no-fund', '--prefix', dir, ...Object.entries(DEPS).map(([n, v]) => `${n}@${v}`)],
      { encoding: 'utf8', timeout: 600000 });
    if (r.status !== 0) throw new Error(`npm install of the runners failed: ${r.stderr}`);
  }
  return dir;
}

function write(dir, files) {
  for (const [name, body] of Object.entries(files)) {
    const p = path.join(dir, name);
    if (body === null) { fs.rmSync(p, { force: true, recursive: true }); continue; }
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, body);
  }
}

const EXPECT = [
  "const assert = require('node:assert/strict');",
  'const expect = (a) => ({ toBe: (b) => assert.strictEqual(a, b), toEqual: (b) => assert.deepStrictEqual(a, b), toBeGreaterThan: (b) => assert.ok(a > b, `${a} > ${b}`) });',
].join('\n');
const CJS_HEAD = "const fs = require('node:fs'); const path = require('node:path'); const os = require('node:os'); const cp = require('node:child_process'); const net = require('node:net');";

/** Per runner: where test files live, how a test body becomes a test file, the configuration file, the CLI. */
const RUNNERS = {
  tap: {
    file: (n) => `test/${n}.test.js`,
    head: `${CJS_HEAD}\n${EXPECT}\nconst t = require('tap');\nconst test = (n, f) => t.test(n, async () => { await f(); });\nconst afterAll = (f) => t.teardown(f);`,
    tail: '',
    config: (extra = '') => ({ '.taprc': `allow-incomplete-coverage: true\n${extra}` }),
    pkg: {},
    args: [],
  },
  ava: {
    file: (n) => `test/${n}.test.mjs`,
    head: [
      "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);",
      "import ava from 'ava';",
      CJS_HEAD, EXPECT,
      'const test = (n, f) => ava(n, async (t) => { await f(); t.pass(); });',
      'const afterAll = (f) => ava.after.always(f);',
    ].join('\n'),
    tail: '',
    config: (extra = '') => ({ 'ava.config.mjs': `export default {${extra}};\n` }),
    pkg: {},
    args: [],
  },
  jasmine: {
    file: (n) => `spec/${n}Spec.js`,
    head: `${CJS_HEAD}\nconst test = (n, f) => it(n, async () => { await f(); });`,
    tail: '',
    config: (extra = {}) => ({
      'spec/support/jasmine.json': JSON.stringify({ spec_dir: 'spec', spec_files: ['**/*Spec.js'], helpers: ['helpers/**/*.js'], env: { random: true }, ...extra }),
    }),
    pkg: {},
    args: [],
  },
  uvu: {
    file: (n) => `tests/${n}.js`,
    head: `${CJS_HEAD}\n${EXPECT}\nconst { test: uvuTest } = require('uvu');\nconst test = (n, f) => uvuTest(n, async () => { await f(); });\nconst afterAll = (f) => uvuTest.after(f);`,
    tail: 'uvuTest.run();',
    config: () => ({}),
    pkg: {},
    args: ['tests'],
  },
};

function tfile(runner, name, body) {
  const R = RUNNERS[runner];
  return { [R.file(name)]: `${R.head}\n${body}\n${R.tail}\n` };
}

function fixture(runner, name, files, { config, pkg = {} } = {}) {
  const R = RUNNERS[runner];
  const dir = path.join(ROOT, runner, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  fs.symlinkSync(path.join(depsDir(), 'node_modules'), path.join(dir, 'node_modules'));
  write(dir, { 'package.json': JSON.stringify({ name: `rb-${runner}-${name}`, private: true, ...R.pkg, ...pkg }) });
  write(dir, R.config(config));
  write(dir, files);
  return dir;
}

function cleanEnv(extra = {}) {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'TAP', 'TAP_CHILD_ID', 'NODE_TEST_CONTEXT']) delete env[k];
  for (const [k, v] of Object.entries(extra)) { if (v === undefined) delete env[k]; else env[k] = v; }
  return env;
}

/** Run detjs <runner> --det [--det-cache]; {status, summary, stdout, stderr}. */
function crun(runner, dir, { cache = true, args = [], env = {}, det = [] } = {}) {
  fs.rmSync(path.join(dir, '.detjs', 'cache-summary.json'), { force: true });
  const c = cache ? [`--det-cache=${path.join(dir, '.cache')}`] : [];
  const r = spawnSync(process.execPath, [BIN, runner, '--det', ...c, ...det, ...RUNNERS[runner].args, ...args],
    { cwd: dir, encoding: 'utf8', env: cleanEnv(env), timeout: 300000 });
  let summary = null;
  if (cache) { try { summary = JSON.parse(fs.readFileSync(path.join(dir, '.detjs', 'cache-summary.json'), 'utf8')); } catch { /* none */ } }
  return { status: r.status, summary, stdout: r.stdout || '', stderr: r.stderr || '' };
}

function show(r) {
  const s = r.summary || {};
  return `status=${r.status}\nreused=${JSON.stringify(s.reused_files_list)}\nmisses=${JSON.stringify(s.misses)}\nnot_cached=${JSON.stringify(s.not_cached_detail)}\nstdout=${r.stdout.slice(-2500)}\nstderr=${r.stderr.slice(-2500)}`;
}

const reused = (r) => ((r.summary && r.summary.reused_files_list) || []);

/** Record, reuse, change one input, then the cached run must agree with a fresh (failing) run. */
function noWrongReuse(runner, dir, file, change, o = {}) {
  const r1 = crun(runner, dir, { env: o.env, args: o.args });
  assert.equal(r1.status, 0, `run 1 (record) must pass\n${show(r1)}`);
  const r2 = crun(runner, dir, { env: o.env, args: o.args });
  assert.equal(r2.status, 0, `run 2 must pass\n${show(r2)}`);
  assert.ok(reused(r2).includes(file), `run 2 must reuse ${file} (otherwise this test proves nothing)\n${show(r2)}`);
  if (typeof change === 'function') change(); else write(dir, change);
  const o3 = { env: o.env3 || o.env, args: o.args3 || o.args };
  const fresh = crun(runner, dir, { cache: false, ...o3 });
  assert.notEqual(fresh.status, 0, `the change must make a fresh run fail (test precondition)\n${show(fresh)}`);
  const r3 = crun(runner, dir, o3);
  assert.ok(!reused(r3).includes(file), `WRONG REUSE: ${file} reused after its input changed; a fresh run fails\n${show(r3)}`);
  assert.equal(r3.status, fresh.status, `cached run must agree with the fresh run\n${show(r3)}`);
  return r3;
}

/** The file must never be reused (no entry is recorded), and the reason must name `why`. */
function neverCached(runner, dir, file, why, o = {}) {
  const r1 = crun(runner, dir, o);
  assert.equal(r1.status, 0, `run 1 must pass\n${show(r1)}`);
  const r2 = crun(runner, dir, o);
  assert.equal(r2.status, 0, `run 2 must pass\n${show(r2)}`);
  assert.ok(!reused(r2).includes(file), `${file} must not be reused\n${show(r2)}`);
  const detail = JSON.stringify((r1.summary && r1.summary.not_cached_detail) || {});
  assert.ok(why.test(detail), `not-cached reason for ${file} must match ${why}: ${detail}`);
}

function readTrace(dir) {
  const lines = fs.readFileSync(path.join(dir, '.detjs', 'trace.jsonl'), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
  return { header: lines[0], tests: lines.filter((l) => l.type === 'test') };
}

/** The cases shared by every runner. */
function sharedCases(runner) {
  const F = (n) => RUNNERS[runner].file(n);
  const tf = (n, body) => tfile(runner, n, body);
  const fx = (name, files, o) => fixture(runner, name, files, o);
  const isEsm = runner === 'ava';
  return [
    ['content: a data file read with readFileSync', () => {
      const dir = fx('content', { 'data/msg.txt': 'hello', ...tf('content', "test('content', () => { expect(fs.readFileSync('data/msg.txt', 'utf8')).toBe('hello'); });") });
      noWrongReuse(runner, dir, F('content'), { 'data/msg.txt': 'HELLO' });
    }],
    ['content: a project module the test loads changes', () => {
      const dir = fx('module', {
        'src/value.js': 'module.exports.v = 1;\n',
        ...tf('module', "const { v } = require('../src/value.js');\ntest('module', () => { expect(v).toBe(1); });"),
      });
      noWrongReuse(runner, dir, F('module'), { 'src/value.js': 'module.exports.v = 2;\n' });
    }],
    ['content: a FileHandle read (fs.promises.open + readFile)', () => {
      const dir = fx('filehandle', { 'data/msg.txt': 'hello', ...tf('filehandle', "test('fh', async () => { const h = await fs.promises.open('data/msg.txt'); const s = await h.readFile('utf8'); await h.close(); expect(s).toBe('hello'); });") });
      noWrongReuse(runner, dir, F('filehandle'), { 'data/msg.txt': 'bye' });
    }],
    ['F1a stat() size', () => {
      const dir = fx('stat-size', { 'data/blob.bin': 'abc', ...tf('size', "test('size', () => { expect(fs.statSync('data/blob.bin').size).toBe(3); });") });
      noWrongReuse(runner, dir, F('size'), { 'data/blob.bin': 'abcd' });
    }],
    ['stat() mode: a file made executable', () => {
      const dir = fx('stat-mode', { 'data/run.sh': '#!/bin/sh\n', ...tf('mode', "test('mode', () => { expect(fs.statSync('data/run.sh').mode & 0o111).toBe(0); });") });
      fs.chmodSync(path.join(dir, 'data', 'run.sh'), 0o644);
      noWrongReuse(runner, dir, F('mode'), () => fs.chmodSync(path.join(dir, 'data', 'run.sh'), 0o755));
    }],
    ['stat() mtime read by the test: not cached', () => {
      const dir = fx('stat-mtime', { 'data/a.txt': 'a', ...tf('mtime', "test('mtime', () => { expect(fs.statSync('data/a.txt').mtimeMs > 0).toBe(true); });") });
      neverCached(runner, dir, F('mtime'), /metadata that is not keyed/);
    }],
    ['F1b realpath() of a symbolic link: retargeting the link', () => {
      const dir = fx('realpath', { 'data/one.txt': '1', 'data/two.txt': '2', ...tf('real', "test('real', () => { expect(path.basename(fs.realpathSync('data/current'))).toBe('one.txt'); });") });
      fs.symlinkSync('one.txt', path.join(dir, 'data', 'current'));
      noWrongReuse(runner, dir, F('real'), () => { fs.rmSync(path.join(dir, 'data', 'current')); fs.symlinkSync('two.txt', path.join(dir, 'data', 'current')); });
    }],
    ['F1c lstat(): a symbolic link replaced by a regular file', () => {
      const dir = fx('lstat', { 'data/target.txt': 't', ...tf('lstat', "test('lstat', () => { expect(fs.lstatSync('data/entry').isSymbolicLink()).toBe(true); });") });
      fs.symlinkSync('target.txt', path.join(dir, 'data', 'entry'));
      noWrongReuse(runner, dir, F('lstat'), () => { fs.rmSync(path.join(dir, 'data', 'entry')); write(dir, { 'data/entry': 't' }); });
    }],
    ['listing: a new file in a directory the test lists', () => {
      const dir = fx('readdir', { 'fixtures/l/one.json': '{}', ...tf('list', "test('list', () => { expect(fs.readdirSync('fixtures/l').length).toBe(1); });") });
      noWrongReuse(runner, dir, F('list'), { 'fixtures/l/two.json': '{}' });
    }],
    ['F2a recursive readdir: a new file in a subdirectory', () => {
      const dir = fx('readdir-recursive', { 'fixtures/cases/a/one.json': '{}', ...tf('cases', "test('cases', () => { expect(fs.readdirSync('fixtures/cases', { recursive: true }).filter((f) => f.endsWith('.json')).length).toBe(1); });") });
      noWrongReuse(runner, dir, F('cases'), { 'fixtures/cases/a/two.json': '{}' });
    }],
    ['F2b readdir withFileTypes: an entry changes from file to directory', () => {
      const dir = fx('readdir-types', { 'fixtures/x/item': 'file', ...tf('types', "test('types', () => { expect(fs.readdirSync('fixtures/x', { withFileTypes: true }).filter((e) => e.isFile()).length).toBe(1); });") });
      noWrongReuse(runner, dir, F('types'), () => { fs.rmSync(path.join(dir, 'fixtures', 'x', 'item')); write(dir, { 'fixtures/x/item/inner': 'dir' }); });
    }],
    ['existence probe: a missing file appears', () => {
      const dir = fx('exists', { 'data/.keep': '', ...tf('exists', "test('exists', () => { expect(fs.existsSync('data/flag')).toBe(false); });") });
      noWrongReuse(runner, dir, F('exists'), { 'data/flag': '1' });
    }],
    ['O_EXCL create: the path a test creates exclusively appears', () => {
      const dir = fx('excl', { 'data/.keep': '', ...tf('excl', "test('excl', () => { const fd = fs.openSync('data/lock', 'wx'); fs.closeSync(fd); fs.rmSync('data/lock'); });") });
      noWrongReuse(runner, dir, F('excl'), { 'data/lock': 'held' });
    }],
    ['mkdir without recursive: the directory appears', () => {
      const dir = fx('mkdir', { 'data/.keep': '', ...tf('mkdir', "test('mkdir', () => { fs.mkdirSync('data/work'); fs.rmdirSync('data/work'); });") });
      noWrongReuse(runner, dir, F('mkdir'), { 'data/work/x': '1' });
    }],
    ['F5 an optional module loaded with a caught require: the module appears', () => {
      const dir = fx('optional', { 'src/.keep': '', ...tf('opt', "test('opt', () => { let v = 'none'; try { v = require('../src/optional.js').v; } catch {} expect(v).toBe('none'); });") });
      noWrongReuse(runner, dir, F('opt'), { 'src/optional.js': "module.exports.v = 'here';\n" });
    }],
    ...(isEsm ? [['F5 an optional module loaded with a caught dynamic import: the module appears', () => {
      const dir = fx('optional-esm', { 'src/.keep': '', ...tf('optesm', "test('optesm', async () => { let v = 'none'; try { v = (await import('../src/optional.mjs')).v; } catch {} expect(v).toBe('none'); });") });
      noWrongReuse(runner, dir, F('optesm'), { 'src/optional.mjs': "export const v = 'here';\n" });
    }]] : []),
    ['F3a fs.openAsBlob', () => {
      const dir = fx('blob', { 'data/msg.txt': 'hello', ...tf('blob', "test('blob', async () => { const b = await fs.openAsBlob('data/msg.txt'); expect(await b.text()).toBe('hello'); });") });
      noWrongReuse(runner, dir, F('blob'), { 'data/msg.txt': 'HELLO' });
    }],
    ['F3b process.loadEnvFile', () => {
      const dir = fx('envfile', { 'fixtures/app.env': 'GREETING=hello\n', ...tf('envfile', "test('envfile', () => { process.loadEnvFile('fixtures/app.env'); expect(process.env.GREETING).toBe('hello'); });") });
      noWrongReuse(runner, dir, F('envfile'), { 'fixtures/app.env': 'GREETING=bye\n' });
    }],
    ['F3c node:sqlite read-only database file', () => {
      const dir = fx('sqlite', { ...tf('db', "const { DatabaseSync } = require('node:sqlite');\ntest('db', () => { const db = new DatabaseSync('fixtures/data.db', { readOnly: true }); const n = db.prepare('select count(*) as n from t').get().n; db.close(); expect(n).toBe(1); });") });
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
    }],
    ['F4 fs.cpSync of a fixture, then the copy is read', () => {
      const dir = fx('cp', {
        'fixtures/tpl/config.json': '{"v":1}',
        ...tf('cp', "test('cp', () => { const dst = path.join('out', 'cp'); fs.rmSync(dst, { recursive: true, force: true }); fs.cpSync('fixtures/tpl', dst, { recursive: true }); expect(JSON.parse(fs.readFileSync(path.join(dst, 'config.json'), 'utf8')).v).toBe(1); });"),
      });
      noWrongReuse(runner, dir, F('cp'), { 'fixtures/tpl/config.json': '{"v":2}' });
    }],
    ['F8 a directory outside the project listed asynchronously by a glob library', () => {
      const outside = path.join(ROOT, `outside-${runner}`);
      fs.rmSync(outside, { recursive: true, force: true });
      write(outside, { 'one.txt': '1' });
      const dir = fx('outside', { ...tf('outside', `const { glob } = require('tinyglobby');\ntest('outside', async () => { expect((await glob(['*.txt'], { cwd: ${JSON.stringify(outside)} })).length).toBe(1); });`) });
      noWrongReuse(runner, dir, F('outside'), () => write(outside, { 'two.txt': '2' }));
    }],
    ['held: fs.globSync: a new file matching the pattern', () => {
      const dir = fx('fsglob', { 'fixtures/g/one.json': '{}', ...tf('fglob', "test('fglob', () => { expect(fs.globSync('fixtures/g/*.json').length).toBe(1); });") });
      noWrongReuse(runner, dir, F('fglob'), { 'fixtures/g/two.json': '{}' });
    }],
    ['held: a file read in an after-all hook', () => {
      const dir = fx('after', { 'data/expected.txt': 'ok', ...tf('after', "test('t', () => { expect(1).toBe(1); });\nafterAll(() => { if (fs.readFileSync('data/expected.txt', 'utf8') !== 'ok') throw new Error('teardown check failed'); });") });
      noWrongReuse(runner, dir, F('after'), { 'data/expected.txt': 'changed' });
    }],
    ['environment: a variable read by the test changes', () => {
      const dir = fx('env', { ...tf('env', "test('env', () => { expect(process.env.RB_MODE).toBe('a'); });") });
      noWrongReuse(runner, dir, F('env'), () => {}, { env: { RB_MODE: 'a' }, env3: { RB_MODE: 'b' } });
    }],
    ['environment: enumeration makes the whole environment an input', () => {
      const dir = fx('env-enum', { ...tf('envall', "test('envall', () => { expect(Object.keys(process.env).includes('RB_EXTRA')).toBe(false); });") });
      noWrongReuse(runner, dir, F('envall'), () => {}, { env3: { RB_EXTRA: '1' } });
    }],
    ['time zone: TZ is part of the runtime identity', () => {
      const dir = fx('tz', { ...tf('tz', "test('tz', () => { expect(new Date(Date.UTC(2020, 0, 1)).getHours()).toBe(0); });") });
      noWrongReuse(runner, dir, F('tz'), () => {}, { env: { TZ: 'UTC' }, env3: { TZ: 'Asia/Tokyo' } });
    }],
    ['never cached: a child process', () => {
      const dir = fx('spawn', { ...tf('spawn', "test('spawn', () => { expect(String(cp.execFileSync(process.execPath, ['-e', 'process.stdout.write(String(7))'])).trim()).toBe('7'); });") });
      neverCached(runner, dir, F('spawn'), /subprocess/);
    }],
    ['never cached: a loopback socket', () => {
      const dir = fx('socket', {
        ...tf('socket', "test('socket', async () => { const srv = net.createServer((s) => s.end('hi')); await new Promise((r) => srv.listen(0, '127.0.0.1', r)); const got = await new Promise((r, j) => { const c = net.connect(srv.address().port, '127.0.0.1'); let d = ''; c.on('data', (x) => { d += x; }); c.on('end', () => r(d)); c.on('error', j); }); srv.close(); expect(got).toBe('hi'); });"),
      });
      neverCached(runner, dir, F('socket'), /network connection/);
    }],
    ['never cached: /dev/shm is a channel outside the project', () => {
      const dir = fx('shm', { ...tf('shm', "test('shm', () => { const p = '/dev/shm/rb-' + process.pid; fs.writeFileSync(p, 'x'); expect(fs.readFileSync(p, 'utf8')).toBe('x'); fs.rmSync(p); });") });
      neverCached(runner, dir, F('shm'), /\/proc, \/sys or \/dev/);
    }],
    ['a file written by another test file is never a reused input', () => {
      const dir = fx('rw', {
        ...tf('a_writer', "test('writer', () => { fs.mkdirSync('shared', { recursive: true }); fs.writeFileSync('shared/x.txt', 'v1'); });"),
        ...tf('b_reader', "test('reader', () => { expect(fs.readFileSync('shared/x.txt', 'utf8')).toBe('v1'); });"),
      });
      const r1 = crun(runner, dir);
      assert.equal(r1.status, 0, show(r1));
      const r2 = crun(runner, dir);
      assert.ok(!reused(r2).includes(F('b_reader')), `the reader must not be reused\n${show(r2)}`);
    }],
    ['a new test file matching the glob runs', () => {
      const dir = fx('newfile', { ...tf('first', "test('first', () => { expect(1).toBe(1); });") });
      const r1 = crun(runner, dir);
      assert.equal(r1.status, 0, show(r1));
      write(dir, tf('second', "test('second', () => { expect(1).toBe(2); });"));
      const fresh = crun(runner, dir, { cache: false });
      assert.notEqual(fresh.status, 0, show(fresh));
      const r2 = crun(runner, dir);
      assert.equal(r2.status, fresh.status, show(r2));
      assert.ok(reused(r2).includes(F('first')), `the unchanged file is reused\n${show(r2)}`);
      assert.ok(!reused(r2).includes(F('second')), show(r2));
    }],
    ['a failure is never reused', () => {
      const dir = fx('failure', { ...tf('fails', "test('fails', () => { expect(1).toBe(2); });") });
      const r1 = crun(runner, dir);
      assert.notEqual(r1.status, 0, show(r1));
      const r2 = crun(runner, dir);
      assert.notEqual(r2.status, 0, show(r2));
      assert.ok(!reused(r2).includes(F('fails')), show(r2));
    }],
    ['verify mode decides but runs everything and compares', () => {
      const dir = fx('verify', { ...tf('v', "test('v', () => { expect(1).toBe(1); });") });
      crun(runner, dir);
      const r = crun(runner, dir, { det: ['--det-cache-verify'] });
      assert.equal(r.status, 0, show(r));
      assert.ok(r.summary.verify_mode && r.summary.verified >= 1 && r.summary.verify_mismatches.length === 0, show(r));
      assert.ok(Object.keys(r.summary.ran_files).includes(F('v')), `verify mode runs the file\n${show(r)}`);
    }],
  ];
}

/** Control tests: determinism of --det runs and the seeded order. */
function controlCases(runner) {
  const tf = (n, body) => tfile(runner, n, body);
  const fx = (name, files, o) => fixture(runner, name, files, o);
  return [
    ['two --det runs give identical fingerprints; clock, seeds and closed network active in tests', () => {
      const dir = fx('control', {
        ...tf('ctl_a', [
          "test('clock', async () => { const t0 = Date.now(); await new Promise((r) => setTimeout(r, 5000)); expect(new Date(t0).getUTCFullYear()).toBe(2025); expect(Date.now() - t0 >= 5000).toBe(true); });",
          "test('random', () => { const v = Math.random(); fs.mkdirSync('out', { recursive: true }); fs.appendFileSync('out/random.txt', String(v) + '\\n'); expect(v < 1).toBe(true); });",
          "test('network', async () => { let err = null; try { await fetch('http://example.com/'); } catch (e) { err = e; } expect(err !== null).toBe(true); expect(String(err && (err.cause || err).message).includes('detjs')).toBe(true); });",
        ].join('\n')),
        ...tf('ctl_b', "test('uuid', () => { expect(typeof require('node:crypto').randomUUID()).toBe('string'); });\ntest('timers', async () => { let n = 0; await new Promise((r) => { const h = setInterval(() => { n++; if (n === 50) { clearInterval(h); r(); } }, 1000); }); expect(n).toBe(50); });"),
      });
      const t0 = Date.now();
      const r1 = crun(runner, dir, { cache: false });
      assert.equal(r1.status, 0, show(r1));
      const tr1 = readTrace(dir);
      fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), path.join(dir, 'trace1.jsonl'));
      const r2 = crun(runner, dir, { cache: false });
      assert.equal(r2.status, 0, show(r2));
      assert.ok(Date.now() - t0 < 120000, 'virtual timers: 2 x (5 s + 50 s) of timers must not run in real time');
      const tr2 = readTrace(dir);
      assert.ok(tr1.tests.length >= 5, `every test is traced: ${tr1.tests.map((t) => t.nodeid)}`);
      assert.deepEqual(tr2.tests.map((t) => [t.nodeid, t.fingerprint]), tr1.tests.map((t) => [t.nodeid, t.fingerprint]));
      const v = spawnSync(process.execPath, [BIN, 'verify', path.join(dir, 'trace1.jsonl'), path.join(dir, '.detjs', 'trace.jsonl')], { encoding: 'utf8' });
      assert.equal(v.status, 0, v.stdout + v.stderr);
      const rnd = fs.readFileSync(path.join(dir, 'out', 'random.txt'), 'utf8').trim().split('\n');
      assert.equal(rnd.length, 2);
      assert.equal(rnd[0], rnd[1], 'seeded Math.random: the same value in both runs');
    }],
    ['seeded shuffle: the same seed gives the same order, another seed another order', () => {
      const files = {};
      for (const f of ['f1', 'f2', 'f3', 'f4', 'f5', 'f6']) {
        const body = [];
        for (const t of ['t1', 't2', 't3', 't4']) body.push(`test('${f}-${t}', () => { fs.appendFileSync(path.join(${JSON.stringify(path.join(ROOT, runner))}, 'order-${runner}.log'), '${f}-${t}\\n'); });`);
        Object.assign(files, tf(f, body.join('\n')));
      }
      const dir = fx('shuffle', files);
      const log = path.join(ROOT, runner, `order-${runner}.log`);
      const orderOf = (seed) => {
        fs.rmSync(log, { force: true });
        const r = crun(runner, dir, { cache: false, det: seed === null ? [] : [`--det-seed=${seed}`] });
        assert.equal(r.status, 0, show(r));
        const executed = fs.readFileSync(log, 'utf8').trim().split('\n');
        const traced = readTrace(dir).tests.map((t) => t.nodeid.split('::').pop());
        assert.deepEqual(traced, executed, 'the trace lists the tests in execution order');
        return executed;
      };
      const fixed = orderOf(null);
      assert.deepEqual(fixed, [...fixed].sort(), 'fixed order: files sorted, tests in declaration order');
      const a = orderOf(1);
      const b = orderOf(1);
      const c = orderOf(2);
      assert.deepEqual(a, b, 'same seed, same order');
      assert.notDeepEqual(a, c, 'another seed, another order');
      const fileOrder = (o) => [...new Set(o.map((x) => x.split('-')[0]))];
      assert.notDeepEqual(fileOrder(a), fileOrder(c), 'the file order depends on the seed');
      if (runner !== 'tap') {
        // tap starts a subtest as soon as it is declared: its tests keep declaration order (docs/runners/tap.md)
        const within = (o) => JSON.stringify(['f1', 'f2', 'f3', 'f4', 'f5', 'f6'].map((f) => o.filter((x) => x.startsWith(`${f}-`))));
        assert.ok(within(a) !== within(fixed) || within(c) !== within(fixed), 'the tests of a file are shuffled too');
      }
    }],
  ];
}

/** Register the suites of one runner. `specific`: [[name, fn]] runner-specific adversarial cases. */
function defineRunnerSuite(runner, specific = []) {
  before(() => { fs.mkdirSync(path.join(ROOT, runner), { recursive: true }); depsDir(); });
  const only = process.env.DETJS_RB_ONLY ? new RegExp(process.env.DETJS_RB_ONLY) : null;
  const reg = (title, list) => describe(title, () => {
    for (const [name, fn] of list) {
      if (only && !only.test(name)) continue;
      test(name, T, fn);
    }
  });
  reg(`${runner}: control`, controlCases(runner));
  reg(`${runner}: wrong reuse (shared cases)`, sharedCases(runner));
  if (specific.length) reg(`${runner}: wrong reuse (runner specific)`, specific);
}

module.exports = {
  defineRunnerSuite, fixture, tfile, write, crun, show, reused, noWrongReuse, neverCached, readTrace, RUNNERS, ROOT, depsDir,
};
