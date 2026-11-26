'use strict';
// P2 C2 (BREAKDOWN.md C2; coordinator D1 = A): a free worker slot goes to a file whose lane is free.
// Vitest: src/vitest/lanequeue.js gives the pool's queue a lane-aware shift(); DETJS_LANE_QUEUE=fifo keeps Vitest's own
// order (the "before" of these tests). Jest: unchanged (its lanes are bound to workers, src/jest/cli.js, but
// jest-runner admits at most maxWorkers files at once, so a file queued behind its lane's slow predecessor still holds
// one of them; the fix there needs jest-runner internals: open question to the coordinator). For Jest the tests
// show that DETJS_LANE_QUEUE changes nothing and record the blocking as it is.
//
// Fixture: two lanes replayed from a plan (`--det-plan`): lane 0 = [a1 (2.5 s of real time), a2], lane 1 =
// [b1, b2, b3]. Cold state, so the dispatch order is a1, b1, a2, b2, b3: with Vitest's first-in-first-out queue a2
// takes the slot b1 frees and waits there for a1, and b2/b3 start only after a1.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

const T = { timeout: 600000 };
const RUNNERS = (process.env.DETJS_TEST_RUNNERS || 'vitest,jest').split(',');
const SLOW_MS = 2500;

function fixture(runner) {
  const dir = path.join(TMP, 'p2-c2', runner);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: `p2-c2-${runner}`, private: true }));
  const ext = runner === 'vitest' ? 'mjs' : 'js';
  if (runner === 'vitest') fs.writeFileSync(path.join(dir, 'vitest.config.mjs'), "export default { test: { include: ['tests/**/*.test.mjs'] } };\n");
  else fs.writeFileSync(path.join(dir, 'jest.config.js'), "module.exports = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node' };\n");
  const head = runner === 'vitest'
    ? "import { test, expect } from 'vitest'; import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path';"
    : "const fs = require('node:fs'); const os = require('node:os'); const path = require('node:path');";
  const files = ['a1', 'a2', 'b1', 'b2', 'b3'];
  for (const f of files) {
    const body = f === 'a1'
      // real time passes (Atomics.wait blocks for real; the virtual clock advances by the timeout)
      ? `Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ${SLOW_MS});`
      : '';
    fs.writeFileSync(path.join(dir, 'tests', `${f}.test.${ext}`), `${head}
test('${f}', async () => {
  ${body}
  // a file every file writes under its own name: a footprint per file, and no hazard between them
  const p = path.join(os.tmpdir(), 'p2c2-${runner}-${f}-' + process.pid);
  await fs.promises.writeFile(p, '${f}');
  expect(await fs.promises.readFile(p, 'utf8')).toBe('${f}');
  await fs.promises.rm(p);
});
`);
  }
  const k = (f) => `tests/${f}.test.${ext}`;
  fs.writeFileSync(path.join(dir, 'plan.json'), JSON.stringify({ lanes: [[k('a1'), k('a2')], [k('b1'), k('b2'), k('b3')]] }));
  return { dir, k };
}

function run(runner, dir, trace, env = {}) {
  fs.rmSync(path.join(dir, '.detjs'), { recursive: true, force: true }); // cold state: the same dispatch order
  fs.rmSync(trace, { force: true });
  const e = { ...process.env, ...env };
  for (const x of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'JEST_WORKER_ID', 'VITEST_POOL_ID', 'VITEST_WORKER_ID', 'DETJS_PHASES', 'DETJS_PHASES_FILE']) delete e[x];
  if (!('DETJS_LANE_QUEUE' in env)) delete e.DETJS_LANE_QUEUE;
  const args = runner === 'vitest' ? ['run'] : [`--cacheDirectory=${path.join(dir, '.jest-cache')}`];
  const r = spawnSync(process.execPath, [BIN, runner, ...args, '--det', '--det-workers=2', '--det-epoch=fixed',
    `--det-plan=${path.join(dir, 'plan.json')}`, `--det-trace=${trace}`], { cwd: dir, env: e, encoding: 'utf8', timeout: 300000 });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  return r;
}

const header = (trace) => JSON.parse(fs.readFileSync(trace, 'utf8').split('\n', 1)[0]);

/** The trace with the PREREG §6 normalisation (timing, placement spans, waited seconds) and nothing else removed. */
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
  test(runner === 'vitest' ? 'vitest: a slow lane does not hold the other lane\'s files (C2)' : 'jest: a slow lane still holds a submission slot (C2 not applied to Jest)', T, () => {
    // protects= (Vitest) a lane's next file never takes a worker slot while its predecessor runs, when another lane's
    // file could run; fails_when= lane 1's files wait for lane 0's slow file (b3 ends after a1); (Jest) records the
    // current blocking; no_claim= the order inside a lane (next test), the timings of a real repository
    const { dir, k } = fixture(runner);
    const trace = path.join(dir, 'lq.jsonl');
    run(runner, dir, trace);
    const P = header(trace).meta.parallel;
    const s = P.placement.spans;
    if (runner === 'vitest') {
      assert.ok(s[k('b3')][1] < s[k('a1')][1], `b3 ended after the slow a1: ${JSON.stringify(s)}`);
      assert.ok(P.placement.waited_seconds < SLOW_MS / 1000, `waited ${P.placement.waited_seconds} s`);
    } else {
      // Jest as it is (not C2's scope yet): b2 is admitted only after a1 ends; when this fails, Jest got the fix
      assert.ok(s[k('b2')][0] >= s[k('a1')][1] - 50, `jest: b2 no longer waits for a1 (update this test): ${JSON.stringify(s)}`);
    }
  });

  test(`${runner}: the lane queue changes no result (outcomes, events, hazards, placement, proof fields) (C2)`, T, () => {
    // protects= C2 only changes which ready file takes a free slot: the trace equals the first-in-first-out run's
    // under the PREREG normalisation, so every test line (outcome, events, fingerprint, status), the plan, the
    // hazards, the processes and the deviations are the same; each file still ran in its planned lane after its lane
    // predecessor; fails_when= any of those differ, or a file starts before its lane predecessor ended;
    // no_claim= the run is faster (previous test)
    const { dir, k } = fixture(runner);
    const a = path.join(dir, 'fifo.jsonl');
    const b = path.join(dir, 'lq.jsonl');
    run(runner, dir, a, { DETJS_LANE_QUEUE: 'fifo' });
    run(runner, dir, b);
    assert.deepEqual(normalised(b), normalised(a));
    const P = header(b).meta.parallel;
    assert.deepEqual(P.plan.lanes, [[k('a1'), k('a2')], [k('b1'), k('b2'), k('b3')]]);
    assert.deepEqual(P.hazards || [], []);
    assert.deepEqual(P.placement.deviations, []);
    const s = P.placement.spans;
    for (const lane of P.plan.lanes) for (let j = 1; j < lane.length; j++) assert.ok(s[lane[j]][0] >= s[lane[j - 1]][1], `${lane[j]} started before ${lane[j - 1]} ended`);
    if (runner === 'vitest') {
      // before: b2 waited for the slow a1 (the behaviour C2 removes)
      const f = header(a).meta.parallel.placement.spans;
      assert.ok(f[k('b2')][0] >= f[k('a1')][1] - 50, `fifo: b2 started before a1 ended: ${JSON.stringify(f)}`);
    }
  });
}
