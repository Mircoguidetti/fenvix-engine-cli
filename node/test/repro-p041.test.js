'use strict';
// The options a repro driver needs (row F-02 for Node; src/repro.js): --det-order, --det-outcomes, --det-collect,
// and the `fenvix repro` line of a failing --det run.
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { project, RUNNERS, BIN } = require('./helpers');

const T = { timeout: 300000 };

function det(runner, dir, args) {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS']) delete env[k];
  const r = spawnSync(process.execPath, [BIN, runner, ...(runner === 'vitest' ? ['run'] : []), '--det', ...args],
    { cwd: dir, encoding: 'utf8', env, timeout: 120000 });
  return { status: r.status, out: `${r.stdout}\n${r.stderr}` };
}

function outcomes(dir, file = 'o.json') {
  return JSON.parse(fs.readFileSync(path.join(dir, file), 'utf8'));
}

function writeOrder(dir, ids) {
  fs.writeFileSync(path.join(dir, 'order.txt'), ids.map((i) => `${i}\n`).join(''));
  return 'order.txt';
}

// A state file outside the test realms: tests of different files share it, as polluter and victim do.
const BODY_A = `
const MARK = path.join(__dirname, '..', 'ran');
function mark(n) { fs.appendFileSync(MARK, n + '\\n'); }
beforeAll(() => mark('beforeAll-a'));
test('a1', () => { mark('a1'); });
describe('g', () => {
  test('a2', () => { mark('a2'); });
  test('a3', () => { mark('a3'); expect(1).toBe(2); });
});
test('a4', () => { mark('a4'); });
`;
const BODY_B = `
const MARK = path.join(__dirname, '..', 'ran');
function mark(n) { fs.appendFileSync(MARK, n + '\\n'); }
test('b1', () => { mark('b1'); });
test('b2', () => { mark('b2'); });
`;

function ids(runner) {
  const ext = runner === 'vitest' ? '.test.mjs' : '.test.js';
  const a = `tests/a${ext}`;
  const b = `tests/b${ext}`;
  return { a, b, a1: `${a}::a1`, a2: `${a}::g::a2`, a3: `${a}::g::a3`, a4: `${a}::a4`, b1: `${b}::b1`, b2: `${b}::b2` };
}

function ran(dir) {
  const f = path.join(dir, 'ran');
  const out = fs.existsSync(f) ? fs.readFileSync(f, 'utf8').split('\n').filter(Boolean) : [];
  fs.rmSync(f, { force: true });
  return out;
}

for (const runner of RUNNERS.filter((r) => r === 'vitest' || r === 'jest')) {
  describe(`repro options (${runner})`, () => {
    test('--det-outcomes: order, outcomes, fingerprints and exceptions of the run, the same ids as the trace', T, () => {
      const dir = project(runner, 'p041-outcomes', { a: BODY_A, b: BODY_B });
      const I = ids(runner);
      const r = det(runner, dir, ['--det-outcomes=o.json']);
      assert.equal(r.status, 1, r.out);
      const o = outcomes(dir);
      assert.deepEqual(o.order, [I.a1, I.a2, I.a3, I.a4, I.b1, I.b2]);
      assert.equal(o.outcomes[I.a3], 'failed');
      assert.equal(o.outcomes[I.a1], 'passed');
      assert.deepEqual(Object.keys(o.fingerprints).sort(), [...o.order].sort());
      assert.equal(o.exceptions[I.a3][1], 'call');
      assert.match(o.exceptions[I.a3][2], /2/);
      const line = fs.readFileSync(path.join(dir, I.a), 'utf8').split('\n').findIndex((l) => l.includes('expect(1).toBe(2)')) + 1;
      assert.equal(o.exceptions[I.a3][3], `${I.a}:${line}`);
      assert.equal(o.seed, 0);
      assert.deepEqual(o.order_missing, []);
      const trace = fs.readFileSync(path.join(dir, '.detjs', 'trace.jsonl'), 'utf8').split('\n').filter((l) => l.startsWith('{"type":"test"')).map((l) => JSON.parse(l));
      assert.deepEqual(trace.map((t) => t.nodeid), o.order);
      for (const t of trace) assert.equal(o.fingerprints[t.nodeid], t.fingerprint);
      ran(dir);
    });

    test('a failing test ends the --det run with the command that turns it into a defect', T, () => {
      const dir = project(runner, 'p041-hint', { a: BODY_A, b: BODY_B });
      const I = ids(runner);
      let r = det(runner, dir, []);
      assert.match(r.out, /1 test\(s\) failed under --det \(seed 0, fixed order\)/);
      assert.ok(r.out.includes(`    fenvix repro ${I.a3} --runner=${runner}\n`), r.out);
      r = det(runner, dir, ['--det-seed=7']);
      assert.ok(r.out.includes(`    fenvix repro ${I.a3} --runner=${runner} --seed=7\n`), r.out);
      assert.match(r.out, new RegExp(`the same run again: detjs ${runner}${runner === 'vitest' ? ' run' : ''} --det --det-seed=7`));
      ran(dir);
    });

    test('--det-collect: the order of a run with the same seed, without running a test body or a hook', T, () => {
      const dir = project(runner, 'p041-collect', { a: BODY_A, b: BODY_B });
      for (const seed of [null, 3, 11]) {
        const s = seed === null ? [] : [`--det-seed=${seed}`];
        det(runner, dir, [...s, '--det-outcomes=full.json']);
        ran(dir);
        const r = det(runner, dir, [...s, '--det-collect', '--det-outcomes=col.json']);
        assert.equal(r.status, 0, r.out);
        assert.deepEqual(ran(dir), [], 'a test body or hook ran during collection');
        const col = outcomes(dir, 'col.json');
        assert.equal(col.collect, true);
        assert.deepEqual(col.order, outcomes(dir, 'full.json').order, `seed ${seed}`);
        assert.ok(Object.values(col.outcomes).every((x) => x === 'collected'));
      }
    });

    test('--det-order: exactly the listed tests, in the listed order (files by first listed test), across describe blocks', T, () => {
      const dir = project(runner, 'p041-order', { a: BODY_A, b: BODY_B });
      const I = ids(runner);
      const order = [I.b2, I.a4, I.a2, I.a3];
      const r = det(runner, dir, [`--det-order=${writeOrder(dir, [...order, `${I.a}::nope`])}`, '--det-outcomes=o.json']);
      const o = outcomes(dir);
      assert.deepEqual(o.order, order, r.out);
      assert.deepEqual(ran(dir), ['b2', 'beforeAll-a', 'a4', 'a2', 'a3']);
      assert.deepEqual(o.order_missing, [`${I.a}::nope`]);
      assert.equal(o.order_regrouped, false);
      assert.equal(o.outcomes[I.a3], 'failed');
      assert.equal(o.outcomes[I.b2], 'passed');
      // the same test, the same events: its fingerprint does not depend on which other tests ran
      det(runner, dir, ['--det-outcomes=full.json']);
      ran(dir);
      assert.equal(o.fingerprints[I.a3], outcomes(dir, 'full.json').fingerprints[I.a3]);
    });

    test('--det-order that interleaves files is run grouped by file and says so', T, () => {
      const dir = project(runner, 'p041-regroup', { a: BODY_A, b: BODY_B });
      const I = ids(runner);
      const r = det(runner, dir, [`--det-order=${writeOrder(dir, [I.a1, I.b1, I.a4])}`, '--det-outcomes=o.json']);
      const o = outcomes(dir);
      assert.deepEqual(o.order, [I.a1, I.a4, I.b1]);
      assert.equal(o.order_regrouped, true);
      assert.match(r.out, /--det-order interleaves test files or describe blocks/);
      ran(dir);
    });

    test('--det-order with a seed: the listed order wins over the shuffle, the seed still seeds Math.random', T, () => {
      const dir = project(runner, 'p041-seed', { a: "test('r1', () => { fs.writeFileSync(path.join(__dirname, '..', 'r1-' + process.env.DETJS_SEED), String(Math.random())); });\ntest('r2', () => {});" });
      const ext = runner === 'vitest' ? '.test.mjs' : '.test.js';
      const order = [`tests/a${ext}::r2`, `tests/a${ext}::r1`];
      det(runner, dir, ['--det-seed=4', `--det-order=${writeOrder(dir, order)}`, '--det-outcomes=o.json']);
      assert.deepEqual(outcomes(dir).order, order);
      det(runner, dir, ['--det-seed=4', '--det-outcomes=full.json']);
      const v4 = fs.readFileSync(path.join(dir, 'r1-4'), 'utf8');
      det(runner, dir, ['--det-seed=4', `--det-order=${writeOrder(dir, [order[1]])}`, '--det-outcomes=o.json']);
      assert.equal(fs.readFileSync(path.join(dir, 'r1-4'), 'utf8'), v4, 'r1 alone drew a different value under the same seed');
      det(runner, dir, ['--det-seed=5', `--det-order=${writeOrder(dir, [order[1]])}`, '--det-outcomes=o.json']);
      assert.notEqual(fs.readFileSync(path.join(dir, 'r1-5'), 'utf8'), v4);
    });

    test('a listed test whose file fails to load is an error with the load error, not a missing test', T, () => {
      const dir = project(runner, 'p041-load', { a: "test('a1', () => {});", c: "throw new Error('module level failure');\ntest('c1', () => {});" });
      const ext = runner === 'vitest' ? '.test.mjs' : '.test.js';
      const id = `tests/c${ext}::c1`;
      const r = det(runner, dir, [`--det-order=${writeOrder(dir, [`tests/a${ext}::a1`, id])}`, '--det-outcomes=o.json']);
      const o = outcomes(dir);
      assert.equal(o.outcomes[id], 'error', r.out);
      assert.match(o.exceptions[id][2], /module level failure/);
      assert.equal(o.exceptions[id][1], 'collect');
      assert.deepEqual(o.order_missing, []);
    });

    test('--det-order names a missing file: a clear error', T, () => {
      const dir = project(runner, 'p041-nofile', { a: "test('a1', () => {});" });
      const r = det(runner, dir, ['--det-order=missing.txt']);
      assert.notEqual(r.status, 0);
      assert.match(r.out, /--det-order: no such file missing\.txt/);
    });
  });
}
