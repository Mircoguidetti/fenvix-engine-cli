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
// The main side (cache.js) turns these into the run's inputs and decides whether the run may be reused.
const fs = require('node:fs');
const path = require('node:path');

const DIR = process.env.DETJS_PW_INPUTS;
let OUT = null;
const SEEN = new Set();
const REAL = {
  appendFileSync: fs.appendFileSync,
  mkdirSync: fs.mkdirSync,
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
  wrap(process, 'dlopen', (a) => file(a[1]));
  // connections and listening ports
  const net = require('node:net');
  wrap(net.Socket.prototype, 'connect', (a) => {
    let o = a[0];
    if (Array.isArray(o)) o = o[0];
    if (o && typeof o === 'object') { if (o.path) emit(['u', String(o.path)]); else if (o.port !== undefined) emit(['c', String(o.host || 'localhost'), String(o.port)]); }
    else if (typeof o === 'number' || /^\d+$/.test(String(o))) emit(['c', String(a[1] || 'localhost'), String(o)]);
    else if (typeof o === 'string') emit(['u', o]);
  });
  wrap(net.Server.prototype, 'listen', (a) => {
    const o = a[0];
    const port = o && typeof o === 'object' ? o.port : o;
    if (port !== undefined && port !== null && /^\d+$/.test(String(port))) emit(['l', String(port)]);
  });
  // child processes: Node children inherit NODE_OPTIONS (boot.js) and record their own reads; others do not
  const cp = require('node:child_process');
  const isNode = (f) => { const b = path.basename(String(f || '')); return b === 'node' || b === path.basename(process.execPath) || /^(npm|npx|pnpm|yarn|corepack)$/.test(b); };
  const shellCmd = (s) => String(s || '').trim().split(/\s+/)[0];
  for (const n of ['spawn', 'spawnSync', 'execFile', 'execFileSync']) {
    wrap(cp, n, (a) => {
      const opts = a.find((x, i) => i > 0 && x && typeof x === 'object' && !Array.isArray(x)) || {};
      const cmd = opts.shell ? shellCmd(a[0]) : a[0];
      if (!isNode(cmd)) emit(['x', String(cmd)]);
    });
  }
  for (const n of ['exec', 'execSync']) wrap(cp, n, (a) => { if (!isNode(shellCmd(a[0]))) emit(['x', `sh: ${String(a[0]).slice(0, 200)}`]); });
  wrap(cp, 'fork', () => { /* a Node child: it records itself */ });
}

module.exports = { install };
