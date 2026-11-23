'use strict';
// P1 A1 (docs/DESIGN-P1.md section A): a KEPT or proxy environment variable (TMPDIR, PWD, HTTPS_PROXY, ...) read
// outside any test -- module scope of a test file -- is not a run input (its value differs between CI machines), so the
// trunk marked EVERY test of the run NOT PROVEN (`not_proven_outside_tests`), although `verify` compares two given
// runs and the value was the same in both. A1 records the value's digest with the mark; verify discharges the mark
// when both runs saw the same value and reports the tests input-differs / NOT PROVEN when they did not.
//
// protects=a variable read outside any test with the same value in both runs no longer makes every test NOT PROVEN,
//   and a different value is never called identical;
// fails_when=serial and parallel runs with the same environment leave a test NOT PROVEN for an `env:` entry, or two
//   runs whose TMPDIR differs (read at module scope, written by the test) report every test stable;
// no_claim=the cache (one run, no second to compare with) keeps refusing such tests; non-env entries
//   (`api:`, `native:`) are unchanged.
// Red on the trunk (e7338950): the first test reports every test not-proven.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const native = require('../src/native');
const { project, run, RUNNERS } = require('./helpers');

const T = { timeout: 600000 };
const OUT = fs.mkdtempSync(path.join(os.tmpdir(), 'p1a-'));

function files(runner) {
  return {
    // module scope: a KEPT variable and an enumeration of the environment (an `env.list` outside any test)
    a: `const SEEN = String(process.env.TMPDIR); const N = Object.keys(process.env).length;
test('a1', () => { fs.writeFileSync(process.env.P1A_OUT, SEEN); expect(N > 0).toBe(true); });
test('a2', () => { expect(1).toBe(1); });`,
    b: `test('b1', () => { expect(2).toBe(2); });
test('b2', () => { expect(3).toBe(3); });`,
  };
}

function trace(r, dir, name) {
  const p = path.join(dir, `${name}.jsonl`);
  fs.copyFileSync(r.tracePath, p);
  return p;
}

for (const runner of RUNNERS) {
  test(`P1 A1 ${runner}: TMPDIR and the environment read at module scope, same values: serial = parallel, all stable`, T, () => {
    const dir = project(runner, 'p1a-same', files(runner));
    const tmp = path.join(OUT, `${runner}-same`);
    fs.mkdirSync(tmp, { recursive: true });
    const env = { TMPDIR: tmp, P1A_OUT: path.join(OUT, `${runner}-same.out`) };
    const s = run(runner, dir, ['--det', '--det-workers=1'], { env });
    assert.equal(s.status, 0, s.stdout + s.stderr);
    const ts = trace(s, dir, 'serial');
    const p = run(runner, dir, ['--det', '--det-workers=2'], { env });
    assert.equal(p.status, 0, p.stdout + p.stderr);
    const tp = trace(p, dir, 'par');
    const np = s.trace.header.meta.not_proven_outside_tests || [];
    assert.ok(np.some((e) => e.startsWith('env:TMPDIR')), `the module-scope read is recorded: ${JSON.stringify(np)}`);
    const rep = JSON.parse(native.verify([ts, tp]));
    const bad = rep.tests.filter((t) => t.status !== 'stable').map((t) => `${t.nodeid}: ${t.status}: ${t.divergence && t.divergence.description}`);
    assert.deepEqual(bad, [], 'same values in both runs: nothing differs');
    assert.equal(rep.summary.stable, 4);
  });

  // acceptance 2: the value really differs between the two runs
  test(`P1 A1 ${runner}: TMPDIR differs between the runs: the tests are never all stable`, T, () => {
    const dir = project(runner, 'p1a-diff', files(runner));
    const vals = [];
    const traces = [];
    for (const i of [0, 1]) {
      const tmp = path.join(OUT, `${runner}-diff${i}`);
      fs.mkdirSync(tmp, { recursive: true });
      const out = path.join(OUT, `${runner}-diff.out`);
      const r = run(runner, dir, ['--det', i === 0 ? '--det-workers=1' : '--det-workers=2'], { env: { TMPDIR: tmp, P1A_OUT: out } });
      assert.equal(r.status, 0, r.stdout + r.stderr);
      vals.push(fs.readFileSync(out, 'utf8'));
      traces.push(trace(r, dir, `t${i}`));
    }
    assert.notEqual(vals[0], vals[1], 'the test observed two different values');
    const rep = JSON.parse(native.verify(traces));
    const a1 = rep.tests.find((t) => t.nodeid.endsWith('a1'));
    assert.ok(a1, JSON.stringify(rep.tests.map((t) => t.nodeid)));
    assert.notEqual(a1.status, 'stable', `a1 observed ${JSON.stringify(vals)} and was called stable`);
    assert.ok(['input-differs', 'not-proven', 'diverged'].includes(a1.status), a1.status);
  });
}
