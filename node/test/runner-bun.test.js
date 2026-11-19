'use strict';
// `detjs bun-test`: control tests (Level 0 inside bun test) and adversarial wrong-reuse tests (--det-cache).
//
// Every adversarial case: record, reuse (must reuse, otherwise it proves nothing), change ONE input so that a fresh run
// fails, then the cached run must not reuse the file and must agree with the fresh run (noWrongReuse); or, for inputs
// the capture refuses to key, the file is never reused (neverReused). The `naive:` note on a case says what a shell
// that ran `bun test` with only the Node capture (no Bun-specific wrappers, no loader observer) would do.
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const H = require('./runtime-helpers');

const T = { timeout: 600000 };
const RT = 'bun';
const SKIP = H.BINARY.bun ? false : 'bun not found (PATH or DETJS_BUN): Bun runner tests skipped';
const HEAD = "import { test, expect, describe, mock, beforeAll, afterAll } from 'bun:test'; import fs from 'node:fs'; import path from 'node:path';";
const tf = (name, body) => ({ [`tests/${name}.test.ts`]: `${HEAD}\n${body}\n` });
const F = (name) => `tests/${name}.test.ts`;

describe('bun: Level 0 controls', { skip: SKIP }, () => {
  const files = {
    ...tf('clock', [
      "test('wall clock at the epoch', () => { expect(new Date().toISOString()).toBe('2025-01-01T00:00:00.000Z'); });",
      "test('virtual sleep', async () => { const t0 = Date.now(); const p0 = performance.now(); const n0 = Bun.nanoseconds(); await Bun.sleep(60000); await new Promise((r) => setTimeout(r, 30000));",
      "  expect(Date.now() - t0).toBeGreaterThanOrEqual(90000); expect(performance.now() - p0).toBeGreaterThanOrEqual(90000); expect(Bun.nanoseconds() - n0).toBeGreaterThan(9e10); });",
    ].join('\n')),
    ...tf('random', [
      "const g = (n, v) => { const f = path.join(import.meta.dir, '..', 'golden', n + '.json'); const t = JSON.stringify(v);",
      "  if (!fs.existsSync(f)) { fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, t); return; } expect(t).toBe(fs.readFileSync(f, 'utf8')); };",
      "test('seeded', () => { g('random', [Math.random(), crypto.randomUUID(), [...crypto.getRandomValues(new Uint8Array(4))], Bun.randomUUIDv7()]); });",
    ].join('\n')),
    ...tf('net', [
      "test('fetch closed', async () => { await expect(fetch('https://example.com/')).rejects.toThrow(); });",
      "test('Bun.connect closed', async () => { await expect(Bun.connect({ hostname: 'example.com', port: 80, socket: { data() {} } })).rejects.toThrow(/blocked/); });",
      "test('node:http closed', () => { expect(() => require('node:http').get('http://example.com/')).toThrow(/blocked/); });",
      "test('loopback allowed', async () => { const s = Bun.serve({ port: 0, fetch: () => new Response('ok') }); try { expect(await (await fetch(`http://127.0.0.1:${s.port}/`)).text()).toBe('ok'); } finally { s.stop(true); } });",
    ].join('\n')),
    ...tf('order', ['a', 'b', 'c', 'd', 'e', 'f'].map((n) => `test('${n}', () => {});`).join('\n')),
  };
  for (const n of ['o1', 'o2', 'o3', 'o4']) files[`tests/${n}.test.ts`] = `${HEAD}\ntest('${n}', () => {});\n`;

  test('two --det runs give identical fingerprints; the controls are active inside bun test', T, () => {
    const dir = H.fixture(RT, 'controls', files);
    const a = H.crun(RT, dir, { cache: false });
    assert.equal(a.status, 0, H.show(a));
    const b = H.crun(RT, dir, { cache: false });
    assert.equal(b.status, 0, H.show(b));
    const fa = H.fingerprints(a);
    assert.ok(Object.keys(fa).length >= 13, `all tests traced\n${JSON.stringify(fa)}`);
    assert.deepEqual(H.fingerprints(b), fa);
    assert.deepEqual(b.trace.header.order, a.trace.header.order);
  });

  test('seeded shuffle: same seed same order, another seed another order (files and tests)', T, () => {
    const dir = H.fixture(RT, 'shuffle', { ...files, 'tests/random.test.ts': null }); // its golden values depend on the seed
    const order = (r) => r.trace.header.order;
    const s1 = H.crun(RT, dir, { cache: false, seed: 1 });
    const s1b = H.crun(RT, dir, { cache: false, seed: 1 });
    const s2 = H.crun(RT, dir, { cache: false, seed: 2 });
    for (const r of [s1, s1b, s2]) assert.equal(r.status, 0, H.show(r));
    assert.deepEqual(order(s1b), order(s1));
    assert.deepEqual(H.fingerprints(s1b), H.fingerprints(s1));
    assert.notDeepEqual(order(s2), order(s1));
    const files1 = [...new Set(order(s1).map((x) => x.split('::')[0]))];
    const files2 = [...new Set(order(s2).map((x) => x.split('::')[0]))];
    const inOrder1 = order(s1).filter((x) => x.startsWith('tests/order.test.ts'));
    const inOrder2 = order(s2).filter((x) => x.startsWith('tests/order.test.ts'));
    assert.ok(files1.join() !== files2.join() || inOrder1.join() !== inOrder2.join(), 'a different seed changes the order');
    const fixed = H.crun(RT, dir, { cache: false });
    assert.deepEqual(fixed.trace.header.order.filter((x) => x.startsWith('tests/order.test.ts')).map((x) => x.split('::')[1]), ['a', 'b', 'c', 'd', 'e', 'f']);
  });

  test('isolation: a test that depends on another file\'s globals changes outcome under one process per file (counted)', T, () => {
    const dir = H.fixture(RT, 'isolation', {
      ...tf('a1', "test('sets', () => { globalThis.shared = 1; });"),
      ...tf('a2', "test('reads', () => { expect(globalThis.shared).toBe(1); });"),
    });
    const plain = spawnSync(H.BINARY.bun, ['test', './tests/a1.test.ts', './tests/a2.test.ts'], { cwd: dir, encoding: 'utf8' });
    assert.equal(plain.status, 0, `plain bun test shares one process: passes\n${plain.stderr}`);
    const det = H.crun(RT, dir, { cache: false });
    assert.notEqual(det.status, 0, 'under detjs each file runs alone: the dependent test fails (and is reported, never reused)');
    const changed = Object.entries(H.fingerprints(det)).filter(([, v]) => !v.startsWith('passed'));
    assert.deepEqual(changed.map(([k]) => k), ['tests/a2.test.ts::reads']);
  });
});

describe('bun: wrong reuse (--det-cache)', { skip: SKIP }, () => {
  test('reuse works: an unchanged suite is reused with receipts', T, () => {
    const dir = H.fixture(RT, 'reuse', { ...tf('ok', "test('ok', () => { expect(1).toBe(1); });") });
    const r1 = H.crun(RT, dir);
    assert.equal(r1.status, 0, H.show(r1));
    const r2 = H.crun(RT, dir);
    assert.deepEqual(H.reused(r2), [F('ok')], H.show(r2));
    const rc = fs.readFileSync(path.join(dir, '.detjs', 'receipts.jsonl'), 'utf8');
    assert.match(rc, /"reused":true/);
  });

  test('file content through Bun.file().text() (naive: wrong reuse, Bun.file is native)', T, () => {
    const dir = H.fixture(RT, 'bunfile', { 'data/msg.txt': 'hello', ...tf('bf', "test('bf', async () => { expect(await Bun.file('data/msg.txt').text()).toBe('hello'); });") });
    H.noWrongReuse(RT, dir, F('bf'), { 'data/msg.txt': 'bye' });
  });

  test('file content through new Response(Bun.file()) (a native consumer of a BunFile)', T, () => {
    const dir = H.fixture(RT, 'bunfile-response', { 'data/msg.txt': 'hello', ...tf('br', "test('br', async () => { expect(await new Response(Bun.file('data/msg.txt')).text()).toBe('hello'); });") });
    H.noWrongReuse(RT, dir, F('br'), { 'data/msg.txt': 'bye' });
  });

  test('file content through a named node:fs import', T, () => {
    const dir = H.fixture(RT, 'nodefs', { 'data/msg.txt': 'hello',
      'tests/nf.test.ts': "import { test, expect } from 'bun:test'; import { readFileSync } from 'node:fs';\ntest('nf', () => { expect(readFileSync('data/msg.txt', 'utf8')).toBe('hello'); });\n" });
    H.noWrongReuse(RT, dir, F('nf'), { 'data/msg.txt': 'bye' });
  });

  test('file metadata: size through fs.statSync and BunFile#size', T, () => {
    const dir = H.fixture(RT, 'size', { 'data/blob.bin': 'abc',
      ...tf('size', "test('size', () => { expect(fs.statSync('data/blob.bin').size).toBe(3); expect(Bun.file('data/blob.bin').size).toBe(3); });") });
    H.noWrongReuse(RT, dir, F('size'), { 'data/blob.bin': 'abcd' });
  });

  test('file metadata: mode bits', T, () => {
    const dir = H.fixture(RT, 'mode', { 'data/run.sh': '#!/bin/sh\n', ...tf('mode', "test('mode', () => { expect(fs.statSync('data/run.sh').mode & 0o100).toBe(0); });") });
    H.noWrongReuse(RT, dir, F('mode'), () => fs.chmodSync(path.join(dir, 'data', 'run.sh'), 0o755));
  });

  test('file metadata: modification time (BunFile#lastModified cannot be wrapped: source scan, never cached)', T, () => {
    const dir = H.fixture(RT, 'mtime', { 'data/a.txt': 'a',
      ...tf('mtime', "test('mtime', () => { expect(Bun.file('data/a.txt').lastModified).toBeLessThan(Date.parse('2030-01-01')); });") });
    H.neverReused(RT, dir, F('mtime'), () => fs.utimesSync(path.join(dir, 'data', 'a.txt'), new Date('2031-01-01'), new Date('2031-01-01')), /lastModified/);
  });

  test('symbolic link target through fs.realpathSync', T, () => {
    const dir = H.fixture(RT, 'realpath', { 'data/one.txt': '1', 'data/two.txt': '2',
      ...tf('real', "test('real', () => { expect(path.basename(fs.realpathSync('data/current'))).toBe('one.txt'); });") });
    fs.symlinkSync('one.txt', path.join(dir, 'data', 'current'));
    H.noWrongReuse(RT, dir, F('real'), () => { fs.rmSync(path.join(dir, 'data', 'current')); fs.symlinkSync('two.txt', path.join(dir, 'data', 'current')); });
  });

  test('lstat: a link replaced by a regular file', T, () => {
    const dir = H.fixture(RT, 'lstat', { 'data/t.txt': 't', ...tf('lstat', "test('lstat', () => { expect(fs.lstatSync('data/entry').isSymbolicLink()).toBe(true); });") });
    fs.symlinkSync('t.txt', path.join(dir, 'data', 'entry'));
    H.noWrongReuse(RT, dir, F('lstat'), () => { fs.rmSync(path.join(dir, 'data', 'entry')); H.write(dir, { 'data/entry': 't' }); });
  });

  test('directory listing: readdirSync', T, () => {
    const dir = H.fixture(RT, 'listing', { 'fixtures/a.json': '{}', ...tf('ls', "test('ls', () => { expect(fs.readdirSync('fixtures').length).toBe(1); });") });
    H.noWrongReuse(RT, dir, F('ls'), { 'fixtures/b.json': '{}' });
  });

  test('recursive listing through Bun.Glob#scanSync (naive: wrong reuse)', T, () => {
    const dir = H.fixture(RT, 'glob', { 'fixtures/cases/a/one.json': '{}',
      ...tf('glob', "test('glob', () => { expect([...new Bun.Glob('**/*.json').scanSync({ cwd: 'fixtures' })].length).toBe(1); });") });
    H.noWrongReuse(RT, dir, F('glob'), { 'fixtures/cases/a/deep/two.json': '{}' });
  });

  test('existence probe through Bun.file().exists() (naive: wrong reuse)', T, () => {
    const dir = H.fixture(RT, 'exists', { ...tf('ex', "test('ex', async () => { expect(await Bun.file('data/flag').exists()).toBe(false); });") });
    H.noWrongReuse(RT, dir, F('ex'), { 'data/flag': '1' });
  });

  test('changed imported module (static import; Bun\'s loader is native)', T, () => {
    const dir = H.fixture(RT, 'import', { 'src/dep.ts': 'export const v = 1;\n',
      'tests/imp.test.ts': "import { test, expect } from 'bun:test'; import { v } from '../src/dep';\ntest('imp', () => { expect(v).toBe(1); });\n" });
    H.noWrongReuse(RT, dir, F('imp'), { 'src/dep.ts': 'export const v = 2;\n' });
  });

  test('a new file shadowing a resolution (m.tsx before m.ts)', T, () => {
    const dir = H.fixture(RT, 'shadow', { 'src/m.ts': "export const w = 'ts';\n",
      'tests/sh.test.ts': "import { test, expect } from 'bun:test'; import { w } from '../src/m';\ntest('sh', () => { expect(w).toBe('ts'); });\n" });
    H.noWrongReuse(RT, dir, F('sh'), { 'src/m.tsx': "export const w = 'tsx';\n" });
  });

  test('module resolution miss: an optional module appearing (dynamic import in try)', T, () => {
    const dir = H.fixture(RT, 'optional', {
      ...tf('opt', "test('opt', async () => { let v = 0; try { v = (await import('../src/optional')).v; } catch {} expect(v).toBe(0); });") });
    H.noWrongReuse(RT, dir, F('opt'), { 'src/optional.ts': 'export const v = 1;\n' });
  });

  test('module resolution miss through require() in try', T, () => {
    const dir = H.fixture(RT, 'optional-req', {
      ...tf('optr', "test('optr', () => { let v = 0; try { v = require('../src/opt.cjs'); } catch {} expect(v).toBe(0); });") });
    H.noWrongReuse(RT, dir, F('optr'), { 'src/opt.cjs': 'module.exports = 1;\n' });
  });

  test('tsconfig paths (a changed alias target)', T, () => {
    const dir = H.fixture(RT, 'paths', { 'src/a.ts': 'export const v = 1;\n', 'src/b.ts': 'export const v = 2;\n',
      'tsconfig.json': JSON.stringify({ compilerOptions: { baseUrl: '.', paths: { '@lib': ['src/a.ts'] } } }),
      'tests/al.test.ts': "import { test, expect } from 'bun:test'; import { v } from '@lib';\ntest('al', () => { expect(v).toBe(1); });\n" });
    H.noWrongReuse(RT, dir, F('al'), { 'tsconfig.json': JSON.stringify({ compilerOptions: { baseUrl: '.', paths: { '@lib': ['src/b.ts'] } } }) });
  });

  test('mock.module(): the module its factory loads changes', T, () => {
    const dir = H.fixture(RT, 'mock', { 'src/dep.ts': 'export const v = 1;\n', 'src/fake.ts': 'export const v = 10;\n',
      'tests/mk.test.ts': "import { test, expect, mock } from 'bun:test';\nmock.module('../src/dep', () => require('../src/fake'));\ntest('mk', async () => { const { v } = await import('../src/dep'); expect(v).toBe(10); });\n" });
    H.noWrongReuse(RT, dir, F('mk'), { 'src/fake.ts': 'export const v = 11;\n' });
  });

  test('environment variable: a single read through process.env', T, () => {
    const dir = H.fixture(RT, 'env', { ...tf('env', "test('env', () => { expect(process.env.FX_MODE).toBe('a'); });") });
    H.noWrongReuse(RT, dir, F('env'), null, { env1: { FX_MODE: 'a' }, env2: { FX_MODE: 'b' } });
  });

  test('environment variable through Bun.env (not wrappable: the whole environment is keyed)', T, () => {
    const dir = H.fixture(RT, 'bunenv', { ...tf('benv', "test('benv', () => { expect(Bun.env.FX_MODE).toBe('a'); });") });
    H.noWrongReuse(RT, dir, F('benv'), null, { env1: { FX_MODE: 'a' }, env2: { FX_MODE: 'b' } });
  });

  test('environment variable through import.meta.env', T, () => {
    const dir = H.fixture(RT, 'imenv', { ...tf('imenv', "test('imenv', () => { expect(import.meta.env.FX_MODE).toBe('a'); });") });
    H.noWrongReuse(RT, dir, F('imenv'), null, { env1: { FX_MODE: 'a' }, env2: { FX_MODE: 'b' } });
  });

  test('environment enumeration', T, () => {
    const dir = H.fixture(RT, 'envall', { ...tf('envall', "test('envall', () => { expect(Object.keys(process.env).filter((k) => k.startsWith('FX_')).length).toBe(0); });") });
    H.noWrongReuse(RT, dir, F('envall'), null, { env1: {}, env2: { FX_NEW: '1' } });
  });

  test('a .env file Bun loads by itself', T, () => {
    const dir = H.fixture(RT, 'dotenv', { '.env': 'FX_DOT=a\n', ...tf('dot', "test('dot', () => { expect(process.env.FX_DOT).toBe('a'); });") });
    H.noWrongReuse(RT, dir, F('dot'), { '.env': 'FX_DOT=b\n' });
  });

  test('child process (Bun.spawnSync): never reused', T, () => {
    const dir = H.fixture(RT, 'spawn', { 'data/x': 'a', ...tf('sp', "test('sp', () => { expect(Bun.spawnSync(['cat', 'data/x']).stdout.toString()).toBe('a'); });") });
    H.neverReused(RT, dir, F('sp'), { 'data/x': 'b' }, /subprocess/);
  });

  test('child process through Bun.$: never reused', T, () => {
    const dir = H.fixture(RT, 'shell', { ...tf('sh', "test('sh', async () => { expect((await Bun.$`echo hi`.text()).trim()).toBe('hi'); });") });
    H.neverReused(RT, dir, F('sh'), null, /subprocess/);
  });

  test('sockets (Bun.serve + loopback fetch): never reused', T, () => {
    const dir = H.fixture(RT, 'socket', { ...tf('so', "test('so', async () => { const s = Bun.serve({ port: 0, fetch: () => new Response('x') }); try { expect(await (await fetch(`http://localhost:${s.port}`)).text()).toBe('x'); } finally { s.stop(true); } });") });
    H.neverReused(RT, dir, F('so'), null, /network connection/);
  });

  test('time zone (TZ, read by the runtime\'s ICU)', T, () => {
    const dir = H.fixture(RT, 'tz', { ...tf('tz', "test('tz', () => { expect(new Intl.DateTimeFormat('en', { timeZoneName: 'short' }).resolvedOptions().timeZone).toBe('UTC'); });") });
    H.noWrongReuse(RT, dir, F('tz'), null, { env1: { TZ: 'UTC' }, env2: { TZ: 'Asia/Tokyo' } });
  });

  test('runner configuration file: bunfig.toml (a [define] the test sees)', T, () => {
    const dir = H.fixture(RT, 'bunfig', { 'bunfig.toml': '[define]\n"FX_CONST" = "1"\n',
      'tests/cfg.test.ts': "import { test, expect } from 'bun:test';\ndeclare const FX_CONST: number;\ntest('cfg', () => { expect(FX_CONST).toBe(1); });\n" });
    H.noWrongReuse(RT, dir, F('cfg'), { 'bunfig.toml': '[define]\n"FX_CONST" = "2"\n' });
  });

  test('bunfig preload: its reads are captured (detjs\' preload runs first)', T, () => {
    const dir = H.fixture(RT, 'preload', { 'bunfig.toml': '[test]\npreload = ["./setup.ts"]\n', 'data/seed.txt': 'a',
      'setup.ts': "import fs from 'node:fs'; (globalThis as any).SEED = fs.readFileSync('data/seed.txt', 'utf8');\n",
      ...tf('pre', "test('pre', () => { expect((globalThis as any).SEED).toBe('a'); });") });
    H.noWrongReuse(RT, dir, F('pre'), { 'data/seed.txt': 'b' });
  });

  test('runner command-line arguments (--define)', T, () => {
    const dir = H.fixture(RT, 'args', { 'tests/arg.test.ts': "import { test, expect } from 'bun:test';\ndeclare const FX_ARG: number;\ntest('arg', () => { expect(FX_ARG).toBe(1); });\n" });
    H.noWrongReuse(RT, dir, F('arg'), null, { args1: ['--define', 'FX_ARG=1'], args2: ['--define', 'FX_ARG=2'] });
  });

  test('the loader: tsconfig compiler options (jsx factory)', T, () => {
    const dir = H.fixture(RT, 'loader', {
      'tsconfig.json': JSON.stringify({ compilerOptions: { jsx: 'react', jsxFactory: 'h1' } }),
      'src/h.ts': 'export const h1 = (t: any) => 1; export const h2 = (t: any) => 2;\n',
      'tests/jsx.test.tsx': "import { test, expect } from 'bun:test'; import { h1, h2 } from '../src/h';\ntest('jsx', () => { expect(<div />).toBe(1); void h2; });\n" });
    H.noWrongReuse(RT, dir, 'tests/jsx.test.tsx', { 'tsconfig.json': JSON.stringify({ compilerOptions: { jsx: 'react', jsxFactory: 'h2' } }) });
  });

  test('a file written by another test file: the reader is never reused', T, () => {
    const dir = H.fixture(RT, 'written', {
      ...tf('a_writer', "test('w', () => { fs.mkdirSync('out', { recursive: true }); fs.writeFileSync('out/shared.txt', 'x'); });"),
      ...tf('b_reader', "test('r', () => { expect(fs.readFileSync('out/shared.txt', 'utf8')).toBe('x'); });") });
    H.neverReused(RT, dir, F('b_reader'), null, /another test file/);
  });

  test('snapshot file read natively by toMatchSnapshot', T, () => {
    const dir = H.fixture(RT, 'snapshot', { ...tf('snap', "test('snap', () => { expect({ a: 1 }).toMatchSnapshot(); });") });
    const r0 = H.crun(RT, dir, { cache: false });
    assert.equal(r0.status, 0, H.show(r0));
    const snap = path.join(dir, 'tests', '__snapshots__', 'snap.test.ts.snap');
    assert.ok(fs.existsSync(snap), 'snapshot written');
    H.noWrongReuse(RT, dir, F('snap'), () => fs.writeFileSync(snap, fs.readFileSync(snap, 'utf8').replace('"a": 1', '"a": 2')), { env1: { CI: 'true' } });
  });

  test('bun:sqlite database file', T, () => {
    const dir = H.fixture(RT, 'sqlite', { ...tf('db', "import { Database } from 'bun:sqlite';\ntest('db', () => { const d = new Database('data/x.db', { readonly: true }); expect(d.query('select v from t').get().v).toBe(1); d.close(); });") });
    const mk = (v) => { const r = spawnSync(H.BINARY.bun, ['-e', `const { Database } = require('bun:sqlite'); require('fs').mkdirSync('data', {recursive:true}); require('fs').rmSync('data/x.db', {force:true}); const d = new Database('data/x.db'); d.run('create table t (v int)'); d.run('insert into t values (${v})'); d.close();`], { cwd: dir }); assert.equal(r.status, 0, String(r.stderr)); };
    mk(1);
    H.noWrongReuse(RT, dir, F('db'), () => mk(2));
  });

  test('node:sqlite (opened natively, bindings not re-pointable): never reused', T, () => {
    const dir = H.fixture(RT, 'nodesqlite', { ...tf('ns', "import { DatabaseSync } from 'node:sqlite';\ntest('ns', () => { const d = new DatabaseSync(':memory:'); expect(d.prepare('select 1 as v').get().v).toBe(1); });") });
    H.neverReused(RT, dir, F('ns'), null, /SQLite/);
  });

  test('an unclassified Bun API (Bun.which) is not cacheable', T, () => {
    const dir = H.fixture(RT, 'which', { ...tf('wh', "test('wh', () => { expect(typeof Bun.which('sh')).toBe('string'); });") });
    H.neverReused(RT, dir, F('wh'), null, /runtime API/);
  });

  test('a failure is never reused', T, () => {
    const dir = H.fixture(RT, 'failure', { 'data/v': 'a', ...tf('fl', "test('fl', () => { expect(fs.readFileSync('data/v', 'utf8')).toBe('b'); });") });
    const r1 = H.crun(RT, dir);
    assert.notEqual(r1.status, 0);
    const r2 = H.crun(RT, dir);
    assert.notEqual(r2.status, 0);
    assert.deepEqual(H.reused(r2), [], H.show(r2));
  });

  test('verify mode: would-be reuses are compared with a fresh run', T, () => {
    const dir = H.fixture(RT, 'verify', { ...tf('v', "test('v', () => { expect(1).toBe(1); });") });
    H.crun(RT, dir);
    const r = H.crun(RT, dir, { args: ['--det-cache-verify'] });
    assert.equal(r.status, 0, H.show(r));
    assert.equal(r.summary.verify_mode, true);
    assert.ok(r.summary.verified >= 2, H.show(r));
    assert.deepEqual(r.summary.verify_mismatches, []);
  });
});
