'use strict';
// Input recording for the Playwright cache with proof (`detjs playwright --det --det-cache=DIR`, src/pw/cache.js).
// Loaded by boot.js into every Node process of the run (the Playwright runner, its workers, the app servers started by
// `webServer` or by `detjs serve --det-cache=DIR`, and their Node children) when DETJS_PW_INPUTS names a directory.
//
// Each process appends to <DETJS_PW_INPUTS>/<role>-<pid>.jsonl, one JSON array per new fact, written at once (an app
// server killed at the end of the run has nothing left to flush):
//   ["f", path]        a file whose content was read (fs reads, read opens, read streams, modules loaded, native
//                      addons): its content digest is an input of the run
//   ["d", path]        a directory listed: its listing is an input
//   ["c", host, port]  a TCP connection opened
//   ["l", port]        a TCP port listened on (an app server)
//   ["x", file]        a child process that is not Node (its own reads are not recorded: the run is not cacheable)
//   ["w", path, before] the first write of the run to a path (file write, append, write open, rename target,
//                      unlink, mkdir, rm), with the content it had before: "missing", "dir", or the content digest.
//                      A file the run reads after writing it is an input by its content BEFORE the run (a database
//                      file the app creates must be absent at the start of the next run too)
//   ["n", file]        a native addon loaded (its own file reads are not seen; cache.js decides)
// The main side (cache.js) turns these into the run's inputs and decides whether the run may be reused.
const fs = require('node:fs');
const path = require('node:path');

const DIR = process.env.DETJS_PW_INPUTS;
let OUT = null;
const SEEN = new Set();
const REAL = {
  appendFileSync: fs.appendFileSync,
  mkdirSync: fs.mkdirSync,
  readFileSync: fs.readFileSync,
};

function emit(rec) {
  const k = rec.join('\0');
  if (SEEN.has(k)) return;
  SEEN.add(k);
  try { REAL.appendFileSync(OUT, `${JSON.stringify(rec)}\n`); } catch { /* the directory went away: run is over */ }
}

function toPath(p) {
  if (p === undefined || p === null) return null;
  if (typeof p === 'number') return null; // a file descriptor: its open was recorded
  if (Buffer.isBuffer(p)) p = p.toString();
  if (p instanceof URL) { if (p.protocol !== 'file:') return null; p = require('node:url').fileURLToPath(p); }
  if (typeof p !== 'string') return null;
  if (p.startsWith('file:')) { try { p = require('node:url').fileURLToPath(p); } catch { return null; } }
  return path.resolve(p);
}

function file(p) {
  const a = toPath(p);
  if (!a || a.startsWith('/proc/') || a.startsWith('/dev/') || a.startsWith('/sys/')) return;
  if (DIR && a.startsWith(DIR)) return;
  emit(['f', a]);
}

const WRITTEN = new Set();
function before(p) {
  const a = toPath(p);
  if (!a || WRITTEN.has(a) || a.startsWith('/proc/') || a.startsWith('/dev/') || (DIR && a.startsWith(DIR))) return;
  WRITTEN.add(a);
  let b = 'missing';
  try {
    const st = fs.statSync(a);
    if (st.isDirectory()) b = 'dir';
    else b = require('node:crypto').createHash('sha256').update(REAL.readFileSync(a)).digest('hex').slice(0, 32);
  } catch { /* missing */ }
  emit(['w', a, b]);
}

function longStack() {
  const lim = Error.stackTraceLimit;
  Error.stackTraceLimit = 100;
  try { return new Error().stack || ''; } finally { Error.stackTraceLimit = lim; }
}

function readFlags(flags) {
  if (flags === undefined || flags === null) return true;
  if (typeof flags === 'number') return (flags & 3) !== 1; // O_WRONLY only: not a read
  return /r|\+/.test(String(flags));
}

function wrap(obj, name, before) {
  const orig = obj[name];
  if (typeof orig !== 'function' || orig.__detjsInputs) return;
  const w = function (...a) { try { before(a); } catch { /* never break the caller */ } return orig.apply(this, a); };
  Object.defineProperty(w, '__detjsInputs', { value: true });
  Object.defineProperty(w, 'name', { value: orig.name });
  for (const k of Object.keys(orig)) { try { w[k] = orig[k]; } catch { /* read-only */ } }
  obj[name] = w;
}

function install(role) {
  if (!DIR || OUT) return;
  try { REAL.mkdirSync(DIR, { recursive: true }); } catch { /* exists */ }
  OUT = path.join(DIR, `${role}-${process.pid}.jsonl`);
  emit(['p', role, process.argv.slice(1, 3).join(' ')]);
  for (const n of ['readFileSync', 'readFile', 'createReadStream']) wrap(fs, n, (a) => file(a[0]));
  for (const n of ['openSync', 'open']) wrap(fs, n, (a) => { if (readFlags(a[1])) file(a[0]); });
  for (const n of ['readdirSync', 'readdir', 'opendirSync', 'opendir']) wrap(fs, n, (a) => { const d = toPath(a[0]); if (d) emit(['d', d]); });
  for (const n of ['readFile', 'open']) wrap(fs.promises, n, (a) => { if (n === 'readFile' || readFlags(a[1])) file(a[0]); });
  for (const n of ['readdir', 'opendir']) wrap(fs.promises, n, (a) => { const d = toPath(a[0]); if (d) emit(['d', d]); });
  // modules: CommonJS (every compiled file) and ES modules / CommonJS through the loader hooks where Node has them
  const Module = require('node:module');
  const ext = Module._extensions;
  for (const k of Object.keys(ext)) {
    const orig = ext[k];
    ext[k] = function (m, filename) { file(filename); return orig.call(this, m, filename); };
  }
  if (typeof Module.registerHooks === 'function') {
    try {
      Module.registerHooks({ load(url, context, next) { if (url.startsWith('file:')) file(url); return next(url, context); } });
    } catch { /* older Node: CommonJS only, ESM files are read with fs by the loaders that matter (tsx) */ }
  }
  // writes: the content before the run's first write (see the header)
  for (const n of ['writeFileSync', 'writeFile', 'appendFileSync', 'appendFile', 'createWriteStream', 'truncateSync', 'truncate',
    'unlinkSync', 'unlink', 'rmSync', 'rm', 'rmdirSync', 'rmdir', 'mkdirSync', 'mkdir', 'copyFileSync', 'copyFile']) {
    wrap(fs, n, (a) => before(n.startsWith('copyFile') ? a[1] : a[0]));
  }
  for (const n of ['renameSync', 'rename']) wrap(fs, n, (a) => { before(a[0]); before(a[1]); });
  for (const n of ['openSync', 'open']) wrap(fs, n, (a) => { if (a[1] !== undefined && !(typeof a[1] === 'string' && a[1] === 'r') && !(typeof a[1] === 'number' && (a[1] & 3) === 0)) before(a[0]); });
  for (const n of ['writeFile', 'appendFile', 'unlink', 'rm', 'rmdir', 'mkdir', 'truncate']) wrap(fs.promises, n, (a) => before(a[0]));
  wrap(fs.promises, 'rename', (a) => { before(a[0]); before(a[1]); });
  wrap(fs.promises, 'copyFile', (a) => before(a[1]));
  wrap(process, 'dlopen', (a) => { file(a[1]); const f = toPath(a[1]); if (f) emit(['n', f]); });
  // connections and listening ports
  const net = require('node:net');
  // Connections that were established (a connection the network control blocked never connects; a replayed one
  // connects to the replay server of the process, a port it listened on): the remote end as the socket saw it.
  const origConnect = net.Socket.prototype.connect;
  net.Socket.prototype.connect = function connect(...a) {
    try {
      this.once('connect', () => {
        try {
          if (this.remotePort) emit(['c', String(this.remoteAddress || 'localhost'), String(this.remotePort)]);
          else emit(['u', String(this._pipeName || this.remoteAddress || '?')]);
        } catch { /* gone */ }
      });
    } catch { /* never break the caller */ }
    return origConnect.apply(this, a);
  };
  const origListen = net.Server.prototype.listen;
  net.Server.prototype.listen = function listen(...a) {
    try {
      this.once('listening', () => {
        try { const ad = this.address(); if (ad && typeof ad === 'object' && ad.port) emit(['l', String(ad.port)]); } catch { /* closed */ }
      });
    } catch { /* never break the caller */ }
    return origListen.apply(this, a);
  };
  // child processes: Node children inherit NODE_OPTIONS (boot.js) and record their own reads; others do not
  const cp = require('node:child_process');
  const isNode = (f) => { const b = path.basename(String(f || '')); return b === 'node' || b === path.basename(process.execPath) || /^(npm|npx|pnpm|yarn|corepack)$/.test(b); };
  const shellCmd = (s) => String(s || '').trim().split(/\s+/)[0];
  for (const n of ['spawn', 'spawnSync', 'execFile', 'execFileSync']) {
    wrap(cp, n, (a) => {
      const opts = a.find((x, i) => i > 0 && x && typeof x === 'object' && !Array.isArray(x)) || {};
      const cmd = opts.shell ? shellCmd(a[0]) : a[0];
      if (isNode(cmd)) return;
      // tsx's esbuild service: transform requests carry the source through a pipe; the binary reads no file
      // itself (esbuild's build API would; it is not what tsx uses). Its binary is an input.
      if (/[\\/]esbuild$/.test(String(cmd)) && /[\\/]node_modules[\\/](?:\.pnpm[\\/][^\\/]+[\\/]node_modules[\\/])?tsx[\\/]/.test(longStack())) {
        file(cmd);
        return;
      }
      emit(['x', String(cmd)]);
    });
  }
  for (const n of ['exec', 'execSync']) wrap(cp, n, (a) => { if (!isNode(shellCmd(a[0]))) emit(['x', `sh: ${String(a[0]).slice(0, 200)}`]); });
  wrap(cp, 'fork', () => { /* a Node child: it records itself */ });
}

module.exports = { install };
