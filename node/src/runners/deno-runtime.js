'use strict';
// Deno's own APIs under --det (Level 0) and --det-cache (capture), in the test process of `detjs deno-test`.
//
// Deno's Node compatibility layer (node:fs, node:os, process.env, ...) is covered by the shared controls and the
// shared capture, which run unchanged in Deno. This module adds the `Deno` namespace with the same shared calls:
//
// * Level 0: `fetch`, `Deno.connect`, `Deno.connectTls`, `Deno.resolveDns`, `WebSocket`, `node:http(s)` closed to
//   non-local hosts (Deno's HTTP clients are not built on net.Socket#connect);
// * capture: file reads (`Deno.readTextFile`, `readFile`, `open`, `FsFile#stat`, ...), metadata (`stat`, `lstat`,
//   `realPath`, `readLink`), listings (`readDir`: names and entry types), writes, `Deno.env`, machine facts,
//   processes, sockets, FFI, KV, cron, watchers; every other function of the namespace makes the file not cacheable
//   unless it is on the PURE list (a function added by a later Deno is not cacheable until it is classified);
// * a cross-check (`explained`): the paths, variables and system facts the capture saw. Deno logs every permission
//   check it makes (DENO_AUDIT_PERMISSIONS, set per file by src/runners/deno.js); after the run, any access in that
//   log the capture did not see makes the file not cacheable (src/runners/deno.js `auditCheck`).
const path = require('node:path');
const { STATE } = require('../state');
const network = require('../network');

// Functions of the Deno namespace that read no input (or only the process's own state).
const PURE = new Set(['bench', 'build', 'chdir', 'cwd', 'errors', 'execPath', 'exit', 'exitCode', 'inspect', 'internal', 'mainModule',
  'memoryUsage', 'cpuUsage', 'noColor', 'pid', 'ppid', 'permissions', 'PermissionStatus', 'Permissions', 'refTimer', 'unrefTimer', 'SeekMode',
  'stderr', 'stdout', 'umask', 'version', 'args', 'addSignalListener', 'removeSignalListener', 'test', 'FsFile', 'isatty', 'jupyter',
  'lint', 'telemetry', 'env']);
const HANDLED = new Set(['readTextFile', 'readTextFileSync', 'readFile', 'readFileSync', 'stat', 'statSync', 'lstat', 'lstatSync', 'realPath',
  'realPathSync', 'readLink', 'readLinkSync', 'readDir', 'readDirSync', 'open', 'openSync', 'create', 'createSync', 'writeFile', 'writeFileSync',
  'writeTextFile', 'writeTextFileSync', 'mkdir', 'mkdirSync', 'remove', 'removeSync', 'rename', 'renameSync', 'copyFile', 'copyFileSync',
  'chmod', 'chmodSync', 'chown', 'chownSync', 'symlink', 'symlinkSync', 'link', 'linkSync', 'truncate', 'truncateSync', 'utime', 'utimeSync',
  'makeTempDir', 'makeTempDirSync', 'makeTempFile', 'makeTempFileSync', 'hostname', 'osRelease', 'networkInterfaces', 'uid', 'gid',
  'osUptime', 'loadavg', 'systemMemoryInfo', 'Command', 'ChildProcess', 'Process', 'run', 'spawn', 'spawnAndWait', 'spawnAndWaitSync', 'kill',
  'connect', 'connectTls', 'listen', 'listenTls', 'startTls', 'serve', 'serveHttp', 'upgradeWebSocket', 'resolveDns', 'createHttpClient',
  'HttpClient', 'dlopen', 'UnsafeCallback', 'UnsafeFnPointer', 'UnsafePointer', 'UnsafePointerView', 'watchFs', 'consoleSize', 'stdin',
  'openKv', 'cron']);

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

/** Replace a property of the namespace (value or getter). */
function replace(obj, key, fn) {
  const d = Object.getOwnPropertyDescriptor(obj, key);
  try {
    if (d && d.get) Object.defineProperty(obj, key, { get: () => fn, configurable: true, enumerable: d.enumerable });
    else obj[key] = fn;
  } catch { /* below */ }
  if (obj[key] !== fn) {
    try { Object.defineProperty(obj, key, { value: fn, writable: true, configurable: true, enumerable: true }); } catch { /* keep */ }
  }
  return obj[key] === fn;
}

// -- Level 0 ---------------------------------------------------------------------------------------------------
function installLevel0(cfg, notes) {
  if (!cfg.controls.has('net')) return;
  if (cfg.netMode === 'record') notes.push('deno: --det-record does not record Deno\'s native connections: they are allowed and not recorded');
  const open = cfg.netMode === 'record';
  const realFetch = globalThis.fetch;
  const fetchW = function fetch(input, init) {
    const h = hostOf(input);
    if (!open && h && /^(https?|wss?):$/.test(h.protocol) && !localHost(h.host)) {
      return Promise.reject(new TypeError('fetch failed', { cause: blocked(`${h.host}${h.port ? `:${h.port}` : ''}`) }));
    }
    return realFetch.apply(this, arguments);
  };
  replace(globalThis, 'fetch', fetchW);
  for (const k of ['connect', 'connectTls']) {
    const real = Deno[k];
    replace(Deno, k, function (o) {
      if (!open && o && o.transport !== 'unix' && !localHost(o.hostname || '127.0.0.1')) return Promise.reject(blocked(`${o.hostname}:${o.port}`));
      return real.apply(this, arguments);
    });
  }
  const realDns = Deno.resolveDns;
  replace(Deno, 'resolveDns', function resolveDns(q) {
    if (!open && typeof q === 'string' && !localHost(q)) {
      STATE.record('net', 'Deno.resolveDns', `${q} blocked`);
      return Promise.reject(new network.NetworkBlockedError(`${q} (DNS)`, 'ENOTFOUND'));
    }
    return realDns.apply(this, arguments);
  });
  const RealWS = globalThis.WebSocket;
  if (typeof RealWS === 'function') {
    replace(globalThis, 'WebSocket', new Proxy(RealWS, {
      construct(t, args, nt) {
        const h = hostOf(args[0]);
        if (!open && h && !localHost(h.host)) throw blocked(`${h.host} (WebSocket)`);
        return Reflect.construct(t, args, nt);
      },
    }));
  }
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

// -- capture ---------------------------------------------------------------------------------------------------
/**
 * What the capture saw (absolute paths, variable names, system facts), for the cross-check with Deno's audit log.
 * Filled by every wrapper below and by the shared capture's read / wrote / env (wrapped here).
 */
const explained = { paths: new Set(), env: new Set(), sys: new Set(), any: false };

function installCapture(cap, notes, { wrappers = true } = {}) {
  const cfg = require('../controls').cfg();
  const closed = cfg.controls.has('net') && cfg.netMode !== 'record';
  const abs = (p) => { try { const t = require('../cache/capture').toPath(p); return t; } catch { return null; } };
  // explained accesses: whatever the shared capture is asked about, before its own filters
  for (const m of ['read', 'wrote']) {
    const real = cap[m].bind(cap);
    cap[m] = (p, ...rest) => { const a = abs(p); if (a) explained.paths.add(a); return real(p, ...rest); };
  }
  const realEnv = cap.env.bind(cap);
  cap.env = (name) => { if (typeof name === 'string') explained.env.add(name); return realEnv(name); };
  const realFlag = cap.flag.bind(cap);
  cap.flag = (kind, detail) => { explained.any = true; return realFlag(kind, detail); };

  const wrap = (obj, key, before, after) => {
    if (!wrappers) return false; // DETJS_DENO_WRAPPERS=off (tests: the audit cross-check alone)
    const real = obj[key];
    if (typeof real !== 'function' || real.__detjsCache) return false;
    const w = new Proxy(real, {
      apply(t, self, args) {
        if (cap.active && !cap.busy) { try { before(args); } catch { /* never break the call */ } }
        const r = Reflect.apply(t, self, args);
        if (after && cap.active && !cap.busy) {
          try { return after(args, r); } catch { /* ignore */ }
        }
        return r;
      },
      construct(t, args, nt) {
        if (cap.active && !cap.busy) { try { before(args); } catch { /* ignore */ } }
        return Reflect.construct(t, args, nt);
      },
      get(t, k, r) { return k === '__detjsCache' ? true : Reflect.get(t, k, r); },
    });
    if (!replace(obj, key, w)) { notes.push(`deno: Deno.${key} not replaceable`); return false; }
    return true;
  };
  const both = (name) => [name, `${name}Sync`];
  // content reads
  for (const k of [...both('readTextFile'), ...both('readFile')]) wrap(Deno, k, (a) => cap.read(a[0], 'f'));
  // metadata: the kind by the call, the fields read from the result keyed or not cacheable (shared statField)
  const statWrap = (k, kind) => {
    const sync = k.endsWith('Sync');
    wrap(Deno, k, (a) => cap.read(a[0], kind), (a, r) => {
      const t = cap.statTarget(a[0]);
      if (t === null) return r;
      return sync ? statProxy(cap, r, t) : r.then((st) => statProxy(cap, st, t));
    });
  };
  for (const k of both('stat')) statWrap(k, 's');
  for (const k of both('lstat')) statWrap(k, 'l');
  for (const k of both('realPath')) wrap(Deno, k, (a) => cap.read(a[0], 'r'));
  for (const k of both('readLink')) wrap(Deno, k, (a) => cap.read(a[0], 'l'));
  // listings: Deno's entries carry their types
  for (const k of both('readDir')) wrap(Deno, k, (a) => cap.read(a[0], 'e'));
  // open: read unless write-only / truncating; writes are outputs; FsFile#stat as stat of the opened path
  const files = new WeakMap();
  for (const k of both('open')) {
    wrap(Deno, k, (a) => {
      const o = a[1] || { read: true };
      const reads = o.read !== false && !o.truncate && !(o.write && !o.read) && !(o.createNew);
      if (reads || o.read) cap.read(a[0], 'f');
      if (o.write || o.append || o.create || o.createNew || o.truncate) cap.wrote(a[0]);
    }, (a, r) => {
      if (r && typeof r.then === 'function') return r.then((f) => { files.set(f, a[0]); return f; });
      if (r) files.set(r, a[0]);
      return r;
    });
  }
  for (const k of both('create')) {
    wrap(Deno, k, (a) => cap.wrote(a[0]), (a, r) => {
      if (r && typeof r.then === 'function') return r.then((f) => { files.set(f, a[0]); return f; });
      if (r) files.set(r, a[0]);
      return r;
    });
  }
  const FP = Deno.FsFile && Deno.FsFile.prototype;
  if (FP) {
    for (const k of ['stat', 'statSync']) {
      const real = FP[k];
      if (typeof real !== 'function') continue;
      FP[k] = function (...a) {
        const p = files.get(this);
        let t = null;
        if (p !== undefined && cap.active && !cap.busy) { try { cap.read(p, 's'); t = cap.statTarget(p); } catch { /* ignore */ } }
        if (p === undefined && cap.active && !cap.busy) cap.flag('runtime-api', 'FsFile#stat of a file not opened by path');
        const r = real.apply(this, a);
        if (t === null) return r;
        return k === 'statSync' ? statProxy(cap, r, t) : r.then((st) => statProxy(cap, st, t));
      };
    }
  }
  // writes
  for (const k of [...both('writeFile'), ...both('writeTextFile'), ...both('mkdir'), ...both('remove'), ...both('chmod'), ...both('chown'),
    ...both('truncate'), ...both('utime')]) wrap(Deno, k, (a) => cap.wrote(a[0]));
  for (const k of [...both('symlink'), ...both('link')]) wrap(Deno, k, (a) => cap.wrote(a[1]));
  for (const k of both('copyFile')) wrap(Deno, k, (a) => { cap.read(a[0], 'f'); cap.wrote(a[1]); });
  for (const k of both('rename')) wrap(Deno, k, (a) => { cap.read(a[0], 'c'); cap.wrote(a[0]); cap.wrote(a[1]); });
  for (const k of both('makeTempDir').concat(both('makeTempFile'))) {
    // Deno checks the parent directory (the temporary directory, or options.dir) when it creates the entry
    wrap(Deno, k, (a) => { const d = a[0] && a[0].dir; const t = abs(d || require('node:os').tmpdir()); if (t) explained.paths.add(t); }, (_a, r) => {
      if (r && typeof r.then === 'function') return r.then((p) => { cap.wrote(p); return p; });
      cap.wrote(r);
      return r;
    });
  }
  // environment
  const E = Deno.env;
  for (const k of wrappers ? ['get', 'has'] : []) {
    const real = E[k];
    E[k] = function (name) { if (cap.active && !cap.busy && typeof name === 'string') cap.env(name); return real.call(this, name); };
  }
  const realToObject = E.toObject;
  if (wrappers) E.toObject = function toObject() { if (cap.active && !cap.busy) cap.env('*'); return realToObject.call(this); };
  // machine facts (same names as the shared capture's `~os.<name>`, digested by the main process)
  const fact = (k, name) => wrap(Deno, k, () => { explained.sys.add(k); cap.env(`~os.${name}`); });
  fact('hostname', 'hostname');
  fact('osRelease', 'release');
  fact('networkInterfaces', 'networkInterfaces');
  fact('uid', 'userInfo');
  fact('gid', 'userInfo');
  for (const k of ['osUptime', 'loadavg', 'systemMemoryInfo']) wrap(Deno, k, () => { explained.sys.add(k); cap.flag('machine', `Deno.${k}`); });
  // processes, sockets, FFI, KV, cron, watchers, terminal input: never cached
  for (const k of ['Command', 'ChildProcess', 'Process', 'run', 'spawn', 'spawnAndWait', 'spawnAndWaitSync', 'kill']) {
    if (Deno[k]) wrap(Deno, k, () => cap.flag('spawn', `Deno.${k}`));
  }
  for (const k of ['listen', 'listenTls', 'startTls', 'serve', 'serveHttp', 'upgradeWebSocket', 'createHttpClient', 'HttpClient']) {
    if (Deno[k]) wrap(Deno, k, () => cap.flag('connect', `Deno.${k}`));
  }
  for (const k of ['connect', 'connectTls']) {
    wrap(Deno, k, (a) => { const o = a[0] || {}; if (!(closed && o.transport !== 'unix' && !localHost(o.hostname || '127.0.0.1'))) cap.flag('connect', `Deno.${k}`); });
  }
  wrap(Deno, 'resolveDns', (a) => { if (!(closed && !localHost(a[0]))) cap.flag('connect', 'Deno.resolveDns'); });
  for (const k of ['dlopen', 'UnsafeCallback', 'UnsafeFnPointer', 'UnsafePointer', 'UnsafePointerView']) wrap(Deno, k, () => cap.flag('runtime-api', `Deno.${k} (FFI)`));
  wrap(Deno, 'watchFs', (a) => cap.flag('watch', String(a[0])));
  wrap(Deno, 'consoleSize', () => cap.flag('runtime-api', 'Deno.consoleSize'));
  if (Deno.stdin) {
    replace(Deno, 'stdin', new Proxy(Deno.stdin, { get(t, p) { if (cap.active && !cap.busy && (p === 'read' || p === 'readSync' || p === 'readable')) cap.flag('runtime-api', 'Deno.stdin'); const v = Reflect.get(t, p, t); return typeof v === 'function' ? v.bind(t) : v; } }));
  }
  for (const k of ['openKv', 'cron']) {
    const d = Object.getOwnPropertyDescriptor(Deno, k);
    if (d) wrap(Deno, k, () => cap.flag('runtime-api', `Deno.${k}`));
  }
  // fetch of a file URL reads it; other URLs are connections (non-local ones closed by Level 0)
  wrap(globalThis, 'fetch', (a) => {
    const h = hostOf(a[0]);
    if (h && h.protocol === 'file:') cap.read(h.url, 'f');
    else if (h && h.protocol === 'data:') { /* inline */ } else if (h && /^(https?|wss?):$/.test(h.protocol) && !localHost(h.host) && closed) { /* closed */ } else cap.flag('connect', `fetch ${String(a[0] && a[0].url ? a[0].url : a[0]).slice(0, 160)}`);
  });
  if (typeof globalThis.WebSocket === 'function') {
    wrap(globalThis, 'WebSocket', (a) => { const h = hostOf(a[0]); if (!(h && closed && !localHost(h.host))) cap.flag('connect', 'WebSocket'); });
  }
  if (typeof globalThis.Worker === 'function') wrap(globalThis, 'Worker', (a) => cap.flag('worker', `Worker ${String(a[0]).slice(0, 160)}`));
  // storage that persists between runs (Deno keeps it per origin under DENO_DIR)
  for (const k of ['localStorage', 'sessionStorage', 'caches']) {
    const d = Object.getOwnPropertyDescriptor(globalThis, k);
    if (!d || !d.configurable) continue;
    Object.defineProperty(globalThis, k, {
      configurable: true,
      enumerable: d.enumerable,
      get() { if (cap.active && !cap.busy) cap.flag('runtime-api', `${k} (persistent storage)`); return d.get ? d.get.call(this) : d.value; },
    });
  }
  // every other function of the namespace
  for (const k of Object.getOwnPropertyNames(Deno)) {
    if (PURE.has(k) || HANDLED.has(k)) continue;
    const d = Object.getOwnPropertyDescriptor(Deno, k);
    const v = d.get ? (() => { try { return d.get.call(Deno); } catch { return undefined; } })() : d.value;
    if (typeof v === 'function') wrap(Deno, k, () => cap.flag('runtime-api', `Deno.${k}`));
    else if (v && typeof v === 'object') {
      replace(Deno, k, new Proxy(v, { get(t, p, r) { if (cap.active && !cap.busy && typeof p === 'string') cap.flag('runtime-api', `Deno.${k}.${p}`); return Reflect.get(t, p, r); } }));
    }
  }
}

function statProxy(cap, st, absPath) {
  if (!st || typeof st !== 'object') return st;
  return new Proxy(st, {
    get(t, k) {
      const v = Reflect.get(t, k, t);
      if (typeof k === 'string' && cap.active && !cap.busy) { try { cap.statField(absPath, k); } catch { /* ignore */ } }
      return typeof v === 'function' && k !== 'constructor' ? v.bind(t) : v;
    },
  });
}

module.exports = { installLevel0, installCapture, explained, PURE, HANDLED };
