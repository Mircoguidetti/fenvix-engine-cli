'use strict';
// Level 2 for browser tests: the app server side (loaded by boot.js in Node
// processes started under `detjs playwright` that are neither the Playwright
// runner nor its workers: the config's webServer commands, or a server
// started with `detjs serve -- <command>`).
//
// * Level 0 controls of detjs in the server process: seeded Math.random and
//   crypto (OS entropy too: session ids and tokens become reproducible),
//   virtual clock (one wall clock for the whole run, not reset per test: the
//   server's state outlives tests), virtual timers, sorted readdir. The
//   network stays open (servers talk to databases and mail catchers).
// * Test brackets: every HTTP request carrying `x-detjs-test: <id>` (added by
//   the worker to the requests it releases) switches the server to that test:
//   generators reseeded with derive_seed(seed, id), a new fingerprint started.
//   `GET /__detjs/end` (not seen by the app) closes the current test and
//   returns the fingerprints of the tests finished since the last call.
const path = require('node:path');
const http = require('node:http');
const https = require('node:https');
const controls = require('../controls');

const { STATE } = controls;
const FINISHED = {};

function install() {
  // Server settings (inherited by the server's own child processes): one wall clock for the
  // run, OS entropy seeded (session ids, CSRF tokens), network open, no ordering/isolation.
  process.env.DETJS_WALL_RESET = '0';
  if (process.env.DETJS_URANDOM !== '1') process.env.DETJS_URANDOM = process.env.DETJS_PW_SERVER_URANDOM === '0' ? '0' : '1';
  process.env.DETJS_DISABLE = process.env.DETJS_PW_SERVER_DISABLE || 'net,order,isolation';
  const c = controls.cfg();
  if (!c.active) return false;
  if (!controls.installProcess()) return false;
  controls.installRealm(globalThis, { sameRealm: true });
  // One trace part per server process, named after its command line (stable across runs).
  const label = `server:${process.argv.slice(1).map((a) => path.basename(a)).join(' ')}`;
  controls.openFile(label, 'server');
  return true;
}

function endCurrent() {
  if (STATE.testId === null) return;
  const id = STATE.testId;
  STATE.flush();
  const ce = STATE.recorder ? STATE.recorder.currentEvents : 0;
  const events = typeof ce === 'function' ? ce.call(STATE.recorder) : ce;
  const fp = STATE.endTest('passed');
  if (fp) FINISHED[id] = { fingerprint: fp, events };
}

function handleControl(req, res) {
  if (req.url.startsWith('/__detjs/end')) {
    endCurrent();
    const body = JSON.stringify({ pid: process.pid, finished: FINISHED });
    for (const k of Object.keys(FINISHED)) delete FINISHED[k];
    res.writeHead(200, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body) });
    res.end(body);
    return true;
  }
  res.writeHead(404);
  res.end();
  return true;
}

function patchServer(proto) {
  const origEmit = proto.emit;
  proto.emit = function emit(event, req, res) {
    if (event === 'request' && req && req.headers) {
      if (typeof req.url === 'string' && req.url.startsWith('/__detjs/')) return handleControl(req, res);
      const id = req.headers['x-detjs-test'];
      if (id && id !== STATE.testId) {
        endCurrent();
        STATE.beginTest(String(id));
      }
    }
    return origEmit.apply(this, arguments);
  };
}

if (install()) {
  patchServer(http.Server.prototype);
  if (https.Server.prototype.emit !== http.Server.prototype.emit) patchServer(https.Server.prototype);
  process.on('exit', () => {
    try { endCurrent(); controls.closeFile(); } catch { /* ignore */ }
  });
  // Servers usually stop on a signal: close the trace part first.
  for (const sig of ['SIGTERM', 'SIGINT']) {
    process.once(sig, () => {
      try { endCurrent(); controls.closeFile(); } catch { /* ignore */ }
      if (process.listenerCount(sig) === 0) process.kill(process.pid, sig);
    });
  }
}

module.exports = { endCurrent, FINISHED };
