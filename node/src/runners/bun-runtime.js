'use strict';
// Bun's own APIs under --det (Level 0) and --det-cache (capture), in the test process of `detjs bun-test`.
//
// The Node modules Bun implements (node:fs, node:os, node:child_process, node:net, process.env, ...) are covered by
// the shared controls (src/controls.js) and the shared capture (src/cache/capture.js), which run unchanged in Bun.
// This module adds what only Bun has, with the same shared calls (CAPTURE.read / wrote / flag / env / module):
//
// * Level 0: `Bun.nanoseconds`, `Bun.sleep`, `Bun.sleepSync`, `Bun.randomUUIDv7` on the virtual clock and the
//   seeded generators; `fetch`, `Bun.connect`, `WebSocket`, `Bun.dns.*`, `node:http(s)` requests (Bun's HTTP client
//   is not built on net.Socket) closed to non-local hosts like every other connection;
// * capture: `Bun.file` (+ BunFile methods), `Bun.write`, `Bun.mmap`, `Bun.Glob#scan`, `bun:sqlite`, processes
//   (`Bun.spawn`, `Bun.$`, ...), sockets and servers, `Bun.resolve*`, the module loader (`Bun.plugin` onResolve
//   observer), snapshot files, and every other Bun API that may read an input: not cacheable unless it is on the
//   PURE list below (an API added by a later Bun is therefore not cacheable until it is classified);
// * properties Bun does not let us replace (`Bun.env` = `import.meta.env`, `Bun.fetch`, `BunFile#lastModified`,
//   `Bun.secrets`, ...): the source of every module the file loads is scanned for them (SCAN below), and a use makes
//   the input conservative (the whole environment) or the file not cacheable.
const fs = require('node:fs');
const path = require('node:path');
const { STATE } = require('../state');
const clock = require('../clock');
const network = require('../network');

// Bun APIs that read no input (pure functions of their arguments, or output only).
const PURE = new Set(['ArrayBufferSink', 'Cookie', 'CookieMap', 'CryptoHasher', 'MD4', 'MD5', 'SHA1', 'SHA224', 'SHA256', 'SHA384',
  'SHA512', 'SHA512_256', 'JSONC', 'JSON5', 'JSONL', 'TOML', 'XML', 'YAML', 'markdown', 'Transpiler', 'allocUnsafe', 'argv', 'color',
  'concatArrayBuffers', 'deepEquals', 'deepMatch', 'deflateSync', 'inflateSync', 'gzipSync', 'gunzipSync', 'zstdCompressSync',
  'zstdDecompressSync', 'zstdCompress', 'zstdDecompress', 'embeddedFiles', 'enableANSIColors', 'escapeHTML', 'fileURLToPath',
  'pathToFileURL', 'gc', 'generateHeapSnapshot', 'hash', 'indexOfLine', 'inspect', 'isMainThread', 'isStandaloneExecutable', 'jest',
  'main', 'origin', 'peek', 'plugin', 'randomUUIDv5', 'readableStreamToArray', 'readableStreamToArrayBuffer', 'readableStreamToBytes',
  'readableStreamToBlob', 'readableStreamToFormData', 'readableStreamToJSON', 'readableStreamToText', 'revision', 'semver', 'sha',
  'shrink', 'sliceAnsi', 'stringWidth', 'stripANSI', 'wrapAnsi', 'version', 'version_with_sha', 'cwd', 'stdout', 'stderr', 'env',
  'nanoseconds', 'sleep', 'sleepSync', 'randomUUIDv7']);
// Bun APIs handled one by one below (keyed reads, writes, or a precise reason)
const HANDLED = new Set(['file', 'write', 'mmap', 'Glob', 'spawn', 'spawnSync', '$', 'openInEditor', 'Terminal', 'connect', 'listen',
  'serve', 'udpSocket', 'fetch', 'dns', 'sql', 'SQL', 'postgres', 'redis', 'RedisClient', 's3', 'S3Client', 'resolve', 'resolveSync',
  'stdin', 'password', 'CSRF']);
// Source text of a loaded module that uses a Bun property detjs cannot wrap: [pattern, kind, detail]
const SCAN = [
  [/\bBun\s*\.\s*env\b|\bimport\s*\.\s*meta\s*\.\s*env\b|\bBun\s*\[\s*['"`]env['"`]\s*\]|\{[^{}]*\benv\b[^{}]*\}\s*=\s*(?:globalThis\s*\.\s*)?Bun\b/, 'env*', 'Bun.env / import.meta.env'],
  [/(?:[=(,:[?&|!]|\breturn|\bin|\bof)\s*(?:globalThis\s*\.\s*)?Bun\b(?!\s*\.\s*[A-Za-z_$])(?!\s*(?:!==?|===?)\s*['"`]?undefined)/, 'env*', 'Bun used as a value (aliased)'],
  [/\blastModified\b/, 'stat', 'BunFile#lastModified'],
  [/\bBun\s*\.\s*fetch\b/, 'connect', 'Bun.fetch (not replaceable: Level 0 does not close it)'],
  [/\bBun\s*\.\s*(?:WebView|ModuleGraph|secrets)\b/, 'runtime-api', 'Bun.WebView / ModuleGraph / secrets'],
];
const BUILTIN = /^(?:bun:|node:)/;
const REAL_RESOLVE = Bun.resolveSync.bind(Bun); // before installCapture wraps it

function localHost(host) {
  return network.isLocalName(host) || String(process.env.DETJS_ALLOW_HOSTS || '').split(',').map((s) => s.trim().toLowerCase())
    .filter(Boolean).includes(String(host).toLowerCase());
}

function blocked(what) {
  STATE.record('net', 'connect', `${what} blocked`);
  return new network.NetworkBlockedError(what);
}

function hostOf(u) {
  try {
    const x = new URL(String(u && typeof u === 'object' && 'url' in u ? u.url : u));
    return { protocol: x.protocol, host: x.hostname, port: x.port, url: x };
  } catch { return null; }
}

function replace(obj, key, fn) {
  try { obj[key] = fn; } catch { /* below */ }
  if (obj[key] !== fn) {
    try { Object.defineProperty(obj, key, { value: fn, writable: true, configurable: true, enumerable: true }); } catch { /* keep */ }
  }
  return obj[key] === fn;
}

// -- Level 0 ---------------------------------------------------------------------------------------------------
function installLevel0(cfg, notes) {
  if (cfg.controls.has('time')) {
    replace(Bun, 'nanoseconds', function nanoseconds() { return Math.round(performance.now() * 1e6); });
    if (cfg.controls.has('timers')) {
      replace(Bun, 'sleep', function sleep(ms) {
        const d = ms instanceof Date ? ms.getTime() - Date.now() : Number(ms);
        return new Promise((r) => setTimeout(r, Math.max(0, d || 0)));
      });
    }
    replace(Bun, 'sleepSync', function sleepSync(ms) {
      const C = clock.CLOCK;
      STATE.record('time', 'Bun.sleepSync', String(ms));
      if (C) C.advanceTo(C.elapsed + Math.max(0, Number(ms) || 0) * 1e6);
    });
  }
  if (cfg.controls.has('seeds')) {
    replace(Bun, 'randomUUIDv7', function randomUUIDv7(encoding, timestamp) {
      const ms = BigInt(timestamp === undefined ? Date.now() : (timestamp instanceof Date ? timestamp.getTime() : Number(timestamp)));
      const b = new Uint8Array(16);
      crypto.getRandomValues(b);
      for (let i = 0; i < 6; i++) b[i] = Number((ms >> BigInt(8 * (5 - i))) & 0xffn);
      b[6] = (b[6] & 0x0f) | 0x70;
      b[8] = (b[8] & 0x3f) | 0x80;
      if (encoding === 'buffer') return Buffer.from(b);
      if (encoding === 'base64' || encoding === 'base64url') return Buffer.from(b).toString(encoding);
      const h = Buffer.from(b).toString('hex');
      return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
    });
  }
  if (cfg.controls.has('net')) {
    if (cfg.netMode === 'record') notes.push('bun: --det-record does not record Bun\'s native connections (fetch, Bun.connect): they are allowed and not recorded');
    const open = cfg.netMode === 'record';
    const realFetch = globalThis.fetch;
    const fetchW = function fetch(input, init) {
      const h = hostOf(input);
      if (!open && h && /^(https?|wss?):$/.test(h.protocol) && !localHost(h.host)) {
        return Promise.reject(new TypeError('fetch failed', { cause: blocked(`${h.host}${h.port ? `:${h.port}` : ''}`) }));
      }
      return realFetch.apply(this, arguments);
    };
    Object.assign(fetchW, realFetch);
    replace(globalThis, 'fetch', fetchW);
    const realConnect = Bun.connect;
    replace(Bun, 'connect', function connect(o) {
      if (!open && o && !o.unix && !localHost(o.hostname || 'localhost')) return Promise.reject(blocked(`${o.hostname}:${o.port}`));
      return realConnect.apply(this, arguments);
    });
    const RealWS = globalThis.WebSocket;
    if (typeof RealWS === 'function') {
      const WS = new Proxy(RealWS, {
        construct(t, args, nt) {
          const h = hostOf(args[0]);
          if (!open && h && !localHost(h.host)) throw blocked(`${h.host} (WebSocket)`);
          return Reflect.construct(t, args, nt);
        },
      });
      replace(globalThis, 'WebSocket', WS);
    }
    for (const k of Object.keys(Bun.dns || {})) {
      const real = Bun.dns[k];
      if (typeof real !== 'function' || k === 'getServers' || k === 'getCacheStats') continue;
      replace(Bun.dns, k, function (host) {
        if (!open && typeof host === 'string' && !localHost(host) && !require('node:net').isIP(host)) {
          STATE.record('net', `Bun.dns.${k}`, `${host} blocked`);
          const e = new network.NetworkBlockedError(`${host} (DNS)`, 'ENOTFOUND');
          if (k === 'prefetch') return undefined;
          return Promise.reject(e);
        }
        return real.apply(this, arguments);
      });
    }
    // node:http(s) requests in Bun go through Bun's HTTP client, not net.Socket#connect
    for (const mod of ['node:http', 'node:https']) {
      const m = require(mod);
      for (const fn of ['request', 'get']) {
        const real = m[fn];
        if (typeof real !== 'function') continue;
        replace(m, fn, function (...a) {
          let host = 'localhost';
          const x = a[0];
          if (typeof x === 'string' || x instanceof URL) { const h = hostOf(x); if (h) host = h.host; } else if (x && typeof x === 'object') host = x.hostname || x.host || 'localhost';
          host = String(host).replace(/:\d+$/, '');
          if (!open && !localHost(host)) throw blocked(`${host} (${mod.slice(5)}.${fn})`);
          return real.apply(this, a);
        });
      }
    }
  }
}

// -- capture ---------------------------------------------------------------------------------------------------
function installCapture(cap, bracket, notes) {
  const cfg = require('../controls').cfg();
  const closed = cfg.controls.has('net') && cfg.netMode !== 'record';
  const flagger = (kind, name) => function () { if (cap.active && !cap.busy) cap.flag(kind, name); };
  const wrapCall = (obj, key, before, after) => {
    const real = obj[key];
    if (typeof real !== 'function' || real.__detjsCache) return false;
    const w = new Proxy(real, {
      apply(t, self, args) {
        if (cap.active && !cap.busy) { try { before(args); } catch { /* never break the call */ } }
        const r = Reflect.apply(t, self, args);
        if (after && cap.active && !cap.busy) { try { after(args, r); } catch { /* ignore */ } }
        return r;
      },
      construct(t, args, nt) {
        if (cap.active && !cap.busy) { try { before(args); } catch { /* ignore */ } }
        return Reflect.construct(t, args, nt);
      },
      get(t, k, r) { return k === '__detjsCache' ? true : Reflect.get(t, k, r); },
    });
    if (!replace(obj, key, w)) { notes.push(`bun: Bun.${key} not replaceable`); return false; }
    return true;
  };
  const pathArg = (p) => {
    if (typeof p === 'string') return /^[a-z][a-z0-9+.-]*:\/\//i.test(p) && !p.startsWith('file:') ? null : p;
    if (p instanceof URL) return p.protocol === 'file:' ? p : null;
    return undefined;
  };
  // Bun.file: the content is an input as soon as a BunFile names a path (native consumers such as Response and
  // Bun.write read it without calling a method); method calls record again at call time (after the test's writes)
  const fileProto = Object.getPrototypeOf(Bun.file('/'));
  const fileName = (f) => { try { return f.name; } catch { return undefined; } };
  const bunFileRead = (f, what) => {
    const n = fileName(f);
    if (typeof n === 'string' && n) {
      if (/^s3:\/\//.test(n)) cap.flag('connect', `S3 file ${n}`);
      else cap.read(n, 'f');
    } else {
      cap.flag('runtime-api', `BunFile without a path (${what}: descriptor or stdin)`);
    }
  };
  wrapCall(Bun, 'file', (a) => {
    const p = pathArg(a[0]);
    if (p === undefined) cap.flag('runtime-api', `Bun.file(${typeof a[0]}) (descriptor)`);
    else if (p === null) cap.flag('connect', `Bun.file(${String(a[0]).slice(0, 120)})`);
    else cap.read(p, 'f');
  });
  for (const m of ['text', 'json', 'bytes', 'arrayBuffer', 'stream', 'formData', 'image', 'slice', 'exists']) {
    if (typeof fileProto[m] === 'function') {
      const real = fileProto[m];
      replace(fileProto, m, function (...a) {
        if (cap.active && !cap.busy) { try { bunFileRead(this, m); } catch { /* ignore */ } }
        return real.apply(this, a);
      });
    }
  }
  if (typeof fileProto.stat === 'function') {
    const real = fileProto.stat;
    replace(fileProto, 'stat', function (...a) {
      let abs = null;
      if (cap.active && !cap.busy) {
        try { const n = fileName(this); if (typeof n === 'string') { cap.read(n, 's'); abs = cap.statTarget(n); } } catch { /* ignore */ }
      }
      const r = real.apply(this, a);
      if (abs === null || !r || typeof r.then !== 'function') return r;
      return r.then((st) => statFields(cap, st, abs));
    });
  }
  for (const m of ['write', 'writer', 'delete', 'unlink']) {
    if (typeof fileProto[m] !== 'function') continue;
    const real = fileProto[m];
    replace(fileProto, m, function (...a) {
      if (cap.active && !cap.busy) { try { const n = fileName(this); if (typeof n === 'string') cap.wrote(n); } catch { /* ignore */ } }
      return real.apply(this, a);
    });
  }
  wrapCall(Bun, 'write', (a) => {
    const d = a[0];
    const dn = d && typeof d === 'object' && !(d instanceof URL) ? fileName(d) : d;
    if (typeof dn === 'string' || dn instanceof URL) cap.wrote(dn);
    const s = a[1];
    if (s && typeof s === 'object' && Object.getPrototypeOf(s) === fileProto) bunFileRead(s, 'Bun.write source');
  });
  wrapCall(Bun, 'mmap', (a) => cap.read(a[0], 'f'));
  // Bun.Glob#scan: every path below the scanned directory and its type
  for (const m of ['scan', 'scanSync']) {
    const real = Bun.Glob.prototype[m];
    if (typeof real !== 'function') continue;
    replace(Bun.Glob.prototype, m, function (o) {
      if (cap.active && !cap.busy) {
        try {
          const cwd = typeof o === 'string' ? o : (o && o.cwd) || process.cwd();
          cap.read(path.resolve(cwd), 't');
          if (o && typeof o === 'object' && o.followSymlinks) cap.flag('runtime-api', 'Bun.Glob scan following symbolic links');
        } catch { /* ignore */ }
      }
      return real.apply(this, arguments);
    });
  }
  // processes, sockets, servers, network clients: never cached
  for (const k of ['spawn', 'spawnSync', '$', 'openInEditor', 'Terminal']) wrapCall(Bun, k, (a) => cap.flag('spawn', `Bun.${k} ${String(a[0]).slice(0, 160)}`));
  for (const k of ['connect', 'listen', 'serve']) wrapCall(Bun, k, () => cap.flag('connect', `Bun.${k}`));
  wrapCall(Bun, 'udpSocket', () => cap.flag('udp', 'Bun.udpSocket'));
  for (const k of ['sql', 'SQL', 'postgres', 'RedisClient', 'S3Client']) wrapCall(Bun, k, () => cap.flag('connect', `Bun.${k}`));
  for (const k of ['redis', 's3']) {
    const o = Bun[k];
    if (o && typeof o === 'object') {
      replace(Bun, k, new Proxy(o, { get(t, p, r) { if (cap.active && !cap.busy && typeof p === 'string') cap.flag('connect', `Bun.${k}.${p}`); return Reflect.get(t, p, r); } }));
    }
  }
  for (const k of Object.keys(Bun.dns || {})) {
    if (typeof Bun.dns[k] === 'function') wrapCall(Bun.dns, k, () => cap.flag('connect', `Bun.dns.${k}`));
  }
  // global fetch of a file URL reads it; other URLs are connections (non-local ones are closed by Level 0)
  wrapCall(globalThis, 'fetch', (a) => {
    const h = hostOf(a[0]);
    if (h && h.protocol === 'file:') cap.read(h.url, 'f');
    else if (h && h.protocol === 'data:') { /* inline */ } else if (h && /^(https?|wss?):$/.test(h.protocol) && !localHost(h.host) && closed) {
      // a non-local host: closed by Level 0 (the same deterministic failure every run)
    } else cap.flag('connect', `fetch ${String(a[0] && a[0].url ? a[0].url : a[0]).slice(0, 160)}`);
  });
  if (typeof globalThis.WebSocket === 'function') {
    wrapCall(globalThis, 'WebSocket', (a) => { const h = hostOf(a[0]); if (!(h && closed && !localHost(h.host))) cap.flag('connect', 'WebSocket'); });
  }
  // entropy that is not seeded
  if (Bun.password) {
    for (const k of ['hash', 'hashSync']) wrapCall(Bun.password, k, () => cap.flag('entropy', `Bun.password.${k}`));
  }
  if (Bun.CSRF) wrapCall(Bun.CSRF, 'generate', () => cap.flag('entropy', 'Bun.CSRF.generate'));
  // resolution done by the code itself: the result is a module dependency, a failure what would make it resolve
  for (const k of ['resolveSync', 'resolve']) {
    const real = Bun[k];
    if (typeof real !== 'function') continue;
    replace(Bun, k, function (spec, from) {
      const note = (res) => { if (cap.active && !cap.busy && typeof res === 'string') cap.module(res); };
      const fail = () => { if (cap.active && !cap.busy) { try { cap.resolveFailed(String(spec), fromFile(from)); } catch { /* ignore */ } } };
      let r;
      try { r = real.apply(this, arguments); } catch (e) { fail(); throw e; }
      if (r && typeof r.then === 'function') return r.then((x) => { note(x); return x; }, (e) => { fail(); throw e; });
      note(r);
      return r;
    });
  }
  // every other Bun API: not cacheable when used, unless it is known to be pure
  for (const k of Object.getOwnPropertyNames(Bun)) {
    if (PURE.has(k) || HANDLED.has(k)) continue;
    const d = Object.getOwnPropertyDescriptor(Bun, k);
    if (!d || d.get) continue;
    const v = d.value;
    if (typeof v === 'function') {
      if (!wrapCall(Bun, k, flagger('runtime-api', `Bun.${k}`))) notes.push(`bun: Bun.${k} cannot be wrapped (source scan only)`);
    } else if (v && typeof v === 'object') {
      if (!replace(Bun, k, new Proxy(v, { get(t, p, r) { if (cap.active && !cap.busy && typeof p === 'string') cap.flag('runtime-api', `Bun.${k}.${p}`); return Reflect.get(t, p, r); } }))) {
        notes.push(`bun: Bun.${k} cannot be wrapped (source scan only)`);
      }
    }
  }
  installSqlite(cap);
  installTestModule(cap);
  installResolver(cap, bracket);
}

function fromFile(from) {
  if (typeof from !== 'string' || !from) return undefined;
  try {
    if (from.startsWith('file:')) return require('node:url').fileURLToPath(from);
    if (fs.statSync(from).isDirectory()) return path.join(from, '__detjs_resolve__.js');
  } catch { /* keep */ }
  return from;
}

/** Stats of a BunFile#stat(): the fields read are keyed or make the file not cacheable (as for fs.stat). */
function statFields(cap, st, abs) {
  if (!st || typeof st !== 'object') return st;
  return new Proxy(st, {
    get(t, k) {
      const v = Reflect.get(t, k, t);
      if (typeof k === 'string' && cap.active && !cap.busy) { try { cap.statField(abs, k); } catch { /* ignore */ } }
      return typeof v === 'function' && k !== 'constructor' ? v.bind(t) : v;
    },
  });
}

const SQLITE_UNKEYED = /\b(attach|vacuum\s+into|load_extension)\b/i;

/** bun:sqlite opens database files natively: like node:sqlite in the shared capture. */
function installSqlite(cap) {
  let m;
  try { m = require('bun:sqlite'); } catch { return; }
  const Real = m.Database;
  if (typeof Real !== 'function' || Real.__detjsCache) return;
  const opened = (loc, options) => {
    if (loc === undefined || loc === null || loc === '' || loc === ':memory:') return;
    if (typeof loc !== 'string' || loc.startsWith('file:')) { cap.flag('sqlite', `database ${String(loc).slice(0, 200)}`); return; }
    for (const x of [loc, `${loc}-wal`, `${loc}-journal`, `${loc}-shm`]) cap.read(x, 'f');
    const ro = options === true || (options && typeof options === 'object' && options.readonly) || (typeof options === 'number' && (options & 1) && !(options & 2));
    if (!ro) cap.wrote(loc);
  };
  class Database extends Real {
    constructor(loc, options) {
      if (cap.active && !cap.busy) { try { opened(loc, options); } catch { /* never break the call */ } }
      super(loc, options);
    }

    static open(loc, options) { return new Database(loc, options); }
  }
  Object.defineProperty(Database, '__detjsCache', { value: true });
  Object.defineProperty(Database, 'name', { value: 'Database' });
  for (const n of ['exec', 'run', 'query', 'prepare']) {
    const real = Real.prototype[n];
    if (typeof real !== 'function') continue;
    Real.prototype[n] = function (sql, ...rest) {
      if (cap.active && !cap.busy && typeof sql === 'string' && SQLITE_UNKEYED.test(sql)) cap.flag('sqlite', `SQL ${sql.slice(0, 200)}`);
      return real.call(this, sql, ...rest);
    };
  }
  if (typeof Real.prototype.loadExtension === 'function') {
    const real = Real.prototype.loadExtension;
    Real.prototype.loadExtension = function (...a) { if (cap.active) cap.flag('sqlite', `extension ${a[0]}`); return real.apply(this, a); };
  }
  replace(m, 'Database', Database);
  if (m.default && typeof m.default === 'object') replace(m.default, 'Database', Database);
}

/** bun:test's mock.module(): the mocked specifier is resolved like an import (a new file there changes the mock target). */
function installTestModule(cap) {
  const bt = require('bun:test');
  const mock = bt.mock;
  if (!mock || typeof mock.module !== 'function') return;
  const real = mock.module;
  mock.module = function module(spec, factory) {
    if (cap.active && !cap.busy && typeof spec === 'string') {
      const caller = callerFile();
      try {
        const res = Bun.resolveSync(spec, caller ? path.dirname(caller) : process.cwd());
        if (typeof res === 'string') cap.module(res);
      } catch { try { cap.resolveFailed(spec, caller); } catch { /* ignore */ } }
    }
    return real.call(this, spec, factory);
  };
}

function callerFile() {
  const st = String(new Error().stack || '').split('\n');
  for (const l of st.slice(2)) {
    const m = /\(?((?:file:\/\/)?\/[^():]+):\d+:\d+\)?\s*$/.exec(l);
    if (m && !m[1].includes('/node/src/')) return m[1].replace(/^file:\/\//, '');
  }
  return undefined;
}

/**
 * The module loader. Bun's resolver and loader are native: they do not go through node:fs or Node's Module._load,
 * and a Bun.plugin onResolve hook is not called for every specifier (measured on Bun 1.4.4: not for extensionless
 * relative specifiers, found or not). So the modules of a test file are taken as a graph, like Deno's: from the
 * roots (the test file, the preloads, Bun's CommonJS registry and whatever onResolve did see), every import of every
 * module (Bun's own scanner, `Bun.Transpiler#scanImports`: static and literal dynamic imports, require calls) is
 * resolved with Bun's resolver, with the import and the require condition sets. A resolved project module is keyed by
 * content, with the stem listing of its name and its nearest package.json (cap.module, as for Node); a specifier that
 * does not resolve is keyed by what would make it resolve (cap.resolveFailed). A project module with an import() or
 * require() whose specifier is not a literal is not cacheable (its target is not known before the run). The source
 * of every module reached (installed packages included) is scanned for Bun properties that cannot be wrapped (SCAN).
 */
const LOADERS = { '.ts': 'ts', '.mts': 'ts', '.cts': 'ts', '.tsx': 'tsx', '.js': 'js', '.mjs': 'js', '.cjs': 'js', '.jsx': 'jsx' };
const NONLITERAL = /\bimport\s*\(\s*(?!(['"])[^'"\n]*\1\s*[,)])(?!`[^`$]*`\s*[,)])|\brequire\s*\(\s*(?!(['"])[^'"\n]*\2\s*\))(?!`[^`$]*`\s*\))/;

function installResolver(cap, bracket) {
  const { createRequire } = require('node:module');
  const engine = path.resolve(__dirname, '..', '..') + path.sep;
  const own = (file) => file.startsWith(engine) && /^(src|bin|node_modules)[\\/]/.test(file.slice(engine.length));
  const transpilers = {};
  const done = new Set(); // modules whose imports were followed
  const roots = new Set();
  const inProject = (f) => cap.where(f) === 'root';
  const visit = (file) => {
    if (done.has(file) || own(file) || !path.isAbsolute(file)) return;
    done.add(file);
    let src;
    cap.busy++;
    try { src = fs.readFileSync(file, 'latin1'); } catch { return; } finally { cap.busy--; }
    const where = cap.key(file);
    for (const [re, kind, detail] of SCAN) {
      if (!re.test(src)) continue;
      if (kind === 'env*') cap.add(['env', '*'], false);
      else cap.flag(kind, `${detail} in ${where}`);
    }
    const loader = LOADERS[path.extname(file)];
    if (!loader) return;
    const project = inProject(file);
    let imports = [];
    try {
      const t = transpilers[loader] || (transpilers[loader] = new Bun.Transpiler({ loader }));
      imports = t.scanImports(src);
    } catch {
      if (project) cap.flag('dynamic-import', `${where}: imports not readable by Bun's scanner`);
      return;
    }
    if (project && NONLITERAL.test(src)) cap.flag('dynamic-import', `${where}: import() or require() of a specifier that is not a literal`);
    const dir = path.dirname(file);
    let req = null;
    for (const im of imports) {
      const spec = im.path;
      if (typeof spec !== 'string' || !spec) continue;
      if (/^(node:)?sqlite$/.test(spec)) { cap.flag('sqlite', `node:sqlite imported by ${where}`); continue; }
      if (BUILTIN.test(spec) || require('node:module').isBuiltin(spec)) continue;
      const targets = [];
      cap.busy++;
      try {
        try { targets.push(REAL_RESOLVE(spec, dir)); } catch { /* below */ }
        try { req = req || createRequire(file); targets.push(req.resolve(spec)); } catch { /* import-only */ }
      } finally {
        cap.busy--;
      }
      const ok = [...new Set(targets.filter((x) => typeof x === 'string' && path.isAbsolute(x)))];
      if (!ok.length) {
        // installed packages: their own optional imports are covered by the runtime identity; a specifier that is
        // not in the source is the scanner's own (JSX runtime imports it adds with its default JSX settings; the
        // project's settings are in tsconfig, a configuration file)
        const literal = src.includes(`'${spec}'`) || src.includes(`"${spec}"`) || src.includes(`\`${spec}\``);
        if (project && literal) cap.resolveFailed(spec, file);
        continue;
      }
      for (const x of ok) {
        cap.module(x);
        visit(x);
      }
    }
  };
  const run = () => {
    try { for (const k of Object.keys(require.cache)) if (path.isAbsolute(k)) roots.add(k); } catch { /* none */ }
    for (const r of roots) visit(r);
    return [...done];
  };
  roots.add(path.resolve(require('../controls').cfg().root, process.env.DETJS_FILE));
  for (const p of String(process.env.DETJS_PRELOADS || '').split(path.delimiter).filter(Boolean)) roots.add(p);
  Bun.plugin({
    name: 'detjs-capture',
    setup(build) {
      build.onResolve({ filter: /.*/ }, (args) => {
        try {
          if (args.importer) {
            if (/^(node:)?sqlite$/.test(args.path)) cap.flag('sqlite', `node:sqlite imported by ${cap.key(args.importer)}`);
            else if (!BUILTIN.test(args.path)) roots.add(args.importer);
          } else if (path.isAbsolute(args.path)) roots.add(args.path);
        } catch { /* never break resolution */ }
        return undefined;
      });
    },
  });
  // cap.module() records each file once; run() is called at the end of every test and of the file
  bracket.modules = () => { const l = run(); for (const f of l) cap.module(f); return l; };
}

/** The snapshot file Bun reads natively for `toMatchSnapshot` of a test file (an input, or `missing`). */
function snapshotPath(abs) {
  return path.join(path.dirname(abs), '__snapshots__', `${path.basename(abs)}.snap`);
}

module.exports = { installLevel0, installCapture, snapshotPath, PURE, HANDLED, SCAN };
