'use strict';
// Preloaded with NODE_OPTIONS=--require by `detjs playwright` and `detjs serve`
// into every Node process of a Level 2 browser run; picks the role:
//   * Playwright Test worker (lib/worker/ entry, or TEST_WORKER_INDEX) -> worker.js
//   * the Playwright runner itself                         -> nothing (reporter.js runs there)
//   * package managers and task launchers                  -> nothing
//   * anything else (the app server and its children)      -> server.js
// DETJS_PW_SERVER=0 leaves app servers uncontrolled.
const path = require('node:path');

const LAUNCHERS = /^(npm|npm-cli|npx|npx-cli|pnpm|pnpm\.c?js|yarn|yarn\.c?js|corepack|cross-env|turbo|nx|concurrently|run-p|run-s|npm-run-all2?|wait-on|start-server-and-test|tsc)(\.js)?$/;

function role() {
  if (process.env.DETJS !== '1') return null;
  // Off-thread module loader hooks (`--import=tsx`, module.register) run in a worker thread that gets the same
  // --require preloads: controls there would start a second coordinator in the same process (with several Playwright
  // workers it took over the worker's place at the hub: MEASURED locally, documenso with 2 workers hung at T=20 ms).
  if (!require('node:worker_threads').isMainThread) return null;
  const main = process.argv[1] || '';
  if (process.env.TEST_WORKER_INDEX !== undefined || /[\\/]playwright[\\/]lib[\\/](worker|common)[\\/]/.test(main)) return 'worker'; // child process entry (1.3x: common/process.js)
  // The runner and its helpers (loader, test server) live in node_modules; an app whose own path
  // contains a "playwright" folder (tests/playwright/server.js) is still a server.
  if (/[\\/]node_modules[\\/](.*[\\/])?(playwright|playwright-core|@playwright[\\/]test)[\\/]/.test(main)) return null;
  if (/[\\/]node_modules[\\/]\.bin[\\/]playwright$/.test(main)) return null; // the runner through its bin link
  const script = path.basename(main);
  if (process.env.DETJS_PW_RUNNER_PID === String(process.pid)) return null;
  if (LAUNCHERS.test(script) || /[\\/](npm|pnpm|yarn|corepack)[\\/]/.test(main)) return null;
  if (/[\\/]node_modules[\\/](.*[\\/])?(tsx|nodemon)[\\/]dist[\\/]cli\.m?js$/.test(main)) return null; // relays to a child Node process
  if (process.env.DETJS_PW_SERVER === '0') return null;
  return 'server';
}

const r = role();
// --det-cache: every Node process of the run records its inputs (inputs.js), the launchers and the runner too
if (process.env.DETJS_PW_INPUTS && process.env.DETJS === '1') {
  try { require('./inputs').install(r || (require('node:worker_threads').isMainThread ? 'runner' : 'thread')); } catch (e) { process.stderr.write(`detjs: input recording failed: ${e.message}\n`); }
}
if (r === 'worker') require('./worker');
else if (r === 'server') require('./server');
