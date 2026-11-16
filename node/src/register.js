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
if (process.env.DETJS === '1' && process.env.TEST_WORKER_INDEX !== undefined) {
  const controls = require('./controls');
  if (controls.installProcess()) {
    controls.installRealm(globalThis, { sameRealm: true });
    controls.openFile(`playwright-worker-${process.env.TEST_PARALLEL_INDEX || process.env.TEST_WORKER_INDEX}`, '');
  }
}
