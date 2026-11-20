'use strict';
// The environment as test code sees it under --det (audit G-2162).
//
// detjs passes its settings to every worker thread and child process through `DETJS_*` variables (and the shared
// cache's `FENVIX_CACHE_*`). Test code must not see them: `Object.keys(process.env)`, an environment snapshot or a
// `process.env.DETJS` check would differ from a plain run. The recording `process.env` object (src/cache/capture.js
// installEnv, used by Level 0 with or without the cache) asks `hidden()` / `visibleKeys()` here: a detjs variable is
// hidden when the code reading it is test code, that is when the first stack frame outside Node's internals is neither
// detjs nor the test runner; it stays visible to detjs and the runners, and to Node's own child_process and
// worker_threads code, so processes and workers inherit it as before. Jest's per-file copy of the environment is
// covered the same way (it is wrapped by the same object).
const { STATE } = require('./state');
const sites = require('./sites');

const OWN = /^(?:DETJS(?:$|_)|FENVIX_CACHE_)/;
const INHERIT = /^(?:node:)?(?:internal\/)?(?:child_process|worker_threads|internal\/worker|worker)(?:\/|$)/;
const structured = (_e, cs) => cs;
const CAPTURE_FILE = require('node:path').join(__dirname, 'cache', 'capture.js');

/** Whether the code reading the environment now is test code (see above). */
function testReader() {
  if (STATE.quietDepth > 0) return false;
  const E = Error;
  const prevPrepare = E.prepareStackTrace;
  const prevLimit = E.stackTraceLimit;
  E.prepareStackTrace = structured;
  E.stackTraceLimit = 40;
  const holder = {};
  try {
    E.captureStackTrace(holder, testReader);
    // eslint-disable-next-line no-unused-expressions
    holder.stack;
  } finally {
    E.prepareStackTrace = prevPrepare;
    E.stackTraceLimit = prevLimit;
  }
  const frames = holder.stack;
  if (!Array.isArray(frames)) return false;
  let trap = true; // the recording environment object's own frames come first
  for (const cs of frames) {
    let f = cs.getFileName() || '';
    if (f.startsWith('file://')) { try { f = require('node:url').fileURLToPath(f); } catch { /* keep */ } }
    if (trap && (f === __filename || f === CAPTURE_FILE)) continue;
    trap = false;
    if (INHERIT.test(f)) return false; // a process or worker being started inherits the environment
    if (!f || f.startsWith('node:') || f.startsWith('internal/') || !f.includes('/')) continue;
    if (f.startsWith(sites.SHELL_DIR)) return false; // detjs itself
    return !sites.INFRA.test(f); // the runner's own code sees it; the first other frame is test code
  }
  return false;
}

/** A detjs variable read by test code: answered as absent. */
function hidden(k) {
  return typeof k === 'string' && OWN.test(k) && testReader();
}

/** The keys of an enumeration of the environment, without detjs' own when test code enumerates it. */
function visibleKeys(keys) {
  if (!keys.some((k) => typeof k === 'string' && OWN.test(k))) return keys;
  return testReader() ? keys.filter((k) => typeof k !== 'string' || !OWN.test(k)) : keys;
}

/** The environment object for display (util.inspect of process.env) without detjs' variables, for test code. */
function view(real) {
  if (!Object.keys(real).some((k) => OWN.test(k)) || !testReader()) return real;
  const out = {};
  for (const k of Object.keys(real)) if (!OWN.test(k)) out[k] = real[k];
  return out;
}

function install() {
  STATE.envView = { hidden, visibleKeys, view };
}

module.exports = { install, hidden, visibleKeys, view, OWN };
