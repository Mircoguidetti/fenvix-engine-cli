'use strict';
// P2 Phase B (spec "P2 speed", B.1; acceptance criterion 4): DETJS_PHASES=1 timing is opt-in and leaves the trace
// equal under the PREREG normalisation (harness/p2/PREREG.md §6: meta.parallel.timing, meta.parallel.placement.spans,
// meta.parallel.placement.waited_seconds removed; nothing else).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

const T = { timeout: 600000 };
const RUNNERS = (process.env.DETJS_TEST_RUNNERS || 'vitest,jest').split(',');

function fixture(runner) {
  const dir = path.join(TMP, 'p2-phases', runner);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: `p2-phases-${runner}`, private: true }));
  if (runner === 'vitest') fs.writeFileSync(path.join(dir, 'vitest.config.mjs'), "export default { test: { include: ['tests/**/*.test.mjs'] } };\n");
  else fs.writeFileSync(path.join(dir, 'jest.config.js'), "module.exports = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node' };\n");
  const head = runner === 'vitest'
    ? "import { test, expect } from 'vitest'; import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path';"
    : "const fs = require('node:fs'); const os = require('node:os'); const path = require('node:path');";
  for (let i = 1; i <= 4; i++) {
    // file I/O (ioorder tracks it), two operations in flight at once (uncontrolled.io / io.complete), the clock
    fs.writeFileSync(path.join(dir, 'tests', `f${i}.test.${runner === 'vitest' ? 'mjs' : 'js'}`), `${head}
test('t${i} io', async () => {
  const p = path.join(os.tmpdir(), 'p2ph-${runner}-${i}-' + Math.random());
  await fs.promises.writeFile(p, 'x');
  const [a, b] = await Promise.all([fs.promises.readFile(p, 'utf8'), fs.promises.stat(p)]);
  expect(a).toBe('x'); expect(b.size).toBe(1);
  await fs.promises.rm(p);
});
test('t${i} clock', () => { expect(Date.now()).toBeGreaterThan(0); });
`);
  }
  return dir;
}

function run(runner, dir, trace, env = {}) {
  fs.rmSync(path.join(dir, '.detjs'), { recursive: true, force: true }); // cold state: the plan's costs are equal
  fs.rmSync(trace, { force: true });
  fs.rmSync(`${trace}.phases.jsonl`, { force: true });
  const e = { ...process.env, ...env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'JEST_WORKER_ID', 'VITEST_POOL_ID', 'VITEST_WORKER_ID', 'DETJS_PHASES_FILE']) delete e[k];
  if (!('DETJS_PHASES' in env)) delete e.DETJS_PHASES;
  const args = runner === 'vitest' ? ['run'] : [`--cacheDirectory=${path.join(dir, '.jest-cache')}`];
  const r = spawnSync(process.execPath, [BIN, runner, ...args, '--det', '--det-workers=2', '--det-epoch=fixed', `--det-trace=${trace}`], { cwd: dir, env: e, encoding: 'utf8', timeout: 300000 });
  return r;
}

/** The trace as text lines, with the PREREG normalisation applied to the header (and only that). */
function normalised(trace) {
  const lines = fs.readFileSync(trace, 'utf8').split('\n').filter(Boolean);
  const h = JSON.parse(lines[0]);
  const p = h.meta && h.meta.parallel;
  if (p) {
    delete p.timing;
    if (p.placement) { delete p.placement.spans; delete p.placement.waited_seconds; }
  }
  return [JSON.stringify(h), ...lines.slice(1)];
}

for (const runner of RUNNERS) {
  test(`${runner}: DETJS_PHASES is off by default: no phases file, no phases env in the workers`, T, () => {
    // protects= the timing never runs unless asked for; fails_when= a default run writes <trace>.phases.jsonl;
    // no_claim= how fast the default run is
    const dir = fixture(runner);
    const trace = path.join(dir, 'off.jsonl');
    const r = run(runner, dir, trace);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.ok(fs.existsSync(trace));
    assert.equal(fs.existsSync(`${trace}.phases.jsonl`), false);
    const all = fs.readdirSync(dir);
    assert.deepEqual(all.filter((f) => f.includes('phases')), []);
  });

  test(`${runner}: DETJS_PHASES=1 leaves the trace equal under the PREREG normalisation`, T, () => {
    // protects= the timing changes no recorded event, outcome, fingerprint or header field beyond the three
    // timing fields two flag-off runs already differ in; fails_when= a phases write is tracked by ioorder/fs controls
    // (an io.* / uncontrolled.io / fs event appears) or any other trace byte changes; no_claim= the timings' accuracy
    const dir = fixture(runner);
    const a = path.join(dir, 'a.jsonl');
    const b = path.join(dir, 'b.jsonl');
    const c = path.join(dir, 'c.jsonl');
    assert.equal(run(runner, dir, a).status, 0);
    assert.equal(run(runner, dir, b).status, 0);
    // first: two flag-off runs, equal under the normalisation on their own (else PREREG's list is incomplete)
    assert.deepEqual(normalised(b), normalised(a), 'two flag-off runs differ beyond the PREREG fields: amend PREREG §6');
    const r = run(runner, dir, c, { DETJS_PHASES: '1' });
    assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.ok(fs.existsSync(`${c}.phases.jsonl`), 'flag on: phases file written');
    assert.deepEqual(normalised(c), normalised(a));
    const text = fs.readFileSync(c, 'utf8');
    // (the fixture path itself contains "p2-phases", so look for the file suffix and the variables)
    for (const s of ['.phases.jsonl', 'DETJS_PHASES']) assert.equal(text.includes(s), false, `${s} is named in the trace`);
  });

  test(`${runner}: DETJS_PHASES=1 phase lines are well formed`, T, () => {
    // protects= every timer named in PREREG §6 is written with numbers a summary can use; fails_when= a phase is
    // missing, a line is not JSON, or a worker's files carry no counters; no_claim= where the time goes
    const dir = fixture(runner);
    const trace = path.join(dir, 'on.jsonl');
    const r = run(runner, dir, trace, { DETJS_PHASES: '1' });
    assert.equal(r.status, 0, r.stdout + r.stderr);
    const lines = fs.readFileSync(`${trace}.phases.jsonl`, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
    const names = new Set(lines.map((l) => l.phase));
    for (const p of ['start', 'deps_hash', 'plan', 'workers_spawn', 'worker_ready', 'file', 'tests', 'trace_write', 'exit']) {
      assert.ok(names.has(p), `phase ${p} missing: ${[...names].join(',')}`);
    }
    for (const l of lines) {
      assert.equal(typeof l.pid, 'number');
      assert.equal(typeof l.t, 'number');
      if ('ms' in l) assert.ok(Number.isFinite(l.ms) && l.ms >= 0, JSON.stringify(l));
    }
    const files = lines.filter((l) => l.phase === 'file');
    assert.equal(files.length, 4);
    for (const f of files) for (const c of ['io_release', 'held_ms', 'stack_captures', 'uncontrolled_io']) assert.equal(typeof f[c], 'number', c);
    assert.ok(files.some((f) => f.stack_captures > 0), 'stack captures counted');
    const tests = lines.filter((l) => l.phase === 'tests');
    assert.ok(tests.length >= 1 && tests.reduce((s, t) => s + t.files, 0) === 4, JSON.stringify(tests));
    // the main process's own phases come from one pid
    assert.equal(new Set(lines.filter((l) => ['start', 'plan', 'trace_write', 'exit'].includes(l.phase)).map((l) => l.pid)).size, 1);
  });
}
