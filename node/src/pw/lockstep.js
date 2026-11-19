'use strict';
// Lockstep (round 4): the Playwright runner, the browser pages and the app server processes advance on ONE
// engine clock and ONE event order. The decisions are taken by the Rust scheduler (crates/detpy-core/src/
// lockstep.rs, through native.Lockstep); this module is the shell around it in a test worker process:
//
//   loop, while a test runs:
//     settle    wait until every component is quiet: every page's virtual-time budget has expired, every request
//               a page started has reached the queue, every app server is idle (or blocked on its own virtual
//               timers), and the worker process saw no socket, protocol or timer activity for a quiet window;
//     act       the scheduler's next action:
//               * release one pending message (page request, runner API request, WebSocket frame either way),
//                 chosen from the pending set by key order (seeded with --det-seed), with its latency and fault;
//               * fire the virtual timers due now (runner, servers) and the held messages due now;
//               * advance T to the next deadline (at most one quantum) and give the pages that much virtual time.
//
// Nothing moves in real time inside a test: the runner's timers and clocks are virtual (runner-clock.js), pages
// get CDP virtual time only in `advance`, servers fire timers only when told (server.js /__detjs/ls), and time
// advances only while the runner waits on the engine (a Playwright call in flight, or a sleep in test code).
// Real time is used only to *detect* quiet, never to order: a decision is taken only when nothing can change the
// pending set any more.
const http = require('node:http');
const net = require('node:net');
const fs = require('node:fs');
const path = require('node:path');
const native = require('../native');
const { RunnerClock, REAL } = require('./runner-clock');

const ENV = process.env;
const NS = 1e6; // ns per ms
const realNow = () => REAL.perfNow();
const realSleep = (ms) => new Promise((r) => REAL.setTimeout(r, ms));
const immediate = () => new Promise((r) => REAL.setImmediate(r));

// ------------------------------------------------------------------ activity
// Anything that can still change the pending set: socket traffic (the browser's CDP pipe, HTTP to the app
// servers, WebSocket relays), Playwright protocol calls, virtual timers created or cleared, route events.
// The coordinator's own control traffic is marked and not counted.
const ACT = { n: 0, routes: 0, ownDepth: 0 };
function activity() { if (ACT.ownDepth === 0) ACT.n++; }
const CTL_AGENT = new http.Agent({ keepAlive: true, maxSockets: 4 });
CTL_AGENT.on('free', (s) => { s.__detjsCtl = true; });
// ------------------------------------------------------------------ CDP commands in flight
// The browser's DevTools pipe (Playwright launches Chromium with --remote-debugging-pipe) carries NUL-separated
// JSON messages. A command the runner sent and Chromium has not answered means the browser is still working
// (the runner is busy, time must not advance), except commands that await a promise in the page (Playwright's
// in-page waits: element stable, waitForFunction): those wait on page time.
const CDP = { out: new Map(), own: new Set(), lastChange: 0 };
function cdpWrite(sock, chunk) {
  if (typeof chunk !== 'string' || chunk.length < 8 || chunk.charCodeAt(0) !== 123 /* { */) return;
  const m = /^\{"id":(\d+),"method":"([^"]+)"/.exec(chunk);
  if (!m) return;
  sock.__detjsCdp = true;
  const id = Number(m[1]);
  CDP.out.set(id, { method: m[2], wait: chunk.includes('"awaitPromise":true'), own: ACT.ownDepth > 0, t: realNow() });
  CDP.lastChange = realNow();
}
function cdpRead(sock, buf) {
  if (!Buffer.isBuffer(buf)) return;
  // A message starts at the beginning of the stream or after a NUL; responses start with {"id":N,
  let start = sock.__detjsCarry ? -1 : 0;
  if (sock.__detjsCarry) { buf = Buffer.concat([sock.__detjsCarry, buf]); sock.__detjsCarry = null; start = 0; }
  if (sock.__detjsMid) {
    const z = buf.indexOf(0);
    if (z < 0) return;
    start = z + 1;
    sock.__detjsMid = false;
  }
  while (start < buf.length) {
    if (buf.length - start < 24 && buf.indexOf(0, start) < 0) { sock.__detjsCarry = buf.subarray(start); return; }
    if (buf[start] === 123 && buf[start + 1] === 34 && buf[start + 2] === 105 && buf[start + 3] === 100) { // {"id
      const head = buf.toString('latin1', start, Math.min(buf.length, start + 24));
      const m = /^\{"id":(\d+)/.exec(head);
      if (m) { CDP.out.delete(Number(m[1])); CDP.lastChange = realNow(); sock.__detjsCdp = true; }
    }
    const z = buf.indexOf(0, start);
    if (z < 0) { sock.__detjsMid = true; return; }
    start = z + 1;
  }
}
// Commands that complete only after an animation frame (frames come from the engine): waits on time.
// Navigations wait for their document request, which the engine releases: waits too.
const FRAME_METHODS = /^(Page\.captureScreenshot|Page\.startScreencast|Page\.screencastFrameAck|Page\.printToPDF|Page\.navigate|Page\.reload|Page\.navigateToHistoryEntry)$/;
function cdpState() {
  let busy = 0;
  let wait = 0;
  let oldest = Infinity;
  const methods = [];
  for (const c of CDP.out.values()) {
    if (c.own) continue;
    if (c.wait || FRAME_METHODS.test(c.method)) wait++;
    else { busy++; oldest = Math.min(oldest, c.t); methods.push(c.method); }
  }
  return { busy, wait, oldest, methods };
}

let activityInstalled = false;
function installActivity() {
  if (activityInstalled) return;
  activityInstalled = true;
  const proto = net.Socket.prototype;
  const origWrite = proto.write;
  proto.write = function write(chunk, ...a) {
    if (!this.__detjsCtl) {
      activity();
      if (this.__detjsCdp !== false) cdpWrite(this, chunk);
    }
    return origWrite.call(this, chunk, ...a);
  };
  const origEmit = proto.emit;
  proto.emit = function emit(ev, ...a) {
    if (!this.__detjsCtl && (ev === 'data' || ev === 'end' || ev === 'close' || ev === 'connect' || ev === 'error')) {
      activity();
      if (ev === 'data' && (this.__detjsCdp || this.__detjsCdpRead !== false)) {
        // Only pipes (no remote address) can be the DevTools pipe.
        if (this.__detjsCdpRead === undefined) this.__detjsCdpRead = !this.remoteAddress;
        if (this.__detjsCdpRead) cdpRead(this, a[0]);
      }
    }
    return origEmit.call(this, ev, ...a);
  };
  process.on('message', activity);
}

// Requests of the pages that are not ordered (scripts, styles, images, fonts) but are still loading: the page's
// state depends on them, so time does not advance while one is in flight.
const NETFLIGHT = { n: 0, since: 0 };
function netStart() { if (NETFLIGHT.n++ === 0) NETFLIGHT.since = realNow(); activity(); }
function netEnd() { NETFLIGHT.n = Math.max(0, NETFLIGHT.n - 1); activity(); if (LS) LS.poke(); }

// Playwright calls that are real work in other processes (starting or connecting a browser): never a wait.
const REALWORK = /^(BrowserType\.(launch|launchPersistentContext|connect|connectOverCDP)|Browser\.close|Android|Electron)/;

// ------------------------------------------------- Playwright protocol calls in flight
// Calls the runner makes (click, expect, goto, fetch, waitForTimeout ...). While one is in flight the runner
// waits on the browser or the network: time may advance. The engine's own calls (CDP sessions, route
// continuations, tracing) are not waits.
const OWN_TYPES = new Set(['CDPSession', 'Route', 'WebSocketRoute', 'Tracing', 'Artifact', 'Stream', 'LocalUtils', 'JsonPipe']);
// Calls on browser objects (actions, evaluations, navigations): admitted at quiet points (see dispatch).
const GATED_TYPES = new Set(['Frame', 'Page', 'ElementHandle', 'JSHandle', 'Worker', 'Dialog', 'BrowserContext']);
// Calls the engine makes itself (route.fetch of a page request, its body, CDP sessions): marked by async context.
const { AsyncLocalStorage } = require('node:async_hooks');
const OWN = new AsyncLocalStorage();
const CALLS = { inflight: 0, byMethod: new Map(), patched: new WeakSet(), waits: new Set(), gated: new Map() };
function patchDispatcher(DC) {
  if (!DC || !DC.prototype || CALLS.patched.has(DC.prototype)) return false;
  CALLS.patched.add(DC.prototype);
  const orig = DC.prototype.dispatch;
  DC.prototype.dispatch = async function dispatch(message) {
    let type = '';
    try { const d = this._dispatcherByGuid.get(message.guid); type = d ? d._type : ''; } catch { /* ignore */ }
    if (message.method === '__waitInfo__') {
      // Client-side waits (waitForURL, waitForEvent, waitForResponse, waitForLoadState ...): the runner waits for
      // the page, without a call in flight and often without a deadline (navigation timeout 0).
      const info = message.params || {};
      if (info.phase === 'before') CALLS.waits.add(info.waitId);
      else if (info.phase === 'after') CALLS.waits.delete(info.waitId);
      activity();
      if (LS) LS.poke();
    }
    const mine = OWN_TYPES.has(type) || message.method === '__waitInfo__' || message.method === '__abort__' || OWN.getStore() === true;
    if (mine) return orig.call(this, message);
    const k = `${type}.${message.method}`;
    if (REALWORK.test(k)) CALLS.realwork = (CALLS.realwork || 0) + 1;
    // Admission (round 4): a call on a browser object runs only at a quiet point, ACTION ms of engine time after
    // the runner asked for it. The runner reacts to browser events in real time (a navigation event resolves
    // waitForURL in the middle of a page's time budget); its next action must not reach the browser at a real-time
    // dependent moment of that budget.
    let navMark = null;
    if (LS && LS.gating && GATED_TYPES.has(type) && !REALWORK.test(k) && LS.o.currentTest() !== null) {
      await LS.admit(message.id);
      // A navigation the runner starts must reach the queue (its document request) before the next decision.
      if (/^(goto|reload|goBack|goForward)$/.test(message.method)) { navMark = { open: true }; LS.navPending.push(navMark); }
    }
    CALLS.inflight++;
    CALLS.byMethod.set(k, (CALLS.byMethod.get(k) || 0) + 1);
    activity();
    try {
      return await orig.call(this, message);
    } finally {
      if (navMark && navMark.open) { navMark.open = false; const i = LS.navPending.indexOf(navMark); if (i >= 0) LS.navPending.splice(i, 1); }
      if (REALWORK.test(k)) CALLS.realwork--;
      CALLS.inflight--;
      const c = CALLS.byMethod.get(k) - 1;
      if (c) CALLS.byMethod.set(k, c); else CALLS.byMethod.delete(k);
      activity();
      LS && LS.poke();
    }
  };
  return true;
}
/** Module loader hook (worker.js): find DispatcherConnection in whichever playwright-core the project uses. */
function onModuleLoaded(exp) {
  if (!exp || typeof exp !== 'object') return;
  try {
    if (exp.DispatcherConnection) patchDispatcher(exp.DispatcherConnection);
    else if (exp.server && exp.server.DispatcherConnection) patchDispatcher(exp.server.DispatcherConnection);
  } catch { /* never break loading */ }
}

// ------------------------------------------------------------------ coordinator
let LS = null;

class Coordinator {
  /**
   * @param {object} o
   * @param {bigint} o.seed
   * @param {boolean} o.seeded
   * @param {number} o.epochMs
   * @param {() => (string|null)} o.currentTest  Playwright test id of the running test (null outside tests)
   * @param {(key: string) => string} o.readable   readable test id (server bracket)
   * @param {(key, source, op, value) => void} o.record  append a fingerprint event (in order)
   * @param {string} o.dir  run directory (clock persisted across worker restarts)
   */
  constructor(o) {
    this.o = o;
    this.quantumMs = Number(ENV.DETJS_LS_QUANTUM_MS || 20);
    this.latencyMs = Number(ENV.DETJS_LS_LATENCY_MS || 1);
    this.quietMs = Number(ENV.DETJS_LS_QUIET_MS || 15);
    this.probeMaxMs = Number(ENV.DETJS_LS_PROBE_MAX_MS || 3000);
    this.serverQuietMs = Number(ENV.DETJS_LS_SERVER_QUIET_MS || 15);
    this.serverMaxMs = Number(ENV.DETJS_LS_SERVER_MAX_MS || 5000);
    this.stallMs = Number(ENV.DETJS_LS_STALL_MS || 3000);
    this.frameMs = Number(ENV.DETJS_LS_FRAME_MS || 16);
    this.frames = ENV.DETJS_LS_FRAMES !== '0';
    // Frame times handed to Chromium (renderer TimeTicks, ms). A document's animation timeline starts at its real
    // creation time (the machine's monotonic clock); a frame time before it leaves the timeline unresolved and every
    // CSS transition/animation frozen at its start (MEASURED: a 100 ms margin transition never moved with frame
    // times from 1000 ms). Frame times therefore start 6 h ahead of the monotonic clock at launch, so every document
    // created during the run lies behind them; only differences of frame times reach the page (animation progress),
    // and rAF timestamps are re-based on the engine page clock (page-init.js).
    this.frameBase = Number(process.hrtime.bigint() / 1000000n) + Number(ENV.DETJS_LS_FRAME_AHEAD_MS || 6 * 3600 * 1000);
    this.pageClock = ENV.DETJS_LS_PAGE_CLOCK !== '0';
    this.microMax = Number(ENV.DETJS_LS_MICRO_MAX || 200);
    this.fetchMs = Number(ENV.DETJS_LS_FETCH_MS === undefined ? 10 : ENV.DETJS_LS_FETCH_MS);
    this.microMs = Number(ENV.DETJS_LS_MICRO_MS === undefined ? 0.001 : ENV.DETJS_LS_MICRO_MS);
    // pauseIfNetworkFetchesPending: a page's time stops while any of its requests is open, so the real duration
    // of a script or style load never becomes page time (round-3 class A on actual: draw counts).
    // Default `advance`: every response a page gets (app requests, scripts, styles, images) is fetched by the engine
    // and handed over between two time slices, so network time never overlaps page time either way.
    this.vtPolicy = ENV.DETJS_LS_VT_POLICY || 'advance';
    this.clockFile = path.join(o.dir, 'lockstep-clock.json');
    let start = 0;
    try { start = Number(JSON.parse(fs.readFileSync(this.clockFile, 'utf8')).t) || 0; } catch { start = 0; }
    this.sched = new native.Lockstep(o.seed, !!o.seeded, start, this.quantumMs * NS, this.latencyMs * NS);
    this.applySeedSpace();
    this.msgs = new Map(); // id -> { item, resolve, owner, page }
    this.nextMsg = 1;
    this.holds = []; // { due, seq, id, info }
    this.holdSeq = 0;
    this.inprogress = new Map(); // id -> item (released, not completed)
    this.pages = new Set();
    this.servers = new Map(); // origin -> { attached, next, waiting, label }
    this.blocked = new Set();
    this.routedWs = 0; // WebSocket frames pages sent that reached the engine
    this.lpAwait = new Set(); // long polls the server answered whose response has not reached the engine yet
    this.lpArrived = new Set(); // long-poll responses that reached the engine before the server reported them
    this.quietHooks = [];
    this.window = new Map(); // test key -> events recorded since the last decision (flushed sorted)
    this.late = new Map(); // test key -> [decision, source, op, value] written at the end of the test
    this.responses = []; // fetched responses waiting for their page
    this.gatedResults = []; // results of runner calls waiting for a quiet point
    this.gating = ENV.DETJS_LS_GATE !== '0';
    this.admits = []; // runner calls waiting for admission
    this.actionMs = Number(ENV.DETJS_LS_ACTION_MS || 20);
    this.clock = new RunnerClock({
      currentTest: () => o.currentTest(),
      epochMs: o.epochMs,
      now: () => this.sched.now(),
      onActivity: () => { activity(); this.poke(); },
    });
    this.wake = null;
    this.lastKey = null;
    this.stats = { settles: 0, releases: 0, advances: 0, fired: 0, stalls: 0, probeWaits: 0, idleWaits: 0 };
    this.running = false;
    this.navPending = []; // navigations started by test code, not yet seen as a document request
  }

  applySeedSpace() {
    // Item 2 (seed space aimed at the flaking step) and item 4 (socket faults): see seedspace.js.
    try { require('./seedspace').configure(this.sched, ENV); } catch (e) { process.stderr.write(`detjs: seed space: ${e.message}\n`); }
  }

  now() { return this.sched.now(); }

  saveClock() {
    try { fs.writeFileSync(this.clockFile, JSON.stringify({ t: this.sched.now() })); } catch { /* best effort */ }
  }

  poke() {
    if (this.wake) { const w = this.wake; this.wake = null; w(); }
  }

  // -------------------------------------------------------------- recording (deterministic order)
  /** Events of one decision window are written sorted: their real arrival order inside the window is not
   * part of the schedule. */
  record(key, source, op, value) {
    if (!key) return;
    let w = this.window.get(key);
    if (!w) this.window.set(key, (w = []));
    w.push([source, op, String(value)]);
  }

  flushWindow() {
    for (const [key, list] of this.window) {
      list.sort((a, b) => (a.join('\u001f') < b.join('\u001f') ? -1 : 1));
      for (const [s, op, v] of list) this.o.record(key, s, op, v);
    }
    this.window.clear();
  }

  /** An event whose arrival time is not part of the schedule (a body read by the page in its own time): kept at
   * its message's decision index and written at the end of the test. */
  recordLate(key, decision, source, op, value) {
    if (!key) return;
    let l = this.late.get(key);
    if (!l) this.late.set(key, (l = []));
    l.push([Number(decision) || 0, source, op, String(value)]);
  }

  flushLate(key) {
    const l = this.late.get(key);
    if (!l) return;
    this.late.delete(key);
    l.sort((a, b) => a[0] - b[0] || (a.slice(1).join('\u001f') < b.slice(1).join('\u001f') ? -1 : 1));
    for (const [d, s, op, v] of l) this.o.record(key, s, op, `${d} ${v}`);
  }

  decision(key, op, value) {
    this.flushWindow();
    this.o.record(key, 'sched', op, value);
  }

  // -------------------------------------------------------------- messages
  /**
   * A message waits for its turn. Resolves with `done(how)` once released; the caller delivers the message and
   * calls done when it completed. item: { kind, test, method, target, bodyDigest, conn?, nav?, page?, server? }
   */
  enqueue(item) {
    return new Promise((resolve) => {
      const id = this.nextMsg++;
      const kind = item.nav ? 'nav' : item.kind === 'ws' ? 'ws-send' : item.kind === 'push' ? 'ws-recv' : item.kind;
      const key = `${item.kind} ${item.method} ${item.target} ${item.bodyDigest}`;
      this.msgs.set(id, { item, resolve, key, kind });
      if (item.nav && item.page) { const p = this.pageState(item.page); if (p) p.navs++; }
      this.sched.enqueue(id, key, item.test || '<none>', item.conn === undefined ? null : item.conn, 'w0', kind);
      this.trace(`enqueue #${id} ${key}`);
      activity();
      this.poke();
    });
  }

  deliver(id, info) {
    const m = this.msgs.get(id);
    if (!m) return;
    this.msgs.delete(id);
    const item = m.item;
    this.inprogress.set(id, item);
    this.stats.releases++;
    let finished = false;
    const done = () => {
      if (finished) return;
      finished = true;
      this.inprogress.delete(id);
      if (item.nav && item.page) { const p = this.pageState(item.page); if (p) p.navs = Math.max(0, p.navs - 1); }
      activity();
      this.poke();
    };
    item.fault = info.fault;
    item.lsId = id;
    item.decision = info.decision;
    item.lsT = this.sched.now();
    m.resolve(done);
  }

  // -------------------------------------------------------------- gated call results
  /** A runner call waits for admission: at a quiet point, ACTION ms after it was asked for. */
  admit(id) {
    return new Promise((resolve) => {
      this.admits.push({ id, due: this.sched.now() + this.actionMs * NS, resolve });
      this.admits.sort((a, b) => a.id - b.id);
      activity();
      this.poke();
    });
  }

  admitReady() {
    const T = this.sched.now();
    const ready = this.admits.filter((a) => a.due <= T);
    if (!ready.length) return 0;
    this.admits = this.admits.filter((a) => a.due > T);
    for (const a of ready) a.resolve();
    return ready.length;
  }

  gate(id, deliver, issuedNs) {
    // Seen by the runner ACTION ms after the call was issued, or when its result arrived if that was later.
    const T = this.sched.now();
    const due = Math.max((issuedNs === undefined ? T : issuedNs) + this.actionMs * NS, T);
    this.gatedResults.push({ id, deliver, waitFor: null, due });
    this.gatedResults.sort((a, b) => a.id - b.id);
    activity();
    this.poke();
  }

  /** At a quiet point: results whose action's messages were all released are delivered (in call order). */
  deliverGated() {
    let n = 0;
    for (const g of this.gatedResults) {
      if (g.waitFor === null) g.waitFor = new Set([...this.msgs.keys(), ...this.holds.map((h) => h.id)]);
    }
    const ready = [];
    const T = this.sched.now();
    for (const g of [...this.gatedResults]) {
      const open = [...g.waitFor].some((id) => this.msgs.has(id) || this.holds.some((h) => h.id === id));
      // A runner action takes time, as a real one does (CDP round trips, actionability checks); the page runs
      // meanwhile. Results are independent of each other: each is delivered when its own conditions hold.
      if (open || g.due > T) continue;
      ready.push(g);
      this.gatedResults.splice(this.gatedResults.indexOf(g), 1);
    }
    for (const g of ready) { g.deliver(); n++; }
    return n;
  }

  // -------------------------------------------------------------- responses to pages
  /** A response the engine fetched for a page: delivered at a quiet point, one at a time per page (the next only
   * after the page saw the previous one, which happens in the page's virtual time). */
  respond(page, item, fulfill, request) {
    // Chromium gives every completed fetch at least FETCH_MS of the page's virtual time (Blink's non-instant
    // virtual-time pauser: time jumps to start + 10 ms when the load ends). A response handed over earlier would
    // move the page clock past T by a real-time dependent amount: it is held until T >= start + FETCH_MS.
    const isDoc = !!item.nav || (request && request.resourceType && request.resourceType() === 'document');
    const notBefore = isDoc || this.vtPolicy !== 'advance' ? 0 : (item.reqT === undefined ? this.sched.now() : item.reqT) + this.fetchMs * NS;
    this.responses.push({ page, decision: item.decision || 0, id: item.lsId || 0, key: item.key || '', fulfill, request, notBefore, doc: !!item.nav || (request && request.resourceType && request.resourceType() === 'document') });
    this.responses.sort((a, b) => a.decision - b.decision || (a.key || '').localeCompare(b.key || '') || a.id - b.id);
    activity();
    this.poke();
  }

  /** Deliver the responses whose page has none waiting. Returns how many were delivered. */
  async deliverResponses() {
    let n = 0;
    const busyPages = new Set();
    for (const r of [...this.responses]) {
      if (r.notBefore > this.sched.now()) continue;
      const p = this.pageState(r.page);
      // With pauseIfNetworkFetchesPending the page's time cannot run while a response is outstanding, so responses
      // are handed over in decision order without waiting for the page to see the previous one.
      if (this.vtPolicy === 'advance' && (busyPages.has(r.page) || (p && p.awaiting))) { busyPages.add(r.page); continue; }
      busyPages.add(r.page);
      this.responses.splice(this.responses.indexOf(r), 1);
      if (p && r.request) {
        p.awaiting = r.request;
        const clear = (x) => {
          if ((x.request ? x.request() : x) !== r.request) return;
          r.page.off('response', clear); r.page.off('requestfailed', clear); r.page.off('close', clearAll);
          if (p.awaiting === r.request) p.awaiting = null;
          activity(); this.poke();
        };
        const clearAll = () => { if (p.awaiting === r.request) p.awaiting = null; };
        r.page.on('response', clear); r.page.on('requestfailed', clear); r.page.on('close', clearAll);
      }
      const tf = realNow();
      try { await r.fulfill(); } catch { if (p && p.awaiting === r.request) p.awaiting = null; }
      this.trace(`fulfill ${Math.round(realNow() - tf)}ms`);
      // §5(a): the page sees the response in a micro-slice of its own, right now. Chromium either processes a
      // fulfilled response while the page's time is paused or at the start of its next slice (decided in real
      // time inside the renderer); a micro-slice runs every task that is ready (virtual time only moves when the
      // page is idle), so both cases end in the same state at the same page time.
      if (p && this.microMs > 0 && this.vtPolicy === 'advance' && !r.doc && !p.closed && p.navs === 0 && !p.inBudget && !p.running) {
        // The body reaches the renderer through a data pipe in real time: micro-slices (1 us of page time each) run
        // until the load finished, plus one more for the JS continuation that the finished load resolves.
        // fetch/XHR: the page's own counter of responses its JS received (fetch settled, XHR loadend) is the
        // completion signal (the browser-side "finished" can precede the renderer's data-pipe read).
        let rtype = '';
        try { rtype = r.request ? r.request.resourceType() : ''; } catch { rtype = ''; }
        const jsSeen = rtype === 'fetch' || rtype === 'xhr';
        if (jsSeen) p.expectDone = (p.expectDone || 0) + 1;
        let finished = !r.request;
        const onEnd = (x) => { if (x === r.request && !jsSeen) finished = true; };
        if (r.request) { r.page.on('requestfinished', onEnd); r.page.on('requestfailed', onEnd); }
        let extra = 0;
        for (let i = 0; i < this.microMax && !p.closed && p.navs === 0; i++) {
          if (jsSeen && !finished) {
            const d = await this.pageDone(p);
            if (d === null || d >= p.expectDone) finished = true;
            // A response whose JS never runs (its document went away): stop expecting it.
            else if (i >= 40) { p.expectDone = d; finished = true; }
          }
          // A micro-slice can start a navigation (the page sets location): its document waits in the queue and
          // Chromium suspends the page until it arrives, so the slice ends after the engine released it.
          const mto = p.pageT + this.microMs * NS;
          const b = Promise.all([this.runWorkers(mto, { deferAfterMs: 50 }), this.budget(p, mto, { deferAfterMs: 50 })]);
          while (await Promise.race([b.then(() => true), realSleep(2).then(() => false)]) === false) {
            if (p.navs > 0 || this.navPending.length) break;
          }
          if (p.navs > 0 || p.inBudget) break;
          if (finished && ++extra >= 2) break;
          if (!finished) await realSleep(1);
        }
        if (r.request) { r.page.off('requestfinished', onEnd); r.page.off('requestfailed', onEnd); }
        await this.readPageClock(p);
      }
      n++;
    }
    return n;
  }

  // -------------------------------------------------------------- pages
  pageState(page) {
    for (const p of this.pages) if (p.page === page) return p;
    return null;
  }

  // ------------------------------------------------------------ workers (round 4, §5(2))
  // Dedicated and shared workers run on their own virtual-time controller: once their page's time is controlled
  // they stop and never resume (MEASURED: a 10 ms interval in a worker made 0 ticks in 300 ms real + 100 ms of page
  // budget). The engine attaches to every worker target (browser CDP session, non-flat) and gives it the same
  // slices as the pages, right after each page slice, so messages between page and worker cross at slice ends.
  async ensureWorkerControl(ctx) {
    if (this.workerCtl !== undefined || ENV.DETJS_LS_WORKERS !== '1') return; // opt-in: see INTERMEDIATE-2 (Atomics.wait between a worker and its page deadlocks fenced slices)
    this.workerCtl = null;
    let browser = null;
    try { browser = ctx.browser(); } catch { browser = null; }
    if (!browser || typeof browser.newBrowserCDPSession !== 'function') return;
    let bs;
    try { bs = await OWN.run(true, () => browser.newBrowserCDPSession()); } catch { return; }
    this.workerCtl = { bs, workers: new Map(), nextId: 1, waiters: new Map() };
    bs.on('Target.receivedMessageFromTarget', (e) => {
      let m;
      try { m = JSON.parse(e.message); } catch { return; }
      const w = this.workerCtl.workers.get(e.sessionId);
      if (m.id && this.workerCtl.waiters.has(m.id)) { const r = this.workerCtl.waiters.get(m.id); this.workerCtl.waiters.delete(m.id); r(m); return; }
      if (w && m.method === 'Emulation.virtualTimeBudgetExpired') { w.inBudget = false; w.waitingEngine = false; if (w.expired) { const r = w.expired; w.expired = null; r(); } activity(); this.poke(); }
    });
    bs.on('Target.targetCreated', (e) => { const t = e.targetInfo; this.trace(`target-created ${t && t.type} ${t && t.url && t.url.slice(-60)}`); if (t && /^(worker|shared_worker|service_worker)$/.test(t.type)) this.attachWorker(t.targetId).catch(() => {}); });
    bs.on('Target.targetDestroyed', (e) => {
      for (const [sid, w] of this.workerCtl.workers) if (w.targetId === e.targetId) { w.closed = true; if (w.expired) { const r = w.expired; w.expired = null; r(); } this.workerCtl.workers.delete(sid); }
    });
    bs.on('Target.detachedFromTarget', (e) => {
      const w = this.workerCtl.workers.get(e.sessionId);
      if (w) { w.closed = true; if (w.expired) { const r = w.expired; w.expired = null; r(); } this.workerCtl.workers.delete(e.sessionId); }
    });
    ACT.ownDepth++;
    try { await bs.send('Target.setDiscoverTargets', { discover: true }); } catch { /* old browser */ } finally { ACT.ownDepth--; }
  }

  workerSend(w, method, params) {
    const wc = this.workerCtl;
    const id = wc.nextId++;
    return new Promise((resolve) => {
      wc.waiters.set(id, resolve);
      ACT.ownDepth++;
      wc.bs.send('Target.sendMessageToTarget', { sessionId: w.sessionId, message: JSON.stringify({ id, method, params }) })
        .catch(() => { wc.waiters.delete(id); resolve(null); }).finally(() => { ACT.ownDepth--; });
      REAL.setTimeout(() => { if (wc.waiters.has(id)) { wc.waiters.delete(id); resolve(null); } }, 3000);
    });
  }

  async attachWorker(targetId) {
    const wc = this.workerCtl;
    if (!wc) return;
    let r;
    ACT.ownDepth++;
    try { r = await wc.bs.send('Target.attachToTarget', { targetId, flatten: false }); } catch { return; } finally { ACT.ownDepth--; }
    const w = { sessionId: r.sessionId, targetId, pageT: this.sched.now(), inBudget: false, expired: null, closed: false };
    wc.workers.set(w.sessionId, w);
    await this.workerSend(w, 'Emulation.setVirtualTimePolicy', { policy: 'pause', initialVirtualTime: (this.o.epochMs + this.sched.now() / NS) / 1000 });
    this.stats.workers = (this.stats.workers || 0) + 1;
    // A worker created inside a slice (a nested worker its parent waits for with Atomics.wait: actual's database)
    // joins that slice at once, or its parent and the page could never reach the end of it.
    if (this.lastSliceTo > w.pageT) this.runWorker(w, this.lastSliceTo).catch(() => {});
    activity(); this.poke();
  }

  /** Bring every worker to toNs (after a page slice). */
  async runWorkers(toNs, opt = {}) {
    if (!(this.lastSliceTo >= toNs)) this.lastSliceTo = toNs;
    const wc = this.workerCtl;
    if (!wc || !wc.workers.size) return;
    await Promise.all([...wc.workers.values()].map((w) => this.runWorker(w, toNs, opt)));
  }

  async runWorker(w, toNs, opt = {}) {
    {
      if (w.closed || w.inBudget || w.free) return;
      const budget = (toNs - w.pageT) / NS;
      if (budget <= 0) return;
      w.pageT = toNs;
      w.inBudget = true;
      const expired = new Promise((res) => { w.expired = res; });
      const ok = await this.workerSend(w, 'Emulation.setVirtualTimePolicy', { policy: 'advance', budget });
      if (!ok || ok.error) { w.inBudget = false; w.expired = null; return; }
      await this.awaitSlice(expired, () => w.closed, (v) => { w.waitingEngine = v; }, () => {
        // A worker whose slice never ends: it blocks in Atomics.wait on another thread (actual's SQLite backend
        // waits synchronously for the page), which a fenced page cannot answer. That worker runs free from now on
        // (Chromium's own virtual time, no budgets) and the switch is recorded.
        this.trace('stall worker budget -> free'); w.inBudget = false; w.expired = null; w.free = true;
        this.stats.freeWorkers = (this.stats.freeWorkers || 0) + 1;
        this.workerSend(w, 'Emulation.setVirtualTimePolicy', { policy: 'advance' }).catch(() => {});
        if (this.lastKey) this.decision(this.lastKey, 'ls.worker-free', w.targetId ? 'worker' : '');
      }, opt.deferAfterMs);
    }
  }

  async addPage(ctx, page) {
    await this.ensureWorkerControl(ctx);
    let cdp;
    try { cdp = await ctx.newCDPSession(page); } catch { return null; }
    const p = { page, cdp, pageT: this.sched.now(), inBudget: false, expired: null, navs: 0, routed: 0, closed: false, startedDoc: 0, startedBase: 0, blockers: new Set(), issued: 0, routedAll: 0 };
    // Exact request barrier (round 4): the renderer announces every request it starts (Network.requestWillBeSent)
    // on this session before it answers a later Runtime.evaluate; the engine waits until as many requests reached
    // its route handler. Parser-started requests (scripts, styles) are covered, which the page counters were not.
    cdp.on('Network.requestWillBeSent', (e) => { if (e && e.request && /^https?:/.test(e.request.url)) { p.issued++; activity(); } });
    try { ACT.ownDepth++; await cdp.send('Network.enable', { maxTotalBufferSize: 0, maxResourceBufferSize: 0 }); } catch { /* ignore */ } finally { ACT.ownDepth--; }
    cdp.on('Emulation.virtualTimeBudgetExpired', () => {
      if (!p.inBudget) return;
      p.inBudget = false;
      p.waitingEngine = false;
      const r = p.expired; p.expired = null;
      if (r) r();
      activity();
      this.poke();
    });
    if (ENV.DETJS_LS_TRACE_ALL) for (const ev of ['request', 'response', 'requestfinished', 'requestfailed']) page.on(ev, (r) => { const u = (r.url ? r.url() : ''); if (!/\.(js|css|svg|png)$/.test(u)) this.trace(`page-${ev} ${u.slice(-20)}`); });
    page.on('close', () => { p.closed = true; this.pages.delete(p); if (p.expired) { const r = p.expired; p.expired = null; r(); } this.poke(); });
    try {
      await cdp.send('Emulation.setVirtualTimePolicy', { policy: 'pause', initialVirtualTime: (this.o.epochMs + this.sched.now() / NS) / 1000 });
    } catch { return null; }
    this.pages.add(p);
    return p;
  }

  /**
   * A request of `page` that the engine holds or that never ends on its own (long polling): while it is open the
   * page's time is paused (pauseIfNetworkFetchesPending) and the page counts as waiting for the engine.
   */
  blockOn(page, request) {
    if (this.vtPolicy === 'advance') return;
    const p = this.pageState(page);
    if (!p) return;
    p.blockers.add(request);
    const done = (r) => {
      const req = r && r.request ? r.request() : r;
      if (req !== request) return;
      page.off('requestfinished', done); page.off('requestfailed', done); page.off('response', resp);
      p.blockers.delete(request);
      activity(); this.poke();
    };
    // A long poll unblocks when its response starts; an ordered fetch when it finished loading.
    const resp = (r) => { if (r.request() === request && request.__detjsLongPoll) done(r); };
    page.on('requestfinished', done); page.on('requestfailed', done); page.on('response', resp);
    page.once('close', () => p.blockers.delete(request));
  }

  /** The engine received the response of long poll `id` (worker.js lsFetch). */
  longPollArrived(id) {
    if (!this.lpAwait.delete(id)) this.lpArrived.add(id);
    activity(); this.poke();
  }

  navHold(page) {
    const p = this.pageState(page);
    if (!p) return () => {};
    p.navs++;
    let open = true;
    return () => { if (open) { open = false; p.navs = Math.max(0, p.navs - 1); activity(); this.poke(); } };
  }

  async pageDone(p) {
    ACT.ownDepth++;
    try {
      const r = await Promise.race([
        p.cdp.send('Runtime.evaluate', { expression: 'self.__detjs && self.__detjs.done ? self.__detjs.done() : -1', returnByValue: true }),
        realSleep(300).then(() => null),
      ]);
      const v = r && r.result ? Number(r.result.value) : -1;
      if (v < 0) return null;
      // A new document restarts the page's counter.
      if (p.doneDoc !== undefined && v < p.doneDoc) p.doneBase = (p.doneBase || 0) + p.doneDoc;
      p.doneDoc = v;
      return (p.doneBase || 0) + v;
    } catch { return null; } finally { ACT.ownDepth--; }
  }

  /** Any request of `page` reached the route handler. */
  routedAny(page) {
    const p = this.pageState(page);
    if (p) { p.routedAll++; activity(); this.poke(); }
  }

  /** A fetch/XHR of `page` reached the route handler. */
  routed(page) {
    const p = this.pageState(page);
    if (p) p.routed++;
  }

  /**
   * Give a page virtual time up to toNs. Animation frames are produced by the engine too (headless shell with
   * --deterministic-mode: no frame without HeadlessExperimental.beginFrame): one frame at every multiple of
   * FRAME ms of engine time, so requestAnimationFrame, CSS animations and Playwright's "stable" checks follow the
   * engine clock instead of the compositor's real-time vsync.
   */
  /** Raise a page's target to toNs; its time runs there in frame-sized slices, in the background (a slice can
   * stop on one of the page's requests and resume when the engine delivers it). */
  grant(p, toNs) {
    if (p.closed || p.navs > 0) return; // a page whose main-frame navigation is pending cannot run a budget
    if (!(p.target >= toNs)) p.target = toNs;
    if (p.running) return;
    p.running = true;
    this.runPage(p).catch(() => {}).finally(() => { p.running = false; activity(); this.poke(); });
  }

  async runPage(p) {
    const F = this.frameMs * NS;
    while (p.pageT < p.target && !p.closed && p.navs === 0) {
      const nextFrame = (Math.floor(p.pageT / F) + 1) * F;
      const stop = this.frames ? Math.min(nextFrame, p.target) : p.target;
      // Workers and their page share one slice: Chromium ends the page's budget only when its workers reached it.
      const wk = this.runWorkers(stop);
      if (this.pageClock) await this.anchor(p, p.pageT, (stop - p.pageT) / NS);
      await this.budget(p, stop);
      await wk;
      if (this.frames && stop === nextFrame && !p.closed) {
        // The frame's callbacks (rAF, animation events) read the frame time exactly, not engine time plus the
        // real time the slice happened to take.
        if (this.pageClock) await this.anchor(p, stop, 0);
        await this.beginFrame(p, stop);
      }
      await this.readPageClock(p);
    }
  }

  /** After every slice: Chromium may have moved the page's clock past the slice (its fixed duration for every
   * completed fetch). Read it at this fixed point of every slice, so the next slice brings it back to T. */
  /** §5(b): the page clock reads engine time `baseNs` plus at most `allowMs` of the page's own progress. */
  async anchor(p, baseNs, allowMs) {
    if (p.closed || p.navs > 0) return;
    ACT.ownDepth++;
    try {
      await Promise.race([
        p.cdp.send('Runtime.evaluate', { expression: `self.__detjs && self.__detjs.anchor ? self.__detjs.anchor(${this.o.epochMs + baseNs / NS}, ${allowMs}) : 0`, returnByValue: true }),
        realSleep(300),
      ]);
    } catch { /* navigating */ } finally { ACT.ownDepth--; }
  }

  async readPageClock(p) {
    if (this.pageClock) { await this.anchor(p, p.pageT, 0); return; }
    if (p.closed || p.navs > 0) return;
    ACT.ownDepth++;
    try {
      const r = await Promise.race([
        p.cdp.send('Runtime.evaluate', { expression: 'self.__detjs && self.__detjs.vnow ? self.__detjs.vnow() : 0', returnByValue: true }),
        realSleep(300).then(() => null),
      ]);
      const v = r && r.result ? Number(r.result.value) : 0;
      if (v > 0) {
        const pt = (v - this.o.epochMs) * NS;
        if (pt > p.pageT) p.pageT = pt;
      }
    } catch { /* navigating */ } finally { ACT.ownDepth--; }
  }

  async beginFrame(p, tNs) {
    if (p.noFrames) return;
    ACT.ownDepth++;
    try {
      const r = await Promise.race([
        p.cdp.send('HeadlessExperimental.beginFrame', { frameTimeTicks: this.frameBase + tNs / NS, interval: this.frameMs, noDisplayUpdates: false }),
        realSleep(this.stallMs).then(() => 'timeout'),
      ]);
      if (r === 'timeout') { this.stats.stalls++; this.trace('stall beginFrame'); }
      this.stats.frames = (this.stats.frames || 0) + 1;
    } catch (e) {
      // Not a headless shell with begin-frame control, or the page is navigating: frames stay the compositor's.
      if (/only supported|wasn't found|not found/i.test(String(e && e.message))) p.noFrames = true;
    } finally { ACT.ownDepth--; }
  }

  async budget(p, toNs, opt = {}) {
    const budget = (toNs - p.pageT) / NS;
    if (budget <= 0) return;
    p.pageT = toNs;
    p.inBudget = true;
    const expired = new Promise((r) => { p.expired = r; });
    ACT.ownDepth++;
    try {
      await p.cdp.send('Emulation.setVirtualTimePolicy', { policy: this.vtPolicy, budget });
    } catch {
      ACT.ownDepth--;
      p.inBudget = false; p.closed = true; this.pages.delete(p); return;
    }
    ACT.ownDepth--;
    return this.awaitSlice(expired, () => p.closed || p.blockers.size > 0, (v) => { p.waitingEngine = v; }, () => {
      this.trace(`stall budget ${budget}ms`); p.inBudget = false; p.expired = null;
    }, opt.deferAfterMs);
  }

  /** Something the engine holds can keep a slice from ending (a request of the page or of its workers, which
   * Chromium waits for). While that is so, the page counts as waiting for the engine (quiet). */
  engineWork() {
    return this.sched.pending() > 0 || this.holds.length > 0 || this.responses.length > 0 || this.inprogress.size > 0 || ACT.routes > 0;
  }

  async awaitSlice(expired, legit, setWaiting, onStall, deferAfterMs) {
    let since = realNow();
    const t0 = since;
    let done = false;
    let waiting = false;
    expired.then(() => { done = true; });
    while (!done) {
      await Promise.race([expired, realSleep(10)]);
      if (done) break;
      if (legit() || this.engineWork()) {
        // Called from inside a delivery (micro-slices): the engine cannot act until we return, so the slice is
        // left open (the page counts as waiting for the engine) instead of waited for.
        if (deferAfterMs !== undefined && realNow() - t0 > deferAfterMs) { setWaiting(true); return 'deferred'; }
        if (!waiting) { waiting = true; setWaiting(true); this.poke(); }
        since = realNow();
        continue;
      }
      if (realNow() - since > this.serverMaxMs) { this.stats.stalls++; onStall(); break; }
    }
    setWaiting(false);
  }

  /** A page still running its time slice, not waiting for anything the engine holds (its own requests, or a
   * worker's slice that waits for the engine). */
  pageBusy(p) {
    if (!(p.inBudget || p.running) || p.closed || p.navs > 0 || p.blockers.size > 0 || p.waitingEngine) return false;
    const wk = this.workerCtl ? [...this.workerCtl.workers.values()] : [];
    return !wk.some((w) => w.waitingEngine);
  }

  /** Wait until every page has finished its budget (a page with a pending navigation counts as paused). */
  async pagesPaused() {
    const t = realNow();
    for (;;) {
      // A page whose virtual time is paused on one of its requests (pauseIfNetworkFetchesPending) waits for the
      // engine: it is quiet.
      const busy = [...this.pages].filter((p) => this.pageBusy(p));
      if (!busy.length) return true;
      if (realNow() - t > this.serverMaxMs) { this.stats.stalls++; this.diag('stall', 'budget'); return false; }
      await new Promise((r) => { this.wake = r; REAL.setTimeout(r, 50); });
    }
  }

  /** Every fetch/XHR a page started has reached the route handler (exact barrier through the page's counter). */
  async probePages() {
    // Every fetch/XHR/WebSocket frame a page started must have reached the engine (exact barrier through the
    // pages' own counters; WebSocket frames cannot be told apart by page, so the barrier is over all pages).
    let started = 0;
    let probed = false;
    for (const p of [...this.pages]) {
      if (p.closed || p.navs > 0 || p.inBudget || p.running || this.navPending.length) return; // not probeable now
      let v = null;
      ACT.ownDepth++;
      try {
        const r = await Promise.race([
          p.cdp.send('Runtime.evaluate', { expression: 'self.__detjs && self.__detjs.reqs ? [self.__detjs.reqs(), self.__detjs.vnow()] : [-1, 0]', returnByValue: true }),
          realSleep(300).then(() => null),
        ]);
        v = r && r.result && Array.isArray(r.result.value) ? r.result.value : null;
      } catch { v = null; } finally { ACT.ownDepth--; }
      if (!v || v[0] < 0) continue;
      // Chromium adds virtual time of its own for every fetch a page completes (a fixed "non-instant" fetch
      // duration): the page's clock is read back here so that the next budget only brings it to T.

      // A document's counter restarts at 0: count per page the maximum seen since the last navigation.
      if (v[0] < p.startedDoc) { p.startedBase = (p.startedBase || 0) + p.startedDoc; }
      p.startedDoc = Number(v[0]);
      started += (p.startedBase || 0) + p.startedDoc;
      probed = true;
    }
    if (!probed) return;
    const routed = () => [...this.pages].reduce((a, p) => a + p.routed, 0) + this.routedWs;
    const t = realNow();
    while ((routed() < started || [...this.pages].some((p) => !p.closed && p.routedAll < p.issued)) && realNow() - t < this.probeMaxMs) {
      this.stats.probeWaits++;
      await realSleep(2);
    }
  }

  // -------------------------------------------------------------- servers
  addOrigin(origin) {
    if (!this.servers.has(origin)) this.servers.set(origin, { attached: false, next: null, waiting: false });
  }

  serverCall(origin, op, params) {
    return new Promise((resolve) => {
      let u;
      try {
        u = new URL(`/__detjs/ls/${op}`, origin);
        for (const [k, v] of Object.entries(params)) u.searchParams.set(k, String(v));
      } catch { resolve(null); return; }
      const req = http.get(u, { agent: CTL_AGENT, timeout: this.serverMaxMs + 3000 }, (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => { try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); } catch { resolve(null); } });
      });
      req.on('socket', (s) => { s.__detjsCtl = true; });
      req.on('error', () => resolve(null));
      req.on('timeout', () => { req.destroy(); });
    });
  }

  /** Bring every known app server to T: it fires its timers due by T, then reports when quiet. */
  async settleServers() {
    const t = this.sched.now();
    this.blocked = new Set(); // released messages a server holds, blocked on its own virtual timers
    for (const [origin, s] of [...this.servers].sort()) {
      const r = await this.serverCall(origin, 'settle', { t, w: this.serverQuietMs, max: this.serverMaxMs });
      if (!r || r.lockstep === false) { s.next = null; s.waiting = false; s.dead = !r; continue; }
      s.attached = true;
      s.next = r.next === null || r.next === undefined ? null : Number(r.next);
      s.waiting = !!r.waiting;
      if (ENV.DETJS_LS_TRACE_SRV) this.trace(`srv ${JSON.stringify(r)} inprog=${[...this.inprogress.keys()]}`);
      for (const id of r.blocked || []) this.blocked.add(Number(id));
      for (const id of r.lpDone || []) if (!this.lpArrived.delete(Number(id))) this.lpAwait.add(Number(id));
      if (r.busy) { this.stats.stalls++; this.diag('stall', `server ${origin} busy`); }
      if (r.fired) this.stats.fired += r.fired;
    }
  }

  // -------------------------------------------------------------- settle
  async settle(key) {
    this.stats.settles++;
    const tSettle = realNow();
    try { return await this.settleInner(key); } finally { if (realNow() - tSettle > 300) this.trace(`settle took ${Math.round(realNow() - tSettle)}ms`); }
  }

  async settleInner(key) {
    const tS = realNow();
    for (let round = 0; ; round++) {
      const t1 = realNow();
      await this.pagesPaused();
      const t2 = realNow();
      await this.probePages();
      const t3 = realNow();
      if (t3 - t1 > 100) this.trace(`slow-settle paused=${Math.round(t2 - t1)} probe=${Math.round(t3 - t2)} total=${Math.round(t3 - tS)} pages=${[...this.pages].map((p) => `[run=${p.running} inb=${p.inBudget} navs=${p.navs} blk=${p.blockers.size} url=${(() => { try { return p.page.url().slice(-20); } catch { return '?'; } })()}]`)} navp=${this.navPending.length} pend=${this.sched.pending()} holds=${this.holds.length} resp=${this.responses.length}`);
      // Navigations started by the test code must reach the queue first (their document request).
      const tNav = realNow();
      while (this.navPending.length && realNow() - tNav < this.probeMaxMs) await realSleep(2);
      // The servers settle while the worker's quiet window runs (both are real-time waits).
      const a0 = ACT.n;
      const t0 = realNow();
      const window = (async () => {
        while (realNow() - t0 < this.quietMs) {
          await realSleep(2);
          if (ACT.n !== a0 || ACT.routes > 0 || [...this.pages].some((p) => this.pageBusy(p))) return false;
        }
        return true;
      })();
      const t4 = realNow();
      const [, quiet] = await Promise.all([this.settleServers(), window]);
      if (realNow() - t4 > 100) this.trace(`slow-servers ${Math.round(realNow() - t4)}`);
      if (this.o.currentTest() !== key) return false;
      if (quiet && ACT.n === a0) {
        // A released message still in progress keeps the system busy, unless an app server reports a request
        // blocked on its own virtual timers (then only time can complete it).
        if ([...this.inprogress.keys()].every((id) => this.blocked.has(id)) && this.lpAwait.size === 0) return true;
        await new Promise((r) => { this.wake = r; REAL.setTimeout(r, 20); });
        continue;
      }
      if (round > 0 && round % 10 === 0) this.trace(`settle-round ${round} quiet=${quiet} act=${ACT.n - a0} routes=${ACT.routes} budgets=${[...this.pages].filter((p) => p.inBudget).length} inprog=${[...this.inprogress.keys()]} blocked=${[...this.blocked]} navp=${this.navPending.length} pend=${this.sched.pending()} holds=${this.holds.length} resp=${this.responses.length} pages=${[...this.pages].map((p) => `[run=${p.running} inb=${p.inBudget} we=${p.waitingEngine} navs=${p.navs} blk=${p.blockers.size}]`)} workers=${this.workerCtl ? [...this.workerCtl.workers.values()].map((w) => `[inb=${w.inBudget} we=${w.waitingEngine}]`) : '-'}`);
    }
  }

  /** Run fn at the next quiet point (observations at test end). */
  atQuiet(fn) {
    return new Promise((resolve, reject) => {
      if (!this.running || this.o.currentTest() === null) { Promise.resolve().then(fn).then(resolve, reject); return; }
      this.quietHooks.push({ fn, resolve, reject });
      this.poke();
    });
  }

  trace(text) {
    if (!ENV.DETJS_LS_TRACE) return;
    try { fs.appendFileSync(ENV.DETJS_LS_TRACE, `${(this.sched.now() / NS).toFixed(3)} ${text}${ENV.DETJS_LS_TRACE_REAL ? ` @${Math.round(realNow())}` : ""}\n`); } catch { /* ignore */ }
  }

  diag(op, text) {
    if (ENV.DETJS_PW_DEBUG === '1') process.stderr.write(`[detjs ls T=${(this.sched.now() / NS).toFixed(1)}ms] ${op} ${text}\n`);
  }

  /**
   * The runner's state: `busy` (the browser or another process works for it: time must not advance), `waiting`
   * (it waits on time: a sleep, a retry interval, an operation deadline, an in-page wait), or `idle`.
   * A `busy` that does not change for STALL ms is a wait we do not recognise: counted as waiting (recorded).
   */
  runnerState() {
    const c = cdpState();
    const now = realNow();
    if (CALLS.realwork > 0) return { state: 'busy', why: 'realwork' };
    if (this.admits.length) return { state: 'waiting', why: `admit:${this.admits.length}` };
    if (c.busy > 0) {
      if (now - c.oldest > this.stallMs && now - CDP.lastChange > this.stallMs) return { state: 'waiting', why: `cdp-stall:${c.methods.join(',')}`, stall: true };
      return { state: 'busy', why: `cdp:${c.methods.join(',')}` };
    }
    if (NETFLIGHT.n > 0) {
      if (now - NETFLIGHT.since > this.stallMs * 3) return { state: 'waiting', why: 'net-stall', stall: true };
      return { state: 'busy', why: `net:${NETFLIGHT.n}` };
    }
    if (this.clock.waitingTimers() > 0 || c.wait > 0) return { state: 'waiting', why: `timers:${JSON.stringify(this.clock.kinds())} await:${c.wait}` };
    if (CALLS.inflight > 0) return { state: 'waiting', why: `calls:${[...CALLS.byMethod.keys()]}` };
    if (CALLS.waits.size > 0) return { state: 'waiting', why: `waiters:${CALLS.waits.size}` };
    if (this.extraWaiting && this.extraWaiting() > 0) return { state: 'waiting', why: 'node-fetch' };
    // The runner's own requests (Playwright API requests, Node fetch) pending, held or in progress: it waits on them.
    let api = 0;
    for (const m of this.msgs.values()) if (m.item.kind === 'api') api++;
    for (const it of this.inprogress.values()) if (it.kind === 'api') api++;
    for (const h of this.holds) { const m = this.msgs.get(h.id); if (m && m.item.kind === 'api') api++; }
    if (api > 0) return { state: 'waiting', why: `api:${api}` };
    return { state: 'idle', why: '' };
  }

  // -------------------------------------------------------------- main loop
  start() {
    if (this.running) return;
    this.running = true;
    this.loop().catch((e) => { process.stderr.write(`detjs: lockstep loop failed: ${e && e.stack}\n`); this.running = false; });
  }

  async loop() {
    for (;;) {
      const key = this.clock.sync();
      if (key !== this.lastKey) {
        if (this.lastKey) this.endTest(this.lastKey);
        this.lastKey = key;
      }
      if (!key) { await new Promise((r) => { this.wake = r; const h = REAL.setTimeout(r, 5); if (h.unref) h.unref(); }); continue; }
      if (!(await this.settle(key))) continue;
      if (this.quietHooks.length) {
        const hooks = this.quietHooks; this.quietHooks = [];
        for (const h of hooks) { try { h.resolve(await h.fn()); } catch (e) { h.reject(e); } }
        continue;
      }
      const T = this.sched.now();
      // 0. Responses fetched for pages, handed over at a quiet point.
      if (this.responses.length && (await this.deliverResponses()) > 0) continue;
      // 0b. Runner calls admitted now.
      if (this.admits.length && this.admitReady() > 0) { this.flushWindow(); continue; }
      // 1. Held messages due now (seeded latency), in (due, release) order.
      if (this.holds.length && this.holds[0].due <= T) {
        const h = this.holds.shift();
        const hm = this.msgs.get(h.id);
        this.decision((hm && hm.item.test) || key, 'ls.deliver', `${h.decision} ${hm ? hm.key : ''}`);
        this.trace(`deliver #${h.id}`);
        this.deliver(h.id, h.info);
        continue;
      }
      // 2. Runner timers due now.
      if (this.clock.hasDue(T)) {
        this.flushWindow();
        this.trace(`fire runner ${this.clock.queue.filter((t) => t._due <= T).map((t) => `${t._kind}:${t._delay}`).join(',')}`);
        this.stats.fired += await this.clock.fireDue(T);
        continue;
      }
      // 3. The scheduler: release, advance or idle.
      const rs = this.runnerState();
      if (ENV.DETJS_LS_TRACE_ALL) this.trace(`pages ${[...this.pages].map((p) => `[run=${p.running} inb=${p.inBudget} navs=${p.navs} pageT=${p.pageT / NS} tgt=${p.target / NS} blk=${[...p.blockers].map((r) => r.url().slice(-12))}]`)}`);
      if (ENV.DETJS_LS_TRACE_ALL) this.trace(`state ${rs.state}/${rs.why} pend=${this.sched.pending()} holds=${this.holds.length} gated=${this.gatedResults.map((g) => g.id)} inprog=${[...this.inprogress.keys()]} resp=${this.responses.length}`);
      if (rs.state === 'busy' && this.sched.pending() === 0) {
        // The browser (or a browser launch) works for the runner: wait for it, in real time, without deciding.
        await new Promise((r) => { this.wake = r; REAL.setTimeout(r, 20); });
        continue;
      }
      if (rs.stall) { this.stats.stalls++; this.decision(key, 'ls.stall', rs.why.split(':')[0]); }
      this.sched.setDeadline('runner', this.clock.nextDue());
      this.sched.setWaiting('runner', rs.state === 'waiting');
      let netDue = this.holds.length ? this.holds[0].due : null;
      for (const g of this.admits) if (g.due > this.sched.now() && (netDue === null || g.due < netDue)) netDue = g.due;
      for (const r of this.responses) if (r.notBefore > this.sched.now() && (netDue === null || r.notBefore < netDue)) netDue = r.notBefore;
      this.sched.setDeadline('net', netDue);
      this.sched.setWaiting('net', false);
      let srvNext = null;
      let srvWait = false;
      for (const s of this.servers.values()) {
        if (s.next !== null && (srvNext === null || s.next < srvNext)) srvNext = s.next;
        srvWait = srvWait || s.waiting;
      }
      this.sched.setDeadline('servers', srvNext);
      this.sched.setWaiting('servers', false); // only the runner's wait moves time (see runnerState)
      const a = this.sched.next();
      this.trace(`${a.kind} ${a.kind === 'release' ? (this.msgs.get(a.id) || {}).key : a.kind === 'advance' ? `to=${a.toNs / NS} rs=${rs.state}/${rs.why} calls=${CALLS.inflight}[${[...CALLS.byMethod.keys()]}] rn=${this.clock.nextDue() === null ? '-' : this.clock.nextDue() / NS} srv=${srvNext === null ? '-' : srvNext / NS}/${srvWait} holds=${this.holds.length}` : ''}`);
      if (a.kind === 'release') {
        const m = this.msgs.get(a.id);
        const info = { fault: a.fault, latencyNs: a.latencyNs, decision: a.decision };
        this.decision(m ? (m.item.test || key) : key, 'sched.io', `${a.idx}/${a.n}:${m ? m.key : '?'}${a.fault !== 'none' ? ` fault=${a.fault}` : ''}${a.latencyNs !== this.latencyMs * NS ? ` lat=${a.latencyNs / NS}` : ''}`);
        // Every message travels for its latency (base 1 ms, or the seed's choice): it is delivered when the engine
        // clock reaches T + latency, after the timers due by then fired, and is complete (or blocked on a server
        // timer) before T moves again.
        if (a.latencyNs > 0) {
          this.holds.push({ due: T + a.latencyNs, seq: this.holdSeq++, id: a.id, info, decision: a.decision });
          this.holds.sort((x, y) => x.due - y.due || x.seq - y.seq);
        } else {
          this.deliver(a.id, info);
        }
        continue;
      }
      if (a.kind === 'advance') {
        this.stats.advances++;
        this.flushWindow();
        this.saveClock();
        const to = a.toNs;
        if (this.responses.length) await this.deliverResponses();
        for (const p of this.pages) this.grant(p, to);
        continue;
      }
      // Idle: nobody waits on time and nothing is pending. The runner is busy with its own work (test code, a
      // database query of a seed helper): wait for activity. A wait that never ends would be a call we do not
      // see as a wait: after STALL ms the runner is counted as waiting once (recorded).
      this.stats.idleWaits++;
      this.trace(`idle-state kinds=${JSON.stringify(this.clock.kinds())} waits=${CALLS.waits.size} calls=${CALLS.inflight}`);
      const t0 = realNow();
      const n0 = ACT.n;
      await new Promise((r) => { this.wake = r; REAL.setTimeout(r, this.stallMs); });
      if (ACT.n === n0 && realNow() - t0 >= this.stallMs && this.o.currentTest() === key && (this.clock.queue.length || this.pages.size)) {
        this.stats.stalls++;
        this.decision(key, 'ls.stall', `${this.clock.queue.length}`);
        const to = T + this.quantumMs * NS;
        this.sched.advanceTo(to);
        if (this.responses.length) await this.deliverResponses();
        for (const p of this.pages) this.grant(p, to);
      }
    }
  }

  endTest(key) {
    this.trace(`end ${key}`);
    this.flushWindow();
    this.flushLate(key);
    this.clock.releaseTest(key);
    this.saveClock();
    if (ENV.DETJS_LS_STATS === '1') process.stderr.write(`detjs lockstep ${JSON.stringify({ test: this.o.readable(key), t_ms: this.sched.now() / NS, ...this.stats, calls: [...CALLS.byMethod.keys()] })}\n`);
    for (const k of Object.keys(this.stats)) this.stats[k] = 0;
    // Pages of the finished test that stay open (worker-scoped contexts) keep their state; nothing else to do.
  }
}

function create(o) {
  installActivity();
  // A worker whose runner is gone must not keep stepping the app servers.
  process.once('disconnect', () => { try { process.exit(1); } catch { /* exiting */ } });
  LS = new Coordinator(o);
  LS.clock.install();
  LS.start();
  return LS;
}

module.exports = { OWN, create, onModuleLoaded, ACT, CALLS, CDP, NETFLIGHT, netStart, netEnd, activity, get LS() { return LS; } };
