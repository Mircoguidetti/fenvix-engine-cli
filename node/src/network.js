'use strict';
// Closed network with optional record/replay.
//
// * Connections (`net.Socket#connect`, hence `net.connect`, `http`, `https`,
//   `tls.connect`, global `fetch` and `undici`) and DNS lookups (`dns.lookup`,
//   `dns.resolve*`, `dns.promises.*`) towards non-local hosts fail with
//   `NetworkBlockedError` (code ECONNREFUSED; ENOTFOUND for DNS). Loopback,
//   Unix sockets and hosts given with `--det-allow-host` are allowed. Local
//   HTTP(S) proxies from the `*_PROXY` variables count as external.
// * `--det-record`: external connections are allowed and their byte streams
//   are recorded per test into the cassette (plaintext above TLS, recorded at
//   the `tls.connect` level), shared format with the Python shell.
// * When a cassette exists and `--det-record` is not given, recorded
//   connections are replayed: the socket is transparently connected to a
//   local Unix socket served by a replay server that plays the recorded
//   conversation (a TLS server with a throwaway certificate for TLS
//   connections; certificate checks are disabled for that socket only).

const net = require('node:net');
const tls = require('node:tls');
const dns = require('node:dns');
const os = require('node:os');
const path = require('node:path');
const fs = require('node:fs');
const native = require('./native');
const { STATE } = require('./state');

const real = {
  connect: net.Socket.prototype.connect,
  tlsConnect: tls.connect,
  lookup: dns.lookup,
  pLookup: dns.promises.lookup,
};
const RESOLVE_FNS = ['resolve', 'resolve4', 'resolve6', 'resolveAny', 'resolveCname', 'resolveMx', 'resolveNs',
  'resolveTxt', 'resolveSrv', 'resolvePtr', 'resolveNaptr', 'resolveSoa', 'resolveCaa'];

class NetworkBlockedError extends Error {
  constructor(what, code = 'ECONNREFUSED') {
    const hint = POLICY && POLICY.mode === 'replay'
      ? 'no recording for it in this test: re-run with --det-record'
      : 'use --det-record to record real responses, or --det-allow-host to allow it';
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

class Policy {
  constructor(cfg) {
    this.mode = cfg.netMode; // block | record | replay
    this.allow = new Set(cfg.allowHosts);
    this.proxies = proxyEndpoints();
    this.cassettePath = cfg.cassette;
    this.recording = this.mode === 'record' ? new native.Cassette() : null;
    this.source = null;
    if (this.mode === 'replay' && this.cassettePath && fs.existsSync(this.cassettePath)) {
      this.source = native.Cassette.load(this.cassettePath);
    } else if (this.mode === 'replay') {
      this.mode = 'block';
    }
    this.hostOfIp = new Map();
    this.fakeIpOf = new Map();
    this.hostOfFake = new Map();
    this.counters = new Map();
    this.recordedTests = new Set();
  }

  startTest() {
    this.counters = new Map();
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
    if (!this.source || STATE.testId === null) return false;
    const n = this.source.count(STATE.testId);
    for (let i = 0; i < n; i++) if (this.source.info(STATE.testId, i).host === host) return true;
    return false;
  }

  nth(host, port) {
    const k = `${host}:${port}`;
    const n = this.counters.get(k) || 0;
    this.counters.set(k, n + 1);
    return n;
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

// Recording -------------------------------------------------------------------
function toBuf(chunk, enc) {
  if (Buffer.isBuffer(chunk)) return chunk;
  if (ArrayBuffer.isView(chunk)) return Buffer.from(chunk.buffer, chunk.byteOffset, chunk.byteLength);
  return Buffer.from(String(chunk), typeof enc === 'string' && enc !== 'buffer' ? enc : 'utf8');
}

function hookRecording(sock, testId, idx) {
  const cassette = POLICY.recording;
  const origPush = sock.push;
  sock.push = function push(chunk, enc) {
    if (chunk !== null && chunk !== undefined && chunk.length) cassette.append(testId, idx, 'recv', toBuf(chunk, enc));
    return origPush.call(this, chunk, enc);
  };
  const origWrite = sock._writeGeneric;
  sock._writeGeneric = function _writeGeneric(writev, data, encoding, cb) {
    if (!this.connecting) {
      if (writev) {
        for (const c of data) {
          const chunk = c && c.chunk !== undefined ? c.chunk : c;
          const b = toBuf(chunk, c && c.encoding);
          if (b.length) cassette.append(testId, idx, 'send', b);
        }
      } else {
        const b = toBuf(data, encoding);
        if (b.length) cassette.append(testId, idx, 'send', b);
      }
    }
    return origWrite.call(this, writev, data, encoding, cb);
  };
}

function startRecording(sock, host, port, isTls) {
  const testId = STATE.testId;
  const idx = POLICY.recording.openConnection(testId, host, Number(port));
  if (isTls) POLICY.recording.setTls(testId, idx);
  POLICY.recordedTests.add(testId);
  hookRecording(sock, testId, idx);
  STATE.record('net', isTls ? 'tls.connect' : 'net.connect', `${host}:${port} record#${idx}`);
}

// Replay ------------------------------------------------------------------------
let pipeCounter = 0;

function pipePath() {
  const name = `detjs-${process.pid}-${pipeCounter++}-${Date.now().toString(36)}`;
  return process.platform === 'win32' ? `\\\\?\\pipe\\${name}` : path.join(os.tmpdir(), `${name}.sock`);
}

function startReplayServer(segments, isTls, label) {
  const p = pipePath();
  const handler = (conn) => {
    let i = 0;
    let pending = Buffer.alloc(0);
    let idle = null;
    const step = () => {
      while (i < segments.length) {
        const s = segments[i];
        if (s.dir === 'recv') { conn.write(s.data); i++; continue; }
        if (pending.length >= s.data.length || (idle === 'expired' && pending.length > 0)) {
          const got = pending.subarray(0, Math.min(pending.length, s.data.length));
          if (!got.equals(s.data)) STATE.recordAt('net', 'replay.mismatch', '<detjs>', `${label} segment ${i}`);
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
      pending = Buffer.concat([pending, d]);
      if (idle && idle !== 'expired') require('./clock').REAL.clearTimeout(idle);
      // Request bytes may differ in length from the recording (dates,
      // boundaries): after 50 ms without more data the segment is accepted.
      idle = require('./clock').REAL.setTimeout(() => { idle = 'expired'; step(); }, 50);
      step();
    });
    conn.on('error', () => {});
    step();
  };
  const server = isTls ? tls.createServer(require('./replay-cert'), handler) : net.createServer(handler);
  server.on('error', () => {});
  server.listen(p);
  server.unref();
  return p;
}

function findReplay(host, port, wantTls) {
  if (!POLICY.source || STATE.testId === null) return null;
  const nth = POLICY.nth(host, port);
  const idx = POLICY.source.find(STATE.testId, host, Number(port), nth);
  if (idx === null || idx === undefined) return null;
  const info = POLICY.source.info(STATE.testId, idx);
  if (info.tls !== wantTls) return null;
  return { idx, segments: POLICY.source.segments(STATE.testId, idx) };
}

// net.Socket#connect -------------------------------------------------------------
function blockSocket(sock, host, port) {
  STATE.record('net', 'net.connect', `${host}:${port} blocked`);
  const err = new NetworkBlockedError(`${host}:${port}`);
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
  if (options.path || options.port === undefined) return real.connect.apply(this, args);
  const rawHost = options.host || 'localhost';
  const port = options.port;
  if (!POLICY.external(rawHost, port)) return real.connect.apply(this, args);
  const host = POLICY.hostname(rawHost);
  const isTls = this instanceof tls.TLSSocket;
  if (POLICY.mode === 'record') {
    if (inTlsConnect || isTls || STATE.testId === null) return real.connect.apply(this, args);
    const r = real.connect.apply(this, args);
    startRecording(this, host, port, false);
    return r;
  }
  if (POLICY.mode === 'replay' && !isTls) {
    const rep = findReplay(host, port, false);
    if (rep) {
      STATE.record('net', 'net.connect', `${host}:${port} replay#${rep.idx}`);
      const p = startReplayServer(rep.segments, false, `${host}:${port}#${rep.idx}`);
      const { host: _h, port: _p, lookup: _l, family: _f, hints: _hi, localAddress: _la, localPort: _lp, autoSelectFamily: _a, ...rest } = options;
      return real.connect.call(this, { ...rest, path: p }, cb);
    }
  }
  return blockSocket(this, host, port);
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
  if (options.socket || options.path || options.port === undefined) return callTls(this, args);
  const rawHost = options.host || 'localhost';
  const port = options.port;
  if (!POLICY.external(rawHost, port)) return callTls(this, args);
  const host = POLICY.hostname(rawHost);
  if (POLICY.mode === 'record' && STATE.testId !== null) {
    const sock = callTls(this, args);
    startRecording(sock, host, port, true);
    return sock;
  }
  if (POLICY.mode === 'replay') {
    const rep = findReplay(host, port, true);
    if (rep) {
      STATE.record('net', 'tls.connect', `${host}:${port} replay#${rep.idx}`);
      const p = startReplayServer(rep.segments, true, `${host}:${port}#${rep.idx}`);
      const { host: _h, port: _p, lookup: _l, family: _f, ...rest } = options;
      const servername = options.servername || (net.isIP(host) ? undefined : host);
      return callTls(this, [{ ...rest, path: p, servername, rejectUnauthorized: false, checkServerIdentity: () => undefined }, ...(cb ? [cb] : [])]);
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
    STATE.record('net', 'dns', `${h} replay`);
    return POLICY.fakeIp(h);
  }
  STATE.record('net', 'dns', `${h} blocked`);
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

function dnsCheckNoFake(hostname) {
  const h = String(hostname);
  if (isLocalName(h) || net.isIP(h) || POLICY.allow.has(h.toLowerCase())) return;
  STATE.record('net', 'dns', `${h} blocked`);
  const err = new NetworkBlockedError(`${h} (DNS)`, 'ENOTFOUND');
  err.hostname = h;
  throw err;
}

// Installation -------------------------------------------------------------------
function installProcess(patcher, cfg) {
  if (POLICY === null) {
    POLICY = new Policy(cfg);
    STATE.onTestStart.push(() => POLICY.startTest());
  }
  patcher.set(net.Socket.prototype, 'connect', connect);
  patcher.set(tls, 'connect', tlsConnect);
  patcher.set(dns, 'lookup', lookup);
  patcher.set(dns.promises, 'lookup', pLookup);
  for (const n of RESOLVE_FNS) {
    const f = guardResolve(dns, n, false);
    if (f) patcher.set(dns, n, f);
    const pf = guardResolve(dns.promises, n, true);
    if (pf) patcher.set(dns.promises, n, pf);
  }
  return POLICY.mode;
}

/** Merge what this process recorded into the cassette file; returns the number of tests. */
function saveRecordings() {
  if (!POLICY || POLICY.mode !== 'record' || !POLICY.cassettePath || !POLICY.recordedTests.size) return 0;
  const target = fs.existsSync(POLICY.cassettePath) ? native.Cassette.load(POLICY.cassettePath) : new native.Cassette();
  for (const t of POLICY.recordedTests) target.clearTest(t);
  target.merge(POLICY.recording);
  target.save(POLICY.cassettePath);
  const n = POLICY.recordedTests.size;
  POLICY.recordedTests.clear();
  POLICY.recording = new native.Cassette();
  return n;
}

module.exports = {
  installProcess, saveRecordings, NetworkBlockedError, isLocalName,
  get mode() { return POLICY ? POLICY.mode : null; },
};
