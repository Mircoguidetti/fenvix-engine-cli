'use strict';
// Preload of Jest's worker processes in a parallel `detjs jest --det` run (`--require`, added by the worker binding in
// src/jest/cli.js). With the cache on, it starts the capture before Jest's worker loads anything and wraps the test
// environments, as the main process does for an in-band run: the worker's capture then sees what the in-band
// capture sees (role `main`: only project code's environment reads count; ctx '' = outside any test file).
const fs = require('node:fs');
const path = require('node:path');

if (process.env.DETJS === '1' && process.env.DETJS_DIR && process.env.DETJS_CACHE === '1') {
  const root = process.env.DETJS_ROOT || process.cwd();
  const { CAPTURE } = require('../cache/capture');
  CAPTURE.install({ role: 'main', root, mainAnyReads: false });
  CAPTURE.phase = 'run';
  CAPTURE.setCtx('', '');
  let shown = null;
  try { shown = JSON.parse(fs.readFileSync(path.join(process.env.DETJS_DIR, 'jest-shown.json'), 'utf8')); } catch { /* none */ }
  require('./cli').wrapEnvironments(shown, root);
  // the Jest runner shell uses this worker's capture (src/jest/runner.js)
  globalThis[Symbol.for('detjs.cache.worker')] = true;
}
