'use strict';
// Level 2 for browser tests: the controls applied from a Playwright Test
// worker process (loaded by boot.js when TEST_WORKER_INDEX is set).
//
// For every browser context the tests create:
//   * browser time: CDP Emulation.setVirtualTimePolicy on every page
//     (pauseIfNetworkFetchesPending: timers never overtake a pending fetch;
//     the page starts at the run's epoch); `fast` grants virtual time as fast
//     as the page idles, `paced` never lets it run ahead of real time;
//   * seeds: an init script seeding Math.random / crypto in every frame;
//   * network order: requests of the app (documents, fetch, XHR) and the
//     runner's API requests go through one queue per worker: after a quiet
//     window the next request is chosen from the pending set (sorted; with a
//     seed, a seeded choice), released with an `x-detjs-test` header (the app
//     server's test bracket) and awaited to completion before the next one;
//     WebSocket frames are relayed in order and recorded;
//   * fingerprint: choices, request/response digests, frame digests, page
//     seeds stats, final DOM digest and the app server's per-test fingerprint
//     become events of the test, written to <DETJS_DIR>/buckets/ and turned
//     into the shared trace by reporter.js.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const Module = require('node:module');
const native = require('../native');
const { pageInitSource } = require('./page-init');

const ENV = process.env;
const SEED = BigInt(ENV.DETJS_SEED || '0');
const SHUFFLE = ENV.DETJS_SHUFFLE === '1';
const DIR = ENV.DETJS_DIR || path.join(process.cwd(), '.detjs', 'run');
const ROOT = ENV.DETJS_ROOT || process.cwd();
const VTIME = ENV.DETJS_PW_VTIME || 'paced';
const WINDOW_MS = Number(ENV.DETJS_PW_NET_WINDOW || 15);
const NET = ENV.DETJS_PW_NET !== 'off';
const SEEDS = ENV.DETJS_PW_SEEDS !== 'off';
const VCAP_MS = Number(ENV.DETJS_PW_VTIME_CAP || 600000);
const EPOCH_MS = Date.parse(ENV.DETJS_EPOCH || '2025-01-01T00:00:00Z');
const SERVER_HOSTS = new Set((ENV.DETJS_PW_SERVER_HOSTS || 'localhost,127.0.0.1,[::1],0.0.0.0').split(','));
const COMPLETE_TIMEOUT_MS = Number(ENV.DETJS_PW_COMPLETE_TIMEOUT || 5000);
const APP_TYPES = new Set(['document', 'fetch', 'xhr']);
const DEBUG = ENV.DETJS_PW_DEBUG === '1';
const T_START = Date.now();
function dbg(...a) { if (DEBUG) process.stderr.write(`[detjs ${Date.now() - T_START}ms] ${a.join(' ')}\n`); }

// ---------------------------------------------------------------- buckets
const BUCKET_DIR = path.join(DIR, 'buckets');
fs.mkdirSync(BUCKET_DIR, { recursive: true });
const PENDING = new Map(); // testId -> [[source, op, site, value]]
let PW_TEST = null;

function testInfo() {
  if (!PW_TEST) return null;
  try { return PW_TEST.test.info(); } catch { return null; }
}
function currentKey() {
  const ti = testInfo();
  return ti ? ti.testId : null;
}
function rec(key, source, op, value) {
  if (!key) return;
  let list = PENDING.get(key);
  if (!list) PENDING.set(key, (list = []));
  list.push([source, op, '', String(value)]);
}
function flush(key) {
  const keys = key ? [key] : [...PENDING.keys()];
  for (const k of keys) {
    const list = PENDING.get(k);
    if (!list || !list.length) continue;
    fs.appendFileSync(path.join(BUCKET_DIR, `${k}.jsonl`), list.map((e) => JSON.stringify(e)).join('\n') + '\n');
    list.length = 0;
  }
}
process.on('exit', () => { try { flush(); } catch { /* ignore */ } });

// Diagnosis (DETJS_PW_DIAG_DIR): the texts behind the digests (response bodies, frames, final DOM),
// one file per test, so that two replays can be diffed where their fingerprints diverge.
const DIAG_DIR = ENV.DETJS_PW_DIAG_DIR || '';
const DIAG_MAX = Number(ENV.DETJS_PW_DIAG_MAX || 4000);
function diag(key, op, target, data, max = DIAG_MAX) {
  if (!DIAG_DIR || !key) return;
  try {
    let text = data === undefined || data === null ? '' : Buffer.isBuffer(data) ? data.toString('utf8') : String(data);
    if (text.length > max) text = `${text.slice(0, max)}...[${text.length}]`;
    const name = testIdOf(key).replace(/[^A-Za-z0-9._-]+/g, '_').slice(-180);
    fs.mkdirSync(DIAG_DIR, { recursive: true });
    fs.appendFileSync(path.join(DIAG_DIR, `${name}.jsonl`), `${JSON.stringify({ t: Date.now() - T_START, op, target, text })}\n`);
  } catch { /* diagnosis never breaks a run */ }
}

function digest(data) {
  if (data === undefined || data === null) return '-';
  return native.digest(Buffer.isBuffer(data) ? data : Buffer.from(String(data)));
}

// ------------------------------------------------------- network queue
// One queue per worker process (workers are serialized: one process runs at a time).
const QUEUE = { pending: [], busy: false, timer: null, decisions: new Map() };

function keyOf(item) {
  return `${item.kind} ${item.method} ${item.target} ${item.bodyDigest}`;
}

function schedule() {
  if (QUEUE.busy || QUEUE.timer || !QUEUE.pending.length) return;
  QUEUE.timer = setTimeout(pump, WINDOW_MS);
}

// Navigations requested by the test code (page.goto, reload, ...) reach the queue only after a
// round trip through the browser; a runner API request issued just before would be chosen alone
// or together with the document depending on that latency (found on the fixture's "runner write
// vs browser read"). The queue waits until every navigation the test started has either reached
// it as a document request or finished without one.
const NAV = { pending: [], maxWait: Number(ENV.DETJS_PW_NAV_WAIT || 3000) };
function navStarted() {
  const n = { open: true };
  NAV.pending.push(n);
  return () => navClaim(n);
}
function navClaim(n) {
  const x = n || NAV.pending[0];
  if (!x || !x.open) return;
  x.open = false;
  NAV.pending.splice(NAV.pending.indexOf(x), 1);
  if (QUEUE.pending.length) { if (QUEUE.timer) { clearTimeout(QUEUE.timer); QUEUE.timer = null; } schedule(); }
}
async function navSettled() {
  const t = Date.now();
  while (NAV.pending.length && Date.now() - t < NAV.maxWait) await new Promise((r) => setTimeout(r, 2));
}
// Page.goto delegates to its main frame's goto: Frame gets goto, Page the page-level ones.
const NAV_METHODS = { frame: ['goto'], page: ['reload', 'goBack', 'goForward'] };
function patchNavigation(obj, kind) {
  const proto = obj && Object.getPrototypeOf(obj);
  if (!proto || Object.prototype.hasOwnProperty.call(proto, '__detjsNav')) return;
  Object.defineProperty(proto, '__detjsNav', { value: true });
  for (const m of NAV_METHODS[kind]) {
    const orig = proto[m];
    if (typeof orig !== 'function') continue;
    proto[m] = function (...args) {
      if (!NET || !currentKey()) return orig.apply(this, args);
      const done = navStarted();
      let p;
      try { p = orig.apply(this, args); } catch (e) { done(); throw e; }
      Promise.resolve(p).then(done, done);
      return p;
    };
  }
}

function enqueue(item) {
  return new Promise((resolve) => {
    item.release = resolve;
    QUEUE.pending.push(item);
    if (item.nav) navClaim();
    if (item.nav && VT.waiters.length) { const w = VT.waiters; VT.waiters = []; for (const f of w) f(); }
    if (QUEUE.timer) { clearTimeout(QUEUE.timer); QUEUE.timer = null; }
    schedule();
  });
}

const QUIET_MS = Number(ENV.DETJS_PW_QUIET_MS || 20);
const QUIET_MAX = Number(ENV.DETJS_PW_QUIET_MAX || 3000);
const PASSTHROUGH = new RegExp(ENV.DETJS_PW_PASSTHROUGH || '[?&]transport=polling|/sockjs/|/__vite_ping|/@vite/|hot-update');

function serverQuiet(origin) {
  return new Promise((resolve) => {
    let u;
    try { u = new URL(`/__detjs/quiet?ms=${QUIET_MS}&max=${QUIET_MAX}`, origin); } catch { resolve(null); return; }
    const req = http.get(u, { timeout: QUIET_MAX + 2000 }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => { try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); } catch { resolve(null); } });
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
  });
}

/** Wait until every app server touched so far has finished the work of earlier messages. */
async function barrier(test) {
  if (!QUIET_MS) return;
  for (const origin of [...ORIGINS].sort()) {
    const r = await serverQuiet(origin);
    if (r && !r.quiet) rec(test, 'sched', 'server.busy', origin); // still busy after QUIET_MAX: recorded
  }
}

async function pump() {
  QUEUE.timer = null;
  if (QUEUE.busy || !QUEUE.pending.length) return;
  QUEUE.busy = true;
  // Never deliver a response while a page is inside a virtual time chunk, except a main-frame
  // navigation: Chrome suspends the page's DevTools session while its navigation request is
  // pending, so the chunk cannot end before the document arrives (deadlock: found on a first
  // page.goto issued right after a grant). The new document starts at the page's virtual instant.
  await navSettled();
  if (!QUEUE.pending.some((it) => it.nav)) await whenPaused();
  await barrier(QUEUE.pending[0].test);
  QUEUE.busy = false;
  if (!QUEUE.pending.length) return;
  // Sort the pending set by a stable key (repeated keys keep arrival order: same URL twice
  // is the same choice either way), then choose: index 0 without a seed, a seeded index with one.
  // Frames of one WebSocket keep their order: only the oldest pending frame of a connection is eligible.
  const head = new Map();
  for (const it of QUEUE.pending) if (it.conn !== undefined && !head.has(it.conn)) head.set(it.conn, it);
  const eligible = QUEUE.pending.filter((it) => it.conn === undefined || head.get(it.conn) === it);
  const sorted = eligible.map((it, i) => ({ it, i, k: keyOf(it) }))
    .sort((a, b) => (a.k < b.k ? -1 : a.k > b.k ? 1 : a.i - b.i));
  const testKey = sorted[0].it.test || '<none>';
  const n = sorted.length;
  const d = (QUEUE.decisions.get(testKey) || 0) + 1;
  QUEUE.decisions.set(testKey, d);
  let idx = 0;
  if (SHUFFLE && n > 1) idx = native.shuffleIndices(n, SEED, `${testKey}\0net\0${d}`)[0];
  const chosen = sorted[idx].it;
  QUEUE.pending.splice(QUEUE.pending.indexOf(chosen), 1);
  rec(chosen.test, 'sched', 'sched.io', `${idx}/${n}:${keyOf(chosen)}`);
  diag(chosen.test, 'sched.io', keyOf(chosen), sorted.map((x) => x.k).join('\n'));
  dbg('release', keyOf(chosen));
  QUEUE.busy = true;
  const done = () => {
    QUEUE.busy = false;
    schedule();
  };
  chosen.release(done);
}

function targetOf(url) {
  try {
    const u = new URL(url);
    return `${u.protocol}//${u.host}${u.pathname}${u.search}`;
  } catch { return String(url); }
}
function isServerHost(url) {
  try { return SERVER_HOSTS.has(new URL(url).hostname); } catch { return false; }
}

// ----------------------------------------------------- app servers
const ORIGINS = new Set(); // origins that received a bracket header

function serverEnd(origin) {
  return new Promise((resolve) => {
    let u;
    try { u = new URL('/__detjs/end', origin); } catch { resolve(null); return; }
    const req = http.get(u, { timeout: 3000 }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); } catch { resolve(null); }
      });
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
  });
}

// ----------------------------------------------------- browser contexts
const CONTEXTS = new WeakSet();

async function routeHandler(route, request) {
  const key = currentKey();
  const url = request.url();
  const type = request.resourceType();
  if (!key || !APP_TYPES.has(type) || !/^https?:/.test(url)) {
    return route.fallback();
  }
  if (PASSTHROUGH.test(url) || /text\/event-stream/.test(request.headers().accept || '')) {
    // Long-lived requests (long polling, event streams, dev-server pings) would hold the
    // queue: not ordered, not recorded; they still carry the test bracket.
    if (!isServerHost(url)) return route.fallback();
    return route.fallback({ headers: { ...request.headers(), 'x-detjs-test': testIdOf(key) } });
  }
  let nav = false;
  try { nav = type === 'document' && request.isNavigationRequest() && request.frame().parentFrame() === null; } catch { nav = false; }
  const item = { kind: 'browser', test: key, method: request.method(), target: targetOf(url), bodyDigest: digest(request.postDataBuffer()), nav };
  const release = await enqueue(item);
  const page = request.frame && (() => { try { return request.frame().page(); } catch { return null; } })();
  let finished = false;
  const finish = (how) => {
    if (finished) return;
    finished = true;
    if (page) { page.off('requestfinished', onDone); page.off('requestfailed', onFail); page.off('response', onResponse); }
    clearTimeout(timer);
    rec(key, 'net', 'browser.done', `${item.method} ${item.target} ${how}`);
    dbg('done', item.target, how);
    release();
  };
  const onDone = async (r) => {
    if (r !== request) return;
    let how = 'finished';
    try {
      const resp = await r.response();
      if (resp) {
        let body = '-';
        try { const buf = await resp.body(); body = digest(buf); diag(key, 'browser.body', `${item.method} ${item.target} ${resp.status()}`, buf); } catch { body = 'nobody'; }
        how = `${resp.status()} ${body}`;
      }
    } catch { /* ignore */ }
    finish(how);
  };
  const onFail = (r) => { if (r === request) finish(`failed ${r.failure() ? r.failure().errorText : ''}`); };
  const timer = setTimeout(() => finish('incomplete'), COMPLETE_TIMEOUT_MS);
  // A document's body is consumed by the page's loader, which waits for virtual time:
  // its response headers complete it (the final DOM digest covers its content).
  const onResponse = (resp) => { if (resp.request() === request) finish(`${resp.status()} document`); };
  if (type === 'document' && page) { page.on('response', onResponse); page.on('requestfailed', onFail); }
  else if (page) { page.on('requestfinished', onDone); page.on('requestfailed', onFail); }
  rec(key, 'net', 'browser.request', `${item.method} ${item.target} ${item.bodyDigest}`);
  try {
    if (isServerHost(url)) {
      ORIGINS.add(new URL(url).origin);
      await route.fallback({ headers: { ...request.headers(), 'x-detjs-test': testIdOf(key) } });
    } else {
      await route.fallback();
    }
  } catch (e) {
    finish(`route-error ${e && e.message}`);
  }
  if (!page) finish('nopage');
}

// Readable test ids for the server bracket (the server part uses them as node ids).
const READABLE = new Map();
function testIdOf(key) {
  return READABLE.get(key) || key;
}
function rememberTest() {
  const ti = testInfo();
  if (!ti) return null;
  if (!READABLE.has(ti.testId)) {
    const file = path.relative(ROOT, ti.file).split(path.sep).join('/');
    READABLE.set(ti.testId, `${file}::${ti.titlePath.slice(1).join('::')}${ti.project && ti.project.name ? ` [${ti.project.name}]` : ''}`);
  }
  return ti.testId;
}

function wsKeep(text) {
  // engine.io heartbeats ("2" ping / "3" pong, optionally "2probe") depend on real time: not fingerprinted.
  return !(typeof text === 'string' && /^[23](probe)?$/.test(text));
}

let WS_CONNS = 0;
async function setupWebSockets(ctx) {
  if (typeof ctx.routeWebSocket !== 'function') return;
  await ctx.routeWebSocket(() => true, (ws) => {
    const key = currentKey();
    let server;
    try { server = ws.connectToServer(); } catch { return; }
    const conn = ++WS_CONNS;
    rec(key, 'net', 'ws.open', targetOf(ws.url()));
    ws.onMessage((m) => {
      const k = currentKey() || key;
      if (!wsKeep(m) || !k) { server.send(m); return; }
      // Page -> server frames are messages to the app like requests: same queue, same barrier.
      enqueue({ kind: 'ws', conn, test: k, method: 'SEND', target: targetOf(ws.url()), bodyDigest: digest(m) }).then((release) => {
        rec(k, 'net', 'ws.send', digest(m));
        diag(k, 'ws.send', targetOf(ws.url()), m, 1500);
        try { server.send(m); } finally { release(); }
      });
    });
    server.onMessage((m) => {
      if (wsKeep(m)) { rec(currentKey() || key, 'net', 'ws.recv', digest(m)); diag(currentKey() || key, 'ws.recv', targetOf(ws.url()), m, 1500); }
      ws.send(m);
    });
    ws.onClose((code, reason) => { try { server.close({ code, reason }); } catch { /* closed */ } });
    server.onClose((code, reason) => { try { ws.close({ code, reason }); } catch { /* closed */ } });
  });
}

// Virtual time is granted in small chunks (policy `advance` with a budget):
// the page runs its timers, animations and rendering through one chunk, then
// stops until the next grant. Between chunks the driver lets the requests
// issued during the chunk reach the queue (SETTLE_MS) and runs the queue to
// completion before the next grant, and the queue releases requests only
// while no page is inside a chunk: responses always land between two chunks,
// at the same virtual instant in every run. (Chrome's own
// pauseIfNetworkFetchesPending policy freezes the page for as long as any
// request is open, so long polling apps stop: socket.io, found on uptime-kuma.)
// paced: virtual time never runs ahead of real time (the app server and
// WebSocket peers live in real time); fast: idle time is skipped.
const CHUNK_MS = Number(ENV.DETJS_PW_VTIME_CHUNK || 20);
const SETTLE_MS = Number(ENV.DETJS_PW_VTIME_SETTLE || 10);
const VT = { running: 0, waiters: [] };
function whenPaused() {
  return VT.running === 0 ? Promise.resolve() : new Promise((r) => VT.waiters.push(r));
}
function chunkEnded() {
  VT.running = Math.max(0, VT.running - 1);
  if (VT.running === 0) { const w = VT.waiters; VT.waiters = []; for (const f of w) f(); }
}
function queueIdle() {
  return !QUEUE.busy && !QUEUE.pending.length && !QUEUE.timer;
}
async function whenQueueIdle() {
  while (!queueIdle()) await new Promise((r) => setTimeout(r, 2));
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function setupPage(ctx, page, key) {
  if (VTIME === 'off') return;
  let cdp;
  try { cdp = await ctx.newCDPSession(page); } catch { rec(key, 'other', 'vtime', 'unsupported'); return; }
  const started = Date.now();
  let granted = 0;
  let stopped = false;
  let inChunk = false;
  const end = () => { if (inChunk) { inChunk = false; chunkEnded(); } };
  const grant = async (first) => {
    if (stopped) return;
    if (!first) {
      await sleep(SETTLE_MS);
      await whenQueueIdle();
    }
    if (granted >= VCAP_MS) { rec(currentKey() || key, 'time', 'vtime.cap', String(granted)); return; }
    if (VTIME === 'paced') {
      const ahead = granted - (Date.now() - started);
      if (ahead > 0) await sleep(ahead);
      await whenQueueIdle();
    }
    if (stopped) return;
    granted += CHUNK_MS;
    const params = { policy: 'advance', budget: CHUNK_MS };
    if (first) params.initialVirtualTime = EPOCH_MS / 1000;
    inChunk = true;
    VT.running++;
    dbg('grant', granted, first ? 'first' : '');
    try { await cdp.send('Emulation.setVirtualTimePolicy', params); } catch { stopped = true; end(); }
  };
  cdp.on('Emulation.virtualTimeBudgetExpired', () => {
    if (!inChunk) return; // a chunk already ended by a stall
    dbg('expired', granted);
    end();
    grant(false).catch(() => {});
  });
  if (DEBUG) {
    page.on('framenavigated', (f) => dbg('framenavigated', f === page.mainFrame() ? 'main' : 'sub', f.url()));
    page.on('requestfailed', (r) => dbg('requestfailed', r.url(), r.failure() && r.failure().errorText));
    page.on('crash', () => dbg('crash'));
    page.on('request', (r) => dbg('request', r.resourceType(), r.url()));
  }
  page.on('close', () => { stopped = true; end(); });
  await grant(true);
}

async function setupContext(ctx) {
  if (CONTEXTS.has(ctx)) return;
  CONTEXTS.add(ctx);
  const key = rememberTest();
  if (seedsInstalled) maybeReseed();
  const seedKey = key ? testIdOf(key) : '<outside>';
  if (SEEDS) {
    const [hi, lo] = native.deriveSeedWords(SEED, `${seedKey}\0page`);
    await ctx.addInitScript({ content: pageInitSource(hi, lo) });
  }
  if (NET) {
    await ctx.route(() => true, routeHandler);
    await setupWebSockets(ctx);
    patchApiRequest(ctx.request);
  }
  // Virtual time must be on before the first navigation: newPage() waits for it; pages the
  // app opens itself (popups) get it as soon as the 'page' event is handled (limit B5).
  const ready = new WeakMap();
  const prepare = (page) => {
    patchNavigation(page, 'page');
    try { patchNavigation(page.mainFrame(), 'frame'); } catch { /* closed */ }
    if (!ready.has(page)) ready.set(page, setupPage(ctx, page, currentKey() || key).catch(() => {}));
    return ready.get(page);
  };
  ctx.on('page', (page) => { prepare(page); });
  for (const p of ctx.pages()) await prepare(p);
  const origNewPage = ctx.newPage;
  ctx.newPage = async function newPage(...args) {
    const page = await origNewPage.apply(this, args);
    await prepare(page);
    return page;
  };
  const origClose = ctx.close;
  ctx.close = async function close(...args) {
    await finishContext(ctx).catch(() => {});
    return origClose.apply(this, args);
  };
}

async function finishContext(ctx) {
  const key = currentKey();
  if (!key) return;
  for (const page of ctx.pages()) {
    try {
      const res = await Promise.race([
        page.evaluate(() => ({
          stats: window.__detjs ? window.__detjs.stats() : null,
          dom: document.documentElement ? document.documentElement.outerHTML : '',
        })),
        new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), 2000)),
      ]);
      if (res.stats) rec(key, 'random', 'page.random', `${res.stats.random}/${res.stats.crypto}/${res.stats.uuid}:${res.stats.digest}`);
      rec(key, 'other', 'dom.digest', digest(res.dom));
      diag(key, 'dom', page.url(), res.dom, 400000);
      if (res.stats) diag(key, 'page.random', page.url(), JSON.stringify(res.stats));
    } catch (e) {
      rec(key, 'other', 'dom.digest', 'unavailable');
    }
  }
  await serverFingerprints(key);
  flush(key);
}

async function serverFingerprints(key) {
  for (const origin of [...ORIGINS].sort()) {
    const res = await serverEnd(origin);
    if (!res || !res.finished) continue;
    const mine = res.finished[testIdOf(key)];
    if (mine) rec(key, 'other', 'server.fingerprint', `${origin} ${mine.fingerprint} ${mine.events}`);
  }
}

// -------------------------------------------------- runner API requests
let apiPatched = false;
function patchApiRequest(reqCtx) {
  if (apiPatched || !reqCtx) return;
  const proto = Object.getPrototypeOf(reqCtx);
  if (!proto || typeof proto.fetch !== 'function') return;
  apiPatched = true;
  const origFetch = proto.fetch;
  proto.fetch = async function fetch(urlOrRequest, options = {}) {
    const key = currentKey();
    if (!key || !NET) return origFetch.call(this, urlOrRequest, options);
    const url = typeof urlOrRequest === 'string' ? urlOrRequest : (urlOrRequest && urlOrRequest.url && urlOrRequest.url()) || '';
    let abs = url;
    const ti = testInfo();
    const base = (this._options && this._options.baseURL) || (ti && ti.project && ti.project.use && ti.project.use.baseURL) || undefined;
    try { abs = new URL(url, base).toString(); } catch { /* relative without base */ }
    const method = (options.method || (typeof urlOrRequest === 'object' && urlOrRequest.method && urlOrRequest.method()) || 'GET').toUpperCase();
    const body = options.data !== undefined ? (typeof options.data === 'string' || Buffer.isBuffer(options.data) ? options.data : JSON.stringify(options.data)) : options.form ? JSON.stringify(options.form) : undefined;
    const item = { kind: 'api', test: key, method, target: targetOf(abs), bodyDigest: digest(body) };
    const release = await enqueue(item);
    rec(key, 'net', 'api.request', `${method} ${item.target} ${item.bodyDigest}`);
    let opts = options;
    if (isServerHost(abs)) {
      ORIGINS.add(new URL(abs).origin);
      opts = { ...options, headers: { ...(options.headers || {}), 'x-detjs-test': testIdOf(key) } };
    }
    try {
      const resp = await origFetch.call(this, urlOrRequest, opts);
      let b = '-';
      try { const buf = await resp.body(); b = digest(buf); diag(key, 'api.body', `${method} ${item.target} ${resp.status()}`, buf); } catch { b = 'nobody'; }
      rec(key, 'net', 'api.done', `${method} ${item.target} ${resp.status()} ${b}`);
      return resp;
    } catch (e) {
      rec(key, 'net', 'api.done', `${method} ${item.target} error`);
      throw e;
    } finally {
      release();
    }
  };
}

// ------------------------------------------- seeds of the test code itself
// Test code draws random names (pads, users, e-mails) with Math.random or
// crypto.randomUUID: the worker's own generators are seeded per test.
let seedsInstalled = false;
let lastSeeded = null;
function installWorkerSeeds() {
  if (!SEEDS || seedsInstalled) return;
  const config = require('../config');
  const { STATE } = require('../state');
  const seeds = require('../seeds');
  const { Patcher } = require('../patch');
  if (!STATE.config) STATE.config = { ...config.fromEnv(), urandom: false };
  const patcher = new Patcher();
  seeds.installProcess(patcher, STATE.config);
  seeds.installRealm(patcher, globalThis, STATE.config, { sameRealm: true });
  seeds.seedFile(`playwright-worker`);
  const rnd = Math.random;
  Math.random = function random() { maybeReseed(); return rnd(); };
  seedsInstalled = true;
  installWorkerSeeds.reseed = (id) => seeds.reseed(id);
}
function maybeReseed() {
  const key = currentKey();
  if (key && key !== lastSeeded) {
    lastSeeded = key;
    rememberTest();
    installWorkerSeeds.reseed(testIdOf(key));
  }
}
installWorkerSeeds();

// ------------------------------------------------- Playwright hooks
const EXECUTABLE = ENV.DETJS_PW_EXECUTABLE || '';

function patchBrowser(browser) {
  const proto = Object.getPrototypeOf(browser);
  if (!proto || proto.__detjsPatched) return;
  Object.defineProperty(proto, '__detjsPatched', { value: true });
  const origNewContext = proto.newContext;
  proto.newContext = async function newContext(...args) {
    const ctx = await origNewContext.apply(this, args);
    await setupContext(ctx);
    return ctx;
  };
}

function patchBrowserType(bt) {
  const proto = Object.getPrototypeOf(bt);
  if (!proto || proto.__detjsPatched) return;
  Object.defineProperty(proto, '__detjsPatched', { value: true });
  const origLaunch = proto.launch;
  proto.launch = async function launch(options = {}) {
    const opts = EXECUTABLE && this.name() === 'chromium' ? { ...options, executablePath: EXECUTABLE } : options;
    const browser = await origLaunch.call(this, opts);
    patchBrowser(browser);
    return browser;
  };
  for (const m of ['connect', 'connectOverCDP']) {
    const orig = proto[m];
    if (typeof orig !== 'function') continue;
    proto[m] = async function (...args) {
      const browser = await orig.apply(this, args);
      patchBrowser(browser);
      return browser;
    };
  }
  const origPersistent = proto.launchPersistentContext;
  if (typeof origPersistent === 'function') {
    proto.launchPersistentContext = async function (...args) {
      const ctx = await origPersistent.apply(this, args);
      await setupContext(ctx);
      return ctx;
    };
  }
}

let corePatched = false;
const origLoad = Module._load;
Module._load = function load(request, parent, isMain) {
  const exp = origLoad.apply(this, arguments);
  try {
    if (!PW_TEST && exp && exp.test && typeof exp.test.info === 'function' && /playwright/.test(request)) PW_TEST = exp;
    if (!corePatched && exp && exp.chromium && typeof exp.chromium.launch === 'function' && /playwright/.test(request)) {
      corePatched = true;
      patchBrowserType(exp.chromium);
    }
  } catch { /* never break module loading */ }
  return exp;
};

module.exports = { setupContext, flush, _queue: QUEUE };
