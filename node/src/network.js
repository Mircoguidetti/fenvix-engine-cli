'use strict';
// Closed network with optional record/replay, and the bytes of every connection in the fingerprint.
//
// * Connections (`net.Socket#connect`, hence `net.connect`, `http`, `https`, `http2`, `tls.connect`, global `fetch`
//   and `undici`) and DNS lookups (`dns.lookup`, `dns.resolve*`, `dns.promises.*`) towards non-local hosts fail with
//   `NetworkBlockedError` (code ECONNREFUSED; ENOTFOUND for DNS). Loopback, Unix sockets and hosts given with
//   `--det-allow-host` are allowed. Local HTTP(S) proxies from the `*_PROXY` variables count as external.
// * `--det-record`: external connections are allowed and their byte streams are recorded into the cassette
//   (plaintext above TLS, recorded at the `tls.connect` level), shared format with the Python shell: per test, and
//   for connections made outside a test body under `<file>::<setup>` (module level, beforeAll, afterAll) or
//   `<startup>` (globalSetup, in the runner's main process) (audit G-1419). Each recorded connection also carries its
//   recording time (`recorded_at`) and its negotiated ALPN protocol (`alpn`): extra fields the Rust core ignores.
// * When a cassette exists and `--det-record` is not given, recorded connections are replayed: the socket is
//   transparently connected to a local Unix socket served by a replay server that plays the recorded conversation
//   (a TLS server with a certificate generated per process, negotiating the recorded ALPN protocol, `h2` included;
//   certificate checks are disabled for that socket only). `--det-cassette-max-age=D` refuses recordings older than D
//   days (G-1418, G-1420, G-2165).
// * Every connection of a test that Level 0 lets through (loopback and Unix sockets, allowed hosts, recorded and
//   replayed ones) is an event: `net.connect` when it opens and, when the test ends, `net.stream` with the length and
//   digest of each direction of what the test exchanged on it (plaintext above TLS; loopback ports from the
//   ephemeral range normalised), so a different answer is a different fingerprint (G-1415, G-1416, G-1417).
//   Connections outside test bodies are summarised in a `net.setup` event at the start of every later test.

const net = require('node:net');
const tls = require('node:tls');
const dns = require('node:dns');
const os = require('node:os');
const path = require('node:path');
const fs = require('node:fs');
const nodeCrypto = require('node:crypto');
const native = require('./native');
const sites = require('./sites');
const { STATE } = require('./state');

const real = {
  connect: net.Socket.prototype.connect,
  tlsConnect: tls.connect,
  lookup: dns.lookup,
  pLookup: dns.promises.lookup,
  Date: globalThis.Date,
};
const RESOLVE_FNS = ['resolve', 'resolve4', 'resolve6', 'resolveAny', 'resolveCname', 'resolveMx', 'resolveNs',
  'resolveTxt', 'resolveSrv', 'resolvePtr', 'resolveNaptr', 'resolveSoa', 'resolveCaa'];
const DAY_MS = 86400000;
const PID = process.pid; // read once here: a test's reads of process.pid are events (src/facts.js)

class NetworkBlockedError extends Error {
  constructor(what, code = 'ECONNREFUSED', why = null) {
    const hint = why || (POLICY && POLICY.mode === 'replay'
      ? 'no recording for it in this test: re-run with --det-record'
      : 'use --det-record to record real responses, or --det-allow-host to allow it');
    super(`detjs: network access to ${what} blocked (Level 0 closes the network; localhost is allowed); ${hint}`);
    this.name = 'NetworkBlockedError';
    this.code = code;
    this.errno = code === 'ENOTFOUND' ? -3008 : -111;
    this.syscall = code === 'ENOTFOUND' ? 'getaddrinfo' : 'connect';
    this.detjs = true;
  }
}

const LOCAL_NAMES = new Set(['localhost', 'localhost.localdomain', 'ip6-localhost', 'ip6-loopback', '']);

function isLocalName(host) {
  const h = String(host).toLowerCase().replace(/\.$/, '').replace(/^\[|\]$/g, '');
  if (LOCAL_NAMES.has(h) || h.endsWith('.localhost')) return true;
  const kind = net.isIP(h.split('%')[0]);
  if (kind === 4) return h.startsWith('127.') || h === '0.0.0.0';
  if (kind === 6) return h === '::1' || h === '::' || /^::ffff:127\./.test(h) || /^0*:(0*:)*0*1$/.test(h);
  return false;
}

function proxyEndpoints() {
  const out = new Set();
  for (const v of ['http_proxy', 'https_proxy', 'all_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']) {
    const val = process.env[v];
    if (!val) continue;
    let u;
    try { u = new URL(val.includes('://') ? val : `http://${val}`); } catch { continue; }
    const port = Number(u.port) || ({ 'https:': 443, 'socks5:': 1080, 'socks5h:': 1080 }[u.protocol] || 80);
    const host = u.hostname.toLowerCase().replace(/^\[|\]$/g, '');
    if (host && isLocalName(host)) for (const h of [host, '127.0.0.1', '::1', 'localhost']) out.add(`${h}:${port}`);
  }
  return out;
}

// Cassette file (JSON): the Rust core reads and writes the conversations; detjs adds per connection `recorded_at`
// (ISO time of the recording) and `alpn` (negotiated ALPN protocol, false when none), which the core ignores.
function readCassetteJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return null; }
}

/** Staleness of a cassette: { total, unknown, oldest: {key, days} | null, stale: [keys] } for `maxAgeDays`. */
function cassetteAges(file, maxAgeDays = 0, now = real.Date.now()) {
  const j = readCassetteJson(file);
  const out = { total: 0, unknown: 0, oldest: null, stale: [] };
  if (!j || !j.tests) return out;
  for (const key of Object.keys(j.tests).sort()) {
    let staleKey = false;
    for (const c of j.tests[key] || []) {
      out.total++;
      const t = c && typeof c.recorded_at === 'string' ? Date.parse(c.recorded_at) : NaN;
      if (Number.isNaN(t)) { out.unknown++; if (maxAgeDays > 0) staleKey = true; continue; }
      const days = (now - t) / DAY_MS;
      if (!out.oldest || days > out.oldest.days) out.oldest = { key, days };
      if (maxAgeDays > 0 && days > maxAgeDays) staleKey = true;
    }
    if (staleKey) out.stale.push(key);
  }
  return out;
}

class Policy {
  constructor(cfg) {
    this.mode = cfg.netMode; // block | record | replay
    this.allow = new Set(cfg.allowHosts);
    this.proxies = proxyEndpoints();
    this.cassettePath = cfg.cassette;
    this.maxAgeDays = Number(cfg.cassetteMaxAge) || 0;
    this.recording = this.mode === 'record' ? new native.Cassette() : null;
    this.recMeta = new Map(); // key -> [{recorded_at, alpn}] by connection index (record mode)
    this.source = null;
    this.srcMeta = null; // tests of the cassette file as JSON (replay mode): recorded_at, alpn
    if (this.mode === 'replay' && this.cassettePath && fs.existsSync(this.cassettePath)) {
      this.source = native.Cassette.load(this.cassettePath);
      const j = readCassetteJson(this.cassettePath);
      this.srcMeta = (j && j.tests) || {};
    } else if (this.mode === 'replay') {
      this.mode = 'block';
    }
    this.hostOfIp = new Map();
    this.fakeIpOf = new Map();
    this.hostOfFake = new Map();
    this.counters = new Map(); // key -> Map(host:port -> n)
    this.recordedTests = new Set();
    this.testSockets = new Set();
  }

  startTest(id) {
    this.counters.delete(id);
  }

  /**
   * Recorded and replayed connections belong to the test that opened them: when it ends they are closed, so that a
   * keep-alive agent opens a new one for the next test, which is then recorded under that test (audit G-0129:
   * a later test's request travelled on the first test's connection and was stored under the first test, so the
   * later test could not be replayed alone or in another order).
   */
  endTest() {
    for (const s of this.testSockets) {
      try { if (!s.destroyed) s.destroy(); } catch { /* ignore */ }
    }
    this.testSockets.clear();
  }

  hostname(host) {
    return this.hostOfFake.get(host) || this.hostOfIp.get(host) || host;
  }

  external(host, port) {
    if (this.proxies.has(`${String(host).toLowerCase()}:${port}`)) return true;
    if (isLocalName(host)) return false;
    return !this.allow.has(this.hostname(host).toLowerCase());
  }

  hasRecording(host) {
    if (!this.source) return false;
    const key = currentKey();
    const n = this.source.count(key);
    for (let i = 0; i < n; i++) if (this.source.info(key, i).host === host) return true;
    return false;
  }

  nth(key, host, port) {
    let m = this.counters.get(key);
    if (!m) { m = new Map(); this.counters.set(key, m); }
    const k = `${host}:${port}`;
    const n = m.get(k) || 0;
    m.set(k, n + 1);
    return n;
  }

  meta(key, idx) {
    const conns = this.srcMeta && this.srcMeta[key];
    return (conns && conns[idx]) || {};
  }

  fakeIp(host) {
    let ip = this.fakeIpOf.get(host);
    if (!ip) {
      const n = this.fakeIpOf.size + 1;
      ip = `198.18.${Math.floor(n / 250)}.${(n % 250) + 1}`; // RFC 2544 benchmarking range
      this.fakeIpOf.set(host, ip);
      this.hostOfFake.set(ip, host);
    }
    return ip;
  }
}

let POLICY = null;
let inTlsConnect = 0;
let MAIN = false; // the runner's main process (globalSetup): only external connections are recorded or replayed

// Where a connection belongs: the running test, else the current test file's set-up, else the start-up.
let FILE_KEY = null;
const STARTUP_KEY = '<startup>';
function currentKey() {
  if (STATE.testId !== null) return STATE.testId;
  return FILE_KEY || STARTUP_KEY;
}

// Byte streams in the fingerprint (G-1415, G-1416, G-1417) ------------------------------------------------------
// Each tracked connection keeps, per owner (the test, or the set-up / start-up key, running when the bytes flowed),
// a running SHA-256 of each direction. Loopback ports from the ephemeral range (listen(0)) change from run to run
// and appear in the bytes (`Host: 127.0.0.1:41234`): they are replaced by `<port>` in what is digested.
const EPHEMERAL_MIN = 32768;
const BUCKETS = new Map(); // owner key -> { list: [entry] }
let STARTUP_FILE = null; // main process: where the start-up summary is published for the test processes
let STARTUP_SUMMARY = ''; // test processes: the start-up summary read at each file start
let streamSerial = 0;

function bucketOf(key) {
  let b = BUCKETS.get(key);
  if (!b) { b = { list: [] }; BUCKETS.set(key, b); }
  return b;
}

function newDir() { return { h: nodeCrypto.createHash('sha256'), n: 0 }; }

/**
 * Client WebSocket frames carry a random 4-byte mask (RFC 6455) drawn from a pool that implementations refill now and
 * then: the same message has other bytes in another order of tests. What is digested, recorded and compared in replay
 * is the client stream with every frame unmasked and its mask key zeroed (same length). Streams that do not start with
 * an HTTP request upgrading to WebSocket pass through unchanged.
 */
class WsNormalizer {
  constructor() {
    this.mode = 'http';
    this.head = '';
    this.hdr = Buffer.alloc(0);
    this.left = 0; // payload bytes left in the current frame
    this.mask = null;
    this.off = 0;
  }

  push(chunk) {
    if (this.mode === 'other' || !chunk.length) return chunk;
    if (this.mode === 'http') {
      this.head += chunk.toString('latin1');
      const end = this.head.indexOf('\r\n\r\n');
      if (end < 0) {
        if (this.head.length > 16384 || !/^(?:G|GE|GET|GET )/.test(this.head)) { this.mode = 'other'; this.head = ''; }
        return chunk;
      }
      const isWs = /^GET /.test(this.head) && /\r\nupgrade:[ \t]*websocket/i.test(this.head.slice(0, end));
      const after = this.head.length - (end + 4); // bytes of this chunk past the request head
      this.head = '';
      if (!isWs) { this.mode = 'other'; return chunk; }
      this.mode = 'ws';
      if (after <= 0) return chunk;
      return Buffer.concat([chunk.subarray(0, chunk.length - after), this.frames(chunk.subarray(chunk.length - after))]);
    }
    return this.frames(chunk);
  }

  frames(data) {
    const out = [];
    let i = 0;
    while (i < data.length) {
      if (this.left > 0) {
        const n = Math.min(this.left, data.length - i);
        const part = Buffer.from(data.subarray(i, i + n));
        if (this.mask) for (let k = 0; k < n; k++) part[k] ^= this.mask[(this.off + k) & 3];
        this.off += n;
        this.left -= n;
        out.push(part);
        i += n;
        continue;
      }
      // a frame header: 2 bytes, extended length (2 or 8), mask key (4); held until complete
      const before = this.hdr.length;
      const take = data.subarray(i, i + 14 - before);
      this.hdr = Buffer.concat([this.hdr, take]);
      const len7 = this.hdr.length >= 2 ? this.hdr[1] & 0x7f : 0;
      const masked = this.hdr.length >= 2 && (this.hdr[1] & 0x80) !== 0;
      const ext = len7 === 126 ? 2 : len7 === 127 ? 8 : 0;
      const need = 2 + ext + (masked ? 4 : 0);
      if (this.hdr.length < 2 || this.hdr.length < need) { i += take.length; break; }
      i += need - before;
      const h = Buffer.from(this.hdr.subarray(0, need));
      let len = len7;
      if (ext === 2) len = h.readUInt16BE(2);
      else if (ext === 8) len = Number(h.readBigUInt64BE(2));
      this.mask = masked ? Buffer.from(h.subarray(2 + ext, need)) : null;
      if (masked) h.fill(0, 2 + ext, need);
      out.push(h);
      this.hdr = Buffer.alloc(0);
      this.left = len;
      this.off = 0;
    }
    return out.length === 1 ? out[0] : Buffer.concat(out);
  }

  /** Bytes held back (an incomplete frame header), as they are. */
  flush() {
    const h = this.hdr;
    this.hdr = Buffer.alloc(0);
    return h;
  }
}

class Stream {
  constructor(label, site, normPort) {
    this.id = streamSerial++;
    this.label = label;
    this.site = site;
    this.port = normPort ? String(normPort) : null;
    this.portRe = normPort ? new RegExp(`(?<![0-9])${normPort}(?![0-9])`, 'g') : null;
    this.tail = { send: '', recv: '' };
    this.entry = null;
    this.entryKey = null;
    this.frozen = false;
    this.ws = new WsNormalizer();
  }

  entryFor(key) {
    if (this.entry && this.entryKey === key) return this.entry;
    if (this.entry) this.flushTails(this.entry);
    const e = { stream: this, send: newDir(), recv: newDir() };
    bucketOf(key).list.push(e);
    this.entry = e;
    this.entryKey = key;
    return e;
  }

  norm(text) { return this.portRe ? text.replace(this.portRe, '<port>') : text; }

  add(dir, buf) {
    if (this.frozen || !buf || !buf.length) return;
    const e = this.entryFor(currentKey());
    e[dir].n += buf.length;
    this.feed(e[dir], dir, dir === 'send' ? this.ws.push(buf) : buf);
  }

  feed(d, dir, buf) {
    if (!buf.length) return;
    if (!this.portRe) { d.h.update(buf); return; }
    // hold back a trailing run of digits (a port may continue in the next chunk)
    const s = this.tail[dir] + buf.toString('latin1');
    let cut = s.length;
    while (cut > 0 && cut > s.length - 32 && s.charCodeAt(cut - 1) >= 48 && s.charCodeAt(cut - 1) <= 57) cut--;
    this.tail[dir] = s.slice(cut);
    if (cut > 0) d.h.update(this.norm(s.slice(0, cut)), 'latin1');
  }

  flushTails(e) {
    this.feed(e.send, 'send', this.ws.flush());
    for (const dir of ['send', 'recv']) {
      if (this.tail[dir]) { e[dir].h.update(this.norm(this.tail[dir]), 'latin1'); this.tail[dir] = ''; }
    }
  }
}

function entryValue(e) {
  if (e.stream.entry === e) e.stream.flushTails(e);
  const dig = (d) => `${d.n}:${d.h.copy().digest('hex').slice(0, 16)}`;
  return `${e.stream.label} send=${dig(e.send)} recv=${dig(e.recv)}`;
}

/** The test ends: one `net.stream` event per connection it used, in the order of first use. */
function emitTestStreams(id) {
  const b = BUCKETS.get(id);
  if (!b) return;
  BUCKETS.delete(id);
  for (const e of b.list) {
    STATE.recordAt('net', 'net.stream', e.stream.site, entryValue(e));
    if (e.stream.entry === e) { e.stream.entry = null; e.stream.entryKey = null; }
  }
}

function bucketSummary(key) {
  const b = BUCKETS.get(key);
  if (!b || !b.list.length) return '';
  const vals = b.list.map(entryValue);
  return `${vals.length}:${native.digest(Buffer.from(vals.join('\n'))).slice(0, 16)}`;
}

/** A test starts: what the set-up of its file and the start-up exchanged so far is part of its inputs. */
function emitSetup() {
  const file = FILE_KEY ? bucketSummary(FILE_KEY) : '';
  const startup = STARTUP_SUMMARY || bucketSummary(STARTUP_KEY);
  if (file || startup) STATE.recordAt('net', 'net.setup', '<setup>', `file=${file || '-'} startup=${startup || '-'}`);
}

function publishStartup() {
  if (!STARTUP_FILE) return;
  try { fs.writeFileSync(STARTUP_FILE, bucketSummary(STARTUP_KEY)); } catch { /* run directory gone */ }
}

// Socket hooks: one wrapper of `push` (received bytes) and `_writeGeneric` (sent bytes) per socket, shared by the
// cassette recording and the stream digests.
const HOOKS = Symbol('detjs.netHooks');
const TRACKED = Symbol('detjs.netStream');
function toBuf(chunk, enc) {
  if (Buffer.isBuffer(chunk)) return chunk;
  if (ArrayBuffer.isView(chunk)) return Buffer.from(chunk.buffer, chunk.byteOffset, chunk.byteLength);
  return Buffer.from(String(chunk), typeof enc === 'string' && enc !== 'buffer' ? enc : 'utf8');
}

function hooks(sock) {
  if (sock[HOOKS]) return sock[HOOKS];
  const h = { send: [], recv: [] };
  Object.defineProperty(sock, HOOKS, { value: h });
  const origPush = sock.push;
  sock.push = function push(chunk, enc) {
    if (chunk !== null && chunk !== undefined && chunk.length) {
      const b = toBuf(chunk, enc);
      for (const f of h.recv) f(b);
    }
    return origPush.call(this, chunk, enc);
  };
  const origWrite = sock._writeGeneric;
  sock._writeGeneric = function _writeGeneric(writev, data, encoding, cb) {
    if (!this.connecting) {
      const each = (b) => { if (b.length) for (const f of h.send) f(b); };
      if (writev) {
        for (const c of data) each(toBuf(c && c.chunk !== undefined ? c.chunk : c, c && c.encoding));
      } else {
        each(toBuf(data, encoding));
      }
    }
    return origWrite.call(this, writev, data, encoding, cb);
  };
  // HTTP/2 sessions read and write a stream-base handle natively, below `push` and `_writeGeneric`: for http2 the
  // handle reports that it is not one, so the session runs over the socket's JavaScript stream instead (G-1420).
  // Only http2 is told so (TLS asserts the property on the handles it wraps).
  const handle = sock._handle;
  if (handle && !Object.prototype.hasOwnProperty.call(handle, 'isStreamBase')) {
    try {
      Object.defineProperty(handle, 'isStreamBase', {
        configurable: true,
        get() {
          const lim = Error.stackTraceLimit;
          Error.stackTraceLimit = 4;
          let st;
          try { st = new Error().stack || ''; } finally { Error.stackTraceLimit = lim; }
          if (!st.includes('internal/http2/core')) return true;
          patchJsStreamSocket();
          return false;
        },
      });
    } catch { /* keep the native path */ }
  }
  return h;
}

/**
 * The JavaScript stream http2 then wraps the socket in (`JSStreamSocket`) reports what the socket is: encrypted, its
 * ALPN protocol, and for a TLS socket still in its handshake a pending connection whose 'connect' is the socket's
 * 'secureConnect' (so the session is set up once the protocol is negotiated, as over a native TLS handle).
 */
let JSS_PATCHED = false;
function patchJsStreamSocket() {
  if (JSS_PATCHED) return;
  JSS_PATCHED = true;
  let P;
  try {
    const { Duplex } = require('node:stream');
    const d = new Duplex({ read() {}, write(_c, _e, cb) { cb(); } });
    const t = new tls.TLSSocket(d);
    P = Object.getPrototypeOf(t._handle._parentWrap);
    t.destroy();
    d.destroy();
  } catch { return; }
  if (!P || !(P instanceof net.Socket)) return;
  const ours = (w) => w.stream && w.stream[HOOKS] && w.stream instanceof tls.TLSSocket;
  const def = (name, get) => {
    if (Object.prototype.hasOwnProperty.call(P, name)) return;
    Object.defineProperty(P, name, {
      configurable: true,
      get() { return ours(this) ? get(this, this.stream) : undefined; },
      set(v) { Object.defineProperty(this, name, { value: v, writable: true, configurable: true, enumerable: true }); },
    });
  };
  def('encrypted', () => true);
  def('alpnProtocol', (_w, s) => s.alpnProtocol);
  def('secureConnecting', (w, s) => {
    if (s._secureEstablished || s.destroyed) return false;
    if (!w.__detjsSecure) {
      Object.defineProperty(w, '__detjsSecure', { value: true });
      s.once('secureConnect', () => w.emit('connect'));
    }
    return true;
  });
}

function siteHere() {
  if (!STATE.config || !STATE.config.sites) return '';
  return STATE.quiet(() => sites.resolve());
}

/** Track the bytes of `sock` under `label` (site: where it was opened). */
function track(sock, label, site, normPort = null) {
  if (!sock || sock[TRACKED]) return null;
  const st = new Stream(label, site === null || site === undefined ? '' : site, normPort);
  Object.defineProperty(sock, TRACKED, { value: st });
  const h = hooks(sock);
  const main = MAIN;
  h.send.push((b) => { st.add('send', b); if (main) publishStartup(); });
  h.recv.push((b) => { st.add('recv', b); if (main) publishStartup(); });
  return st;
}

function portLabel(port) {
  const p = Number(port);
  return p >= EPHEMERAL_MIN ? '<port>' : String(port);
}

// Recording -------------------------------------------------------------------
function startRecording(sock, host, port, isTls, site) {
  const key = currentKey();
  const idx = POLICY.recording.openConnection(key, host, Number(port));
  if (isTls) POLICY.recording.setTls(key, idx);
  POLICY.recordedTests.add(key);
  let metas = POLICY.recMeta.get(key);
  if (!metas) { metas = []; POLICY.recMeta.set(key, metas); }
  const meta = { recorded_at: new real.Date().toISOString(), alpn: false };
  metas[idx] = meta;
  if (isTls) sock.once('secureConnect', () => { meta.alpn = sock.alpnProtocol || false; });
  const cassette = POLICY.recording;
  const h = hooks(sock);
  h.recv.push((b) => cassette.append(key, idx, 'recv', b));
  const wsn = new WsNormalizer(); // client WebSocket frames are stored unmasked (replay compares them so)
  h.send.push((b) => { const n = wsn.push(b); if (n.length) cassette.append(key, idx, 'send', redact(n)); });
  sock.once('close', () => { const r = wsn.flush(); if (r.length) { try { cassette.append(key, idx, 'send', r); } catch { /* saved */ } } });
  track(sock, `${host}:${port}`, site);
  if (key === STATE.testId) POLICY.testSockets.add(sock);
  STATE.record('net', isTls ? 'tls.connect' : 'net.connect', `${host}:${port} record#${idx}`);
}

// Replay ------------------------------------------------------------------------
let pipeCounter = 0;
const REPLAY_PIPES = new Map(); // path of a replay server -> { label, site }

function pipePath() {
  const name = `detjs-replay-${PID}-${pipeCounter++}-${real.Date.now().toString(36)}`;
  return process.platform === 'win32' ? `\\\\?\\pipe\\${name}` : path.join(os.tmpdir(), `${name}.sock`);
}

const MISMATCH_TOLD = new Set();

// Credentials in recorded requests (audit G-0131): the values of these HTTP request headers are stored as a digest
// padded to the same length (so replay compares requests byte for byte after the same redaction). Responses are kept
// as they are (the code under test reads them).
const SECRET_HEADERS = /^(authorization|proxy-authorization|cookie|x-api-key|api-key|x-auth-token|x-access-token|x-csrf-token|x-amz-security-token|x-goog-api-key|private-token|x-[a-z0-9-]*(?:token|secret|key|signature))$/i;
const REQUEST_LINE = /^[A-Z]{3,10} \S+ HTTP\/1\.[01]\r\n/;
function redact(buf) {
  if (buf.length < 16 || !REQUEST_LINE.test(buf.subarray(0, Math.min(buf.length, 2048)).toString('latin1'))) return buf;
  const text = buf.toString('latin1');
  const end = text.indexOf('\r\n\r\n');
  const head = end < 0 ? text : text.slice(0, end);
  let changed = false;
  const lines = head.split('\r\n').map((line, i) => {
    if (i === 0) return line;
    const c = line.indexOf(':');
    if (c <= 0 || !SECRET_HEADERS.test(line.slice(0, c).trim())) return line;
    const value = line.slice(c + 1);
    const tag = `<${native.digest(Buffer.from(value, 'latin1')).slice(0, 12)}>`;
    const out = (tag.length <= value.length ? tag + '*'.repeat(value.length - tag.length) : '*'.repeat(value.length));
    changed = true;
    return `${line.slice(0, c + 1)}${out}`;
  });
  if (!changed) return buf;
  return Buffer.from(lines.join('\r\n') + (end < 0 ? '' : text.slice(end)), 'latin1');
}

const H2_PREFACE = Buffer.from('PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n', 'latin1');

/**
 * The ALPN protocol the replay server negotiates: the recorded one; for a recording without it (older cassettes),
 * `h2` when the recorded client bytes start with the HTTP/2 preface. None: the server ignores the client's offer.
 */
function replayAlpn(meta, segments) {
  if (typeof meta.alpn === 'string' && meta.alpn) return meta.alpn;
  if (meta.alpn === false) return null;
  const first = segments.find((s) => s.dir === 'send');
  return first && first.data.subarray(0, H2_PREFACE.length).equals(H2_PREFACE) ? 'h2' : null;
}

function startReplayServer(segments, isTls, label, alpn) {
  const p = pipePath();
  const handler = (conn) => {
    let i = 0;
    let pending = Buffer.alloc(0);
    let idle = null;
    const wsn = new WsNormalizer();
    const step = () => {
      while (i < segments.length) {
        const s = segments[i];
        if (s.dir === 'recv') { conn.write(s.data); i++; continue; }
        if (pending.length >= s.data.length || (idle === 'expired' && pending.length > 0)) {
          const got = redact(pending.subarray(0, Math.min(pending.length, s.data.length)));
          if (!got.equals(s.data)) {
            // the request is not the recorded one: the recorded answer would be stale (audit G-0130). The
            // connection is reset and the test sees the error; the trace names the mismatch.
            STATE.recordAt('net', 'net.connect', '<detjs>', `replay-mismatch ${label} segment ${i}`);
            if (!MISMATCH_TOLD.has(label)) {
              MISMATCH_TOLD.add(label);
              let at = 0;
              while (at < got.length && got[at] === s.data[at]) at++;
              process.stderr.write(`detjs: network replay: the request to ${label} differs from the recording (segment ${i}, from byte ${at}: ${JSON.stringify(got.subarray(at, at + 40).toString('latin1'))} instead of ${JSON.stringify(s.data.subarray(at, at + 40).toString('latin1'))}); the connection is reset. Re-record with --det-record.\n`);
            }
            conn.destroy();
            server.close();
            return;
          }
          pending = pending.subarray(got.length);
          idle = null;
          i++;
          continue;
        }
        return;
      }
      conn.end();
      server.close();
    };
    conn.on('data', (d) => {
      pending = Buffer.concat([pending, wsn.push(d)]);
      if (idle && idle !== 'expired') require('./clock').REAL.clearTimeout(idle);
      // Request bytes may differ in length from the recording (dates,
      // boundaries): after 50 ms without more data the segment is accepted.
      idle = require('./clock').REAL.setTimeout(() => { idle = 'expired'; step(); }, 50);
      step();
    });
    conn.on('error', () => {});
    step();
  };
  let server;
  if (isTls) {
    const opts = { ...require('./selfcert').replayCert() };
    // the recorded protocol when the client offers it (HTTP/2, gRPC); no ALPN when the recording had none
    if (alpn) opts.ALPNCallback = ({ protocols }) => (protocols.includes(alpn) ? alpn : undefined);
    server = tls.createServer(opts, handler);
  } else {
    server = net.createServer(handler);
  }
  server.on('error', () => {});
  server.listen(p);
  server.unref();
  return p;
}

/** The recording to replay for the next connection of the current owner to host:port; 'stale' when too old. */
function findReplay(host, port, wantTls) {
  if (!POLICY.source) return null;
  const key = currentKey();
  const nth = POLICY.nth(key, host, port);
  const idx = POLICY.source.find(key, host, Number(port), nth);
  if (idx === null || idx === undefined) return null;
  const info = POLICY.source.info(key, idx);
  if (info.tls !== wantTls) return null;
  const meta = POLICY.meta(key, idx);
  if (POLICY.maxAgeDays > 0) {
    const t = typeof meta.recorded_at === 'string' ? Date.parse(meta.recorded_at) : NaN;
    const days = Number.isNaN(t) ? null : (real.Date.now() - t) / DAY_MS;
    if (days === null || days > POLICY.maxAgeDays) {
      return { stale: true, idx, why: `the recording is ${days === null ? 'of unknown age' : `${Math.floor(days)} days old`} (--det-cassette-max-age=${POLICY.maxAgeDays}): re-record with --det-record` };
    }
  }
  const segments = POLICY.source.segments(key, idx);
  return { idx, segments, alpn: wantTls ? replayAlpn(meta, segments) : null };
}

// net.Socket#connect -------------------------------------------------------------
function blockSocket(sock, host, port, why = null) {
  STATE.record('net', 'net.connect', `${host}:${port} ${why ? 'stale' : 'blocked'}`);
  const err = new NetworkBlockedError(`${host}:${port}`, 'ECONNREFUSED', why);
  err.address = host;
  err.port = Number(port);
  sock.connecting = true; // writes issued now are queued, then fail with err
  process.nextTick(() => sock.destroy(err));
  return sock;
}

function connect(...args) {
  if (POLICY === null) return real.connect.apply(this, args);
  // net.connect() passes an already normalized [options, cb] array.
  const normalized = Array.isArray(args[0]) ? args[0] : net._normalizeArgs(args);
  const options = normalized[0] || {};
  const cb = normalized[1];
  if (options.path) {
    const r = real.connect.apply(this, args);
    const rp = REPLAY_PIPES.get(String(options.path));
    if (rp) track(this, rp.label, rp.site);
    else if (!MAIN) localConnect(this, `unix:${sites.normPath(String(options.path))}`, null);
    return r;
  }
  if (options.port === undefined) return real.connect.apply(this, args);
  const rawHost = options.host || 'localhost';
  const port = options.port;
  if (!POLICY.external(rawHost, port)) {
    const r = real.connect.apply(this, args);
    if (isLocalName(rawHost)) {
      if (!MAIN) localConnect(this, `${rawHost}:${portLabel(port)}`, Number(port) >= EPHEMERAL_MIN ? Number(port) : null);
    } else {
      // a host allowed with --det-allow-host: live, in the fingerprint (G-1416)
      const host = POLICY.hostname(rawHost);
      const site = siteHere();
      if (site !== null) {
        STATE.record('net', this instanceof tls.TLSSocket ? 'tls.connect' : 'net.connect', `${host}:${port} allowed`);
        track(this, `${host}:${port}`, site);
      }
    }
    return r;
  }
  const host = POLICY.hostname(rawHost);
  const isTls = this instanceof tls.TLSSocket;
  // A mocking library that intercepts this socket (nock >= 14 / @mswjs/interceptors: an own `connect` on the
  // instance, the answer served from its handle): no real connection is made here. The real connection, if the mock
  // passes the request through, is a new socket and comes back through this function (audit G-0127).
  if (Object.prototype.hasOwnProperty.call(this, 'connect') && this._handle && Object.prototype.hasOwnProperty.call(this._handle, 'connect')) {
    STATE.record('net', 'net.connect', `${host}:${port} intercepted`);
    return real.connect.apply(this, args);
  }
  if (Object.prototype.hasOwnProperty.call(this, 'connect')) {
    guardHandle(this, host, port);
    return real.connect.apply(this, args);
  }
  if (POLICY.mode === 'record') {
    if (inTlsConnect || isTls) return real.connect.apply(this, args); // recorded at the TLS level (tls.connect)
    const site = siteHere();
    const r = real.connect.apply(this, args);
    startRecording(this, host, port, false, site);
    return r;
  }
  if (POLICY.mode === 'replay' && !isTls) {
    const rep = findReplay(host, port, false);
    if (rep && rep.stale) return blockSocket(this, host, port, rep.why);
    if (rep) {
      STATE.record('net', 'net.connect', `${host}:${port} replay#${rep.idx}`);
      const p = startReplayServer(rep.segments, false, `${host}:${port}#${rep.idx}`, null);
      const site = siteHere();
      const { host: _h, port: _p, lookup: _l, family: _f, hints: _hi, localAddress: _la, localPort: _lp, autoSelectFamily: _a, ...rest } = options;
      if (currentKey() === STATE.testId) POLICY.testSockets.add(this);
      const r = real.connect.call(this, { ...rest, path: p }, cb);
      track(this, `${host}:${port}`, site);
      return r;
    }
  }
  return blockSocket(this, host, port, isTls ? STALE_WHY : null);
}
let STALE_WHY = null;

/** A loopback or Unix-socket connection of a test (or of its file's set-up): an event, and its bytes digested. */
function localConnect(sock, label, normPort) {
  const site = siteHere();
  if (site === null) return; // the runner's own connection
  STATE.record('net', sock instanceof tls.TLSSocket ? 'tls.connect' : 'net.connect', `${label} local`);
  track(sock, label, site, normPort);
}

/**
 * A socket whose `connect` a library overrode on the instance, without (yet) a handle of its own: the connection is
 * decided when the handle connects. An interceptor replaces `handle.connect` on the instance (mocked: no network);
 * otherwise the handle's own connect would reach the network and is refused.
 */
function guardHandle(sock, host, port) {
  const arm = () => {
    const h = sock._handle;
    if (!h || h.__detjsGuard) return;
    Object.defineProperty(h, '__detjsGuard', { value: true });
    const protoConnect = Object.getPrototypeOf(h).connect;
    for (const k of ['connect', 'connect6']) {
      if (Object.prototype.hasOwnProperty.call(h, k)) continue; // intercepted: mocked
      const orig = h[k];
      if (typeof orig !== 'function') continue;
      h[k] = function guarded(...a) {
        if (Object.prototype.hasOwnProperty.call(h, 'connect') && h.connect !== guarded && h.connect !== protoConnect) return orig.apply(this, a);
        STATE.record('net', 'net.connect', `${host}:${port} blocked`);
        return -111; // UV_ECONNREFUSED: net reports "connect ECONNREFUSED"
      };
    }
  };
  arm();
  sock.once('lookup', arm);
}

// tls.connect --------------------------------------------------------------------
function tlsArgs(args) {
  // tls.connect(options[, cb]) | (port[, host][, options][, cb]) | (path[, options][, cb])
  let options = {};
  let cb;
  const a = [...args];
  if (typeof a[a.length - 1] === 'function') cb = a.pop();
  if (a.length && typeof a[0] === 'object' && a[0] !== null) {
    options = { ...a[0] };
  } else if (typeof a[0] === 'number' || (typeof a[0] === 'string' && /^\d+$/.test(a[0]))) {
    options.port = a[0];
    if (typeof a[1] === 'string') options.host = a[1];
    const o = a.find((x, i) => i > 0 && typeof x === 'object' && x !== null);
    if (o) options = { ...o, ...options };
  } else if (typeof a[0] === 'string') {
    options.path = a[0];
    if (typeof a[1] === 'object' && a[1] !== null) options = { ...a[1], path: a[0] };
  }
  return { options, cb };
}

function tlsConnect(...args) {
  if (POLICY === null) return real.tlsConnect.apply(this, args);
  const { options, cb } = tlsArgs(args);
  if (options.socket) {
    // TLS over a connection already open (STARTTLS): the plaintext above TLS is tracked from here on
    const sock = callTls(this, args);
    const st = options.socket[TRACKED];
    if (st) {
      st.frozen = true;
      track(sock, `${st.label}+tls`, st.site, st.port ? Number(st.port) : null);
    }
    return sock;
  }
  if (options.path || options.port === undefined) return callTls(this, args);
  const rawHost = options.host || 'localhost';
  const port = options.port;
  if (!POLICY.external(rawHost, port)) return callTls(this, args);
  const host = POLICY.hostname(rawHost);
  if (POLICY.mode === 'record') {
    const site = siteHere();
    const sock = callTls(this, args);
    startRecording(sock, host, port, true, site);
    return sock;
  }
  if (POLICY.mode === 'replay') {
    const rep = findReplay(host, port, true);
    if (rep && rep.stale) {
      // the TLS socket connects through net.Socket#connect, which refuses it with this reason
      STALE_WHY = rep.why;
      try { return callTls(this, args); } finally { STALE_WHY = null; }
    }
    if (rep) {
      STATE.record('net', 'tls.connect', `${host}:${port} replay#${rep.idx}`);
      const p = startReplayServer(rep.segments, true, `${host}:${port}#${rep.idx}`, rep.alpn);
      REPLAY_PIPES.set(p, { label: `${host}:${port}`, site: siteHere() });
      const { host: _h, port: _p, lookup: _l, family: _f, ...rest } = options;
      const servername = options.servername || (net.isIP(host) ? undefined : host);
      // certificate checks are disabled for this replayed socket only (G-2165)
      const sock = callTls(this, [{ ...rest, path: p, servername, rejectUnauthorized: false, checkServerIdentity: () => undefined }, ...(cb ? [cb] : [])]);
      if (currentKey() === STATE.testId) POLICY.testSockets.add(sock);
      return sock;
    }
  }
  return callTls(this, args); // block mode: the socket's connect is refused
}

function callTls(self, args) {
  inTlsConnect++;
  try {
    return real.tlsConnect.apply(self, args);
  } finally {
    inTlsConnect--;
  }
}

// DNS ----------------------------------------------------------------------------
function dnsCheck(host) {
  // undefined: resolve for real; a string: fake address (replay); throws when blocked.
  if (POLICY === null || host === null || host === undefined) return undefined;
  const h = String(host);
  if (isLocalName(h) || net.isIP(h) || POLICY.allow.has(h.toLowerCase().replace(/\.$/, ''))) return undefined;
  if (POLICY.mode === 'record') return undefined;
  if (POLICY.mode === 'replay' && POLICY.hasRecording(h)) {
    STATE.record('net', 'dns.lookup', `${h} replay`);
    return POLICY.fakeIp(h);
  }
  STATE.record('net', 'dns.lookup', `${h} blocked`);
  const err = new NetworkBlockedError(`${h} (DNS)`, 'ENOTFOUND');
  err.hostname = h;
  throw err;
}

function lookup(hostname, options, cb) {
  if (typeof options === 'function') { cb = options; options = {}; }
  let fake;
  try {
    fake = dnsCheck(hostname);
  } catch (err) {
    if (typeof cb === 'function') { process.nextTick(cb, err); return {}; }
    throw err;
  }
  if (fake === undefined) {
    return real.lookup.call(dns, hostname, options, (err, address, family) => {
      if (!err && POLICY && POLICY.mode === 'record' && !net.isIP(String(hostname))) {
        for (const a of Array.isArray(address) ? address : [{ address }]) POLICY.hostOfIp.set(a.address, String(hostname));
      }
      cb(err, address, family);
    });
  }
  const all = options && typeof options === 'object' && options.all;
  process.nextTick(() => (all ? cb(null, [{ address: fake, family: 4 }]) : cb(null, fake, 4)));
  return {};
}

async function pLookup(hostname, options) {
  const fake = dnsCheck(hostname);
  if (fake === undefined) return real.pLookup.call(dns.promises, hostname, options);
  return options && options.all ? [{ address: fake, family: 4 }] : { address: fake, family: 4 };
}

function guardResolve(obj, name, promises) {
  const orig = obj[name];
  if (typeof orig !== 'function') return null;
  if (promises) {
    return async function (hostname, ...rest) {
      if (POLICY && POLICY.mode !== 'record') dnsCheckNoFake(hostname);
      return orig.call(this, hostname, ...rest);
    };
  }
  return function (hostname, ...rest) {
    if (POLICY && POLICY.mode !== 'record') {
      try {
        dnsCheckNoFake(hostname);
      } catch (err) {
        const cb = rest[rest.length - 1];
        if (typeof cb === 'function') { process.nextTick(cb, err); return {}; }
        throw err;
      }
    }
    return orig.call(this, hostname, ...rest);
  };
}

/** dns.reverse(ip) / lookupService(ip, port): a query about a non-local address goes to the resolver: blocked. */
function guardReverse(obj, name, promises) {
  const orig = obj[name];
  if (typeof orig !== 'function') return null;
  const check = (ip) => {
    if (POLICY === null || POLICY.mode === 'record') return null;
    const h = String(ip);
    if (isLocalName(h) || POLICY.allow.has(h.toLowerCase())) return null;
    STATE.record('net', `dns.${name}`, `${h} blocked`);
    const err = new NetworkBlockedError(`${h} (reverse DNS)`, 'ENOTFOUND');
    err.hostname = h;
    return err;
  };
  if (promises) {
    return async function (ip, ...rest) {
      const err = check(ip);
      if (err) throw err;
      return orig.call(this, ip, ...rest);
    };
  }
  return function (ip, ...rest) {
    const err = check(ip);
    if (err) {
      const cb = rest[rest.length - 1];
      if (typeof cb === 'function') { process.nextTick(cb, err); return undefined; }
      throw err;
    }
    return orig.call(this, ip, ...rest);
  };
}

function dnsCheckNoFake(hostname) {
  const h = String(hostname);
  if (isLocalName(h) || net.isIP(h) || POLICY.allow.has(h.toLowerCase())) return;
  STATE.record('net', 'dns.resolve', `${h} blocked`);
  const err = new NetworkBlockedError(`${h} (DNS)`, 'ENOTFOUND');
  err.hostname = h;
  throw err;
}

// Installation -------------------------------------------------------------------
function installProcess(patcher, cfg) {
  if (POLICY === null) POLICY = new Policy(cfg);
  if (!STATE.__netHooked) {
    STATE.__netHooked = true;
    STATE.onTestStart.push((id) => { if (POLICY) { POLICY.startTest(id); emitSetup(); } });
    STATE.onTestEnd.push((id) => { emitTestStreams(id); if (POLICY) POLICY.endTest(); });
  }
  MAIN = false;
  installHttpDate(patcher);
  patcher.set(net.Socket.prototype, 'connect', connect);
  installDgram(patcher);
  patcher.set(tls, 'connect', tlsConnect);
  patcher.set(dns, 'lookup', lookup);
  patcher.set(dns.promises, 'lookup', pLookup);
  // `new dns.Resolver()` instances and reverse lookups send real queries too (audit G-1413, G-1414)
  for (const [P, promises] of [[dns.Resolver && dns.Resolver.prototype, false], [dns.promises.Resolver && dns.promises.Resolver.prototype, true]]) {
    if (!P) continue;
    for (const n of RESOLVE_FNS) {
      const f = guardResolve(P, n, promises);
      if (f) patcher.set(P, n, f);
    }
    const rv = guardReverse(P, 'reverse', promises);
    if (rv) patcher.set(P, 'reverse', rv);
  }
  for (const [obj, promises] of [[dns, false], [dns.promises, true]]) {
    const rv = guardReverse(obj, 'reverse', promises);
    if (rv) patcher.set(obj, 'reverse', rv);
    const ls = guardReverse(obj, 'lookupService', promises);
    if (ls) patcher.set(obj, 'lookupService', ls);
  }
  for (const n of RESOLVE_FNS) {
    const f = guardResolve(dns, n, false);
    if (f) patcher.set(dns, n, f);
    const pf = guardResolve(dns.promises, n, true);
    if (pf) patcher.set(dns.promises, n, pf);
  }
  return POLICY.mode;
}

// UDP (audit G-0128): datagrams to non-local addresses are refused like connections (no record/replay for UDP).
function installDgram(patcher) {
  const dgram = require('node:dgram');
  const P = dgram.Socket.prototype;
  const realSend = P.send;
  const realConnect = P.connect;
  const refuse = (sock, host, port, cb) => {
    STATE.record('net', 'dgram.send', `${host}:${port} blocked`);
    const err = new NetworkBlockedError(`${host}:${port} (UDP)`);
    err.address = host;
    err.port = Number(port);
    if (typeof cb === 'function') process.nextTick(cb, err);
    else process.nextTick(() => sock.emit('error', err));
  };
  patcher.set(P, 'send', function send(msg, ...rest) {
    if (POLICY === null) return realSend.call(this, msg, ...rest);
    const cb = typeof rest[rest.length - 1] === 'function' ? rest[rest.length - 1] : undefined;
    const a = rest.filter((x) => typeof x !== 'function');
    // send(msg[, offset, length][, port][, address])
    let port;
    let address;
    if (a.length >= 3 && typeof a[0] === 'number' && typeof a[1] === 'number' && !(typeof msg === 'string')) { port = a[2]; address = a[3]; } else { port = a[0]; address = a[1]; }
    if (port === undefined || port === null) return realSend.call(this, msg, ...rest); // connected socket: checked at connect
    const host = address === undefined || address === null ? (this.type === 'udp6' ? '::1' : '127.0.0.1') : String(address);
    if (!POLICY.external(host, port)) return realSend.call(this, msg, ...rest);
    return refuse(this, POLICY.hostname(host), port, cb);
  });
  patcher.set(P, 'connect', function connect(port, address, cb) {
    if (typeof address === 'function') { cb = address; address = undefined; }
    if (POLICY === null) return realConnect.call(this, port, address, cb);
    const host = address === undefined || address === null ? (this.type === 'udp6' ? '::1' : '127.0.0.1') : String(address);
    if (!POLICY.external(host, port)) return realConnect.call(this, port, address, cb);
    return refuse(this, POLICY.hostname(host), port, cb);
  });
}

/**
 * Merge what this process recorded into the cassette file; returns the number of tests (keys) recorded. The merge
 * is done on the JSON so that the `recorded_at` and `alpn` fields of the entries kept are preserved.
 */
function saveRecordings() {
  if (!POLICY || POLICY.mode !== 'record' || !POLICY.cassettePath || !POLICY.recordedTests.size) return 0;
  const tmp = `${POLICY.cassettePath}.part-${PID}-${require('node:worker_threads').threadId}`;
  POLICY.recording.save(tmp);
  const fresh = readCassetteJson(tmp) || { tests: {} };
  try { fs.rmSync(tmp, { force: true }); } catch { /* ignore */ }
  const target = (fs.existsSync(POLICY.cassettePath) && readCassetteJson(POLICY.cassettePath)) || { format: fresh.format, version: fresh.version, tests: {} };
  const tests = { ...(target.tests || {}) };
  for (const key of POLICY.recordedTests) {
    delete tests[key];
    const conns = (fresh.tests || {})[key];
    if (!conns) continue;
    const metas = POLICY.recMeta.get(key) || [];
    tests[key] = conns.map((c, i) => ({ ...c, ...(metas[i] || {}) }));
  }
  const sorted = {};
  for (const k of Object.keys(tests).sort()) sorted[k] = tests[k];
  const out = { ...target, format: fresh.format || target.format, version: Math.max(fresh.version || 0, target.version || 0), tests: sorted };
  fs.mkdirSync(path.dirname(POLICY.cassettePath), { recursive: true });
  const tmp2 = `${POLICY.cassettePath}.tmp-${PID}`;
  fs.writeFileSync(tmp2, JSON.stringify(out, null, 2));
  fs.renameSync(tmp2, POLICY.cassettePath);
  const n = POLICY.recordedTests.size;
  POLICY.recordedTests.clear();
  POLICY.recMeta.clear();
  POLICY.recording = new native.Cassette();
  return n;
}

/** Suspend the closed network (detjs' own shared-cache requests, outside tests); returns the restore function. */
function openNetwork() {
  const saved = POLICY;
  POLICY = null;
  return () => { POLICY = saved; };
}

/**
 * The runner's main process (`globalSetup`, start-up code), from session.prepare: external connections are closed,
 * recorded under `<startup>` or replayed like a test's (G-1419); what they exchange is published for the test
 * processes (`net-startup` in the run directory), whose tests carry it in their `net.setup` event.
 */
function installStartup(patcher, cfg) {
  if (POLICY !== null) return POLICY.mode;
  POLICY = new Policy(cfg);
  MAIN = true;
  if (cfg.dir) STARTUP_FILE = path.join(cfg.dir, 'net-startup');
  patcher.set(net.Socket.prototype, 'connect', connect);
  patcher.set(tls, 'connect', tlsConnect);
  patcher.set(dns, 'lookup', lookup);
  patcher.set(dns.promises, 'lookup', pLookup);
  return POLICY.mode;
}

/** A test file starts (controls.openFile): its set-up connections are recorded and replayed under its own key. */
function startFile(label) {
  if (FILE_KEY) BUCKETS.delete(FILE_KEY);
  FILE_KEY = `${label}::<setup>`;
  BUCKETS.delete(FILE_KEY);
  if (POLICY) POLICY.counters.delete(FILE_KEY);
  STARTUP_SUMMARY = '';
  const dir = STATE.config && STATE.config.dir;
  if (dir) { try { STARTUP_SUMMARY = fs.readFileSync(path.join(dir, 'net-startup'), 'utf8'); } catch { /* no start-up traffic */ } }
}

/**
 * Node's HTTP server writes a `Date` header from the real clock (an internal clock Level 0 does not reach): a local
 * server started by a test would put the machine's time into the bytes the test receives. Under Level 0 a response
 * without an explicit `Date` gets the virtual clock's (a clock read of the test).
 */
function installHttpDate(patcher) {
  const http = require('node:http');
  const P = http.ServerResponse && http.ServerResponse.prototype;
  if (!P || P.writeHead.__detjsDate) return;
  const realWriteHead = P.writeHead;
  const w = function writeHead(...a) {
    try {
      if (POLICY !== null && this.sendDate && !this._header && !this.hasHeader('date')) {
        const ms = require('./clock').virtualNowMs('http.Date');
        if (ms !== null) this.setHeader('Date', new real.Date(ms).toUTCString());
      }
    } catch { /* never break the response */ }
    return realWriteHead.apply(this, a);
  };
  Object.defineProperty(w, '__detjsDate', { value: true });
  patcher.set(P, 'writeHead', w);
}

module.exports = {
  openNetwork, installStartup, startFile, cassetteAges, readCassetteJson,
  installProcess, saveRecordings, NetworkBlockedError, isLocalName,
  get mode() { return POLICY ? POLICY.mode : null; },
};
