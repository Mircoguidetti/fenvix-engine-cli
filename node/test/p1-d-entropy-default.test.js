'use strict';
// P1 D (docs/DESIGN-P1.md section D; decision 2026-11-23: option 3): under --det, crypto.randomBytes /
// randomFillSync / randomInt draw from a per-test deterministic stream by default; `--det-urandom=off` opts out; the
// draws stay recorded as `entropy` events. Protocol nonces keep their own seeded stream (src/seeds.js `nonce`) and
// native key generation stays observed, as on the trunk.
//
// protects=a test that draws random bytes (a temp-file suffix, an id) is identical between the serial and the parallel
//   run without any flag;
// fails_when=the serial and parallel runs of such a test are not stable by default, or two runs whose bytes differ
//   (--det-urandom=off, or another --det-seed) are called stable;
// no_claim=native key generation (generateKeyPair*) stays observed: a test using it is not made identical.
// Red on the trunk (e7338950): the drawing tests diverge (`crypto.randomBytes` returned different values).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const native = require('../src/native');
const { project, run, RUNNERS } = require('./helpers');

const T = { timeout: 600000 };
const body = (name) => `test('${name}1', () => {
  const id = nodeCrypto.randomBytes(8).toString('hex');
  const b = Buffer.alloc(4); nodeCrypto.randomFillSync(b);
  const n = nodeCrypto.randomInt(1000);
  fs.writeFileSync(path.join(process.env.P1D_OUT, path.basename(process.cwd()) + '-${name}-' + process.env.P1D_RUN), JSON.stringify([id, b.toString('hex'), n]));
  expect(id.length).toBe(16);
});
test('${name}2', () => { expect(1).toBe(1); });`;
const os = require('node:os');
const OUT = fs.mkdtempSync(path.join(os.tmpdir(), 'p1d-'));
// where the tests write what they drew (declared irrelevant: P1D_RUN differs between the runs on purpose)
const VOL = { FENVIX_VOLATILE_ENV: 'P1D_RUN,P1D_OUT', P1D_OUT: OUT };

function keep(r, dir, name) {
  const p = path.join(dir, `${name}.jsonl`);
  fs.copyFileSync(r.tracePath, p);
  return p;
}
const seen = (dir, name) => fs.readFileSync(path.join(OUT, `${path.basename(dir)}-${name}`), 'utf8');

for (const runner of RUNNERS) {
  test(`P1 D ${runner}: random bytes drawn by tests: serial = parallel by default, all stable`, T, () => {
    const dir = project(runner, 'p1d-same', { a: body('a'), b: body('b') });
    const s = run(runner, dir, ['--det', '--det-workers=1'], { env: { ...VOL, P1D_RUN: 's' } });
    assert.equal(s.status, 0, s.stdout + s.stderr);
    const ts = keep(s, dir, 'serial');
    const p = run(runner, dir, ['--det', '--det-workers=2'], { env: { ...VOL, P1D_RUN: 'p' } });
    assert.equal(p.status, 0, p.stdout + p.stderr);
    assert.equal(seen(dir, 'a-s'), seen(dir, 'a-p'), 'the same bytes in both runs');
    assert.notEqual(seen(dir, 'a-p'), seen(dir, 'b-p'), 'two tests draw different bytes');
    const rep = JSON.parse(native.verify([ts, keep(p, dir, 'par')]));
    const bad = rep.tests.filter((t) => t.status !== 'stable').map((t) => `${t.nodeid}: ${t.status}: ${t.divergence && t.divergence.description}`);
    assert.deepEqual(bad, []);
    assert.ok(p.trace.tests.flatMap((t) => t.events).some((e) => e.s === 'entropy' && e.o === 'crypto.randomBytes'), 'the draws are still events');
    assert.equal(p.trace.header.meta.entropy, 'controlled');
  });

  // acceptance 2: the bytes really differ between the two runs
  for (const [label, args] of [['--det-urandom=off', ['--det-urandom=off']], ['another --det-seed', null]]) {
    test(`P1 D ${runner}: bytes that differ between the runs (${label}) are never called stable`, T, () => {
      const dir = project(runner, `p1d-diff-${label.replace(/[^a-z]+/g, '')}`, { a: body('a') });
      const traces = [0, 1].map((i) => {
        const extra = args || [`--det-seed=${i + 1}`];
        const r = run(runner, dir, ['--det', '--det-workers=1', ...extra], { env: { ...VOL, P1D_RUN: `r${i}` } });
        assert.equal(r.status, 0, r.stdout + r.stderr);
        return keep(r, dir, `t${i}`);
      });
      assert.notEqual(seen(dir, 'a-r0'), seen(dir, 'a-r1'), 'the test drew different bytes');
      const rep = JSON.parse(native.verify(traces));
      const a1 = rep.tests.find((t) => t.nodeid.endsWith('a1'));
      assert.notEqual(a1.status, 'stable', JSON.stringify(a1));
    });
  }
}

// Found by the full suite after D (Playwright's worker exited: two dispatchers got the same GUID): before the
// streams are seeded in a process (a runner's or a library's start-up, before any test or test file), the controlled
// stream gave zero bytes on every draw, an unseeded xoshiro state. Those draws now stay real (observed).
// Red on the trunk with --det-urandom (f67be4a) and on this branch before the fix: 00000000... twice.
test('P1 D: a draw made before any test or file seeded the streams is not a constant', T, () => {
  const src = path.join(__dirname, '..', 'src');
  const script = `
const { STATE } = require(${JSON.stringify(path.join(src, 'state'))});
STATE.config = { urandom: true, seed: 0n };
const { Patcher } = require(${JSON.stringify(path.join(src, 'patch'))});
const seeds = require(${JSON.stringify(path.join(src, 'seeds'))});
const crypto = require('node:crypto');
seeds.installProcess(new Patcher(), STATE.config);
const early = [crypto.randomBytes(16).toString('hex'), crypto.randomBytes(16).toString('hex'), String(crypto.randomInt(1e9)), String(crypto.randomInt(1e9))];
seeds.seedFile('f'); const f1 = crypto.randomBytes(16).toString('hex');
seeds.seedFile('f'); const f2 = crypto.randomBytes(16).toString('hex');
process.stdout.write(JSON.stringify({ early, f1, f2 }));`;
  const r = require('node:child_process').spawnSync(process.execPath, ['-e', script], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  const { early, f1, f2 } = JSON.parse(r.stdout);
  assert.notEqual(early[0], '0'.repeat(32), 'zero bytes before seeding');
  assert.notEqual(early[0], early[1], 'two draws before seeding gave the same bytes');
  assert.notEqual(early[2], early[3], 'two randomInt draws before seeding gave the same value');
  // once seeded, the stream is controlled: the same file key gives the same bytes
  assert.equal(f1, f2);
});
