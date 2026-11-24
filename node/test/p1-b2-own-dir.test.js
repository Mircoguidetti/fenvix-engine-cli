'use strict';
// P1 B2 (docs/DESIGN-P1.md section B, the process's own work; coordinator 2026-11-24): codex-multi-auth's setup file
// creates a sandbox HOME with mkdtemp, and code outside any test stats `<HOME>/.codex/accounts.json` (missing). In one
// run that stat happens while no test file is open (a run-wide entry), in the other it does not happen there, so the
// header's entries differ and every test of the run diverges (8,661 of 8,663). A `missing` answer for a path inside a
// directory the same process created with mkdtemp, with no child process or worker started since, is the process's
// own work and no run input.
//
// protects=a `missing` answer outside any test inside this process's own mkdtemp directory is no entry, so a run that
//   makes that stat and a run that does not are not told apart by it;
// fails_when=such an answer is still an entry (the files' tests diverge between a run that stats and a run that does
//   not), or a path that exists in one run and is missing in the other is called stable (acceptance 2), or a missing
//   answer is dropped after a child process was started, or in a directory made with mkdir (a fixed name);
// no_claim=answers other than `missing` (a file's size or bytes) stay entries, whoever wrote them.
// Red on 1541685 (before B2): the first case diverges.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const native = require('../src/native');
const { project, run, RUNNERS } = require('./helpers');

const T = { timeout: 600000 };
const VOL = 'P1B2_STAT,P1B2_MAKE';
const CP = { vitest: "import cp from 'node:child_process';", jest: "const cp = require('node:child_process');" };

function keep(r, dir, i) { const p = path.join(dir, `t${i}.jsonl`); fs.copyFileSync(r.tracePath, p); return p; }
const verify = (traces) => JSON.parse(native.verify(traces));
const status = (rep, suffix) => rep.tests.find((t) => t.nodeid.endsWith(suffix));
const entries = (r) => (r.trace.header.meta.files_read_outside_tests || []).map((e) => (typeof e === 'string' ? e : `${e.path}|${e.digest}`));

// a file whose beforeAll makes a mkdtemp directory and, when P1B2_STAT=1, stats a path inside it; when P1B2_MAKE=1 the
// path is created first
const body = (runner, extra = '') => `${CP[runner]}
beforeAll(() => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'p1b2-'));
  ${extra}
  if (process.env.P1B2_MAKE === '1') fs.writeFileSync(path.join(d, 'accounts.json'), '{}');
  if (process.env.P1B2_STAT === '1') {
    fs.existsSync(path.join(d, 'accounts.json'));
    try { fs.statSync(path.join(d, '.codex', 'auth.json')); } catch { /* missing */ }
  }
});
test('a1', () => { expect(1).toBe(1); });
test('a2', () => { expect(2).toBe(2); });`;

function pair(runner, name, files, envs) {
  const dir = project(runner, name, files);
  return envs.map((env, i) => {
    const r = run(runner, dir, ['--det', `--det-workers=${i + 1}`], { env: { FENVIX_VOLATILE_ENV: VOL, ...env } });
    assert.equal(r.status, 0, r.stdout + r.stderr);
    return { r, t: keep(r, dir, i) };
  });
}

for (const runner of RUNNERS) {
  test(`P1 B2 ${runner}: a missing path inside the process's own mkdtemp directory is no entry: a run that stats it and one that does not are stable`, T, () => {
    const [s, p] = pair(runner, 'p1b2-gain', { a: body(runner), b: `test('b1', () => { expect(3).toBe(3); });` }, [{ P1B2_STAT: '1' }, { P1B2_STAT: '0' }]);
    assert.deepEqual(entries(s.r).filter((e) => /accounts\.json|auth\.json/.test(e)), [], 'no entry for the own directory');
    const rep = verify([s.t, p.t]);
    const bad = rep.tests.filter((t) => t.status !== 'stable').map((t) => `${t.nodeid}: ${t.status}: ${t.divergence && t.divergence.description}`);
    assert.deepEqual(bad, []);
  });

  test(`P1 B2 ${runner}: acceptance 2, the path exists in one run and is missing in the other: that file's tests are not stable`, T, () => {
    const [s, p] = pair(runner, 'p1b2-real', { a: body(runner), b: `test('b1', () => { expect(3).toBe(3); });` }, [{ P1B2_STAT: '1', P1B2_MAKE: '1' }, { P1B2_STAT: '1', P1B2_MAKE: '0' }]);
    assert.ok(entries(s.r).some((e) => /accounts\.json\|stat:(present|file)/.test(e)), `an existing path stays an entry: ${entries(s.r)}`);
    const rep = verify([s.t, p.t]);
    for (const id of ['a1', 'a2']) assert.notEqual(status(rep, id).status, 'stable', id);
  });

  test(`P1 B2 ${runner}: after a child process was started, a missing path in the own directory stays an entry`, T, () => {
    const [s] = pair(runner, 'p1b2-child', { a: body(runner, "cp.spawnSync('true');") }, [{ P1B2_STAT: '1' }]);
    assert.ok(entries(s.r).some((e) => /accounts\.json\|stat:missing/.test(e)), `${entries(s.r)}`);
  });

  test(`P1 B2 ${runner}: a missing path in a directory made with mkdir (a fixed name) stays an entry`, T, () => {
    const fixed = `${CP[runner]}
beforeAll(() => {
  const d = path.join(os.tmpdir(), 'p1b2-fixed-dir');
  fs.mkdirSync(d, { recursive: true });
  fs.existsSync(path.join(d, 'accounts.json'));
});
test('a1', () => { expect(1).toBe(1); });`;
    const [s] = pair(runner, 'p1b2-mkdir', { a: fixed }, [{}]);
    assert.ok(entries(s.r).some((e) => /accounts\.json\|stat:missing/.test(e)), `${entries(s.r)}`);
  });
}
