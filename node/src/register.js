'use strict';
// Level 0 inside Playwright Test worker processes (measurement only).
//
//   NODE_OPTIONS="--require <detjs>/src/register.js" DETJS=1 npx playwright test --workers=1
//
// Activates only in Playwright workers (TEST_WORKER_INDEX is set), so the
// runner process and the web servers it starts are left alone. It installs
// the process-wide and realm controls (seeds, clock, timers, fs order, closed
// network for the test process) but has no per-test brackets: randomness is
// seeded once per worker, the wall clock is not reset per test and no trace
// is written. The browser is a separate process and is not controlled at all.
//
// Placement: Playwright's dispatcher hands test groups to whichever worker is free, so with more than one worker
// which tests share a worker process (and its state) is decided at run time; detjs does not control it. Every
// worker says so on stderr (once) and appends its identity to `$DETJS_PLAYWRIGHT_PLACEMENT` when set; use
// `--workers=1` for a fixed placement. Playwright >= 1.5x sets TEST_WORKER_INDEX only after the worker started (after
// this preload): such workers are recognised by their entry module, the controls are NOT installed in them (Level 0
// does not reach their tests), and the placement report is written when the worker exits.
const PW_WORKER = /[\\/]playwright[\\/]lib[\\/](?:worker[\\/]workerProcessEntry|common[\\/]process)\.js$/;

function reportPlacement(controlled) {
  const report = () => {
    const parallelIndex = process.env.TEST_PARALLEL_INDEX;
    if (process.env.DETJS_PLAYWRIGHT_QUIET !== '1') {
      process.stderr.write(`detjs: Playwright worker ${process.env.TEST_WORKER_INDEX} (parallel index ${parallelIndex}): `
        + `placement NOT controlled: Playwright assigns tests to workers at run time; run with --workers=1 for a fixed placement${controlled ? '' : '; Level 0 controls not installed in this worker (it set TEST_WORKER_INDEX after the preload)'}\n`);
    }
    if (process.env.DETJS_PLAYWRIGHT_PLACEMENT) {
      try {
        require('node:fs').appendFileSync(process.env.DETJS_PLAYWRIGHT_PLACEMENT, `${JSON.stringify({
          pid: process.pid, worker_index: process.env.TEST_WORKER_INDEX ?? null, parallel_index: parallelIndex ?? null, placement_controlled: false, level0: controlled,
        })}\n`);
      } catch { /* report only */ }
    }
  };
  if (process.env.TEST_WORKER_INDEX !== undefined) report();
  else process.once('exit', report);
}

if (process.env.DETJS === '1' && process.env.TEST_WORKER_INDEX !== undefined) {
  const controls = require('./controls');
  if (controls.installProcess()) {
    controls.installRealm(globalThis, { sameRealm: true });
    controls.openFile(`playwright-worker-${process.env.TEST_PARALLEL_INDEX || process.env.TEST_WORKER_INDEX}`, '');
  }
}

if (process.env.DETJS === '1') {
  if (process.env.TEST_WORKER_INDEX !== undefined) reportPlacement(true);
  else if (PW_WORKER.test(process.argv[1] || '')) reportPlacement(false);
}
