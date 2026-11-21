'use strict';
// Parallel `--det` (row JS-07, audit gaps G-1044, G-1304, G-1395, G-1396, G-1448, G-1450, G-1455, G-1457, G-1458,
// G-1449, G-1456): Vitest threads/forks pools and Jest workers run test files in
// lanes with a fixed plan (src/parallel.js). Checked here:
//   * the plan is a function of the inputs (identical across runs, written in the trace, replayed from the trace);
//   * the lanes really overlap in time;
//   * per test, outcome and fingerprint of a parallel run equal those of the serial run (isolated suite);
//   * a cross-worker write/read and process-wide state carried between files of one process are detected
//     (stderr + trace) and never reused by the cache; a read of the worker / pool id is never reused;
//   * cache entries recorded in parallel are reused serially and vice versa;
//   * a shared worker (Vitest isolate=false) keeps the run serial and says so;
//   * the same on Vitest 3 and 4 and Jest 29 (installed into fixture directories when the registry is reachable);
//   * Playwright workers say that their placement is not controlled.
const { test, describe, before } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const os = require('node:os');
const { BIN, TMP, readTrace } = require('./helpers');

const T = { timeout: 900000 };
const RUNNERS = (process.env.DETJS_TEST_RUNNERS || 'vitest,jest').split(',');
const EXT = { vitest: '.test.mjs', jest: '.test.js' };
const HEAD = {
  vitest: "import { test, expect, describe } from 'vitest'; import fs from 'node:fs'; import path from 'node:path'; import os from 'node:os';",
  jest: "const fs = require('node:fs'); const path = require('node:path'); const os = require('node:os');",
};

function write(dir, files) {
  for (const [name, body] of Object.entries(files)) {
    const p = path.join(dir, name);
    if (body === null) { fs.rmSync(p, { force: true, recursive: true }); continue; }
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, body);
  }
}

/** A fixture project under `base` (default: node/test/.tmp, which resolves the runners of node/node_modules). */
function fixture(runner, name, tests, { base = path.join(TMP, 'par'), vitest = {}, jest = {}, extra = {} } = {}) {
  const dir = path.join(base, runner, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  write(dir, { 'package.json': JSON.stringify({ name: `par-${name}`, private: true }) });
  if (runner === 'vitest') write(dir, { 'vitest.config.mjs': `export default { test: ${JSON.stringify({ include: ['tests/**/*.test.mjs'], ...vitest })} };\n` });
  else write(dir, { 'jest.config.js': `module.exports = ${JSON.stringify({ testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node', ...jest })};\n` });
  for (const [f, body] of Object.entries(tests)) write(dir, { [`tests/${f}${EXT[runner]}`]: `${HEAD[runner]}\n${body}\n` });
  write(dir, extra);
  return dir;
}

function cleanEnv(extra = {}) {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_SEED', 'DETJS_CACHE_DIR', 'JEST_WORKER_ID', 'VITEST_POOL_ID', 'VITEST_WORKER_ID']) delete env[k];
  return { ...env, ...extra };
}

/** One run: returns {status, stdout, stderr, trace, summary, wall}. */
function det(runner, dir, args = [], { env = {} } = {}) {
  fs.rmSync(path.join(dir, '.detjs', 'cache-summary.json'), { force: true });
  fs.rmSync(path.join(dir, '.detjs', 'trace.jsonl'), { force: true });
  const runnerArgs = runner === 'vitest' ? ['run'] : [`--cacheDirectory=${path.join(dir, '.jest-cache')}`];
  const t0 = Date.now();
  const r = spawnSync(process.execPath, [BIN, runner, ...runnerArgs, '--det', ...args], { cwd: dir, encoding: 'utf8', env: cleanEnv(env), timeout: 300000 });
  const wall = Date.now() - t0;
  let trace = null;
  try { trace = readTrace(path.join(dir, '.detjs', 'trace.jsonl')); } catch { /* none */ }
  let summary = null;
  try { summary = JSON.parse(fs.readFileSync(path.join(dir, '.detjs', 'cache-summary.json'), 'utf8')); } catch { /* none */ }
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '', trace, summary, wall };
}

const show = (r) => `status=${r.status}\nstdout=${r.stdout.slice(-2500)}\nstderr=${r.stderr.slice(-2500)}\nsummary=${JSON.stringify(r.summary && { reused: r.summary.reused_files_list, misses: r.summary.misses, nc: r.summary.not_cached_detail })}`;
const fps = (r) => Object.fromEntries(r.trace.tests.map((t) => [t.nodeid, `${t.outcome}|${t.fingerprint}`]));
const plan = (r) => r.trace && r.trace.header.meta.parallel && r.trace.header.meta.parallel.plan;
const reusedFiles = (r) => ((r.summary && r.summary.reused_files_list) || []).map((f) => f.split('@@')[0]);
const notCached = (r) => (r.summary && r.summary.not_cached_detail) || {};

// An isolated suite: every Level 0 control is exercised, no file depends on another.
function isolatedSuite(n = 6) {
  const out = {};
  for (let i = 1; i <= n; i++) {
    out[`f${i}`] = `
const lst = fs.readdirSync(path.join(process.cwd(), 'tests')).join(',');
describe('group ${i}', () => {
  test('random and clock ${i}', () => { const a = Math.random(); const d = Date.now(); expect(typeof a).toBe('number'); expect(d).toBeGreaterThan(0); });
  test('timers ${i}', async () => { const t0 = Date.now(); await new Promise((r) => setTimeout(r, 200 * ${i})); expect(Date.now() - t0).toBeGreaterThanOrEqual(200 * ${i}); });
  test('crypto ${i}', () => { expect(globalThis.crypto.randomUUID().length).toBe(36); expect(lst.length).toBeGreaterThan(0); });
  test('real wait ${i}', () => { Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 400); expect(1).toBe(1); });
});`;
  }
  return out;
}

// -- the plan ----------------------------------------------------------------------------------------------------

describe('fixed plan (unit)', () => {
  test('makePlan is a function of its inputs; lanes are subsequences of the serial order; together-edges join files', () => {
    const parallel = require('../src/parallel');
    const root = path.join(TMP, 'par', 'unit');
    fs.rmSync(root, { recursive: true, force: true });
    fs.mkdirSync(path.join(root, '.detjs'), { recursive: true });
    const keys = Array.from({ length: 20 }, (_, i) => `tests/f${String(i).padStart(2, '0')}.test.js`);
    const a = parallel.makePlan(root, keys, 4);
    const b = parallel.makePlan(root, keys, 4);
    assert.deepEqual(a.lanes, b.lanes);
    assert.equal(a.digest, b.digest);
    assert.equal(a.inputs_digest, b.inputs_digest);
    for (const l of a.lanes) assert.deepEqual(l, [...l].sort((x, y) => keys.indexOf(x) - keys.indexOf(y)));
    assert.deepEqual(a.lanes.flat().sort(), keys);
    // dispatch order keeps every lane's order
    for (const l of a.lanes) assert.deepEqual(a.dispatch.filter((k) => l.includes(k)), l);
    // durations and together-edges recorded by earlier runs are inputs
    fs.writeFileSync(path.join(root, '.detjs', 'plan-state.json'), JSON.stringify({
      version: 1, durations: { ...Object.fromEntries(keys.map((k) => [k, [1]])), [keys[0]]: [9, 9, 9] }, together: { [`${keys[3]}\u0000${keys[17]}`]: 'read-write x' }, previous: {},
    }));
    const c = parallel.makePlan(root, keys, 4);
    assert.notEqual(c.inputs_digest, a.inputs_digest);
    const laneOf = (p, k) => p.lanes.findIndex((l) => l.includes(k));
    assert.equal(laneOf(c, keys[3]), laneOf(c, keys[17]), 'files joined by a together-edge share a lane');
    assert.deepEqual(c.lanes.find((l) => l.includes(keys[0])), [keys[0]], 'the long file is alone in its lane');
    // a file listed twice (a Vitest test file that is also a typecheck spec; found on cheerio, where the duplicate
    // was its own lane predecessor and the run waited forever): one place in the plan, never its own predecessor
    const d = parallel.makePlan(root, [keys[0], keys[1], keys[1], keys[2]], 2);
    assert.deepEqual(d.lanes.flat().sort(), [keys[0], keys[1], keys[2]]);
    const runDir = path.join(root, 'run');
    parallel.writeRunPlan(runDir, d, 'vitest');
    const rp = JSON.parse(fs.readFileSync(path.join(runDir, 'plan.json'), 'utf8'));
    for (const [k, p] of Object.entries(rp.pred)) assert.notEqual(k, p);
    // replay: the same lanes whatever the state says
    const r = parallel.makePlan(root, keys, 2, { replay: { lanes: a.lanes } });
    assert.deepEqual(r.lanes, a.lanes);
    assert.equal(r.workers, 4);
  });
});

for (const runner of RUNNERS) {
  describe(`${runner}: parallel lanes`, () => {
    let dir;
    let serial;
    before(() => {
      dir = fixture(runner, 'iso', isolatedSuite());
      // One lane is the serial baseline every test below compares against. It is asked for explicitly:
      // since row JS-07 (gap G-1044) `--det` is PARALLEL by default, so the default no longer means serial.
      serial = det(runner, dir, ['--det-workers=1']);
      assert.equal(serial.status, 0, show(serial));
      assert.equal(plan(serial), undefined, 'one lane runs serially');
      assert.equal(serial.trace.header.meta.serial, true);
      // the new default: no worker option at all is parallel, on a machine with more than one CPU
      const def = det(runner, dir);
      assert.equal(def.status, 0, show(def));
      if (os.availableParallelism() > 1) {
        assert.ok(plan(def), `parallel by default (G-1044): ${show(def)}`);
        assert.equal(plan(def).workers, os.availableParallelism());
        assert.match(def.stdout, /detjs: parallel execution in \d+ lanes with a fixed plan \(default \(this machine's CPUs\)\)/);
        assert.match(def.stderr, /detjs: parallel: \d+ lanes, plan [0-9a-f]+/);
      }
    });

    test('the plan is identical across runs, recorded in the trace and replayed from it; lanes overlap in time', T, () => {
      const p1 = det(runner, dir, ['--det-workers=3']);
      assert.equal(p1.status, 0, show(p1));
      const p2 = det(runner, dir, ['--det-workers=3']);
      assert.equal(p2.status, 0, show(p2));
      assert.ok(plan(p1), show(p1));
      assert.equal(plan(p1).workers, 3);
      assert.deepEqual(plan(p1).lanes, plan(p2).lanes);
      assert.equal(plan(p1).digest, plan(p2).digest);
      assert.deepEqual(p1.trace.header.meta.parallel.placement.deviations, [], show(p1));
      assert.match(p1.stderr, /detjs: parallel: 3 lanes, plan [0-9a-f]+/);
      // Jest: one worker process per lane, running the lane's files in order (JEST_WORKER_ID = lane + 1)
      if (runner === 'jest') assert.deepEqual(p1.trace.header.meta.parallel.placement.processes.sort(), plan(p1).lanes.slice().sort());
      // the lanes ran at the same time: at some moment 3 files were running (each waits 0.4 s for real)
      const spans = Object.values(p1.trace.header.meta.parallel.placement.spans);
      const overlap = Math.max(...spans.map(([s]) => spans.filter(([a, b]) => a <= s && s < b).length));
      assert.equal(overlap, 3, JSON.stringify(spans));
      // replay from the trace, with another worker count asked: the trace's lanes win
      fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), path.join(dir, 'p1.jsonl'));
      const rp = det(runner, dir, ['--det-workers=2', `--det-plan=${path.join(dir, 'p1.jsonl')}`]);
      assert.equal(rp.status, 0, show(rp));
      assert.deepEqual(plan(rp).lanes, plan(p1).lanes);
      assert.equal(plan(rp).replayed, true);
    });

    const pools = runner === 'vitest' ? ['threads', 'forks'] : ['workers'];
    for (const pool of pools) {
      test(`parallel fingerprints equal the serial ones (${pool})`, T, () => {
        const args = runner === 'vitest' ? [`--pool=${pool}`, '--maxWorkers=3'] : ['-w', '3'];
        const s = runner === 'vitest' ? det(runner, dir, [`--pool=${pool}`]) : serial;
        assert.equal(s.status, 0, show(s));
        const p = det(runner, dir, args);
        assert.equal(p.status, 0, show(p));
        assert.ok(plan(p), `the runner's own worker option asks for parallel lanes\n${show(p)}`);
        assert.equal(p.trace.tests.length, 24);
        assert.deepEqual(fps(p), fps(s));
        assert.deepEqual(p.trace.tests.map((t) => t.nodeid), s.trace.tests.map((t) => t.nodeid), 'merged in the serial order');
        // the verifier reads the merged trace
        fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), path.join(dir, 'par.jsonl'));
        det(runner, dir, runner === 'vitest' ? [`--pool=${pool}`] : []);
        const v = spawnSync(process.execPath, [BIN, 'verify', path.join(dir, 'par.jsonl'), path.join(dir, '.detjs', 'trace.jsonl'), '--json'], { encoding: 'utf8' });
        assert.equal(v.status, 0, v.stdout + v.stderr);
        const rep = JSON.parse(v.stdout);
        assert.equal(rep.summary.stable, 24);
        assert.equal(rep.summary.order_identical, true);
      });
    }

    test('cache: recorded in parallel, reused serially; recorded serially, reused in parallel', T, () => {
      const cache = path.join(dir, '.cache-a');
      fs.rmSync(cache, { recursive: true, force: true });
      const r1 = det(runner, dir, ['--det-workers=3', `--det-cache=${cache}`]);
      assert.equal(r1.status, 0, show(r1));
      assert.equal(r1.summary.recorded, 24, show(r1));
      const r2 = det(runner, dir, [`--det-cache=${cache}`]);
      assert.equal(r2.status, 0, show(r2));
      assert.equal(r2.summary.reused_tests, 24, show(r2));
      const cache2 = path.join(dir, '.cache-b');
      fs.rmSync(cache2, { recursive: true, force: true });
      const r3 = det(runner, dir, [`--det-cache=${cache2}`]);
      assert.equal(r3.summary.recorded, 24, show(r3));
      // change one file: only it reruns, in a parallel run, and the receipts cover every test
      fs.appendFileSync(path.join(dir, 'tests', `f2${EXT[runner]}`), '\n// changed\n');
      const r4 = det(runner, dir, ['--det-workers=3', `--det-cache=${cache2}`]);
      assert.equal(r4.status, 0, show(r4));
      assert.equal(r4.summary.reused_tests, 20, show(r4));
      assert.deepEqual(Object.keys(r4.summary.misses), [`tests/f2${EXT[runner]}`]);
      const receipts = fs.readFileSync(path.join(dir, '.detjs', 'receipts.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l));
      assert.equal(receipts.filter((x) => x.reused).length, 25, 'one receipt per reused test and file entry');
      fs.writeFileSync(path.join(dir, 'tests', `f2${EXT[runner]}`), fs.readFileSync(path.join(dir, 'tests', `f2${EXT[runner]}`), 'utf8').replace('\n// changed\n', ''));
    });
  });

  describe(`${runner}: placement effects`, () => {
    test('a cross-worker write/read is reported, joins the files in the next plan, and is never reused', T, () => {
      const shared = path.join(TMP, 'par', `${runner}-shared-out.txt`);
      fs.rmSync(shared, { force: true });
      const dir = fixture(runner, 'xw', {
        a_writer: `test('writes', () => { fs.writeFileSync(${JSON.stringify(shared)}, fs.readFileSync(path.join(process.cwd(), 'value.txt'), 'utf8')); });`,
        b_reader: `test('reads', async () => { for (let i = 0; i < 50 && !fs.existsSync(${JSON.stringify(shared)}); i++) await new Promise((r) => setTimeout(r, 20)); expect(fs.readFileSync(${JSON.stringify(shared)}, 'utf8')).toBe('x'); });`,
        c_plain: "test('c', () => { expect(1).toBe(1); });",
        d_plain: "test('d', () => { expect(2).toBe(2); });",
      }, { extra: { 'value.txt': 'x' } });
      const ext = EXT[runner];
      // the writer and the reader in two lanes
      write(dir, { 'plan.json': JSON.stringify({ lanes: [[`tests/a_writer${ext}`, `tests/c_plain${ext}`], [`tests/b_reader${ext}`, `tests/d_plain${ext}`]] }) });
      const cache = path.join(dir, '.cache');
      const r1 = det(runner, dir, ['--det-plan=plan.json', `--det-cache=${cache}`]);
      assert.match(r1.stderr, /CROSS-WORKER read-write .*shared-out\.txt: tests\/a_writer\S* \(lane 1\) \/ tests\/b_reader\S* \(lane 2\)/, show(r1));
      const hz = r1.trace.header.meta.parallel.hazards;
      assert.equal(hz.length, 1, show(r1));
      const nc = notCached(r1);
      assert.match(nc[`tests/a_writer${ext}`] || '', /touched a path or port another test file running in parallel also touched/, show(r1));
      assert.ok(nc[`tests/b_reader${ext}`], show(r1));
      // with the same split again, neither file is reused, whatever the reader's verdict was
      const r2 = det(runner, dir, ['--det-plan=plan.json', `--det-cache=${cache}`]);
      assert.deepEqual(reusedFiles(r2).sort(), [`tests/c_plain${ext}`, `tests/d_plain${ext}`], show(r2));
      // the value changes: a fresh serial run fails the reader; a cached run must not reuse it
      write(dir, { 'value.txt': 'y' });
      const r3 = det(runner, dir, ['--det-workers=2', `--det-cache=${cache}`]);
      assert.ok(!reusedFiles(r3).includes(`tests/b_reader${ext}`), show(r3));
      assert.notEqual(r3.status, 0, show(r3));
      // the planner learnt the edge: without a replayed plan, writer and reader share a lane
      const lanes = plan(r3).lanes;
      assert.equal(lanes.findIndex((l) => l.includes(`tests/a_writer${ext}`)), lanes.findIndex((l) => l.includes(`tests/b_reader${ext}`)), show(r3));
      assert.deepEqual(plan(r3).together, [[`tests/a_writer${ext}`, `tests/b_reader${ext}`]]);
    });

    // P1 (docs/LIMITS.md section 10): a placement must never decide an outcome. Both tests below first prove the
    // disease is real by running with the wrapper switched off (DETJS_HAZARD_RERUN=1, which is how each of the two
    // passes tells itself apart -- src/parallel-rerun.js), then prove the engine now reports the one-lane re-run.
    // One test per conflict class the hazard detector has: a shared path, and a fixed port.
    //
    // Each fixture makes the two files really overlap with a blocking wait (`Atomics.wait`): under `--det` timers
    // are virtual, so a `setTimeout` would return at once and the two files would not be in flight together.
    test('P1 shared path: a first run in lanes reports the one-lane re-run, not the placement failure', T, () => {
      // the fixture of node/test/controls.test.js "isolation: parallel workers interleave": two files appending to
      // one log, each asserting that its own two lines are the last two. Serially both pass; in two lanes they
      // interleave and fail. Here each file waits for the other's start line, so the interleaving is not a race.
      const body = (n) => `
const LOG = path.join(process.cwd(), 'shared.log');
const lines = () => { try { return fs.readFileSync(LOG, 'utf8').trim().split('\\n'); } catch { return []; } };
test('${n} writes a contiguous block', () => {
  fs.appendFileSync(LOG, '${n}-start\\n');
  const sab = new Int32Array(new SharedArrayBuffer(4));
  for (let i = 0; i < 60; i++) {
    if (lines().some((l) => l.endsWith('-start') && !l.startsWith('${n}'))) break;
    Atomics.wait(sab, 0, 0, 50);
  }
  fs.appendFileSync(LOG, '${n}-end\\n');
  expect(lines().slice(-2)).toEqual(['${n}-start', '${n}-end']);
});
`;
      const dir = fixture(runner, 'p1-shared', { x: body('X'), y: body('Y') });
      const log = path.join(dir, 'shared.log');
      const ext = EXT[runner];
      const files = [`tests/x${ext}`, `tests/y${ext}`];
      // The lanes are forced with an explicit plan, as the cross-worker test above does. Without it the second run
      // of the pair cannot reproduce the conflict at all: the first run learns the together-edge and every later
      // plan puts the two files in one lane (docs/LIMITS.md P2, a together-edge never expires), so the test would
      // pass for the wrong reason. `--det-plan` is also what the re-run must ignore, which this exercises:
      // src/parallel-rerun.js strips it, or the re-run would be put straight back into two lanes.
      write(dir, { 'plan.json': JSON.stringify({ lanes: [[files[0]], [files[1]]] }) });

      // 1. the disease: with the re-run switched off, the lanes turn a suite that passes serially red
      fs.rmSync(log, { force: true });
      const off = det(runner, dir, ['--det-plan=plan.json'], { env: { DETJS_HAZARD_RERUN: '1' } });
      assert.notEqual(off.status, 0, show(off));
      assert.match(off.stderr, /CROSS-WORKER read-write .*shared\.log/, show(off));
      const failedOff = off.trace.tests.filter((t) => t.outcome !== 'passed').map((t) => t.nodeid);
      assert.ok(failedOff.length > 0, `the placement must have failed a test: ${show(off)}`);

      // 2. the fix: the files the hazard names run again in one lane and that is what is reported
      fs.rmSync(log, { force: true });
      const on = det(runner, dir, ['--det-plan=plan.json']);
      assert.equal(on.status, 0, show(on));
      assert.match(on.stderr, /named by a cross-worker hazard run again in one lane/, show(on));
      assert.deepEqual(on.trace.tests.filter((t) => t.outcome !== 'passed').map((t) => t.nodeid), [], show(on));
      const hr = on.trace.header.meta.hazard_rerun;
      assert.ok(hr, `the trace must record the re-run: ${show(on)}`);
      assert.deepEqual(hr.files.slice().sort(), files.slice().sort(), show(on));
      assert.equal(hr.complete, true, show(on));
      assert.equal(hr.reported, 'one-lane re-run', show(on));
      assert.deepEqual(hr.unaccounted, [], show(on));
      assert.ok(hr.first_run_failed.length > 0, `the re-run must say what the lanes had failed: ${show(on)}`);
    });

    test('P1 fixed port: the same, and a real failure of an affected file is still reported', T, () => {
      // two files binding one fixed port (45321). Nothing but the port is shared, so the hazard is a port hazard
      // and not a path one. The holder keeps the port for real, so a file starting in the other lane within that
      // window really collides with EADDRINUSE.
      const body = (n, extra = '') => `
const net = require('node:net');
test('${n} binds the fixed port', async () => {
  const srv = net.createServer();
  const bound = await new Promise((res) => {
    srv.once('error', (e) => res(e.code || 'ERR'));
    srv.listen(45321, '127.0.0.1', () => res('ok'));
  });
  if (bound === 'ok') Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 2500);
  await new Promise((res) => srv.close(() => res()));
  expect(bound).toBe('ok');${extra}
});
`;
      // Vitest's ESM head has no `require`; the port fixture needs one for node:net
      const head = runner === 'vitest' ? "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);\n" : '';
      const dir = fixture(runner, 'p1-port', { x: head + body('X'), y: head + body('Y') });
      const ext = EXT[runner];
      const lanes = (d) => write(d, { 'plan.json': JSON.stringify({ lanes: [[`tests/x${EXT[runner]}`], [`tests/y${EXT[runner]}`]] }) });
      lanes(dir); // forced, for the reason given in the test above (docs/LIMITS.md P2)

      // 1. the disease
      const off = det(runner, dir, ['--det-plan=plan.json'], { env: { DETJS_HAZARD_RERUN: '1' } });
      assert.notEqual(off.status, 0, show(off));
      assert.match(off.stderr, /CROSS-WORKER port 45321/, show(off));

      // 2. the fix
      const on = det(runner, dir, ['--det-plan=plan.json']);
      assert.equal(on.status, 0, show(on));
      assert.match(on.stderr, /named by a cross-worker hazard run again in one lane/, show(on));
      assert.deepEqual(on.trace.tests.filter((t) => t.outcome !== 'passed').map((t) => t.nodeid), [], show(on));
      assert.equal(on.trace.header.meta.hazard_rerun.complete, true, show(on));

      // 3. the re-run must never whitewash a defect: the same conflict, with a real failure in one of the files.
      // The placement failure goes, the defect stays, and the run is still red.
      const dir2 = fixture(runner, 'p1-port-real', {
        x: head + body('X', "\n  expect(1).toBe(2); // a real defect, nothing to do with placement"),
        y: head + body('Y'),
      });
      lanes(dir2);
      const real = det(runner, dir2, ['--det-plan=plan.json']);
      assert.notEqual(real.status, 0, show(real));
      assert.match(real.stderr, /named by a cross-worker hazard run again in one lane/, show(real));
      const bad = real.trace.tests.filter((t) => t.outcome !== 'passed').map((t) => t.nodeid);
      assert.deepEqual(bad, [`tests/x${ext}::X binds the fixed port`], show(real));
    });

    test('a read of the worker or pool id: never reused from a parallel run; keyed as the serial value (1) serially', T, () => {
      const v = runner === 'vitest' ? 'VITEST_POOL_ID' : 'JEST_WORKER_ID';
      const dir = fixture(runner, 'wid', {
        a: `test('worker id', () => { expect(Number(process.env.${v})).toBeGreaterThan(0); });`,
        b: "test('b', () => { expect(1).toBe(1); });",
        c: "test('c', () => { expect(1).toBe(1); });",
        // a copy of the whole environment is keyed as the whole environment, not as a read of the id
        d: "test('copy', () => { const e = { ...process.env }; expect(Object.keys(e).length).toBeGreaterThan(0); });",
      });
      const cache = path.join(dir, '.cache');
      const a = `tests/a${EXT[runner]}`;
      const r1 = det(runner, dir, ['--det-workers=2', `--det-cache=${cache}`]);
      assert.equal(r1.status, 0, show(r1));
      assert.match(notCached(r1)[a] || '', new RegExp(`reads the worker or pool id.*${v}`), show(r1));
      assert.ok(!notCached(r1)[`tests/d${EXT[runner]}`], show(r1));
      const r2 = det(runner, dir, ['--det-workers=2', `--det-cache=${cache}`]);
      assert.ok(!reusedFiles(r2).includes(a), show(r2));
      assert.ok(reusedFiles(r2).includes(`tests/d${EXT[runner]}`), show(r2));
      // serially every test sees 1: the read is keyed with that value, and the entry is reused
      // (one lane asked for explicitly: `--det` itself is parallel by default since G-1044)
      const s1 = det(runner, dir, ['--det-workers=1', `--det-cache=${cache}`]);
      assert.equal(s1.status, 0, show(s1));
      assert.ok(!notCached(s1)[a], show(s1));
      const s2 = det(runner, dir, ['--det-workers=1', `--det-cache=${cache}`]);
      assert.ok(reusedFiles(s2).includes(a), show(s2));
      if (runner === 'vitest') {
        // VITEST_WORKER_ID counts the files before it, serially too: never reused
        write(dir, { [`tests/e${EXT[runner]}`]: `${HEAD[runner]}\ntest('wid', () => { expect(Number(process.env.VITEST_WORKER_ID)).toBeGreaterThan(0); });\n` });
        const s3 = det(runner, dir, ['--det-workers=1', `--det-cache=${cache}`]);
        assert.match(notCached(s3)[`tests/e${EXT[runner]}`] || '', /VITEST_WORKER_ID/, show(s3));
      }
    });

    if (runner === 'jest') {
      test('state a file leaves in its worker process is reported for the files after it, which are not cached', T, () => {
        const dir = fixture(runner, 'carry', {
          a_leaker: "test('patches fs', () => { const real = fs.existsSync; fs.existsSync = (p) => real(p); expect(1).toBe(1); });",
          b_victim: "test('uses fs', () => { expect(fs.existsSync(__filename)).toBe(true); });",
          c_other: "test('c', () => { expect(1).toBe(1); });",
          d_other: "test('d', () => { expect(1).toBe(1); });",
        });
        write(dir, { 'plan.json': JSON.stringify({ lanes: [['tests/a_leaker.test.js', 'tests/b_victim.test.js'], ['tests/c_other.test.js', 'tests/d_other.test.js']] }) });
        const cache = path.join(dir, '.cache');
        for (const args of [['--det-plan=plan.json'], ['--det-workers=1']]) {
          fs.rmSync(cache, { recursive: true, force: true });
          const r = det(runner, dir, [...args, `--det-cache=${cache}`]);
          assert.equal(r.status, 0, show(r));
          assert.match(r.stderr, /CARRIED STATE tests\/b_victim\.test\.js: fs\.existsSync \(changed by tests\/a_leaker\.test\.js\)/, show(r));
          const carried = r.trace.header.meta.parallel.carried.map((c) => c.file).sort();
          assert.match(notCached(r)['tests/b_victim.test.js'] || '', /left process-wide state changed/, show(r));
          // in parallel, the other lane's process never saw the change; serially (in band) every later file did
          // (both arg lists are non-empty now, so the branch tests for the replayed plan itself)
          if (args.some((a) => a.startsWith('--det-plan'))) {
            assert.deepEqual(carried, ['tests/b_victim.test.js']);
            assert.ok(!notCached(r)['tests/d_other.test.js'], show(r));
          } else {
            assert.deepEqual(carried, ['tests/b_victim.test.js', 'tests/c_other.test.js', 'tests/d_other.test.js']);
          }
          const r2 = det(runner, dir, [...args, `--det-cache=${cache}`]);
          assert.ok(!reusedFiles(r2).includes('tests/b_victim.test.js'), show(r2));
        }
      });

      // mobx: jsdom reads the host's performance.timeOrigin while it builds the window, before Level 0 was installed in
      // the process: every result was refused as a real-clock read. The process controls now come first.
      test('jsdom environment: results are recorded and reused, serially and in lanes', T, () => {
        const dir = fixture(runner, 'jsdom-env', {
          a: "test('dom', () => { document.body.innerHTML = '<p>x</p>'; expect(document.querySelectorAll('p').length).toBe(1); });",
          b: "test('dom2', () => { expect(typeof window.performance.now()).toBe('number'); });",
          // the clock jsdom copies into the window (the read that refused mobx): virtual, the same value in every run
          c: "test('origin', () => { const o = window.performance.timeOrigin; expect(o).toBe(performance.timeOrigin); require('node:fs').writeFileSync(require('node:path').join(process.cwd(), 'origin.txt'), String(o)); });",
        }, { jest: { testEnvironment: 'jsdom' } });
        const origins = [];
        for (const args of [['--det-workers=1'], ['-w', '2']]) {
          const cache = path.join(dir, `.cache${args.join('')}`);
          fs.rmSync(path.join(dir, 'origin.txt'), { force: true });
          const r1 = det(runner, dir, [...args, `--det-cache=${cache}`]);
          assert.equal(r1.status, 0, show(r1));
          assert.equal(r1.summary.recorded, 3, show(r1));
          origins.push(fs.readFileSync(path.join(dir, 'origin.txt'), 'utf8'));
          const r2 = det(runner, dir, [...args, `--det-cache=${cache}`]);
          assert.equal(r2.summary.reused_tests, 3, show(r2));
        }
        assert.equal(origins[0], origins[1], 'performance.timeOrigin in the jsdom window is the same in every run');
      });

      test('Jest workerThreads: lanes, the capture in each worker thread, no wrong reuse after a change', T, () => {
        const dir = fixture(runner, 'wthreads', {
          a: "test('reads', () => { expect(fs.readFileSync(path.join(process.cwd(), 'value.txt'), 'utf8')).toBe('1'); });",
          b: "test('b', () => { expect(1).toBe(1); });",
          c: "test('c', () => { expect(Math.random()).toBeLessThan(1); });",
        }, { extra: { 'value.txt': '1' } });
        const cache = path.join(dir, '.cache');
        const args = ['-w', '2', '--workerThreads', `--det-cache=${cache}`];
        const r1 = det(runner, dir, args);
        assert.equal(r1.status, 0, show(r1));
        assert.ok(plan(r1), show(r1));
        assert.deepEqual(r1.trace.header.meta.parallel.placement.deviations, [], show(r1));
        assert.equal(r1.summary.recorded, 3, show(r1));
        const r2 = det(runner, dir, args);
        assert.equal(r2.summary.reused_tests, 3, show(r2));
        write(dir, { 'value.txt': '2' });
        const r3 = det(runner, dir, args);
        assert.ok(!reusedFiles(r3).includes('tests/a.test.js'), show(r3));
        assert.notEqual(r3.status, 0, 'the fresh result fails');
      });
    }

    test('the cost of serial is shown: test-file time and an estimate for --det-workers', T, () => {
      const dir = fixture(runner, 'cost', isolatedSuite(3));
      const s = det(runner, dir, ['--det-workers=1']);  // the serial cost message: one lane, asked for explicitly
      assert.match(s.stdout, /--det-workers=N/);
      assert.match(s.stderr, /detjs: serial run: 3 files, [\d.]+ s of test-file time \(MEASURED\); with --det-workers=\d+ \(this machine's CPUs\) about [\d.]+ s \(ESTIMATED/);
      assert.equal(s.trace.header.meta.parallel.timing.files, 3);
      const p = det(runner, dir, ['--det-workers=3']);
      assert.match(p.stderr, /detjs: parallel: [\d.]+ s of test-file time ran in [\d.]+ s across 3 lanes \(MEASURED/);
    });

    if (runner === 'vitest') {
      test('isolate=false (files share a worker) keeps the run serial and says so', T, () => {
        const dir = fixture(runner, 'noiso', { a: "test('a', () => { expect(1).toBe(1); });", b: "test('b', () => { expect(1).toBe(1); });" }, { vitest: { isolate: false } });
        const r = det(runner, dir, ['--det-workers=2']);
        assert.equal(r.status, 0, show(r));
        assert.match(r.stderr, /parallel refused, running serially: isolate=false/);
        assert.equal(plan(r), undefined);
        assert.match(r.trace.header.meta.parallel.requested.refused, /isolate=false/);
      });
    }

    // dom-testing-library: source-map's lazily drawn Math.random (parsing a map while Jest formats a stack) moved the
    // test's own values depending on which file came first in the process, so 2 fingerprints differed between the
    // parallel and the serial run. A draw made for the runner now uses its own stream and is not recorded.
    test('a draw a library makes for the runner does not shift the test\'s own values', T, () => {
      const req = runner === 'vitest' ? "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" : '';
      const dir = fixture(runner, 'infra-draw', {
        a: `${req}\ntest('own', () => { if (fs.existsSync('probe.on')) require('jest-probe')(); globalThis.__v = Math.random(); expect(globalThis.__v).toBeLessThan(1); });`,
      }, {
        extra: {
          // a runner package (INFRA by name) calling an ordinary library that draws
          'node_modules/jest-probe/package.json': '{"name":"jest-probe","main":"index.js"}',
          'node_modules/jest-probe/index.js': "module.exports = () => require('lazy-dep')();\n",
          'node_modules/lazy-dep/package.json': '{"name":"lazy-dep","main":"index.js"}',
          'node_modules/lazy-dep/index.js': 'module.exports = () => { let x = 0; for (let i = 0; i < 5; i++) x += Math.random(); return x; };\n',
        },
      });
      const randomEvents = (r) => r.trace.tests[0].events.filter((e) => e.s === 'random').map((e) => `${e.o}=${e.v}`);
      const off = det(runner, dir);
      assert.equal(off.status, 0, show(off));
      write(dir, { 'probe.on': '1' });
      const on = det(runner, dir);
      assert.equal(on.status, 0, show(on));
      assert.deepEqual(randomEvents(on), randomEvents(off), 'the probe\'s draws neither move the test\'s value nor appear in its events');
      assert.equal(randomEvents(on).length, 1);
    });

    // dom-testing-library again (5 of 666 fingerprints differed parallel vs serial): the same draws, made while the
    // runner's Error.prepareStackTrace hook (source-map-support) maps a stack the test's code reads, inside a deep
    // recursion (source-map's quick-sort). Two causes: inside the hook V8 gives a nested capture the default text, not
    // call sites; the recursion filled the 40 frames looked at with library frames. Both were taken as the test's.
    // Also: draws made while detjs itself formats a stack (a site lookup) never use the test's streams.
    test('a draw inside the runner\'s stack-trace hook, deep in a recursion, is not the test\'s', T, () => {
      const req = runner === 'vitest' ? "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" : '';
      const dir = fixture(runner, 'hook-draw', {
        a: `${req}\nif (fs.existsSync('probe.on')) require('source-map-support').install();\ntest('own', () => { const a = Math.random(); const e = new Error('x'); expect(typeof e.stack).toBe('string'); expect(Math.random()).not.toBe(a); });`,
      }, {
        extra: {
          // a runner package (INFRA by name) whose hook calls an ordinary library that recurses and draws
          'node_modules/source-map-support/package.json': '{"name":"source-map-support","main":"index.js"}',
          'node_modules/source-map-support/index.js': "exports.install = () => { const sort = require('deep-sort'); const prev = Error.prepareStackTrace; Error.prepareStackTrace = (e, cs) => { sort(60); return String(e) + cs.map((c) => '\\n    at ' + c).join(''); }; };\n",
          'node_modules/deep-sort/package.json': '{"name":"deep-sort","main":"index.js"}',
          'node_modules/deep-sort/index.js': 'module.exports = function sort(n) { if (n > 0) return sort(n - 1); return Math.random(); };\n',
        },
      });
      const randomEvents = (r) => r.trace.tests[0].events.filter((e) => e.s === 'random').map((e) => `${e.o}=${e.v}`);
      const off = det(runner, dir);
      assert.equal(off.status, 0, show(off));
      write(dir, { 'probe.on': '1' });
      const on = det(runner, dir);
      assert.equal(on.status, 0, show(on));
      assert.deepEqual(randomEvents(on), randomEvents(off), 'the hook\'s draws neither move the test\'s values nor appear in its events');
      assert.equal(randomEvents(on).length, 2);
    });

    // audit G-1449 / G-1456: concurrent tests ran one at a time under --det. They now run interleaved, each in its own
    // Level 0 context (src/concur.js): its events, clock and generators are its own, so its fingerprint is the same in
    // every run, serially or in lanes, whatever the interleaving.
    const concurrentCases = runner === 'vitest'
      ? [['test.concurrent', 'test.concurrent', {}], ['describe.concurrent', 'test', { wrap: 'describe.concurrent' }], ['sequence.concurrent', 'test', { config: { sequence: { concurrent: true } } }]]
      : [['test.concurrent', 'test.concurrent', {}]];
    for (const [label, fnName, how] of concurrentCases) {
      test(`${label}: tests interleave, each in its own context; fingerprints stable across runs and lanes`, T, () => {
        const outDir = path.join(TMP, 'par', `${runner}-conc-out-${label}`);
        fs.rmSync(outDir, { recursive: true, force: true });
        fs.mkdirSync(outDir, { recursive: true });
        const tests = [];
        for (let i = 0; i < 3; i++) tests.push(`${fnName}('timer ${i}', async () => { const a = Math.random(); const t0 = Date.now(); await new Promise((r) => setTimeout(r, ${(3 - i) * 100})); expect(Date.now() - t0).toBeGreaterThanOrEqual(${(3 - i) * 100}); expect(Math.random()).not.toBe(a); });`);
        // a child process prints the real time around a real 400 ms wait: overlapping intervals = the tests ran together
        for (let i = 0; i < 3; i++) tests.push(`${fnName}('child ${i}', async () => { const a = Math.random(); const out = await new Promise((r) => cp.execFile(process.execPath, ['-e', 'const t = Date.now(); setTimeout(() => console.log(t + " " + Date.now()), 400)'], (e, so) => r(String(so)))); fs.writeFileSync(${JSON.stringify(outDir)} + '/child-${i}.txt', out); expect(Math.random()).not.toBe(a); });`);
        let body = tests.join('\n');
        if (how.wrap) body = `${how.wrap}('group', () => {\n${body}\n});`;
        const dir = fixture(runner, `conc-${label.replace(/\W/g, '')}`, {
          c: `${runner === 'vitest' ? "import cp from 'node:child_process';" : "const cp = require('node:child_process');"}\n${body}`,
          d: "test('serial', () => { expect(Math.random()).toBeLessThan(1); });",
        }, { vitest: how.config || {} });
        const r1 = det(runner, dir);
        assert.equal(r1.status, 0, show(r1));
        const intervals = [0, 1, 2].map((i) => fs.readFileSync(path.join(outDir, `child-${i}.txt`), 'utf8').trim().split(' ').map(Number));
        const overlap = intervals.some(([s1, e1], i) => intervals.some(([s2], j) => i !== j && s2 >= s1 && s2 < e1));
        assert.ok(overlap, `the child tests ran at the same time: ${JSON.stringify(intervals)}`);
        const conc = r1.trace.tests.filter((t) => /(timer|child) \d$/.test(t.nodeid));
        assert.equal(conc.length, 6, JSON.stringify(r1.trace.tests.map((t) => t.nodeid)));
        for (const t of conc) {
          assert.equal(t.events.filter((e) => e.s === 'random').length, 2, `${t.nodeid}: its own two draws only`);
          assert.ok(t.events.some((e) => e.o === 'sched.concurrent'), t.nodeid);
        }
        const r2 = det(runner, dir);
        const p = det(runner, dir, ['--det-workers=2']);
        assert.equal(p.status, 0, show(p));
        assert.deepEqual(fps(r2), fps(r1));
        assert.deepEqual(fps(p), fps(r1));
        // serial vs concurrent: the same concurrent tests run one at a time (maxConcurrency=1) have the same
        // fingerprints; written as plain serial tests, every event but the `sched.concurrent` marker is the same
        const one = det(runner, dir, ['--maxConcurrency=1']);
        assert.equal(one.status, 0, show(one));
        assert.deepEqual(fps(one), fps(r1), 'maxConcurrency=1 vs concurrent');
        const evs = (r) => Object.fromEntries(r.trace.tests.map((t) => [t.nodeid,
          [t.outcome, ...t.events.filter((e) => e.o !== 'sched.concurrent').map((e) => `${e.s}|${e.o}|${e.v}`)]]));
        const conc1 = evs(r1);
        let plain = fs.readFileSync(path.join(dir, 'tests', `c${EXT[runner]}`), 'utf8').split(`${fnName}(`).join('test(');
        if (how.wrap) plain = plain.replace(`${how.wrap}(`, 'describe(');
        write(dir, { [`tests/c${EXT[runner]}`]: plain });
        if (how.config) write(dir, { 'vitest.config.mjs': `export default { test: ${JSON.stringify({ include: ['tests/**/*.test.mjs'] })} };\n` });
        const ser = det(runner, dir);
        assert.equal(ser.status, 0, show(ser));
        assert.ok(ser.trace.tests.every((t) => !t.events.some((e) => e.o === 'sched.concurrent')), 'the plain tests ran serially');
        assert.deepEqual(evs(ser), conc1, 'serial vs concurrent: same events per test');
      });
    }

    // yaml: test names with an unpaired surrogate made the policy input invalid JSON for the core ("lone leading
    // surrogate"): nothing was recorded for the whole session; napi would also turn both into U+FFFD (one id)
    test('test names with unpaired surrogates: distinct ids, recorded and reused', T, () => {
      const dir = fixture(runner, 'surrogates', {
        s: [
          "test('lone \\ud800', () => { expect(Math.random()).toBeLessThan(1); });",
          "test('lone \\ud801', () => { expect(Math.random()).toBeLessThan(1); });",
          "test('marker \\uffffd800', () => { expect(1).toBe(1); });",
          "test('pair \\ud83d\\ude00', () => { expect(1).toBe(1); });",
        ].join('\n'),
      });
      const cache = path.join(dir, '.cache');
      const r1 = det(runner, dir, [`--det-cache=${cache}`]);
      assert.equal(r1.status, 0, show(r1));
      assert.equal(new Set(r1.trace.tests.map((t) => t.nodeid)).size, 4, JSON.stringify(r1.trace.tests.map((t) => t.nodeid)));
      assert.equal(r1.summary.recorded, 4, show(r1));
      const r2 = det(runner, dir, [`--det-cache=${cache}`]);
      assert.equal(r2.summary.reused_tests, 4, show(r2));
    });
  });
}

// -- other runner versions -------------------------------------------------------------------------------------------

const VERSIONS = [
  { runner: 'vitest', dir: 'vitest3', pkg: 'vitest@3.2.7' },
  { runner: 'vitest', dir: 'vitest4', pkg: 'vitest@4.1.12' },
  { runner: 'jest', dir: 'jest29', pkg: 'jest@29.7.0' },
].filter((v) => RUNNERS.includes(v.runner));

/** A directory with the runner installed (npm; skipped when the registry is not reachable). */
function installed(v) {
  const base = path.join(TMP, 'par-runners', v.dir);
  const name = v.runner;
  if (fs.existsSync(path.join(base, 'node_modules', name, 'package.json'))) return base;
  fs.mkdirSync(base, { recursive: true });
  fs.writeFileSync(path.join(base, 'package.json'), JSON.stringify({ private: true }));
  const r = spawnSync('npm', ['install', '--no-audit', '--no-fund', '--legacy-peer-deps', v.pkg], { cwd: base, encoding: 'utf8', timeout: 300000 });
  return r.status === 0 && fs.existsSync(path.join(base, 'node_modules', name, 'package.json')) ? base : null;
}

for (const v of VERSIONS) {
  describe(`${v.pkg}: parallel lanes`, () => {
    test('plan identical across runs, fingerprints equal serial, cache reused both ways', T, (t) => {
      const base = installed(v);
      if (!base) { t.skip(`${v.pkg} could not be installed (offline?)`); return; }
      // plus three concurrent tests (each in its own Level 0 context: G-1449, G-1456; Jest 29 starts them before their
      // test_start events)
      const conc = { conc: [0, 1, 2].map((i) => `test.concurrent('c${i}', async () => { const a = Math.random(); await new Promise((r) => setTimeout(r, ${(3 - i) * 50})); expect(Math.random()).not.toBe(a); });`).join('\n') };
      const dir = fixture(v.runner, 'iso', { ...isolatedSuite(4), ...conc }, { base: path.join(base, 'fx') });
      const s = det(v.runner, dir);
      assert.equal(s.status, 0, show(s));
      const args = v.runner === 'vitest' ? ['--pool=threads', '--maxWorkers=2'] : ['--maxWorkers=2'];
      const p1 = det(v.runner, dir, args);
      const p2 = det(v.runner, dir, args);
      assert.equal(p1.status, 0, show(p1));
      assert.deepEqual(plan(p1).lanes, plan(p2).lanes);
      assert.deepEqual(p1.trace.header.meta.parallel.placement.deviations, [], show(p1));
      assert.deepEqual(fps(p1), fps(s));
      if (v.runner === 'jest') assert.deepEqual(p1.trace.header.meta.parallel.placement.processes.sort(), plan(p1).lanes.slice().sort());
      const cache = path.join(dir, '.cache');
      const c1 = det(v.runner, dir, [...args, `--det-cache=${cache}`]);
      assert.equal(c1.summary.recorded, 19, show(c1));
      const serialArgs = v.runner === 'vitest' ? ['--pool=threads'] : [];
      const c2 = det(v.runner, dir, [...serialArgs, `--det-cache=${cache}`]);
      assert.equal(c2.summary.reused_tests, 19, show(c2));
      fs.rmSync(cache, { recursive: true, force: true });
      det(v.runner, dir, [...serialArgs, `--det-cache=${cache}`]);
      const c4 = det(v.runner, dir, [...args, `--det-cache=${cache}`]);
      assert.equal(c4.summary.reused_tests, 19, show(c4));
      for (const t of s.trace.tests.filter((x) => /::c\d$/.test(x.nodeid))) assert.equal(t.events.filter((e) => e.s === 'random').length, 2, t.nodeid);
    });
  });
}

// -- Playwright ----------------------------------------------------------------------------------------------------

test('Playwright workers: placement is reported as not controlled', () => {
  const dir = path.join(TMP, 'par', 'pw');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  const log = path.join(dir, 'placement.jsonl');
  const reg = path.join(__dirname, '..', 'src', 'register.js');
  for (const i of ['0', '1']) {
    const r = spawnSync(process.execPath, ['--require', reg, '-e', 'Math.random()'], {
      cwd: dir, encoding: 'utf8', env: cleanEnv({ DETJS: '1', TEST_WORKER_INDEX: i, TEST_PARALLEL_INDEX: i, DETJS_PLAYWRIGHT_PLACEMENT: log }),
    });
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stderr, new RegExp(`Playwright worker ${i} \\(parallel index ${i}\\): placement NOT controlled`));
  }
  const rows = fs.readFileSync(log, 'utf8').trim().split('\n').map((l) => JSON.parse(l));
  assert.deepEqual(rows.map((x) => [x.parallel_index, x.placement_controlled, x.level0]), [['0', false, true], ['1', false, true]]);
});

test('Playwright Test with 2 workers (no browser needed): every worker reports placement not controlled', T, (t) => {
  const base = installed({ runner: '@playwright/test', dir: 'playwright', pkg: '@playwright/test@1.65.1' });
  if (!base) { t.skip('@playwright/test could not be installed (offline?)'); return; }
  const dir = path.join(base, 'fx');
  fs.rmSync(dir, { recursive: true, force: true });
  for (let i = 1; i <= 4; i++) write(dir, { [`tests/t${i}.spec.js`]: `const { test, expect } = require('@playwright/test'); test('t${i}', async () => { expect(Math.random()).toBeLessThan(1); await new Promise((r) => setTimeout(r, 100)); });` });
  write(dir, { 'playwright.config.js': "module.exports = { testDir: 'tests', workers: 2 };" });
  const log = path.join(dir, 'placement.jsonl');
  const reg = path.join(__dirname, '..', 'src', 'register.js');
  const cli = path.join(base, 'node_modules', '@playwright', 'test', 'cli.js');
  const r = spawnSync(process.execPath, [cli, 'test'], {
    cwd: dir, encoding: 'utf8', timeout: 120000, env: cleanEnv({ DETJS: '1', DETJS_PLAYWRIGHT_PLACEMENT: log, NODE_OPTIONS: `--require ${reg}` }),
  });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const rows = fs.readFileSync(log, 'utf8').trim().split('\n').map((l) => JSON.parse(l));
  assert.deepEqual(rows.map((x) => x.parallel_index).sort(), ['0', '1']);
  assert.ok(rows.every((x) => x.placement_controlled === false));
});
