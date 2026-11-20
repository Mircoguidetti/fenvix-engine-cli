'use strict';
// Review R-032: adversarial wrong-reuse attacks on `detjs bun-test` and `detjs deno-test`.
// attack(): record, run 2; if run 2 does not reuse the file the input is refused (sound, coarse) and the case passes;
// otherwise change ONE input so a fresh run fails; the cached run 3 must not reuse the file.
// Run: cd node && DETJS_DENO=$(which deno) node --test --test-concurrency=1 test/review-r032-runtimes.test.js
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const H = require('./runtime-helpers');

const T = { timeout: 600000 };

function attack(rt, dir, file, change, opts = {}) {
  const r1 = H.crun(rt, dir, { env: opts.env1 || {} });
  assert.equal(r1.status, 0, `run 1 must pass\n${H.show(r1)}`);
  const r2 = H.crun(rt, dir, { env: opts.env1 || {} });
  if (!H.reused(r2).includes(file)) { console.log(`R032-RESULT ${rt} ${file} uncached`); return 'uncached'; }
  if (typeof change === 'function') change(); else H.write(dir, change);
  const env2 = opts.env2 || opts.env1 || {};
  const fresh = H.crun(rt, dir, { cache: false, env: env2 });
  assert.notEqual(fresh.status, 0, `precondition: the change must make a fresh run fail\n${H.show(fresh)}`);
  const r3 = H.crun(rt, dir, { env: env2 });
  assert.ok(!H.reused(r3).includes(file), `WRONG REUSE: ${file}\n${H.show(r3)}`);
  console.log(`R032-RESULT ${rt} ${file} sound`);
  return 'sound';
}

function entropyNotReused(rt, dir, file) {
  const r1 = H.crun(rt, dir);
  assert.equal(r1.status, 0, H.show(r1));
  const r2 = H.crun(rt, dir);
  assert.ok(!H.reused(r2).includes(file), `a file that drew OS entropy was reused\n${H.show(r2)}`);
}

function soLib(dir, v) {
  fs.writeFileSync(path.join(dir, 'v.c'), `int v(void) { return ${v}; }\n`);
  spawnSync('cc', ['-shared', '-fPIC', '-o', path.join(dir, 'libv.so'), path.join(dir, 'v.c')]);
}

describe('bun', { skip: H.BINARY.bun ? false : 'no bun' }, () => {
  const RT = 'bun';
  const HEAD = "import { test, expect } from 'bun:test'; import fs from 'node:fs'; import path from 'node:path';";
  const tf = (n, body) => ({ [`tests/${n}.test.ts`]: `${HEAD}\n${body}\n` });
  const F = (n) => `tests/${n}.test.ts`;

  test('B1 bunfig.toml appears (absent input): a [define] the test sees', T, () => {
    const dir = H.fixture(RT, 'r032-bunfig-appears', {
      'tests/d.test.ts': "import { test, expect } from 'bun:test';\ndeclare const FX_C: number | undefined;\ntest('d', () => { expect(typeof FX_C === 'undefined' ? 0 : FX_C).toBe(0); });\n" });
    attack(RT, dir, F('d'), { 'bunfig.toml': '[define]\nFX_C = "1"\n' });
  });
  test('B2 text import with { type: "text" }', T, () => {
    const dir = H.fixture(RT, 'r032-text-import', { 'data/m.txt': 'hello',
      'tests/t.test.ts': "import { test, expect } from 'bun:test'; import t from '../data/m.txt' with { type: 'text' };\ntest('t', () => { expect(t).toBe('hello'); });\n" });
    attack(RT, dir, F('t'), { 'data/m.txt': 'changed' });
  });
  test('B3 fetch(file://)', T, () => {
    const dir = H.fixture(RT, 'r032-fetch-file', { 'data/m.txt': 'hello',
      ...tf('ff', "test('ff', async () => { expect(await (await fetch('file://' + path.resolve('data/m.txt'))).text()).toBe('hello'); });") });
    attack(RT, dir, F('ff'), { 'data/m.txt': 'changed' });
  });
  test('B4 Bun.mmap', T, () => {
    const dir = H.fixture(RT, 'r032-mmap', { 'data/m.txt': 'hello',
      ...tf('mm', "test('mm', () => { expect(new TextDecoder().decode(Bun.mmap('data/m.txt'))).toBe('hello'); });") });
    attack(RT, dir, F('mm'), { 'data/m.txt': 'HELLO' });
  });
  test('B5 Bun.file().slice().text() and .bytes()', T, () => {
    const dir = H.fixture(RT, 'r032-slice', { 'data/m.txt': 'hello',
      ...tf('sl', "test('sl', async () => { expect(await Bun.file('data/m.txt').slice(0, 2).text()).toBe('he'); expect((await Bun.file('data/m.txt').bytes()).length).toBe(5); });") });
    attack(RT, dir, F('sl'), { 'data/m.txt': 'HEllo' });
  });
  test('B6 Bun.which() (PATH lookup: a tool appears)', T, () => {
    const dir = H.fixture(RT, 'r032-which', { ...tf('w', "test('w', () => { expect(Bun.which('r032-tool', { PATH: path.resolve('bin') })).toBe(null); });") });
    fs.mkdirSync(path.join(dir, 'bin'), { recursive: true });
    attack(RT, dir, F('w'), () => { fs.writeFileSync(path.join(dir, 'bin', 'r032-tool'), '#!/bin/sh\n'); fs.chmodSync(path.join(dir, 'bin', 'r032-tool'), 0o755); });
  });
  test('B7 Bun.resolveSync probe of an optional module', T, () => {
    const dir = H.fixture(RT, 'r032-resolvesync', { ...tf('rs', "test('rs', () => { let ok = true; try { Bun.resolveSync('./src/opt', process.cwd()); ok = false; } catch {} expect(ok).toBe(true); });") });
    attack(RT, dir, F('rs'), { 'src/opt.ts': 'export const v = 1;\n' });
  });
  test('B8 bun:ffi dlopen of a project library', T, () => {
    const dir = H.fixture(RT, 'r032-ffi', { ...tf('ffi', "import { dlopen, FFIType } from 'bun:ffi';\ntest('ffi', () => { const l = dlopen(path.resolve('libv.so'), { v: { returns: FFIType.i32, args: [] } }); expect(l.symbols.v()).toBe(1); });") });
    soLib(dir, 1);
    attack(RT, dir, F('ffi'), () => soLib(dir, 2));
  });
  test('B9 entropy through crypto.subtle.generateKey', T, () => {
    const dir = H.fixture(RT, 'r032-subtle', { ...tf('k', "test('k', async () => { const k = await crypto.subtle.generateKey({ name: 'HMAC', hash: 'SHA-256', length: 256 }, true, ['sign']); expect(new Uint8Array(await crypto.subtle.exportKey('raw', k)).length).toBe(32); });") });
    entropyNotReused(RT, dir, F('k'));
  });
});

describe('deno', { skip: H.BINARY.deno ? false : 'no deno' }, () => {
  const RT = 'deno';
  const tf = (n, body) => ({ [`tests/${n}_test.ts`]: `const eq = (a: unknown, b: unknown) => { if (a !== b) throw new Error(String(a) + ' !== ' + String(b)); };\n${body}\n` });
  const F = (n) => `tests/${n}_test.ts`;

  test('D1 deno.json appears (absent input): an import map entry shadows a bare specifier fallback', T, () => {
    const dir = H.fixture(RT, 'r032-denojson-appears', { 'src/a.ts': 'export const v = 1;\n',
      ...tf('cfg', "Deno.test('cfg', async () => { let v = 0; try { v = (await import('@r032/x')).v; } catch { /* unmapped */ } eq(v, 0); });") });
    attack(RT, dir, F('cfg'), { 'deno.json': JSON.stringify({ imports: { '@r032/x': './src/a.ts' } }) });
  });
  test('D2 deno.json appears in a PARENT directory of the project (auto-discovered upwards)', T, () => {
    const outer = H.fixture(RT, 'r032-parent-denojson', {});
    const dir = path.join(outer, 'inner');
    H.write(dir, { 'src/a.ts': 'export const v = 1;\n',
      'tests/p_test.ts': "Deno.test('p', async () => { let v = 0; try { v = (await import('@r032/y')).v; } catch { /* unmapped */ } if (v !== 0) throw new Error('mapped'); });\n" });
    attack(RT, dir, F('p'), () => H.write(outer, { 'deno.json': JSON.stringify({ imports: { '@r032/y': './inner/src/a.ts' } }) }));
  });
  test('D3 Deno.readLinkSync', T, () => {
    const dir = H.fixture(RT, 'r032-readlink', { 'data/a': 'a', 'data/b': 'b', ...tf('rl', "Deno.test('rl', () => { eq(Deno.readLinkSync('data/cur'), 'a'); });") });
    fs.symlinkSync('a', path.join(dir, 'data', 'cur'));
    attack(RT, dir, F('rl'), () => { fs.unlinkSync(path.join(dir, 'data', 'cur')); fs.symlinkSync('b', path.join(dir, 'data', 'cur')); });
  });
  test('D4 Deno.dlopen (FFI) of a project library', T, () => {
    const dir = H.fixture(RT, 'r032-ffi', { ...tf('ffi', "Deno.test('ffi', () => { const l = Deno.dlopen(Deno.cwd() + '/libv.so', { v: { parameters: [], result: 'i32' } }); eq(l.symbols.v(), 1); l.close(); });") });
    soLib(dir, 1);
    attack(RT, dir, F('ffi'), () => soLib(dir, 2));
  });
  test('D5 a Worker reads a file', T, () => {
    const dir = H.fixture(RT, 'r032-worker', { 'data/m.txt': 'hello',
      'tests/w.ts': "self.postMessage(Deno.readTextFileSync('data/m.txt'));\n",
      ...tf('wk', "Deno.test('wk', async () => { const w = new Worker(new URL('./w.ts', import.meta.url), { type: 'module' }); const m = await new Promise((r) => { w.onmessage = (e) => r(e.data); }); w.terminate(); eq(m, 'hello'); });") });
    attack(RT, dir, F('wk'), { 'data/m.txt': 'changed' });
  });
  test('D6 Deno.statSync().ino / nlink (hard link added)', T, () => {
    const dir = H.fixture(RT, 'r032-nlink', { 'data/a': 'a', ...tf('nl', "Deno.test('nl', () => { eq(Deno.statSync('data/a').nlink, 1); });") });
    attack(RT, dir, F('nl'), () => fs.linkSync(path.join(dir, 'data', 'a'), path.join(dir, 'data', 'b')));
  });
  test('D7 entropy through crypto.subtle.generateKey', T, () => {
    const dir = H.fixture(RT, 'r032-subtle', { ...tf('k', "Deno.test('k', async () => { const k = await crypto.subtle.generateKey({ name: 'HMAC', hash: 'SHA-256', length: 256 }, true, ['sign']); eq(new Uint8Array(await crypto.subtle.exportKey('raw', k)).length, 32); });") });
    entropyNotReused(RT, dir, F('k'));
  });
  test('D8 Deno.permissions.querySync depends on the permission flags (detjs passes -A)', T, () => {
    const dir = H.fixture(RT, 'r032-perm', { ...tf('pm', "Deno.test('pm', () => { eq(Deno.permissions.querySync({ name: 'read' }).state, 'granted'); });") });
    const r1 = H.crun(RT, dir);
    assert.equal(r1.status, 0, H.show(r1));
  });
});
