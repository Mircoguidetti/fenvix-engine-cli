'use strict';
// P1 C (docs/DESIGN-P1.md section C): `process.pid` was observed (the real value, hashed into a `process.pid` event),
// so every test that read it -- a logger printing `[Nest] <pid>`, a lock file naming its owner -- diverged between a
// serial and a parallel run. C gives test code a virtual pid per test file: a function of the run seed and the file,
// the same in every run of that file, different for two files that run at the same time, above Linux's PID_MAX_LIMIT
// (never another live process's pid); process.kill on it reaches the real process.
//
// protects=a test reading process.pid is identical between the serial and the parallel run, and two files running
//   concurrently never see the same pid (paths built from it do not collide);
// fails_when=the serial and parallel runs of a pid-reading test are not stable, two concurrent files read the same
//   pid, process.kill(process.pid, 0) fails, or two runs whose pids differ (different --det-seed) are called stable;
// no_claim=child processes and native code (getpid(2)) still see real pids.
// Red on the trunk (e7338950): the pid-reading tests diverge (`process.pid` returned different values).
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
const OUT = fs.mkdtempSync(path.join(os.tmpdir(), 'p1c-'));
// where the tests write what they saw: declared irrelevant by the project (they differ between the runs on purpose)
const VOL = { FENVIX_VOLATILE_ENV: 'P1C_OUT,P1C_RUN' };

// each file reads its pid (an event), builds a path from it and writes what it saw
const body = (name) => `test('${name}1', () => {
  const pid = process.pid;
  fs.writeFileSync(path.join(process.env.P1C_OUT, '${name}-' + process.env.P1C_RUN), String(pid));
  const d = path.join(os.tmpdir(), 'p1c-' + pid);
  fs.mkdirSync(d, { recursive: true });
  expect(Number.isInteger(pid) && pid > 0).toBe(true);
});
test('${name}2', async () => { await sleepP(50); expect(1).toBe(1); });`;

function trace(r, dir, name) {
  const p = path.join(dir, `${name}.jsonl`);
  fs.copyFileSync(r.tracePath, p);
  return p;
}
const seen = (name, i) => fs.readFileSync(path.join(OUT, `${name}-${i}`), 'utf8');

for (const runner of RUNNERS) {
  test(`P1 C ${runner}: process.pid read by tests: serial = parallel, all stable; concurrent files differ`, T, () => {
    const dir = project(runner, 'p1c-same', { a: body('a'), b: body('b') });
    const s = run(runner, dir, ['--det', '--det-workers=1'], { env: { ...VOL, P1C_OUT: OUT, P1C_RUN: `${runner}s` } });
    assert.equal(s.status, 0, s.stdout + s.stderr);
    const ts = trace(s, dir, 'serial'); // copied now: the next run overwrites .detjs/trace.jsonl
    const p = run(runner, dir, ['--det', '--det-workers=2'], { env: { ...VOL, P1C_OUT: OUT, P1C_RUN: `${runner}p` } });
    assert.equal(p.status, 0, p.stdout + p.stderr);
    assert.equal(seen('a', `${runner}s`), seen('a', `${runner}p`), 'a file sees the same pid in both runs');
    assert.notEqual(seen('a', `${runner}p`), seen('b', `${runner}p`), 'two files see different pids');
    const rep = JSON.parse(native.verify([ts, trace(p, dir, 'par')]));
    const bad = rep.tests.filter((t) => t.status !== 'stable').map((t) => `${t.nodeid}: ${t.status}: ${t.divergence && t.divergence.description}`);
    assert.deepEqual(bad, []);
    assert.equal(rep.summary.stable, 4);
    const ev = p.trace.tests.flatMap((t) => t.events).filter((e) => e.o === 'process.pid');
    assert.ok(ev.length >= 2, 'the reads are still events');
  });

  // process.kill on the virtual pid reaches this process (the call itself is a gap of the general rule:
  // `api:process._kill`, NOT PROVEN on the trunk too, so this case checks the call, not the verdict)
  test(`P1 C ${runner}: process.kill(process.pid, 0) succeeds on the virtual pid`, T, () => {
    const dir = project(runner, 'p1c-kill', { k: `test('k', () => { expect(process.pid > 4194304).toBe(true); expect(process.kill(process.pid, 0)).toBe(true); expect(() => process.kill(2147480000, 0)).toThrow(); expect(process.ppid < 4194304).toBe(true); });` });
    const r = run(runner, dir, ['--det', '--det-workers=1'], {});
    assert.equal(r.status, 0, r.stdout + r.stderr);
  });

  // acceptance 2: the pid the test sees really differs between the two runs
  test(`P1 C ${runner}: a different pid between the runs (another seed) is never called stable`, T, () => {
    const dir = project(runner, 'p1c-diff', { a: body('a') });
    const traces = [];
    for (const i of [0, 1]) {
      const r = run(runner, dir, ['--det', `--det-seed=${i + 1}`, '--det-workers=1'], { env: { ...VOL, P1C_OUT: OUT, P1C_RUN: `${runner}d${i}` } });
      assert.equal(r.status, 0, r.stdout + r.stderr);
      traces.push(trace(r, dir, `t${i}`));
    }
    assert.notEqual(seen('a', `${runner}d0`), seen('a', `${runner}d1`), 'the test saw two different pids');
    const rep = JSON.parse(native.verify(traces));
    const a1 = rep.tests.find((t) => t.nodeid.endsWith('a1'));
    assert.notEqual(a1.status, 'stable', JSON.stringify(a1));
  });
}
