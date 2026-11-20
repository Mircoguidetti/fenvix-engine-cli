'use strict';
// `detjs node-test` (the node:test runner): control tests (determinism, Level 0 inside test processes, isolation)
// and adversarial wrong-reuse tests (review r021 F1-F8 and held cases, R-009/R-017 holes, node:test specifics).
// Run: cd node && node --test --test-concurrency=1 test/runner-node-test.test.js
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { write, fixture, crun, show, reused, noWrongReuse, notCached, trace, TMP } = require('./runner-helpers');

const T = { timeout: 600000 };
const R = 'node-test';
const HEAD = "import { test, describe, it, before, after, mock } from 'node:test'; import assert from 'node:assert/strict'; import fs from 'node:fs'; import path from 'node:path';";
const CJS = "const { test, describe, it } = require('node:test'); const assert = require('node:assert/strict'); const fs = require('node:fs'); const path = require('node:path');";
const F = (n) => `tests/${n}.test.mjs`;
const tf = (n, body) => ({ [F(n)]: `${HEAD}\n${body}\n` });
const proj = (name, files) => fixture('runner-node-test', name, files);

describe('node-test: control', () => {
  test('two --det runs give identical fingerprints; a seed gives a reproducible shuffle, another seed another order', T, () => {
    const body = [
      "const seen = [];",
      "for (const n of ['a', 'b', 'c', 'd', 'e', 'f']) test(n, async () => { seen.push(n); await new Promise((r) => setTimeout(r, 5)); assert.ok(Date.now() > 0); Math.random(); });",
      "describe('group', () => { for (const n of ['x', 'y', 'z']) it(n, () => { performance.now(); Math.random(); }); });",
    ].join('\n');
    const dir = proj('determinism', { ...tf('one', body), ...tf('two', body), ...tf('three', body) });
    const run = (det) => { const r = crun(R, dir, [], { cache: false, det }); assert.equal(r.status, 0, show(r)); return trace(dir); };
    const a = run(['--det']);
    const b = run(['--det']);
    assert.equal(a.order.length, 27);
    assert.deepEqual(a.order, b.order);
    for (const id of a.order) assert.equal(a.tests[id].fingerprint, b.tests[id].fingerprint, `fingerprint of ${id}`);
    // fixed order: sorted files, declaration order
    assert.deepEqual(a.order.slice(0, 3), ['tests/one.test.mjs::a', 'tests/one.test.mjs::b', 'tests/one.test.mjs::c']);
    const s1 = run(['--det', '--det-seed=11']);
    const s1b = run(['--det', '--det-seed=11']);
    const s2 = run(['--det', '--det-seed=12']);
    assert.deepEqual(s1.order, s1b.order, 'same seed, same order');
    for (const id of s1.order) assert.equal(s1.tests[id].fingerprint, s1b.tests[id].fingerprint, `seeded fingerprint of ${id}`);
    assert.notDeepEqual(s1.order, s2.order, 'another seed, another order');
    assert.notDeepEqual(s1.order, a.order, 'the seed shuffles');
    assert.deepEqual([...s1.order].sort(), [...a.order].sort(), 'the same tests');
  });

  test('Level 0 inside the test processes: virtual clock at the epoch, seeded randomness, closed network', T, () => {
    const dir = proj('level0', tf('l0', [
      "test('clock', () => { assert.ok(Math.abs(Date.now() - Date.parse('2025-01-01T00:00:00Z')) < 1000, String(new Date())); });",
      "test('random', () => { fs.mkdirSync('out', { recursive: true }); fs.writeFileSync('out/r-' + process.env.RUN_N, String(Math.random())); });",
      "test('network', async () => { await assert.rejects(fetch('http://example.com/')); });",
    ].join('\n')));
    for (const n of ['1', '2']) {
      const r = crun(R, dir, [], { cache: false, env: { RUN_N: n } });
      assert.equal(r.status, 0, show(r));
    }
    const v1 = fs.readFileSync(path.join(dir, 'out', 'r-1'), 'utf8');
    assert.equal(v1, fs.readFileSync(path.join(dir, 'out', 'r-2'), 'utf8'), 'seeded Math.random');
    const penv = { ...process.env, RUN_N: '3' };
    delete penv.NODE_TEST_CONTEXT;
    const plain = spawnSync(process.execPath, ['--test', F('l0')], { cwd: dir, encoding: 'utf8', env: penv });
    assert.notEqual(plain.status, 0, 'without detjs the clock test fails (the controls are what makes it pass)');
  });

  test('--test-isolation=none: one process under --det; under --det-cache every file in its own process (outcome changes counted)', T, () => {
    const dir = proj('isolation-none', {
      ...tf('a', "globalThis.sharedByA = 1; test('a', () => {});"),
      ...tf('b', "test('b sees a', () => { assert.equal(globalThis.sharedByA, 1); });"),
    });
    const shared = crun(R, dir, ['--test-isolation=none'], { cache: false });
    assert.equal(shared.status, 0, `one process: b sees a's global\n${show(shared)}`);
    const t1 = trace(dir);
    const cached = crun(R, dir, ['--test-isolation=none']);
    assert.match(cached.stdout, /--test-isolation=none: under --det-cache every file runs in its own process/);
    const t2 = trace(dir);
    const changed = t1.order.filter((id) => t2.tests[id] && t2.tests[id].outcome !== t1.tests[id].outcome);
    assert.deepEqual(changed, ['tests/b.test.mjs::b sees a'], 'tests whose outcome changes under per-file isolation');
    assert.notEqual(cached.status, 0);
    assert.ok(!reused(crun(R, dir, ['--test-isolation=none'])).includes(F('b')), 'the failing file is never reused');
  });

  test('--det-cache-verify runs every file and compares each would-be reuse; failures are never reused', T, () => {
    const dir = proj('verify', {
      ...tf('ok', "test('ok', () => { assert.equal(fs.readFileSync('data/v.txt', 'utf8'), '1'); });"),
      ...tf('bad', "test('bad', () => { assert.fail('always'); });"),
      'data/v.txt': '1',
    });
    const r1 = crun(R, dir);
    assert.notEqual(r1.status, 0);
    const r2 = crun(R, dir, [], { verify: true });
    assert.equal(r2.summary.verify_mode, true);
    assert.ok(r2.summary.verified >= 2, show(r2));
    assert.equal(r2.summary.verify_mismatches.length, 0);
    assert.deepEqual(r2.summary.ran_files[F('ok')] && r2.summary.ran_files[F('ok')].ok, true, 'verify mode runs the file');
    assert.match(r2.summary.misses[F('bad')], /no recorded result/);
    const r3 = crun(R, dir);
    assert.deepEqual(reused(r3), [F('ok')]);
    assert.match(JSON.stringify(r1.summary.not_cached_detail), /outcome failed/);
  });

  test('every file reused: exit 0, the reporters still run (junit file written), receipts list the reuse', T, () => {
    const dir = proj('all-reused', { ...tf('a', "test('a', (t) => { const f = t.mock.fn(() => 2); assert.equal(f(), 2); });") });
    const args = ['--test-reporter=junit', '--test-reporter-destination=out.xml'];
    assert.equal(crun(R, dir, args).status, 0);
    fs.rmSync(path.join(dir, 'out.xml'), { force: true });
    const r = crun(R, dir, args);
    assert.equal(r.status, 0, show(r));
    assert.deepEqual(reused(r), [F('a')]);
    assert.ok(fs.existsSync(path.join(dir, 'out.xml')), 'the reporter destination is written');
    const rec = fs.readFileSync(path.join(dir, '.detjs', 'receipts.jsonl'), 'utf8');
    assert.match(rec, /"nodeid":"tests\/a\.test\.mjs::a","reused":true/);
  });

  test('reporter locations point to the test file, not detjs (node:test getCallerLocation)', T, () => {
    const dir = proj('locations', tf('loc', "\n\ntest('fails here', () => { throw new Error('x'); });"));
    const r = crun(R, dir, ['--test-reporter=spec'], { cache: false });
    assert.match(r.stdout, /test at tests\/loc\.test\.mjs:4:1/, show(r));
  });
});

describe('node-test: adversarial (review r021 translated)', () => {
  test('file content', T, () => {
    const dir = proj('content', { 'data/a.txt': 'one', ...tf('c', "test('c', () => { assert.equal(fs.readFileSync('data/a.txt', 'utf8'), 'one'); });") });
    noWrongReuse(R, dir, F('c'), { 'data/a.txt': 'two' });
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

  test('F1c lstat().isSymbolicLink(): a link replaced by a regular file', T, () => {
    const dir = proj('lstat', { 'data/target.txt': 't', ...tf('l', "test('l', () => { assert.equal(fs.lstatSync('data/entry').isSymbolicLink(), true); });") });
    fs.symlinkSync('target.txt', path.join(dir, 'data', 'entry'));
    noWrongReuse(R, dir, F('l'), () => { fs.rmSync(path.join(dir, 'data', 'entry')); fs.writeFileSync(path.join(dir, 'data', 'entry'), 't'); });
  });

  test('F2a readdir({ recursive: true }): a new file deep below', T, () => {
    const dir = proj('readdir-rec', { 'fixtures/cases/a/one.json': '1', ...tf('d', "test('d', () => { assert.equal(fs.readdirSync('fixtures/cases', { recursive: true }).length, 2); });") });
    noWrongReuse(R, dir, F('d'), { 'fixtures/cases/a/two.json': '2' });
  });

  test('F2b readdir({ withFileTypes: true }): a file becomes a directory', T, () => {
    const dir = proj('readdir-types', { 'fixtures/t/item': 'f', ...tf('d', "test('d', () => { assert.equal(fs.readdirSync('fixtures/t', { withFileTypes: true }).filter((e) => e.isFile()).length, 1); });") });
    noWrongReuse(R, dir, F('d'), () => { fs.rmSync(path.join(dir, 'fixtures', 't', 'item')); fs.mkdirSync(path.join(dir, 'fixtures', 't', 'item')); });
  });

  test('existence probe: a feature file appears', T, () => {
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

  test('F5 an optional ES module that appears (import() in try)', T, () => {
    const dir = proj('optional-esm', tf('o', "test('o', async () => { let v = 'none'; try { v = (await import('../lib/optional.mjs')).v; } catch {} assert.equal(v, 'none'); });"));
    noWrongReuse(R, dir, F('o'), { 'lib/optional.mjs': "export const v = 'here';\n" });
  });

  test('F5 an optional CommonJS module that appears (require in try)', T, () => {
    const dir = proj('optional-cjs', { 'tests/o.test.cjs': `${CJS}\ntest('o', () => { let v = 'none'; try { v = require('../lib/optional.cjs').v; } catch {} assert.equal(v, 'none'); });\n` });
    noWrongReuse(R, dir, 'tests/o.test.cjs', { 'lib/optional.cjs': "module.exports.v = 'here';\n" });
  });

  test('F8 a directory outside the project listed by a library after an await (no project frame on the stack)', T, () => {
    const outside = path.join(TMP, 'runner-node-test', 'outside-dir');
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

  test('held: a file read in a root after() hook (the file manifest covers it)', T, () => {
    const dir = proj('after-hook', { 'data/a.txt': 'a', ...tf('h', "test('h', () => {}); after(() => { assert.equal(fs.readFileSync('data/a.txt', 'utf8'), 'a'); });") });
    noWrongReuse(R, dir, F('h'), { 'data/a.txt': 'b' });
  });

  test('held: fs.globSync over a project directory', T, () => {
    const dir = proj('globsync', { 'fixtures/g/a.json': '1', ...tf('g', "test('g', () => { assert.equal(fs.globSync('fixtures/g/*.json').length, 1); });") });
    noWrongReuse(R, dir, F('g'), { 'fixtures/g/b.json': '2' });
  });
});

describe('node-test: adversarial (environment, processes, R-009 / R-017)', () => {
  test('environment variable read', T, () => {
    const dir = proj('env-read', tf('e', "test('e', () => { assert.equal(process.env.FIXTURE_LEVEL ?? 'unset', 'unset'); });"));
    noWrongReuse(R, dir, F('e'), null, { env3: { FIXTURE_LEVEL: 'x' } });
  });

  test('an environment name that is an Object.prototype property (process.env.constructor) is keyed, not a crash', T, () => {
    const dir = proj('env-proto', tf('e', "test('e', () => { assert.equal(typeof process.env.constructor, 'function'); assert.equal(process.env.FIXTURE_P ?? 'unset', 'unset'); });"));
    noWrongReuse(R, dir, F('e'), null, { env3: { FIXTURE_P: 'x' } });
  });

  test('environment enumeration', T, () => {
    const dir = proj('env-enum', tf('e', "test('e', () => { assert.equal(Object.keys(process.env).filter((k) => k.startsWith('FIXTURE_')).length, 0); });"));
    noWrongReuse(R, dir, F('e'), null, { env3: { FIXTURE_NEW: '1' } });
  });

  test('time zone (read by ICU, not through process.env)', T, () => {
    const dir = proj('tz', tf('z', "test('z', () => { assert.equal(new Date(0).getHours(), 0); });"));
    noWrongReuse(R, dir, F('z'), null, { env: { TZ: 'UTC' }, env3: { TZ: 'Asia/Tokyo' } });
  });

  test('child process: not cacheable', T, () => {
    const dir = proj('spawn', tf('p', "import { execFileSync } from 'node:child_process';\ntest('p', () => { assert.equal(execFileSync(process.execPath, ['-e', 'process.stdout.write(\"1\")']).toString(), '1'); });"));
    notCached(R, dir, F('p'), 'subprocess');
  });

  test('loopback socket: not cacheable', T, () => {
    const dir = proj('socket', tf('s', "import net from 'node:net';\ntest('s', async () => { const srv = net.createServer((c) => c.end('x')); await new Promise((r) => srv.listen(0, '127.0.0.1', r)); const c = net.connect(srv.address().port, '127.0.0.1'); await new Promise((r) => c.on('end', r).on('data', () => {})); srv.close(); });"));
    notCached(R, dir, F('s'), 'network connection');
  });

  test('a file another test file wrote: not cacheable', T, () => {
    const dir = proj('rw', {
      ...tf('a', "test('a', () => { fs.mkdirSync('out', { recursive: true }); fs.writeFileSync('out/shared.txt', 'v'); });"),
      ...tf('b', "test('b', () => { assert.equal(fs.readFileSync('out/shared.txt', 'utf8'), 'v'); });"),
    });
    notCached(R, dir, F('b'), 'written by tests/a.test.mjs');
  });

  test('stat().mtimeMs read by the test: not cacheable', T, () => {
    const dir = proj('mtime', { 'data/a.txt': 'a', ...tf('m', "test('m', () => { assert.ok(fs.statSync('data/a.txt').mtimeMs > 0); });") });
    notCached(R, dir, F('m'), 'mtimeMs');
  });

  test('R-009 exclusive create (wx): the path appears before the run', T, () => {
    const dir = proj('excl', tf('x', "test('x', () => { fs.mkdirSync('data', { recursive: true }); const fd = fs.openSync('data/lock', 'wx'); fs.closeSync(fd); fs.unlinkSync('data/lock'); });"));
    noWrongReuse(R, dir, F('x'), { 'data/lock': 'held' });
  });

  test('R-009 non-recursive mkdir: the directory exists before the run', T, () => {
    const dir = proj('mkdir', tf('m', "test('m', () => { fs.mkdirSync('work'); fs.rmdirSync('work'); });"));
    noWrongReuse(R, dir, F('m'), () => fs.mkdirSync(path.join(dir, 'work')));
  });

  test('R-009 interpreter shutdown: a file read in process.on("exit")', T, () => {
    const dir = proj('exit-read', { 'data/x.txt': 'ok', ...tf('x', "test('x', () => {}); process.on('exit', () => { if (fs.readFileSync('data/x.txt', 'utf8') !== 'ok') process.exitCode = 1; });") });
    noWrongReuse(R, dir, F('x'), { 'data/x.txt': 'changed' });
  });

  test('R-009 .git read directly', T, () => {
    const dir = proj('git-read', { '.git/HEAD': 'ref: refs/heads/main\n', ...tf('g', "test('g', () => { assert.match(fs.readFileSync('.git/HEAD', 'utf8'), /main/); });") });
    noWrongReuse(R, dir, F('g'), { '.git/HEAD': 'ref: refs/heads/other\n' });
  });

  test('R-017 sqlite file: URI: not cacheable', T, () => {
    const dir = proj('sqlite-uri', tf('u', "import { DatabaseSync } from 'node:sqlite';\ntest('u', () => { const db = new DatabaseSync('file:fixtures/u.db?mode=ro'); db.close(); });"));
    const { DatabaseSync } = require('node:sqlite');
    fs.mkdirSync(path.join(dir, 'fixtures'), { recursive: true });
    new DatabaseSync(path.join(dir, 'fixtures', 'u.db')).close();
    notCached(R, dir, F('u'), 'SQLite');
  });

  test('unwrapped read: an fs function taken by a NODE_OPTIONS --require module before detjs (moved after the preload)', T, () => {
    const dir = proj('early-ref', {
      'early.cjs': "const fs = require('node:fs'); globalThis.earlyRead = fs.readFileSync;\n",
      'data/a.txt': 'one',
      ...tf('u', "test('u', () => { assert.equal(globalThis.earlyRead('data/a.txt', 'utf8'), 'one'); });"),
    });
    noWrongReuse(R, dir, F('u'), { 'data/a.txt': 'two' }, { env: { NODE_OPTIONS: '--require ./early.cjs' } });
  });

  test('R-009 real clocks Level 0 does not virtualize (uptime, performance.timeOrigin, Intl format of now): not cacheable', T, () => {
    const dir = proj('real-clock', {
      ...tf('u', "test('u', () => { assert.ok(process.uptime() >= 0); });"),
      ...tf('o', "test('o', () => { assert.ok(performance.timeOrigin > 0); });"),
      ...tf('i', "test('i', () => { assert.ok(new Intl.DateTimeFormat('en', { year: 'numeric' }).format().length >= 4); });"),
    });
    notCached(R, dir, F('u'), 'process.uptime');
    const r = crun(R, dir);
    for (const [f, why] of [[F('o'), 'performance.timeOrigin'], [F('i'), 'Intl.DateTimeFormat']]) {
      assert.ok(!reused(r).includes(f), `${f} must not be reused\n${show(r)}`);
      assert.match(JSON.stringify(r.summary.not_cached_detail), new RegExp(why.replace('.', '\\.')));
    }
  });

  test('R-009 /dev/shm listed by the test: not cacheable', T, () => {
    const dir = proj('dev-shm', tf('d', "test('d', () => { assert.ok(Array.isArray(fs.readdirSync('/dev/shm'))); });"));
    notCached(R, dir, F('d'), '/dev/shm');
  });

  test('native binding reached directly (process.binding): not cacheable', T, () => {
    const dir = proj('binding', tf('b', "test('b', () => { process.binding('fs'); });"));
    notCached(R, dir, F('b'), 'process.binding');
  });
});

describe('node-test: adversarial (runner configuration, loaders, node:test features)', () => {
  test('a --require setup file changes', T, () => {
    const dir = proj('require-setup', { 'setup.cjs': "globalThis.LEVEL = 'a';\n", ...tf('s', "test('s', () => { assert.equal(globalThis.LEVEL, 'a'); });") });
    noWrongReuse(R, dir, F('s'), { 'setup.cjs': "globalThis.LEVEL = 'b';\n" }, { args: ['--require', './setup.cjs'] });
  });

  test('an --import setup module changes', T, () => {
    const dir = proj('import-setup', { 'setup.mjs': "globalThis.LEVEL = 'a';\n", ...tf('s', "test('s', () => { assert.equal(globalThis.LEVEL, 'a'); });") });
    noWrongReuse(R, dir, F('s'), { 'setup.mjs': "globalThis.LEVEL = 'b';\n" }, { args: ['--import', './setup.mjs'] });
  });

  test('--test-name-pattern selects other tests: no reuse under another selection', T, () => {
    const dir = proj('name-pattern', tf('p', "test('alpha', () => {}); test('beta', () => { assert.fail('beta fails'); });"));
    noWrongReuse(R, dir, F('p'), null, { args: ['--test-name-pattern=alpha'], args3: ['--test-name-pattern=beta'] });
  });

  test('--env-file content changes', T, () => {
    const dir = proj('env-file', { 'cfg/test.vars': 'FIXTURE_MODE=a\n', ...tf('v', "test('v', () => { assert.equal(process.env.FIXTURE_MODE, 'a'); });") });
    noWrongReuse(R, dir, F('v'), { 'cfg/test.vars': 'FIXTURE_MODE=b\n' }, { args: ['--env-file=cfg/test.vars'] });
  });

  test('--conditions added on the command line: another export of a package is resolved', T, () => {
    const dir = proj('conditions', {
      'node_modules/cond-pkg/package.json': JSON.stringify({ name: 'cond-pkg', exports: { custom: './custom.mjs', default: './default.mjs' } }),
      'node_modules/cond-pkg/custom.mjs': "export const v = 'custom';\n",
      'node_modules/cond-pkg/default.mjs': "export const v = 'default';\n",
      ...tf('c', "import { v } from 'cond-pkg';\ntest('c', () => { assert.equal(v, 'default'); });"),
    });
    noWrongReuse(R, dir, F('c'), null, { args3: ['--conditions=custom'] });
  });

  test('a --require loader package installed in node_modules changes (runtime identity)', T, () => {
    const dir = proj('loader-pkg', {
      'node_modules/fixture-loader/package.json': '{"name":"fixture-loader","main":"index.js"}',
      'node_modules/fixture-loader/index.js': "globalThis.LOADED = '1';\n",
      ...tf('l', "test('l', () => { assert.equal(globalThis.LOADED, '1'); });"),
    });
    noWrongReuse(R, dir, F('l'), { 'node_modules/fixture-loader/index.js': "globalThis.LOADED = '2';\n" }, { args: ['--require', 'fixture-loader'] });
  });

  test('type stripping: a .ts test and the .ts module it imports', T, () => {
    const dir = proj('strip-types', {
      'lib/h.ts': "export const v: number = 1;\n",
      'tests/t.test.ts': "import { test } from 'node:test'; import assert from 'node:assert/strict'; import { v } from '../lib/h.ts';\ntest('t', () => { assert.equal(v, 1); });\n",
    });
    noWrongReuse(R, dir, 'tests/t.test.ts', { 'lib/h.ts': 'export const v: number = 2;\n' });
  });

  test('tsx loader: tsconfig paths retargeted', T, () => {
    const dir = proj('tsx-paths', {
      'tsconfig.json': JSON.stringify({ compilerOptions: { baseUrl: '.', paths: { '@lib/*': ['lib/a/*'] } } }),
      'lib/a/v.ts': "export const v = 'a';\n",
      'lib/b/v.ts': "export const v = 'b';\n",
      'tests/p.test.ts': "import { test } from 'node:test'; import assert from 'node:assert/strict'; import { v } from '@lib/v';\ntest('p', () => { assert.equal(v, 'a'); });\n",
    });
    noWrongReuse(R, dir, 'tests/p.test.ts', { 'tsconfig.json': JSON.stringify({ compilerOptions: { baseUrl: '.', paths: { '@lib/*': ['lib/b/*'] } } }) },
      { args: ['--import', 'tsx', 'tests/p.test.ts'] });
  });

  test('ts-node register: a TypeScript module the test imports changes', T, () => {
    const dir = proj('ts-node', {
      'tsconfig.json': JSON.stringify({ compilerOptions: { module: 'commonjs', target: 'es2020', esModuleInterop: true } }),
      'lib/h.ts': 'export const v: number = 1;\n',
      'tests/t.test.cts': "import { test } from 'node:test'; import assert from 'node:assert/strict'; import { v } from '../lib/h';\ntest('t', () => { assert.equal(v, 1); });\n",
    });
    noWrongReuse(R, dir, 'tests/t.test.cts', { 'lib/h.ts': 'export const v: number = 2;\n' },
      { args: ['--no-experimental-strip-types', '--require', 'ts-node/register/transpile-only', 'tests/t.test.cts'] });
  });

  test('mock.module(): the mocked module disappears', T, () => {
    const dir = proj('mock-module', {
      'lib/dep.mjs': "export const v = 'real';\n",
      ...tf('m', "test('m', async (t) => { t.mock.module('../lib/dep.mjs', { namedExports: { v: 'mocked' } }); const { v } = await import('../lib/dep.mjs'); assert.equal(v, 'mocked'); });"),
    });
    noWrongReuse(R, dir, F('m'), { 'lib/dep.mjs': null }, { args: ['--experimental-test-module-mocks'] });
  });

  test('snapshot file (t.assert.snapshot) changes', T, () => {
    const dir = proj('snapshot', tf('s', "test('s', (t) => { t.assert.snapshot({ a: 1 }); });"));
    const u = crun(R, dir, ['--test-update-snapshots'], { cache: false });
    assert.equal(u.status, 0, show(u));
    const snap = path.join(dir, 'tests', 's.test.mjs.snapshot');
    assert.ok(fs.existsSync(snap));
    noWrongReuse(R, dir, F('s'), () => fs.writeFileSync(snap, fs.readFileSync(snap, 'utf8').replace('"a": 1', '"a": 2')));
  });

  test('a new test file matching the default pattern is found and run (failing file added)', T, () => {
    const dir = proj('glob-new', tf('a', "test('a', () => {});"));
    assert.equal(crun(R, dir).status, 0);
    assert.deepEqual(reused(crun(R, dir)), [F('a')]);
    write(dir, tf('b', "test('b', () => { assert.fail('new'); });"));
    const r = crun(R, dir);
    assert.notEqual(r.status, 0, show(r));
    assert.deepEqual(reused(r), [F('a')]);
    assert.ok(r.summary.ran_files[F('b')], 'the new file ran');
  });
});
