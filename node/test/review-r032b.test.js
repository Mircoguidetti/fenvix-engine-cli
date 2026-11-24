'use strict';
// Review R-032b (claude/all-runners-2): wrong-reuse attacks on node --test, Mocha, bun test and deno test.
// attack(): run 1 records (passes); run 2: if the file is not reused the input is refused (sound, coarse: logged
// `uncached`); else ONE input changes (or time passes); a fresh run without cache must fail (else logged `held`:
// the input is not one under --det, e.g. a virtual clock); the cached run must not reuse the file.
// Run: cd node && DETJS_DENO=<deno> node --test --test-concurrency=1 test/review-r032b.test.js
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const RH = require('./runner-helpers');
const H = require('./runtime-helpers');

const T = { timeout: 900000 };
const HEAD = {
  'node-test': "import { test } from 'node:test'; import assert from 'node:assert/strict'; import fs from 'node:fs'; import path from 'node:path'; import { createRequire } from 'node:module'; const require = createRequire(import.meta.url); const expect = (a) => ({ toBe: (b) => assert.equal(a, b) });",
  mocha: "import assert from 'node:assert/strict'; import fs from 'node:fs'; import path from 'node:path'; import { createRequire } from 'node:module'; const require = createRequire(import.meta.url); const test = (n, f) => it(n, f); const expect = (a) => ({ toBe: (b) => assert.equal(a, b) });",
  bun: "import { test, expect } from 'bun:test'; import fs from 'node:fs'; import path from 'node:path';",
  deno: "// @ts-nocheck\nimport fs from 'node:fs'; import path from 'node:path'; const test = (n, f) => Deno.test(n, f); const expect = (a) => ({ toBe: (b) => { if (a !== b) throw new Error(`${a} !== ${b}`); } });",
};
const FILE = { 'node-test': (n) => `tests/${n}.test.mjs`, mocha: (n) => `test/${n}.spec.mjs`, bun: (n) => `tests/${n}.test.ts`, deno: (n) => `tests/${n}_test.ts` };
const ALL = ['node-test', 'mocha', 'bun', 'deno'];
const avail = (rt) => (rt === 'bun' || rt === 'deno' ? Boolean(H.BINARY[rt]) : true);

function fixture(rt, name, files) {
  return rt === 'bun' || rt === 'deno' ? H.fixture(rt, `r032b-${name}`, files) : RH.fixture('review-r032b', `${rt}-${name}`, files);
}
function run(rt, dir, { cache = true, env = {}, extra = [] } = {}) {
  if (rt === 'bun' || rt === 'deno') return H.crun(rt, dir, { cache, env, args: extra });
  return RH.crun(rt, dir, [], { cache, env, det: ['--det', ...extra] });
}
const reusedFiles = (r) => ((r.summary && r.summary.reused_files_list) || []).map((f) => f.split('@@')[0]);
const show = (r) => `status=${r.status}\nreused=${JSON.stringify(r.summary && r.summary.reused_files_list)}\nnc=${JSON.stringify(r.summary && r.summary.not_cached_detail)}\nstdout=${(r.stdout || '').slice(-2000)}\nstderr=${(r.stderr || '').slice(-1500)}`;
const sleep = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);

function attack(rt, dir, file, change, o = {}) {
  const x = o.extra || [];
  const r1 = run(rt, dir, { env: o.env1, extra: x });
  assert.equal(r1.status, 0, `run 1 must pass\n${show(r1)}`);
  const r2 = run(rt, dir, { env: o.env1, extra: x });
  if (!reusedFiles(r2).includes(file)) { console.log(`R032B-RESULT ${rt} ${file} uncached`); return 'uncached'; }
  if (typeof change === 'function') change(); else if (change) H.write(dir, change);
  const env2 = o.env2 || o.env1;
  const fresh = run(rt, dir, { cache: false, env: env2, extra: x });
  if (fresh.status === 0) { console.log(`R032B-RESULT ${rt} ${file} held (a fresh --det run still passes)`); return 'held'; }
  const r3 = run(rt, dir, { env: env2, extra: x });
  assert.ok(!reusedFiles(r3).includes(file), `WRONG REUSE: ${rt} ${file}\n${show(r3)}\n--- fresh\n${show(fresh)}`);
  console.log(`R032B-RESULT ${rt} ${file} sound`);
  return 'sound';
}
const tf = (rt, n, body) => ({ [FILE[rt](n)]: `${HEAD[rt]}\n${body}\n` });

// real clocks Level 0 may not virtualize: a test that passes only before a deadline (real time, 40 s ahead)
const CLOCKS = {
  intl: "const s = new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).format(); const [d, t] = s.split(', '); const [mo, da, y] = d.split('/').map(Number); const [h, mi, se] = t.split(':').map(Number); const now = Date.UTC(y, mo - 1, da, h, mi, se);",
  timeorigin: 'const now = performance.timeOrigin + performance.now();',
};

for (const rt of ALL) {
  describe(`${rt}: R-032b`, { skip: avail(rt) ? false : `no ${rt}` }, () => {
    for (const [name, expr] of Object.entries(CLOCKS)) {
      test(`C-${name}: a real clock read (deadline passes between runs)`, T, () => {
        const deadline = Date.now() + 40000;
        const dir = fixture(rt, `clock-${name}`, tf(rt, `c_${name}`, `test('c', () => { ${expr} expect(now < ${deadline}).toBe(true); });`));
        // opt-out of the host epoch (spec 2026-11-23): with it the fresh run (no cache: host time) and the cached run
        // (the cache's virtual day) read different virtual clocks, so the fresh run is no longer this attack's oracle
        attack(rt, dir, FILE[rt](`c_${name}`), () => { const w = deadline - Date.now() + 2000; if (w > 0) sleep(w); }, { extra: ['--det-epoch=fixed'] });
      });
    }

    test('E1 process.loadEnvFile (.env parsed in C++)', T, () => {
      const dir = fixture(rt, 'loadenvfile', { '.env': 'R032B_V=1\n',
        ...tf(rt, 'le', "import process from 'node:process'; test('le', () => { process.loadEnvFile('.env'); expect(process.env.R032B_V).toBe('1'); });") });
      attack(rt, dir, FILE[rt]('le'), { '.env': 'R032B_V=2\n' });
    });

    test('E2 fs.globSync: a matching file appears', T, () => {
      const dir = fixture(rt, 'globsync', { 'cfg/keep.txt': '',
        ...tf(rt, 'gs', "test('gs', () => { expect(fs.globSync('cfg/*.json').length).toBe(0); });") });
      attack(rt, dir, FILE[rt]('gs'), { 'cfg/new.json': '{}' });
    });

    test('E3 module.findPackageJSON: a nested package.json appears', T, () => {
      const dir = fixture(rt, 'findpkg', { 'lib/x.js': 'module.exports = 1;\n',
        ...tf(rt, 'fp', "import mod from 'node:module'; test('fp', () => { const p = mod.findPackageJSON ? mod.findPackageJSON(new URL('file://' + path.resolve('lib/x.js'))) : 'n/a'; expect(p === 'n/a' || !String(p).includes(path.join('lib', 'package.json'))).toBe(true); });") });
      attack(rt, dir, FILE[rt]('fp'), { 'lib/package.json': '{}' });
    });

    test('E4 Intl time zone from TZ (read by ICU in C++)', T, () => {
      const dir = fixture(rt, 'tz', tf(rt, 'tz', "test('tz', () => { expect(new Intl.DateTimeFormat().resolvedOptions().timeZone).toBe('UTC'); });"));
      attack(rt, dir, FILE[rt]('tz'), null, { env1: { TZ: 'UTC' }, env2: { TZ: 'Asia/Tokyo' } });
    });

    test('E5 a child process reads a data file', T, () => {
      const dir = fixture(rt, 'child', { 'data/v.txt': '1',
        ...tf(rt, 'ch', "import cp from 'node:child_process'; test('ch', () => { expect(cp.execFileSync('cat', ['data/v.txt'], { encoding: 'utf8' })).toBe('1'); });") });
      attack(rt, dir, FILE[rt]('ch'), { 'data/v.txt': '2' });
    });
  });
}

describe('bun: R-032b specific', { skip: H.BINARY.bun ? false : 'no bun' }, () => {
  const rt = 'bun';
  test('B1 Bun.spawnSync reads a data file', T, () => {
    const dir = fixture(rt, 'spawn', { 'data/v.txt': '1', ...tf(rt, 'sp', "test('sp', () => { expect(Bun.spawnSync(['cat', 'data/v.txt']).stdout.toString()).toBe('1'); });") });
    attack(rt, dir, FILE[rt]('sp'), { 'data/v.txt': '2' });
  });
  test('B2 a Worker reads a data file', T, () => {
    const dir = fixture(rt, 'worker', { 'data/v.txt': '1', 'tests/w.ts': "import fs from 'node:fs'; postMessage(fs.readFileSync('data/v.txt', 'utf8'));\n",
      ...tf(rt, 'wk', "test('wk', async () => { const w = new Worker(new URL('./w.ts', import.meta.url).href); const v = await new Promise((r) => { w.onmessage = (e) => r(e.data); }); w.terminate(); expect(v).toBe('1'); });") });
    attack(rt, dir, FILE[rt]('wk'), { 'data/v.txt': '2' });
  });
  test('B3 a global ~/.bunfig.toml appears (HOME)', T, () => {
    const home = path.join(H.TMP, 'r032b-bun-home');
    fs.rmSync(home, { recursive: true, force: true }); fs.mkdirSync(home, { recursive: true });
    const dir = fixture(rt, 'global-bunfig', { 'tests/g.test.ts': "import { test, expect } from 'bun:test';\ndeclare const FX_G: number | undefined;\ntest('g', () => { expect(typeof FX_G === 'undefined' ? 0 : FX_G).toBe(0); });\n" });
    attack(rt, dir, 'tests/g.test.ts', () => fs.writeFileSync(path.join(home, '.bunfig.toml'), '[define]\nFX_G = "1"\n'), { env1: { HOME: home, XDG_CONFIG_HOME: path.join(home, '.config') } });
  });
  test('B4 Bun.password.hashSync (random salt) is not reused / is deterministic', T, () => {
    const dir = fixture(rt, 'password', tf(rt, 'pw', "test('pw', () => { console.log('R032B-VAL=' + Bun.password.hashSync('x', { algorithm: 'bcrypt', cost: 4 })); expect(1).toBe(1); });"));
    const a = run(rt, dir, { cache: false }); const b = run(rt, dir, { cache: false });
    const val = (r) => ((r.stdout + r.stderr).match(/R032B-VAL=(\S+)/) || [])[1];
    assert.ok(val(a), show(a));
    if (val(a) === val(b)) { console.log('R032B-RESULT bun password deterministic under --det'); return; }
    run(rt, dir); const r2 = run(rt, dir);
    assert.ok(!reusedFiles(r2).includes(FILE[rt]('pw')), `a test that drew unseeded randomness was reused\n${show(r2)}`);
  });
});

describe('deno: R-032b specific', { skip: H.BINARY.deno ? false : 'no deno' }, () => {
  const rt = 'deno';
  test('D1 deno.json "imports" retargeted (both files exist)', T, () => {
    const dir = fixture(rt, 'imports-map', { 'deno.json': JSON.stringify({ imports: { lib: './src/a.ts' } }), 'src/a.ts': 'export const v = 1;\n', 'src/b.ts': 'export const v = 2;\n',
      ...tf(rt, 'im', "import { v } from 'lib'; test('im', () => { expect(v).toBe(1); });") });
    attack(rt, dir, FILE[rt]('im'), { 'deno.json': JSON.stringify({ imports: { lib: './src/b.ts' } }) });
  });
  test('D2 deno.json "importMap" file retargeted', T, () => {
    const dir = fixture(rt, 'import-map-file', { 'deno.json': JSON.stringify({ importMap: './import_map.json' }), 'import_map.json': JSON.stringify({ imports: { lib: './src/a.ts' } }),
      'src/a.ts': 'export const v = 1;\n', 'src/b.ts': 'export const v = 2;\n', ...tf(rt, 'mf', "import { v } from 'lib'; test('mf', () => { expect(v).toBe(1); });") });
    attack(rt, dir, FILE[rt]('mf'), { 'import_map.json': JSON.stringify({ imports: { lib: './src/b.ts' } }) });
  });
  test('D3 a dynamic import of an absent module succeeds later', T, () => {
    const dir = fixture(rt, 'dyn-absent', tf(rt, 'da', "test('da', async () => { let ok = true; try { await import('../src/opt.ts'); ok = false; } catch {} expect(ok).toBe(true); });"));
    attack(rt, dir, FILE[rt]('da'), { 'src/opt.ts': 'export const v = 1;\n' });
  });
  test('D4 Temporal.Now (if present) passes a deadline', T, () => {
    const deadline = Date.now() + 40000;
    const dir = fixture(rt, 'temporal', tf(rt, 'tp', `test('tp', () => { const T = globalThis.Temporal; const now = T ? T.Now.instant().epochMilliseconds : 0; expect(now < ${deadline}).toBe(true); });`));
    attack(rt, dir, FILE[rt]('tp'), () => { const w = deadline - Date.now() + 2000; if (w > 0) sleep(w); });
  });
  test('D5 Deno.Command reads a data file', T, () => {
    const dir = fixture(rt, 'command', { 'data/v.txt': '1', ...tf(rt, 'cm', "test('cm', () => { const o = new Deno.Command('cat', { args: ['data/v.txt'] }).outputSync(); expect(new TextDecoder().decode(o.stdout)).toBe('1'); });") });
    attack(rt, dir, FILE[rt]('cm'), { 'data/v.txt': '2' });
  });
  test('D6 a module imported by a .ts file through a "jsr:"-free relative re-export chain where the leaf changes', T, () => {
    const dir = fixture(rt, 'reexport', { 'src/a.ts': "export * from './b.ts';\n", 'src/b.ts': 'export const v = 1;\n',
      ...tf(rt, 're', "import { v } from '../src/a.ts'; test('re', () => { expect(v).toBe(1); });") });
    attack(rt, dir, FILE[rt]('re'), { 'src/b.ts': 'export const v = 2;\n' });
  });
});
