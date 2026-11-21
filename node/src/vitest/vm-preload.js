'use strict';
// Worker preload of Vitest's vm pools (vmThreads, vmForks) under --det (audit G-0461; added by src/vitest/cli.js).
//
// In these pools every test file runs in its own vm context, which imports Node's built-in modules through Vitest's
// own synthetic modules: their named exports (`import { setTimeout } from 'node:timers'`) are copied when the context
// first imports the module, which Vitest's entry does before the test runner (where detjs installs) is loaded. The
// process-wide controls are therefore installed here, in the worker, before any context exists; the runner then
// installs the realm controls into each file's context (src/vitest/runner.mjs, makeRunner's realm).
if (process.env.DETJS === '1') {
  require('../controls').installProcess();
}
