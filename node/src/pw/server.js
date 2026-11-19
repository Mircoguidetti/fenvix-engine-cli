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

// ------------------------------------------------------------ message scope (round 2)
// Each message the worker releases (an HTTP request carrying `x-detjs-test`, or a WebSocket frame
// announced with /__detjs/frame) is handled in its own async context (AsyncLocalStorage). Inside it:
//   * clock values = the message's logical instant (epoch + n x STEP, n = messages received by this
//     server so far) + reads at the same call site x tick: a background job reading the clock no
//     longer shifts the values a request sees (round 2 diagnosis, source S1);
//   * random values from a stream per (test, message index, call site, kind);
//   * events go into the message's own list; the test's server fingerprint is the digest of its
//     messages in order, each message digested as the sorted list of its events (order between
//     concurrent chains of one message is not fingerprinted: values no longer depend on it).
// Events outside every message context (timers of earlier work, pool reapers, heartbeats, file
// watchers) are background: counted, not fingerprinted (source S2). Their effects on later
// responses and frames remain visible in the browser side of the fingerprint.
// DETJS_PW_SCOPE=0 restores round 1 (one counter, every event in the fingerprint).
const { AsyncLocalStorage } = require('node:async_hooks');
const net = require('node:net');
const native = require('../native');
const sites = require('../sites');
const seedsMod = require('../seeds');
const clockMod = require('../clock');

const SCOPE = process.env.DETJS_PW_SCOPE !== '0';
const STEP_NS = Number(process.env.DETJS_PW_SERVER_STEP_MS || 100) * 1e6;
const TICK_NS = Number(process.env.DETJS_TICK || 1000);
const MSG = new AsyncLocalStorage();
// Lockstep (round 4): the engine clock T (ns since the run's epoch) as last told by the coordinator.
const LOCKSTEP = process.env.DETJS_PW_LOCKSTEP !== '0';
const LSS = { t: 0, attached: false, msgs: new Map() }; // msgs: engine message id -> message scope
const baseNs = () => (LSS.attached ? LSS.t : SCOPED.n * STEP_NS);
/** Engine time of the current message (stamped by the engine at delivery), else T. */
const nowNs = () => { const st = MSG.getStore(); return st && st.t !== undefined ? st.t : LSS.t; };
const SCOPED = { n: 0, perTest: new Map(), messages: new Map(), bg: { counts: new Map(), gens: new Map(), n: -1, events: 0 }, pendingFrame: null };

function newMessage(test, kind) {
  SCOPED.n += 1;
  const idx = (SCOPED.perTest.get(test) || 0) + 1;
  SCOPED.perTest.set(test, idx);
  const st = { test, idx, kind, base: baseNs(), counts: new Map(), gens: new Map(), events: [] };
  let list = SCOPED.messages.get(test);
  if (!list) SCOPED.messages.set(test, (list = []));
  list.push(st);
  return st;
}

function siteNow() {
  return STATE.quiet(() => sites.resolve());
}

function bgStore() {
  const bg = SCOPED.bg;
  const epochKey = LSS.attached ? `t${LSS.t}` : SCOPED.n;
  if (bg.n !== epochKey) { bg.n = epochKey; bg.counts.clear(); bg.gens.clear(); bg.reads = 0; bg.readsN = epochKey; }
  bg.base = baseNs();
  return bg;
}

const DIAG_BG = !!process.env.DETJS_PW_DIAG_DIR;
function valueHook(op) {
  const msg = MSG.getStore();
  if (!msg) {
    // Background: not fingerprinted, so no call-site resolution (its cost kept busy servers busy).
    const bg = bgStore();
    bg.reads = (bg.n === bg.readsN ? bg.reads : 0) + 1;
    bg.readsN = bg.n;
    return { e: bg.base + bg.reads * TICK_NS, rel: String(bg.reads * TICK_NS) };
  }
  const site = siteNow();
  if (site === null) return null; // infrastructure: default path (real values)
  const st = msg;
  const k = `${site}\0${op === 'Date.now' || op === 'Date' ? 'wall' : 'mono'}`;
  const c = (st.counts.get(k) || 0) + 1;
  st.counts.set(k, c);
  return { e: st.base + c * TICK_NS, rel: String(c * TICK_NS) };
}

function streamHook(kind) {
  const msg = MSG.getStore();
  const st = msg || bgStore();
  const k = msg ? `${siteNow()}\0${kind}` : `<bg>\0${kind}`;
  let g = st.gens.get(k);
  if (!g) {
    g = new seedsMod.Xoshiro128();
    const key = st === SCOPED.bg ? `<bg>\0${st.n}\0${k}` : `${st.test}\0${st.idx}\0${k}`;
    const [hi, lo] = native.deriveSeedWords(STATE.config.seed, key);
    g.seed(hi, lo);
    st.gens.set(k, g);
  }
  return g;
}

const FS_ = '\u001f';
function installScope() {
  clockMod.setValueHook(valueHook);
  clockMod.setTimerContextHook(() => MSG.getStore() || null);
  seedsMod.setStreamHook(streamHook);
  // Every recorded event also goes to the message it belongs to (or counts as background).
  const origRecord = STATE.record.bind(STATE);
  STATE.record = function record(source, op, value) {
    const st = MSG.getStore();
    if (!st || st.done) {
      SCOPED.bg.events++;
      return DIAG_BG ? origRecord(source, op, value) : undefined; // raw background events only when diagnosing
    }
    if (this.quietDepth > 0) return undefined;
    let site = '';
    if (this.config.sites) {
      site = siteNow();
      if (site === null) return undefined;
    }
    st.events.push(source + FS_ + op + FS_ + site + FS_ + value);
    if (this.testId !== null && this.recorder !== null) {
      if (this.onOtherEvent && source !== 'time') this.onOtherEvent();
      this.buffer.push(source + FS_ + op + FS_ + site + FS_ + value);
      if (this.buffer.length >= 256) this.flush();
    }
    return undefined;
  };
  const origAt = STATE.recordAt.bind(STATE);
  STATE.recordAt = function recordAt(source, op, site, value) {
    const st = MSG.getStore();
    if (st && !st.done) st.events.push(source + FS_ + op + FS_ + site + FS_ + value);
    else { SCOPED.bg.events++; if (!DIAG_BG) return undefined; }
    return origAt(source, op, site, value);
  };
  // WebSocket frames: the worker announces the next frame (/__detjs/frame); the next data chunk
  // read from an upgraded socket is handled in that message's context.
  const origSockEmit = net.Socket.prototype.emit;
  net.Socket.prototype.emit = function emit(event, ...args) {
    if (event === 'data' && this.__detjsWs && SCOPED.pendingFrame) {
      const st = SCOPED.pendingFrame;
      SCOPED.pendingFrame = null;
      return MSG.run(st, () => origSockEmit.call(this, event, ...args));
    }
    return origSockEmit.call(this, event, ...args);
  };
}

/** Scoped fingerprint of one test: its messages in arrival order, each the digest of its sorted events. */
function scopedFingerprint(test) {
  const list = SCOPED.messages.get(test) || [];
  SCOPED.messages.delete(test);
  const diagDir = process.env.DETJS_PW_DIAG_DIR;
  const parts = list.map((m) => {
    const ev = m.events.slice().sort();
    if (diagDir) {
      try {
        const fs = require('node:fs');
        fs.mkdirSync(diagDir, { recursive: true });
        const name = `${test}`.replace(/[^A-Za-z0-9._-]+/g, '_').slice(-170);
        fs.appendFileSync(path.join(diagDir, `${name}.server.jsonl`), `${JSON.stringify({ t: 0, op: 'server.msg', target: `${m.idx} ${m.kind}`, text: ev.join('\n') })}\n`);
      } catch { /* diagnosis never breaks a run */ }
    }
    return `${m.idx}:${m.kind}:${ev.length}:${native.digest(Buffer.from(ev.join('\u001e')))}`;
  });
  return { fingerprint: native.digest(Buffer.from(parts.join('\n'))), messages: parts.length, events: list.reduce((a, m) => a + m.events.length, 0) };
}

function install() {
  // Server settings (inherited by the server's own child processes): one wall clock for the
  // run, OS entropy seeded (session ids, CSRF tokens), network open, no ordering/isolation.
  process.env.DETJS_WALL_RESET = '0';
  process.env.DETJS_NODE_INFRA = '1';
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
  if (SCOPE) {
    const sc = scopedFingerprint(id);
    FINISHED[id] = { fingerprint: sc.fingerprint, events: sc.events, messages: sc.messages, raw: fp, raw_events: events, background: SCOPED.bg.events };
  } else if (fp) FINISHED[id] = { fingerprint: fp, events };
}

// Quiet barrier: the worker asks before releasing the next message, so that the
// server finishes the work of the previous one first (database writes, socket
// pushes). Quiet = no HTTP request in flight and the event loop idle (utilization
// under 10%) for `ms` consecutive real milliseconds; gives up after `max` ms.
let inflight = 0;
const { performance } = require('node:perf_hooks');
const { REAL } = require('../clock');
const REAL_SET_TIMEOUT = REAL.setTimeout;
const realNow = () => REAL.perfNow(); // the server's own performance.now is virtual

function waitQuiet(ms, max, done) {
  const start = realNow();
  let idleSince = null;
  let prev = performance.eventLoopUtilization();
  const step = () => {
    const now = realNow();
    const cur = performance.eventLoopUtilization();
    const d = performance.eventLoopUtilization(cur, prev);
    prev = cur;
    // A one-shot timer created while handling a message is part of that message's work (a push sent
    // a few ms after the response): not quiet until it fired (round 2).
    const pendingWork = SCOPE && clockMod.DRIVER.queue.some((t) => t._ctx && !t._repeat && t._realDeadline - REAL.perfNow() < max);
    const idle = inflight === 0 && d.utilization < 0.1 && !pendingWork;
    if (!idle) idleSince = null; else if (idleSince === null) idleSince = now;
    if (idleSince !== null && now - idleSince >= ms) return done(true, now - start);
    if (now - start >= max) return done(false, now - start);
    REAL_SET_TIMEOUT(step, 2);
  };
  REAL_SET_TIMEOUT(step, 2);
}

// ------------------------------------------------------------------ lockstep control
// GET /__detjs/ls/settle?t=T&w=MS&max=MS: the engine clock is now T. The first call attaches the server to the
// engine (pending timers restart at T). Fires every virtual timer due by T (in order), then waits until the
// process is quiet: event loop idle for w ms, no released message in progress unless it is blocked on a virtual
// timer of its own, no timer due. Reports the next deadline and whether a message waits on time.
function lsQuiet(w, max, done) {
  const start = realNow();
  let idleSince = null;
  let prev = performance.eventLoopUtilization();
  const step = () => {
    const now = realNow();
    const cur = performance.eventLoopUtilization();
    const d = performance.eventLoopUtilization(cur, prev);
    prev = cur;
    const blocked = [...LSS.msgs.values()].every((st) => clockMod.DRIVER.queue.some((t) => t._ctx === st));
    const due = clockMod.DRIVER.queue.length > 0 && clockMod.DRIVER.queue[0]._due <= LSS.t;
    const idle = d.utilization < 0.1 && blocked && !due;
    if (process.env.DETJS_LS_QDEBUG) process.stderr.write(`q u=${d.utilization.toFixed(3)} b=${blocked} due=${due} dt=${(now - start).toFixed(1)}\n`);
    if (!idle) idleSince = null; else if (idleSince === null) idleSince = now;
    if (idleSince !== null && now - idleSince >= w) return done(true);
    if (now - start >= max) return done(false);
    REAL_SET_TIMEOUT(step, 2);
  };
  REAL_SET_TIMEOUT(step, 2);
}

const DB_CLOCK_FILE = process.env.DETJS_LS_DB_CLOCK_FILE || '';
const EPOCH_MS_SRV = Date.parse(process.env.DETJS_EPOCH || '2025-01-01T00:00:00Z');
function writeDbClock() {
  // libfaketime (FAKETIME_TIMESTAMP_FILE, FAKETIME_NO_CACHE=1) reads this file: the database clock is T, frozen
  // between steps, at one-second resolution.
  if (!DB_CLOCK_FILE) return;
  try {
    const d = new (clockMod.REAL.Date)(EPOCH_MS_SRV + LSS.t / 1e6);
    const iso = d.toISOString();
    require('node:fs').writeFileSync(DB_CLOCK_FILE, `${iso.slice(0, 10)} ${iso.slice(11, 19)}\n`);
  } catch { /* best effort */ }
}

let lsBusy = Promise.resolve();
function handleLockstep(req, res) {
  const u = new URL(req.url, 'http://x');
  const reply = (obj) => {
    const body = JSON.stringify(obj);
    // A server that is closing (server.close() waits for busy connections) must not be kept open by the engine's
    // control connection (found on uptime-kuma: its setup server closes, then the main server starts).
    const closing = req.socket && req.socket.server && req.socket.server.listening === false;
    res.writeHead(200, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body), ...(closing ? { connection: 'close' } : {}) });
    res.end(body);
  };
  if (!LOCKSTEP || !SCOPE) return reply({ lockstep: false });
  const t = Number(u.searchParams.get('t') || 0);
  const w = Number(u.searchParams.get('w') || 15);
  const max = Number(u.searchParams.get('max') || 5000);
  if (process.env.DETJS_LS_QDEBUG) process.stderr.write(`ls call ${req.url}\n`);
  lsBusy = lsBusy.then(async () => {
    if (!LSS.attached) {
      LSS.t = t;
      LSS.attached = true;
      clockMod.DRIVER.attachAt(t);
    }
    if (t > LSS.t) LSS.t = t;
    clockMod.CLOCK.advanceTo(LSS.t);
    writeDbClock();
    const fired = await clockMod.DRIVER.fireDue(LSS.t);
    const quiet = await new Promise((r) => lsQuiet(w, max, r));
    const next = clockMod.DRIVER.nextDue();
    const blockedIds = [...LSS.msgs].filter(([, st]) => clockMod.DRIVER.queue.some((x) => x._ctx === st)).map(([id]) => id);
    reply({ lockstep: true, fired, busy: !quiet, next, waiting: LSS.msgs.size > 0, blocked: blockedIds, t: LSS.t });
  }).catch((e) => reply({ lockstep: true, error: String(e && e.message) }));
  return true;
}

function handleControl(req, res) {
  if (req.url.startsWith('/__detjs/ls/')) return handleLockstep(req, res);
  if (req.url.startsWith('/__detjs/quiet')) {
    const u = new URL(req.url, 'http://x');
    const ms = Number(u.searchParams.get('ms') || 20);
    const max = Number(u.searchParams.get('max') || 3000);
    waitQuiet(ms, max, (quiet, waited) => {
      const body = JSON.stringify({ quiet, waited: Math.round(waited) });
      res.writeHead(200, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body) });
      res.end(body);
    });
    return true;
  }
  if (req.url.startsWith('/__detjs/frame')) {
    // The next WebSocket frame the worker sends belongs to this test.
    const u = new URL(req.url, 'http://x');
    const test = u.searchParams.get('test');
    if (SCOPE && test) {
      if (test !== STATE.testId) { endCurrent(); STATE.beginTest(String(test)); }
      SCOPED.pendingFrame = newMessage(test, 'ws');
    }
    res.writeHead(204);
    res.end();
    return true;
  }
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
      inflight++;
      let counted = true;
      const dec = () => { if (counted) { counted = false; inflight--; } };
      if (res && typeof res.once === 'function') { res.once('finish', dec); res.once('close', dec); }
      const id = req.headers['x-detjs-test'];
      if (id && id !== STATE.testId) {
        endCurrent();
        STATE.beginTest(String(id));
      }
      if (SCOPE && id) {
        const msgT = req.headers['x-detjs-t'];
        if (LSS.attached && msgT !== undefined && Number(msgT) > LSS.t) LSS.t = Number(msgT);
        const st = newMessage(String(id), 'http');
        if (LSS.attached && msgT !== undefined) { st.t = Number(msgT); st.base = st.t; }
        // Lockstep: what a message's handler does after its response was sent (a server.close() callback that
        // waits for other connections to end, a log line of a background tail) happens at a moment set by real
        // socket lifetimes: it is not part of the message's fingerprint.
        if (LSS.attached && res && typeof res.once === 'function') { const end = () => { st.done = true; }; res.once('finish', end); res.once('close', end); }
        const mid = req.headers['x-detjs-msg'];
        if (LSS.attached && mid && res && typeof res.once === 'function') {
          // A message released by the engine: in progress until its response is sent.
          LSS.msgs.set(String(mid), st);
          const fin = () => LSS.msgs.delete(String(mid));
          res.once('finish', fin); res.once('close', fin);
        }
        const args = arguments;
        return MSG.run(st, () => origEmit.apply(this, args));
      }
    }
    if (event === 'upgrade' && req && req.socket) req.socket.__detjsWs = true;
    return origEmit.apply(this, arguments);
  };
}

if (install()) {
  if (SCOPE) installScope();
  if (LOCKSTEP && SCOPE) {
    clockMod.setLockstep({ on: true, now: nowNs, runIn: (ctx, fn) => MSG.run(ctx, fn) });
    // Park: once the server listens (plus DETJS_LS_PARK_MS), its timers stop firing in real time and wait for the
    // engine; a timer that fired between start-up and the first test would make the first response depend on
    // how long the runner took to start (found on the lockstep fixture: a 100 ms background counter).
    if (process.env.DETJS_LS_PARK !== 'never') {
      const parkMs = Number(process.env.DETJS_LS_PARK_MS || 0);
      const origListen = net.Server.prototype.listen;
      net.Server.prototype.listen = function listen(...a) {
        this.once('listening', () => {
          const park = () => { if (!LSS.attached && !clockMod.LOCK.parked) { clockMod.setLockstep({ parked: true }); clockMod.DRIVER.rearm(); } };
          if (parkMs > 0) REAL_SET_TIMEOUT(park, parkMs); else park();
        });
        return origListen.apply(this, a);
      };
    }
  }
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
