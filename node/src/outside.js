'use strict';
// Files outside the project read by the test (review R-050 N1; the Node side of the Python os control's "other files
// read ... recorded"): the project's files are the checkout every run starts from, a file elsewhere (a config in the
// home directory, a fixture in /tmp, a system file) is an input the run does not carry. Each read by the test's own
// code is an event `fs.read.outside` = `<path>|<bytes>:<digest>`, so two runs that read different contents differ and
// `verify` never calls them identical. Paths are machine-independent (src/sites.js normPath: `<abs>/name`,
// `<tmp>/...`); the project (relative paths), installed packages (`<deps>/`) and detjs itself are not recorded.
// Covered: readFileSync, readFile (callback), fs.promises.readFile, FileHandle.readFile / read, and reads of a
// descriptor opened with open / openSync (readSync, read): together the ways a file's bytes reach JavaScript
// (createReadStream reads through fs.open / fs.read).
const fs = require('node:fs');
const path = require('node:path');
const { STATE } = require('./state');
const sites = require('./sites');
const native = require('./native');

const FDS = new Map(); // fd -> normalized path, for descriptors of outside files opened by the test
const ENV_LOADED = new Set(); // variables set by process.loadEnvFile (not run inputs)

function outsidePath(p) {
  if (typeof p === 'number') return FDS.get(p) || null;
  let n;
  try { n = sites.normPath(p); } catch { return null; }
  // a file of the project read by the test's own code (a fixture, a data file): its bytes are an input too, they
  // can change between two runs of one checkout (docs/VERIFY-INPUTS.md); installed packages (<deps>/) are not
  if (!n.startsWith('<')) return n === '.' || n.startsWith('node_modules/') || n.startsWith('.detjs/') ? null : n;
  if (!n.startsWith('<abs>/') && !n.startsWith('<tmp>/')) return null;
  let abs;
  try { abs = path.resolve(typeof p === 'string' ? p : Buffer.isBuffer(p) ? p.toString() : require('node:url').fileURLToPath(p)); } catch { return null; }
  if (abs.startsWith(sites.SHELL_DIR) || /^\/(?:dev|proc|sys)\//.test(abs)) return null; // detjs; devices (seeds.js, facts.js)
  return n === '<abs>/' ? null : n;
}

/** The test's own call (not the runner's, not detjs' own): its site, or null. */
function byTest() {
  if (STATE.testId === null || STATE.quietDepth > 0) return false;
  if (!STATE.config || !STATE.config.sites) return true;
  return STATE.quiet(() => sites.resolve()) !== null;
}

function contentDigest(data, n) {
  let bytes;
  if (typeof data === 'string') bytes = Buffer.from(data);
  else if (ArrayBuffer.isView(data)) bytes = Buffer.from(data.buffer, data.byteOffset + (n && n.offset || 0), n && n.length !== undefined ? n.length : data.byteLength);
  else return null;
  return `${bytes.length}:${native.digest(bytes)}`;
}

function record(where, data, n) {
  const d = contentDigest(data, n);
  if (d === null) return;
  STATE.record('fs', where.startsWith('<') ? 'fs.read.outside' : 'fs.read', `${where}|${d}`);
}

// Files read while no test runs (review R-055 V3: module scope of a test file, a setup file, a project module at
// import, `process.loadEnvFile` at module scope): no test's event, so each (path, digest) goes to
// <run dir>/filesout/<pid>.txt and the trace header lists them (`files_read_outside_tests`, src/session.js,
// docs/VERIFY-CONTRACT.md); the verifier makes every test diverge when they differ. The module loader's own reads of
// source files are not entries (`inputs.code` / `inputs.deps` cover them).
const MODULE_LOADER = /\((?:node:)?internal\/modules\/|at (?:node:)?internal\/modules\//;
const LOADING = /(?:node:)?internal\/modules\/(?:cjs\/loader|esm\/(?:module_job|loader|translators))/;
const filesSeen = new Set();
function byProjectOutside(where, stat = false) {
  if (STATE.testId !== null || STATE.quietDepth > 0) return false;
  const c = STATE.config;
  if (!c || !c.dir) return false;
  const E = Error;
  const prev = E.stackTraceLimit;
  E.stackTraceLimit = 40;
  let stack;
  try { stack = String(new E().stack || ''); } finally { E.stackTraceLimit = prev; }
  // the caller of the fs function (the first frame outside detjs): the module loader reading a source file, or code
  if (MODULE_LOADER.test(stack.split('\n').slice(1).find((l) => !l.includes(sites.SHELL_DIR)) || '')) return false;
  if (!c.sites) return true;
  // the project's own code (a test file, a setup file, a project module), or a dependency reading a file of the
  // project at import (dotenv/config reading .env, a config loader); not a package reading its own or the runner's
  // files elsewhere (the runner's caches in <tmp>, a transformer's files): the same tool work in every run
  const site = STATE.quiet(() => sites.resolve());
  if (site === null) return false;
  if (!site.startsWith('<')) return true;
  // a dependency: only a read of a project file while a module is being loaded (its import), never a stat; Babel's
  // configuration lookup and the runner's transform cache run while transforming, in some runs only
  return !stat && site.startsWith('<deps>/') && typeof where === 'string' && !where.startsWith('<') && LOADING.test(stack);
}
function noteFile(where, digest) {
  const key = `${where}\u0000${digest}`;
  if (filesSeen.has(key)) return;
  filesSeen.add(key);
  STATE.quietDepth++;
  try {
    const dir = path.join(STATE.config.dir, 'filesout');
    fs.mkdirSync(dir, { recursive: true });
    fs.appendFileSync(path.join(dir, `${process.pid}.txt`), `${JSON.stringify({ path: where, digest })}\n`);
  } catch { /* the run directory is gone (the run ended) */ } finally { STATE.quietDepth--; }
}
/** A read of `where` (bytes `data`): an event of the test, or an entry of the run when no test runs. */
function onRead(where, data, n) {
  if (!where) return;
  if (byTest()) record(where, data, n);
  else if (byProjectOutside(where)) { const d = contentDigest(data, n); if (d !== null) noteFile(where, d); }
}

// File metadata (review R-055 V6): existence, kind and size seen by the test are `fs.stat` events
// (docs/VERIFY-CONTRACT.md section 2: `<path>|missing`, `<path>|present` (existence, access), `<path>|<type>`, and
// ` size=<n>` for a file (stat, lstat)). Times are not part of the value: they are virtual and recorded by
// src/fstime.js.
function typeOf(st) {
  if (!st) return 'missing';
  return st.isFile() ? 'file' : st.isDirectory() ? 'dir' : st.isSymbolicLink() ? 'link' : 'other';
}
// the kind only: is*() are keyed by the call for the cache (src/cache/capture.js), a field such as `size` would be
// a dependency of the test; existence calls record `present` (no second stat)
const { CAPTURE } = require('./cache/capture');
function statValue(st) {
  const t = typeOf(st);
  if (t !== 'file') return t;
  // the size the call returned (docs/VERIFY-CONTRACT.md section 2), read past the cache capture: the test reading
  // only isFile() does not make the size a dependency of its cached result (r021b). Times stay with src/fstime.js
  // (virtual; the real ones of a file the test wrote differ in every run)
  CAPTURE.busy++;
  try { return `${t} size=${st.size}`; } catch { return t; } finally { CAPTURE.busy--; }
}
function onStat(p, value) {
  if (typeof p === 'number') return;
  const where = outsidePath(p);
  if (!where) return;
  if (byTest()) STATE.record('fs', 'fs.stat', `${where}|${value}`);
  else if (byProjectOutside(where, true)) noteFile(where, `stat:${value}`);
}

function installProcess(patcher) {
  if (STATE.__outsideHooked) return;
  STATE.__outsideHooked = true;
  const w = (obj, name, make) => { const real = obj && obj[name]; if (typeof real === 'function') patcher.set(obj, name, make(real)); };
  w(fs, 'readFileSync', (real) => function readFileSync(p, ...a) {
    const r = real.call(this, p, ...a);
    if (STATE.quietDepth === 0) onRead(outsidePath(p), r);
    return r;
  });
  w(fs, 'readFile', (real) => function readFile(p, ...a) {
    const cb = a[a.length - 1];
    const o = typeof cb === 'function' && STATE.quietDepth === 0 ? outsidePath(p) : null;
    if (o && byTest()) {
      const id = STATE.testId;
      a[a.length - 1] = function done(e, data) { if (!e && STATE.testId === id) record(o, data); return cb.apply(this, arguments); };
    } else if (o && byProjectOutside(o)) {
      a[a.length - 1] = function done(e, data) { if (!e) { const d = contentDigest(data); if (d !== null) noteFile(o, d); } return cb.apply(this, arguments); };
    }
    return real.call(this, p, ...a);
  });
  w(fs.promises, 'readFile', (real) => async function readFile(p, ...a) {
    const o = STATE.quietDepth === 0 ? outsidePath(p) : null;
    const mine = o && byTest();
    const outside = o && !mine && byProjectOutside(o);
    const id = STATE.testId;
    const r = await real.call(this, p, ...a);
    if (mine && STATE.testId === id) record(o, r);
    else if (outside) { const d = contentDigest(r); if (d !== null) noteFile(o, d); }
    return r;
  });
  // metadata (V6)
  w(fs, 'existsSync', (real) => function existsSync(p) {
    const r = real.call(this, p);
    if (STATE.quietDepth === 0 && typeof p !== 'number') onStat(p, r ? 'present' : 'missing');
    return r;
  });
  for (const n of ['statSync', 'lstatSync']) {
    w(fs, n, (real) => function statSync(p, ...a) {
      let r;
      try { r = real.call(this, p, ...a); } catch (e) { if (STATE.quietDepth === 0) onStat(p, 'missing'); throw e; }
      if (STATE.quietDepth === 0) onStat(p, r && typeof r.isFile === 'function' ? statValue(r) : 'missing');
      return r;
    });
  }
  w(fs, 'accessSync', (real) => function accessSync(p, ...a) {
    try { real.call(this, p, ...a); } catch (e) { if (STATE.quietDepth === 0) onStat(p, 'missing'); throw e; }
    if (STATE.quietDepth === 0) onStat(p, 'present');
  });
  for (const n of ['stat', 'lstat', 'access']) {
    w(fs, n, (real) => function stat(p, ...a) {
      const cb = a[a.length - 1];
      if (typeof cb === 'function' && STATE.quietDepth === 0 && typeof p !== 'number') {
        const id = STATE.testId;
        a[a.length - 1] = function done(e, st) {
          if (STATE.testId === id) onStat(p, e ? 'missing' : n === 'access' ? 'present' : statValue(st));
          return cb.apply(this, arguments);
        };
      }
      return real.call(this, p, ...a);
    });
    w(fs.promises, n, (real) => async function stat(p, ...a) {
      const watch = STATE.quietDepth === 0 && typeof p !== 'number';
      const id = STATE.testId;
      let r;
      try { r = await real.call(this, p, ...a); } catch (e) { if (watch && STATE.testId === id) onStat(p, 'missing'); throw e; }
      if (watch && STATE.testId === id) onStat(p, n === 'access' ? 'present' : statValue(r));
      return r;
    });
  }
  // process.loadEnvFile (V16): C++ reads the file; its bytes are a read like readFileSync's, and the variables it
  // sets were no run input (src/controls.js records a digest of their values)
  if (typeof process.loadEnvFile === 'function') {
    const realLoad = process.loadEnvFile;
    patcher.set(process, 'loadEnvFile', function loadEnvFile(p = '.env') {
      let bytes = null;
      try { bytes = STATE.quiet(() => fs.readFileSync(p)); } catch { /* the real call reports it */ }
      const r = realLoad.call(this, p);
      if (bytes) {
        onRead(outsidePath(p), bytes);
        try { for (const k of Object.keys(require('node:util').parseEnv(bytes.toString('utf8')))) ENV_LOADED.add(k); } catch { /* old Node */ }
      }
      return r;
    });
  }
  w(fs, 'openSync', (real) => function openSync(p, ...a) {
    const fd = real.call(this, p, ...a);
    const o = typeof p === 'number' ? null : outsidePath(p);
    if (o) FDS.set(fd, o);
    return fd;
  });
  w(fs, 'open', (real) => function open(p, ...a) {
    const cb = a[a.length - 1];
    const o = typeof cb === 'function' ? outsidePath(p) : null;
    if (o) a[a.length - 1] = function done(e, fd) { if (!e) FDS.set(fd, o); return cb.apply(this, arguments); };
    return real.call(this, p, ...a);
  });
  w(fs, 'closeSync', (real) => function closeSync(fd, ...a) { FDS.delete(fd); return real.call(this, fd, ...a); });
  w(fs, 'close', (real) => function close(fd, ...a) { FDS.delete(fd); return real.call(this, fd, ...a); });
  const offsetOf = (a) => (typeof a[0] === 'number' ? a[0] : a[0] && typeof a[0] === 'object' && !ArrayBuffer.isView(a[0]) && typeof a[0].offset === 'number' ? a[0].offset : 0);
  w(fs, 'readSync', (real) => function readSync(fd, buf, ...a) {
    const n = real.call(this, fd, buf, ...a);
    const o = FDS.get(fd);
    if (o && n > 0 && byTest()) record(o, buf, { offset: offsetOf(a), length: n });
    return n;
  });
  w(fs, 'read', (real) => function read(fd, ...a) {
    const cb = a[a.length - 1];
    const o = FDS.get(fd);
    if (o && typeof cb === 'function' && byTest()) {
      const off = ArrayBuffer.isView(a[0]) ? offsetOf(a.slice(1)) : offsetOf(a);
      const id = STATE.testId;
      a[a.length - 1] = function done(e, n, buf) { if (!e && n > 0 && STATE.testId === id) record(o, buf, { offset: off, length: n }); return cb.apply(this, arguments); };
    }
    return real.call(this, fd, ...a);
  });
  // FileHandle (fs.promises.open): readFile and read of a handle on an outside file
  w(fs.promises, 'open', (real) => async function open(p, ...a) {
    const fh = await real.call(this, p, ...a);
    const o = outsidePath(p);
    if (o && fh && typeof fh.readFile === 'function') {
      const rf = fh.readFile;
      fh.readFile = async function readFile(...b) { const mine = byTest(); const r = await rf.apply(this, b); if (mine) record(o, r); return r; };
      const rd = fh.read;
      fh.read = async function read(buf, ...b) {
        const mine = byTest();
        const r = await rd.call(this, buf, ...b);
        if (mine && r && r.buffer && r.bytesRead > 0) record(o, r.buffer, { offset: ArrayBuffer.isView(buf) ? offsetOf(b) : offsetOf([buf]), length: r.bytesRead });
        return r;
      };
    }
    return fh;
  });
}

module.exports = { installProcess, outsidePath, ENV_LOADED };
