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
  const main = process.argv[1] || '';
  if (process.env.TEST_WORKER_INDEX !== undefined || /[\\/]playwright[\\/]lib[\\/]worker[\\/]/.test(main)) return 'worker';
  if (/[\\/](playwright|playwright-core|@playwright[\\/]test)[\\/]/.test(main)) return null; // runner helpers (loader, test server)
  const script = path.basename(main);
  const args = process.argv.slice(1).join(' ');
  if (/playwright/.test(args) && /\b(cli\.js|playwright)\b/.test(args) && /\btest\b/.test(args)) return null; // the runner
  if (process.env.DETJS_PW_RUNNER_PID === String(process.pid)) return null;
  if (LAUNCHERS.test(script) || /[\\/](npm|pnpm|yarn|corepack)[\\/]/.test(process.argv[1] || '')) return null;
  if (process.env.DETJS_PW_SERVER === '0') return null;
  return 'server';
}

const r = role();
if (r === 'worker') require('./worker');
else if (r === 'server') require('./server');
