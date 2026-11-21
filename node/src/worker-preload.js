'use strict';
// Level 0 inside a worker thread started by a test (src/children.js adds `--require` of this file to the worker's
// execArgv). The worker gets the process-wide and realm controls; its randomness and clock start from a key derived
// from the parent test id and the worker's index in that test (DETJS_WORKER_KEY), as if the worker were a test of
// its own. Nothing is written to the trace from the worker (the parent records the worker's messages and exit).
if (process.env.DETJS === '1') {
  const controls = require('./controls');
  const c = controls.cfg();
  c.dir = null; // no trace part of its own
  if (controls.installProcess()) {
    controls.installRealm(globalThis, { sameRealm: true });
    controls.openFile(`<worker>${process.env.DETJS_WORKER_KEY || ''}`, '');
    controls.STATE.beginTest(process.env.DETJS_WORKER_KEY || '<worker>');
  }
}
