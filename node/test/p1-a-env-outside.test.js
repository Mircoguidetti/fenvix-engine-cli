'use strict';
// P1 A1 (docs/DESIGN-P1.md section A): a KEPT or proxy environment variable (TMPDIR, PWD, HTTPS_PROXY, ...) read
// outside any test -- module scope of a test file -- is not a run input (its value differs between CI machines), so the
// trunk marked EVERY test of the run NOT PROVEN (`not_proven_outside_tests`), although `verify` compares two given
// runs and the value was the same in both. A1 records the value's digest with the mark; verify discharges the mark
// when both runs saw the same value and reports the tests input-differs / NOT PROVEN when they did not.
//
// protects=a variable read outside any test with the same value in both runs no longer makes every test NOT PROVEN,
//   and a different value is never called identical;
// fails_when=two one-worker runs with the same environment leave a test NOT PROVEN for an `env:` entry, a one-worker
//   run compared with a two-worker run is called stable through one (fail-safe of 2026-11-24), or two
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
const helpers = require('./helpers');
const { project, RUNNERS } = helpers;
// two separate runs are compared: --det-epoch=fixed, the opt-out of det-host-values' per-run host epoch (merged from
// release-1 9ac63d6), as the trunk's own two-run tests do; a test that names its own epoch keeps it
const run = (runner, dir, args = [], opts) =>
  helpers.run(runner, dir, args.includes('--det') && !args.some((x) => x.startsWith('--det-epoch')) ? [...args, '--det-epoch=fixed'] : args, opts);

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
  // fail-safe of 2026-11-24 (founder decision D1 = C, eng review of the P1 merge): the entries are one set per run, so
  // a run with several workers does not say which worker saw which value; the entry is discharged only when every
  // compared run used one worker (fails_when also: a serial run compared with a two-worker run is called stable
  // through an `env:` entry; red on 0358ea4, where it was)
  test(`P1 A1 ${runner}: TMPDIR and the environment read at module scope, same values: two one-worker runs all stable, one-worker vs two-worker NOT PROVEN`, T, () => {
    const dir = project(runner, 'p1a-same', files(runner));
    const tmp = path.join(OUT, `${runner}-same`);
    fs.mkdirSync(tmp, { recursive: true });
    const env = { TMPDIR: tmp, P1A_OUT: path.join(OUT, `${runner}-same.out`) };
    const s = run(runner, dir, ['--det', '--det-workers=1'], { env });
    assert.equal(s.status, 0, s.stdout + s.stderr);
    const ts = trace(s, dir, 'serial');
    const s2 = run(runner, dir, ['--det', '--det-workers=1'], { env });
    assert.equal(s2.status, 0, s2.stdout + s2.stderr);
    const ts2 = trace(s2, dir, 'serial2');
    const p = run(runner, dir, ['--det', '--det-workers=2'], { env });
    assert.equal(p.status, 0, p.stdout + p.stderr);
    const tp = trace(p, dir, 'par');
    const np = s.trace.header.meta.not_proven_outside_tests || [];
    assert.ok(np.some((e) => e.startsWith('env:TMPDIR')), `the module-scope read is recorded: ${JSON.stringify(np)}`);
    const rep = JSON.parse(native.verify([ts, ts2]));
    const bad = rep.tests.filter((t) => t.status !== 'stable').map((t) => `${t.nodeid}: ${t.status}: ${t.divergence && t.divergence.description}`);
    assert.deepEqual(bad, [], 'same values in two one-worker runs: nothing differs');
    assert.equal(rep.summary.stable, 4);
    const mixed = JSON.parse(native.verify([ts, tp]));
    const st = mixed.tests.map((t) => `${t.nodeid}: ${t.status}`);
    assert.ok(mixed.tests.every((t) => t.status === 'not-proven'), `one-worker vs two-worker: every test NOT PROVEN: ${st}`);
    assert.ok(mixed.tests[0].divergence.description.includes('env:TMPDIR'), mixed.tests[0].divergence.description);
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

// Review of 2026-11-24 (security / adversarial finding 1): the digest of `HTTPS_PROXY=http://user:pass@host` is a short
// unkeyed hash of a credential, written into the trace header, where a weak password can be recovered offline. A value
// carrying URL credentials gets no digest: the entry is the name alone, never discharged (the trunk's verdict: NOT
// PROVEN); a value without credentials keeps its digest. protects=no credential-bearing value is hashed into the
// trace, and dropping the digest never lets a run be called stable through that entry; fails_when=the header holds a
// digest for a credential-bearing proxy value, or the tests of such runs are reported stable.
for (const runner of RUNNERS) {
  test(`P1 A1 ${runner}: a proxy URL with credentials read outside any test gets no digest and stays NOT PROVEN`, T, () => {
    const dir = project(runner, 'p1a-cred', { c: `const P = String(process.env.HTTPS_PROXY); const Q = String(process.env.HTTP_PROXY);
test('c1', () => { expect(P.length > 0 && Q.length > 0).toBe(true); });` });
    const env = { HTTPS_PROXY: 'http://alice:s3cret@proxy.invalid:8080', HTTP_PROXY: 'http://proxy.invalid:8080' };
    const traces = [];
    for (const w of [1, 2]) {
      const r = run(runner, dir, ['--det', '--det-net=closed', `--det-workers=${w}`], { env });
      assert.equal(r.status, 0, r.stdout + r.stderr);
      const np = r.trace.header.meta.not_proven_outside_tests || [];
      assert.ok(np.includes('env:HTTPS_PROXY'), `the credential-bearing value is named without a digest: ${JSON.stringify(np)}`);
      assert.ok(!np.some((e) => e.startsWith('env:HTTPS_PROXY=')), `no digest of a credential: ${JSON.stringify(np)}`);
      assert.ok(np.some((e) => e.startsWith('env:HTTP_PROXY=')), `a value without credentials keeps its digest: ${JSON.stringify(np)}`);
      traces.push(trace(r, dir, `cred${w}`));
    }
    const rep = JSON.parse(native.verify(traces));
    assert.equal(rep.tests.find((t) => t.nodeid.endsWith('c1')).status, 'not-proven');
  });
}
