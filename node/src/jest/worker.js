'use strict';
// Preload of Jest's worker processes in a parallel `detjs jest --det` run (`--require`, added by the worker binding in
// src/jest/cli.js). It wraps the test environments (src/jest/environment.js) as the main process does for an in-band
// run: Level 0 is installed before setupFiles run (G-1312), with or without the cache. With the cache on, it first
// starts the capture before Jest's worker loads anything: the worker's capture then sees what the in-band capture
// sees (role `main`: only project code's environment reads count; ctx '' = outside any test file).
const fs = require('node:fs');
const path = require('node:path');

if (process.env.DETJS === '1' && process.env.DETJS_DIR) {
  const root = process.env.DETJS_ROOT || process.cwd();
  const cache = process.env.DETJS_CACHE === '1';
  if (cache) {
    const { CAPTURE } = require('../cache/capture');
    CAPTURE.install({ role: 'main', root, mainAnyReads: false });
    CAPTURE.phase = 'run';
    CAPTURE.setCtx('', '');
    // the Jest runner shell uses this worker's capture (src/jest/runner.js)
    globalThis[Symbol.for('detjs.cache.worker')] = true;
  }
  let shown = null;
  try { shown = JSON.parse(fs.readFileSync(path.join(process.env.DETJS_DIR, 'jest-shown.json'), 'utf8')); } catch { /* none */ }
  // a worker's process.argv is the one plain Jest's workers have: kept (argv: null)
  require('./environment').install(shown, { cache, argv: null });
}
