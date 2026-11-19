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
const FRAME_METHODS = /^(Page\.captureScreenshot|Page\.startScreencast|Page\.screencastFrameAck|Page\.printToPDF)$/;
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
const CALLS = { inflight: 0, byMethod: new Map(), patched: new WeakSet() };
function patchDispatcher(DC) {
  if (!DC || !DC.prototype || CALLS.patched.has(DC.prototype)) return false;
  CALLS.patched.add(DC.prototype);
  const orig = DC.prototype.dispatch;
  DC.prototype.dispatch = async function dispatch(message) {
    let type = '';
    try { const d = this._dispatcherByGuid.get(message.guid); type = d ? d._type : ''; } catch { /* ignore */ }
    const mine = OWN_TYPES.has(type) || message.method === '__waitInfo__' || message.method === '__abort__'
      || (message.method === 'fetch' && message.params && Array.isArray(message.params.headers) && message.params.headers.some((h) => h && h.name === 'x-detjs-own'));
    if (mine) return orig.call(this, message);
    const k = `${type}.${message.method}`;
    if (REALWORK.test(k)) CALLS.realwork = (CALLS.realwork || 0) + 1;
    CALLS.inflight++;
    CALLS.byMethod.set(k, (CALLS.byMethod.get(k) || 0) + 1);
    activity();
    try {
      return await orig.call(this, message);
    } finally {
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
    this.quietHooks = [];
    this.window = new Map(); // test key -> events recorded since the last decision (flushed sorted)
    this.late = new Map(); // test key -> [decision, source, op, value] written at the end of the test
    this.responses = []; // fetched responses waiting for their page
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

  // -------------------------------------------------------------- responses to pages
  /** A response the engine fetched for a page: delivered at a quiet point, one at a time per page (the next only
   * after the page saw the previous one, which happens in the page's virtual time). */
  respond(page, item, fulfill, request) {
    this.responses.push({ page, decision: item.decision || 0, id: item.lsId || 0, fulfill, request });
    this.responses.sort((a, b) => a.decision - b.decision || a.id - b.id);
    activity();
    this.poke();
  }

  /** Deliver the responses whose page has none waiting. Returns how many were delivered. */
  async deliverResponses() {
    let n = 0;
    const busyPages = new Set();
    for (const r of [...this.responses]) {
      const p = this.pageState(r.page);
      if (busyPages.has(r.page) || (p && p.awaiting)) { busyPages.add(r.page); continue; }
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
      try { await r.fulfill(); } catch { if (p && p.awaiting === r.request) p.awaiting = null; }
      n++;
    }
    return n;
  }

  // -------------------------------------------------------------- pages
  pageState(page) {
    for (const p of this.pages) if (p.page === page) return p;
    return null;
  }

  async addPage(ctx, page) {
    let cdp;
    try { cdp = await ctx.newCDPSession(page); } catch { return null; }
    const p = { page, cdp, pageT: this.sched.now(), inBudget: false, expired: null, navs: 0, routed: 0, closed: false, started: 0 };
    cdp.on('Emulation.virtualTimeBudgetExpired', () => {
      if (!p.inBudget) return;
      p.inBudget = false;
      const r = p.expired; p.expired = null;
      if (r) r();
      activity();
      this.poke();
    });
    page.on('close', () => { p.closed = true; this.pages.delete(p); if (p.expired) { const r = p.expired; p.expired = null; r(); } this.poke(); });
    try {
      await cdp.send('Emulation.setVirtualTimePolicy', { policy: 'pause', initialVirtualTime: (this.o.epochMs + this.sched.now() / NS) / 1000 });
    } catch { return null; }
    this.pages.add(p);
    return p;
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
  async grant(p, toNs) {
    if (p.closed || p.navs > 0) return; // a page whose main-frame navigation is pending cannot run a budget
    const F = this.frameMs * NS;
    while (p.pageT < toNs && !p.closed && p.navs === 0) {
      const nextFrame = (Math.floor(p.pageT / F) + 1) * F;
      const stop = this.frames ? Math.min(nextFrame, toNs) : toNs;
      await this.budget(p, stop);
      if (this.frames && stop === nextFrame && !p.closed) await this.beginFrame(p, stop);
    }
  }

  async beginFrame(p, tNs) {
    if (p.noFrames) return;
    ACT.ownDepth++;
    try {
      await p.cdp.send('HeadlessExperimental.beginFrame', { frameTimeTicks: 1000 + tNs / NS, interval: this.frameMs, noDisplayUpdates: false });
      this.stats.frames = (this.stats.frames || 0) + 1;
    } catch (e) {
      // Not a headless shell with begin-frame control, or the page is navigating: frames stay the compositor's.
      if (/only supported|wasn't found|not found/i.test(String(e && e.message))) p.noFrames = true;
    } finally { ACT.ownDepth--; }
  }

  async budget(p, toNs) {
    const budget = (toNs - p.pageT) / NS;
    if (budget <= 0) return;
    p.pageT = toNs;
    p.inBudget = true;
    const expired = new Promise((r) => { p.expired = r; });
    ACT.ownDepth++;
    try {
      await p.cdp.send('Emulation.setVirtualTimePolicy', { policy: 'advance', budget });
    } catch {
      ACT.ownDepth--;
      p.inBudget = false; p.closed = true; this.pages.delete(p); return;
    }
    ACT.ownDepth--;
    await expired;
  }

  /** Wait until every page has finished its budget (a page with a pending navigation counts as paused). */
  async pagesPaused() {
    const t = realNow();
    for (;;) {
      const busy = [...this.pages].filter((p) => p.inBudget && p.navs === 0 && !p.closed);
      if (!busy.length) return true;
      if (realNow() - t > this.serverMaxMs) { this.stats.stalls++; this.diag('stall', 'budget'); return false; }
      await new Promise((r) => { this.wake = r; REAL.setTimeout(r, 50); });
    }
  }

  /** Every fetch/XHR a page started has reached the route handler (exact barrier through the page's counter). */
  async probePages() {
    for (const p of [...this.pages]) {
      if (p.closed || p.navs > 0 || p.inBudget) continue;
      let started = null;
      ACT.ownDepth++;
      try {
        const r = await Promise.race([
          p.cdp.send('Runtime.evaluate', { expression: 'self.__detjs && self.__detjs.reqs ? self.__detjs.reqs() : -1', returnByValue: true }),
          realSleep(1000).then(() => null),
        ]);
        started = r && r.result ? Number(r.result.value) : null;
      } catch { started = null; } finally { ACT.ownDepth--; }
      if (started === null || started < 0) continue;
      p.started = started;
      const t = realNow();
      while (p.routed < started && realNow() - t < this.probeMaxMs && !p.closed) {
        this.stats.probeWaits++;
        await realSleep(2);
      }
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
      if (r.busy) { this.stats.stalls++; this.diag('stall', `server ${origin} busy`); }
      if (r.fired) this.stats.fired += r.fired;
    }
  }

  // -------------------------------------------------------------- settle
  async settle(key) {
    this.stats.settles++;
    for (let round = 0; ; round++) {
      await this.pagesPaused();
      await this.probePages();
      // Navigations started by the test code must reach the queue first (their document request).
      const tNav = realNow();
      while (this.navPending.length && realNow() - tNav < this.probeMaxMs) await realSleep(2);
      // The servers settle while the worker's quiet window runs (both are real-time waits).
      const a0 = ACT.n;
      const t0 = realNow();
      const window = (async () => {
        while (realNow() - t0 < this.quietMs) {
          await realSleep(2);
          if (ACT.n !== a0 || ACT.routes > 0 || [...this.pages].some((p) => p.inBudget && p.navs === 0)) return false;
        }
        return true;
      })();
      const [, quiet] = await Promise.all([this.settleServers(), window]);
      if (this.o.currentTest() !== key) return false;
      if (quiet && ACT.n === a0) {
        // A released message still in progress keeps the system busy, unless an app server reports a request
        // blocked on its own virtual timers (then only time can complete it).
        if ([...this.inprogress.keys()].every((id) => this.blocked.has(id))) return true;
        await new Promise((r) => { this.wake = r; REAL.setTimeout(r, 20); });
        continue;
      }
      if (round > 0 && round % 200 === 0) this.diag('settle', `round ${round}`);
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
      // 0. Responses fetched for pages, one per page that has none pending.
      if (this.responses.length && (await this.deliverResponses()) > 0) continue;
      // 1. Held messages due now (seeded latency), in (due, release) order.
      if (this.holds.length && this.holds[0].due <= T) {
        const h = this.holds.shift();
        this.decision(key, 'ls.deliver', `${h.decision} ${this.msgs.get(h.id) ? this.msgs.get(h.id).key : ''}`);
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
      if (rs.state === 'busy' && this.sched.pending() === 0) {
        // The browser (or a browser launch) works for the runner: wait for it, in real time, without deciding.
        await new Promise((r) => { this.wake = r; REAL.setTimeout(r, 20); });
        continue;
      }
      if (rs.stall) { this.stats.stalls++; this.decision(key, 'ls.stall', rs.why.split(':')[0]); }
      this.sched.setDeadline('runner', this.clock.nextDue());
      this.sched.setWaiting('runner', rs.state === 'waiting');
      this.sched.setDeadline('net', this.holds.length ? this.holds[0].due : null);
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
        await Promise.all([...this.pages].map((p) => this.grant(p, to)));
        continue;
      }
      // Idle: nobody waits on time and nothing is pending. The runner is busy with its own work (test code, a
      // database query of a seed helper): wait for activity. A wait that never ends would be a call we do not
      // see as a wait: after STALL ms the runner is counted as waiting once (recorded).
      this.stats.idleWaits++;
      const t0 = realNow();
      const n0 = ACT.n;
      await new Promise((r) => { this.wake = r; REAL.setTimeout(r, this.stallMs); });
      if (ACT.n === n0 && realNow() - t0 >= this.stallMs && this.o.currentTest() === key && (this.clock.queue.length || this.pages.size)) {
        this.stats.stalls++;
        this.decision(key, 'ls.stall', `${this.clock.queue.length}`);
        const to = T + this.quantumMs * NS;
        this.sched.advanceTo(to);
        await Promise.all([...this.pages].map((p) => this.grant(p, to)));
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
  LS = new Coordinator(o);
  LS.clock.install();
  LS.start();
  return LS;
}

module.exports = { create, onModuleLoaded, ACT, CALLS, CDP, NETFLIGHT, netStart, netEnd, activity, get LS() { return LS; } };
