'use strict';
// Preload of Jest's worker processes in a parallel `detjs jest --det` run (`--require`, added by the worker binding in
// src/jest/cli.js), child processes and worker threads alike. As the main process does for an in-band run, it wraps
// the test environments (src/jest/environment.js: the Level 0 controls are installed when a file's environment is
// built, before its setupFiles run) and, with the cache on, starts the capture before Jest's worker loads anything
// (role `main`: only project code's environment reads count; ctx '' = outside any test file). A worker's
// `process.argv` is its own, as with plain Jest workers.
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
  require('./environment').install(shown, { cache, argv: null });
}
