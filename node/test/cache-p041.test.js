'use strict';
// Row F-06 (cache with proof for Node), `detjs verify` and the per-file process models: the gaps of the 2026-11-20
// audit closed by session node-D, each with its regression test (Vitest and Jest unless the gap is one runner's;
// DETJS_TEST_RUNNERS selects). Shared-process runners (Mocha, Jasmine, uvu, Bun, Deno: G-0145..G-0149) are in their
// own suites (runner-mocha, runner-b-specific, runner-bun, runner-deno), named by gap id.
//
//   receipts     G-2161 (why a result is reused), G-2225 (a capture that is not written is a counted refusal)
//   keys         G-1399 (configuration files per runner, the changed file named), G-1401 (start-up outputs by content)
//   trace        G-1402 (reused tests in the trace), G-1481 (call sites of callbacks)
//   verify       G-1482 (different settings named), G-1483 (order-dependent failure explained)
//   isolation    G-1394 (--det-isolate), G-1397 (per-test reuse under --det-isolate; why the file is the unit without)
//   refusals     G-1582 clock-real, G-1583 dynamic-import (Bun), G-1584 keygen, G-1585 loader, G-1586 preload,
//                G-2220 /proc, G-2221 env-unobserved, G-2222 net-record, G-2223 UDP: each kept, with the test that
//                shows it never gives a wrong result (G-2224 Deno: runner-deno.test.js, "the audit cross-check alone")
// Run: cd node && node --test test/cache-p041.test.js
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const { fixture, crun, show, reused, write } = require('./runner-helpers');
const { BIN } = require('./helpers');

const T = { timeout: 900000 };
const RUNNERS = (process.env.DETJS_TEST_RUNNERS || 'vitest,jest').split(',').filter((r) => r === 'vitest' || r === 'jest');
const EXT = { vitest: '.test.mjs', jest: '.test.js' };
const HEAD = {
  vitest: "import { test, expect, describe } from 'vitest'; import fs from 'node:fs'; import path from 'node:path';",
  jest: "const fs = require('node:fs'); const path = require('node:path');",
};

function proj(runner, name, files, extra = {}, cfg = {}) {
  const f = {};
  if (runner === 'vitest') f['vitest.config.mjs'] = `export default { test: ${JSON.stringify({ include: ['t/**/*.test.mjs'], ...cfg }).replace(/"__GS__"/g, "'./gs.mjs'")} };\n`;
  else f['jest.config.js'] = `module.exports = ${JSON.stringify({ testMatch: ['**/t/**/*.test.js'], testEnvironment: 'node', ...cfg })};\n`;
  for (const [n, body] of Object.entries(files)) f[`t/${n}${EXT[runner]}`] = `${HEAD[runner]}\n${body}\n`;
  return fixture(`cache-p041-${runner}`, name, { ...f, ...extra });
}
const args = (runner, a = []) => (runner === 'vitest' ? ['run', ...a] : a);
const run = (runner, dir, a = [], o = {}) => crun(runner, dir, args(runner, a), o);
const fileOf = (runner, n) => `t/${n}${EXT[runner]}`;
const receipts = (dir) => fs.readFileSync(path.join(dir, '.detjs', 'receipts.jsonl'), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
const traceOf = (p) => {
  const lines = fs.readFileSync(p, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
  return { header: lines[0], tests: lines.filter((l) => l.type === 'test') };
};
const verify = (...a) => spawnSync(process.execPath, [BIN, 'verify', ...a], { encoding: 'utf8' });

/** The shape of every refusal proof: never reused, and a change that makes a fresh run fail makes the cached run fail. */
function refusalIsSound(runner, dir, file, why, change, o = {}) {
  const r1 = run(runner, dir, o.args, { env: o.env, det: o.det });
  assert.equal(r1.status, 0, `run 1 must pass\n${show(r1)}`);
  // `o.whyIn` names the field the reason is recorded in: a per-file refusal lands in `not_cached_detail`, a
  // refusal of the whole project in `misses`. Only a caller that expects a project-level refusal passes it, and
  // every other assertion below is unchanged either way -- the point of this helper is that nothing is reused and
  // that the change still makes the cached run fail, whichever reason the engine gave.
  const whyField = o.whyIn === 'misses' ? r1.summary.misses : r1.summary.not_cached_detail;
  assert.match(JSON.stringify(whyField), why, `not cached for ${why}\n${show(r1)}`);
  const r2 = run(runner, dir, o.args, { env: o.env, det: o.det });
  assert.equal(r2.status, 0, show(r2));
  assert.ok(!reused(r2).includes(file), `${file} must never be reused\n${show(r2)}`);
  if (typeof change === 'function') change(); else write(dir, change);
  const env3 = o.env3 || o.env;
  const fresh = run(runner, dir, o.args, { cache: false, env: env3, det: o.det });
  assert.notEqual(fresh.status, 0, `the change must make a fresh run fail\n${show(fresh)}`);
  const r3 = run(runner, dir, o.args, { env: env3, det: o.det });
  assert.ok(!reused(r3).includes(file), `WRONG REUSE\n${show(r3)}`);
  assert.notEqual(r3.status, 0, `the cached run fails like the fresh run\n${show(r3)}`);
}

for (const runner of RUNNERS) {
  describe(`${runner}: receipts and refusal accounting`, () => {
    test('G-2161: a reused result says why in its receipt', T, () => {
      const dir = proj(runner, 'why', { a: "test('reads', () => { expect(fs.readFileSync('in.txt', 'utf8')).toBe('x'); });" }, { 'in.txt': 'x' });
      assert.equal(run(runner, dir).status, 0);
      const r2 = run(runner, dir);
      assert.ok(reused(r2).includes(fileOf(runner, 'a')), show(r2));
      const rc = receipts(dir).find((l) => l.nodeid === `${fileOf(runner, 'a')}::reads`);
      assert.ok(rc && rc.reused, JSON.stringify(rc));
      assert.match(String(rc.why), /^reused: every input unchanged since run .*same configuration and runtime digests; \d+ code file\(s\) by content; \d+ file\/listing\/metadata key\(s\); \d+ environment variable\(s\); does not read the clock; recorded outcome passed$/, JSON.stringify(rc));
      const file = receipts(dir).find((l) => l.nodeid === fileOf(runner, 'a'));
      assert.match(String(file.why), /all 1 test\(s\) of the file proved reuse/);
    });

    test('G-2225: a capture that cannot be written is a counted, visible refusal', T, () => {
      // the test replaces the run's capture directory by a file: the worker cannot write the file's capture
      const dir = proj(runner, 'unwritten', {
        a: "test('breaks the capture dir', () => { for (const r of fs.readdirSync('.detjs').filter((n) => n.startsWith('run-'))) { const d = path.join('.detjs', r, 'cache'); fs.rmSync(d, { recursive: true, force: true }); fs.writeFileSync(d, 'x'); } });",
      });
      const r1 = run(runner, dir);
      assert.equal(r1.status, 0, show(r1));
      assert.equal(r1.summary.not_cached['capture not written'], 1, show(r1));
      assert.match(r1.stdout, /detjs cache: not cached: capture not written 1/, show(r1));
      assert.match(r1.summary.not_cached_detail[fileOf(runner, 'a')], /^capture not written/);
    });
  });

  describe(`${runner}: keys`, () => {
    test('G-1399: another runner\'s configuration file is not an input; a configuration miss names the changed file', T, () => {
      const other = runner === 'vitest' ? { 'jest.config.js': 'module.exports = { testTimeout: 1000 };\n' } : { 'vite.config.mjs': 'export default {};\n' };
      const dir = proj(runner, 'config-files', { a: "test('a', () => { expect(1).toBe(1); });" }, { ...other, 'tsconfig.json': '{"compilerOptions":{"strict":true}}' });
      assert.equal(run(runner, dir).status, 0);
      const [name] = Object.keys(other);
      write(dir, { [name]: `${other[name]}// edited\n` });
      const r2 = run(runner, dir);
      assert.ok(reused(r2).includes(fileOf(runner, 'a')), `editing ${name} must not rerun ${runner} files\n${show(r2)}`);
      write(dir, { 'tsconfig.json': '{"compilerOptions":{"strict":false}}' });
      const r3 = run(runner, dir);
      assert.ok(!reused(r3).includes(fileOf(runner, 'a')), show(r3));
      assert.match(r3.summary.misses[fileOf(runner, 'a')], /^config: changed .*tsconfig\.json/, show(r3));
    });

    if (runner === 'vitest') {
      test('G-1401: a file written by globalSetup is keyed by its content (Vitest decides after globalSetup)', T, () => {
        const dir = proj(runner, 'gsetup', { a: "test('reads', () => { expect(fs.readFileSync('fx/gs-out.txt', 'utf8')).toBe('ok'); });" }, {
          'gs.mjs': "import fs from 'node:fs';\nexport default function () { fs.mkdirSync('fx', { recursive: true }); fs.writeFileSync('fx/gs-out.txt', fs.readFileSync('src.txt', 'utf8')); }\n",
          'src.txt': 'ok',
        }, { globalSetup: '__GS__' });
        const r1 = run(runner, dir);
        assert.equal(r1.status, 0, show(r1));
        assert.deepEqual(r1.summary.not_cached_detail, {}, show(r1));
        const r2 = run(runner, dir);
        assert.ok(reused(r2).includes(fileOf(runner, 'a')), `reused: the start-up output is unchanged\n${show(r2)}`);
        write(dir, { 'src.txt': 'changed' });
        const fresh = run(runner, dir, [], { cache: false });
        assert.notEqual(fresh.status, 0, show(fresh));
        const r3 = run(runner, dir);
        assert.ok(!reused(r3).includes(fileOf(runner, 'a')), `WRONG REUSE\n${show(r3)}`);
        assert.notEqual(r3.status, 0, show(r3));
        assert.match(r3.summary.misses[fileOf(runner, 'a')], /fx\/gs-out\.txt/, show(r3));
      });
    } else {
      test('G-1401 (kept for Jest): Jest decides before globalSetup, so a file globalSetup writes is never reused', T, () => {
        const dir = proj(runner, 'gsetup', { a: "test('reads', () => { expect(fs.readFileSync('fx/gs-out.txt', 'utf8')).toBe('ok'); });" }, {
          'gs.js': "const fs = require('node:fs');\nmodule.exports = () => { fs.mkdirSync('fx', { recursive: true }); fs.writeFileSync('fx/gs-out.txt', fs.readFileSync('src.txt', 'utf8')); };\n",
          'src.txt': 'ok',
        }, { globalSetup: './gs.js' });
        refusalIsSound(runner, dir, fileOf(runner, 'a'), /written by start-up|start-up code wrote/, { 'src.txt': 'changed' });
      });
    }
  });

  describe(`${runner}: trace and verify`, () => {
    test('G-1402: reused tests are in the trace with their recorded fingerprints; verify of a cached run vs a full run is stable', T, () => {
      const dir = proj(runner, 'trace-reused', {
        a: "test('a1', () => { expect(Math.random() < 1).toBe(true); }); test('a2', () => { expect(fs.readFileSync('in.txt', 'utf8')).toBe('x'); });",
        b: "test('b1', () => { expect(1).toBe(1); });",
      }, { 'in.txt': 'x' });
      assert.equal(run(runner, dir).status, 0);
      fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), path.join(dir, 'full.jsonl'));
      const r2 = run(runner, dir);
      assert.equal(reused(r2).length, 2, show(r2));
      const t2 = traceOf(path.join(dir, '.detjs', 'trace.jsonl'));
      assert.deepEqual(t2.tests.map((x) => x.nodeid).sort(), [`${fileOf(runner, 'a')}::a1`, `${fileOf(runner, 'a')}::a2`, `${fileOf(runner, 'b')}::b1`]);
      assert.deepEqual([...t2.header.meta.reused_tests].sort(), t2.tests.map((x) => x.nodeid).sort());
      const v = verify(path.join(dir, 'full.jsonl'), path.join(dir, '.detjs', 'trace.jsonl'));
      assert.equal(v.status, 0, v.stdout + v.stderr);
      assert.match(v.stdout, /run 1: 3 test\(s\) reused from the cache/);
      assert.match(v.stdout, /covered by Level 0: 3 {2}not covered: 0 {2}missing: 0/);
    });

    test('G-1481: listings from callbacks, promise chains and fs.glob carry their call site', T, () => {
      const dir = proj(runner, 'sites', {
        a: [
          "test('cb', async () => { await new Promise((r) => fs.readdir('fx', () => r())); });",
          "test('then', async () => { await Promise.all([fs.promises.readdir('fx')]).then(() => fs.promises.readdir('fx')); });",
          "test('opendir', async () => { await new Promise((r) => fs.opendir('fx', () => r())); });",
          "test('glob', async () => { if (fs.glob) await new Promise((r) => fs.glob('fx/*', () => r())); else fs.readdirSync('fx'); });",
        ].join('\n'),
      }, { 'fx/one': '1', 'fx/two': '2' });
      const r = run(runner, dir, [], { cache: false });
      assert.equal(r.status, 0, show(r));
      const t = traceOf(path.join(dir, '.detjs', 'trace.jsonl'));
      const fsEvents = t.tests.flatMap((x) => (x.events || []).filter((e) => e.s === 'fs').map((e) => [x.nodeid.split('::').pop(), e.o, e.at]));
      assert.ok(fsEvents.length >= 5, JSON.stringify(fsEvents));
      for (const [name, op, at] of fsEvents) assert.match(at, new RegExp(`^${fileOf(runner, 'a').replace(/\./g, '\\.')}:\\d+$`), `${name} ${op} has no call site: ${at}`);
    });

    test('G-1482: verify says when the traces were recorded with different settings', T, () => {
      const dir = proj(runner, 'settings', { a: "test('r', () => { expect(Math.random() < 1).toBe(true); });" });
      assert.equal(run(runner, dir, [], { cache: false, det: ['--det', '--det-seed=1', '--det-trace=s1.jsonl'] }).status, 0);
      assert.equal(run(runner, dir, [], { cache: false, det: ['--det', '--det-seed=2', '--det-trace=s2.jsonl', '--det-epoch=2024-06-01T00:00:00Z'] }).status, 0);
      const v = verify(path.join(dir, 's1.jsonl'), path.join(dir, 's2.jsonl'));
      assert.match(v.stdout, /WARNING: the traces were recorded with different settings/, v.stdout);
      assert.match(v.stdout, /run 0 vs 1: seed: 1 vs 2/);
      assert.match(v.stdout, /run 0 vs 1: epoch: /);
      const j = JSON.parse(verify(path.join(dir, 's1.jsonl'), path.join(dir, 's2.jsonl'), '--json').stdout);
      assert.ok(j.setting_differences.some((d) => d.key === 'seed'), JSON.stringify(j.setting_differences));
    });

    test('G-1483: an order-dependent failure names the tests that ran before it in the failing run only', T, () => {
      const dir = proj(runner, 'order', {
        a: "test('a1 pollutes', () => { globalThis.polluted = true; }); test('a2 victim', () => { expect(globalThis.polluted).toBe(undefined); }); test('a3', () => {}); test('a4', () => {});",
      });
      // seeds whose orders put the polluter before / after the victim
      const outcomes = {};
      for (const s of [1, 2, 3, 4, 5, 6, 7, 8]) {
        const r = run(runner, dir, [], { cache: false, det: ['--det', `--det-seed=${s}`, `--det-trace=s${s}.jsonl`] });
        outcomes[s] = r.status;
      }
      const pass = Object.keys(outcomes).find((s) => outcomes[s] === 0);
      const fail = Object.keys(outcomes).find((s) => outcomes[s] !== 0);
      assert.ok(pass && fail, JSON.stringify(outcomes));
      const v = verify(path.join(dir, `s${pass}.jsonl`), path.join(dir, `s${fail}.jsonl`));
      // the verifier of claude/verifier-cli: the first divergence is the run input (the seed), then the tests that
      // ran before the victim only in the failing run (G-1483: the polluter is among them)
      assert.match(v.stdout, /a2 victim\s+\[seed\] outcomes=passed,failed/, v.stdout);
      assert.match(v.stdout, /a2 victim[^\n]*\n[^\n]*run input seed differs[^\n]*\n\s+before it only in run 1: [^\n]*a1 pollutes/, v.stdout);
    });
  });

  describe(`${runner}: --det-isolate`, () => {
    test('G-1394: --det-isolate runs every test in a fresh process (state an earlier test left is gone)', T, () => {
      const dir = proj(runner, 'isolate', { a: "let n = 0; test('first', () => { n++; expect(n).toBe(1); }); test('second', () => { n++; expect(n).toBe(1); });" });
      const plain = run(runner, dir, [], { cache: false });
      assert.notEqual(plain.status, 0, 'one process per file: second sees first\'s state');
      const iso = run(runner, dir, [], { cache: false, det: ['--det', '--det-isolate'] });
      assert.equal(iso.status, 0, `a fresh process per test\n${show(iso)}`);
      assert.match(iso.stdout, /--det-isolate: 2 tests, each in a fresh process/);
      const t = traceOf(path.join(dir, '.detjs', 'trace.jsonl'));
      assert.deepEqual(t.tests.map((x) => [x.nodeid, x.outcome]), [[`${fileOf(runner, 'a')}::first`, 'passed'], [`${fileOf(runner, 'a')}::second`, 'passed']]);
      assert.equal(t.header.meta.isolate_tests, true);
    });

    test('G-1397: with --det-isolate a test is reused or run on its own inputs; without it the file is the unit (and must be)', T, () => {
      const dir = proj(runner, 'per-test', {
        a: "test('one', () => { expect(fs.readFileSync('in1.txt', 'utf8')).toBe('1'); }); test('two', () => { expect(fs.readFileSync('in2.txt', 'utf8')).toBe('2'); });",
      }, { 'in1.txt': '1', 'in2.txt': '2' });
      const det = ['--det', '--det-isolate'];
      assert.equal(run(runner, dir, [], { det }).status, 0);
      const r2 = run(runner, dir, [], { det });
      assert.deepEqual(r2.summary.reused_tests_list.sort(), [`${fileOf(runner, 'a')}::one`, `${fileOf(runner, 'a')}::two`], show(r2));
      write(dir, { 'in2.txt': 'changed' });
      const r3 = run(runner, dir, [], { det });
      assert.notEqual(r3.status, 0, show(r3));
      assert.deepEqual(r3.summary.reused_tests_list, [`${fileOf(runner, 'a')}::one`], `only "two" runs again\n${show(r3)}`);
      assert.deepEqual(r3.summary.ran_tests_list, [`${fileOf(runner, 'a')}::two`], show(r3));
      // without --det-isolate the tests of a file share module state: skipping "first" would change what "second"
      // sees ("second" alone fails), so a change of an input only "second" reads reruns the whole file, which keeps
      // the verdict of a fresh run
      const shared = proj(runner, 'file-unit', {
        a: "let n = 0; test('first', () => { n++; }); test('second', () => { expect(fs.readFileSync('in.txt', 'utf8').startsWith('x')).toBe(true); expect(n).toBe(1); });",
      }, { 'in.txt': 'x' });
      assert.equal(run(runner, shared).status, 0);
      const alone = run(runner, shared, ['-t', 'second'], { cache: false });
      assert.notEqual(alone.status, 0, `"second" alone fails: a per-test unit without isolation would be wrong\n${show(alone)}`);
      write(shared, { 'in.txt': 'x2' });
      const s2 = run(runner, shared);
      assert.equal(s2.status, 0, `the whole file runs again: "second" sees "first"'s state\n${show(s2)}`);
      assert.ok(!reused(s2).includes(fileOf(runner, 'a')), show(s2));
      assert.equal(s2.summary.ran_files[fileOf(runner, 'a')].tests, 2, show(s2));
    });
  });

  describe(`${runner}: refusals kept, each proven never to give a wrong result`, () => {
    test('G-1582 clock-real: a test that reads process.cpuUsage() is never reused', T, () => {
      const dir = proj(runner, 'clock-real', { a: "test('cpu', () => { expect(process.cpuUsage().user >= 0).toBe(true); expect(fs.readFileSync('v.txt', 'utf8')).toBe('1'); });" }, { 'v.txt': '1' });
      refusalIsSound(runner, dir, fileOf(runner, 'a'), /reads a clock Level 0 does not virtualize: process\.cpuUsage/, { 'v.txt': '2' });
    });

    test('G-1584 keygen: a test that generates a key pair is never reused', T, () => {
      const dir = proj(runner, 'keygen', { a: "test('key', () => { const { publicKey } = process.getBuiltinModule('node:crypto').generateKeyPairSync('ec', { namedCurve: 'P-256' }); expect(publicKey.asymmetricKeyType).toBe(fs.readFileSync('v.txt', 'utf8')); });" }, { 'v.txt': 'ec' });
      refusalIsSound(runner, dir, fileOf(runner, 'a'), /OS randomness drawn in native crypto/, { 'v.txt': 'rsa' });
    });

    test('G-2220 /proc: a test that reads /proc is never reused', T, () => {
      const dir = proj(runner, 'proc', { a: "test('proc', () => { expect(fs.readFileSync('/proc/self/stat', 'utf8').length > 0).toBe(true); expect(fs.readFileSync('v.txt', 'utf8')).toBe('1'); });" }, { 'v.txt': '1' });
      refusalIsSound(runner, dir, fileOf(runner, 'a'), /reads \/proc, \/sys or \/dev/, { 'v.txt': '2' });
    });

    test('G-2223 UDP: a test that sends UDP (to a local listener) is never reused', T, () => {
      const imp = runner === 'vitest' ? "import dgram from 'node:dgram';" : "const dgram = require('node:dgram');";
      const dir = proj(runner, 'udp', {
        a: `${imp}\ntest('udp', async () => { const srv = dgram.createSocket('udp4'); await new Promise((r) => srv.bind(0, '127.0.0.1', r)); const got = new Promise((r) => srv.once('message', (m) => r(String(m)))); const c = dgram.createSocket('udp4'); c.send(fs.readFileSync('v.txt', 'utf8'), srv.address().port, '127.0.0.1'); expect(await got).toBe('1'); c.close(); srv.close(); });`,
      }, { 'v.txt': '1' });
      refusalIsSound(runner, dir, fileOf(runner, 'a'), /UDP socket/, { 'v.txt': '2' });
    });

    test('G-1586 preload: a preload module that reads the clock before Level 0 makes the tests never reused', T, () => {
      const dir = proj(runner, 'preload', { a: "test('pre', () => { expect(globalThis.__preloadedAt > 0).toBe(true); expect(fs.readFileSync('v.txt', 'utf8')).toBe('1'); });" }, {
        'pre.cjs': 'globalThis.__preloadedAt = Date.now();\n', 'v.txt': '1',
      });
      const env = { NODE_OPTIONS: `--require ${path.join(dir, 'pre.cjs')}` };
      // Since `--det` is parallel by default (row JS-07, gap G-1044) a Jest run with a NODE_OPTIONS preload
      // refuses the WHOLE project, not just this file: the preload runs in each worker before the capture, so
      // what it reads is not observed (node/src/jest/cli.js). That refusal is strictly stronger than the per-file
      // one this test was first written for -- nothing of the project is reused -- so it is what Jest must say
      // here, and the rest of refusalIsSound still has to hold. What the coarser refusal costs in reuse is
      // measured in docs/LIMITS.md P5. Vitest wraps its own workers and still gives the per-file reason.
      const why = runner === 'jest'
        ? /NODE_OPTIONS preloads run in Jest workers before the capture/
        : /a preload module read the clock or OS entropy before Level 0/;
      refusalIsSound(runner, dir, fileOf(runner, 'a'), why, { 'v.txt': '2' },
        { env, whyIn: runner === 'jest' ? 'misses' : 'not_cached_detail' });
    });

    test('G-1585 loader: an off-thread loader (module.register in an --import preload) makes the tests never reused, and no longer breaks the run', T, () => {
      if (runner === 'jest') return; // Jest's module registry loads modules itself, not through Node's loader
      // an installed package loaded natively by Node (Vitest externalizes node_modules), rewritten by a loader from
      // data.txt, a file read in the loader thread (not observable)
      const dir = proj(runner, 'loader', { a: "import { v } from 'ldpkg';\ntest('loaded', () => { expect(v).toBe(1); });" }, {
        'node_modules/ldpkg/package.json': '{"name":"ldpkg","version":"1.0.0","type":"module","main":"index.mjs"}',
        'node_modules/ldpkg/index.mjs': 'export const v = 0;\n',
        'hooks.mjs': "import fs from 'node:fs';\nexport async function load(url, ctx, next) { const r = await next(url, ctx); if (url.endsWith('/ldpkg/index.mjs')) return { ...r, source: `export const v = ${fs.readFileSync(new URL('./data.txt', import.meta.url), 'utf8').trim()};` }; return r; }\n",
        'reg.mjs': "import { register } from 'node:module';\nregister('./hooks.mjs', import.meta.url);\n",
        'data.txt': '1',
      });
      const env = { NODE_OPTIONS: `--import ${path.join(dir, 'reg.mjs')}` };
      // the run itself under --det-cache: the worker used to die (in-thread and off-thread hooks mixed)
      refusalIsSound(runner, dir, fileOf(runner, 'a'), /off-thread module loader/, { 'data.txt': '2' }, { env });
    });

    test('G-2222 net-record: a --det-record session records nothing in the cache; its results are never reused', T, async () => {
      const srv = spawn(process.execPath, [path.join(__dirname, 'counter-server.js')], { stdio: ['ignore', 'pipe', 'inherit'] });
      const ports = await new Promise((resolve) => srv.stdout.once('data', (d) => resolve(JSON.parse(String(d)))));
      try {
        const imp = runner === 'vitest' ? "import http from 'node:http';" : "const http = require('node:http');";
        const dir = proj(runner, 'net-record', {
          a: `${imp}
const lookup = (h, o, cb) => { if (typeof o === 'function') cb = o; return o && o.all ? cb(null, [{ address: '127.0.0.1', family: 4 }]) : cb(null, '127.0.0.1', 4); };
test('first answer', async () => {
  const b = await new Promise((resolve, reject) => http.get({ host: 'counter.detjs.test', port: Number(process.env.COUNTER_PORT), path: '/x', lookup }, (r) => { let s = ''; r.on('data', (d) => { s += d; }); r.on('end', () => resolve(s)); }).on('error', reject));
  expect(b).toMatch(/^response #1\\b/);
});`,
        });
        const env = { COUNTER_PORT: String(ports.http) };
        const det = ['--det', '--det-record'];
        const r1 = run(runner, dir, [], { det, env });
        assert.equal(r1.status, 0, show(r1));
        assert.match(JSON.stringify(r1.summary.not_cached_detail), /network recording \(--det-record\)/, show(r1));
        // the live server has moved on: a fresh recording fails, and the cached recording run must fail too
        const r2 = run(runner, dir, [], { det, env });
        assert.ok(!reused(r2).includes(fileOf(runner, 'a')), `WRONG REUSE of a recorded result\n${show(r2)}`);
        assert.notEqual(r2.status, 0, show(r2));
      } finally { srv.kill(); }
    });
  });
}

describe('tap: env-unobserved refusal (G-2221)', () => {
  test('G-2221: a test whose own code reads a variable tap sets per process is never reused; a change is never missed', T, () => {
    const B = require('./runner-b-cases');
    B.depsDir();
    const dir = B.fixture('tap', 'env-unobserved', {
      'test/env.test.js': "const t = require('tap'); const fs = require('node:fs');\nt.ok(process.env.TAP_CHILD_ID !== undefined);\nt.equal(fs.readFileSync('v.txt', 'utf8'), '1');\n",
      'v.txt': '1',
    });
    const r1 = B.crun('tap', dir);
    assert.equal(r1.status, 0, B.show(r1));
    assert.match(JSON.stringify(r1.summary.not_cached_detail), /environment reads not observable in this process: TAP_CHILD_ID/, B.show(r1));
    const r2 = B.crun('tap', dir);
    assert.ok(!B.reused(r2).includes('test/env.test.js'), B.show(r2));
    B.write(dir, { 'v.txt': '2' });
    const fresh = B.crun('tap', dir, { cache: false });
    assert.notEqual(fresh.status, 0, B.show(fresh));
    const r3 = B.crun('tap', dir);
    assert.ok(!B.reused(r3).includes('test/env.test.js'), `WRONG REUSE\n${B.show(r3)}`);
    assert.notEqual(r3.status, 0, B.show(r3));
  });
});

describe('bun: dynamic-import refusal (G-1583)', { skip: (() => { try { return spawnSync('bun', ['--version']).status === 0 ? false : 'bun not found'; } catch { return 'bun not found'; } })() }, () => {
  test('G-1583: an import() whose target is not a literal is never reused; its target changing changes the result', T, () => {
    const H = require('./runtime-helpers');
    const dir = H.fixture('bun', 'dynamic-import', {
      'lib/one.js': 'export const v = 1;\n',
      'tests/dyn.test.ts': "import { test, expect } from 'bun:test';\nconst name = ['o', 'ne'].join('');\ntest('dyn', async () => { const m = await import(`../lib/${name}.js`); expect(m.v).toBe(1); });\n",
    });
    const r1 = H.crun('bun', dir);
    assert.equal(r1.status, 0, H.show(r1));
    assert.match(JSON.stringify(r1.summary.not_cached_detail), /dynamic import whose target is not known/, H.show(r1));
    const r2 = H.crun('bun', dir);
    assert.ok(!H.reused(r2).includes('tests/dyn.test.ts'), H.show(r2));
    H.write(dir, { 'lib/one.js': 'export const v = 2;\n' });
    const fresh = H.crun('bun', dir, { cache: false });
    assert.notEqual(fresh.status, 0, H.show(fresh));
    const r3 = H.crun('bun', dir);
    assert.ok(!H.reused(r3).includes('tests/dyn.test.ts'), `WRONG REUSE\n${H.show(r3)}`);
    assert.notEqual(r3.status, 0, H.show(r3));
  });
});
