'use strict';
// P1 B1 (docs/DESIGN-P1.md section B): a file read or stat'ed while no test runs (module scope, beforeAll) went into
// the header as a run input (`files_read_outside_tests`), and a difference made EVERY test of the run diverge. Under a
// runner that isolates test files from one another (Jest; Vitest with a fresh worker per file), an entry read while a
// test file is open is scoped to that file: a difference diverges that file's tests only.
// (B2 as implemented drops only a `missing` answer inside the process's own mkdtemp directory, with no child started
// since: p1-b2-own-dir.test.js. A read of the process's own write is never dropped: the bytes written can come from a
// source nothing records outside a test. The first case below is that situation: the file's tests must still
// diverge, through the file's bytes and size.)
//
// protects=a differing read in one file's module scope or hook no longer diverges the other files' tests;
// fails_when=a test of another file diverges because of such a read, or a test of the file whose hook read bytes that
//   really differ between the runs (a file it wrote itself from /proc, or a file outside the project) is called
//   stable;
// no_claim=runners without per-file isolation (Vitest isolate: false or one shared fork, node:test, mocha, ...) keep
//   the run-wide rule.
// Red on the trunk (e7338950): the other file's tests diverge too.
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
const OUT = fs.mkdtempSync(path.join(os.tmpdir(), 'p1b-'));
const hook = () => 'beforeAll';

// every run writes .detjs/trace.jsonl: copied right after the run
function keep(r, dir, i) { const p = path.join(dir, `t${i}.jsonl`); fs.copyFileSync(r.tracePath, p); return p; }
const verify = (traces) => JSON.parse(native.verify(traces));
const status = (rep, suffix) => rep.tests.find((t) => t.nodeid.endsWith(suffix));

for (const runner of RUNNERS) {
  test(`P1 B1 ${runner}: a file the hook wrote from /proc and read back differs: that file's tests diverge, the other file's stay stable`, T, () => {
    const dir = project(runner, 'p1b-own', {
      a: `let V;
${hook(runner)}(() => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'p1b-own-'));
  const f = path.join(d, 'state.json');
  fs.writeFileSync(f, JSON.stringify({ stat: fs.readFileSync('/proc/self/stat', 'utf8'), up: fs.readFileSync('/proc/uptime', 'utf8') })); // real values (not recorded, not virtual): they differ on every run
  V = JSON.parse(fs.readFileSync(f, 'utf8'));
  fs.statSync(f); fs.existsSync(path.join(d, 'missing.json'));
});
test('a1', () => { expect(typeof V).toBe('object'); });
test('a2', () => { expect(1).toBe(1); });`,
      b: `test('b1', () => { expect(2).toBe(2); });`,
    });
    const s = run(runner, dir, ['--det', '--det-workers=1']);
    assert.equal(s.status, 0, s.stdout + s.stderr);
    const ts = keep(s, dir, 0);
    const p = run(runner, dir, ['--det', '--det-workers=2']);
    assert.equal(p.status, 0, p.stdout + p.stderr);
    const rep = verify([ts, keep(p, dir, 1)]);
    for (const id of ['a1', 'a2']) assert.notEqual(status(rep, id).status, 'stable', `${id}: its file read bytes that differ between the runs`);
    const b1 = status(rep, 'b1');
    assert.equal(b1.status, 'stable', `b1 never read the file: ${JSON.stringify(b1.divergence)}`);
  });

  // B1 and acceptance 2: the bytes really differ between the runs
  test(`P1 B1 ${runner}: a file read in one file's hook differs: that file's tests diverge, the other file's stay stable`, T, () => {
    const f = path.join(OUT, `${runner}-input.txt`);
    const dir = project(runner, 'p1b-scope', {
      a: `let V;
${hook(runner)}(() => { V = fs.readFileSync(${JSON.stringify(f)}, 'utf8'); });
test('a1', () => { fs.writeFileSync(${JSON.stringify(path.join(OUT, `${runner}-seen`))} + V, V); expect(V.length > 0).toBe(true); });`,
      b: `test('b1', () => { expect(2).toBe(2); });
test('b2', () => { expect(3).toBe(3); });`,
    });
    const runs = [0, 1].map((i) => {
      fs.writeFileSync(f, `v${i}`);
      const r = run(runner, dir, ['--det', i === 0 ? '--det-workers=1' : '--det-workers=2']);
      assert.equal(r.status, 0, r.stdout + r.stderr);
      return keep(r, dir, i);
    });
    const rep = verify(runs);
    const a1 = status(rep, 'a1');
    assert.notEqual(a1.status, 'stable', `a1 read v0 then v1 and was called stable: ${JSON.stringify(a1)}`);
    for (const id of ['b1', 'b2']) {
      const t = status(rep, id);
      assert.equal(t.status, 'stable', `${id} never read the file: ${JSON.stringify(t.divergence)}`);
    }
  });
}
