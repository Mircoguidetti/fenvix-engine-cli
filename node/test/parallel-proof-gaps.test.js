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

  test('two lanes connecting to one local port, unix socket or remote host:port: shared-service (a1, a2, a3)', () => {
    // protects=a shared database / service is a hazard even when no lane listens; fails_when=connect matched only to
    // listeners; no_claim=synthetic keys (the connect wrapper's keys are checked by the integration tests)
    assert.deepEqual(kinds(run({ connect: ['5432'] }, { connect: ['5432'] })), ['shared-service 5432']);
    assert.deepEqual(kinds(run({ connect: ['unix:/run/pg/.s.PGSQL.5432'] }, { connect: ['unix:/run/pg/.s.PGSQL.5432'] })), ['shared-service unix:/run/pg/.s.PGSQL.5432']);
    assert.deepEqual(kinds(run({ connect: ['tcp:db.example.com:5432'] }, { connect: ['tcp:db.example.com:5432'] })), ['shared-service tcp:db.example.com:5432']);
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
