'use strict';
// Coordinator decision 2026-11-23 (det-host-values, D1 = A): the deadline clock hook (src/deadline.js
// installClockHook) must recognise the class-field initializer frame of Vitest's `TaskDeadline` under both names V8
// gives it: `<instance_members_initializer>` (Vitest 5.1.0's build) and `TaskDeadline.<instance_members_initializer>`
// (Vitest 5.0.5's build, codex-multi-auth). With the second name unrecognised, `TaskDeadline.startTime` is read on
// the real clock while `exceeded()` reads the deadline clock, and every test after one that charged more than its
// timeout of virtual time fails "Test timed out" at once (harness/det_host_values/REPORT.md section 2).
//
// protects: the runner's start-time read and its deadline check use the same (deadline) clock for both frame names.
// fails_when: a frame name of the initializer is not recognised (the hook returns undefined -> the real clock).
// no_claim: Vitest itself is not run here; the stacks are the frames observed in Vitest 5.0.5 and 5.1.0 runs.
// Run: cd node && node --test test/deadline-initializer.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const SRC = path.join(__dirname, '..', 'src');
// A child process: the preload's box, the virtual clock and a running test, then the hook fed stack strings.
const CHILD = `
process.env.DETJS = '1';
require(${JSON.stringify(path.join(SRC, 'deadline-preload.js'))});
const config = require(${JSON.stringify(path.join(SRC, 'config.js'))});
const clock = require(${JSON.stringify(path.join(SRC, 'clock.js'))});
const { Patcher } = require(${JSON.stringify(path.join(SRC, 'patch.js'))});
const { STATE } = require(${JSON.stringify(path.join(SRC, 'state.js'))});
clock.installProcess(new Patcher(), config.fromEnv({ DETJS: '1', DETJS_EPOCH: '2025-01-01T00:00:00Z' }));
STATE.testId = 'tests/a.test.mjs::t';
const box = globalThis[Symbol.for('detjs.deadlineClock')];
const VITEST = 'file:///p/node_modules/vitest/dist/chunks/run.BPv-BBRv.js';
const head = ['Error', '    at stackOf (deadline.js:1:1)', '    at deadlineClock (deadline.js:2:2)', '    at Performance.now (deadline-preload.js:20:44)'];
function feed(frames) {
  const prev = Error.prepareStackTrace;
  Error.prepareStackTrace = () => [...head, ...frames].join('\\n');
  try { return box.hook('perf'); } finally { Error.prepareStackTrace = prev; }
}
const out = {
  plain: feed(['    at <instance_members_initializer> (' + VITEST + ':3200:13)', '    at new TaskDeadline (' + VITEST + ':3204:2)']),
  qualified: feed(['    at TaskDeadline.<instance_members_initializer> (' + VITEST + ':3200:13)', '    at new TaskDeadline (' + VITEST + ':3204:2)']),
  noVitest: feed(['    at TaskDeadline.<instance_members_initializer> (file:///p/src/deadline.js:3:3)', '    at new TaskDeadline (file:///p/src/deadline.js:4:4)']),
};
process.stdout.write(JSON.stringify(out));
`;

function hookResults() {
  const r = spawnSync(process.execPath, ['-e', CHILD], { encoding: 'utf8', env: { ...process.env, DETJS: '1' } });
  assert.equal(r.status, 0, `child failed\n${r.stdout}\n${r.stderr}`);
  return JSON.parse(r.stdout);
}

test('the deadline hook answers the TaskDeadline start-time read under both initializer frame names', () => {
  const out = hookResults();
  assert.equal(typeof out.plain, 'number', `'at <instance_members_initializer>' + Vitest frame: ${JSON.stringify(out)}`);
  assert.equal(typeof out.qualified, 'number', `'at TaskDeadline.<instance_members_initializer>' + Vitest frame (Vitest 5.0.5): ${JSON.stringify(out)}`);
});

test('without a Vitest runner frame the hook leaves the clock real (returns undefined)', () => {
  const out = hookResults();
  assert.equal(out.noVitest, undefined, JSON.stringify(out));
});
