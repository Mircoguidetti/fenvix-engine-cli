'use strict';
// `detjs mocha`: control tests (determinism, Level 0 inside the tests, single process vs one process per file) and
// adversarial wrong-reuse tests (review r021 F1-F8 and held cases, R-009/R-017 holes, Mocha specifics: .mocharc,
// --require, --file, root hook plugins, --grep, ESM and CJS specs, TypeScript loaders).
// Run: cd node && node --test --test-concurrency=1 test/runner-mocha.test.js
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { write, fixture, crun, show, reused, noWrongReuse, notCached, trace, TMP } = require('./runner-helpers');

const T = { timeout: 600000 };
const R = 'mocha';
const HEAD = "import assert from 'node:assert/strict'; import fs from 'node:fs'; import path from 'node:path'; const test = (n, f) => it(n, f);";
const CJS = "const assert = require('node:assert/strict'); const fs = require('node:fs'); const path = require('node:path'); const test = (n, f) => it(n, f);";
const F = (n) => `test/${n}.spec.mjs`;
const tf = (n, body) => ({ [F(n)]: `${HEAD}\n${body}\n` });
const cf = (n, body) => ({ [`test/${n}.spec.cjs`]: `${CJS}\n${body}\n` });
const proj = (name, files) => fixture('runner-mocha', name, files);

describe('mocha: control', () => {
  test('two --det runs give identical fingerprints; a seed gives a reproducible shuffle, another seed another order', T, () => {
    const body = [
      "for (const n of ['a', 'b', 'c']) test(n, async () => { await new Promise((r) => setTimeout(r, 5)); assert.ok(Date.now() > 0); Math.random(); });",
      "describe('group', () => { for (const n of ['x', 'y', 'z']) it(n, () => { performance.now(); Math.random(); }); describe('inner', () => { it('i1', () => {}); it('i2', () => {}); }); });",
    ].join('\n');
    const dir = proj('determinism', { ...tf('one', body), ...tf('two', body), ...cf('three', body) });
    const run = (det, cache = false) => { const r = crun(R, dir, [], { cache, det }); assert.equal(r.status, 0, show(r)); return trace(dir); };
    const a = run(['--det']);
    const b = run(['--det']);
    assert.equal(a.order.length, 24);
    assert.deepEqual(a.order, b.order);
    for (const id of a.order) assert.equal(a.tests[id].fingerprint, b.tests[id].fingerprint, `fingerprint of ${id}`);
    const s1 = run(['--det', '--det-seed=5']);
    const s1b = run(['--det', '--det-seed=5']);
    const s2 = run(['--det', '--det-seed=6']);
    assert.deepEqual(s1.order, s1b.order, 'same seed, same order');
    for (const id of s1.order) assert.equal(s1.tests[id].fingerprint, s1b.tests[id].fingerprint, `seeded fingerprint of ${id}`);
    assert.notDeepEqual(s1.order, s2.order, 'another seed, another order');
    assert.deepEqual([...s1.order].sort(), [...a.order].sort());
    // --det-cache keeps Mocha's one process: the same order and fingerprints as --det (G-0148)
    fs.rmSync(path.join(dir, '.cache'), { recursive: true, force: true });
    const c = run(['--det'], true);
    assert.deepEqual(c.order, a.order, '--det-cache: one process, the order of --det');
    for (const id of a.order) assert.equal(c.tests[id].fingerprint, a.tests[id].fingerprint, `cached-run fingerprint of ${id}`);
    // one process per file (--det-isolate) gives the same tests and fingerprints (the order differs: in one process
    // Mocha runs the top-level tests of every file before the suites)
    fs.rmSync(path.join(dir, '.cache'), { recursive: true, force: true });
    const p = run(['--det', '--det-isolate'], true);
    assert.deepEqual([...p.order].sort(), [...a.order].sort());
    fs.rmSync(path.join(dir, '.cache'), { recursive: true, force: true });
    assert.deepEqual(run(['--det', '--det-isolate'], true).order, p.order, 'per-file order is reproducible');
    for (const id of a.order) assert.equal(p.tests[id].fingerprint, a.tests[id].fingerprint, `per-file fingerprint of ${id}`);
  });

  test('Level 0 inside the tests: virtual clock at the epoch, seeded randomness, closed network', T, () => {
    const dir = proj('level0', tf('l0', [
      "test('clock', () => { assert.ok(Math.abs(Date.now() - Date.parse('2025-01-01T00:00:00Z')) < 1000, String(new Date())); });",
      "test('random', () => { fs.mkdirSync('out', { recursive: true }); fs.writeFileSync('out/r-' + process.env.RUN_N, String(Math.random())); });",
      "test('network', async () => { await assert.rejects(fetch('http://example.com/')); });",
    ].join('\n')));
    for (const n of ['1', '2']) {
      // opt-out of the host-values defaults (spec 2026-11-23): 2025 epoch, closed network
      const r = crun(R, dir, [], { cache: false, det: ['--det', '--det-epoch=fixed', '--det-net=closed'], env: { RUN_N: n } });
      assert.equal(r.status, 0, show(r));
    }
    assert.equal(fs.readFileSync(path.join(dir, 'out', 'r-1'), 'utf8'), fs.readFileSync(path.join(dir, 'out', 'r-2'), 'utf8'));
    const plain = crun(R, dir, [], { cache: false, det: [], env: { RUN_N: '3' } });
    assert.notEqual(plain.status, 0, 'without --det the clock test fails');
  });

  test('G-0148: one process under --det and --det-cache (the process is the cache unit); one process per file under --det-isolate (outcome changes counted)', T, () => {
    const dir = proj('isolation', {
      ...tf('a', "globalThis.sharedByA = 1; test('a', () => {});"),
      ...tf('b', "test('b sees a', () => { assert.equal(globalThis.sharedByA, 1); });"),
    });
    const single = crun(R, dir, [], { cache: false });
    assert.equal(single.status, 0, show(single));
    const t1 = trace(dir);
    // --det-cache: the verdict of Mocha's own model, never a false failure
    const c1 = crun(R, dir);
    assert.equal(c1.status, 0, `--det-cache keeps one process\n${show(c1)}`);
    const c2 = crun(R, dir);
    assert.deepEqual(reused(c2).sort(), [F('a'), F('b')], show(c2));
    // a change of a reruns b (b ran with a's state): the cached run agrees with a fresh run
    write(dir, tf('a', "globalThis.sharedByA = 2; test('a', () => {});"));
    const fresh = crun(R, dir, [], { cache: false });
    assert.notEqual(fresh.status, 0, show(fresh));
    const c3 = crun(R, dir);
    assert.notEqual(c3.status, 0, `b runs again with a's new state\n${show(c3)}`);
    assert.ok(!reused(c3).includes(F('b')), show(c3));
    write(dir, tf('a', "globalThis.sharedByA = 1; test('a', () => {});"));
    const per = crun(R, dir, [], { det: ['--det', '--det-isolate'] });
    assert.match(per.stdout, /every spec file runs in its own process/);
    const t2 = trace(dir);
    const changed = t1.order.filter((id) => t2.tests[id] && t2.tests[id].outcome !== t1.tests[id].outcome);
    assert.deepEqual(changed, ['test/b.spec.mjs::b sees a']);
    assert.notEqual(per.status, 0);
  });

  test('.mocharc parallel: true is turned off under --det', T, () => {
    const dir = proj('parallel-off', { '.mocharc.json': '{"parallel": true, "jobs": 4}', ...tf('a', "test('a', () => {});"), ...tf('b', "test('b', () => {});") });
    const r = crun(R, dir, [], { cache: false });
    assert.equal(r.status, 0, show(r));
    assert.match(r.stdout, /--parallel is off under --det/);
    assert.equal(trace(dir).order.length, 2);
  });

  test('--det-cache-verify runs every file and compares; failures are never reused; every file reused is a pass', T, () => {
    const dir = proj('verify', {
      ...tf('ok', "test('ok', () => { assert.equal(fs.readFileSync('data/v.txt', 'utf8'), '1'); });"),
      ...tf('bad', "test('bad', () => { assert.fail('always'); });"),
      'data/v.txt': '1',
    });
    // per-file units (--det-isolate): the failing file never blocks the passing one
    const det = ['--det', '--det-isolate'];
    assert.notEqual(crun(R, dir, [], { det }).status, 0);
    const v = crun(R, dir, [], { verify: true, det });
    assert.ok(v.summary.verified >= 2, show(v));
    assert.equal(v.summary.verify_mismatches.length, 0);
    const r3 = crun(R, dir, [], { det });
    assert.deepEqual(reused(r3), [F('ok')]);
    // the process unit (--det-cache alone): a failure in the run is never reused, nothing of it
    const u1 = crun(R, dir);
    assert.notEqual(u1.status, 0);
    assert.deepEqual(reused(crun(R, dir)), [], 'a run with a failure is never reused');
    write(dir, { [F('bad')]: null });
    assert.equal(crun(R, dir).status, 0);
    const u2 = crun(R, dir, ['--fail-zero']);
    assert.equal(u2.status, 0, `the whole run reused is a pass, even with --fail-zero\n${show(u2)}`);
    assert.deepEqual(reused(u2), [F('ok')], show(u2));
    const r4 = crun(R, dir, ['--fail-zero'], { det });
    assert.equal(r4.status, 0, `every file reused is a pass, even with --fail-zero\n${show(r4)}`);
    assert.deepEqual(reused(r4), [F('ok')]);
  });

  test('mochaGlobalSetup runs in the captured process under --det-cache: what it reads is an input', T, () => {
    const dir = proj('global-setup', {
      'fixtures.cjs': "const fs = require('node:fs'); exports.mochaGlobalSetup = () => { process.env.FIXTURE_FROM_SETUP = fs.readFileSync('data/s.txt', 'utf8'); };\n",
      'data/s.txt': 'a',
      ...tf('g', "test('g', () => { assert.equal(process.env.FIXTURE_FROM_SETUP, 'a'); });"),
    });
    const single = crun(R, dir, ['--require', './fixtures.cjs'], { cache: false });
    assert.equal(single.status, 0, show(single));
    noWrongReuse(R, dir, F('g'), { 'data/s.txt': 'b' }, { args: ['--require', './fixtures.cjs'] });
  });
});

describe('mocha: adversarial (review r021 translated)', () => {
  test('file content (CommonJS spec)', T, () => {
    const dir = proj('content', { 'data/a.txt': 'one', ...cf('c', "test('c', () => { assert.equal(fs.readFileSync('data/a.txt', 'utf8'), 'one'); });") });
    noWrongReuse(R, dir, 'test/c.spec.cjs', { 'data/a.txt': 'two' });
  });

  test('F1a stat().size', T, () => {
    const dir = proj('stat-size', { 'data/blob.bin': 'abc', ...tf('s', "test('s', () => { assert.equal(fs.statSync('data/blob.bin').size, 3); });") });
    noWrongReuse(R, dir, F('s'), { 'data/blob.bin': 'abcd' });
  });

  test('F1b realpath() of a retargeted link', T, () => {
    const dir = proj('realpath', { 'data/one.txt': 'x', 'data/two.txt': 'x', ...tf('r', "test('r', () => { assert.equal(path.basename(fs.realpathSync('data/current')), 'one.txt'); });") });
    fs.symlinkSync('one.txt', path.join(dir, 'data', 'current'));
    noWrongReuse(R, dir, F('r'), () => { fs.rmSync(path.join(dir, 'data', 'current')); fs.symlinkSync('two.txt', path.join(dir, 'data', 'current')); });
  });

  test('F1c lstat().isSymbolicLink()', T, () => {
    const dir = proj('lstat', { 'data/target.txt': 't', ...tf('l', "test('l', () => { assert.equal(fs.lstatSync('data/entry').isSymbolicLink(), true); });") });
    fs.symlinkSync('target.txt', path.join(dir, 'data', 'entry'));
    noWrongReuse(R, dir, F('l'), () => { fs.rmSync(path.join(dir, 'data', 'entry')); fs.writeFileSync(path.join(dir, 'data', 'entry'), 't'); });
  });

  test('F2a readdir({ recursive: true })', T, () => {
    const dir = proj('readdir-rec', { 'fixtures/cases/a/one.json': '1', ...tf('d', "test('d', () => { assert.equal(fs.readdirSync('fixtures/cases', { recursive: true }).length, 2); });") });
    noWrongReuse(R, dir, F('d'), { 'fixtures/cases/a/two.json': '2' });
  });

  test('F2b readdir({ withFileTypes: true })', T, () => {
    const dir = proj('readdir-types', { 'fixtures/t/item': 'f', ...tf('d', "test('d', () => { assert.equal(fs.readdirSync('fixtures/t', { withFileTypes: true }).filter((e) => e.isFile()).length, 1); });") });
    noWrongReuse(R, dir, F('d'), () => { fs.rmSync(path.join(dir, 'fixtures', 't', 'item')); fs.mkdirSync(path.join(dir, 'fixtures', 't', 'item')); });
  });

  test('existence probe', T, () => {
    const dir = proj('exists', tf('e', "test('e', () => { assert.equal(fs.existsSync('feature.flag'), false); });"));
    noWrongReuse(R, dir, F('e'), { 'feature.flag': '' });
  });

  test('F3a fs.openAsBlob', T, () => {
    const dir = proj('blob', { 'data/msg.txt': 'hi', ...tf('b', "test('b', async () => { assert.equal(await (await fs.openAsBlob('data/msg.txt')).text(), 'hi'); });") });
    noWrongReuse(R, dir, F('b'), { 'data/msg.txt': 'ho' });
  });

  test('F3b process.loadEnvFile', T, () => {
    const dir = proj('loadenv', { 'cfg/vars': 'FIXTURE_MODE=a\n', ...tf('v', "test('v', () => { process.loadEnvFile('cfg/vars'); assert.equal(process.env.FIXTURE_MODE, 'a'); });") });
    noWrongReuse(R, dir, F('v'), { 'cfg/vars': 'FIXTURE_MODE=b\n' });
  });

  test('F3c node:sqlite database', T, () => {
    const dir = proj('sqlite', tf('q', "import { DatabaseSync } from 'node:sqlite';\ntest('q', () => { const db = new DatabaseSync('fixtures/r.db', { readOnly: true }); const n = db.prepare('select count(*) as n from t').get().n; db.close(); assert.equal(n, 1); });"));
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
    noWrongReuse(R, dir, F('q'), () => mk(2));
  });

  test('F4 fs.cpSync of a fixture tree, then the copy is read', T, () => {
    const dir = proj('cp', {
      'fixtures/tpl/config.json': '{"v":1}',
      ...tf('cp', "test('cp', () => { const dst = path.join('out', 'c' + process.pid); fs.rmSync(dst, { recursive: true, force: true }); fs.cpSync('fixtures/tpl', dst, { recursive: true }); assert.equal(JSON.parse(fs.readFileSync(path.join(dst, 'config.json'), 'utf8')).v, 1); });"),
    });
    noWrongReuse(R, dir, F('cp'), { 'fixtures/tpl/config.json': '{"v":2}' });
  });

  test('F5 an optional ES module that appears', T, () => {
    const dir = proj('optional-esm', tf('o', "test('o', async () => { let v = 'none'; try { v = (await import('../lib/optional.mjs')).v; } catch {} assert.equal(v, 'none'); });"));
    noWrongReuse(R, dir, F('o'), { 'lib/optional.mjs': "export const v = 'here';\n" });
  });

  test('F5 an optional CommonJS module that appears', T, () => {
    const dir = proj('optional-cjs', cf('o', "test('o', () => { let v = 'none'; try { v = require('../lib/optional.cjs').v; } catch {} assert.equal(v, 'none'); });"));
    noWrongReuse(R, dir, 'test/o.spec.cjs', { 'lib/optional.cjs': "module.exports.v = 'here';\n" });
  });

  test('F8 a directory outside the project listed by a library after an await', T, () => {
    const outside = path.join(TMP, 'runner-mocha', 'outside-dir');
    fs.rmSync(outside, { recursive: true, force: true });
    fs.mkdirSync(outside, { recursive: true });
    fs.writeFileSync(path.join(outside, 'a.txt'), 'a');
    const dir = proj('outside-lib', {
      'node_modules/tinyglobby/package.json': '{"name":"tinyglobby","main":"index.js"}',
      'node_modules/tinyglobby/index.js': "const fs = require('node:fs'); module.exports.list = async (d) => { await new Promise((r) => setImmediate(r)); return (await fs.promises.readdir(d)).filter((n) => n.endsWith('.txt')); };\n",
      ...tf('g', `import { createRequire } from 'node:module'; const { list } = createRequire(import.meta.url)('tinyglobby');\ntest('g', async () => { assert.equal((await list(${JSON.stringify(outside)})).length, 1); });`),
    });
    noWrongReuse(R, dir, F('g'), () => fs.writeFileSync(path.join(outside, 'b.txt'), 'b'));
  });

  test('held: a file read in an after() hook', T, () => {
    const dir = proj('after-hook', { 'data/a.txt': 'a', ...tf('h', "test('h', () => {}); after(() => { assert.equal(fs.readFileSync('data/a.txt', 'utf8'), 'a'); });") });
    noWrongReuse(R, dir, F('h'), { 'data/a.txt': 'b' });
  });

  test('held: fs.globSync over a project directory', T, () => {
    const dir = proj('globsync', { 'fixtures/g/a.json': '1', ...tf('g', "test('g', () => { assert.equal(fs.globSync('fixtures/g/*.json').length, 1); });") });
    noWrongReuse(R, dir, F('g'), { 'fixtures/g/b.json': '2' });
  });
});

describe('mocha: adversarial (environment, processes, R-009 / R-017)', () => {
  test('environment variable read', T, () => {
    const dir = proj('env-read', tf('e', "test('e', () => { assert.equal(process.env.FIXTURE_LEVEL ?? 'unset', 'unset'); });"));
    noWrongReuse(R, dir, F('e'), null, { env3: { FIXTURE_LEVEL: 'x' } });
  });

  test('environment enumeration', T, () => {
    const dir = proj('env-enum', tf('e', "test('e', () => { assert.equal(Object.keys(process.env).filter((k) => k.startsWith('FIXTURE_')).length, 0); });"));
    noWrongReuse(R, dir, F('e'), null, { env3: { FIXTURE_NEW: '1' } });
  });

  test('time zone', T, () => {
    const dir = proj('tz', tf('z', "test('z', () => { assert.equal(new Date(0).getHours(), 0); });"));
    noWrongReuse(R, dir, F('z'), null, { args: ['--det-tz=keep'], env: { TZ: 'UTC' }, env3: { TZ: 'Asia/Tokyo' } });
  });

  test('child process: not cacheable', T, () => {
    const dir = proj('spawn', tf('p', "import { execFileSync } from 'node:child_process';\ntest('p', () => { assert.equal(execFileSync(process.execPath, ['-e', 'process.stdout.write(\"1\")']).toString(), '1'); });"));
    notCached(R, dir, F('p'), 'subprocess');
  });

  test('loopback socket: not cacheable', T, () => {
    const dir = proj('socket', tf('s', "import net from 'node:net';\ntest('s', async () => { const srv = net.createServer((c) => c.end('x')); await new Promise((r) => srv.listen(0, '127.0.0.1', r)); const c = net.connect(srv.address().port, '127.0.0.1'); await new Promise((r) => c.on('end', r).on('data', () => {})); srv.close(); });"));
    notCached(R, dir, F('s'), 'network connection');
  });

  test('a file another spec file wrote: not cacheable', T, () => {
    const dir = proj('rw', {
      ...tf('a', "test('a', () => { fs.mkdirSync('out', { recursive: true }); fs.writeFileSync('out/shared.txt', 'v'); });"),
      ...tf('b', "test('b', () => { assert.equal(fs.readFileSync('out/shared.txt', 'utf8'), 'v'); });"),
    });
    // --det-isolate (a process per spec file): the reader is not cacheable
    const det = ['--det', '--det-isolate'];
    const i1 = crun(R, dir, [], { det });
    assert.equal(i1.status, 0, show(i1));
    assert.ok(JSON.stringify(i1.summary.not_cached_detail).includes('written by test/a.spec.mjs'), show(i1));
    assert.ok(!reused(crun(R, dir, [], { det })).includes(F('b')));
    // one process (the process unit): the write is the unit's own; a change of the writer reruns the reader
    fs.rmSync(path.join(dir, '.cache'), { recursive: true, force: true });
    assert.equal(crun(R, dir).status, 0);
    assert.deepEqual(reused(crun(R, dir)).sort(), [F('a'), F('b')]);
    write(dir, tf('a', "test('a', () => { fs.mkdirSync('out', { recursive: true }); fs.writeFileSync('out/shared.txt', 'w'); });"));
    const u3 = crun(R, dir);
    assert.notEqual(u3.status, 0, show(u3));
    assert.ok(!reused(u3).includes(F('b')), show(u3));
  });

  test('stat().mtimeMs: keyed by its value', T, () => {
    // claude/all-runners-2: claude/node-cache-proof's review r021b fixes key a Stats field by its value (V:), so a
    // test that reads mtimeMs is cached and reruns when the value changes (claude/all-runners: never cached)
    const dir = proj('mtime', { 'data/a.txt': 'a', ...tf('m', "test('m', () => { assert.ok(fs.statSync('data/a.txt').mtimeMs < 1e12); });") });
    fs.utimesSync(path.join(dir, 'data', 'a.txt'), 6e8, 6e8);
    // claude/node (clock branch): a file time is a clock reading (clock-real), never cached; the change is never missed
    const r1 = crun(R, dir);
    assert.equal(r1.status, 0, show(r1));
    assert.ok(/reads a clock Level 0 does not virtualize|stat/.test(JSON.stringify(r1.summary.not_cached_detail)) || reused(crun(R, dir)).includes(F('m')), show(r1));
    fs.utimesSync(path.join(dir, 'data', 'a.txt'), 2e9, 2e9);
    const r3 = crun(R, dir);
    assert.notEqual(r3.status, 0, `WRONG REUSE\n${show(r3)}`);
    assert.ok(!reused(r3).includes(F('m')), show(r3));
  });

  test('R-009 exclusive create (wx)', T, () => {
    const dir = proj('excl', tf('x', "test('x', () => { fs.mkdirSync('data', { recursive: true }); const fd = fs.openSync('data/lock', 'wx'); fs.closeSync(fd); fs.unlinkSync('data/lock'); });"));
    noWrongReuse(R, dir, F('x'), { 'data/lock': 'held' });
  });

  test('R-009 interpreter shutdown: a file read in process.on("exit")', T, () => {
    const dir = proj('exit-read', { 'data/x.txt': 'ok', ...tf('x', "test('x', () => {}); process.on('exit', () => { if (fs.readFileSync('data/x.txt', 'utf8') !== 'ok') throw new Error('changed at exit'); });") });
    noWrongReuse(R, dir, F('x'), { 'data/x.txt': 'changed' });
  });

  test('R-017 sqlite file: URI: not cacheable', T, () => {
    const dir = proj('sqlite-uri', tf('u', "import { DatabaseSync } from 'node:sqlite';\ntest('u', () => { const db = new DatabaseSync('file:fixtures/u.db?mode=ro'); db.close(); });"));
    const { DatabaseSync } = require('node:sqlite');
    fs.mkdirSync(path.join(dir, 'fixtures'), { recursive: true });
    new DatabaseSync(path.join(dir, 'fixtures', 'u.db')).close();
    notCached(R, dir, F('u'), 'SQLite');
  });

  test('unwrapped read: an fs function taken by a NODE_OPTIONS --require module before detjs', T, () => {
    const dir = proj('early-ref', {
      'early.cjs': "const fs = require('node:fs'); globalThis.earlyRead = fs.readFileSync;\n",
      'data/a.txt': 'one',
      ...tf('u', "test('u', () => { assert.equal(globalThis.earlyRead('data/a.txt', 'utf8'), 'one'); });"),
    });
    noWrongReuse(R, dir, F('u'), { 'data/a.txt': 'two' }, { env: { NODE_OPTIONS: '--require ./early.cjs' } });
  });

  // R-009 made these real-clock reads not cacheable; since P-041 (audit G-0135, G-0136) Level 0 virtualizes them, so
  // they are clock reads keyed by the epoch: reused on the same epoch, never across a change of the epoch.
  test('R-009 uptime, performance.timeOrigin, Intl format of now: virtual, keyed by the epoch', T, () => {
    const dir = proj('real-clock', {
      ...tf('u', "test('u', () => { assert.ok(process.uptime() >= 0); });"),
      ...tf('o', "test('o', () => { assert.ok(performance.timeOrigin < Date.parse('2026-01-01')); });"),
      ...tf('i', "test('i', () => { assert.equal(new Intl.DateTimeFormat('en', { year: 'numeric', timeZone: 'UTC' }).format(), '2025'); });"),
    });
    const A = ['--det', '--det-epoch=2025-03-01T00:00:00Z'];
    const B = ['--det', '--det-epoch=2026-03-01T00:00:00Z'];
    const r1 = crun(R, dir, [], { det: A });
    assert.equal(r1.status, 0, show(r1));
    const r2 = crun(R, dir, [], { det: A });
    for (const f of [F('u'), F('o'), F('i')]) assert.ok(reused(r2).includes(f), `${f} reused on the same epoch\n${show(r2)}`);
    const fresh = crun(R, dir, [], { cache: false, det: B });
    assert.notEqual(fresh.status, 0, `the epoch decides o and i\n${show(fresh)}`);
    const r3 = crun(R, dir, [], { det: B });
    for (const f of [F('o'), F('i')]) assert.ok(!reused(r3).includes(f), `WRONG REUSE of ${f} across epochs\n${show(r3)}`);
    assert.notEqual(r3.status, 0, show(r3));
  });

  test('R-009 /dev/shm listed by the test: not cacheable', T, () => {
    const dir = proj('dev-shm', tf('d', "test('d', () => { assert.ok(Array.isArray(fs.readdirSync('/dev/shm'))); });"));
    notCached(R, dir, F('d'), '/dev/shm');
  });

  test('native binding reached directly: not cacheable', T, () => {
    const dir = proj('binding', tf('b', "test('b', () => { process.binding('fs'); });"));
    notCached(R, dir, F('b'), 'process.binding');
  });
});

describe('mocha: adversarial (configuration, --require, --file, root hooks, --grep, loaders)', () => {
  test('a --require setup file changes', T, () => {
    const dir = proj('require-setup', { 'setup.cjs': "globalThis.LEVEL = 'a';\n", ...tf('s', "test('s', () => { assert.equal(globalThis.LEVEL, 'a'); });") });
    noWrongReuse(R, dir, F('s'), { 'setup.cjs': "globalThis.LEVEL = 'b';\n" }, { args: ['--require', './setup.cjs'] });
  });

  test('.mocharc changes (another --require)', T, () => {
    const dir = proj('mocharc', {
      '.mocharc.json': '{"require": ["./a.cjs"]}', 'a.cjs': "globalThis.LEVEL = 'a';\n", 'b.cjs': "globalThis.LEVEL = 'b';\n",
      ...tf('s', "test('s', () => { assert.equal(globalThis.LEVEL, 'a'); });"),
    });
    noWrongReuse(R, dir, F('s'), { '.mocharc.json': '{"require": ["./b.cjs"]}' });
  });

  test('package.json "mocha" key changes', T, () => {
    const dir = proj('pkg-mocha', { 'a.cjs': "globalThis.LEVEL = 'a';\n", 'b.cjs': "globalThis.LEVEL = 'b';\n", ...tf('s', "test('s', () => { assert.equal(globalThis.LEVEL, 'a'); });") });
    write(dir, { 'package.json': JSON.stringify({ name: 'p', private: true, mocha: { require: ['./a.cjs'] } }) });
    noWrongReuse(R, dir, F('s'), { 'package.json': JSON.stringify({ name: 'p', private: true, mocha: { require: ['./b.cjs'] } }) });
  });

  test('a --file file (root hooks) changes', T, () => {
    const dir = proj('file-arg', { 'hooks.cjs': "before(() => { globalThis.LEVEL = 'a'; });\n", ...tf('s', "test('s', () => { assert.equal(globalThis.LEVEL, 'a'); });") });
    noWrongReuse(R, dir, F('s'), { 'hooks.cjs': "before(() => { globalThis.LEVEL = 'b'; });\n" }, { args: ['--file', './hooks.cjs'] });
  });

  test('a root hook plugin (mochaHooks) changes', T, () => {
    const dir = proj('root-hooks', { 'hooks.cjs': "exports.mochaHooks = { beforeEach() { globalThis.LEVEL = 'a'; } };\n", ...tf('s', "test('s', () => { assert.equal(globalThis.LEVEL, 'a'); });") });
    noWrongReuse(R, dir, F('s'), { 'hooks.cjs': "exports.mochaHooks = { beforeEach() { globalThis.LEVEL = 'b'; } };\n" }, { args: ['--require', './hooks.cjs'] });
  });

  test('--grep selects other tests: no reuse under another selection', T, () => {
    const dir = proj('grep', tf('p', "test('alpha', () => {}); test('beta', () => { assert.fail('beta fails'); });"));
    noWrongReuse(R, dir, F('p'), null, { args: ['--grep', 'alpha'], args3: ['--grep', 'beta'] });
  });

  test('a new spec file matching the glob is found and run', T, () => {
    const dir = proj('glob-new', { '.mocharc.json': '{"spec": ["test/**/*.spec.mjs"]}', ...tf('a', "test('a', () => {});") });
    assert.equal(crun(R, dir).status, 0);
    assert.deepEqual(reused(crun(R, dir)), [F('a')]);
    write(dir, { 'test/deep/b.spec.mjs': `${HEAD}\ntest('b', () => { assert.fail('new'); });\n` });
    const r = crun(R, dir);
    assert.notEqual(r.status, 0, show(r));
    // the process unit: the plan changed (a new file), the whole run runs again
    assert.deepEqual(reused(r), [], show(r));
    assert.match(r.summary.misses['<mocha>@@process'], /^config: changed .*plan/, show(r));
    // per-file units (--det-isolate): the new file runs, the old one is reused
    write(dir, { 'test/deep/b.spec.mjs': null });
    const det = ['--det', '--det-isolate'];
    assert.equal(crun(R, dir, [], { det }).status, 0);
    write(dir, { 'test/deep/b.spec.mjs': `${HEAD}\ntest('b', () => { assert.fail('new'); });\n` });
    const ri = crun(R, dir, [], { det });
    assert.notEqual(ri.status, 0, show(ri));
    assert.deepEqual(reused(ri), [F('a')], show(ri));
    assert.ok(ri.summary.ran_files['test/deep/b.spec.mjs'], show(ri));
  });

  test('--require ts-node/register: tsconfig change (strict null checks fail the compile)', T, () => {
    const cfg = (strict) => JSON.stringify({ compilerOptions: { module: 'commonjs', target: 'es2020', strict, esModuleInterop: true } });
    const dir = proj('ts-node', {
      'tsconfig.json': cfg(false),
      'test/t.spec.ts': "import { equal } from 'node:assert/strict';\ndeclare const it: (n: string, f: () => void) => void;\nfunction f(x: string | undefined): number { return x.length; }\nit('t', () => { equal(f('ab'), 2); });\n",
    });
    noWrongReuse(R, dir, 'test/t.spec.ts', { 'tsconfig.json': cfg(true) }, { args: ['--require', 'ts-node/register', '--extension', 'ts'], env: { TS_NODE_TYPE_CHECK: 'true' } });
  });

  test('--import tsx: tsconfig paths retargeted', T, () => {
    const dir = proj('tsx-paths', {
      'tsconfig.json': JSON.stringify({ compilerOptions: { baseUrl: '.', paths: { '@lib/*': ['lib/a/*'] } } }),
      'lib/a/v.ts': "export const v = 'a';\n",
      'lib/b/v.ts': "export const v = 'b';\n",
      'test/p.spec.ts': "import { equal } from 'node:assert/strict'; import { v } from '@lib/v';\ndeclare const it: (n: string, f: () => void) => void;\nit('p', () => { equal(v, 'a'); });\n",
    });
    noWrongReuse(R, dir, 'test/p.spec.ts', { 'tsconfig.json': JSON.stringify({ compilerOptions: { baseUrl: '.', paths: { '@lib/*': ['lib/b/*'] } } }) },
      { args: ['--import=tsx', '--extension', 'ts'] });
  });

  test('--require @swc-node/register: a TypeScript module the spec imports changes', T, () => {
    const dir = proj('swc', {
      'tsconfig.json': JSON.stringify({ compilerOptions: { module: 'commonjs', target: 'es2020' } }),
      'lib/h.ts': 'export const v: number = 1;\n',
      'test/t.spec.ts': "import { equal } from 'node:assert/strict'; import { v } from '../lib/h';\ndeclare const it: (n: string, f: () => void) => void;\nit('t', () => { equal(v, 1); });\n",
    });
    noWrongReuse(R, dir, 'test/t.spec.ts', { 'lib/h.ts': 'export const v: number = 2;\n' }, { args: ['--require', '@swc-node/register', '--extension', 'ts'] });
  });

  test('--require esbuild-register: a TypeScript module the spec imports changes', T, () => {
    const dir = proj('esbuild-register', {
      'lib/h.ts': 'export const v: number = 1;\n',
      'test/t.spec.ts': "import { equal } from 'node:assert/strict'; import { v } from '../lib/h';\ndeclare const it: (n: string, f: () => void) => void;\nit('t', () => { equal(v, 1); });\n",
    });
    noWrongReuse(R, dir, 'test/t.spec.ts', { 'lib/h.ts': 'export const v: number = 2;\n' }, { args: ['--require', 'esbuild-register', '--extension', 'ts'] });
  });
});
