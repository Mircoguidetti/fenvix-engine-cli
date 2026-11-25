'use strict';
// claude/all-runners-2, task "move the Node session policy into Rust" (review R-032 claim 3): the Rust policy
// (crates/detpy-core/src/node_session.rs, called by node/src/cache/proof.js) against the JavaScript policy it
// replaces (test/legacy-proof-policy.js, the code as it was), on the same inputs:
// 1. inputs dumped by real sessions (node --test, Mocha; DETJS_POLICY_DUMP) over fixtures that
//    exercise every rule (reads, writes across files, environment, clock, entropy with and without --det-urandom,
//    a spawned process, a failing test, verify mode, an earlier session's written paths);
// 2. seeded random inputs (every item kind, flag details of every JSON type, projects, uncacheable projects,
//    verified hits, writers from start-up, from other files and from earlier sessions).
// For each input both policies run on two fresh stores with the same prior state; the saved stores, the recorded
// counts, the not-cached reasons (with their order), the verified comparisons and the ran files must be identical,
// and the receipt lines too.
// Run: cd node && node --test test/policy-equivalence.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const native = require('../src/native');
const legacy = require('./legacy-proof-policy');

const BIN = path.join(__dirname, '..', 'bin', 'detjs.js');
// under node/ (as the other runner tests): Mocha resolves from node/node_modules
fs.mkdirSync(path.join(__dirname, '.tmp'), { recursive: true });
const TMP = fs.mkdtempSync(path.join(__dirname, '.tmp', 'policy-eq-'));

function both(input, prior) {
  const dirs = ['js', 'rust'].map((n) => fs.mkdtempSync(path.join(TMP, `${n}-`)));
  const stores = dirs.map((d) => new native.ProofCache(d, '/project'));
  for (const s of stores) if (prior) s.addWritten(JSON.stringify(prior));
  const js = legacy.recordAll(input, stores[0]);
  const rs = JSON.parse(stores[1].recordSession(JSON.stringify(input)));
  stores.forEach((s) => s.save());
  const text = dirs.map((d) => fs.readFileSync(path.join(d, 'proof-cache.json'), 'utf8'));
  return { js, rs, text };
}

function assertSame(input, prior, label) {
  const { js, rs, text } = both(input, prior);
  assert.equal(rs.recorded, js.recorded, `${label}: recorded`);
  assert.deepEqual(rs.not_cached, js.not_cached, `${label}: not cached (reasons and order)`);
  assert.deepEqual(rs.verified, js.verified, `${label}: verified`);
  assert.deepEqual(rs.ran_files, js.ran_files, `${label}: ran files`);
  assert.equal(text[1], text[0], `${label}: stores differ`);
  return { js, rs };
}

// -- 1. real sessions ------------------------------------------------------------------------------------------
const HEADS = {
  'node-test': { f: (n) => `tests/${n}.test.mjs`, head: "import { test } from 'node:test'; import assert from 'node:assert/strict'; import fs from 'node:fs'; import cp from 'node:child_process'; import crypto from 'node:crypto';" },
  mocha: { f: (n) => `test/${n}.spec.mjs`, head: "import assert from 'node:assert/strict'; import fs from 'node:fs'; import cp from 'node:child_process'; import crypto from 'node:crypto'; const test = it;" },
};
const BODIES = {
  reads: "test('r', () => { assert.equal(fs.readFileSync('data/a.txt', 'utf8'), 'a'); assert.ok(!fs.existsSync('data/none')); });",
  writes: "test('w', () => { fs.mkdirSync('out', { recursive: true }); fs.writeFileSync('out/shared.txt', 'x'); });",
  readsw: "test('rw', () => { assert.ok(fs.readFileSync('out/shared.txt', 'utf8').length >= 0); });",
  env: "test('e', () => { assert.equal(process.env.POLICY_EQ_X, 'x'); assert.ok(Object.keys(process.env).length > 0); });",
  clock: "test('c', () => { assert.ok(Date.now() > 0); });",
  entropy: "test('n', () => { assert.equal(crypto.randomBytes(4).length, 4); });",
  spawn: "test('s', () => { cp.execFileSync('true'); });",
  fails: "test('f', () => { assert.equal(1, 2); });",
  multi: "test('m1', () => { assert.ok(fs.readFileSync('data/a.txt')); }); test('m2', () => { assert.equal(process.env.POLICY_EQ_X, 'x'); }); test('m3', () => {});",
};

function project(runner) {
  const dir = fs.mkdtempSync(path.join(TMP, `proj-${runner}-`));
  const h = HEADS[runner];
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: `peq-${runner}`, private: true, type: 'module' }));
  fs.mkdirSync(path.join(dir, 'data'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'data', 'a.txt'), 'a');
  fs.mkdirSync(path.join(dir, 'out'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'out', 'shared.txt'), 'x');
  for (const [n, b] of Object.entries(BODIES)) {
    const f = path.join(dir, h.f(n));
    fs.mkdirSync(path.dirname(f), { recursive: true });
    fs.writeFileSync(f, `${h.head}\n${b}\n`);
  }
  return dir;
}

function session(runner, dir, dump, extra = []) {
  const env = { ...process.env, DETJS_POLICY_DUMP: dump, POLICY_EQ_X: 'x' };
  for (const k of Object.keys(env)) if (k.startsWith('DETJS_') && k !== 'DETJS_POLICY_DUMP') delete env[k];
  // Mocha: one capture per spec file (--det-isolate); its default is one capture for the whole process (G-0148)
  const iso = runner === 'mocha' ? ['--det-isolate'] : [];
  return spawnSync(process.execPath, [BIN, runner, '--det', ...iso, `--det-cache=${path.join(dir, '.cache')}`, ...extra],
    { cwd: dir, encoding: 'utf8', env, timeout: 600000 });
}

for (const runner of Object.keys(HEADS)) {
  test(`real ${runner} sessions: the Rust policy equals the JavaScript one`, { timeout: 900000 }, () => {
    const dir = project(runner);
    const dump = path.join(TMP, `dump-${runner}`);
    // since P1 D the default is --det-urandom (entropy from a seeded stream): the first session records with real
    // entropy (--det-urandom=off), the second is the other configuration (entropy allowed)
    session(runner, dir, dump, ['--det-urandom=off']);            // record
    session(runner, dir, dump, ['--det-urandom']);                // another configuration: entropy allowed
    session(runner, dir, dump, ['--det-cache-verify']);           // verify mode: hits compared with the fresh run
    const inputs = fs.readdirSync(dump).sort().map((n) => JSON.parse(fs.readFileSync(path.join(dump, n), 'utf8')));
    assert.ok(inputs.length >= 2, `sessions dumped their inputs (${inputs.length})`);
    let reasons = 0;
    for (const [i, input] of inputs.entries()) {
      assert.ok(input.captures.length >= Object.keys(BODIES).length - 1, `${runner} #${i}: captures`);
      const { js } = assertSame(input, null, `${runner} #${i}`);
      assertSame(input, { 'out/shared.txt': ['earlier-file'], 'data/a.txt': [''] }, `${runner} #${i} with earlier writers`);
      reasons += js.not_cached.length;
    }
    assert.ok(reasons > 0, 'the fixtures made results not cacheable (the rules were exercised)');
  });
}

// -- 2. seeded random inputs --------------------------------------------------------------------------------------
function rng(seed) {
  let x = seed >>> 0 || 1;
  return () => { x ^= x << 13; x >>>= 0; x ^= x >>> 17; x ^= x << 5; x >>>= 0; return x / 4294967296; };
}

function randomInput(seed) {
  const r = rng(seed);
  const pick = (a) => a[Math.floor(r() * a.length)];
  const paths = ['a.txt', 'b.txt', 'out/x', 'out/y', 'src/m.js', 'node_modules/p/index.js'];
  const flags = [...Object.keys(legacy.UNCACHEABLE), 'note', 'other-flag'];
  const details = ['d1', 'detail two', 7, null, undefined, true, { o: 1 }, ['l', 2]];
  const labels = ['L0', 'L1', 'L2', 'L3'];
  const env = { A: '1', B: 'two', EMPTY: '' };
  const item = () => {
    const k = pick(['data', 'data', 'data', 'code', 'env', 'clock', 'flag', 'write', 'other']);
    if (k === 'data') return ['data', pick(paths), pick(['f:1', 'f:2', 'missing', 's:file', 'd:9']), ...(r() < 0.3 ? [pick(['infra', 'plugin', 'user'])] : [])];
    if (k === 'code') return ['code', pick(paths), pick(['c1', 'c2'])];
    if (k === 'env') return ['env', pick(['A', 'B', 'C', '*', 'EMPTY', '__proto__', 'constructor'])];
    if (k === 'clock') return ['clock'];
    if (k === 'flag') { const d = pick(details); return d === undefined ? ['flag', pick(flags)] : ['flag', pick(flags), d]; }
    if (k === 'write') return ['write', pick(paths)];
    return ['other', 'x'];
  };
  const captures = [];
  const n = 1 + Math.floor(r() * 4);
  for (let i = 0; i < n; i++) {
    const items = Array.from({ length: Math.floor(r() * 12) }, item);
    const tests = Array.from({ length: Math.floor(r() * 4) }, (_, j) => ({
      id: pick([`f${i}.test.js::t${j}`, `f${i}.test.js`]), upto: Math.floor(r() * (items.length + 2)),
      outcome: pick(['passed', 'passed', 'skipped', 'todo', 'failed', 'cancelled']),
      ...(r() < 0.5 ? { fingerprint: `fp${j}` } : {}), ...(r() < 0.5 ? { duration: r() } : {}),
    }));
    // Every real capture carries the sensor declaration of the process that ran the file (src/provable.js
    // `header`); without one the policy refuses to store anything, which is the clause the dedicated tests
    // below cover. The flag-and-outcome layer these 500 inputs compare is only reached with a valid one.
    captures.push({ label: pick(labels), fileId: `f${i}.test.js`, ...(r() < 0.4 ? { project: pick(['p1', 'p2']) } : {}),
      duration: r(), ok: r() < 0.7, notes: r() < 0.2 ? ['process.env not replaceable: environment reads not captured'] : [],
      tests, items, provable: PROVABLE });
  }
  const hits = {};
  for (const c of captures) {
    if (r() < 0.5) hits[c.project ? `${c.fileId}@@${c.project}` : c.fileId] = pick(['passed', 'failed']);
    for (const t of c.tests) if (r() < 0.5) hits[legacyKey(t.id, c.project || '')] = pick(['passed', 'skipped']);
  }
  return {
    global: Array.from({ length: Math.floor(r() * 6) }, item), spec_keys: ['a.txt', 'f0.test.js'], captures, cur_env: env,
    urandom: r() < 0.5, epoch_ms: r() < 0.5 ? 1700000000000 : null, run_id: `run${seed}`, runtime: 'RT', startup: r() < 0.5 ? 'S' : '',
    config_for: { '': 'C0', p1: 'C1', p2: 'C2' }, uncacheable_projects: r() < 0.2 ? ['p2'] : [], verify: r() < 0.5, hits,
    controls: CONTROLS,
  };
}

// a valid declaration, as the sensor writes it for this build
const PROVABLE = JSON.parse(native.provableHeader('node-surface/1', 'node22'));
// the controls the accounting rests on (provable.rs `required_controls` for a node- sensor); a real --det run has
// them on, and judge() refuses a run missing any of them before it looks at a single name
const CONTROLS = ['time', 'seeds', 'fs', 'net', 'timers', 'order', 'isolation'];

function legacyKey(testId, project) {
  if (!project) return testId;
  const i = testId.indexOf('::');
  return i < 0 ? `${testId}@@${project}` : `${testId.slice(0, i)}@@${project}${testId.slice(i)}`;
}

test('seeded random inputs: the Rust policy equals the JavaScript one (500 inputs)', () => {
  for (let seed = 1; seed <= 500; seed++) {
    const input = randomInput(seed);
    // JSON round trip: what the session hands Rust (undefined details are absent, as in the JSON the capture logs)
    const viaJson = JSON.parse(JSON.stringify(input));
    assertSame(viaJson, seed % 3 ? null : { 'out/x': ['L1', ''], 'a.txt': ['L9'] }, `seed ${seed}`);
  }
});

test('receipt lines: the Rust lines equal the JavaScript ones', () => {
  for (let seed = 1; seed <= 200; seed++) {
    const r = rng(seed);
    const hits = Array.from({ length: Math.floor(r() * 4) }, (_, i) => [`h${i}::t`, { key: `k${i}`, run: 'R', outcome: 'passed', duration: r(), epoch: r() < 0.5 ? null : 5, kind: r() < 0.5 ? 'file' : undefined }]);
    const misses = Array.from({ length: Math.floor(r() * 4) }, (_, i) => [`m${i}`, `data: x "quoted" \\ ${i}`]);
    for (const verify of [false, true]) {
      const js = legacy.receipts(hits, misses, verify);
      const rs = native.receiptLines(hits.map(([n, o]) => [n, JSON.stringify(o)]), misses, verify);
      assert.equal(rs, js, `seed ${seed} verify ${verify}`);
    }
  }
});

test('the uncacheable table is the same', () => {
  assert.deepEqual(native.uncacheableTable(), legacy.UNCACHEABLE);
});

// -- 3. the one predicate gates storing (crates/detpy-core/src/provable.rs judge) ---------------------------------
// The Node cache must not have a reuse rule of its own: a test the sensor could not fully account for, and a run
// that cannot say what it watched, are never stored. These assert against the Rust policy directly -- there is no
// JavaScript mirror of judge() on purpose, so that the rule has one implementation and not two.

function oneTest(extra = {}, testExtra = {}, session = {}) {
  return {
    global: [], spec_keys: ['f0.test.js'], cur_env: {}, urandom: false, epoch_ms: null,
    run_id: 'r', runtime: 'RT', startup: '', config_for: { '': 'C0' }, uncacheable_projects: [], verify: false, hits: {},
    controls: CONTROLS,
    captures: [{
      label: 'L1', fileId: 'f0.test.js', duration: 0.1, ok: true, notes: [], items: [],
      tests: [{ id: 'f0.test.js::t', upto: 0, outcome: 'passed', fingerprint: 'fp', ...testExtra }],
      provable: PROVABLE, ...extra,
    }],
    ...session,
  };
}

function recorded(input) {
  const dir = fs.mkdtempSync(path.join(TMP, 'judge-'));
  const store = new native.ProofCache(dir, '/project');
  return JSON.parse(store.recordSession(JSON.stringify(input)));
}

test('a clean test with a valid sensor declaration is stored', () => {
  const out = recorded(oneTest());
  assert.equal(out.recorded, 1, JSON.stringify(out.not_cached));
  assert.deepEqual(out.not_cached, []);
});

test('a channel the sensor could not place is never stored', () => {
  const out = recorded(oneTest({}, { unaccounted: ['api:v8.getHeapStatistics'] }));
  assert.equal(out.recorded, 0);
  const why = Object.fromEntries(out.not_cached);
  assert.match(why['f0.test.js::t'], /api:v8\.getHeapStatistics/);
  // the file's entry stands for every test in it, so it is refused too
  assert.match(why['f0.test.js'], /api:v8\.getHeapStatistics/);
});

test('a run that declared no sensor stores nothing', () => {
  const out = recorded(oneTest({ provable: null, provable_absent: 'switched off' }));
  assert.equal(out.recorded, 0);
  const why = Object.fromEntries(out.not_cached);
  assert.match(why['f0.test.js::t'], /sensor/);
});

test('a sensor built against another accounting table stores nothing', () => {
  const out = recorded(oneTest({ provable: { ...PROVABLE, surface: 'deadbeef' } }));
  assert.equal(out.recorded, 0);
  assert.match(Object.fromEntries(out.not_cached)['f0.test.js::t'], /accounting table/);
});

test('a runtime the table was not audited against stores nothing', () => {
  const out = recorded(oneTest({ provable: { ...PROVABLE, runtime: 'node99' } }));
  assert.equal(out.recorded, 0);
  assert.match(Object.fromEntries(out.not_cached)['f0.test.js::t'], /audited/);
});

test('a channel rule that names the gap is preferred over the generic finding', () => {
  // both are true; "network connection" tells the reader more than "api:net._normalizeArgs" (judge()'s own
  // reasoning about clause order, applied to the two layers here)
  const inp = oneTest({ items: [['flag', 'connect', '127.0.0.1:1']] }, { unaccounted: ['api:net._normalizeArgs'], upto: 1 });
  const out = recorded(inp);
  assert.equal(out.recorded, 0);
  assert.match(Object.fromEntries(out.not_cached)['f0.test.js::t'], /network connection/);
});

test('a run with a control the accounting rests on switched off stores nothing', () => {
  const out = recorded(oneTest({}, {}, { controls: ['seeds', 'fs', 'net', 'timers'] })); // time off
  assert.equal(out.recorded, 0);
  assert.match(Object.fromEntries(out.not_cached)['f0.test.js::t'], /control `time` off/);
});
