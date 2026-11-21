'use strict';
// Level 0 in the Playwright Test worker processes of a `detjs playwright --det` run (loaded with NODE_OPTIONS
// --require by src/playwright/cli.js; inactive elsewhere: the runner process and the web servers it starts are not
// Playwright's worker entry script).
//
// The worker installs the process and realm controls before Playwright loads a test file, and brackets every test
// with the worker's own `testBegin` / `testEnd` messages to the runner (they frame the test with its hooks and
// fixtures): reseeded generators, the wall clock reset, one fingerprint per test, one trace part per test file and
// worker process (renamed with the pid when the file closes: Playwright starts a new worker after a failure, and
// the remaining tests of the file then go to a second part, merged in run order by cli.js). The Playwright test id
// maps to the detjs id through `<run dir>/pw-ids.json`, written by the reporter before any worker starts.
// The browser and the web servers are other processes: not controlled (the L2 lane).
const fs = require('node:fs');
const path = require('node:path');

function outcomeOf(status, expected) {
  if (status === 'skipped') return 'skipped';
  if (status === 'interrupted') return 'interrupted';
  return status === expected ? 'passed' : 'failed';
}

function install() {
  // Playwright's own file and pipe work (browser profiles in the temporary directory, the browser connection, traces)
  // goes on in Node-internal callbacks with no frame of the test or of Playwright on the stack (site `<node>`): it is
  // infrastructure here, not an event of the test (found on a Chromium test: its browser profile listing made each
  // replay's fingerprint different). A call the test makes has the test's frame on the stack.
  const sites = require('../sites');
  const resolve = sites.resolve;
  sites.resolve = function resolveInPlaywrightWorker() {
    const site = resolve.apply(this, arguments);
    return site === '<node>' ? null : site;
  };
  const controls = require('./../controls');
  if (!controls.installProcess()) return;
  controls.installRealm(globalThis, { sameRealm: true });
  const { STATE } = controls;
  const dir = process.env.DETJS_DIR;
  let ids = null;
  let file = null;
  let seq = 0;
  const lookup = (testId) => {
    if (ids === null) {
      try { ids = JSON.parse(fs.readFileSync(path.join(dir, 'pw-ids.json'), 'utf8')); } catch { ids = {}; }
    }
    return ids[testId] || null;
  };
  const close = () => {
    if (file === null) return;
    controls.closeFile();
    const from = path.join(dir, 'parts', controls.partName(file, ''));
    try { fs.renameSync(from, from.replace(/\.jsonl$/, `-${process.pid}-${seq++}.jsonl`)); } catch { /* nothing written */ }
    file = null;
  };
  const onMessage = (m) => {
    const ev = m && m.method === '__dispatch__' && m.params && m.params.id === undefined ? m.params : null;
    if (!ev) return;
    if (ev.method === 'testBegin') {
      const t = lookup(ev.params.testId);
      if (!t) return;
      if (file !== t.file) { close(); controls.openFile(t.file, ''); file = t.file; }
      if (STATE.testId !== t.id) STATE.beginTest(t.id);
    } else if (ev.method === 'testEnd') {
      const t = lookup(ev.params.testId);
      if (t && STATE.testId === t.id) STATE.endTest(outcomeOf(ev.params.status, ev.params.expectedStatus));
    } else if (ev.method === 'done') {
      close();
    }
  };
  orderTests(lookup);
  const send = process.send;
  if (typeof send === 'function') {
    process.send = function detjsSend(message, ...rest) {
      try { onMessage(message); } catch (e) { process.stderr.write(`detjs playwright: ${e && e.stack}\n`); }
      return send.call(this, message, ...rest);
    };
  }
  process.on('exit', close);
}

/**
 * The worker loads each test file again and runs its tests in `suite.allTests()` order (declaration order): give
 * them the run order the reporter decided (shuffle, --det-order) when every test of the list has a rank.
 */
function orderTests(lookup) {
  let common;
  try {
    common = require(path.join(path.dirname(path.dirname(process.argv[1])), 'common', 'index.js'));
  } catch { return; }
  const Suite = common && common.test && common.test.Suite;
  if (!Suite || typeof Suite.prototype.allTests !== 'function' || Suite.prototype.allTests.__detjs) return;
  const real = Suite.prototype.allTests;
  const allTests = function allTests() {
    const tests = real.call(this);
    if (tests.length < 2) return tests;
    const ranks = tests.map((t) => { const e = lookup(t.id); return e && typeof e.rank === 'number' ? e.rank : null; });
    if (ranks.some((r) => r === null)) return tests;
    return tests.map((t, i) => [t, ranks[i], i]).sort((a, b) => a[1] - b[1] || a[2] - b[2]).map((x) => x[0]);
  };
  Object.defineProperty(allTests, '__detjs', { value: true });
  Suite.prototype.allTests = allTests;
}

// A worker process is Playwright's worker entry script. Not TEST_WORKER_INDEX: the worker sets it only later, and the
// child processes a test starts inherit it (they stay uncontrolled, as in every shell).
const WORKER = /[\\/]worker[\\/]workerProcessEntry\.js$/.test(process.argv[1] || '');
if ((process.env.DETJS === '1' || process.env.DETJS === 'true') && process.env.DETJS_PLAYWRIGHT === '1' && WORKER) {
  install();
}
