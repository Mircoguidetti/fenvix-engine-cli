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
const DETJS_DRIVER = /[\\/]src[\\/](?:vitest|jest|nodetest|mocha)[\\/]|[\\/]src[\\/](?:session|controls|register|fileproc)\.js$|[\\/]src[\\/]cache[\\/](?:proof|remote|runtime-id)\.js$|[\\/]bin[\\/]detjs\.js$/;
const INFRA = /[\\/]node_modules[\\/](?:\.pnpm[\\/][^\\/]+[\\/]node_modules[\\/])?(?:vitest|@vitest|vite|vite-node|tinypool|tinyspy|jest-[a-z-]+|@jest|jest|expect|babel-jest|ts-jest|@swc|source-map-support|pretty-format|esbuild|rollup|@rollup|rolldown|@rolldown|oxc-[a-z-]+|@oxc-[a-z-]+|lightningcss|postcss|@babel|@ampproject|magic-string|es-module-lexer|tsx|@esbuild|graceful-fs|write-file-atomic|signal-exit|exit-x|istanbul-[a-z-]+|@istanbuljs|v8-to-istanbul|chokidar|fdir|picomatch|tinyglobby|fast-glob|micromatch|resolve|enhanced-resolve|import-local|jest-haste-map|walker|fb-watchman|mocha|workerpool|typescript|ts-node|@swc-node|esbuild-register|pirates)[\\/]/;
const ENGINE_OWN = /^(?:src|bin|node_modules|scripts)(?:[\\/]|$)|^package(?:-lock)?\.json$|^detjs\.[^\\/]+\.node$/;
// a Vite config bundled to a temporary module (it is user code: `vitest.config.ts.timestamp-<n>-<hash>.mjs`)
const BUNDLED_CONFIG = /\.timestamp-\d+(?:-[0-9a-f]+)?\.m?[jt]s$/;
const OWN_ENV = /^(DETJS($|_)|FENVIX_CACHE_)/;
const O_ACC = fs.constants.O_RDONLY | fs.constants.O_WRONLY | fs.constants.O_RDWR;

// dependency kinds computed by the core (crates/detpy-core/src/deps.rs): stat metadata (size, permission bits),
// realpath target, listing with entry types, recursive listing, copied tree
const KINDS = { m: 'statMetaDigest', r: 'realpathDigest', e: 'typedListingDigest', t: 'treeListingDigest', c: 'copyTreeDigest' };
// fields of a Stats object: `size` and `mode` are keyed (`m:`); the others change with every checkout or machine
// (times, inode, device, owner, block counts) and cannot be keyed: a test that reads them is not cached
const STAT_KEYED = new Set(['size', 'mode']);
const STAT_VOLATILE = new Set(['dev', 'ino', 'nlink', 'uid', 'gid', 'rdev', 'blksize', 'blocks', 'atimeMs', 'mtimeMs', 'ctimeMs',
  'birthtimeMs', 'atimeNs', 'mtimeNs', 'ctimeNs', 'birthtimeNs', 'atime', 'mtime', 'ctime', 'birthtime']);
const RUNNER_FN = /^findSiblingsWithFileExtension$/;
const RELATIVE_SPEC = /^\.{1,2}(\/|$)/;

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
    this.fdPaths = new Map(); // descriptor -> path it was opened for
    this.cpInFlight = 0; // asynchronous cp calls running (their internal fs calls are not the caller's reads)
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
    // tsx's and @swc-node's transform caches and v8-compile-cache (ts-node, older CLIs) are content-addressed too
    const uid = typeof process.getuid === 'function' ? process.getuid() : '';
    this.skipDirs = [path.join(tmp, 'jiti'), path.join(tmp, 'node-jiti'), path.join(tmp, `tsx-${uid}`),
      path.join(tmp, `v8-compile-cache-${uid}`), path.join(tmp, 'v8-compile-cache'), path.join(tmp, `swc-node-${uid}`),
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
    installBinding(this);
    installRealClock(this);
    installNodeReaders(this);
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
    installBinding(this);
    installNodeReaders(this);
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
    // detjs itself (its sources, native core and the packages it runs with): in the configuration digest; other
    // paths below its directory (scratch directories of its own tests) are files like any other
    if (abs.startsWith(ENGINE_DIR) && ENGINE_OWN.test(abs.slice(ENGINE_DIR.length))) return 'skip';
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

  /** 'user' | 'infra' from the first frame outside Node and detjs' capture: the code doing the access itself. */
  directCaller() {
    const E = Error;
    const pp = E.prepareStackTrace;
    const lim = E.stackTraceLimit;
    E.prepareStackTrace = structured;
    E.stackTraceLimit = 30;
    const h = {};
    try {
      E.captureStackTrace(h, this.directCaller);
      // eslint-disable-next-line no-unused-expressions
      h.stack;
    } finally {
      E.prepareStackTrace = pp;
      E.stackTraceLimit = lim;
    }
    const frames = Array.isArray(h.stack) ? h.stack : [];
    // runner code that reads metadata only to word an error (Jest lists a missing module's siblings with `glob`)
    if (frames.some((cs) => RUNNER_FN.test((cs.getFunctionName && cs.getFunctionName()) || '') && INFRA.test(cs.getFileName() || ''))) return 'infra';
    for (const cs of frames) {
      let f = cs.getFileName && cs.getFileName();
      if (!f) continue;
      if (f.startsWith('file://')) { try { f = url.fileURLToPath(f); } catch { continue; } }
      // Node's own fs internals (cp, glob, ...) read Stats fields for their own checks
      if (f.startsWith('node:internal/fs/') || f.startsWith('internal/fs/')) return 'infra';
      if (f.startsWith('node:internal/test_runner/') || f.startsWith('internal/test_runner/')) return 'infra'; // node:test itself
      if (f.startsWith('node:') || f.startsWith('internal/') || !f.includes('/')) continue;
      if (f.startsWith(SHELL_DIR) && !DETJS_DRIVER.test(f)) continue;
      if (f.startsWith(ENGINE_DIR) && DETJS_DRIVER.test(f)) return 'infra';
      return INFRA.test(f) ? 'infra' : 'user';
    }
    return 'user';
  }

  /** A frame of installed code that is neither runner nor bundler infrastructure nor Node: a third-party plugin. */
  pluginFrame() {
    const E = Error;
    const pp = E.prepareStackTrace;
    const lim = E.stackTraceLimit;
    E.prepareStackTrace = structured;
    E.stackTraceLimit = 60;
    const h = {};
    try {
      E.captureStackTrace(h, this.pluginFrame);
      // eslint-disable-next-line no-unused-expressions
      h.stack;
    } finally {
      E.prepareStackTrace = pp;
      E.stackTraceLimit = lim;
    }
    for (const cs of Array.isArray(h.stack) ? h.stack : []) {
      let f = cs.getFileName && cs.getFileName();
      if (!f) continue;
      if (f.startsWith('file://')) { try { f = url.fileURLToPath(f); } catch { continue; } }
      if (f.startsWith('node:') || f.startsWith('internal/') || !f.includes('/')) continue;
      if (f.startsWith(ENGINE_DIR) && ENGINE_OWN.test(f.slice(ENGINE_DIR.length))) continue;
      if (f.includes(`${path.sep}node_modules${path.sep}`) && !INFRA.test(f)) return true;
    }
    return false;
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
      } else if (KINDS[kind]) {
        const x = native[KINDS[kind]](abs);
        d = x !== null && x !== undefined ? `${kind}:${x}` : 'missing';
      }
      this.memo.set(k, d);
    }
    return d;
  }

  /** Whether Node's own asynchronous `cp` is the caller (it is keyed as a whole: source tree, copied outputs). */
  inNodeCp() {
    const E = Error;
    const lim = E.stackTraceLimit;
    E.stackTraceLimit = 40;
    let st;
    try { st = new E().stack || ''; } finally { E.stackTraceLimit = lim; }
    return st.includes('internal/fs/cp/');
  }

  /** A read of `p` (kind f content, d listing, s existence, l link target). */
  read(p, kind) {
    if (!this.active || this.busy) return;
    const abs = toPath(p);
    if (abs === null) return;
    this.busy++;
    try {
      if (this.cpInFlight > 0 && this.inNodeCp()) return;
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
        if (!user && this.mainAnyReads && w === 'root' && this.pluginFrame()) {
          // a third-party Vite plugin (not runner infrastructure) reading project files or listing project
          // directories, at start-up or while it transforms modules for the tests: its output can depend on what it
          // read, so that is an input of every file (review r021, F6: transforms other than import.meta.glob)
          this.add(['data', this.key(abs), this.dep(kind, abs), 'plugin'], true);
          return;
        }
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
      }
      // test processes: every read outside the project counts, whoever calls (a library on the INFRA list may be
      // working for the test, and after an await its frames are the only ones on the stack: review r021 F8)
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
      for (const k of ['f', 'd', 's', 'l', 'm', 'e']) this.memo.delete(k + abs);
      this.memo.delete(`d${path.dirname(abs)}`);
      this.memo.delete(`e${path.dirname(abs)}`);
      // realpaths, trees and copies depend on paths below or through `abs`
      for (const k of this.memo.keys()) if (k[0] === 'r' || k[0] === 't' || k[0] === 'c') this.memo.delete(k);
    } finally {
      this.busy--;
    }
  }

  /** Every path of the tree at `p` (after a copy or a rename) is an output of the caller. */
  wroteTree(p) {
    if (!this.active || this.busy) return;
    const abs = toPath(p);
    if (abs === null) return;
    const all = [abs];
    this.busy++;
    try {
      const walk = (d, depth) => {
        if (depth > 64) return;
        let ents;
        try { ents = fs.readdirSync(d, { withFileTypes: true }); } catch { return; }
        for (const e of ents) {
          const x = path.join(d, e.name);
          all.push(x);
          if (e.isDirectory()) walk(x, depth + 1);
        }
      };
      walk(abs, 0);
    } finally {
      this.busy--;
    }
    for (const x of all) this.wrote(x);
  }

  /**
   * The path whose metadata a Stats object returned to the code describes, when it is an input (null otherwise):
   * the fields read from that object are then keyed (`size`, `mode`) or make the test not cacheable (times, ...).
   */
  statTarget(p) {
    if (!this.active || this.busy || this.isGlobal) return null;
    const abs = toPath(p);
    if (abs === null) return null;
    const w = this.where(abs);
    return w === 'root' || w === 'outside' ? abs : null;
  }

  /** A field of a Stats object of `abs` was read. */
  statField(abs, field) {
    if (!this.active || this.busy) return;
    if (STAT_KEYED.has(field)) {
      this.read(abs, 'm');
    } else if (STAT_VOLATILE.has(field)) {
      this.busy++;
      let infra;
      try { infra = this.directCaller() === 'infra'; } finally { this.busy--; }
      // runner and transpiler internals read them for their own caches and fix-ups (Babel's configuration cache,
      // Jest's transform cache key, graceful-fs' uid/gid polyfill), whoever called them: the code reading the field
      // decides
      if (infra) return;
      if (process.env.DETJS_CACHE_DEBUG) process.stderr.write(`detjs cache debug: stat field ${field} of ${abs}\n${new Error().stack}\n`);
      this.flag('stat', `${this.key(abs)} .${field}`);
    }
  }

  /** A dependency of kind `kind` on `abs`, whoever reads (resolution facts: the stem listing `g:`). */
  addDep(abs, dep) {
    this.add(['data', this.key(abs), dep], this.isGlobal);
  }

  stemDep(dir, base) {
    const k = path.join(dir, base);
    const x = native.stemListingDigest(k);
    this.add(['data', this.key(k), x === null || x === undefined ? 'missing' : `g:${x}`], this.isGlobal);
  }

  /**
   * A module specifier that could not be resolved (a caught `import()` / `require()` of an optional module): what
   * would make it resolve is an input (review r021 F5). Relative and absolute specifiers: the target's stem listing
   * (any extension, a directory of that name), its content and its listing if it is a directory. Bare specifiers
   * from installed packages: the runtime identity. Bare specifiers from project code (aliases, tsconfig paths, module
   * directories, self-references): not keyed here, the test is not cached.
   * `opts.roots`: directories an absolute URL may be relative to (the Vite root); `opts.mapped`: a module name
   * mapper matched the specifier (its target is not known here).
   */
  resolveFailed(spec, parent, opts = {}) {
    if (!this.active || this.busy || typeof spec !== 'string' || !spec) return;
    let s = spec.split(/[?#]/)[0];
    if (s.startsWith('node:') || require('node:module').isBuiltin(s)) return; // the runtime identity
    if (s.startsWith('file:')) { try { s = url.fileURLToPath(s); } catch { return; } }
    let parentAbs = null;
    if (typeof parent === 'string' && parent) {
      let pf = parent;
      if (pf.startsWith('file:')) { try { pf = url.fileURLToPath(pf.split('?')[0]); } catch { pf = null; } }
      if (pf && path.isAbsolute(pf)) parentAbs = pf.split(/[?#]/)[0];
    }
    const parentSkip = parentAbs !== null && this.where(parentAbs) === 'skip';
    const cands = [];
    if (s.startsWith('/@fs/')) cands.push(s.slice(4));
    else if (RELATIVE_SPEC.test(s)) cands.push(path.resolve(parentAbs ? path.dirname(parentAbs) : process.cwd(), s));
    else if (path.isAbsolute(s)) {
      cands.push(s);
      for (const r of opts.roots || []) if (r) cands.push(path.join(r, s));
    }
    if (!cands.length || opts.mapped) {
      if (parentSkip && !opts.mapped) return;
      this.flag('resolve', `${spec} not resolved from ${parentAbs ? this.key(parentAbs) : '?'}`);
      return;
    }
    for (const c of cands) {
      const w = this.where(c);
      if (w === 'skip') continue;
      this.read(c, 'f');
      this.read(c, 'd');
      this.busy++;
      try {
        this.stemDep(path.dirname(c), path.basename(c).replace(/\.[^.]*$/, ''));
        this.stemDep(path.dirname(c), path.basename(c));
      } finally {
        this.busy--;
      }
    }
  }

  /** Vitest's mocker: the `__mocks__` files it looks for (findMockRedirect reads fs before the capture: F7). */
  hookVitestMocker(mocker) {
    if (!mocker || typeof mocker.findMockRedirect !== 'function' || mocker.findMockRedirect.__detjsCache) return;
    const real = mocker.findMockRedirect;
    const cap = this;
    const w = function findMockRedirect(mockPath, external, rawId) {
      if (cap.active && !cap.busy) {
        try {
          const root = this.root || (globalThis.__vitest_worker__ && globalThis.__vitest_worker__.config && globalThis.__vitest_worker__.config.root) || cap.root;
          const p = external || mockPath;
          if (typeof mockPath === 'string' && path.isAbsolute(mockPath)) {
            cap.read(mockPath, 's');
            cap.read(path.resolve(path.dirname(mockPath), '__mocks__', path.basename(mockPath)), 's');
          }
          if (typeof p === 'string' && p) {
            cap.read(path.join(root, '__mocks__', path.isAbsolute(p) ? '.' : path.dirname(p)), 't');
            if (path.isAbsolute(p)) cap.read(path.resolve(path.dirname(p), '__mocks__', path.basename(p)), 's');
          }
          if (typeof rawId === 'string' && rawId && !rawId.startsWith('.') && !path.isAbsolute(rawId)) {
            cap.read(path.join(root, '__mocks__', path.dirname(rawId)), 't');
          }
        } catch { /* never break the call */ }
      }
      return real.call(this, mockPath, external, rawId);
    };
    Object.defineProperty(w, '__detjsCache', { value: true });
    mocker.findMockRedirect = w;
  }

  /** Vite's module runner: a module the test imports that cannot be fetched (resolution or transform failed). */
  hookModuleRunner(runner, roots) {
    if (!runner || typeof runner.cachedModule !== 'function' || runner.cachedModule.__detjsCache) return;
    const real = runner.cachedModule;
    const cap = this;
    const w = function cachedModule(u, importer, ...rest) {
      const r = real.call(this, u, importer, ...rest);
      if (r && typeof r.then === 'function') {
        r.then(null, () => { try { cap.resolveFailed(String(u), importer, { roots }); } catch { /* ignore */ } });
      }
      return r;
    };
    Object.defineProperty(w, '__detjsCache', { value: true });
    runner.cachedModule = w;
  }

  /** Jest's resolver: a module a test file requires that cannot be resolved. */
  hookJestResolver(resolver, config) {
    if (!resolver || resolver.__detjsCache) return;
    const cap = this;
    const mapper = (config && config.moduleNameMapper) || [];
    const mapped = (name) => mapper.some((m) => { try { return new RegExp(Array.isArray(m) ? m[0] : m).test(name); } catch { return true; } });
    for (const n of ['resolveModule', 'resolveModuleAsync']) {
      const real = resolver[n];
      if (typeof real !== 'function') continue;
      resolver[n] = function (from, name, ...rest) {
        const fail = () => { try { cap.resolveFailed(String(name), from, { mapped: mapped(String(name)) }); } catch { /* ignore */ } };
        let r;
        try { r = real.call(this, from, name, ...rest); } catch (e) { fail(); throw e; }
        if (r && typeof r.then === 'function') r.then(null, fail);
        return r;
      };
    }
    try { Object.defineProperty(resolver, '__detjsCache', { value: true }); } catch { /* frozen */ }
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
      const stem = (dir, base) => this.stemDep(dir, base);
      const base = path.basename(f).replace(/\.[^.]*$/, '');
      stem(path.dirname(f), base);
      if (base === 'index' && this.inRoot(path.dirname(f))) stem(path.dirname(path.dirname(f)), path.basename(path.dirname(f)));
      this.importGlobs(f);
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

  /**
   * `import.meta.glob` in a project module: Vite expands it when it transforms the module, so the directories its
   * patterns can match in are inputs (review r021 F6): an `e:` listing for a pattern that matches direct entries,
   * a `t:` listing for one that matches deeper. A call whose patterns cannot be read soundly makes the test not
   * cacheable.
   */
  importGlobs(f) {
    if (!/\.(?:[cm]?[jt]sx?|vue|svelte|astro|mdx?)$/.test(f)) return;
    let src;
    try { src = fs.readFileSync(f); } catch { return; }
    if (!src.includes('import.meta.glob')) return;
    const bases = native.importGlobBases(src);
    const global = this.isGlobal;
    if (!bases) {
      this.add(['flag', 'import-glob', `${this.key(f)}: an import.meta.glob call that cannot be keyed`], global);
      return;
    }
    const ws = globalThis.__vitest_worker__;
    const viteRoot = (ws && ws.config && ws.config.root) || this.root;
    for (const b of bases) {
      const dir = b.dir.startsWith('/') ? path.join(viteRoot, b.dir) : path.resolve(path.dirname(f), b.dir);
      if (this.where(dir) === 'skip') continue;
      this.add(['data', this.key(dir), this.dep(b.recursive ? 't' : 'e', dir)], global);
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

/** A Stats object whose field reads are recorded (`size`, `mode`: keyed; times, inode, ...: not cacheable). */
function statProxy(cap, st, abs) {
  if (!st || typeof st !== 'object' || abs === null) return st;
  return new Proxy(st, {
    get(t, k) {
      const v = Reflect.get(t, k, t);
      if (typeof k === 'string' && cap.active && !cap.busy) {
        try { cap.statField(abs, k); } catch { /* never break the call */ }
      }
      // methods (isFile(), ...) run on the object itself: the kind is keyed by the call that returned it
      return typeof v === 'function' && k !== 'constructor' ? v.bind(t) : v;
    },
  });
}

/** Wrap a stat-like function: `kind` recorded for the path, the result handed back as a recording proxy. */
function wrapStat(cap, o, name, kind, style, pathOf = (a) => a[0]) {
  const real = o && o[name];
  if (typeof real !== 'function' || real.__detjsCache) return;
  const k = typeof kind === 'function' ? kind : () => kind;
  let w;
  if (style === 'sync') {
    w = function (...a) {
      const on = cap.active && !cap.busy;
      let abs = null;
      if (on) { try { cap.read(pathOf(a), k(a)); abs = cap.statTarget(pathOf(a)); } catch { /* ignore */ } }
      const r = real.apply(this, a);
      return abs !== null ? statProxy(cap, r, abs) : r;
    };
  } else if (style === 'cb') {
    w = function (...a) {
      const on = cap.active && !cap.busy;
      let abs = null;
      if (on) { try { cap.read(pathOf(a), k(a)); abs = cap.statTarget(pathOf(a)); } catch { /* ignore */ } }
      const i = a.length - 1;
      if (abs !== null && typeof a[i] === 'function') {
        const cb = a[i];
        a[i] = function (err, st) { return cb.call(this, err, err ? st : statProxy(cap, st, abs)); };
      }
      return real.apply(this, a);
    };
  } else {
    w = function (...a) {
      const on = cap.active && !cap.busy;
      let abs = null;
      if (on) { try { cap.read(pathOf(a), k(a)); abs = cap.statTarget(pathOf(a)); } catch { /* ignore */ } }
      const r = real.apply(this, a);
      return abs !== null && r && typeof r.then === 'function' ? r.then((st) => statProxy(cap, st, abs)) : r;
    };
  }
  for (const key of Reflect.ownKeys(real)) {
    if (key === 'length' || key === 'name' || key === 'prototype' || key === 'arguments' || key === 'caller') continue;
    try { Object.defineProperty(w, key, Object.getOwnPropertyDescriptor(real, key)); } catch { /* ignore */ }
  }
  Object.defineProperty(w, '__detjsCache', { value: true });
  Object.defineProperty(w, 'name', { value: real.name, configurable: true });
  try { o[name] = w; } catch { /* read-only */ }
}

/** Kind of a listing call from its options: recursive (`t:`), with entry types (`e:`), names (`d:`). */
function listKind(dflt) {
  return (a) => {
    const o = a[1];
    if (o && typeof o === 'object') {
      if (o.recursive) return 't';
      if (o.withFileTypes) return 'e';
    }
    return dflt;
  };
}

/** An access check: existence (`s:`), or permission bits too when a mode other than F_OK is asked. */
function accessKind(a) {
  return typeof a[1] === 'number' && a[1] !== fs.constants.F_OK ? 'm' : 's';
}

/** Wrap a function whose completion (callback, promise or return) produced a tree at `dst`. */
function wrapTreeOp(cap, o, name, before, dstOf, style, inFlight = false) {
  const real = o && o[name];
  if (typeof real !== 'function' || real.__detjsCache) return;
  const w = function (...a) {
    const on = cap.active && !cap.busy;
    if (on) { try { before(a); } catch { /* ignore */ } }
    if (inFlight) cap.cpInFlight++;
    let ended = false;
    const end = () => { if (inFlight && !ended) { ended = true; cap.cpInFlight--; } };
    const done = () => { end(); if (on) { try { cap.wroteTree(dstOf(a)); } catch { /* ignore */ } } };
    if (style === 'cb') {
      const i = a.length - 1;
      if (typeof a[i] === 'function') {
        const cb = a[i];
        a[i] = function (err, ...rest) { if (!err) done(); else end(); return cb.call(this, err, ...rest); };
      }
      try { return real.apply(this, a); } catch (e) { end(); throw e; }
    }
    let r;
    try { r = real.apply(this, a); } catch (e) { end(); throw e; }
    if (style === 'promise' && r && typeof r.then === 'function') return r.then((x) => { done(); return x; }, (e) => { end(); throw e; });
    done();
    return r;
  };
  for (const key of Reflect.ownKeys(real)) {
    if (key === 'length' || key === 'name' || key === 'prototype' || key === 'arguments' || key === 'caller') continue;
    try { Object.defineProperty(w, key, Object.getOwnPropertyDescriptor(real, key)); } catch { /* ignore */ }
  }
  Object.defineProperty(w, '__detjsCache', { value: true });
  Object.defineProperty(w, 'name', { value: real.name, configurable: true });
  try { o[name] = w; } catch { /* read-only */ }
}

function installFs(cap) {
  const P = fs.promises;
  const read = (k) => (a) => cap.read(a[0], k);
  // a write whose success depends on what is at the path before it (exclusive creates, non-recursive mkdir,
  // unlink/rmdir/rm without force, link/symlink destinations): the path's kind (or absence) is an input (R-009)
  const excl = (fl) => (typeof fl === 'number' ? Boolean(fl & fs.constants.O_EXCL) : typeof fl === 'string' && fl.includes('x'));
  const optsOf = (x) => (x && typeof x === 'object' && !Buffer.isBuffer(x) && !ArrayBuffer.isView(x) ? x : null);
  const probe = (p) => {
    if (!cap.active || cap.busy) return;
    cap.busy++;
    let infra;
    try { infra = cap.directCaller() === 'infra'; } finally { cap.busy--; }
    if (!infra) cap.read(p, 's'); // Node's own cp/rm internals create and remove what the caller asked for
  };
  const write0 = (a, n) => {
    try {
      if (/^mkdir/.test(n) && !(optsOf(a[1]) && optsOf(a[1]).recursive)) probe(a[0]);
      else if (/^(unlink|rmdir)/.test(n)) probe(a[0]);
      else if (/^rm(Sync)?$/.test(n) && !(optsOf(a[1]) && optsOf(a[1]).force)) probe(a[0]);
      else if (/^(writeFile|appendFile)/.test(n)) { const o = optsOf(a[2]); if (o && excl(o.flag)) probe(a[0]); }
    } catch { /* never break the call */ }
    cap.wrote(a[0]);
  };
  const open = (dflt) => (a) => {
    const fl = flagsOf(a[1] && typeof a[1] === 'object' && !Buffer.isBuffer(a[1]) ? a[1].flags : a[1], dflt);
    if (fl.reads && !fl.trunc) cap.read(a[0], 'f');
    if (fl.writes && excl(a[1] && typeof a[1] === 'object' && !Buffer.isBuffer(a[1]) ? a[1].flags : a[1])) probe(a[0]);
    if (fl.writes) cap.wrote(a[0]);
  };
  for (const [o, names, fn] of [
    [fs, ['readFileSync', 'readFile', 'openAsBlob'], read('f')],
    [P, ['readFile'], read('f')],
    [fs, ['existsSync', 'exists'], read('s')],
    [fs, ['readlinkSync', 'readlink'], read('l')],
    [P, ['readlink'], read('l')],
    [fs, ['writeFileSync', 'writeFile', 'appendFileSync', 'appendFile', 'unlinkSync', 'unlink', 'rmSync', 'rm', 'rmdirSync', 'rmdir',
      'mkdirSync', 'mkdir', 'truncateSync', 'truncate', 'utimesSync', 'utimes', 'lutimesSync', 'lutimes', 'chmodSync', 'chmod',
      'lchmodSync', 'lchmod', 'chownSync', 'chown', 'lchownSync', 'lchown', 'createWriteStream'], write0],
    [P, ['writeFile', 'appendFile', 'unlink', 'rm', 'rmdir', 'mkdir', 'truncate', 'utimes', 'lutimes', 'chmod', 'lchmod', 'chown', 'lchown'], write0],
  ]) {
    for (const n of names) wrapFn(cap, o, n, fn === write0 ? (a) => write0(a, n) : fn);
  }
  // stat family (review r021 F1): the kind is keyed by the call (stat: following links; lstat: the path's own
  // kind or link target), the fields read from the result by statProxy; access with a mode: permission bits too;
  // realpath: the resolved path (every link on the way)
  wrapStat(cap, fs, 'statSync', 's', 'sync');
  wrapStat(cap, fs, 'stat', 's', 'cb');
  wrapStat(cap, P, 'stat', 's', 'promise');
  wrapStat(cap, fs, 'lstatSync', 'l', 'sync');
  wrapStat(cap, fs, 'lstat', 'l', 'cb');
  wrapStat(cap, P, 'lstat', 'l', 'promise');
  wrapFn(cap, fs, 'accessSync', (a) => cap.read(a[0], accessKind(a)));
  wrapFn(cap, fs, 'access', (a) => cap.read(a[0], accessKind(a)));
  wrapFn(cap, P, 'access', (a) => cap.read(a[0], accessKind(a)));
  for (const n of ['realpathSync', 'realpath']) {
    wrapFn(cap, fs, n, read('r'));
    if (fs[n] && typeof fs[n].native === 'function') wrapFn(cap, fs[n], 'native', read('r'));
  }
  wrapFn(cap, P, 'realpath', read('r'));
  // listings (F2): names (`d:`), with entry types (`e:`), recursive (`t:`); a Dir yields typed entries
  wrapFn(cap, fs, 'readdirSync', (a) => cap.read(a[0], listKind('d')(a)));
  wrapFn(cap, fs, 'readdir', (a) => cap.read(a[0], listKind('d')(a)));
  wrapFn(cap, P, 'readdir', (a) => cap.read(a[0], listKind('d')(a)));
  for (const [o, n] of [[fs, 'opendirSync'], [fs, 'opendir'], [P, 'opendir']]) wrapFn(cap, o, n, (a) => cap.read(a[0], listKind('e')(a)));
  // file system state that is not a function of the files (free space, change events): not cacheable (F3)
  for (const [o, names] of [[fs, ['statfsSync', 'statfs']], [P, ['statfs']]]) {
    for (const n of names) wrapFn(cap, o, n, (a) => cap.flag('statfs', String(a[0])));
  }
  for (const [o, names] of [[fs, ['watch', 'watchFile']], [P, ['watch']]]) {
    for (const n of names) wrapFn(cap, o, n, (a) => cap.flag('watch', String(a[0])));
  }
  // copies (F4): the source is read as a whole tree (contents included); every path of the copy is an output
  for (const [o, n, style] of [[fs, 'cpSync', 'sync'], [fs, 'cp', 'cb'], [P, 'cp', 'promise']]) {
    wrapTreeOp(cap, o, n, (a) => cap.read(a[0], 'c'), (a) => a[1], style, style !== 'sync');
  }
  for (const [o, names] of [[fs, ['copyFileSync', 'copyFile']], [P, ['copyFile']]]) {
    for (const n of names) {
      wrapFn(cap, o, n, (a) => {
        cap.read(a[0], 'f');
        if (typeof a[2] === 'number' && (a[2] & fs.constants.COPYFILE_EXCL)) probe(a[1]);
        cap.wrote(a[1]);
      });
    }
  }
  // rename: what moves is read (unless the caller wrote it), the destination tree is an output
  for (const [o, n, style] of [[fs, 'renameSync', 'sync'], [fs, 'rename', 'cb'], [P, 'rename', 'promise']]) {
    wrapTreeOp(cap, o, n, (a) => { cap.read(a[0], 'c'); cap.wrote(a[0]); }, (a) => a[1], style);
  }
  for (const [o, names] of [[fs, ['symlinkSync', 'symlink', 'linkSync', 'link']], [P, ['symlink', 'link']]]) {
    for (const n of names) wrapFn(cap, o, n, (a) => { probe(a[1]); cap.wrote(a[1]); });
  }
  // descriptors: the path each was opened for, so that fstat results are recorded like stat results
  wrapFn(cap, fs, 'openSync', open('r'), (a, r) => { if (typeof r === 'number') cap.fdPaths.set(r, a[0]); });
  const realOpen = fs.open;
  if (typeof realOpen === 'function' && !realOpen.__detjsCache) {
    const o = function open_(...a) {
      const on = cap.active && !cap.busy;
      if (on) { try { open('r')(a.slice(0, typeof a[1] === 'function' ? 1 : 2)); } catch { /* ignore */ } }
      const i = a.length - 1;
      if (typeof a[i] === 'function') {
        const cb = a[i];
        const p0 = a[0];
        a[i] = function (err, fd) { if (!err && typeof fd === 'number') cap.fdPaths.set(fd, p0); return cb.call(this, err, fd); };
      }
      return realOpen.apply(this, a);
    };
    for (const key of Reflect.ownKeys(realOpen)) {
      if (['length', 'name', 'prototype', 'arguments', 'caller'].includes(key)) continue;
      try { Object.defineProperty(o, key, Object.getOwnPropertyDescriptor(realOpen, key)); } catch { /* ignore */ }
    }
    Object.defineProperty(o, '__detjsCache', { value: true });
    Object.defineProperty(o, 'name', { value: 'open', configurable: true });
    fs.open = o;
  }
  const realPOpen = P.open;
  if (typeof realPOpen === 'function' && !realPOpen.__detjsCache) {
    const po = async function open_(...a) {
      if (cap.active && !cap.busy) { try { open('r')(a); } catch { /* ignore */ } }
      const h = await realPOpen.apply(P, a);
      if (h && typeof h.stat === 'function' && !h.stat.__detjsCache) {
        const p0 = a[0];
        wrapStat(cap, h, 'stat', 's', 'promise', () => p0);
      }
      return h;
    };
    Object.defineProperty(po, '__detjsCache', { value: true });
    Object.defineProperty(po, 'name', { value: 'open', configurable: true });
    P.open = po;
  }
  const fdPath = (a) => (cap.fdPaths.has(a[0]) ? cap.fdPaths.get(a[0]) : null);
  wrapStat(cap, fs, 'fstatSync', 's', 'sync', fdPath);
  wrapStat(cap, fs, 'fstat', 's', 'cb', fdPath);
  for (const n of ['closeSync', 'close']) wrapFn(cap, fs, n, (a) => cap.fdPaths.delete(a[0]));
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
          // esbuild's own service thread for its synchronous API (esbuild-register, tsx fallbacks): a transform of
          // the source it is given (the source is keyed as a module, esbuild by the runtime identity)
          const esbuildService = /[\\/]node_modules[\\/](?:\.pnpm[\\/][^\\/]+[\\/]node_modules[\\/])?esbuild[\\/]lib[\\/]main\.js$/.test(String(file))
            && (() => { cap.busy++; try { return cap.directCaller() === 'infra'; } finally { cap.busy--; } })();
          if (!esbuildService) {
            try { cap.flag('worker', `worker thread ${String(file).slice(0, 200)}`); } catch { /* ignore */ }
          }
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
      // tsx's relay to a parent `tsx` CLI (watch mode): it only sends module paths and ignores a failed connect
      if (/[\\/]tsx-\d+[\\/]\d+\.pipe$/.test(String(target.path)) && cap.directCaller() === 'infra') return;
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

/**
 * Clocks Level 0 does not virtualize (R-009 "real clock outside the virtual clock"): the process' own uptime and
 * CPU / resource counters, `performance.timeOrigin` (reported by the clock control through STATE.onRealClock), and
 * Intl date formatting of "now" (`Intl.DateTimeFormat#format()` / `formatToParts()` without a date reads V8's own
 * clock). A test that reads them is not cached.
 */
function installRealClock(cap) {
  const real = (what) => {
    if (!cap.active || cap.busy || cap.isGlobal) return;
    cap.busy++;
    let infra;
    try { infra = cap.directCaller() === 'infra'; } finally { cap.busy--; }
    if (!infra) cap.flag('clock-real', what);
  };
  for (const k of ['uptime', 'cpuUsage', 'resourceUsage']) wrapFn(cap, process, k, () => real(`process.${k}()`));
  STATE.onRealClock = real;
  // the process' own performance object (other realms get the clock control's wrapper, which reports it)
  const perf = globalThis.performance;
  if (perf && !Object.prototype.hasOwnProperty.call(perf, 'timeOrigin')) {
    let d = null;
    for (let o = perf; o && !d; o = Object.getPrototypeOf(o)) d = Object.getOwnPropertyDescriptor(o, 'timeOrigin');
    if (d && typeof d.get === 'function') {
      try {
        Object.defineProperty(perf, 'timeOrigin', { configurable: true, enumerable: true, get() { real('performance.timeOrigin'); return d.get.call(perf); } });
      } catch { /* not extensible */ }
    }
  }
  const P = Intl.DateTimeFormat.prototype;
  if (!P.__detjsCache) {
    try {
      const d = Object.getOwnPropertyDescriptor(P, 'format');
      if (d && typeof d.get === 'function') {
        Object.defineProperty(P, 'format', {
          configurable: true,
          enumerable: d.enumerable,
          get() {
            const f = d.get.call(this);
            return function format(date) { if (date === undefined) real('Intl.DateTimeFormat#format() of now'); return f(date); };
          },
        });
      }
      const fp = P.formatToParts;
      if (typeof fp === 'function') {
        Object.defineProperty(P, 'formatToParts', {
          configurable: true,
          writable: true,
          value: function formatToParts(date) { if (date === undefined) real('Intl.DateTimeFormat#formatToParts() of now'); return fp.call(this, date); },
        });
      }
      Object.defineProperty(P, '__detjsCache', { value: true });
    } catch { /* frozen intrinsics */ }
  }
}

/** `process.binding('fs')` and friends reach the native readers without the wrapped functions: not cacheable. */
function installBinding(cap) {
  wrapFn(cap, process, 'binding', (a) => {
    if (cap.busy) return;
    const n = String(a[0]);
    if (!/^(fs|fs_dir|fs_event_wrap|spawn_sync|process_wrap|tcp_wrap|pipe_wrap|udp_wrap|stream_wrap|os|cares_wrap)$/.test(n)) return;
    cap.busy++;
    let infra;
    try { infra = cap.directCaller() === 'infra'; } finally { cap.busy--; }
    if (!infra) cap.flag('binding', `process.binding('${n}')`);
  });
}

function installDlopen(cap) {
  wrapFn(cap, process, 'dlopen', (a) => {
    const f = a[1];
    if (typeof f === 'string') cap.nativeLoads.add(f);
  });
}

/**
 * Node APIs that read files in native code, outside the wrapped `fs` functions (review r021 F3):
 * `process.loadEnvFile` (the env file's content decides the variables it sets) and `node:sqlite` (wrapped when it
 * is first loaded: loading it here would print its experimental warning to every run).
 */
function installNodeReaders(cap) {
  wrapFn(cap, process, 'loadEnvFile', (a) => cap.read(a[0] === undefined ? '.env' : a[0], 'f'));
  const realGet = process.getBuiltinModule;
  if (typeof realGet === 'function' && !realGet.__detjsCache) {
    const g = function getBuiltinModule(id) {
      if (cap.active && (id === 'node:sqlite' || id === 'sqlite')) wrapSqlite(cap);
      return realGet.call(this, id);
    };
    Object.defineProperty(g, '__detjsCache', { value: true });
    try { process.getBuiltinModule = g; } catch { /* read-only */ }
  }
  // already loaded (a runner or an earlier file): wrap now
  try {
    if (!cap.sqliteWrapped && Array.isArray(process.moduleLoadList) && process.moduleLoadList.includes('NativeModule sqlite')) wrapSqlite(cap);
  } catch { /* ignore */ }
}

const SQLITE_UNKEYED = /\b(attach|vacuum\s+into|load_extension)\b/i;

/**
 * node:sqlite opens database files natively. A database opened from a path is read (its content, and the
 * journal and write-ahead log files next to it) and, unless opened read-only, written; a database that cannot
 * be keyed by its path (a URI, ATTACH, VACUUM INTO, extensions) makes the test not cacheable.
 */
function wrapSqlite(cap) {
  if (cap.sqliteWrapped) return;
  cap.sqliteWrapped = true;
  let m;
  try { m = require('node:sqlite'); } catch { return; }
  const Real = m.DatabaseSync;
  if (typeof Real !== 'function' || Real.__detjsCache) return;
  const opened = (loc, options) => {
    if (!cap.active || cap.busy) return;
    if (loc === undefined || loc === null) return;
    const str = typeof loc === 'string' ? loc : null;
    if (str === ':memory:' || str === '') return;
    const abs = str !== null && str.startsWith('file:') ? null : toPath(loc);
    if (abs === null) { cap.flag('sqlite', `database ${String(loc).slice(0, 200)}`); return; }
    for (const x of [abs, `${abs}-wal`, `${abs}-journal`, `${abs}-shm`]) cap.read(x, 'f');
    if (!(options && options.readOnly)) cap.wrote(abs);
  };
  class DatabaseSync extends Real {
    constructor(...args) {
      try { opened(args[0], args[1]); } catch { /* never break the call */ }
      super(...args); // the arity matters: an explicit undefined `options` is refused
    }
  }
  Object.defineProperty(DatabaseSync, '__detjsCache', { value: true });
  Object.defineProperty(DatabaseSync, 'name', { value: 'DatabaseSync' });
  const sqlCheck = (a) => { if (typeof a[0] === 'string' && SQLITE_UNKEYED.test(a[0])) cap.flag('sqlite', `SQL ${a[0].slice(0, 200)}`); };
  for (const n of ['exec', 'prepare']) wrapFn(cap, Real.prototype, n, sqlCheck);
  wrapFn(cap, Real.prototype, 'loadExtension', (a) => cap.flag('sqlite', `extension ${String(a[0])}`));
  try { m.DatabaseSync = DatabaseSync; } catch { /* read-only */ }
  if (typeof m.backup === 'function') wrapFn(cap, m, 'backup', (a) => cap.wrote(a[1]));
  try { require('node:module').syncBuiltinESMExports(); } catch { /* ignore */ }
}

function installLoaderHooks(cap) {
  const m = require('node:module');
  if (typeof m.registerHooks !== 'function') {
    cap.notes.add('module.registerHooks unavailable (Node < 22.15): ES modules loaded natively are not listed');
    return;
  }
  try {
    m.registerHooks({
      resolve(spec, context, next) {
        if (cap.active && (spec === 'node:sqlite' || spec === 'sqlite')) {
          try { wrapSqlite(cap); } catch { /* ignore */ }
        }
        try {
          return next(spec, context);
        } catch (e) {
          // a module that cannot be resolved (review r021 F5): what would make it resolve is an input
          if (cap.active && !cap.busy) {
            try { cap.resolveFailed(spec, context && context.parentURL); } catch { /* ignore */ }
          }
          throw e;
        }
      },
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
