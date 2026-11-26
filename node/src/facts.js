'use strict';
// Machine and process facts, native key generation and temporary directory names under --det (P-041; audit G-1406,
// G-1407, G-1408, G-1409, G-1430, G-1431, G-1422..G-1425, G-2163, G-2166).
//
// * Facts of the machine and of the process that Level 0 does not choose (host name, user, home and temporary
//   directories, network interfaces, CPUs, memory, load, uptimes, process ids, CPU and resource usage, event loop
//   utilisation) are passed through and recorded when a test reads them: `other` events `os.<name>` /
//   `process.<name>` with a digest of the value. A run on another machine, or a value that changes from call to call,
//   is then a different fingerprint, never "identical".
// * Native key generation draws OS randomness Level 0 cannot seed (`generateKeyPair`, `generateKey`, ECDH /
//   Diffie-Hellman `generateKeys`, `generatePrime`, WebCrypto `subtle.generateKey`): recorded as `entropy` events with
//   a digest of the generated material (the cache never reuses such a test: `keygen` / `entropy`).
// * `fs.mkdtemp` names: the random suffix comes from a stream seeded by the test id (the same in every run), so paths
//   under the temporary directory are reproducible; the name is recorded.
const os = require('node:os');
const fs = require('node:fs');
const nodeCrypto = require('node:crypto');
const path = require('node:path');
const { STATE } = require('./state');
const sites = require('./sites');
const native = require('./native');

const dig = (v) => native.digest(Buffer.from(typeof v === 'string' ? v : JSON.stringify(v) || String(v))).slice(0, 12);

function rec(op, v, source = 'other') {
  if (STATE.testId === null || STATE.quietDepth > 0) return;
  // A fact is a SYNCHRONOUS read of this process's or this machine's state (`process.pid`, `os.hostname`,
  // `process.memoryUsage`, ...): the frame that asked for it is on the stack right now. If there is no user
  // frame at all, nobody in the test asked, and crediting the test for it makes a parallel run
  // irreproducible: MEASURED, a Jest worker emits Node's `_channel` deprecation warning and Node's warning
  // PRINTER reads `process.pid` for its `(node:NNNN)` prefix, which landed inside whichever test was awaiting
  // a timer -- 2 of 12 tests in a 2-worker run got an event their serial run did not have, so the parallel
  // fingerprints stopped matching the serial ones (the `node (24, shard 0/4)` red of CI 44964230574).
  // The same question, with the same answer, as the general rule's sensor asks in src/provable.js.
  // This is deliberately only the facts path. An ASYNCHRONOUS observation (`fs.promises.access`, a stream)
  // completes with nothing but internal frames on the stack although the test did ask for it at call time,
  // and dropping those made `fenvix verify` answer IDENTICAL on two runs that saw different bytes -- caught
  // by tests/attacks.py (node/test/verifier-inputs.test.js and node/test/verify-inputs-attacks.test.js).
  let site;
  STATE.quietDepth++;
  try { site = sites.resolve(); } finally { STATE.quietDepth--; }
  if (site === null || site === '<node>') return;
  let s;
  try { s = dig(v); } catch { s = '?'; }
  STATE.record(source, op, s, site);
}

function wrap(obj, name, op, patcher, source = 'other', view = (r) => r) {
  const real = obj && obj[name];
  if (typeof real !== 'function' || real.__detjsFacts) return;
  const w = function (...a) {
    const r = real.apply(this, a);
    if (STATE.testId !== null && STATE.quietDepth === 0) { try { recQuietSafe(op, view(r), source); } catch { /* never break the call */ } }
    return r;
  };
  for (const k of Reflect.ownKeys(real)) {
    if (['length', 'name', 'prototype', 'arguments', 'caller'].includes(k)) continue;
    try { Object.defineProperty(w, k, Object.getOwnPropertyDescriptor(real, k)); } catch { /* ignore */ }
  }
  Object.defineProperty(w, '__detjsFacts', { value: true });
  Object.defineProperty(w, 'name', { value: real.name, configurable: true });
  patcher.set(obj, name, w);
}

// `rec` runs inside STATE.quiet (so that digesting does not record): record with the test's site explicitly
function recQuietSafe(op, v, source) {
  const depth = STATE.quietDepth;
  STATE.quietDepth = 0;
  try { rec(op, v, source); } finally { STATE.quietDepth = depth; }
}

//: the `process.binding` tables that are a function of the Node version alone (a run input), and nothing else
const PURE_BINDINGS = new Set(['constants']);

const OS_FACTS = ['hostname', 'userInfo', 'homedir', 'tmpdir', 'networkInterfaces', 'availableParallelism', 'totalmem',
  'freemem', 'loadavg', 'uptime', 'release', 'version', 'machine', 'getPriority', 'type', 'arch', 'endianness'];

function installProcessFacts(patcher, proc) {
  for (const n of ['cpuUsage', 'resourceUsage', 'memoryUsage', 'constrainedMemory', 'availableMemory']) {
    const real = proc[n];
    if (typeof real !== 'function' || real.__detjsFacts) continue;
    const w = function (...a) {
      const r = real.apply(this, a);
      if (STATE.testId !== null && STATE.quietDepth === 0) recQuietSafe(`process.${n}`, r);
      return r;
    };
    for (const k of Reflect.ownKeys(real)) {
      if (['length', 'name', 'prototype', 'arguments', 'caller'].includes(k)) continue;
      try { Object.defineProperty(w, k, Object.getOwnPropertyDescriptor(real, k)); } catch { /* ignore */ }
    }
    if (typeof real.rss === 'function') w.rss = function rss() { const r = real.rss(); if (STATE.testId !== null) recQuietSafe('process.memoryUsage.rss', r); return r; };
    Object.defineProperty(w, '__detjsFacts', { value: true });
    patcher.set(proc, n, w);
  }
  // `process.binding(name)` hands out a raw internal binding, BYPASSING the modules the engine patched: a test
  // that asked for `fs` or `crypto` this way would read files or draw entropy where no observer can see it. So
  // the decision is per ARGUMENT, by the predicate that knows which argument it was, and not by the name:
  //   * `constants` is a table of numbers (O_RDONLY, the errno values, the signal numbers) that reads nothing
  //     and cannot change within a Node version, and the version is a run input (`runtime`). Recorded as an
  //     event so the call is in the fingerprint, and that is all it is.
  //   * anything else marks the running test `uncontrolled.io` at this call: unobserved, so unprovable.
  // Named because Emscripten's generated code asks for `constants`, and PGlite is Emscripten: MEASURED, the
  // pilot's own stack (node:test + PGlite, 36 files) had every test NOT PROVEN with
  // "unaccounted.api: process.binding", so nothing of it could be cached or spread across cores.
  const realBinding = proc.binding;
  if (typeof realBinding === 'function' && !realBinding.__detjsFacts) {
    const w = function binding(name, ...rest) {
      const r = realBinding.call(this, name, ...rest);
      try {
        if (PURE_BINDINGS.has(String(name))) recQuietSafe(`process.binding.${name}`, String(name));
        else if (STATE.testId !== null) STATE.recordAt('other', 'uncontrolled.io', '<detjs>', `process.binding(${name})`);
      } catch { /* never break the call */ }
      return r;
    };
    Object.defineProperty(w, '__detjsFacts', { value: true });
    patcher.set(proc, 'binding', w);
  }
  // `process.pid` / `process.ppid` are plain properties, read synchronously at the reader's own site, so they go
  // through rec() and its `<node>`-site rule like every other fact: a read with no user frame on the stack (MEASURED,
  // jest 29.7.0 --maxWorkers=2: Node's own machinery reading `process.pid` inside a worker while a test is in flight)
  // is not an event of the test, so serial and parallel fingerprints stay equal.
  //
  // P1 C (docs/DESIGN-P1.md section C): while a test file is open, the test's code reads a VIRTUAL pid (`startFile`),
  // the same in every run of that file and different for two files that run at the same time; detjs, the runner and
  // Node's internals keep reading the real one (`testCaller`). `process.ppid` stays real: a test that checks the
  // process tree (its parent is the detjs that spawned it: test/exit-regression.test.js AC1(c)) must keep seeing it.
  for (const n of ['pid', 'ppid']) {
    const d = Object.getOwnPropertyDescriptor(proc, n);
    if (!d || !d.configurable || d.get) continue;
    const value = d.value;
    try {
      Object.defineProperty(proc, n, {
        configurable: true, enumerable: d.enumerable,
        get: function pidGetter() {
          const v = n !== 'pid' || VPID.current === null || STATE.quietDepth > 0 || !testCaller(pidGetter) ? value : VPID.current;
          if (STATE.testId !== null && STATE.quietDepth === 0) recQuietSafe(`process.${n}`, v);
          return v;
        },
        set(v) { Object.defineProperty(proc, n, { value: v, writable: true, configurable: true, enumerable: d.enumerable }); },
      });
    } catch { /* keep */ }
  }
}

// -- the virtual pid (P1 C) ------------------------------------------------------------------------------------------
// Linux's PID_MAX_LIMIT (2^22): no process has this pid or a higher one, so a virtual pid is never another live
// process's. A file's pid: VPID_BASE + 1 + a digest of (run seed, file label)
// below 2^31 - 1 - VPID_BASE: the same file gets the same value in every run with that seed (serial or parallel), two
// files running at the same time get different ones unless their digests collide (probability about n^2 / 4.3e9 for
// n files running at once).
const VPID_BASE = 4194304;
const REAL_PID = process.pid;
const VPID = { current: null };
function startFile(label) {
  const cfg = STATE.config;
  if (!cfg) { VPID.current = null; return; }
  const [h, l] = native.deriveSeedWords(cfg.seed, `vpid\u0000${label}`);
  const range = BigInt(2147483647 - VPID_BASE - 1);
  VPID.current = VPID_BASE + 1 + Number(((BigInt(h >>> 0) << 32n) | BigInt(l >>> 0)) % range);
  // where another process of the run finds the real process behind it (process.kill(V, 0) in a lock file check)
  if (cfg.dir) {
    STATE.quietDepth++;
    try {
      const dir = path.join(cfg.dir, 'vpid');
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, `${VPID.current}.txt`), String(REAL_PID));
    } catch { /* the run directory is gone */ } finally { STATE.quietDepth--; }
  }
}
function endFile() { VPID.current = null; }
/** The real pid behind a virtual one (this process's, or another process of the run's), or `pid`. */
function realPid(pid) {
  if (typeof pid !== 'number' || pid <= VPID_BASE) return pid;
  if (pid === VPID.current) return REAL_PID;
  const cfg = STATE.config;
  if (cfg && cfg.dir) {
    STATE.quietDepth++;
    try { const r = Number(fs.readFileSync(path.join(cfg.dir, 'vpid', `${pid}.txt`), 'utf8')); if (r > 0) return r; } catch { /* none */ } finally { STATE.quietDepth--; }
  }
  return pid;
}
/**
 * The ONE mapping from what test code holds to what the operating system knows (P1 C): every boundary where a pid
 * leaves the process (process.kill, child_process arguments, command strings and environment values, `/proc/<pid>`
 * paths, os.getPriority / os.setPriority) passes its value through it. A number above VPID_BASE that is this file's
 * virtual pid or another process's of the run (`<run dir>/vpid/`) becomes the real pid; a string gets every such
 * number in it replaced where it stands as its own token; anything else is returned as it is.
 * P3 (ironcurtain `/tmp/ironcurtain-arg-validation-${process.pid}` handed to an MCP server): a token is the number
 * between the start / whitespace / `/` `=` `"` `'` `(` `,` / a `-` that itself starts a word (`kill -- -<pid>`) and
 * the end / whitespace / `/` `"` `'` `)` `,` `;` `&` `|`. A number glued to other text (`name-<pid>`, `<pid>.txt`)
 * is part of a name the test made: the child must get the same name, so it is left as it is.
 */
const PID_IN_TEXT = /(?<=^|[\s/="'(,]|(?<!\S)-)[0-9]{7,10}(?=$|[\s/"'),;&|])/g;
function toRealPid(v) {
  if (typeof v === 'number') return realPid(v);
  if (typeof v !== 'string' || v.length < 7 || !/[0-9]{7}/.test(v)) return v;
  return v.replace(PID_IN_TEXT, (m) => {
    const n = Number(m);
    if (n <= VPID_BASE) return m;
    const r = realPid(n);
    return r === n ? m : String(r);
  });
}
/** child_process arguments: the command / file, the argument list, the options' `env` values (a new object). */
function toRealPidArgs(a) {
  if (VPID.current === null && !anyVpid()) return a;
  const out = a.slice();
  if (typeof out[0] === 'string') out[0] = toRealPid(out[0]);
  let opts = -1;
  for (let i = 1; i < out.length; i++) {
    const x = out[i];
    if (Array.isArray(x)) out[i] = x.map((y) => (typeof y === 'string' || typeof y === 'number' ? toRealPid(y) : y));
    else if (x && typeof x === 'object' && opts < 0) {
      opts = i;
      if (x.env && typeof x.env === 'object') {
        const env = mapEnv(x.env);
        if (Object.keys(env).some((k) => env[k] !== x.env[k])) out[i] = { ...x, env };
      }
    }
  }
  // no env option: the child inherits process.env, which may hold a virtual pid the test put there (review
  // 2026-11-24); it gets a mapped copy only when one is found (the options object goes after the argument list)
  if (opts < 0 || !(out[opts].env && typeof out[opts].env === 'object')) {
    const inherited = STATE.quiet(() => ({ ...process.env }));
    const mapped = mapEnv(inherited);
    if (Object.keys(mapped).some((k) => mapped[k] !== inherited[k])) {
      if (opts >= 0) out[opts] = { ...out[opts], env: mapped };
      else {
        const at = Array.isArray(out[1]) ? 2 : 1;
        out.splice(at, typeof out[at] === 'undefined' && out.length > at ? 1 : 0, { env: mapped });
      }
    }
  }
  return out;
}
function mapEnv(env) {
  const o = {};
  for (const k of Object.keys(env)) o[k] = toRealPid(env[k]);
  return o;
}
/** A worker thread runs in the process of the test that started it: it reads that test file's virtual pid. */
function adoptVpid(v) {
  const n = Number(v);
  if (Number.isInteger(n) && n > VPID_BASE) VPID.current = n;
}
// whether this process can meet a virtual pid at all: a file of its own is open, or the run has a table (a process
// with no test file of its own -- a child the test started, a worker between files -- given another's virtual pid)
let tableSeen = false;
function anyVpid() {
  if (tableSeen) return true;
  const cfg = STATE.config;
  if (!cfg || !cfg.dir) return false;
  STATE.quietDepth++;
  try { tableSeen = fs.existsSync(path.join(cfg.dir, 'vpid')); } catch { /* none */ } finally { STATE.quietDepth--; }
  return tableSeen;
}
const PROC_FS = ['readFileSync', 'readFile', 'statSync', 'stat', 'lstatSync', 'lstat', 'existsSync', 'exists',
  'accessSync', 'access', 'readdirSync', 'readdir', 'readlinkSync', 'readlink', 'openSync', 'open', 'realpathSync',
  'createReadStream'];
const PROC_FSP = ['readFile', 'stat', 'lstat', 'access', 'readdir', 'readlink', 'open', 'realpath'];
/** `/proc/<virtual pid>/...` -> `/proc/<real pid>/...` (string paths only). */
function procPath(p) {
  return typeof p === 'string' && p.startsWith('/proc/') ? toRealPid(p) : p;
}
function installPidBoundaries(patcher) {
  if (STATE.__pidBoundaries) return;
  STATE.__pidBoundaries = true;
  const wrapFirst = (obj, n) => {
    const real = obj[n];
    if (typeof real !== 'function') return;
    const w = function (p, ...a) { return real.call(this, procPath(p), ...a); };
    for (const k of Reflect.ownKeys(real)) {
      if (['length', 'name', 'prototype', 'arguments', 'caller'].includes(k)) continue;
      try { Object.defineProperty(w, k, Object.getOwnPropertyDescriptor(real, k)); } catch { /* keep */ }
    }
    try { Object.defineProperty(w, 'name', { value: real.name }); } catch { /* keep */ }
    patcher.set(obj, n, w);
  };
  for (const n of PROC_FS) wrapFirst(fs, n);
  for (const n of PROC_FSP) wrapFirst(fs.promises, n);
  const realGet = os.getPriority;
  if (typeof realGet === 'function') patcher.set(os, 'getPriority', function getPriority(pid, ...a) { return realGet.call(this, toRealPid(pid), ...a); });
  const realSet = os.setPriority;
  if (typeof realSet === 'function') {
    patcher.set(os, 'setPriority', function setPriority(pid, ...a) { return a.length ? realSet.call(this, toRealPid(pid), ...a) : realSet.call(this, pid); });
  }
}
const SRC_DIR = path.resolve(__dirname) + path.sep;
const STRUCTURED = (_e, cs) => cs;
/** The pid was asked for by the test's code (its own or a package's), not by detjs, the runner or Node itself. */
function testCaller(getter) {
  const E = Error;
  const pp = E.prepareStackTrace;
  const lim = E.stackTraceLimit;
  const h = {};
  E.prepareStackTrace = STRUCTURED;
  E.stackTraceLimit = 1;
  try { E.captureStackTrace(h, getter); /* eslint-disable-next-line no-unused-expressions */ h.stack; } finally { E.prepareStackTrace = pp; E.stackTraceLimit = lim; }
  const cs = Array.isArray(h.stack) ? h.stack[0] : null;
  let f = (cs && cs.getFileName && cs.getFileName()) || '';
  if (f.startsWith('file://')) { try { f = require('node:url').fileURLToPath(f); } catch { /* keep */ } }
  if (!f || f.startsWith(SRC_DIR) || f.startsWith('node:') || f.startsWith('internal/')) return false;
  const site = STATE.quiet(() => sites.resolve());
  return site !== null && site !== '<node>';
}

function installProcess(patcher) {
  if (STATE.__factsHooked) return;
  STATE.__factsHooked = true;
  // process.kill on a virtual pid reaches the real process (P1 C)
  const realKill = process.kill;
  if (typeof realKill === 'function') {
    patcher.set(process, 'kill', function kill(pid, ...a) { return realKill.call(this, toRealPid(pid), ...a); });
  }
  for (const n of OS_FACTS) wrap(os, n, `os.${n}`, patcher);
  wrap(os, 'cpus', 'os.cpus', patcher, 'other', (r) => `${r.length}|${r[0] ? r[0].model : ''}`);
  installProcessFacts(patcher, process);
  const perf = globalThis.performance;
  if (perf && typeof perf.eventLoopUtilization === 'function') wrap(perf, 'eventLoopUtilization', 'performance.eventLoopUtilization', patcher);
  // native key generation (entropy Level 0 cannot seed)
  const keyView = (r) => {
    const one = (k) => {
      if (k && typeof k.export === 'function') {
        try { return k.type === 'secret' ? k.export().toString('hex') : JSON.stringify(k.export({ format: 'jwk' })); } catch { return k.type || '?'; }
      }
      return Buffer.isBuffer(k) ? k.toString('hex') : String(k);
    };
    if (r && typeof r === 'object' && 'publicKey' in r) return one(r.publicKey);
    return one(r);
  };
  wrap(nodeCrypto, 'generateKeyPairSync', 'crypto.generateKeyPairSync', patcher, 'entropy', keyView);
  wrap(nodeCrypto, 'generateKeySync', 'crypto.generateKeySync', patcher, 'entropy', keyView);
  wrap(nodeCrypto, 'generatePrimeSync', 'crypto.generatePrimeSync', patcher, 'entropy', (r) => Buffer.from(r).toString('hex'));
  for (const [n, view] of [['generateKeyPair', keyView], ['generateKey', keyView], ['generatePrime', (r) => Buffer.from(r).toString('hex')]]) {
    const real = nodeCrypto[n];
    if (typeof real !== 'function' || real.__detjsFacts) continue;
    const w = function (...a) {
      const i = a.length - 1;
      if (STATE.testId !== null && typeof a[i] === 'function') {
        const cb = a[i];
        const test = STATE.testId;
        a[i] = function (err, ...r) {
          if (!err && STATE.testId === test) recQuietSafe(`crypto.${n}`, view(r.length > 1 ? { publicKey: r[0] } : r[0]), 'entropy');
          return cb.call(this, err, ...r);
        };
      }
      return real.apply(this, a);
    };
    for (const k of Reflect.ownKeys(real)) {
      if (['length', 'name', 'prototype', 'arguments', 'caller'].includes(k)) continue;
      try { Object.defineProperty(w, k, Object.getOwnPropertyDescriptor(real, k)); } catch { /* ignore */ }
    }
    Object.defineProperty(w, '__detjsFacts', { value: true });
    patcher.set(nodeCrypto, n, w);
  }
  for (const make of ['createECDH', 'createDiffieHellman', 'createDiffieHellmanGroup', 'getDiffieHellman']) {
    const real = nodeCrypto[make];
    if (typeof real !== 'function' || real.__detjsFacts) continue;
    const w = function (...a) {
      const o = real.apply(this, a);
      if (o && typeof o.generateKeys === 'function' && !o.__detjsFacts) {
        const g = o.generateKeys;
        o.generateKeys = function (...b) { const r = g.apply(this, b); if (STATE.testId !== null) recQuietSafe(`crypto.${make}.generateKeys`, Buffer.isBuffer(r) ? r.toString('hex') : String(r), 'entropy'); return r; };
      }
      return o;
    };
    Object.defineProperty(w, '__detjsFacts', { value: true });
    patcher.set(nodeCrypto, make, w);
  }
  // on the prototype (as the cache capture's hook): an own property on the instance would shadow it
  const subtle = nodeCrypto.webcrypto && nodeCrypto.webcrypto.subtle;
  const sproto = subtle && Object.getPrototypeOf(subtle);
  if (sproto && typeof sproto.generateKey === 'function' && !sproto.generateKey.__detjsFacts) {
    const real = sproto.generateKey;
    const w = function generateKey(...a) {
      const test = STATE.testId;
      const p = real.apply(this, a);
      if (test !== null) {
        // the key material is usually not extractable: the use of native randomness is what is recorded
        STATE.record('entropy', 'subtle.generateKey', 'native');
        STATE.record('other', 'uncontrolled.entropy', 'subtle.generateKey');
      }
      return p;
    };
    Object.defineProperty(w, '__detjsFacts', { value: true });
    patcher.set(sproto, 'generateKey', w);
  }
  installMkdtemp(patcher);
}

/** Jest's per-file process object: the same facts. */
function installRealm(patcher, g) {
  if (g.process && g.process !== process) installProcessFacts(patcher, g.process);
}

// -- fs.mkdtemp ------------------------------------------------------------------------------------------------------
const CHARS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
let mkdtempN = 0;
STATE.onTestStart.push(() => { mkdtempN = 0; });
require('./concur').register({ name: 'facts', save: () => mkdtempN, restore: (x) => { mkdtempN = x; } });

function suffixes(prefix) {
  const cfg = STATE.config;
  const n = mkdtempN++;
  let k = 0;
  return () => {
    const [h, l] = native.deriveSeedWords(cfg.seed, `${STATE.testId}\u0000mkdtemp\u0000${n}\u0000${k++}\u0000${path.basename(String(prefix))}`);
    let x = (BigInt(h >>> 0) << 32n) | BigInt(l >>> 0);
    let s = '';
    for (let i = 0; i < 6; i++) { s += CHARS[Number(x % 62n)]; x /= 62n; }
    return s;
  };
}

function installMkdtemp(patcher) {
  const realSync = fs.mkdtempSync;
  const realCb = fs.mkdtemp;
  const realP = fs.promises && fs.promises.mkdtemp;
  const inTest = () => STATE.testId !== null && STATE.quietDepth === 0 && STATE.config;
  const name = (prefix, opts) => {
    const enc = typeof opts === 'string' ? opts : opts && opts.encoding;
    return { pre: Buffer.isBuffer(prefix) ? prefix.toString() : String(prefix), enc };
  };
  const out = (p, enc) => (enc === 'buffer' ? Buffer.from(p) : p);
  if (typeof realSync === 'function') {
    patcher.set(fs, 'mkdtempSync', function mkdtempSync(prefix, opts) {
      if (!inTest() || prefix instanceof URL) return realSync.call(this, prefix, opts);
      const { pre, enc } = name(prefix, opts);
      const next = suffixes(pre);
      for (let i = 0; i < 100; i++) {
        const p = pre + next();
        try {
          fs.mkdirSync(p, 0o700);
          STATE.record('fs', 'fs.mkdtemp', path.basename(p));
          return out(p, enc);
        } catch (e) { if (e.code !== 'EEXIST') throw e; }
      }
      return realSync.call(this, prefix, opts);
    });
  }
  if (typeof realP === 'function') {
    patcher.set(fs.promises, 'mkdtemp', async function mkdtemp(prefix, opts) {
      if (!inTest() || prefix instanceof URL) return realP.call(this, prefix, opts);
      const { pre, enc } = name(prefix, opts);
      const next = suffixes(pre);
      const site = STATE.testId;
      for (let i = 0; i < 100; i++) {
        const p = pre + next();
        try {
          await fs.promises.mkdir(p, 0o700);
          if (STATE.testId === site) STATE.record('fs', 'fs.mkdtemp', path.basename(p));
          return out(p, enc);
        } catch (e) { if (e.code !== 'EEXIST') throw e; }
      }
      return realP.call(this, prefix, opts);
    });
  }
  if (typeof realCb === 'function') {
    patcher.set(fs, 'mkdtemp', function mkdtemp(prefix, opts, cb) {
      if (typeof opts === 'function') { cb = opts; opts = undefined; }
      if (typeof cb !== 'function' || !inTest() || prefix instanceof URL) return realCb.call(this, prefix, opts, cb);
      fs.promises.mkdtemp(prefix, opts).then((p) => cb(null, p), (e) => cb(e));
      return undefined;
    });
  }
}

const currentVpid = () => VPID.current;
module.exports = { installProcess, installRealm, installPidBoundaries, startFile, endFile, adoptVpid, currentVpid, toRealPidArgs };
