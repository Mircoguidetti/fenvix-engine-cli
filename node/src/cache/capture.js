'use strict';
// Input capture for the cache with proof (`--det-cache`), one instance per process or worker thread.
//
// While tests run it records, in an ordered log, every input the code could depend on:
//
// * code: the modules loaded (Vitest's module runner graph, Node's own loader through `module.registerHooks`,
//   Jest's runtime registries), each with the bytes it had when it was loaded, plus the nearest package.json of
//   each project module (module resolution reads it);
// * files read (`fs` content reads and read-write opens: digest of the content; paths found missing; directory
//   listings; existence checks; symbolic link targets), native addons loaded (`process.dlopen`);
// * files written (outputs: a read of a file another test file or the start-up code wrote is never cached);
// * environment variables read (`process.env` get / `in` / descriptor; enumerating it records `*`) and machine
//   facts read through `os` (hostname, user, home and temporary directories, CPUs, memory, ...);
// * events that make a test never cacheable: a child process, a worker thread, a socket connection (loopback and
//   Unix sockets included; external hosts are Level 0's: blocked or replayed), a UDP socket, OS entropy, reads of
//   /proc, /sys or /dev, network recording;
// * whether the clock was read (the epoch is then an input).
//
// Inputs are cumulative: the inputs of a test are everything logged in its process (Vitest: its worker; Jest: its
// test file) up to the end of the test, so state carried from earlier tests or from the file's collection is
// covered. The main side (`proof.js`) turns the logs into store entries.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const url = require('node:url');
const native = require('../native');
const { STATE } = require('../state');

const SHELL_DIR = path.resolve(__dirname, '..') + path.sep; // node/src/
const ENGINE_DIR = path.resolve(__dirname, '..', '..') + path.sep; // node/
// detjs' own driver code (runner shells, session, cache): infrastructure; its wrappers of patched APIs are not
const DETJS_DRIVER = /[\\/]src[\\/](?:vitest|jest)[\\/]|[\\/]src[\\/](?:session|controls|register)\.js$|[\\/]src[\\/]cache[\\/](?:proof|remote|runtime-id)\.js$|[\\/]bin[\\/]detjs\.js$/;
const INFRA = /[\\/]node_modules[\\/](?:\.pnpm[\\/][^\\/]+[\\/]node_modules[\\/])?(?:vitest|@vitest|vite|vite-node|tinypool|tinyspy|jest-[a-z-]+|@jest|jest|expect|babel-jest|ts-jest|@swc|source-map-support|pretty-format|esbuild|rollup|@rollup|rolldown|@rolldown|oxc-[a-z-]+|@oxc-[a-z-]+|lightningcss|postcss|@babel|@ampproject|magic-string|es-module-lexer|tsx|@esbuild|graceful-fs|write-file-atomic|signal-exit|exit-x|istanbul-[a-z-]+|@istanbuljs|v8-to-istanbul|chokidar|fdir|picomatch|tinyglobby|fast-glob|micromatch|resolve|enhanced-resolve|import-local|jest-haste-map|walker|fb-watchman)[\\/]/;
// a Vite config bundled to a temporary module (it is user code: `vitest.config.ts.timestamp-<n>-<hash>.mjs`)
const BUNDLED_CONFIG = /\.timestamp-\d+(?:-[0-9a-f]+)?\.m?[jt]s$/;
const OWN_ENV = /^(DETJS($|_)|FENVIX_CACHE_)/;
const O_ACC = fs.constants.O_RDONLY | fs.constants.O_WRONLY | fs.constants.O_RDWR;

const MACHINE = {
  hostname: () => os.hostname(),
  userInfo: () => { try { const u = os.userInfo(); return `${u.username}|${u.uid}|${u.gid}|${u.homedir}|${u.shell}`; } catch { return '?'; } },
  homedir: () => os.homedir(),
  tmpdir: () => os.tmpdir(),
  networkInterfaces: () => JSON.stringify(os.networkInterfaces()),
  cpus: () => { const c = os.cpus(); return `${c.length}|${c[0] ? c[0].model : ''}`; },
  availableParallelism: () => String(os.availableParallelism ? os.availableParallelism() : os.cpus().length),
  totalmem: () => String(os.totalmem()),
  release: () => os.release(),
  version: () => (os.version ? os.version() : ''),
  machine: () => (os.machine ? os.machine() : ''),
  getPriority: () => { try { return String(os.getPriority()); } catch { return '?'; } },
};

/** Values of the machine facts, as environment-like inputs (`~os.<name>`). */
function machineFacts() {
  const out = {};
  for (const [k, f] of Object.entries(MACHINE)) {
    try { out[`~os.${k}`] = String(f()); } catch { out[`~os.${k}`] = '?'; }
  }
  return out;
}

function toPath(p) {
  if (p === undefined || p === null) return null;
  if (typeof p === 'number') return null; // descriptor: recorded when it was opened
  let s;
  if (typeof p === 'string') s = p;
  else if (Buffer.isBuffer(p)) s = p.toString('utf8');
  else if (p instanceof URL || (typeof p === 'object' && typeof p.href === 'string')) {
    if (p.protocol !== 'file:') return null;
    try { s = url.fileURLToPath(p.href); } catch { return null; }
  } else return null;
  if (!s) return null;
  if (s.startsWith('file://')) {
    try { s = url.fileURLToPath(s); } catch { return null; }
  }
  return path.resolve(s);
}

function flagsOf(flags, dflt) {
  if (flags === undefined || flags === null) flags = dflt;
  if (typeof flags === 'number') {
    const acc = flags & O_ACC;
    const reads = acc === fs.constants.O_RDONLY || acc === fs.constants.O_RDWR;
    const writes = acc === fs.constants.O_WRONLY || acc === fs.constants.O_RDWR || Boolean(flags & fs.constants.O_CREAT);
    return { reads, writes, trunc: Boolean(flags & fs.constants.O_TRUNC) };
  }
  const m = String(flags);
  return { reads: m.includes('r') || m.includes('+'), writes: /[wax+]/.test(m), trunc: m.includes('w') };
}

const structured = (_e, cs) => cs;

class Capture {
  constructor() {
    this.active = false;
    this.role = 'worker';
    this.root = null;
    this.rootSep = null;
    this.ctx = ''; // '' global (main) / 'f' file / 't' test
    this.label = ''; // writer label of the running file ('' = start-up / global)
    this.log = []; // file log: [kind, ...]
    this.global = []; // global log (main process)
    this.seen = new Set(); // dedupe within the file log
    this.gseen = new Set();
    this.memo = new Map(); // kind+abs -> dep
    this.written = new Map(); // abs -> Set(labels)
    this.modsSeen = new Set();
    this.pkgMemo = new Map();
    this.nativeLoads = new Set();
    this.busy = 0;
    this.tests = [];
    this.fileStart = 0;
    this.mainAnyReads = false; // Vitest main process: in-root reads by any caller are global candidates
    this.startup = []; // finished start-up processes [argv, cwd, status, stdout digest, stderr digest]
    this.notes = new Set();
    this.phase = 'run';
    // content-addressed caches of tools (a cached result equals recomputing it): jiti's transpile cache; the
    // runners' own caches are added by the shells (Jest cacheDirectory, Vite cacheDir); more with DETJS_CACHE_SKIP_DIRS
    const tmp = os.tmpdir();
    this.skipDirs = [path.join(tmp, 'jiti'), path.join(tmp, 'node-jiti'),
      ...(process.env.DETJS_CACHE_SKIP_DIRS || '').split(path.delimiter).filter(Boolean)].map((d) => path.resolve(d) + path.sep);
  }

  /** Directories whose files are runner caches (never inputs); inherited by workers. */
  addSkipDir(d) {
    if (!d) return;
    const x = path.resolve(d) + path.sep;
    if (!this.skipDirs.includes(x)) this.skipDirs.push(x);
    process.env.DETJS_CACHE_SKIP_DIRS = this.skipDirs.join(path.delimiter);
  }

  // -- set-up --------------------------------------------------------------------------------------------------
  install({ role, root, mainAnyReads }) {
    if (this.active) return;
    this.active = true;
    this.role = role;
    this.root = fs.realpathSync(root);
    this.rootSep = this.root + path.sep;
    this.rootAlt = path.resolve(root) + path.sep; // the root as given (may differ from its real path)
    this.mainAnyReads = Boolean(mainAnyReads);
    this.tmp = (() => { try { return fs.realpathSync(os.tmpdir()); } catch { return os.tmpdir(); } })();
    this.nullDev = path.resolve(os.devNull || '/dev/null');
    try {
      const nm = fs.realpathSync(path.join(this.root, 'node_modules'));
      if (!this.inRoot(nm)) this.nmReal = nm + path.sep;
    } catch { /* none */ }
    installFs(this);
    installEnv(this, process);
    installOs(this);
    installSpawn(this);
    installNet(this);
    installDlopen(this);
    installLoaderHooks(this);
    STATE.onEvent = (source, value) => this.levelEvent(source, value);
    require('node:module').syncBuiltinESMExports();
  }

  /** Wrap again what Level 0 replaced after the capture was installed (Jest installs the controls per file). */
  reinstall() {
    if (!this.active) return;
    installFs(this);
    installEnv(this, process);
    installOs(this);
    installSpawn(this);
    installNet(this);
    installDlopen(this);
    require('node:module').syncBuiltinESMExports();
  }

  setCtx(ctx, label) {
    this.ctx = ctx;
    if (label !== undefined) this.label = label;
  }

  /** Jest: each test file has its own module registry and environment copy, so its log starts afresh. */
  resetFile() {
    this.log = [];
    this.seen = new Set();
    this.tests = [];
    this.modsSeen = new Set();
  }

  // -- classification ------------------------------------------------------------------------------------------
  inRoot(abs) {
    return abs.startsWith(this.rootSep) || abs === this.root || (this.rootAlt !== this.rootSep && abs.startsWith(this.rootAlt));
  }

  rel(abs) {
    if (abs.startsWith(this.rootSep)) return abs.slice(this.rootSep.length).split(path.sep).join('/');
    if (this.rootAlt !== this.rootSep && abs.startsWith(this.rootAlt)) return abs.slice(this.rootAlt.length).split(path.sep).join('/');
    return abs === this.root ? '.' : abs;
  }

  /** 'skip' (covered elsewhere or detjs' own), 'root' (project file), 'outside', 'proc'. */
  where(abs) {
    if (abs === this.nullDev) return 'skip';
    for (const d of this.skipDirs) if (abs.startsWith(d) || abs + path.sep === d) return 'skip'; // tool caches
    if (this.inRoot(abs)) {
      const r = this.rel(abs);
      if (r === '.detjs' || r.startsWith('.detjs/') || r.startsWith('node_modules/') || r.includes('/node_modules/')) return 'skip';
      return 'root';
    }
    // installed packages reached through a node_modules link that leaves the project: in the runtime identity
    if (this.nmReal && abs.startsWith(this.nmReal)) return 'skip';
    if (abs.includes(`${path.sep}node_modules${path.sep}.detjs${path.sep}`)) return 'skip';
    if (abs.startsWith('/proc/') || abs.startsWith('/sys/') || abs.startsWith('/dev/') || abs === '/proc' || abs === '/sys') return 'proc';
    if (abs.startsWith(ENGINE_DIR)) return 'skip'; // detjs itself: in the configuration digest
    return 'outside';
  }

  /** 'user' | 'infra' from the calling frames: a project frame anywhere decides 'user'. */
  caller() {
    const E = Error;
    const pp = E.prepareStackTrace;
    const lim = E.stackTraceLimit;
    E.prepareStackTrace = structured;
    E.stackTraceLimit = 60;
    const h = {};
    try {
      E.captureStackTrace(h, this.caller);
      // eslint-disable-next-line no-unused-expressions
      h.stack;
    } finally {
      E.prepareStackTrace = pp;
      E.stackTraceLimit = lim;
    }
    const frames = Array.isArray(h.stack) ? h.stack : [];
    let infra = false;
    for (const cs of frames) {
      let f = cs.getFileName && cs.getFileName();
      if (!f) continue;
      if (f.startsWith('file://')) { try { f = url.fileURLToPath(f); } catch { continue; } }
      const q = f.indexOf('?');
      if (q >= 0) f = f.slice(0, q);
      if (f.startsWith(ENGINE_DIR) && DETJS_DRIVER.test(f)) { infra = true; continue; }
      if (f.startsWith('node:') || f.startsWith('internal/') || f.startsWith(SHELL_DIR) || !f.includes('/')) continue;
      if (BUNDLED_CONFIG.test(f)) return 'user';
      if (INFRA.test(f)) { infra = true; continue; }
      if (this.inRoot(f) && !f.includes(`${path.sep}node_modules${path.sep}`)) return 'user';
    }
    // no project frame and no runner frame (callback chains inside Node): in the main process, project code that
    // calls fs has its own frame on the stack, so such chains are the runner's (Vitest's async cleanup); in a test
    // process they may be a library working for the test, so they count
    return infra || this.role === 'main' ? 'infra' : 'user';
  }

  // -- logging -------------------------------------------------------------------------------------------------
  add(item, global) {
    const key = item.join('\u0000');
    if (global) {
      if (this.gseen.has(key)) return;
      this.gseen.add(key);
      this.global.push(item);
    } else {
      if (this.seen.has(key)) return;
      this.seen.add(key);
      this.log.push(item);
    }
  }

  /** Global context of the main process: decided by the caller (runner infrastructure is not an input). */
  get isGlobal() {
    return this.role === 'main' && this.ctx === '';
  }

  flag(flag, detail) {
    if (this.isGlobal) {
      if (this.caller() !== 'user') return;
      this.add(['flag', flag, String(detail || '')], true);
    } else {
      this.add(['flag', flag, String(detail || '')], false);
    }
  }

  dep(kind, abs) {
    const k = kind + abs;
    let d = this.memo.get(k);
    if (d === undefined) {
      if (kind === 'f') {
        const x = native.fileDigest(abs);
        d = x !== null && x !== undefined ? `f:${x}` : (native.statKind(abs) === 'missing' ? 'missing' : `s:${native.statKind(abs)}`);
      } else if (kind === 'd') {
        const x = native.listingDigest(abs);
        d = x !== null && x !== undefined ? `d:${x}` : 'missing';
      } else if (kind === 's') {
        d = `s:${native.statKind(abs)}`;
      } else if (kind === 'l') {
        d = native.linkDep(abs);
      }
      this.memo.set(k, d);
    }
    return d;
  }

  /** A read of `p` (kind f content, d listing, s existence, l link target). */
  read(p, kind) {
    if (!this.active || this.busy) return;
    const abs = toPath(p);
    if (abs === null) return;
    this.busy++;
    try {
      const w = this.where(abs);
      if (w === 'skip') return;
      const global = this.isGlobal;
      if (w === 'proc') {
        if (abs.startsWith('/dev/std') || abs.startsWith('/dev/fd/') || abs === '/dev/tty') return;
        if (abs === '/proc/self/exe') return; // the node binary: in the runtime identity
        if (abs !== '/proc/version' && abs !== '/proc/sys/kernel/osrelease') {
          if (global && this.caller() !== 'user') return;
          this.add(['flag', 'proc', abs], global);
          return;
        }
        // the kernel version: the same for every process of a machine, an input like a file
      }
      if (global) {
        // the main process: runner and bundler infrastructure reads everything; only reads that can change what
        // tests see are inputs (Vitest: file contents and missing paths in the project, whoever reads them,
        // except the test modules themselves, removed at the end)
        const user = this.caller() === 'user';
        if (!user) {
          // start-up (configuration, globalSetup): the contents of project files and the paths probed and found
          // missing; during the run, only missing probes (a file created later could shadow a resolved module)
          if (!(this.mainAnyReads && w === 'root' && (kind === 'f' || kind === 's'))) return;
          const d = this.dep('f', abs);
          if (this.phase === 'run' || kind === 's') {
            if (d !== 'missing') return;
          }
          this.add(['data', this.key(abs), d, 'infra'], true);
          return;
        }
      } else if (w === 'outside' && this.caller() !== 'user') {
        return;
      }
      const writers = this.written.get(abs);
      if (writers) {
        // a file this process wrote: an output of the writer, not an input; another file's output is a hidden
        // channel between files
        if (writers.size === 1 && writers.has(this.label)) return;
        this.add(['flag', 'rw', `${this.key(abs)} written by ${[...writers].filter((x) => x !== this.label).join(',') || 'start-up'}`], global);
        return;
      }
      this.add(['data', this.key(abs), this.dep(kind, abs)], global);
    } finally {
      this.busy--;
    }
  }

  wrote(p) {
    if (!this.active || this.busy) return;
    const abs = toPath(p);
    if (abs === null) return;
    this.busy++;
    try {
      const w = this.where(abs);
      if (w === 'skip' || w === 'proc') return;
      const global = this.isGlobal;
      if ((global || w === 'outside') && this.caller() !== 'user') return;
      let s = this.written.get(abs);
      if (!s) this.written.set(abs, (s = new Set()));
      s.add(global ? '' : this.label);
      if (global && process.env.DETJS_CACHE_DEBUG) process.stderr.write(`detjs cache debug: start-up write ${abs}\n${new Error().stack}\n`);
      this.add(['write', this.key(abs)], global);
      for (const k of ['f', 'd', 's', 'l']) this.memo.delete(k + abs);
      this.memo.delete(`d${path.dirname(abs)}`);
    } finally {
      this.busy--;
    }
  }

  key(abs) {
    return this.inRoot(abs) ? this.rel(abs) : abs;
  }

  env(name) {
    if (!this.active || this.busy || typeof name !== 'string' || OWN_ENV.test(name)) return;
    const global = this.isGlobal;
    if (global || name === '*' || this.role === 'main') {
      // the main process reads its environment for itself, and runners copy the whole environment (workers,
      // child processes, Jest's per-file copy): only project code's reads count there
      const seen = global ? this.gseen : this.seen;
      if (seen.has(`env\u0000${name}`)) return;
      this.busy++;
      try {
        if (this.caller() !== 'user') return;
      } finally { this.busy--; }
    }
    if (name === '*' && process.env.DETJS_CACHE_DEBUG) process.stderr.write(`detjs cache debug: env enumerated (${global ? 'global' : this.ctx})\n${new Error().stack}\n`);
    this.add(['env', name], global);
  }

  levelEvent(source, value) {
    if (!this.active || this.isGlobal) return;
    if (source === 'time') this.add(['clock'], false);
    else if (source === 'entropy') this.add(['flag', 'entropy', ''], false);
    else if (source === 'net' && typeof value === 'string' && value.includes('record#')) this.add(['flag', 'net-record', value], false);
    else if (source === 'net' && typeof value === 'string' && value.includes('replay')) this.add(['net-replay'], false);
  }

  // -- code ----------------------------------------------------------------------------------------------------
  module(file) {
    if (!file || typeof file !== 'string') return;
    let f = file;
    if (f.startsWith('file://')) { try { f = url.fileURLToPath(f.split('?')[0]); } catch { return; } }
    if (f.startsWith('/@fs/')) f = f.slice(4);
    const q = f.search(/[?#]/);
    if (q > 0) f = f.slice(0, q);
    if (!path.isAbsolute(f) || f.includes('\0')) return;
    if (this.modsSeen.has(f)) return;
    this.modsSeen.add(f);
    const w = this.where(f);
    if (w === 'skip' || w === 'proc') return;
    this.busy++;
    try {
      if (w === 'outside') {
        this.add(['data', f, this.dep('f', f)], this.isGlobal);
        return;
      }
      const d = native.fileDigest(f);
      if (d === null || d === undefined) return; // virtual module or vanished
      this.add(['code', this.rel(f), d], this.isGlobal);
      // resolution: a new file with the same name stem could shadow this module (extension probing: m.mjs before
      // m.ts; m.ts before m/index.ts); the entries sharing the stem are an input
      const stem = (dir, base) => {
        const k = path.join(dir, base);
        const x = native.stemListingDigest(k);
        this.add(['data', this.rel(k), x === null || x === undefined ? 'missing' : `g:${x}`], this.isGlobal);
      };
      const base = path.basename(f).replace(/\.[^.]*$/, '');
      stem(path.dirname(f), base);
      if (base === 'index' && this.inRoot(path.dirname(f))) stem(path.dirname(path.dirname(f)), path.basename(path.dirname(f)));
      const pkg = this.nearestPackageJson(path.dirname(f));
      if (pkg) {
        // resolution reads only some fields (exports, main, type, ...): those are the input; a test that reads or
        // imports the package.json itself depends on its whole content through that read
        const x = native.packageResolutionDigest(pkg);
        this.add(['data', this.rel(pkg), x === null || x === undefined ? this.dep('f', pkg) : `p:${x}`], this.isGlobal);
      }
    } finally {
      this.busy--;
    }
  }

  nearestPackageJson(dir) {
    if (this.pkgMemo.has(dir)) return this.pkgMemo.get(dir);
    let out = null;
    const p = path.join(dir, 'package.json');
    if (native.statKind(p) === 'file') out = p;
    else if (this.inRoot(path.dirname(dir) + path.sep) && dir !== this.root) out = this.nearestPackageJson(path.dirname(dir));
    this.pkgMemo.set(dir, out);
    return out;
  }

  /** Modules loaded so far (Vitest worker state, CommonJS cache, native loader). */
  scanModules(extra) {
    const st = globalThis.__vitest_worker__;
    if (st) {
      const em = st.evaluatedModules;
      if (em && em.idToModuleMap) {
        for (const m of em.idToModuleMap.values()) this.module(m.file || m.id);
      }
      const mc = st.moduleCache;
      if (mc && typeof mc.keys === 'function') {
        for (const k of mc.keys()) this.module(k);
      }
    }
    try {
      for (const k of Object.keys(require.cache)) this.module(k);
    } catch { /* no cache */ }
    for (const f of this.nativeLoads) this.module(f);
    if (extra) for (const f of extra) this.module(f);
  }

  // -- tests ---------------------------------------------------------------------------------------------------
  testEnd(id, outcome, duration, fingerprint, extraModules) {
    this.scanModules(extraModules);
    this.tests.push({ id, outcome, duration, fingerprint: fingerprint || '', upto: this.log.length });
  }

  /** The log of the file just finished, for the main side. */
  fileCapture(info, extraModules) {
    this.scanModules(extraModules);
    return { ...info, items: this.log.slice(), tests: this.tests.slice(), upto: this.log.length, pid: process.pid, notes: [...this.notes] };
  }

  beginFileTests() {
    this.tests = [];
  }
}

// ---------------------------------------------------------------------------------------------------------------
function wrapFn(cap, obj, name, before, after) {
  const real = obj && obj[name];
  if (typeof real !== 'function' || real.__detjsCache) return;
  const w = function (...args) {
    if (cap.active && !cap.busy) {
      try { before(args); } catch { /* never break the call */ }
    }
    const r = real.apply(this, args);
    if (after && cap.active && !cap.busy) {
      try { after(args, r); } catch { /* ignore */ }
    }
    return r;
  };
  for (const k of Reflect.ownKeys(real)) {
    if (k === 'length' || k === 'name' || k === 'prototype' || k === 'arguments' || k === 'caller') continue;
    try { Object.defineProperty(w, k, Object.getOwnPropertyDescriptor(real, k)); } catch { /* ignore */ }
  }
  Object.defineProperty(w, '__detjsCache', { value: true });
  Object.defineProperty(w, 'name', { value: real.name, configurable: true });
  try { obj[name] = w; } catch { /* read-only */ }
  if (obj[name] !== w) {
    try { Object.defineProperty(obj, name, { value: w, writable: true, configurable: true, enumerable: true }); } catch { /* keep */ }
  }
}

function installFs(cap) {
  const P = fs.promises;
  const read = (k) => (a) => cap.read(a[0], k);
  const write0 = (a) => cap.wrote(a[0]);
  const write01 = (a) => { cap.wrote(a[0]); cap.wrote(a[1]); };
  const open = (dflt) => (a) => {
    const fl = flagsOf(a[1] && typeof a[1] === 'object' && !Buffer.isBuffer(a[1]) ? a[1].flags : a[1], dflt);
    if (fl.reads && !fl.trunc) cap.read(a[0], 'f');
    if (fl.writes) cap.wrote(a[0]);
  };
  for (const [o, names, fn] of [
    [fs, ['readFileSync', 'readFile'], read('f')],
    [P, ['readFile'], read('f')],
    [fs, ['existsSync', 'exists', 'accessSync', 'access', 'statSync', 'stat', 'lstatSync', 'lstat', 'realpathSync', 'realpath'], read('s')],
    [P, ['access', 'stat', 'lstat', 'realpath'], read('s')],
    [fs, ['readdirSync', 'readdir', 'opendirSync', 'opendir'], read('d')],
    [P, ['readdir', 'opendir'], read('d')],
    [fs, ['readlinkSync', 'readlink'], read('l')],
    [P, ['readlink'], read('l')],
    [fs, ['writeFileSync', 'writeFile', 'appendFileSync', 'appendFile', 'unlinkSync', 'unlink', 'rmSync', 'rm', 'rmdirSync', 'rmdir',
      'mkdirSync', 'mkdir', 'truncateSync', 'truncate', 'utimesSync', 'utimes', 'chmodSync', 'chmod', 'createWriteStream'], write0],
    [P, ['writeFile', 'appendFile', 'unlink', 'rm', 'rmdir', 'mkdir', 'truncate', 'utimes', 'chmod'], write0],
    [fs, ['renameSync', 'rename'], write01],
    [P, ['rename'], write01],
  ]) {
    for (const n of names) wrapFn(cap, o, n, fn);
  }
  // copy / link / symlink: the source is read, the destination written
  for (const [o, names] of [[fs, ['copyFileSync', 'copyFile', 'cpSync', 'cp']], [P, ['copyFile', 'cp']]]) {
    for (const n of names) wrapFn(cap, o, n, (a) => { cap.read(a[0], n.startsWith('cp') ? 's' : 'f'); cap.wrote(a[1]); });
  }
  for (const [o, names] of [[fs, ['symlinkSync', 'symlink', 'linkSync', 'link']], [P, ['symlink', 'link']]]) {
    for (const n of names) wrapFn(cap, o, n, (a) => cap.wrote(a[1]));
  }
  wrapFn(cap, fs, 'openSync', open('r'));
  wrapFn(cap, fs, 'open', open('r'));
  wrapFn(cap, P, 'open', open('r'));
  wrapFn(cap, fs, 'createReadStream', (a) => cap.read(a[0], 'f'));
  // mkdtemp: the directory created is an output of the caller
  wrapFn(cap, fs, 'mkdtempSync', () => {}, (_a, r) => cap.wrote(r));
  const realMk = fs.mkdtemp;
  if (typeof realMk === 'function' && !realMk.__detjsCache) {
    const mk = function mkdtemp(prefix, options, cb) {
      if (typeof options === 'function') { cb = options; options = undefined; }
      if (typeof cb !== 'function') return realMk.call(fs, prefix, options, cb);
      return realMk.call(fs, prefix, options, (err, dir) => { if (!err) cap.wrote(dir); cb(err, dir); });
    };
    Object.defineProperty(mk, '__detjsCache', { value: true });
    fs.mkdtemp = mk;
  }
  wrapFn(cap, fs, 'mkdtempDisposableSync', () => {}, (_a, r) => r && cap.wrote(r.path));
  const realPMkD = P.mkdtempDisposable;
  if (typeof realPMkD === 'function' && !realPMkD.__detjsCache) {
    const f = async function mkdtempDisposable(...a) { const r = await realPMkD.apply(P, a); if (r && r.path) cap.wrote(r.path); return r; };
    Object.defineProperty(f, '__detjsCache', { value: true });
    P.mkdtempDisposable = f;
  }
  const realPMk = P.mkdtemp;
  if (typeof realPMk === 'function' && !realPMk.__detjsCache) {
    const pmk = async function mkdtemp(...a) { const dir = await realPMk.apply(P, a); cap.wrote(dir); return dir; };
    Object.defineProperty(pmk, '__detjsCache', { value: true });
    P.mkdtemp = pmk;
  }
}

function installEnv(cap, proc) {
  const env = proc.env;
  if (env && env.__detjsCache) return;
  const handler = {
    get(t, k) {
      if (typeof k === 'string' && k !== '__detjsCache') cap.env(k);
      return k === '__detjsCache' ? true : Reflect.get(t, k);
    },
    has(t, k) {
      if (typeof k === 'string') cap.env(k);
      return Reflect.has(t, k);
    },
    getOwnPropertyDescriptor(t, k) {
      if (typeof k === 'string') cap.env(k);
      return Reflect.getOwnPropertyDescriptor(t, k);
    },
    ownKeys(t) {
      cap.env('*');
      return Reflect.ownKeys(t);
    },
    set(t, k, v) { t[k] = v; return true; },
    deleteProperty(t, k) { delete t[k]; return true; },
  };
  try {
    const p = new Proxy(env, handler);
    proc.env = p;
    if (proc.env !== p) Object.defineProperty(proc, 'env', { value: p, writable: true, configurable: true, enumerable: true });
  } catch { cap.notes.add('process.env not replaceable: environment reads not captured'); }
}

// facts that change from one call to the next: a test that reads them is not cached
const VOLATILE_MACHINE = ['freemem', 'loadavg', 'uptime', 'resourceUsage'];

function installOs(cap) {
  for (const k of VOLATILE_MACHINE) {
    if (typeof os[k] === 'function') wrapFn(cap, os, k, () => cap.flag('machine', `os.${k}`));
  }
  for (const k of Object.keys(MACHINE)) {
    if (typeof os[k] !== 'function') continue;
    wrapFn(cap, os, k, () => {
      if (k === 'homedir') cap.env('HOME');
      if (k === 'tmpdir') { cap.env('TMPDIR'); cap.env('TMP'); cap.env('TEMP'); }
      cap.env(`~os.${k}`);
    });
  }
}

function argvOf(file, args) {
  return [String(file), ...(Array.isArray(args) ? args.map(String) : [])].join(' ').slice(0, 300);
}

function installSpawn(cap) {
  const cp = require('node:child_process');
  for (const n of ['spawn', 'exec', 'execFile', 'fork']) {
    wrapFn(cap, cp, n, (a) => cap.flag('spawn', `${n} ${argvOf(a[0], a[1])}`));
  }
  for (const n of ['spawnSync', 'execSync', 'execFileSync']) {
    const real = cp[n];
    if (typeof real !== 'function' || real.__detjsCache) continue;
    const w = function (...a) {
      if (!cap.active || cap.busy) return real.apply(this, a);
      if (!cap.isGlobal) {
        cap.flag('spawn', `${n} ${argvOf(a[0], Array.isArray(a[1]) ? a[1] : [])}`);
        return real.apply(this, a);
      }
      cap.busy++;
      let user;
      try { user = cap.caller() === 'user'; } finally { cap.busy--; }
      if (!user) return real.apply(this, a);
      // start-up (main process, outside tests): a process that finished and gave back its output is keyed by
      // what it gave back (argv, cwd, exit code, output); any other use of a process taints every test
      let r;
      let err;
      try { r = real.apply(this, a); } catch (e) { err = e; }
      const res = err || r;
      const out = (v) => (v === undefined || v === null ? '-' : native.digest(Buffer.isBuffer(v) ? v : Buffer.from(String(v))));
      const opts = a.find((x, i) => i > 0 && x && typeof x === 'object' && !Array.isArray(x)) || {};
      const status = err ? (err.status ?? 'error') : (r && typeof r === 'object' && 'status' in r ? r.status : 0);
      const stdout = err ? err.stdout : (r && typeof r === 'object' && !Buffer.isBuffer(r) ? r.stdout : r);
      const stderr = err ? err.stderr : (r && typeof r === 'object' && !Buffer.isBuffer(r) ? r.stderr : undefined);
      if (opts.stdio === 'inherit' || (Array.isArray(opts.stdio) && opts.stdio.some((s) => s !== 'pipe' && s !== undefined && s !== null && s !== 'ignore'))) {
        cap.add(['flag', 'spawn', `start-up ${n} ${argvOf(a[0], Array.isArray(a[1]) ? a[1] : [])} with a channel other than pipes`], true);
      } else {
        cap.startup.push([n, argvOf(a[0], Array.isArray(a[1]) ? a[1] : []), String(opts.cwd || process.cwd()), String(status), out(stdout), out(stderr)]);
      }
      if (err) throw err;
      return res;
    };
    for (const k of Reflect.ownKeys(real)) {
      if (['length', 'name', 'prototype', 'arguments', 'caller'].includes(k)) continue;
      try { Object.defineProperty(w, k, Object.getOwnPropertyDescriptor(real, k)); } catch { /* ignore */ }
    }
    Object.defineProperty(w, '__detjsCache', { value: true });
    cp[n] = w;
  }
  const wt = require('node:worker_threads');
  const RealWorker = wt.Worker;
  if (RealWorker && !RealWorker.__detjsCache) {
    class Worker extends RealWorker {
      constructor(file, opts) {
        if (cap.active && !cap.busy) {
          try { cap.flag('worker', `worker thread ${String(file).slice(0, 200)}`); } catch { /* ignore */ }
        }
        super(file, opts);
      }
    }
    Object.defineProperty(Worker, '__detjsCache', { value: true });
    try { wt.Worker = Worker; } catch { /* read-only */ }
  }
}

function installNet(cap) {
  const net = require('node:net');
  const { isLocalName } = require('../network');
  const allow = new Set(String(process.env.DETJS_ALLOW_HOSTS || '').split(',').map((s) => s.trim().toLowerCase()).filter(Boolean));
  wrapFn(cap, net.Socket.prototype, 'connect', (a) => {
    let o = a[0];
    if (Array.isArray(o)) o = o[0];
    let target;
    if (o && typeof o === 'object') target = o.path ? { path: o.path } : { host: o.host || 'localhost', port: o.port };
    else if (typeof o === 'string' && Number.isNaN(Number(o))) target = { path: o };
    else target = { host: typeof a[1] === 'string' ? a[1] : 'localhost', port: o };
    if (target.path) {
      if (String(target.path).includes('detjs-replay')) return; // detjs' own replay server
      cap.flag('connect', `unix socket ${target.path}`);
    } else if (isLocalName(target.host) || allow.has(String(target.host).toLowerCase())) {
      cap.flag('connect', `${target.host}:${target.port}`);
    }
    // other hosts: Level 0's closed network blocks or replays them (replay keeps the test cacheable)
  });
  const dgram = require('node:dgram');
  wrapFn(cap, dgram.Socket.prototype, 'send', () => cap.flag('udp', 'dgram send'));
  wrapFn(cap, dgram.Socket.prototype, 'connect', () => cap.flag('udp', 'dgram connect'));
}

function installDlopen(cap) {
  wrapFn(cap, process, 'dlopen', (a) => {
    const f = a[1];
    if (typeof f === 'string') cap.nativeLoads.add(f);
  });
}

function installLoaderHooks(cap) {
  const m = require('node:module');
  if (typeof m.registerHooks !== 'function') {
    cap.notes.add('module.registerHooks unavailable (Node < 22.15): ES modules loaded natively are not listed');
    return;
  }
  try {
    m.registerHooks({
      load(u, context, next) {
        if (cap.active && typeof u === 'string' && u.startsWith('file:')) {
          try { cap.nativeLoads.add(url.fileURLToPath(u)); } catch { /* ignore */ }
        }
        return next(u, context);
      },
    });
  } catch (e) {
    cap.notes.add(`module.registerHooks failed: ${e && e.message}`);
  }
}

const KEY = Symbol.for('detjs.cache.capture');
const CAPTURE = globalThis[KEY] || (globalThis[KEY] = new Capture());

module.exports = { CAPTURE, Capture, machineFacts, installEnv, flagsOf, toPath, INFRA };
