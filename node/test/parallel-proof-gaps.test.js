'use strict';
// Three gaps of the parallel proof's hazard model (spec "parallel-proof-gaps", 2026-11-25): before these fixes a
// two-lane run reported no hazard, and so proven, when
//   (a) two lanes connect to the same local service (a database on 5432, a unix socket) that no lane listens on,
//   (b) a lane removes / copies / creates / lists / renames a directory recursively and another lane touches a
//       path inside it,
//   (c) a runner's cache directory from the project's configuration covers the project (`cacheDir: '.'`, `'..'`,
//       an in-repo `.cache/vite`, Jest `cacheDirectory: '<rootDir>'`): every path under it was invisible.
// Every integration test forces the two files into two lanes with an explicit plan (`--det-plan`), so the hazard
// does not depend on the planner, and checks the trace: the hazard (kind, path, both files) and the one-lane re-run
// of exactly the named files. Overlap in time is not needed: hazards come from footprints, not from timing.
const { test, describe, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const { spawnSync, spawn } = require('node:child_process');
const { BIN, TMP, readTrace } = require('./helpers');

const T = { timeout: 600000 };
const RUNNERS = (process.env.DETJS_TEST_RUNNERS || 'vitest,jest').split(',');
const EXT = { vitest: '.test.mjs', jest: '.test.js' };
const HEAD = {
  vitest: "import { test, expect } from 'vitest'; import fs from 'node:fs'; import path from 'node:path'; import net from 'node:net';",
  jest: "const fs = require('node:fs'); const path = require('node:path'); const net = require('node:net');",
};
const BASE = path.join(TMP, 'gaps');
fs.mkdirSync(BASE, { recursive: true }); // a fresh checkout has no .tmp/ (the mkdtemp cases below need the parent)

function write(dir, files) {
  for (const [name, body] of Object.entries(files)) {
    const p = path.join(dir, name);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, body);
  }
}

/** A project with two test files `x` and `y` forced into two lanes. `config`: extra top-level Vite / Jest keys. */
function project(runner, name, x, y, { config = {}, extra = {} } = {}) {
  const dir = path.join(BASE, runner, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  write(dir, { 'package.json': JSON.stringify({ name: `gaps-${name}`, private: true }) });
  if (runner === 'vitest') write(dir, { 'vitest.config.mjs': `export default ${JSON.stringify({ ...config, test: { include: ['tests/**/*.test.mjs'] } })};\n` });
  else write(dir, { 'jest.config.js': `module.exports = ${JSON.stringify({ testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node', ...config })};\n` });
  const ext = EXT[runner];
  write(dir, {
    [`tests/x${ext}`]: `${HEAD[runner]}\n${x}\n`,
    [`tests/y${ext}`]: `${HEAD[runner]}\n${y}\n`,
    'plan.json': JSON.stringify({ lanes: [[`tests/x${ext}`], [`tests/y${ext}`]] }),
    ...extra,
  });
  return dir;
}

function cleanEnv(extra = {}) {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_SEED', 'DETJS_CACHE_DIR', 'JEST_WORKER_ID', 'VITEST_POOL_ID', 'VITEST_WORKER_ID',
    'DETJS_FOOTPRINT_SKIP_DIRS', 'DETJS_CACHE_SKIP_DIRS', 'DETJS_HAZARD_RERUN', 'DETJS_HAZARD_RECURSIVE', 'DETJS_HAZARD_SHARED_SERVICE']) delete env[k];
  return { ...env, ...extra };
}

/** One `detjs <runner> --det --det-plan=plan.json` run (two lanes). Jest gets no --cacheDirectory: the config's counts. */
function det(runner, dir, { env = {}, args = [] } = {}) {
  fs.rmSync(path.join(dir, '.detjs', 'trace.jsonl'), { force: true });
  fs.rmSync(path.join(dir, '.detjs', 'plan-state.json'), { force: true });
  const runnerArgs = runner === 'vitest' ? ['run'] : [];
  const r = spawnSync(process.execPath, [BIN, runner, ...runnerArgs, '--det', '--det-epoch=fixed', '--det-plan=plan.json', ...args],
    { cwd: dir, encoding: 'utf8', env: cleanEnv(env), timeout: 300000 });
  let trace = null;
  try { trace = readTrace(path.join(dir, '.detjs', 'trace.jsonl')); } catch { /* none */ }
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '', trace };
}

const show = (r) => `status=${r.status}\nstdout=${r.stdout.slice(-2000)}\nstderr=${r.stderr.slice(-3000)}`;
const par = (r) => (r.trace && r.trace.header.meta.parallel) || {};

/** The run names a hazard of `kind` on `what` between the two files, and re-runs exactly those files in one lane. */
function assertHazard(runner, r, kind, what) {
  assert.ok(r.trace, `no trace: ${show(r)}`);
  const ext = EXT[runner];
  const files = [`tests/x${ext}`, `tests/y${ext}`];
  assert.equal(par(r).workers, 2, `the run must be in two lanes: ${show(r)}`);
  const hz = par(r).hazards || [];
  const hit = hz.find((h) => h.kind === kind && (what instanceof RegExp ? what.test(h.what) : h.what === what));
  assert.ok(hit, `expected a ${kind} hazard on ${what}; hazards=${JSON.stringify(hz)}\n${show(r)}`);
  assert.deepEqual([hit.a, hit.b].sort(), files, JSON.stringify(hit));
  const hr = r.trace.header.meta.hazard_rerun;
  assert.ok(hr, `the hazard files must run again in one lane: ${show(r)}`);
  assert.deepEqual(hr.files.slice().sort(), files, show(r));
  assert.equal(hr.complete, true, show(r));
}

function assertNoHazard(r) {
  assert.ok(r.trace, `no trace: ${show(r)}`);
  assert.equal(par(r).workers, 2, `the run must be in two lanes: ${show(r)}`);
  assert.deepEqual(par(r).hazards, [], show(r));
  assert.equal(r.trace.header.meta.hazard_rerun, undefined, show(r));
  assert.equal(r.status, 0, show(r));
  assert.ok(r.trace.tests.length >= 2 && r.trace.tests.every((t) => t.outcome === 'passed'), show(r));
}

// -- unit: hazards() on synthetic footprints ------------------------------------------------------------------

describe('hazards() unit: recursive roots, shared services', () => {
  const { hazards } = require('../src/parallel');
  const fp = (o) => ({ footprint: { w: [], r: [], l: [], listen: [], connect: [], ...o } });
  const run = (a, b) => hazards(new Map([['A', fp(a)], ['B', fp(b)]]), new Map([['A', 0], ['B', 1]]));
  const kinds = (h) => h.map((x) => `${x.kind} ${x.what}`);

  test('rm/rename/cp-dest recursive root D conflicts with a read, write or listing under D', () => {
    // protects=a recursive write root conflicts with everything inside; fails_when=a read of tmp/x.json in the other
    // lane is not a hazard; no_claim=synthetic footprints, not what the fs wrappers record (integration tests do)
    assert.deepEqual(kinds(run({ wr: ['tmp'] }, { r: ['tmp/x.json'] })), ['recursive-write tmp']);
    assert.deepEqual(kinds(run({ wr: ['tmp'] }, { w: ['tmp/a/b/c'] })), ['recursive-write tmp']);
    assert.deepEqual(kinds(run({ wr: ['tmp'] }, { l: ['tmp/a'] })), ['recursive-write tmp']);
    assert.deepEqual(kinds(run({ wr: ['tmp'] }, { r: ['tmp'] })), ['recursive-write tmp']);
    assert.deepEqual(kinds(run({ wr: ['tmp'] }, { wr: ['tmp/sub'] })), ['recursive-write tmp']);
    assert.deepEqual(kinds(run({ wr: ['tmp/sub'] }, { lr: ['tmp'] })).length, 1);
  });

  test('a listing of an ancestor of a recursive write root conflicts (the root appears or disappears)', () => {
    // protects=list of the parent vs rm -r of a child dir; fails_when=readdir('a') misses rm -r a/b; no_claim=synthetic
    assert.deepEqual(kinds(run({ wr: ['a/b'] }, { l: ['a'] })), ['recursive-write a/b']);
    assert.deepEqual(kinds(run({ wr: ['a/b/c'] }, { lr: ['a'] })).length, 1);
    // a plain read of the parent is not a listing
    assert.deepEqual(run({ wr: ['a/b'] }, { r: ['a'] }), []);
  });

  test('a plain listing conflicts with a recursive write root only as its parent; a recursive listing as any ancestor (B1)', () => {
    // protects=a plain listing sees only the direct children of its dir, so it sees a root D appear or disappear only
    // when it lists dirname(D); a recursive listing sees everything below it (founder decision 2026-11-25, B1; step M:
    // one test listing /tmp sent every file with a per-test dir under the run's tmpdir to the one-lane re-run);
    // fails_when=a plain listing of a grandparent is a hazard, or a plain listing of the parent / a recursive listing
    // of a grandparent is not; no_claim=synthetic footprints
    assert.deepEqual(run({ wr: ['a/b/c'] }, { l: ['a'] }), []);
    assert.deepEqual(run({ wr: ['a/b'] }, { l: ['.'] }), []);
    assert.deepEqual(kinds(run({ wr: ['a'] }, { l: ['.'] })), ['recursive-write a']);
    assert.deepEqual(kinds(run({ wr: ['a/b/c'] }, { l: ['a/b'] })), ['recursive-write a/b/c']);
    assert.deepEqual(kinds(run({ wr: ['a/b/c'] }, { lr: ['a'] })), ['recursive-write a/b/c']);
    assert.deepEqual(kinds(run({ wr: ['a/b/c'] }, { lr: ['.'] })), ['recursive-write a/b/c']);
    // absolute keys (outside the project): the run's tmpdir under /tmp
    assert.deepEqual(run({ wr: ['/tmp/pm-x/case-1'] }, { l: ['/tmp'] }), []);
    assert.deepEqual(run({ wr: ['/tmp/pm-x/case-1'] }, { l: ['/'] }), []);
    assert.deepEqual(kinds(run({ wr: ['/tmp/pm-x/case-1'] }, { l: ['/tmp/pm-x'] })), ['recursive-write /tmp/pm-x/case-1']);
    assert.deepEqual(kinds(run({ wr: ['/tmp/pm-x/case-1'] }, { lr: ['/tmp'] })), ['recursive-write /tmp/pm-x/case-1']);
    assert.deepEqual(kinds(run({ wr: ['/tmp/x'] }, { l: ['/tmp'] })), ['recursive-write /tmp/x']);
  });

  test('a recursive read root D (cp source, readdir recursive) conflicts with a write under D', () => {
    // protects=recursive read vs writes two levels down; fails_when=cp src / readdir -r vs write inside is missed; no_claim=synthetic
    assert.deepEqual(kinds(run({ lr: ['tree'] }, { w: ['tree/a/b/x.txt'] })), ['recursive-read tree']);
    assert.deepEqual(kinds(run({ lr: ['tree'] }, { w: ['tree'] })), ['recursive-read tree']);
    // two recursive reads do not conflict; a read inside a recursive read root does not either
    assert.deepEqual(run({ lr: ['tree'] }, { lr: ['tree'], r: ['tree/a'] }), []);
  });

  test('prefix matching is by path component: tmp does not match tmpdir/x (b-neg)', () => {
    // protects=no false hazard between siblings with a common prefix; fails_when=bare startsWith; no_claim=synthetic
    assert.deepEqual(run({ wr: ['tmp'] }, { r: ['tmpdir/x'], w: ['tmpdir/y'], l: ['tmpdir'] }), []);
    assert.deepEqual(run({ lr: ['tmp'] }, { w: ['tmpdir/x'] }), []);
    // keys of different forms never match: a root-relative key is not a prefix of an absolute one
    assert.deepEqual(run({ wr: ['tmp'] }, { r: ['/tmp/x'] }), []);
  });

  test('the same file in one lane: no hazard, whatever it touches', () => {
    // protects=hazards are cross-lane only; fails_when=a file conflicts with a file of its own lane; no_claim=synthetic
    const h = hazards(new Map([['A', fp({ wr: ['tmp'] })], ['B', fp({ r: ['tmp/x'] })]]), new Map([['A', 0], ['B', 0]]));
    assert.deepEqual(h, []);
  });

  test('two lanes connecting to one local port or unix socket: shared-service (a1, a2)', () => {
    // protects=a shared database / service is a hazard even when no lane listens; fails_when=connect matched only to
    // listeners; no_claim=synthetic keys (the connect wrapper's keys are checked by the integration tests)
    assert.deepEqual(kinds(run({ connect: ['5432'] }, { connect: ['5432'] })), ['shared-service 5432']);
    assert.deepEqual(kinds(run({ connect: ['unix:/run/pg/.s.PGSQL.5432'] }, { connect: ['unix:/run/pg/.s.PGSQL.5432'] })), ['shared-service unix:/run/pg/.s.PGSQL.5432']);
  });

  test('a tcp host pairs unless both files found its address public; loopback ports and unix sockets pair (founder decision "nome A", 2026-11-26)', () => {
    // protects=a service reached by a name or a non-public address is a shared service of the lanes; only an address
    // both files found public (listed in `pub`) is not paired; fails_when=a tcp key without `pub` is not paired, a key
    // both files list in `pub` is, or the loopback / unix pairing is lost; no_claim=a public host two lanes really
    // share (a staging database on a public IP) is not detected (known limit, D1 = A kept for public addresses)
    const pub = ['tcp:raw.githubusercontent.com:443'];
    assert.deepEqual(run({ connect: pub, pub }, { connect: pub, pub }), []);
    assert.deepEqual(kinds(run({ connect: pub, pub }, { connect: pub })), ['shared-service tcp:raw.githubusercontent.com:443']);
    assert.deepEqual(kinds(run({ connect: ['tcp:db.example.com:5432'] }, { connect: ['tcp:db.example.com:5432'] })), ['shared-service tcp:db.example.com:5432']);
    assert.deepEqual(kinds(run({ connect: ['43105'] }, { connect: ['43105'] })), ['shared-service 43105']);
    assert.deepEqual(kinds(run({ connect: ['unix:/run/docker.sock'] }, { connect: ['unix:/run/docker.sock'] })), ['shared-service unix:/run/docker.sock']);
  });

  test('different ports, sockets or hosts: no shared-service hazard; listen rules unchanged', () => {
    // protects=no false hazard; fails_when=any two connects conflict; no_claim=synthetic
    assert.deepEqual(run({ connect: ['5432'] }, { connect: ['6379'] }), []);
    assert.deepEqual(run({ connect: ['unix:/a.sock'] }, { connect: ['unix:/b.sock'] }), []);
    assert.deepEqual(run({ connect: ['tcp:a.example.com:5432'] }, { connect: ['tcp:b.example.com:5432'] }), []);
    assert.deepEqual(run({ connect: ['tcp:a.example.com:5432'] }, { connect: ['5432'] }), []);
    assert.deepEqual(kinds(run({ listen: ['4000'] }, { connect: ['4000'] })), ['port 4000']);
    assert.deepEqual(kinds(run({ listen: ['4000'] }, { listen: ['4000'] })), ['port 4000']);
  });

  test('footprints without the new sets (older markers) still work', () => {
    // protects=markers of an older engine do not crash collect; fails_when=f.wr undefined throws; no_claim=synthetic
    const old = (o) => ({ footprint: { w: [], r: [], l: [], listen: [], connect: [], ...o } });
    assert.deepEqual(hazards(new Map([['A', old({ w: ['x'] })], ['B', old({ r: ['x'] })]]), new Map([['A', 0], ['B', 1]])).map((h) => h.kind), ['read-write']);
  });

  test('scale: 400 files x 300 keys each match in well under a second', () => {
    // protects=prefix matching stays fast on big suites; fails_when=quadratic blow-up; no_claim=one synthetic shape
    const m = new Map(); const lanes = new Map();
    for (let i = 0; i < 400; i++) {
      const keys = Array.from({ length: 300 }, (_, j) => `src/f${i}/m${j}.js`);
      m.set(`t${i}`, fp({ r: keys, w: [`out/${i}/a.txt`], l: [`src/f${i}`], wr: [`tmp/${i}`], lr: [`fixtures/${i}`] }));
      lanes.set(`t${i}`, i % 4);
    }
    const t0 = process.hrtime.bigint();
    const h = hazards(m, lanes);
    const ms = Number(process.hrtime.bigint() - t0) / 1e6;
    assert.deepEqual(h, []);
    assert.ok(ms < 1500, `hazards() took ${ms} ms`);
  });
});

describe('connect wrapper unit: the keys a real socket connect records (a3)', () => {
  /** In a fresh process: install the recorder, record one "file" that opens the given connects, return its footprint. */
  const record = (connects, env = {}) => {
    const dir = fs.mkdtempSync(path.join(BASE, 'conn-'));
    const code = `
const net = require('node:net'); const parallel = require(${JSON.stringify(path.join(__dirname, '..', 'src', 'parallel'))});
parallel.installFootprint(process.cwd());
parallel.enter('f');
for (const c of ${JSON.stringify(connects)}) { const s = new net.Socket(); s.on('error', () => {}); try { s.connect(...c); } catch {} s.destroy(); }
parallel.leave('f');
process.stdout.write(require('node:fs').readFileSync(require('node:fs').readdirSync(process.env.DETJS_DIR + '/lanes').filter((n) => n.endsWith('.json')).map((n) => process.env.DETJS_DIR + '/lanes/' + n)[0], 'utf8'));`;
    const r = spawnSync(process.execPath, ['-e', code], { cwd: dir, encoding: 'utf8', env: cleanEnv({ DETJS_DIR: path.join(dir, 'run'), DETJS_WORKERS: '2', ...env }) });
    assert.equal(r.status, 0, r.stderr);
    return JSON.parse(r.stdout).footprint;
  };

  test('non-local host:port, loopback forms and unix paths get their own keys', () => {
    // protects=the keys hazards() matches are what a real net.Socket#connect records; fails_when=a remote service or a
    // unix socket records nothing, or a loopback alias is taken for a remote host; no_claim=no connection is made
    // (the hosts need not exist: the key is recorded before the connect)
    const fp = record([[{ host: 'DB.Example.com', port: 5432 }], [6379, 'redis.internal'], [{ host: '::ffff:127.0.0.1', port: 7000 }],
      [{ host: '[::1]', port: 7001 }], [{ path: '/run/x/s.sock' }], ['/run/x/t.sock'], [{ port: 7002 }]]);
    assert.deepEqual(fp.connect, ['7000', '7001', '7002', 'tcp:db.example.com:5432', 'tcp:redis.internal:6379', 'unix:/run/x/s.sock', 'unix:/run/x/t.sock']);
  });

  test('DETJS_HAZARD_SHARED_SERVICE=0 records only loopback ports, as release-1 did', () => {
    // protects=the measurement switch does what it says; fails_when=it changes nothing; no_claim=the runner side
    // (tests/test_runner_proof.py: a job with the variable gets no proof)
    const fp = record([[{ host: 'db.example.com', port: 5432 }], [{ path: '/run/x/s.sock' }], [{ host: '127.0.0.1', port: 7002 }]], { DETJS_HAZARD_SHARED_SERVICE: '0' });
    assert.deepEqual(fp.connect, ['7002']);
  });
});

describe('/review fixes (2026-11-26): symlinks, the root directory', () => {
  test('a path through a symlink records its literal key too, and a repointed link is resolved again per file (F1)', () => {
    // protects=a lane that writes cur/x after another file of its process repointed cur keeps the key release-1 gave
    // (cur/x) and the real key of the new target (v2/x), so a reader of either in another lane pairs with it;
    // fails_when=the real path of cur is cached from the first file (the write recorded under the old target v1/x,
    // no hazard with a reader of v2/x or cur/x); no_claim=a link repointed by another process during one file
    // (the literal key still pairs it)
    const dir = fs.mkdtempSync(path.join(BASE, 'fslink-'));
    write(dir, { 'v1/.keep': '', 'v2/.keep': '' });
    fs.symlinkSync('v1', path.join(dir, 'cur'));
    const code = `
const fs = require('node:fs'); const parallel = require(${JSON.stringify(path.join(__dirname, '..', 'src', 'parallel'))});
parallel.installFootprint(process.cwd());
parallel.enter('f1'); fs.writeFileSync('cur/x', '1'); parallel.leave('f1');
fs.unlinkSync('cur'); fs.symlinkSync('v2', 'cur');
parallel.enter('f2'); fs.writeFileSync('cur/x', '2'); parallel.leave('f2');
const d = process.env.DETJS_DIR + '/lanes';
process.stdout.write(JSON.stringify(fs.readdirSync(d).filter((n) => n.endsWith('.json')).map((n) => JSON.parse(fs.readFileSync(d + '/' + n, 'utf8')))));`;
    const r = spawnSync(process.execPath, ['-e', code], { cwd: dir, encoding: 'utf8', env: cleanEnv({ DETJS_DIR: path.join(dir, '.detjs', 'run'), DETJS_WORKERS: '2' }) });
    assert.equal(r.status, 0, r.stderr);
    const all = JSON.parse(r.stdout);
    const by = (k) => all.find((m) => m.file === k || m.label === k || m.key === k) || all[k === 'f1' ? 0 : 1];
    const w2 = by('f2').footprint.w;
    assert.ok(w2.includes('v2/x'), `the write of f2 lands in v2/x: ${JSON.stringify(all.map((m) => m.footprint.w))}`);
    assert.ok(w2.includes('cur/x'), `the literal key cur/x is kept: ${w2}`);
    assert.ok(!w2.includes('v1/x'), `v1/x is the old target: ${w2}`);
  });

  test('a recursive cp that creates a link: a read through it afterwards records the real target (/review delta, finding 1)', () => {
    // protects=fs.cp / cpSync copy symlinks as symlinks, so they change links like symlink() does: the real-path memo
    // filled before the copy must not key a later read through the copied link by its old (missing) path;
    // fails_when=the read of out/lnk/f is recorded only as out/lnk/f and not as shared/f, so a lane writing shared/f
    // pairs with nothing (a wrong identical); no_claim=a link another process creates (LIMITS PG2)
    const dir = fs.mkdtempSync(path.join(BASE, 'fslink4-'));
    write(dir, { 'shared/f': 'x', 'src/.keep': '' });
    fs.symlinkSync(path.join(dir, 'shared'), path.join(dir, 'src', 'lnk'));
    const code = `
const fs = require('node:fs'); const parallel = require(${JSON.stringify(path.join(__dirname, '..', 'src', 'parallel'))});
parallel.installFootprint(process.cwd());
parallel.enter('f'); fs.existsSync('out/lnk/f'); fs.cpSync('src', 'out', { recursive: true }); fs.readFileSync('out/lnk/f'); parallel.leave('f');
const d = process.env.DETJS_DIR + '/lanes';
process.stdout.write(fs.readFileSync(d + '/' + fs.readdirSync(d).filter((n) => n.endsWith('.json'))[0], 'utf8'));`;
    const r = spawnSync(process.execPath, ['-e', code], { cwd: dir, encoding: 'utf8', env: cleanEnv({ DETJS_DIR: path.join(dir, '.detjs', 'run'), DETJS_WORKERS: '2' }) });
    assert.equal(r.status, 0, r.stderr);
    const fp = JSON.parse(r.stdout).footprint;
    assert.ok(fp.r.includes('shared/f'), `the read through the copied link lands in shared/f: ${fp.r}`);
  });

  test('an unawaited fs.promises link change that fails is still an unhandled rejection (/review delta of 282bb9a4)', () => {
    // protects=the footprint never changes what the test's own calls do: a rejected fs.promises.unlink / rm / rename /
    // cp nobody awaits crashes the process serially, and must in a lane too; fails_when=the wrapper's own settle handler
    // on the user's promise marks the rejection handled (the run passes in lanes, a wrong green); no_claim=awaited calls
    const dir = fs.mkdtempSync(path.join(BASE, 'unh-'));
    const code = `
const fs = require('node:fs'); const parallel = require(${JSON.stringify(path.join(__dirname, '..', 'src', 'parallel'))});
parallel.installFootprint(process.cwd());
parallel.enter('f'); fs.promises.unlink('missing.txt');
setTimeout(() => { parallel.leave('f'); process.exit(0); }, 300);`;
    const r = spawnSync(process.execPath, ['-e', code], { cwd: dir, encoding: 'utf8', env: cleanEnv({ DETJS_DIR: path.join(dir, '.detjs', 'run'), DETJS_WORKERS: '2' }) });
    assert.notEqual(r.status, 0, `the unhandled ENOENT must end the process: status ${r.status}, ${r.stderr}`);
    assert.match(r.stderr, /ENOENT/);
  });

  test('a link repointed inside one file: the write after it records the new target (second /review pass, finding 2)', () => {
    // protects=the real-path memo is dropped when the file itself changes a link, so a later call through it records the
    // target it really reaches; fails_when=the memo filled by an earlier call of the same file records the old target
    // (T1/x) and a reader of T2/x in another lane pairs with nothing; no_claim=a link another process repoints while this
    // file runs (its literal key still pairs a lane that uses the link)
    const dir = fs.mkdtempSync(path.join(BASE, 'fslink2-'));
    write(dir, { 'T1/.keep': '', 'T2/.keep': '' });
    fs.symlinkSync('T1', path.join(dir, 'L'));
    const code = `
const fs = require('node:fs'); const parallel = require(${JSON.stringify(path.join(__dirname, '..', 'src', 'parallel'))});
parallel.installFootprint(process.cwd());
parallel.enter('f'); fs.existsSync('L/x'); fs.unlinkSync('L'); fs.symlinkSync('T2', 'L'); fs.writeFileSync('L/x', '2'); parallel.leave('f');
const d = process.env.DETJS_DIR + '/lanes';
process.stdout.write(fs.readFileSync(d + '/' + fs.readdirSync(d).filter((n) => n.endsWith('.json'))[0], 'utf8'));`;
    const r = spawnSync(process.execPath, ['-e', code], { cwd: dir, encoding: 'utf8', env: cleanEnv({ DETJS_DIR: path.join(dir, '.detjs', 'run'), DETJS_WORKERS: '2' }) });
    assert.equal(r.status, 0, r.stderr);
    const w = JSON.parse(r.stdout).footprint.w;
    assert.ok(w.includes('T2/x'), `the write lands in T2/x: ${w}`);
  });

  test('an async link swap in flight: a call during it does not cache the old target (third /review pass, finding 1)', () => {
    // protects=fs.promises / callback rename, symlink, unlink, rm change the link later than the call starts: the memo
    // is bypassed while such a call is pending and dropped when it settles; fails_when=an existsSync during the swap
    // caches the old target A and the write after the await is recorded as A/z, never B/z; no_claim=another process's swap
    const dir = fs.mkdtempSync(path.join(BASE, 'fslink3-'));
    write(dir, { 'A/.keep': '', 'B/.keep': '' });
    fs.symlinkSync('A', path.join(dir, 'cur'));
    fs.symlinkSync('B', path.join(dir, 'tmplink'));
    const code = `
const fs = require('node:fs'); const parallel = require(${JSON.stringify(path.join(__dirname, '..', 'src', 'parallel'))});
parallel.installFootprint(process.cwd());
(async () => {
  parallel.enter('f');
  // one threadpool thread, busy with a slow hash: the rename is queued behind it, so the existsSync runs before it
  const busy = new Promise((res) => require('node:crypto').pbkdf2('x', 'y', 200000, 32, 'sha256', res));
  const pr = fs.promises.rename('tmplink', 'cur'); fs.existsSync('cur/q'); await busy; await pr; fs.writeFileSync('cur/z', '1');
  parallel.leave('f');
  const d = process.env.DETJS_DIR + '/lanes';
  process.stdout.write(fs.readFileSync(d + '/' + fs.readdirSync(d).filter((n) => n.endsWith('.json'))[0], 'utf8'));
})();`;
    const r = spawnSync(process.execPath, ['-e', code], { cwd: dir, encoding: 'utf8', env: cleanEnv({ DETJS_DIR: path.join(dir, '.detjs', 'run'), DETJS_WORKERS: '2', UV_THREADPOOL_SIZE: '1' }) });
    assert.equal(r.status, 0, r.stderr);
    const fp = JSON.parse(r.stdout).footprint;
    assert.ok(fp.r.includes('A/q'), `the existsSync ran before the swap (else this test proves nothing): ${fp.r}`);
    assert.ok(fp.w.includes('B/z'), `the write lands in B/z: ${fp.w}`);
  });

  test('a listing or a recursive root at / pairs with keys directly under it (F6)', () => {
    // protects=the root directory is matched like any other; fails_when=the prefix of '/' is '//' and nothing is under
    // it; no_claim=synthetic keys
    const { hazards } = require('../src/parallel');
    const run = (a, b) => hazards(new Map([['A', { footprint: { w: [], r: [], l: [], listen: [], connect: [], ...a } }], ['B', { footprint: { w: [], r: [], l: [], listen: [], connect: [], ...b } }]]), new Map([['A', 0], ['B', 1]]));
    assert.deepEqual(run({ l: ['/'] }, { w: ['/x'] }).map((h) => `${h.kind} ${h.what}`), ['list-write /']);
    assert.deepEqual(run({ wr: ['/'] }, { r: ['/x/y'] }).map((h) => `${h.kind} ${h.what}`), ['recursive-write /']);
    assert.deepEqual(run({ lr: ['/'] }, { w: ['/x/y'] }).map((h) => `${h.kind} ${h.what}`), ['recursive-read /']);
  });
});

describe('connect wrapper + hazards(): tcp keys pair unless public (founder decision "nome A", 2026-11-26)', () => {
  const SRC = path.join(__dirname, '..', 'src', 'parallel');
  const { hazards } = require(SRC);
  const dns = require('node:dns');
  const os = require('node:os');
/** One file of one lane: connect to each [host, port], wait for the socket to settle (<= 1.5 s), return the footprint. */
function record(connects) {
  const dir = fs.mkdtempSync(path.join(BASE, 'd1h-'));
  const code = `
const net = require('node:net'); const parallel = require(${JSON.stringify(SRC)});
parallel.installFootprint(process.cwd());
(async () => {
  parallel.enter('f');
  await Promise.all(${JSON.stringify(connects)}.map(([host, port]) => new Promise((res) => {
    const s = new net.Socket(); const done = () => { clearTimeout(t); s.destroy(); res(); };
    const t = setTimeout(done, 1500);
    s.on('error', done); s.on('connect', done); s.on('lookup', () => setTimeout(done, 50));
    try { s.connect({ host, port }); } catch { done(); }
  })));
  parallel.leave('f');
  const d = process.env.DETJS_DIR + '/lanes';
  process.stdout.write(require('node:fs').readFileSync(d + '/' + require('node:fs').readdirSync(d).filter((n) => n.endsWith('.json'))[0], 'utf8'));
})();`;
  const r = spawnSync(process.execPath, ['-e', code], { cwd: dir, encoding: 'utf8', env: cleanEnv({ DETJS_DIR: path.join(dir, 'run'), DETJS_WORKERS: '2' }), timeout: 30000 });
  assert.equal(r.status, 0, r.stderr);
  return JSON.parse(r.stdout);
}

/** The hazards between a file of lane 0 and a file of lane 1 that both connect to `host:port`. */
function pair(host, port) {
  const a = record([[host, port]]);
  const b = record([[host, port]]);
  const h = hazards(new Map([['A', a], ['B', b]]), new Map([['A', 0], ['B', 1]]));
  return { kinds: h.map((x) => x.kind), a: a.footprint.connect, b: b.footprint.connect };
}

const resolvesPublic = (name) => new Promise((res) => dns.lookup(name, { all: true }, (e, xs) => res(!e && xs.length > 0 && xs.every((x) => !/^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|169\.254\.|::1$|f[cd]|fe80)/i.test(x.address)))));

  // protects=a local service reached by a name or a private address (CI service containers, docker-compose names,
  // host.docker.internal, the machine's own name, a docker bridge IP, link-local metadata) is a shared service of the
  // lanes; fails_when=only literal loopback forms pair (D1 as of 6ce73906); no_claim=a public host that two lanes
  // really share (a staging database on a public IP) is still not paired (the founder's D1 = A stays for those)
  for (const [what, host, port] of [
    ['a name that does not resolve (CI service container `postgres`, here postgres.invalid)', 'postgres.invalid', 5432],
    ['host.docker.internal (does not resolve outside Docker Desktop)', 'host.docker.internal', 5432],
    ["the machine's own hostname (resolves to a local address)", os.hostname(), 5432],
    ['a private IPv4 address (10/8)', '10.0.0.5', 5432],
    ['a docker bridge address (172.16/12)', '172.17.0.2', 6379],
    ['a 192.168/16 address', '192.168.1.20', 3306],
    ['a link-local address (169.254/16)', '169.254.169.254', 80],
    ['an IPv6 unique-local address (fc00::/7)', 'fd00::1', 5432],
    ['a 6to4 address with a private IPv4 inside (2002::/16; review delta F3)', '2002:c0a8:101::1', 5432],
    ['an IPv6 documentation address in 2000::/3 (3fff::/20; review delta F3)', '3fff::1', 5432],
  ]) {
    test(`two lanes connecting to ${what}: shared-service`, { timeout: 60000 }, async (t) => {
      // a machine whose own name resolves only to public addresses (some cloud VMs) is a public host: not this case
      if (host === os.hostname() && (await resolvesPublic(host))) { t.skip('this hostname resolves to public addresses only'); return; }
      const r = pair(host, port);
      assert.ok(r.kinds.includes('shared-service'), `expected a shared-service hazard; connect keys ${JSON.stringify(r)}`);
    });
  }

  /** One file of one lane running `body` (async, with `net` and `wait(socket)` in scope); returns the marker. */
  function recordJs(body) {
    const dir = fs.mkdtempSync(path.join(BASE, 'd1j-'));
    const code = `
const net = require('node:net'); const parallel = require(${JSON.stringify(SRC)});
parallel.installFootprint(process.cwd());
const wait = (s) => new Promise((res) => { const done = () => { clearTimeout(t); s.destroy(); res(); }; const t = setTimeout(done, 1500); s.on('error', done); s.on('connect', done); });
(async () => {
  parallel.enter('f');
  ${body}
  parallel.leave('f');
  const d = process.env.DETJS_DIR + '/lanes';
  process.stdout.write(require('node:fs').readFileSync(d + '/' + require('node:fs').readdirSync(d).filter((n) => n.endsWith('.json'))[0], 'utf8'));
})();`;
    const r = spawnSync(process.execPath, ['-e', code], { cwd: dir, encoding: 'utf8', env: cleanEnv({ DETJS_DIR: path.join(dir, 'run'), DETJS_WORKERS: '2' }), timeout: 30000 });
    assert.equal(r.status, 0, r.stderr);
    return JSON.parse(r.stdout);
  }
  const pairJs = (body) => {
    const a = recordJs(body); const b = recordJs(body);
    return { kinds: hazards(new Map([['A', a], ['B', b]]), new Map([['A', 0], ['B', 1]])).map((x) => x.kind), pub: [a.footprint.pub, b.footprint.pub] };
  };

  test('a name that resolves to a public and then a loopback address pairs (review delta F1: every address counts)', { timeout: 60000 }, () => {
    // protects=happy eyeballs (autoSelectFamily) tries every resolved address and can land on the private one: a name
    // is public only if every address its lookup reported is; fails_when=the first lookup event (a public address)
    // marks the key public in both lanes and the pair is skipped; no_claim=real DNS (a custom lookup gives the addresses)
    const r = pairJs(`const s = net.connect({ host: 'mixed.test', port: 5432, autoSelectFamily: true,
      lookup: (h, o, cb) => (o && o.all ? cb(null, [{ address: '2001:4860:4860::8888', family: 6 }, { address: '127.0.0.1', family: 4 }]) : cb(null, '2001:4860:4860::8888', 6)) });
    await wait(s);`);
    assert.ok(r.kinds.includes('shared-service'), JSON.stringify(r));
  });

  test('a name looked up public once and private once in one file pairs (review delta F2: every connect counts)', { timeout: 60000 }, () => {
    // protects=DNS round robin / rebinding: one public lookup does not make a key public when another connect of the
    // same file reached a private address; fails_when=pub is the union over the file's connects; no_claim=real DNS
    const look = (ip) => `(h, o, cb) => (o && o.all ? cb(null, [{ address: '${ip}', family: 4 }]) : cb(null, '${ip}', 4))`;
    const r = pairJs(`const a = net.connect({ host: 'flip.test', port: 5432, lookup: ${look('8.8.8.8')} }); await wait(a);
    const b = net.connect({ host: 'flip.test', port: 5432, lookup: ${look('10.0.0.1')} }); await wait(b);`);
    assert.ok(r.kinds.includes('shared-service'), JSON.stringify(r));
  });

  test('every special-purpose range is not public, the addresses just outside are (Testing pass: the range table)', { timeout: 60000 }, () => {
    // protects=each row of the not-public table (RFC 6890 IPv4, IPv6 outside 2000::/3, the non-global blocks inside it,
    // IPv4-mapped IPv6) pairs, and its prefix length is right; fails_when=a row is missing or its prefix is too short or
    // too long (an address inside is called public, or one outside is not); no_claim=names (classified at lookup:
    // tests above) and the founder's choice of which ranges are public
    const inside = ['0.1.2.3', '100.64.0.1', '100.127.255.254', '169.254.1.1', '172.31.255.254', '192.0.0.9', '192.0.2.1', '192.88.99.1',
      '198.18.0.1', '198.19.255.254', '198.51.100.1', '203.0.113.1', '224.0.0.1', '239.255.255.250', '240.0.0.1', '255.255.255.255',
      '::ffff:10.0.0.5', 'fe80::1', 'ff02::1', '2001::1', '2001:2::1', '2001:10::1', '2001:20::1', '2001:db8::1', '2002::1', '3fff:fff::1'];
    const outside = ['1.1.1.1', '100.63.255.254', '100.128.0.1', '172.15.255.254', '172.32.0.1', '192.0.1.1', '192.0.3.1', '198.17.255.254',
      '198.20.0.1', '223.255.255.254', '::ffff:8.8.8.8', '2001:1::1', '2001:3::1', '2001:4860:4860::8888', '2003::1', '3fff:1000::1'];
    const key = (ip) => `tcp:${ip}:5432`;
    const m = recordJs(`await Promise.all(${JSON.stringify([...inside, ...outside])}.map((host) => wait(net.connect({ host, port: 5432 }))));`);
    for (const ip of inside) assert.ok(m.footprint.connect.includes(key(ip)) && !m.footprint.pub.includes(key(ip)), `${ip} must pair: pub ${m.footprint.pub}`);
    for (const ip of outside) assert.ok(m.footprint.pub.includes(key(ip)), `${ip} is public: pub ${m.footprint.pub}`);
  });

  test('a name whose lookup returns after the file closed pairs, even if the address is public (Testing pass)', { timeout: 60000 }, () => {
    // protects=the founder's rule "a name whose class is unknown when the footprint closes pairs"; fails_when=a lookup
    // event after leave() still marks the key public, e.g. a name counted public until its lookup says otherwise (the
    // M2b mutation; dropping the cur === file check is an equivalent mutation: the marker is written at leave()); no_claim=real DNS timing
    const r = pairJs(`const s = net.connect({ host: 'late.test', port: 5432, lookup: (h, o, cb) => setTimeout(() => (o && o.all ? cb(null, [{ address: '8.8.8.8', family: 4 }]) : cb(null, '8.8.8.8', 4)), 300) });
    s.on('lookup', () => setImmediate(() => s.destroy())); s.on('error', () => {});`);
    assert.deepEqual(r.pub, [[], []], JSON.stringify(r));
    assert.ok(r.kinds.includes('shared-service'), JSON.stringify(r));
  });

  test('two lanes connecting to a public IP address: no hazard (D1 = A kept for public hosts)', { timeout: 60000 }, () => {
    const r = pair('185.199.111.133', 443);
    assert.deepEqual(r.kinds, [], JSON.stringify(r));
  });

  test('two lanes connecting to a name that resolves only to public addresses: no hazard', { timeout: 60000 }, async (t) => {
    if (!(await resolvesPublic('raw.githubusercontent.com'))) { t.skip('raw.githubusercontent.com does not resolve publicly here'); return; }
    const r = pair('raw.githubusercontent.com', 443);
    assert.deepEqual(r.kinds, [], JSON.stringify(r));
  });

  test('a different private address or port in each lane: no hazard', { timeout: 60000 }, () => {
    const a = record([['10.0.0.5', 5432]]); const b = record([['10.0.0.6', 5432]]);
    assert.deepEqual(hazards(new Map([['A', a], ['B', b]]), new Map([['A', 0], ['B', 1]])), []);
  });
});

describe('fs wrapper unit: the recursive roots real fs calls record', () => {
  const record = (env = {}) => {
    const dir = fs.mkdtempSync(path.join(BASE, 'fsrec-'));
    for (const f of ['src/a/x.txt', 'gone/y.txt', 'mv/z.txt', 'plain.txt']) write(dir, { [f]: 'x' });
    const code = `
const fs = require('node:fs'); const parallel = require(${JSON.stringify(path.join(__dirname, '..', 'src', 'parallel'))});
parallel.installFootprint(process.cwd());
parallel.enter('f');
fs.cpSync('src', 'dst', { recursive: true }); fs.rmSync('gone', { recursive: true, force: true }); fs.mkdirSync('deep/a/b', { recursive: true });
fs.mkdirSync('src/a', { recursive: true }); fs.mkdirSync(process.cwd(), { recursive: true }); fs.mkdirSync('src/a/new/x', { recursive: true });
fs.readdirSync('src', { recursive: true }); fs.renameSync('mv', 'moved'); fs.renameSync('plain.txt', 'plain2.txt'); fs.mkdirSync('flat'); fs.readdirSync('deep');
parallel.leave('f');
process.stdout.write(fs.readFileSync(fs.readdirSync(process.env.DETJS_DIR + '/lanes').filter((n) => n.endsWith('.json')).map((n) => process.env.DETJS_DIR + '/lanes/' + n)[0], 'utf8'));`;
    const r = spawnSync(process.execPath, ['-e', code], { cwd: dir, encoding: 'utf8', env: cleanEnv({ DETJS_DIR: path.join(dir, '.detjs', 'run'), DETJS_WORKERS: '2', ...env }) });
    assert.equal(r.status, 0, r.stderr);
    return JSON.parse(r.stdout).footprint;
  };

  test('recursive cp, rm, mkdir, readdir and a directory rename record wr / lr roots; plain calls do not', () => {
    // protects=what hazards() matches is what the wrappers record; a recursive mkdir records its root at the first
    // directory it creates (founder decision 2026-11-25, D1 = A) and none when the target exists (mkdir -p of an
    // existing dir changes nothing on disk); fails_when=a recursive call records no root, a recursive mkdir records
    // the target instead of its first missing ancestor or records an existing dir, or a file rename / plain mkdir /
    // plain readdir records one; no_claim=fs.promises and callback forms share the wrappers
    const fp = record();
    assert.deepEqual(fp.wr, ['deep', 'dst', 'gone', 'moved', 'mv', 'src/a/new']);
    assert.deepEqual(fp.lr, ['src']);
    for (const k of ['dst', 'gone', 'deep/a/b', 'flat', 'mv', 'moved']) assert.ok(fp.w.includes(k), `${k} in ${fp.w}`);
  });

  test("the recorder's own existence probes record no keys and are not calls of the test's fs", () => {
    // protects=the lstat probes of the mkdir / rename wrappers (is the target there, its first missing ancestor, is
    // the source a directory) are detjs' own: they add no read keys (no read-write hazard against a lane that writes
    // a checked ancestor) and a test's spy or mock on fs.lstatSync does not see them (/review of 298e80df, finding 1:
    // the probes looked fs.lstatSync up at call time, after the footprint and the test had wrapped it);
    // fails_when=a recursive mkdir records r keys for the directories it checked, or a spy installed by the test
    // counts calls the test did not make; no_claim=a mkdir of an existing directory, which is a read of it (C1)
    const fp = record();
    for (const k of ['deep', 'deep/a', 'deep/a/b', 'flat', 'src/a/new', 'src/a/new/x', 'moved']) assert.ok(!fp.r.includes(k), `${k} must not be a read: ${fp.r}`);
    const dir = fs.mkdtempSync(path.join(BASE, 'fsspy-'));
    const code = `
const fs = require('node:fs'); const parallel = require(${JSON.stringify(path.join(__dirname, '..', 'src', 'parallel'))});
parallel.installFootprint(process.cwd());
parallel.enter('f');
const orig = fs.lstatSync; let calls = 0; fs.lstatSync = function (...a) { calls++; return orig.apply(this, a); };
fs.mkdirSync('p/q/r', { recursive: true }); fs.mkdirSync('p/q', { recursive: true }); fs.renameSync('p', 'p2');
fs.lstatSync = orig;
parallel.leave('f');
process.stdout.write(String(calls));`;
    const r = spawnSync(process.execPath, ['-e', code], { cwd: dir, encoding: 'utf8', env: cleanEnv({ DETJS_DIR: path.join(dir, '.detjs', 'run'), DETJS_WORKERS: '2' }) });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(r.stdout, '0', 'the test made no lstatSync call');
  });

  test('a mkdir of a directory that exists records a read of it, not a write (C1)', () => {
    // protects=creating distinct children under one existing parent is not a write to the parent: mkdir -p of the
    // parent before writing a child changes nothing on disk (founder decision 2026-11-26, D2 = A; P2 BREAKDOWN C1:
    // write-write on the project root and on lerna-lite's e2e dir put whole suites in one lane); fails_when=the
    // existing src/a or the project root is a w key, or the new dirs flat / deep/a/b are not; no_claim=a mkdir that
    // races with another lane's create of the same dir (then one lane records w, the other r: a read-write hazard)
    const fp = record();
    for (const k of ['src/a', '.']) {
      assert.ok(!fp.w.includes(k), `${k} must not be a write: ${fp.w}`);
      assert.ok(fp.r.includes(k), `${k} must be a read: ${fp.r}`);
    }
    for (const k of ['flat', 'deep/a/b', 'src/a/new/x']) assert.ok(fp.w.includes(k), `${k} in ${fp.w}`);
  });

  test('DETJS_HAZARD_RECURSIVE=0 records no roots, as release-1 did', () => {
    // protects=the measurement switch; fails_when=it changes nothing; no_claim=the runner side (test_runner_proof.py)
    const fp = record({ DETJS_HAZARD_RECURSIVE: '0' });
    assert.deepEqual([fp.wr, fp.lr], [[], []]);
  });
});

describe('footprint skip dirs unit: only node_modules and tmpdir (c)', () => {
  const os = require('node:os');
  const { footprintSkip } = require('../src/parallel');
  const root = path.join(BASE, 'unit-root', 'proj');
  before(() => fs.mkdirSync(path.join(root, '.cache', 'vite'), { recursive: true }));
  const reasons = (dirs) => Object.fromEntries(footprintSkip(root, dirs).ignored.map((x) => [x.dir, x.reason]));

  test('the project root, its parent, a dir inside the project: ignored with a reason', () => {
    // protects=a config cache dir cannot hide project paths; fails_when=root/parent/.cache honoured; no_claim=the rule only (integration tests run it)
    const r = reasons([root, path.dirname(root), path.join(root, '.cache', 'vite'), path.join(root, 'fixtures')]);
    assert.equal(r[root], 'contains the project root');
    assert.equal(r[path.dirname(root)], 'contains the project root');
    assert.equal(r[path.join(root, '.cache', 'vite')], 'outside node_modules and tmpdir');
    assert.equal(r[path.join(root, 'fixtures')], 'outside node_modules and tmpdir');
  });

  test('a dir under node_modules (in the project) is honoured', () => {
    // protects=the safe default Vite cacheDir stays skipped; fails_when=node_modules/.vite ignored; no_claim=rule only
    const s = footprintSkip(root, [path.join(root, 'node_modules', '.vite-custom')]);
    assert.deepEqual(s.ignored, []);
    assert.ok(s.skip.includes(path.join(root, 'node_modules', '.vite-custom') + path.sep));
  });

  test('a dir under os.tmpdir() outside the project is honoured; tmpdir itself is not', () => {
    // protects=Jest's default /tmp/jest_* stays skipped, a cacheDir of /tmp itself does not hide all of /tmp;
    // fails_when=tmpdir honoured; no_claim=a tmpdir cache that tests also use for shared data stays a known limit
    const tmp = fs.realpathSync.native(os.tmpdir());
    const s = footprintSkip(root, [path.join(tmp, 'jest_rs'), tmp]);
    assert.ok(s.skip.includes(path.join(tmp, 'jest_rs') + path.sep));
    assert.deepEqual(s.ignored, [{ dir: tmp, reason: 'outside node_modules and tmpdir' }]);
  });

  test('a project that itself lives under tmpdir: its own dirs are still ignored', () => {
    // protects=fixtures in /tmp do not make every in-project cache dir safe; fails_when=tmpdir rule wins over project rule; no_claim=rule only
    const proj = fs.mkdtempSync(path.join(os.tmpdir(), 'gaps-proj-'));
    try {
      const r = Object.fromEntries(footprintSkip(proj, [path.join(proj, '.cache'), proj]).ignored.map((x) => [x.dir, x.reason]));
      assert.equal(r[fs.realpathSync.native(path.join(proj))], 'contains the project root');
      assert.equal(r[path.join(fs.realpathSync.native(proj), '.cache')], 'outside node_modules and tmpdir');
    } finally { fs.rmSync(proj, { recursive: true, force: true }); }
  });

  test('a relative dir is resolved against the project root, empty entries are dropped', () => {
    // protects=`cacheDir: '.'` means the root; fails_when=relative dirs resolved against the engine's cwd; no_claim=rule only
    const r = reasons(['.', '..', '', null]);
    assert.equal(r[root], 'contains the project root');
    assert.equal(r[path.dirname(root)], 'contains the project root');
  });
});

// -- integration: real two-lane runs ---------------------------------------------------------------------------

const tolerantRead = (p) => `try { fs.readFileSync(path.join(process.cwd(), ${JSON.stringify(p)}), 'utf8'); } catch { /* the other lane may have removed it */ }`;

for (const runner of RUNNERS) {
  describe(`${runner}: recursive directory operations (b)`, () => {
    test('(b1) rm -r of a dir in one lane, a read inside it in the other: recursive-write hazard, one-lane re-run', T, () => {
      // protects=rmSync(dir,{recursive}) conflicts with reads inside; fails_when=the run is proven with no hazard
      // (release-1: Node's rm walks the tree through public fs calls, so a file that exists at rm time gets its own
      // unlink key; a path inside that does not exist yet -- created later, or by the other lane -- matched nothing);
      // no_claim=the read here is of a path absent at rm time; the outcome interleaving itself is not forced
      const dir = project(runner, 'b1',
        "test('rm', () => { fs.rmSync(path.join(process.cwd(), 'tmp'), { recursive: true, force: true }); expect(1).toBe(1); });",
        `test('read', () => { ${tolerantRead('tmp/x.json')} expect(1).toBe(1); });`,
        { extra: { 'tmp/.keep': '' } });
      assertHazard(runner, det(runner, dir), 'recursive-write', 'tmp');
    });

    test('(b4) mkdir -p creating a new subtree in one lane, a write inside it in the other: recursive-write hazard', T, () => {
      // protects=mkdirSync(d,{recursive}) conflicts with writes inside the subtree it creates, rooted at the first
      // directory it creates (data/new); fails_when=proven with no hazard, or the root is the target (data/new/deep);
      // no_claim=the write may fail (its directory may not exist yet): the key is recorded before the call
      const dir = project(runner, 'b4',
        "test('mkdir', () => { fs.mkdirSync(path.join(process.cwd(), 'data', 'new', 'deep'), { recursive: true }); expect(1).toBe(1); });",
        "test('write', () => { try { fs.writeFileSync(path.join(process.cwd(), 'data', 'new', 'x.txt'), 'y'); } catch { /* not created yet */ } expect(1).toBe(1); });",
        { extra: { 'data/.keep': '' } });
      assertHazard(runner, det(runner, dir), 'recursive-write', 'data/new');
    });

    test('(b4-parent) mkdir -p creating a new subtree in one lane, a listing of its parent in the other: recursive-write hazard', T, () => {
      // protects=a listing of the parent sees the created subtree appear; fails_when=proven with no hazard (the plain
      // w key data/new/deep is no direct child of data, so list-write alone misses it); no_claim=none beyond protects
      const dir = project(runner, 'b4p',
        "test('mkdir', () => { fs.mkdirSync(path.join(process.cwd(), 'data', 'new', 'deep'), { recursive: true }); expect(1).toBe(1); });",
        "test('list', () => { fs.readdirSync(path.join(process.cwd(), 'data')); expect(1).toBe(1); });",
        { extra: { 'data/.keep': '' } });
      assertHazard(runner, det(runner, dir), 'recursive-write', 'data/new');
    });

    test('(b4-neg) mkdir -p of a dir that exists in one lane, a write inside it in the other: no hazard', T, () => {
      // protects=mkdir -p of an existing directory (a common setup step, e.g. of os.tmpdir() or the project root)
      // changes nothing on disk and does not send the files to the one-lane re-run (founder decision 2026-11-25,
      // D1 = A; step M: /tmp, the tmpdir and the project root roots cost up to +120 % wall time); fails_when=a
      // recursive-write hazard on data/a; no_claim=a dir removed and re-created by another lane in between (then
      // that lane's rm / mkdir records its own root)
      const dir = project(runner, 'b4n',
        "test('mkdir', () => { fs.mkdirSync(path.join(process.cwd(), 'data', 'a'), { recursive: true }); expect(1).toBe(1); });",
        "test('write', () => { fs.writeFileSync(path.join(process.cwd(), 'data', 'a', 'b', 'x.txt'), 'y'); expect(1).toBe(1); });",
        { extra: { 'data/a/b/.keep': '' } });
      assertNoHazard(det(runner, dir));
    });

    if (runner === 'vitest') {
      test('(b2) cp -r into a dir in one lane, a write inside the destination in the other: recursive-write hazard', T, () => {
        // protects=cpSync(src,dest,{recursive}) conflicts with writes inside dest; fails_when=proven with no hazard; no_claim=none beyond protects
        const dir = project(runner, 'b2',
          "test('cp', () => { fs.cpSync(path.join(process.cwd(), 'fixtures'), path.join(process.cwd(), 'out'), { recursive: true }); expect(1).toBe(1); });",
          "test('write', () => { fs.writeFileSync(path.join(process.cwd(), 'out', 'b.txt'), 'y'); expect(1).toBe(1); });",
          { extra: { 'fixtures/a.txt': 'a', 'out/.keep': '' } });
        assertHazard(runner, det(runner, dir), 'recursive-write', 'out');
      });

      test('(b3) cp -r from a dir in one lane, a write inside the source in the other: recursive-read hazard', T, () => {
        // protects=the cp source is read recursively; fails_when=proven with no hazard; no_claim=none beyond protects
        const dir = project(runner, 'b3',
          "test('cp', () => { fs.cpSync(path.join(process.cwd(), 'fixtures'), path.join(process.cwd(), 'out'), { recursive: true }); expect(1).toBe(1); });",
          "test('write', () => { fs.writeFileSync(path.join(process.cwd(), 'fixtures', 'sub', 'new.txt'), 'y'); expect(1).toBe(1); });",
          { extra: { 'fixtures/a.txt': 'a', 'fixtures/sub/.keep': '' } });
        assertHazard(runner, det(runner, dir), 'recursive-read', 'fixtures');
      });

      test('(b5) readdir recursive in one lane, a write two levels down in the other: recursive-read hazard', T, () => {
        // protects=readdirSync(d,{recursive}) sees deep writes; fails_when=only direct children matched; no_claim=none beyond protects
        const dir = project(runner, 'b5',
          "test('list', () => { expect(fs.readdirSync(path.join(process.cwd(), 'tree'), { recursive: true }).length).toBeGreaterThan(0); });",
          "test('write', () => { fs.writeFileSync(path.join(process.cwd(), 'tree', 'a', 'b', 'x.txt'), 'y'); expect(1).toBe(1); });",
          { extra: { 'tree/a/b/.keep': '' } });
        assertHazard(runner, det(runner, dir), 'recursive-read', 'tree');
      });

      test('(C1-distinct) mkdir -p of one existing dir in both lanes, then distinct children: no hazard', T, () => {
        // protects=distinct children of one directory do not conflict, though both files make sure the directory
        // exists first (P2 BREAKDOWN C1; founder decision 2026-11-26, D2 = A); fails_when=a write-write hazard on out;
        // no_claim=a create of the same child (C1-same) or a listing of the dir (C1-list) still conflicts
        const mk = (n) => `test('${n}', () => { const d = path.join(process.cwd(), 'out'); fs.mkdirSync(d, { recursive: true }); fs.writeFileSync(path.join(d, '${n}.txt'), '${n}'); expect(1).toBe(1); });`;
        const dir = project(runner, 'c1d', mk('x'), mk('y'), { extra: { 'out/.keep': '' } });
        assertNoHazard(det(runner, dir));
      });

      test('(C1-same) mkdir -p of one existing dir in both lanes, then the same child: write-write hazard', T, () => {
        // protects=the same child of the shared directory is still a conflict; fails_when=proven with no hazard; no_claim=none beyond protects
        const mk = (n) => `test('${n}', () => { const d = path.join(process.cwd(), 'out'); fs.mkdirSync(d, { recursive: true }); fs.writeFileSync(path.join(d, 'same.txt'), '${n}'); expect(1).toBe(1); });`;
        const dir = project(runner, 'c1s', mk('x'), mk('y'), { extra: { 'out/.keep': '' } });
        assertHazard(runner, det(runner, dir), 'write-write', 'out/same.txt');
      });

      test('(C1-list) a child created under an existing dir in one lane, a listing of the dir in the other: list-write hazard', T, () => {
        // protects=a listing of the directory still sees the created child (positive control for C1);
        // fails_when=proven with no hazard; no_claim=none beyond protects
        const dir = project(runner, 'c1l',
          "test('create', () => { const d = path.join(process.cwd(), 'out'); fs.mkdirSync(d, { recursive: true }); fs.writeFileSync(path.join(d, 'x.txt'), 'x'); expect(1).toBe(1); });",
          "test('list', () => { fs.readdirSync(path.join(process.cwd(), 'out')); expect(1).toBe(1); });",
          { extra: { 'out/.keep': '' } });
        assertHazard(runner, det(runner, dir), 'list-write', 'out');
      });

      test('(b7) rm -r of a dir in one lane, a plain listing of its grandparent in the other: no hazard (B1)', T, () => {
        // protects=a plain readdir of data sees only data's direct children, which rm -r of data/a/b does not change
        // (founder decision 2026-11-25, B1); fails_when=a recursive-write hazard on data/a/b; no_claim=the listing of
        // the parent and recursive listings of any ancestor still conflict (unit tests, b4-parent)
        const dir = project(runner, 'b7',
          "test('rm', () => { fs.rmSync(path.join(process.cwd(), 'data', 'a', 'b'), { recursive: true, force: true }); expect(1).toBe(1); });",
          "test('list', () => { fs.readdirSync(path.join(process.cwd(), 'data')); expect(1).toBe(1); });",
          { extra: { 'data/a/b/.keep': '' } });
        assertNoHazard(det(runner, dir));
      });

      test('(b7-rec) rm -r of a dir in one lane, a recursive listing of its grandparent in the other: recursive-write hazard (B1)', T, () => {
        // protects=a recursive readdir of data sees data/a/b go (positive control for b7: B1 keeps recursive listings
        // of any ancestor); fails_when=proven with no hazard; no_claim=which of the two kinds is reported (one hazard per
        // pair: the rm walk's unlink keys under data also meet the recursive listing as recursive-read)
        const dir = project(runner, 'b7r',
          "test('rm', () => { fs.rmSync(path.join(process.cwd(), 'data', 'a', 'b'), { recursive: true, force: true }); expect(1).toBe(1); });",
          "test('list', () => { fs.readdirSync(path.join(process.cwd(), 'data'), { recursive: true }); expect(1).toBe(1); });",
          { extra: { 'data/a/b/.keep': '' } });
        const r = det(runner, dir);
        const h = (par(r).hazards || []).find((x) => x.kind === 'recursive-read' || x.kind === 'recursive-write');
        assert.ok(h, show(r));
        assertHazard(runner, r, h.kind, h.kind === 'recursive-read' ? 'data' : 'data/a/b');
      });

      test('(b6) rename of a dir in one lane, a read inside the new name in the other: recursive-write hazard', T, () => {
        // protects=renameSync of a directory moves everything inside; fails_when=proven with no hazard; no_claim=none beyond protects
        const dir = project(runner, 'b6',
          "test('rename', () => { const c = process.cwd(); if (fs.existsSync(path.join(c, 'stage'))) fs.renameSync(path.join(c, 'stage'), path.join(c, 'final')); else fs.renameSync(path.join(c, 'final'), path.join(c, 'stage')); expect(1).toBe(1); });",
          "test('read', () => { fs.existsSync(path.join(process.cwd(), 'final', 'x.txt')); expect(1).toBe(1); });",
          { extra: { 'stage/x.txt': 'x' } });
        assertHazard(runner, det(runner, dir), 'recursive-write', 'final');
      });
    }
  });

  describe(`${runner}: skip dirs from the project configuration (c)`, () => {
    // (the directory is created by the fixture: a mkdir of the root or of the cache dir would be a conflict of its own)
    const writeShared = (rel, n) => `test('${n} writes', () => { fs.writeFileSync(path.join(process.cwd(), ${JSON.stringify(rel)}), '${n}'); expect(1).toBe(1); });`;
    const ignoredDirs = (r) => (par(r).skip_dirs_ignored || []).map((x) => x.dir);

    if (runner === 'vitest') {
      // MEASURED (Vitest 5.1.0, 2026-11-25): the shell's skip dir is the resolved `vite.config.cacheDir`, which Vitest
      // nests as `<cacheDir>/vitest/<sha1(project name)>` (the default project's name is '', sha1 da39a3ee...). So
      // `cacheDir: '.'` hides `<root>/vitest/<hash>/`, `'..'` hides `<parent>/vitest/<hash>/`, `.cache/vite` hides
      // `.cache/vite/vitest/<hash>/`: the conflict is put there, where release-1 records nothing.
      const sub = path.posix.join('vitest', require('node:crypto').createHash('sha1').update('').digest('hex'));
      for (const [name, cacheDir] of [['c1', '.'], ['c2', '..'], ['c3', '.cache/vite']]) {
        test(`(${name}) cacheDir ${JSON.stringify(cacheDir)}: ignored and recorded, a write-write conflict there is a hazard`, T, () => {
          // protects=a cacheDir in the project (or above it) does not hide project paths; fails_when=a write-write
          // conflict under it is invisible and the run proven; no_claim=Vite's own writes to its cache happen in the
          // main process (not a lane), so the conflict is the test files' own
          const dir0 = path.join(BASE, runner, name);
          const cache = path.join(path.resolve(dir0, cacheDir), ...sub.split('/'));
          const shared = path.join(cache, 'shared.json');
          const body = (n) => `test('${n} writes', () => { fs.writeFileSync(${JSON.stringify(shared)}, '${n}'); expect(1).toBe(1); });`;
          const dir = project(runner, name, body('x'), body('y'), { config: { cacheDir } });
          fs.mkdirSync(cache, { recursive: true });
          const real = fs.realpathSync.native(shared.slice(0, -'shared.json'.length));
          const key = real.startsWith(fs.realpathSync.native(dir) + path.sep) ? path.relative(fs.realpathSync.native(dir), real).split(path.sep).join('/') + '/shared.json' : path.join(real, 'shared.json');
          const r = det(runner, dir);
          assertHazard(runner, r, 'write-write', key);
          const ign = par(r).skip_dirs_ignored || [];
          assert.ok(ignoredDirs(r).includes(real.replace(/\/$/, '')), `skip_dirs_ignored=${JSON.stringify(ign)}`);
          assert.ok(ign.every((x) => x.reason === 'outside node_modules and tmpdir' || x.reason === 'contains the project root'), JSON.stringify(ign));
        });
      }

      test('(c-neg) cacheDir under node_modules stays skipped and is listed as an effective skip dir', T, () => {
        // protects=the safe location keeps its skip; fails_when=it is ignored or the run loses its proof; no_claim=paths
        // under node_modules are dropped by the footprint anyway, so the listing is what is checked
        const dir = project(runner, 'cneg',
          "test('x', () => { fs.writeFileSync(path.join(process.cwd(), 'x.out'), 'x'); expect(1).toBe(1); });",
          "test('y', () => { fs.writeFileSync(path.join(process.cwd(), 'y.out'), 'y'); expect(1).toBe(1); });",
          { config: { cacheDir: 'node_modules/.vite-custom' } });
        const r = det(runner, dir);
        assertNoHazard(r);
        assert.ok((par(r).skip_dirs || []).some((d) => d === 'node_modules/.vite-custom' || d.startsWith('node_modules/.vite-custom/')), JSON.stringify(par(r).skip_dirs));
        assert.ok(!ignoredDirs(r).some((d) => d.endsWith('.vite-custom')), JSON.stringify(par(r).skip_dirs_ignored));
      });
    } else {
      test('(c4) jest cacheDirectory <rootDir>: ignored and recorded, a write-write conflict in the repo is a hazard', T, () => {
        // protects=a Jest cache in the project root does not hide the project; fails_when=no hazard, proven; no_claim=
        // Jest's transform cache writes into the root then also produce hazards (expected: slower, correct)
        const dir = project(runner, 'c4', writeShared('shared.txt', 'x'), writeShared('shared.txt', 'y'), { config: { cacheDirectory: '<rootDir>' } });
        const r = det(runner, dir);
        assert.ok(r.trace, show(r));
        const hz = par(r).hazards || [];
        assert.ok(hz.some((h) => h.kind === 'write-write' && h.what === 'shared.txt'), `hazards=${JSON.stringify(hz)}\n${show(r)}`);
        assert.ok(r.trace.header.meta.hazard_rerun, show(r));
        assert.ok(ignoredDirs(r).includes(fs.realpathSync.native(dir)), JSON.stringify(par(r).skip_dirs_ignored));
      });
    }
  });

  describe(`${runner}: shared local services (a)`, () => {
    const servers = [];
    /** A server outside the lanes (its own process): a TCP port on 127.0.0.1, or a unix socket. */
    const serve = (where) => new Promise((resolve, reject) => {
      const code = `const net=require('node:net');const s=net.createServer((c)=>{c.end('hi');});s.listen(${where === null ? "0,'127.0.0.1'" : JSON.stringify(where)},()=>{process.stdout.write(String(s.address().port||'ok')+'\\n');});`;
      const p = spawn(process.execPath, ['-e', code], { stdio: ['ignore', 'pipe', 'inherit'] });
      servers.push(p);
      p.stdout.once('data', (d) => resolve(String(d).trim()));
      p.once('error', reject);
    });
    after(() => { for (const p of servers) p.kill(); });
    const client = (opt) => `test('talks to the service', async () => {
  const got = await new Promise((res) => { const s = net.connect(${opt}); let b = ''; s.on('data', (d) => { b += d; }); s.on('end', () => res(b)); s.on('error', (e) => res(String(e.code))); });
  expect(got).toBe('hi');
});`;

    test('(a1) two lanes connect to one local TCP port served outside the lanes: shared-service hazard', T, async () => {
      // protects=a shared database on a fixed port is a hazard; fails_when=connect matched only against lane listeners
      // and the run proven; no_claim=a toy server stands in for Postgres; whether interleaving changes an outcome is not tested
      const port = await serve(null);
      const dir = project(runner, 'a1', client(`{ host: '127.0.0.1', port: ${port} }`), client(`${port}, 'localhost'`));
      assertHazard(runner, det(runner, dir), 'shared-service', String(port));
    });

    if (runner === 'vitest') {
      test('(a2) two lanes connect to one unix socket: shared-service hazard', T, async () => {
        // protects=unix-socket services (Postgres' default socket) are recorded; fails_when=nothing recorded for {path}
        // connects; no_claim=a toy server stands in for the service
        const sock = path.join(fs.mkdtempSync(path.join(BASE, 'sock-')), 's.sock');
        await serve(sock);
        const dir = project(runner, 'a2', client(`{ path: ${JSON.stringify(sock)} }`), client(JSON.stringify(sock)));
        assertHazard(runner, det(runner, dir), 'shared-service', `unix:${fs.realpathSync.native(sock)}`);
      });

      test('(a-neg) two lanes connect to two different local ports: no hazard, proven', T, async () => {
        // protects=no false hazard between unrelated services; fails_when=any two connects conflict; no_claim=none beyond protects
        const p1 = await serve(null); const p2 = await serve(null);
        const dir = project(runner, 'aneg', client(`{ host: '127.0.0.1', port: ${p1} }`), client(`{ host: '127.0.0.1', port: ${p2} }`));
        assertNoHazard(det(runner, dir));
      });
    }
  });

  describe(`${runner}: the one-lane re-run of a hazard (founder decision 2026-11-26, alakajam A)`, () => {
    const shared = "fs.writeFileSync(path.join(process.cwd(), 'shared.txt'), 'x');";
    const reads = "try { fs.readFileSync(path.join(process.cwd(), 'shared.txt'), 'utf8'); } catch { /* not there yet */ }";
    test('a hazard file with a whole describe.skip block: the re-run is complete, nothing NOT PROVEN', T, () => {
      // protects=tests that never start in either pass (alakajam's rate-limiter.spec.ts) do not make the re-run
      // incomplete; fails_when=hazard_rerun.complete is false / not_proven names the file; no_claim=a skipped test
      // that the first pass ran (not possible for describe.skip)
      const skip = runner === 'vitest' ? "import { describe } from 'vitest';\ndescribe.skip('off', () => { test('s1', () => {}); test('s2', () => {}); });"
        : "describe.skip('off', () => { test('s1', () => {}); test('s2', () => {}); });";
      const dir = project(runner, 'rerun-skip', `test('w', () => { ${shared} });\n${skip}`, `test('r', () => { ${reads} });`);
      const r = det(runner, dir);
      assertHazard(runner, r, 'read-write', 'shared.txt');
      assert.deepEqual(r.trace.header.meta.hazard_rerun.not_proven, [], show(r));
      assert.equal(r.status, 0, show(r));
    });

    test('--det-outcomes reports what the trace reports: the re-run outcome of the hazard files', T, () => {
      // protects=the outcomes file and the merged trace agree (P3b: alakajam par2, outcomes failed / trace passed);
      // fails_when=the outcomes file keeps the first pass's outcome of a re-run test; no_claim=the test fails on its
      // first run only (a marker file; a stand-in for a lane-caused failure); the exit stays red (a re-run never
      // lowers the first pass's code)
      const once = "const m = path.join(process.cwd(), 'ran-once'); const first = !fs.existsSync(m); fs.writeFileSync(m, '1');";
      const dir = project(runner, 'rerun-outcomes',
        `test('w', () => { ${shared} ${once} expect(first).toBe(false); });`, `test('r', () => { ${reads} });`);
      const out = path.join(dir, 'outcomes.json');
      fs.rmSync(out, { force: true });
      const r = det(runner, dir, { args: [`--det-outcomes=${out}`] });
      assertHazard(runner, r, 'read-write', 'shared.txt');
      const ext = EXT[runner];
      const id = `tests/x${ext}::w`;
      const rec = r.trace.tests.find((t) => t.nodeid === id);
      assert.equal(rec && rec.outcome, 'passed', show(r));
      assert.ok(r.trace.header.meta.hazard_rerun.first_run_failed.includes(id), show(r));
      const o = JSON.parse(fs.readFileSync(out, 'utf8'));
      assert.equal(o.outcomes[id], 'passed', `outcomes file: ${JSON.stringify(o.outcomes)}\n${show(r)}`);
      assert.equal(o.exceptions[id], undefined, JSON.stringify(o.exceptions));
      assert.equal(o.hazard_rerun && o.hazard_rerun.reported, 'one-lane re-run', JSON.stringify(o.hazard_rerun));
      assert.notEqual(r.status, 0, show(r));
    });
  });

  describe(`${runner}: positive control`, () => {
    test('a clean two-lane run (no shared path, port or socket) keeps its proof', T, () => {
      // protects=the fixes do not take the proof from an isolated suite; fails_when=a hazard or re-run appears, or the
      // run fails; no_claim=a tiny suite: no runner caches in the project, no shared modules
      const dir = project(runner, 'clean',
        "test('x', () => { fs.writeFileSync(path.join(process.cwd(), 'x.out'), 'x'); fs.rmSync(path.join(process.cwd(), 'xdir'), { recursive: true, force: true }); expect(fs.readdirSync(path.join(process.cwd(), 'tests')).length).toBe(2); });",
        "test('y', () => { fs.writeFileSync(path.join(process.cwd(), 'y.out'), 'y'); fs.mkdirSync(path.join(process.cwd(), 'ydir', 'a'), { recursive: true }); expect(1).toBe(1); });");
      assertNoHazard(det(runner, dir));
    });
  });
}
