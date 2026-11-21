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

/** A read outside any test (module scope, a hook, a dependency at import) by the project's own code. */
function outsideTest() {
  if (STATE.testId !== null || STATE.quietDepth > 0) return false;
  if (!STATE.config || !STATE.config.sites) return true;
  return STATE.quiet(() => sites.resolve()) !== null;
}

/** <run dir>/<kind>/<pid>.txt, one `key\tvalue` line: read by src/session.js runInputs (run inputs of every test). */
function noteRun(kind, key, value) {
  let dir;
  try { dir = require('./controls').cfg().dir; } catch { return; }
  if (!dir) return;
  STATE.quietDepth++;
  try {
    fs.mkdirSync(path.join(dir, kind), { recursive: true });
    fs.appendFileSync(path.join(dir, kind, `${process.pid}.txt`), `${key}\t${value}\n`);
  } catch { /* the run directory is gone */ } finally { STATE.quietDepth--; }
}

/** A file read outside any test: a run input `file:<path>` (R-055 V3). */
function recordOutside(where, data) {
  let bytes;
  if (typeof data === 'string') bytes = Buffer.from(data);
  else if (ArrayBuffer.isView(data)) bytes = Buffer.from(data.buffer, data.byteOffset, data.byteLength);
  else return;
  noteRun('filesout', where, `${bytes.length}:${native.digest(bytes)}`);
}

/** What a stat-family call tells the code: absent, a directory, or size and modification time (R-055 V6). */
function statValue(p) {
  return STATE.quiet(() => {
    try {
      const st = fs.statSync(p);
      return st.isDirectory() ? '<dir>' : `${st.size}:${st.mtimeMs}`;
    } catch { return '<absent>'; }
  });
}

function record(where, data, n) {
  let bytes;
  if (typeof data === 'string') bytes = Buffer.from(data);
  else if (ArrayBuffer.isView(data)) bytes = Buffer.from(data.buffer, data.byteOffset + (n && n.offset || 0), n && n.length !== undefined ? n.length : data.byteLength);
  else return;
  STATE.record('fs', where.startsWith('<') ? 'fs.read.outside' : 'fs.read', `${where}|${bytes.length}:${native.digest(bytes)}`);
}

function installProcess(patcher) {
  if (STATE.__outsideHooked) return;
  STATE.__outsideHooked = true;
  const w = (obj, name, make) => { const real = obj && obj[name]; if (typeof real === 'function') patcher.set(obj, name, make(real)); };
  w(fs, 'readFileSync', (real) => function readFileSync(p, ...a) {
    const r = real.call(this, p, ...a);
    const o = outsidePath(p);
    if (o && byTest()) record(o, r);
    else if (o && outsideTest()) recordOutside(o, r);
    return r;
  });
  // existence, size and modification time of a file the code looks at (R-055 V6)
  for (const name of ['existsSync', 'statSync', 'lstatSync']) {
    w(fs, name, (real) => function stat(p, ...a) {
      const r = real.call(this, p, ...a);
      const o = typeof p === 'number' ? null : outsidePath(p);
      if (o && (byTest() || outsideTest())) {
        const v = statValue(p);
        if (STATE.testId !== null) STATE.record('fs', 'fs.stat', `${o}|${v}`);
        else noteRun('filesout', `stat:${o}`, v);
      }
      return r;
    });
  }
  // process.loadEnvFile: the .env file is read in C++ (R-055 V16): its content is an input like a file read
  if (typeof process.loadEnvFile === 'function' && !process.loadEnvFile.__detjs) {
    const realLoad = process.loadEnvFile;
    const load = function loadEnvFile(p, ...a) {
      const file = p === undefined ? '.env' : p;
      const o = outsidePath(file);
      if (o && (byTest() || outsideTest())) {
        let data = null;
        STATE.quietDepth++;
        try { data = fs.readFileSync(file); } catch { data = '<absent>'; } finally { STATE.quietDepth--; }
        if (STATE.testId !== null) record(o, data); else recordOutside(o, data);
      }
      return realLoad.call(this, p, ...a);
    };
    Object.defineProperty(load, '__detjs', { value: true });
    patcher.set(process, 'loadEnvFile', load);
  }
  // the dependency modules this process loaded (CommonJS): their identity is a run input `deps` (R-055 V5)
  process.once('exit', () => {
    let lines = [];
    try {
      lines = Object.keys(require('node:module')._cache || {})
        .filter((f) => f.includes(`${path.sep}node_modules${path.sep}`) && !f.startsWith(sites.SHELL_DIR))
        .map((f) => { try { const st = fs.statSync(f); return `${f}\t${st.size}:${st.mtimeMs}`; } catch { return null; } })
        .filter(Boolean);
    } catch { /* none */ }
    for (const l of lines) { const [k, v] = l.split('\t'); noteRun('depsout', k, v); }
  });
  w(fs, 'readFile', (real) => function readFile(p, ...a) {
    const cb = a[a.length - 1];
    const o = typeof cb === 'function' ? outsidePath(p) : null;
    if (o && byTest()) {
      const id = STATE.testId;
      a[a.length - 1] = function done(e, data) { if (!e && STATE.testId === id) record(o, data); return cb.apply(this, arguments); };
    }
    return real.call(this, p, ...a);
  });
  w(fs.promises, 'readFile', (real) => async function readFile(p, ...a) {
    const o = outsidePath(p);
    const mine = o && byTest();
    const r = await real.call(this, p, ...a);
    if (mine) record(o, r);
    return r;
  });
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

module.exports = { installProcess, outsidePath };
