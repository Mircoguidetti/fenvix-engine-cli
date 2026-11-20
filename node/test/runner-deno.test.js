'use strict';
// `detjs deno-test`: control tests (Level 0 inside deno test) and adversarial wrong-reuse tests (--det-cache).
// Same shapes as runner-bun.test.js (noWrongReuse / neverReused / rerunsAfter in runtime-helpers.js).
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const H = require('./runtime-helpers');
const { auditCheck } = require('../src/runners/deno');

const T = { timeout: 600000 };
const RT = 'deno';
const SKIP = H.BINARY.deno ? false : 'deno not found (PATH or DETJS_DENO): Deno runner tests skipped';
const HEAD = [
  "import fs from 'node:fs'; import path from 'node:path';",
  "const eq = (a: unknown, b: unknown) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`); };",
].join('\n');
const tf = (name, body) => ({ [`tests/${name}_test.ts`]: `${HEAD}\n${body}\n` });
const F = (name) => `tests/${name}_test.ts`;

describe('deno: Level 0 controls', { skip: SKIP }, () => {
  const files = {
    ...tf('clock', [
      "Deno.test('wall clock at the epoch', () => { eq(new Date().toISOString(), '2025-01-01T00:00:00.000Z'); });",
      "Deno.test('virtual sleep', async () => { const t0 = Date.now(); const p0 = performance.now(); await new Promise((r) => setTimeout(r, 90000));",
      "  if (Date.now() - t0 < 90000 || performance.now() - p0 < 90000) throw new Error('not virtual'); });",
    ].join('\n')),
    ...tf('random', [
      "const g = (n: string, v: unknown) => { const f = path.join(import.meta.dirname!, '..', 'golden', n + '.json'); const t = JSON.stringify(v);",
      "  if (!fs.existsSync(f)) { fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, t); return; } eq(t, fs.readFileSync(f, 'utf8')); };",
      "Deno.test('seeded', () => { g('random', [Math.random(), crypto.randomUUID(), [...crypto.getRandomValues(new Uint8Array(4))]]); });",
    ].join('\n')),
    ...tf('net', [
      "Deno.test('fetch closed', async () => { let e: unknown = null; try { await fetch('https://example.com/'); } catch (x) { e = x; } if (!e) throw new Error('open'); });",
      "Deno.test('Deno.connect closed', async () => { let e: any = null; try { await Deno.connect({ hostname: 'example.com', port: 80 }); } catch (x) { e = x; } if (!e || !/blocked/.test(e.message)) throw new Error('open'); });",
      "Deno.test('loopback allowed', async () => { const ac = new AbortController(); const s = Deno.serve({ port: 0, signal: ac.signal, onListen() {} }, () => new Response('ok'));",
      "  try { eq(await (await fetch(`http://127.0.0.1:${s.addr.port}/`)).text(), 'ok'); } finally { ac.abort(); await s.finished; } });",
    ].join('\n')),
    ...tf('order', ['a', 'b', 'c', 'd', 'e', 'f'].map((n) => `Deno.test('${n}', () => {});`).join('\n')),
  };
  for (const n of ['o1', 'o2', 'o3', 'o4']) files[`tests/${n}_test.ts`] = `Deno.test('${n}', () => {});\n`;

  test('two --det runs give identical fingerprints; the controls are active inside deno test', T, () => {
    const dir = H.fixture(RT, 'controls', files);
    const a = H.crun(RT, dir, { cache: false });
    assert.equal(a.status, 0, H.show(a));
    const b = H.crun(RT, dir, { cache: false });
    assert.equal(b.status, 0, H.show(b));
    const fa = H.fingerprints(a);
    assert.ok(Object.keys(fa).length >= 16, `all tests traced\n${JSON.stringify(fa)}`);
    assert.deepEqual(H.fingerprints(b), fa);
    assert.deepEqual(b.trace.header.order, a.trace.header.order);
  });

  test('seeded shuffle: same seed same order, another seed another order', T, () => {
    const dir = H.fixture(RT, 'shuffle', { ...files, 'tests/random_test.ts': null });
    const order = (r) => r.trace.header.order;
    const s1 = H.crun(RT, dir, { cache: false, seed: 1 });
    const s1b = H.crun(RT, dir, { cache: false, seed: 1 });
    const s2 = H.crun(RT, dir, { cache: false, seed: 2 });
    for (const r of [s1, s1b, s2]) assert.equal(r.status, 0, H.show(r));
    assert.deepEqual(order(s1b), order(s1));
    assert.deepEqual(H.fingerprints(s1b), H.fingerprints(s1));
    assert.notDeepEqual(order(s2), order(s1));
    const fixed = H.crun(RT, dir, { cache: false });
    assert.deepEqual(fixed.trace.header.order.filter((x) => x.startsWith('tests/order_test.ts')).map((x) => x.split('::')[1]), ['a', 'b', 'c', 'd', 'e', 'f']);
  });

  test('isolation: state shared through the process (environment) changes outcome under one process per file (counted)', T, () => {
    const dir = H.fixture(RT, 'isolation', {
      ...tf('a1', "Deno.test('sets', () => { Deno.env.set('FX_SHARED', '1'); });"),
      ...tf('a2', "Deno.test('reads', () => { eq(Deno.env.get('FX_SHARED'), '1'); });"),
    });
    const plain = spawnSync(H.BINARY.deno, ['test', '-A', 'tests/'], { cwd: dir, encoding: 'utf8' });
    assert.equal(plain.status, 0, `plain deno test shares one process: passes\n${plain.stderr}`);
    const det = H.crun(RT, dir, { cache: false });
    assert.notEqual(det.status, 0, 'under detjs each file runs alone: the dependent test fails (reported, never reused)');
    const changed = Object.entries(H.fingerprints(det)).filter(([, v]) => !v.startsWith('passed'));
    assert.deepEqual(changed.map(([k]) => k), ['tests/a2_test.ts::reads']);
  });
});

describe('deno: wrong reuse (--det-cache)', { skip: SKIP }, () => {
  test('reuse works: an unchanged suite is reused with receipts', T, () => {
    const dir = H.fixture(RT, 'reuse', { ...tf('ok', "Deno.test('ok', () => { eq(1, 1); });") });
    assert.equal(H.crun(RT, dir).status, 0);
    const r2 = H.crun(RT, dir);
    assert.deepEqual(H.reused(r2), [F('ok')], H.show(r2));
  });

  test('file content through Deno.readTextFile (naive: wrong reuse, Deno ops are not node:fs)', T, () => {
    const dir = H.fixture(RT, 'readtext', { 'data/msg.txt': 'hello', ...tf('rt', "Deno.test('rt', async () => { eq(await Deno.readTextFile('data/msg.txt'), 'hello'); });") });
    H.noWrongReuse(RT, dir, F('rt'), { 'data/msg.txt': 'bye' });
  });

  test('file content through Deno.open + FsFile.readable', T, () => {
    const dir = H.fixture(RT, 'open', { 'data/msg.txt': 'hello',
      ...tf('op', "Deno.test('op', async () => { const f = await Deno.open('data/msg.txt'); eq(await new Response(f.readable).text(), 'hello'); });") });
    H.noWrongReuse(RT, dir, F('op'), { 'data/msg.txt': 'bye' });
  });

  test('file content through a named node:fs import', T, () => {
    const dir = H.fixture(RT, 'nodefs', { 'data/msg.txt': 'hello',
      'tests/nf_test.ts': "import { readFileSync } from 'node:fs';\nDeno.test('nf', () => { if (readFileSync('data/msg.txt', 'utf8') !== 'hello') throw new Error('x'); });\n" });
    H.noWrongReuse(RT, dir, F('nf'), { 'data/msg.txt': 'bye' });
  });

  test('file content through fetch(file:)', T, () => {
    const dir = H.fixture(RT, 'fetchfile', { 'data/msg.txt': 'hello',
      ...tf('ff', "Deno.test('ff', async () => { eq(await (await fetch(new URL('../data/msg.txt', import.meta.url))).text(), 'hello'); });") });
    H.noWrongReuse(RT, dir, F('ff'), { 'data/msg.txt': 'bye' });
  });

  test('file metadata: size through Deno.statSync', T, () => {
    const dir = H.fixture(RT, 'size', { 'data/blob.bin': 'abc', ...tf('size', "Deno.test('size', () => { eq(Deno.statSync('data/blob.bin').size, 3); });") });
    H.noWrongReuse(RT, dir, F('size'), { 'data/blob.bin': 'abcd' });
  });

  test('file metadata: modification time is never keyed (not cached)', T, () => {
    const dir = H.fixture(RT, 'mtime', { 'data/a.txt': 'a', ...tf('mt', "Deno.test('mt', () => { if (Deno.statSync('data/a.txt').mtime!.getFullYear() > 2029) throw new Error('future'); });") });
    H.neverReused(RT, dir, F('mt'), () => fs.utimesSync(path.join(dir, 'data', 'a.txt'), new Date('2031-01-01'), new Date('2031-01-01')), /metadata/);
  });

  test('symbolic link target through Deno.realPathSync', T, () => {
    const dir = H.fixture(RT, 'realpath', { 'data/one.txt': '1', 'data/two.txt': '2',
      ...tf('real', "Deno.test('real', () => { eq(path.basename(Deno.realPathSync('data/current')), 'one.txt'); });") });
    fs.symlinkSync('one.txt', path.join(dir, 'data', 'current'));
    H.noWrongReuse(RT, dir, F('real'), () => { fs.rmSync(path.join(dir, 'data', 'current')); fs.symlinkSync('two.txt', path.join(dir, 'data', 'current')); });
  });

  test('lstat: a link replaced by a regular file (Deno.lstatSync().isSymlink)', T, () => {
    const dir = H.fixture(RT, 'lstat', { 'data/t.txt': 't', ...tf('ls', "Deno.test('ls', () => { eq(Deno.lstatSync('data/entry').isSymlink, true); });") });
    fs.symlinkSync('t.txt', path.join(dir, 'data', 'entry'));
    H.noWrongReuse(RT, dir, F('ls'), () => { fs.rmSync(path.join(dir, 'data', 'entry')); H.write(dir, { 'data/entry': 't' }); });
  });

  test('directory listing with entry types (Deno.readDirSync)', T, () => {
    const dir = H.fixture(RT, 'readdir', { 'fixtures/item': 'x',
      ...tf('rd', "Deno.test('rd', () => { eq([...Deno.readDirSync('fixtures')].filter((e) => e.isFile).length, 1); });") });
    H.noWrongReuse(RT, dir, F('rd'), () => { fs.rmSync(path.join(dir, 'fixtures', 'item')); fs.mkdirSync(path.join(dir, 'fixtures', 'item')); });
  });

  test('recursive listing (a walk over Deno.readDir)', T, () => {
    const dir = H.fixture(RT, 'walk', { 'fixtures/cases/a/one.json': '{}',
      ...tf('wk', "const walk = (d: string): string[] => [...Deno.readDirSync(d)].flatMap((e) => e.isDirectory ? walk(`${d}/${e.name}`) : [`${d}/${e.name}`]);\nDeno.test('wk', () => { eq(walk('fixtures').length, 1); });") });
    H.noWrongReuse(RT, dir, F('wk'), { 'fixtures/cases/a/deep/two.json': '{}' });
  });

  test('existence probe (Deno.stat throwing NotFound)', T, () => {
    const dir = H.fixture(RT, 'exists', { ...tf('ex', "Deno.test('ex', () => { let found = true; try { Deno.statSync('data/flag'); } catch { found = false; } eq(found, false); });") });
    H.noWrongReuse(RT, dir, F('ex'), { 'data/flag': '1' });
  });

  test('changed imported module (module graph after the run)', T, () => {
    const dir = H.fixture(RT, 'import', { 'src/dep.ts': 'export const v = 1;\n',
      'tests/imp_test.ts': "import { v } from '../src/dep.ts';\nDeno.test('imp', () => { if (v !== 1) throw new Error('v'); });\n" });
    H.noWrongReuse(RT, dir, F('imp'), { 'src/dep.ts': 'export const v = 2;\n' });
  });

  test('module resolution miss: an optional module appearing (dynamic import in try)', T, () => {
    const dir = H.fixture(RT, 'optional', {
      ...tf('opt', "Deno.test('opt', async () => { let v = 0; try { v = (await import('../src/optional.ts')).v; } catch { /* absent */ } eq(v, 0); });") });
    H.noWrongReuse(RT, dir, F('opt'), { 'src/optional.ts': 'export const v = 1;\n' });
  });

  test('a dynamic import whose specifier is not a literal: never reused', T, () => {
    const dir = H.fixture(RT, 'dynamic', { 'src/a.ts': 'export const v = 1;\n',
      ...tf('dyn', "Deno.test('dyn', async () => { const n = 'a'; eq((await import(`../src/${n}.ts`)).v, 1); });") });
    H.neverReused(RT, dir, F('dyn'), { 'src/a.ts': 'export const v = 2;\n' }, /dynamic import/);
  });

  test('import map in deno.json (a changed mapping)', T, () => {
    const dir = H.fixture(RT, 'importmap', { 'src/a.ts': 'export const v = 1;\n', 'src/b.ts': 'export const v = 2;\n',
      'deno.json': JSON.stringify({ imports: { '@lib': './src/a.ts' } }),
      'tests/im_test.ts': "import { v } from '@lib';\nDeno.test('im', () => { if (v !== 1) throw new Error('v'); });\n" });
    H.noWrongReuse(RT, dir, F('im'), { 'deno.json': JSON.stringify({ imports: { '@lib': './src/b.ts' } }) });
  });

  test('lockfile change reruns the file', T, () => {
    const dir = H.fixture(RT, 'lockfile', { 'deno.json': JSON.stringify({ lock: true }), 'deno.lock': JSON.stringify({ version: '5' }),
      ...tf('lk', "Deno.test('lk', () => {});") });
    H.rerunsAfter(RT, dir, F('lk'), { 'deno.lock': JSON.stringify({ version: '5', remote: {} }) });
  });

  test('environment variable: Deno.env.get', T, () => {
    const dir = H.fixture(RT, 'env', { ...tf('env', "Deno.test('env', () => { eq(Deno.env.get('FX_MODE'), 'a'); });") });
    H.noWrongReuse(RT, dir, F('env'), null, { env1: { FX_MODE: 'a' }, env2: { FX_MODE: 'b' } });
  });

  test('environment variable: process.env', T, () => {
    const dir = H.fixture(RT, 'penv', { ...tf('penv', "Deno.test('penv', () => { eq(process.env.FX_MODE, 'a'); });") });
    H.noWrongReuse(RT, dir, F('penv'), null, { env1: { FX_MODE: 'a' }, env2: { FX_MODE: 'b' } });
  });

  test('environment enumeration (Deno.env.toObject)', T, () => {
    const dir = H.fixture(RT, 'envall', { ...tf('ea', "Deno.test('ea', () => { eq(Object.keys(Deno.env.toObject()).filter((k) => k.startsWith('FX_')).length, 0); });") });
    H.noWrongReuse(RT, dir, F('ea'), null, { env1: {}, env2: { FX_NEW: '1' } });
  });

  test('child process (Deno.Command): never reused', T, () => {
    const dir = H.fixture(RT, 'spawn', { 'data/x': 'a',
      ...tf('sp', "Deno.test('sp', async () => { const o = await new Deno.Command('cat', { args: ['data/x'] }).output(); eq(new TextDecoder().decode(o.stdout), 'a'); });") });
    H.neverReused(RT, dir, F('sp'), { 'data/x': 'b' }, /subprocess/);
  });

  test('sockets (Deno.serve + loopback fetch): never reused', T, () => {
    const dir = H.fixture(RT, 'socket', {
      ...tf('so', "Deno.test('so', async () => { const ac = new AbortController(); const s = Deno.serve({ port: 0, signal: ac.signal, onListen() {} }, () => new Response('x')); try { eq(await (await fetch(`http://localhost:${s.addr.port}`)).text(), 'x'); } finally { ac.abort(); await s.finished; } });") });
    H.neverReused(RT, dir, F('so'), null, /network connection/);
  });

  test('time zone (TZ)', T, () => {
    const dir = H.fixture(RT, 'tz', { ...tf('tz', "Deno.test('tz', () => { eq(new Intl.DateTimeFormat('en').resolvedOptions().timeZone, 'UTC'); });") });
    H.noWrongReuse(RT, dir, F('tz'), null, { env1: { TZ: 'UTC' }, env2: { TZ: 'Asia/Tokyo' } });
  });

  test('runner configuration file: deno.json compilerOptions (jsx factory, the loader)', T, () => {
    const dir = H.fixture(RT, 'loader', {
      'deno.json': JSON.stringify({ compilerOptions: { jsx: 'react', jsxFactory: 'h1' } }),
      'tests/jsx_test.tsx': "// @ts-nocheck\nconst h1 = () => 1; const h2 = () => 2;\nDeno.test('jsx', () => { if (<div /> !== 1) throw new Error('jsx'); void h2; });\n" });
    H.noWrongReuse(RT, dir, 'tests/jsx_test.tsx', { 'deno.json': JSON.stringify({ compilerOptions: { jsx: 'react', jsxFactory: 'h2' } }) });
  });

  test('runner command-line arguments (--location)', T, () => {
    const dir = H.fixture(RT, 'args', { ...tf('loc', "Deno.test('loc', () => { eq(location.host, 'a.example'); });") });
    H.noWrongReuse(RT, dir, F('loc'), null, { args1: ['--location=https://a.example/'], args2: ['--location=https://b.example/'] });
  });

  test('a file written by another test file: the reader is never reused', T, () => {
    const dir = H.fixture(RT, 'written', {
      ...tf('a_writer', "Deno.test('w', () => { Deno.mkdirSync('out', { recursive: true }); Deno.writeTextFileSync('out/shared.txt', 'x'); });"),
      ...tf('b_reader', "Deno.test('r', () => { eq(Deno.readTextFileSync('out/shared.txt'), 'x'); });") });
    H.neverReused(RT, dir, F('b_reader'), null, /another test file/);
  });

  test('persistent storage (localStorage): never reused', T, () => {
    const dir = H.fixture(RT, 'storage', { ...tf('st', "Deno.test('st', () => { const v = localStorage.getItem('n'); localStorage.setItem('n', 'x'); void v; });") });
    H.neverReused(RT, dir, F('st'), null, /runtime API/, {});
  });

  test('node:sqlite (opened natively): never reused', T, () => {
    const dir = H.fixture(RT, 'nodesqlite', { 'tests/ns_test.ts': "import { DatabaseSync } from 'node:sqlite';\nDeno.test('ns', () => { const d = new DatabaseSync(':memory:'); if (d.prepare('select 1 as v').get()!.v !== 1) throw new Error('x'); });\n" });
    H.neverReused(RT, dir, F('ns'), null, /SQLite/);
  });

  test('the audit cross-check alone catches reads the wrappers miss (DETJS_DENO_WRAPPERS=off)', T, () => {
    const dir = H.fixture(RT, 'audit', { 'data/msg.txt': 'hello', ...tf('au', "Deno.test('au', async () => { eq(await Deno.readTextFile('data/msg.txt'), 'hello'); });") });
    H.neverReused(RT, dir, F('au'), { 'data/msg.txt': 'bye' }, /the runtime reported an access the capture did not see: read data\/msg.txt/,
      { env1: { DETJS_DENO_WRAPPERS: 'off' } });
  });

  test('auditCheck: unexplained read, env, sys and net entries become flags; explained ones and detjs\' own do not', () => {
    const tmp = fs.mkdtempSync(path.join(H.TMP, 'audit-'));
    const log = path.join(tmp, 'a.jsonl');
    const line = (permission, value) => JSON.stringify({ v: 1, datetime: 'x', permission, value });
    fs.writeFileSync(log, [line('env', 'DETJS_SEED'), line('read', '/setup'), line('env', 'DETJS_AUDIT_START'), line('read', 'seen.txt'), line('write', 'seen.txt'),
      line('read', 'unseen.txt'), line('write', 'unseen.txt'), line('env', 'FOO'), line('env', 'BAR'), line('sys', 'hostname'), line('net', 'example.com:443')].join('\n'));
    const out = auditCheck(log, { items: [['data', 'seen.txt', 'f:1']], explained: { paths: [], env: ['FOO'], sys: [] }, cwd: tmp }, tmp, []);
    assert.deepEqual(out.map((x) => x[2]), ['read unseen.txt', 'env BAR', 'sys hostname', 'net example.com:443']);
  });

  test('a failure is never reused', T, () => {
    const dir = H.fixture(RT, 'failure', { 'data/v': 'a', ...tf('fl', "Deno.test('fl', () => { eq(Deno.readTextFileSync('data/v'), 'b'); });") });
    assert.notEqual(H.crun(RT, dir).status, 0);
    const r2 = H.crun(RT, dir);
    assert.notEqual(r2.status, 0);
    assert.deepEqual(H.reused(r2), []);
  });

  test('a sanitizer failure (leaked timer) after the body passed is a failure, never reused', T, () => {
    const dir = H.fixture(RT, 'sanitizer', { ...tf('sa', "Deno.test('sa', () => { Deno.unrefTimer; fetch('http://127.0.0.1:9/').catch(() => {}); });") });
    const r1 = H.crun(RT, dir);
    const r2 = H.crun(RT, dir);
    assert.equal(r2.status, r1.status);
    if (r1.status !== 0) assert.deepEqual(H.reused(r2), [], H.show(r2));
  });

  test('verify mode: would-be reuses are compared with a fresh run', T, () => {
    const dir = H.fixture(RT, 'verify', { ...tf('v', "Deno.test('v', () => {});") });
    H.crun(RT, dir);
    const r = H.crun(RT, dir, { args: ['--det-cache-verify'] });
    assert.equal(r.status, 0, H.show(r));
    assert.equal(r.summary.verify_mode, true);
    assert.ok(r.summary.verified >= 2, H.show(r));
    assert.deepEqual(r.summary.verify_mismatches, []);
  });
});
