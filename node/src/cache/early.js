'use strict';
// Early start of the cache capture (review r021b G4): loaded with `--require` before any user code of a process.
//
// User code can run in a test process before the runner installs the capture: preload modules (`--require`,
// `--import` in Vitest's `execArgv` or in `NODE_OPTIONS`), and in a Vitest worker the test environment's `setup`
// (a custom `environment` module), which Vitest runs before it creates the test runner. This module is the first
// preload of such processes and starts the capture there:
//
// * phase `preload` (until the process's entry module loads): only preload modules run, every read is theirs;
//   the clock and OS entropy are not controlled yet (Level 0 starts with the runner), so reading them makes every
//   test of the process not cacheable;
// * then (Vitest worker) Vitest's own start-up and the test environment's set-up, recorded as everything later in
//   the worker (every read counts, whoever does it), until the runner's capture (`install`) takes over.
//
// Where it is loaded: in Vitest workers through the projects' `execArgv` (always first among the project's
// preloads), and in every process through `NODE_OPTIONS` when the user's `NODE_OPTIONS` or the command line has
// preloads (bin/detjs.js starts itself again with this module first). In the detjs main process it starts the
// main capture (`role: main`); in any other process (a runner's helper, a child of a test) it does nothing.
const KEY = Symbol.for('detjs.cache.early');
const SELF = __filename;

function role() {
  const path = require('node:path');
  if (process.env.DETJS_EARLY === '1' && require('node:worker_threads').isMainThread && process.argv[1]
    && path.resolve(process.argv[1]) === path.resolve(__dirname, '..', '..', 'bin', 'detjs.js')) return 'main';
  if (process.env.DETJS_CACHE === '1' && process.execArgv.some((a) => a === SELF || a.endsWith(`=${SELF}`))) return 'worker';
  return null;
}

/** Entry modules that end the preload phase. */
const VITEST_ENTRY = /[\\/]vitest[\\/]dist[\\/]workers[\\/]|[\\/]tinypool[\\/]dist[\\/]/;

if (!globalThis[KEY]) {
  globalThis[KEY] = true;
  const r = role();
  if (r) {
    const path = require('node:path');
    const url = require('node:url');
    const { CAPTURE } = require('./capture');
    const root = r === 'main' ? process.cwd() : (process.env.DETJS_ROOT || process.cwd());
    CAPTURE.install({ role: r, root, early: true });
    const mainFile = r === 'main' ? path.resolve(process.argv[1]) : null;
    const isEntry = (file) => (mainFile !== null ? file === mainFile : VITEST_ENTRY.test(file));
    const m = require('node:module');
    const { SYNC_HOOKS, offThreadLoader } = require('./capture');
    if (typeof m.registerHooks === 'function' && !offThreadLoader()) {
      const h = m.registerHooks({
        load(u, context, next) {
          if (CAPTURE.preload && typeof u === 'string' && u.startsWith('file:')) {
            let f = null;
            try { f = url.fileURLToPath(u.split('?')[0]); } catch { /* ignore */ }
            if (f !== null && isEntry(f)) CAPTURE.endPreload('run');
          }
          return next(u, context);
        },
      });
      if (h && typeof h.deregister === 'function') SYNC_HOOKS.push(h);
    } else {
      CAPTURE.endPreload('run');
    }
  }
}
