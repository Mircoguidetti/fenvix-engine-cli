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
const ENGINE_OWN = /^(?:src|bin|node_modules|scripts)(?:[\\/]|$)|^package(?:-lock)?\.json$|^detjs\.[^\\/]+\.node$/;
// a Vite config bundled to a temporary module (it is user code: `vitest.config.ts.timestamp-<n>-<hash>.mjs`)
const BUNDLED_CONFIG = /\.timestamp-\d+(?:-[0-9a-f]+)?\.m?[jt]s$/;
const OWN_ENV = /^(DETJS($|_)|FENVIX_CACHE_)/;
const O_ACC = fs.constants.O_RDONLY | fs.constants.O_WRONLY | fs.constants.O_RDWR;

// dependency kinds computed by the core (crates/detpy-core/src/deps.rs): stat metadata (size, permission bits),
// realpath target, listing with entry types, recursive listing (following links to directories / not), copied tree
const KINDS = { m: 'statMetaDigest', r: 'realpathDigest', e: 'typedListingDigest', t: 'treeListingDigest', u: 'treeListingNofollowDigest', c: 'copyTreeDigest' };
// fields of a Stats object: `size` and `mode` are keyed together (`m:`); the others (times, inode, device, owner,
// block counts) each by its exact value (`V:`): they change with every checkout or machine, so a test that reads
// them is reused only where they did not change (review r021b G1b: before, such a test was never cached)
const STAT_KEYED = new Set(['size', 'mode']);
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

/** Number of `set` calls on a Map (its `set` is counted on the instance from the first call here on). */
function countSets(m) {
  if (!m || typeof m.set !== 'function') return -1;
  if (m.__detjsSets === undefined) {
    const real = m.set;
    Object.defineProperty(m, '__detjsSets', { value: 0, writable: true, configurable: true });
    Object.defineProperty(m, 'set', {
      value: function set(k, v) { this.__detjsSets++; return real.call(this, k, v); },
      writable: true, configurable: true,
    });
  }
  return `${m.__detjsSets}:${m.size}`;
}
// classes of a stack frame's file for caller() (Capture#frameClass)
const F_SKIP = 0;
const F_DRIVER = 1;
const F_USER = 2;
const F_INFRA = 3;
const F_OTHER = 4;

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
    this.modsRaw = new Set(); // module keys as the registries give them (module())
    this.loads = 0; // modules loaded through Node's loader (load hook)
    this.loadHooked = false;
    this.lastScan = null; // registries' state at the last scanModules()
    this.whereMemo = new Map();
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
    this.frames = new Map(); // stack frame file name -> class (frameClass)
    this.installedRoots = null; // package trees being digested in the background (see watchInstalled)
    this.installedTouched = false;
    this.preload = false; // early start (src/cache/early.js): preload modules are running
    this.stage = 'run'; // 'preload' (preload modules run: src/cache/early.js) | 'run'
    this.gen = 0; // log generation (Jest starts a new log per file): what recording Stats objects already recorded
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
    this.whereMemo.clear();
    process.env.DETJS_CACHE_SKIP_DIRS = this.skipDirs.join(path.delimiter);
  }

  // -- set-up --------------------------------------------------------------------------------------------------
  install({ role, root, mainAnyReads, early, hooks = true }) {
    if (this.active) {
      // started early (src/cache/early.js, before user preloads): the runner's installation takes over
      if (this.preload) this.endPreload('run');
      this.stage = 'run';
      // the loader hooks (left out of Vitest's own start-up: they slow every module it loads)
      if (!this.loadHooked) installLoaderHooks(this);
      // what Level 0 (installed just before) or the start-up replaced without calling the wrapper is wrapped again;
      // fs is left as is: Level 0's file system order control calls the wrappers it found (src/fsorder.js)
      installEnv(this, process);
      installOs(this);
      installSpawn(this);
      installNet(this);
      installDlopen(this);
      installNodeReaders(this);
      installCloneRetry(this);
      if (role) this.role = role;
      if (mainAnyReads !== undefined) this.mainAnyReads = Boolean(mainAnyReads);
      return;
    }
    this.active = true;
    this.role = role;
    this.frames.clear();
    this.whereMemo.clear();
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
    installNodeReaders(this);
    installCloneRetry(this);
    if (hooks) installLoaderHooks(this);
    STATE.onEvent = (source, value) => this.levelEvent(source, value);
    require('node:module').syncBuiltinESMExports();
    if (early) {
      this.preload = true;
      this.stage = 'preload';
      installPreloadClock(this);
    }
    // an off-thread module loader runs in another thread: what it reads is not observable here
    const ld = offThreadLoader();
    if (ld) this.add(['flag', 'loader', `--loader ${ld}`], this.isGlobal);
  }

  /**
   * End of the preload phase (the process's entry module loads). In a Vitest worker, what runs next before the
   * runner (Vitest's start-up, the test environment's set-up) is recorded as everything later in the process: a
   * custom environment's code is evaluated by Vite's module runner without a file name in its stack frames, so the
   * code doing a read cannot be told from Vitest's own there.
   */
  endPreload(next) {
    if (!this.preload) return;
    this.preload = false;
    this.stage = next;
    uninstallPreloadClock();
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
    installNodeReaders(this);
    installCloneRetry(this);
    require('node:module').syncBuiltinESMExports();
  }

  setCtx(ctx, label) {
    this.ctx = ctx;
    if (label !== undefined) this.label = label;
  }

  /** Jest: each test file has its own module registry and environment copy, so its log starts afresh. */
  resetFile() {
    this.gen++;
    this.log = [];
    this.seen = new Set();
    this.tests = [];
    this.modsSeen = new Set();
    this.modsRaw = new Set();
    this.lastScan = null;
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
    let w = this.whereMemo.get(abs);
    if (w === undefined) {
      w = this.whereOf(abs);
      if (this.whereMemo.size > 100000) this.whereMemo.clear();
      this.whereMemo.set(abs, w);
    }
    return w;
  }

  whereOf(abs) {
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

  /**
   * Classification of a stack frame's file name, cached per name (stacks repeat the same files): bits 0-2 for
   * caller() (F_SKIP, F_DRIVER, F_USER, F_INFRA, F_OTHER), bit 3 a third-party plugin frame (pluginFrame()), bits
   * 4-5 for directCaller() (0 next frame, 1 infra, 2 user).
   */
  frameClass(raw) {
    let c = this.frames.get(raw);
    if (c !== undefined) return c;
    let f = raw;
    let ok = true;
    if (f.startsWith('file://')) { try { f = url.fileURLToPath(f); } catch { ok = false; } }
    let cls = F_SKIP;
    let plugin = 0;
    let direct = 0;
    if (ok) {
      const q = f.indexOf('?');
      const fq = q >= 0 ? f.slice(0, q) : f;
      // caller()
      if (fq.startsWith(ENGINE_DIR) && DETJS_DRIVER.test(fq)) cls = F_DRIVER;
      else if (fq.startsWith('node:') || fq.startsWith('internal/') || fq.startsWith(SHELL_DIR) || !fq.includes('/')) cls = F_SKIP;
      else if (BUNDLED_CONFIG.test(fq)) cls = F_USER;
      else if (INFRA.test(fq)) cls = F_INFRA;
      else if (this.inRoot(fq) && !fq.includes(`${path.sep}node_modules${path.sep}`)) cls = F_USER;
      else cls = F_OTHER;
      // pluginFrame()
      if (!(f.startsWith('node:') || f.startsWith('internal/') || !f.includes('/'))
        && !(f.startsWith(ENGINE_DIR) && ENGINE_OWN.test(f.slice(ENGINE_DIR.length)))
        && f.includes(`${path.sep}node_modules${path.sep}`) && !INFRA.test(f)) plugin = 8;
      // directCaller()
      if (f.startsWith('node:internal/fs/') || f.startsWith('internal/fs/')) direct = 1;
      else if (f.startsWith('node:') || f.startsWith('internal/') || !f.includes('/')) direct = 0;
      else if (f.startsWith(SHELL_DIR) && !DETJS_DRIVER.test(f)) direct = 0;
      else if (f.startsWith(ENGINE_DIR) && DETJS_DRIVER.test(f)) direct = 1;
      else direct = INFRA.test(f) ? 1 : 2;
    }
    c = cls | plugin | (direct << 4);
    if (this.frames.size > 50000) this.frames.clear();
    this.frames.set(raw, c);
    return c;
  }

  /** File names of the calling frames (at most `limit`), skipping the frames above `fn`. */
  stackFiles(limit, fn) {
    const E = Error;
    const pp = E.prepareStackTrace;
    const lim = E.stackTraceLimit;
    E.prepareStackTrace = structured;
    E.stackTraceLimit = limit;
    const h = {};
    try {
      E.captureStackTrace(h, fn);
      // eslint-disable-next-line no-unused-expressions
      h.stack;
    } finally {
      E.prepareStackTrace = pp;
      E.stackTraceLimit = lim;
    }
    return Array.isArray(h.stack) ? h.stack : [];
  }

  /** caller() over captured frames. */
  callerOf(frames) {
    let infra = false;
    for (const cs of frames) {
      const raw = cs.getFileName && cs.getFileName();
      if (!raw) continue;
      const c = this.frameClass(raw) & 7;
      if (c === F_USER) return 'user';
      if (c === F_DRIVER || c === F_INFRA) infra = true;
    }
    // no project frame and no runner frame (callback chains inside Node): in the main process, project code that
    // calls fs has its own frame on the stack, so such chains are the runner's (Vitest's async cleanup); in a test
    // process they may be a library working for the test, so they count
    return infra || this.role === 'main' ? 'infra' : 'user';
  }

  /** 'user' | 'infra' from the calling frames: a project frame anywhere decides 'user'. */
  caller() {
    return this.callerOf(this.stackFiles(60, this.caller));
  }

  /** caller() and pluginFrame() from one stack capture: { user, plugin }. */
  callerAndPlugin() {
    const frames = this.stackFiles(60, this.callerAndPlugin);
    const user = this.callerOf(frames) === 'user';
    let plugin = false;
    if (!user) {
      for (const cs of frames) {
        const raw = cs.getFileName && cs.getFileName();
        if (raw && (this.frameClass(raw) & 8)) { plugin = true; break; }
      }
    }
    return { user, plugin };
  }

  /** 'user' | 'infra' from the first frame outside Node and detjs' capture: the code doing the access itself. */
  directCaller() {
    const frames = this.stackFiles(30, this.directCaller);
    // runner code that reads metadata only to word an error (Jest lists a missing module's siblings with `glob`)
    if (frames.some((cs) => RUNNER_FN.test((cs.getFunctionName && cs.getFunctionName()) || '') && INFRA.test(cs.getFileName() || ''))) return 'infra';
    for (const cs of frames) {
      const raw = cs.getFileName && cs.getFileName();
      if (!raw) continue;
      const d = this.frameClass(raw) >> 4;
      if (d === 1) return 'infra';
      if (d === 2) return 'user';
    }
    return 'user';
  }

  /** A frame of installed code that is neither runner nor bundler infrastructure nor Node: a third-party plugin. */
  pluginFrame() {
    for (const cs of this.stackFiles(60, this.pluginFrame)) {
      const raw = cs.getFileName && cs.getFileName();
      if (raw && (this.frameClass(raw) & 8)) return true;
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
      if (!this.preload && this.caller() !== 'user') return;
      // a process or thread started by the start-up code may install or change packages
      if (flag === 'spawn' || flag === 'worker') this.installedTouched = true;
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
      } else if (kind[0] === 'V') {
        // V<follow><field>: one Stats field by its exact value
        const follow = kind[1] === '1';
        const field = kind.slice(2);
        const x = native.statFieldDigest(abs, field, follow);
        d = x !== null && x !== undefined ? `V:${follow ? 1 : 0}:${field}:${x}` : 'missing';
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
          if (global && !this.preload && this.caller() !== 'user') return;
          this.add(['flag', 'proc', abs], global);
          return;
        }
        // the kernel version: the same for every process of a machine, an input like a file
      }
      if (global) {
        // the main process: runner and bundler infrastructure reads everything; only reads that can change what
        // tests see are inputs (Vitest: file contents and missing paths in the project, whoever reads them,
        // except the test modules themselves, removed at the end)
        let user = this.preload;
        let plugin = false;
        if (!user) {
          if (this.mainAnyReads && w === 'root') ({ user, plugin } = this.callerAndPlugin());
          else user = this.caller() === 'user';
        }
        if (!user && plugin) {
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

  /**
   * The installed package trees whose digest was started before the runner (proof.js, startPackages): a write into
   * them by anyone (except under the names the digest leaves out) makes that digest stale.
   */
  watchInstalled(roots) {
    this.installedRoots = roots.map(([, d]) => path.resolve(d) + path.sep);
    this.installedTouched = false;
  }

  noteInstalledWrite(abs) {
    for (const r of this.installedRoots) {
      if (!abs.startsWith(r) && abs + path.sep !== r) continue;
      const parts = abs.slice(r.length).split(path.sep);
      const { TREE_EXCLUDE } = require('./runtime-id');
      if (parts.some((x) => TREE_EXCLUDE.includes(x) || TREE_EXCLUDE.some((e) => e.startsWith('*') && x.endsWith(e.slice(1))))) continue;
      this.installedTouched = true;
      return;
    }
  }

  wrote(p) {
    if (!this.active || this.busy) return;
    const abs = toPath(p);
    if (abs === null) return;
    if (this.installedRoots && !this.installedTouched && this.isGlobal) this.noteInstalledWrite(abs);
    this.busy++;
    try {
      const w = this.where(abs);
      if (w === 'skip' || w === 'proc') return;
      const global = this.isGlobal;
      if ((global || w === 'outside') && !this.preload && this.caller() !== 'user') return;
      let s = this.written.get(abs);
      if (!s) this.written.set(abs, (s = new Set()));
      s.add(global ? '' : this.label);
      if (global && process.env.DETJS_CACHE_DEBUG) process.stderr.write(`detjs cache debug: start-up write ${abs}\n${new Error().stack}\n`);
      this.add(['write', this.key(abs)], global);
      for (const k of ['f', 'd', 's', 'l', 'm', 'e']) this.memo.delete(k + abs);
      this.memo.delete(`d${path.dirname(abs)}`);
      this.memo.delete(`e${path.dirname(abs)}`);
      // realpaths, trees and copies depend on paths below or through `abs`
      for (const k of this.memo.keys()) if (k[0] === 'r' || k[0] === 't' || k[0] === 'u' || k[0] === 'c' || k[0] === 'V') this.memo.delete(k);
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
    if (!this.active || this.busy || (this.isGlobal && !this.preload)) return null;
    const abs = toPath(p);
    if (abs === null) return null;
    const w = this.where(abs);
    if (w !== 'root' && w !== 'outside') return null;
    return abs;
  }

  /**
   * A field of a Stats object of `abs` (from `stat` when `follow`, else `lstat`) was read. True when it was recorded
   * (it then need not be recorded again for that object). `size` and `mode` are keyed by `m:`; any other field (times,
   * inode, device, owner, ...) by its exact value (`V:`), unless runner or transpiler code reads it for itself.
   */
  statField(abs, field, follow = true) {
    if (!this.active || this.busy) return false;
    if (STAT_KEYED.has(field)) {
      this.read(abs, 'm');
      return true;
    }
    this.busy++;
    let infra;
    try { infra = this.directCaller() === 'infra'; } finally { this.busy--; }
    // runner and transpiler internals read them for their own caches and fix-ups (Babel's configuration cache,
    // Jest's transform cache key, graceful-fs' uid/gid polyfill), whoever called them: the code reading the field
    // decides
    if (infra) return false;
    if (process.env.DETJS_CACHE_DEBUG) process.stderr.write(`detjs cache debug: stat field ${field} of ${abs}\n${new Error().stack}\n`);
    this.read(abs, `V${follow ? 1 : 0}${field}`);
    return true;
  }

  /** A field of a recording Stats object was read (recorded once per object and log). */
  statFieldOf(e, field) {
    if (e.gen !== this.gen) { e.gen = this.gen; e.seen = null; }
    if (e.seen !== null && e.seen.has(field)) return;
    if (this.statField(e.abs, field, e.follow)) (e.seen || (e.seen = new Set())).add(field);
  }

  /** Every field of a recording Stats object was read (inspection, descriptors). */
  statWhole(e) {
    for (const k of Object.keys(e.raw)) this.statFieldOf(e, k);
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
    if (!this.preload && (global || name === '*' || this.role === 'main')) {
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
    // the same key again (every test end rescans the module registries): nothing to do
    if (this.modsRaw.has(file)) return;
    this.modsRaw.add(file);
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
    const em = st && st.evaluatedModules;
    const map = em && em.idToModuleMap;
    const mc = st && st.moduleCache;
    // nothing loaded since the last scan (every load through Node's loader passes the load hook; Vite's module
    // runner adds to its map): the registries hold no module the log does not have
    const sig = `${this.loads}|${countSets(map)}|${countSets(mc)}|${this.nativeLoads.size}`;
    if (!extra && this.loadHooked && sig === this.lastScan) return;
    if (map) for (const m of map.values()) this.module(m.file || m.id);
    if (mc && typeof mc.keys === 'function') for (const k of mc.keys()) this.module(k);
    try {
      for (const k in require.cache) this.module(k);
    } catch { /* no cache */ }
    for (const f of this.nativeLoads) this.module(f);
    if (extra) for (const f of extra) this.module(f);
    this.lastScan = sig;
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

// -- Stats objects (review r021b G1, G2) ------------------------------------------------------------------------
// A Stats object handed to the code is the real `fs.Stats` (or BigIntStats) object, same prototype, not a Proxy:
// its own data fields are turned into accessor properties that record the read (`size`, `mode`: keyed by `m:`;
// times, inode, owner, ...: not cacheable when the code reading them is not runner infrastructure). Every way to
// read a value goes through a getter (property access, spread, `Object.assign`, `JSON.stringify`, structured
// clone, `v8.serialize`, `postMessage`, deep equality), except two that read a property's descriptor instead:
// `Object.getOwnPropertyDescriptor(s)` / `Reflect.getOwnPropertyDescriptor` (patched in every realm tests run in:
// the field is read, a data descriptor is returned as without the cache) and `util.inspect` / `console.log` (a
// custom inspection on the Stats prototypes: every field is read and a plain copy is formatted, so the output is
// the one without the cache). The `is*()` methods read the kind from the object itself: the kind is keyed by the
// call that returned it (`s:` / `l:`), so they do not count as reading `mode`.
const STATS_REC = new WeakMap(); // recording Stats object -> { cap, abs, follow, raw, gen, seen, view }
const STATS_GETTERS = new Map(); // getter function -> field name
const STATS_DESC = new Map(); // field name + enumerable -> accessor descriptor
const StatsBaseProto = Object.getPrototypeOf(fs.Stats.prototype);
const realGOPD = Object.getOwnPropertyDescriptor;
const realGOPDs = Object.getOwnPropertyDescriptors;
const realDefine = Object.defineProperty;
const realGetProto = Object.getPrototypeOf;
const realIsFrozen = Object.isFrozen;

function statsRecOf(o) {
  let x = o;
  for (let i = 0; i < 32 && x !== null && x !== undefined && (typeof x === 'object' || typeof x === 'function'); i++) {
    const e = STATS_REC.get(x);
    if (e !== undefined) return e;
    x = realGetProto(x);
  }
  return undefined;
}

function statsDesc(k, enumerable) {
  const key = `${enumerable ? 1 : 0}${k}`;
  let d = STATS_DESC.get(key);
  if (d) return d;
  const get = function () {
    const e = statsRecOf(this);
    if (e === undefined) return undefined;
    if (e.cap.active && !e.cap.busy) { try { e.cap.statFieldOf(e, k); } catch { /* never break the read */ } }
    return e.raw[k];
  };
  const set = function (v) {
    // as for a data property: the value now held is the one written (no longer the file's)
    const e = STATS_REC.get(this);
    if (e !== undefined) { e.raw[k] = v; e.view = null; }
    try { realDefine(this, k, { value: v, writable: true, enumerable, configurable: true }); } catch { /* frozen */ }
  };
  STATS_GETTERS.set(get, k);
  d = { get, set, enumerable, configurable: true };
  STATS_DESC.set(key, d);
  return d;
}

/** A data descriptor for `k` of a recording Stats object `o` as the plain object would give it (the field is read). */
function statsDataDesc(o, k, d) {
  return { value: STATS_REC.get(o).raw[k], writable: !realIsFrozen(o), enumerable: d.enumerable, configurable: d.configurable };
}

/** A copy of a recording Stats object with data fields (its current values): what the code would see without the cache. */
function statsPlain(o) {
  const e = STATS_REC.get(o);
  const out = Object.create(realGetProto(o));
  for (const k of Reflect.ownKeys(o)) {
    const d = realGOPD(o, k);
    realDefine(out, k, d.get !== undefined && STATS_GETTERS.has(d.get) && e ? statsDataDesc(o, k, d) : d);
  }
  return out;
}

/** The object the `is*()` methods read the kind from: the values the Stats object holds, not recorded. */
function statsView(e, o) {
  if (e.view) return e.view;
  const v = Object.create(realGetProto(o));
  realDefine(v, 'mode', { value: e.raw.mode, writable: true, enumerable: true, configurable: true });
  e.view = v;
  return v;
}

/** Turn a Stats object returned to the code into a recording one, in place. */
function recordingStats(cap, st, abs, follow = true) {
  if (!st || typeof st !== 'object' || abs === null || STATS_REC.has(st) || !(st instanceof StatsBaseProto.constructor)) return st;
  const raw = {};
  const descs = {};
  for (const k of Object.keys(st)) {
    const d = realGOPD(st, k);
    if (!d || !('value' in d) || !d.configurable) continue;
    raw[k] = d.value;
    descs[k] = statsDesc(k, d.enumerable);
  }
  Object.defineProperties(st, descs);
  STATS_REC.set(st, { cap, abs, follow, raw, gen: -1, seen: null, view: null });
  return st;
}

/** Process-wide part: the prototypes' `is*()` methods and custom inspection. Once per process. */
function installStatsProto() {
  if (StatsBaseProto.__detjsCacheStats) return;
  realDefine(StatsBaseProto, '__detjsCacheStats', { value: true });
  for (const n of ['isDirectory', 'isFile', 'isBlockDevice', 'isCharacterDevice', 'isSymbolicLink', 'isFIFO', 'isSocket']) {
    const real = StatsBaseProto[n];
    if (typeof real !== 'function') continue;
    const w = { [n]() { const e = STATS_REC.get(this); return real.call(e !== undefined ? statsView(e, this) : this); } }[n];
    realDefine(StatsBaseProto, n, { ...realGOPD(StatsBaseProto, n), value: w });
  }
  const custom = Symbol.for('nodejs.util.inspect.custom');
  realDefine(StatsBaseProto, custom, {
    value: function inspectStats() {
      const e = STATS_REC.get(this);
      if (e === undefined) return this; // the same object: Node formats it as usual
      if (e.cap.active && !e.cap.busy) { try { e.cap.statWhole(e); } catch { /* ignore */ } }
      return statsPlain(this);
    },
    writable: true, enumerable: false, configurable: true,
  });
}

/**
 * Per realm: the reflection functions that read a property's descriptor (which a getter does not see). A realm is
 * the main one (Vitest, Jest's runner) or the context a Jest test file runs in.
 */
function installReflection(cap, g) {
  const O = g && g.Object;
  const R = g && g.Reflect;
  if (!O || O.getOwnPropertyDescriptor.__detjsCache) return;
  const gopd = O.getOwnPropertyDescriptor;
  const gopds = O.getOwnPropertyDescriptors;
  const wrapOne = (real) => function getOwnPropertyDescriptor(o, k) {
    const d = real(o, k);
    if (d === undefined || d.get === undefined || !STATS_GETTERS.has(d.get)) return d;
    const e = STATS_REC.get(o);
    if (e === undefined) return d;
    const f = STATS_GETTERS.get(d.get);
    if (e.cap.active && !e.cap.busy) { try { e.cap.statFieldOf(e, f); } catch { /* ignore */ } }
    return statsDataDesc(o, f, d);
  };
  const w1 = wrapOne(gopd);
  const w2 = function getOwnPropertyDescriptors(o) {
    const all = gopds(o);
    const e = o !== null && o !== undefined ? STATS_REC.get(o) : undefined;
    if (e === undefined) return all;
    if (e.cap.active && !e.cap.busy) { try { e.cap.statWhole(e); } catch { /* ignore */ } }
    for (const k of Reflect.ownKeys(all)) {
      const d = all[k];
      if (d.get !== undefined && STATS_GETTERS.has(d.get)) all[k] = statsDataDesc(o, STATS_GETTERS.get(d.get), d);
    }
    return all;
  };
  for (const [obj, name, w, real] of [[O, 'getOwnPropertyDescriptor', w1, gopd], [O, 'getOwnPropertyDescriptors', w2, gopds]]) {
    realDefine(w, '__detjsCache', { value: true });
    realDefine(w, 'length', { value: real.length, configurable: true });
    realDefine(obj, name, { ...realGOPD(obj, name), value: w });
  }
  if (R && typeof R.getOwnPropertyDescriptor === 'function') {
    const rw = wrapOne(R.getOwnPropertyDescriptor);
    realDefine(rw, '__detjsCache', { value: true });
    realDefine(rw, 'length', { value: 2, configurable: true });
    realDefine(rw, 'name', { value: 'getOwnPropertyDescriptor', configurable: true });
    realDefine(R, 'getOwnPropertyDescriptor', { ...realGOPD(R, 'getOwnPropertyDescriptor'), value: rw });
  }
  // structured clone of a value that holds the recording environment object (a Proxy cannot be cloned): the clone
  // is made from the real environment, which reads all of it
  if (typeof g.structuredClone === 'function' && !g.structuredClone.__detjsCache) {
    const real = g.structuredClone;
    const sc = function structuredClone(v, ...rest) {
      try { return real.call(this, v, ...rest); } catch (err) {
        const u = unproxyEnv(cap, v);
        if (u === v) throw err;
        return real.call(this, u, ...rest);
      }
    };
    realDefine(sc, '__detjsCache', { value: true });
    realDefine(sc, 'length', { value: real.length, configurable: true });
    realDefine(g, 'structuredClone', { ...realGOPD(g, 'structuredClone'), value: sc });
  }
}

/** Wrap a stat-like function: `kind` recorded for the path, the result handed back as a recording Stats object. */
function wrapStat(cap, o, name, kind, style, pathOf = (a) => a[0]) {
  const real = o && o[name];
  if (typeof real !== 'function' || real.__detjsCache) return;
  const k = typeof kind === 'function' ? kind : () => kind;
  const follow = kind !== 'l'; // lstat: the path's own metadata
  let w;
  if (style === 'sync') {
    w = function (...a) {
      const on = cap.active && !cap.busy;
      let abs = null;
      if (on) { try { cap.read(pathOf(a), k(a)); abs = cap.statTarget(pathOf(a)); } catch { /* ignore */ } }
      const r = real.apply(this, a);
      return abs !== null ? recordingStats(cap, r, abs, follow) : r;
    };
  } else if (style === 'cb') {
    w = function (...a) {
      const on = cap.active && !cap.busy;
      let abs = null;
      if (on) { try { cap.read(pathOf(a), k(a)); abs = cap.statTarget(pathOf(a)); } catch { /* ignore */ } }
      const i = a.length - 1;
      if (abs !== null && typeof a[i] === 'function') {
        const cb = a[i];
        a[i] = function (err, st) { return cb.call(this, err, err ? st : recordingStats(cap, st, abs, follow)); };
      }
      return real.apply(this, a);
    };
  } else {
    w = function (...a) {
      const on = cap.active && !cap.busy;
      let abs = null;
      if (on) { try { cap.read(pathOf(a), k(a)); abs = cap.statTarget(pathOf(a)); } catch { /* ignore */ } }
      const r = real.apply(this, a);
      return abs !== null && r && typeof r.then === 'function' ? r.then((st) => recordingStats(cap, st, abs, follow)) : r;
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

/**
 * Kind of a listing call from its options: names (`d:`), with entry types (`e:`), recursive (G3 of review r021b:
 * `t:` where Node descends into links to directories, as `readdirSync` and callback `readdir` always do and
 * `fs.promises.readdir` does without `withFileTypes`; `u:` where it does not: `fs.promises.readdir` with
 * `withFileTypes`, recursive `opendir`).
 */
function listKind(dflt, followTyped = true) {
  return (a) => {
    const o = a[1];
    if (o && typeof o === 'object') {
      if (o.recursive) return o.withFileTypes && !followTyped ? 'u' : 't';
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
  installStatsProto();
  installReflection(cap, globalThis);
  const read = (k) => (a) => cap.read(a[0], k);
  const write0 = (a) => cap.wrote(a[0]);
  const open = (dflt) => (a) => {
    const fl = flagsOf(a[1] && typeof a[1] === 'object' && !Buffer.isBuffer(a[1]) ? a[1].flags : a[1], dflt);
    if (fl.reads && !fl.trunc) cap.read(a[0], 'f');
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
    for (const n of names) wrapFn(cap, o, n, fn);
  }
  // stat family (review r021 F1): the kind is keyed by the call (stat: following links; lstat: the path's own
  // kind or link target), the fields read from the result through recordingStats; access with a mode: permission
  // bits too;
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
  wrapFn(cap, P, 'readdir', (a) => cap.read(a[0], listKind('d', false)(a)));
  for (const [o, n] of [[fs, 'opendirSync'], [fs, 'opendir'], [P, 'opendir']]) {
    wrapFn(cap, o, n, (a) => cap.read(a[0], (a[1] && typeof a[1] === 'object' && a[1].recursive) ? 'u' : 'e'));
  }
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
    for (const n of names) wrapFn(cap, o, n, (a) => { cap.read(a[0], 'f'); cap.wrote(a[1]); });
  }
  // rename: what moves is read (unless the caller wrote it), the destination tree is an output
  for (const [o, n, style] of [[fs, 'renameSync', 'sync'], [fs, 'rename', 'cb'], [P, 'rename', 'promise']]) {
    wrapTreeOp(cap, o, n, (a) => { cap.read(a[0], 'c'); cap.wrote(a[0]); }, (a) => a[1], style);
  }
  for (const [o, names] of [[fs, ['symlinkSync', 'symlink', 'linkSync', 'link']], [P, ['symlink', 'link']]]) {
    for (const n of names) wrapFn(cap, o, n, (a) => cap.wrote(a[1]));
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

// recording environment proxies -> the environment object each stands for (review r021b: the same class of hole as
// the Stats proxy, closed for process.env too)
const ENV_PROXIES = new WeakMap();

/**
 * `process.env` as a Proxy whose traps record the reads (`get` / `in` / descriptor; enumerating it records `*`).
 * The Proxy's target is not the environment object itself but a stand-in that holds only a custom inspection, so
 * that `util.inspect` / `console.log` (which format a Proxy's target without running its traps) record `*` and
 * format the real environment, exactly as without the cache. Structured cloning of a Proxy fails: `structuredClone`,
 * `v8.serialize` and `postMessage` retry with the real environment in its place (which reads all of it), so they
 * succeed or fail as without the cache; `util.types.isProxy` answers for the real environment object.
 */
function installEnv(cap, proc) {
  const env = proc.env;
  if (env && ENV_PROXIES.has(env)) return;
  const real = env;
  const custom = Symbol.for('nodejs.util.inspect.custom');
  const stand = Object.create(realGetProto(real));
  realDefine(stand, custom, {
    value: function inspectEnv() { cap.env('*'); return real; },
    writable: true, enumerable: false, configurable: true,
  });
  const handler = {
    get(_t, k) {
      if (typeof k === 'string') cap.env(k);
      return Reflect.get(real, k);
    },
    has(_t, k) {
      if (typeof k === 'string') cap.env(k);
      return Reflect.has(real, k);
    },
    getOwnPropertyDescriptor(_t, k) {
      if (typeof k === 'string') cap.env(k);
      return Reflect.getOwnPropertyDescriptor(real, k);
    },
    ownKeys() {
      cap.env('*');
      return Reflect.ownKeys(real);
    },
    set(_t, k, v) { real[k] = v; return true; },
    deleteProperty(_t, k) { delete real[k]; return true; },
    defineProperty(_t, k, d) { return Reflect.defineProperty(real, k, d); },
    getPrototypeOf() { return realGetProto(real); },
    setPrototypeOf(_t, p) { return Reflect.setPrototypeOf(real, p); },
  };
  try {
    const p = new Proxy(stand, handler);
    ENV_PROXIES.set(p, real);
    proc.env = p;
    if (proc.env !== p) realDefine(proc, 'env', { value: p, writable: true, configurable: true, enumerable: true });
  } catch { cap.notes.add('process.env not replaceable: environment reads not captured'); }
}

/** `v` with every recording environment Proxy in it replaced by the environment it stands for (null if none). */
function unproxyEnv(cap, v) {
  let found = false;
  const memo = new Map();
  const walk = (x, depth) => {
    if (x === null || typeof x !== 'object' || depth > 1000) return x;
    const realEnv = ENV_PROXIES.get(x);
    if (realEnv !== undefined) { found = true; cap.env('*'); return realEnv; }
    if (memo.has(x)) return memo.get(x);
    if (Array.isArray(x)) {
      const out = new Array(x.length);
      memo.set(x, out);
      for (let i = 0; i < x.length; i++) if (i in x) out[i] = walk(x[i], depth + 1);
      return out;
    }
    if (x instanceof Map) {
      const out = new Map();
      memo.set(x, out);
      for (const [k, y] of x) out.set(walk(k, depth + 1), walk(y, depth + 1));
      return out;
    }
    if (x instanceof Set) {
      const out = new Set();
      memo.set(x, out);
      for (const y of x) out.add(walk(y, depth + 1));
      return out;
    }
    const proto = realGetProto(x);
    if (proto !== Object.prototype && proto !== null) { memo.set(x, x); return x; }
    const out = {};
    memo.set(x, out);
    for (const k of Object.keys(x)) out[k] = walk(x[k], depth + 1);
    return out;
  };
  const u = walk(v, 0);
  return found ? u : v;
}

/** Serializers that refuse a Proxy: retried with the real environment in place of the recording one. */
function installCloneRetry(cap) {
  const v8 = require('node:v8');
  const retry = (real, argIndex) => function (...a) {
    try { return real.apply(this, a); } catch (err) {
      const u = unproxyEnv(cap, a[argIndex]);
      if (u === a[argIndex]) throw err;
      const b = a.slice();
      b[argIndex] = u;
      return real.apply(this, b);
    }
  };
  const put = (obj, name, idx) => {
    const real = obj && obj[name];
    if (typeof real !== 'function' || real.__detjsCache) return;
    const w = retry(real, idx);
    realDefine(w, '__detjsCache', { value: true });
    realDefine(w, 'name', { value: real.name, configurable: true });
    realDefine(w, 'length', { value: real.length, configurable: true });
    try { obj[name] = w; } catch { /* read-only */ }
  };
  put(v8, 'serialize', 0);
  if (v8.Serializer && v8.Serializer.prototype) put(v8.Serializer.prototype, 'writeValue', 0);
  const wt = require('node:worker_threads');
  if (wt.MessagePort && wt.MessagePort.prototype) put(wt.MessagePort.prototype, 'postMessage', 0);
  if (wt.BroadcastChannel && wt.BroadcastChannel.prototype) put(wt.BroadcastChannel.prototype, 'postMessage', 0);
  const util = require('node:util');
  const types = util.types;
  if (types && typeof types.isProxy === 'function' && !types.isProxy.__detjsCache) {
    const real = types.isProxy;
    const w = function isProxy(x) { const r = ENV_PROXIES.get(x); return real(r !== undefined ? r : x); };
    realDefine(w, '__detjsCache', { value: true });
    try { types.isProxy = w; } catch { /* read-only */ }
  }
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
  // loaded on first use: Level 0's network control (src/network.js) keeps the `connect` it finds when it is loaded,
  // which must be this wrapper when the capture starts first (early.js)
  let isLocalName = null;
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
    } else if ((isLocalName || (isLocalName = require('../network').isLocalName))(target.host) || allow.has(String(target.host).toLowerCase())) {
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
    constructor(loc, options) {
      try { opened(loc, options); } catch { /* never break the call */ }
      super(loc, options);
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

// -- preload phase (src/cache/early.js) --------------------------------------------------------------------------
// The clock and OS entropy before Level 0 is installed: a preload module that reads them makes the tests of its
// process not cacheable (their values are not controlled, so a result that depends on them is not a function of
// the recorded inputs). The wrappers are removed when the preload phase ends.
const PRELOAD_SAVED = [];

function installPreloadClock(cap) {
  const hit = (what) => {
    if (!cap.preload || !cap.active || cap.busy) return;
    cap.add(['flag', 'preload', `${what} read by a preload module before Level 0`], cap.isGlobal);
  };
  const put = (obj, name, what) => {
    const real = obj && obj[name];
    if (typeof real !== 'function') return;
    const w = function (...a) { hit(what); return real.apply(this, a); };
    realDefine(w, 'name', { value: real.name, configurable: true });
    realDefine(w, 'length', { value: real.length, configurable: true });
    for (const k of Reflect.ownKeys(real)) {
      if (k === 'length' || k === 'name' || k === 'prototype' || k === 'arguments' || k === 'caller') continue;
      try { realDefine(w, k, realGOPD(real, k)); } catch { /* ignore */ }
    }
    try { obj[name] = w; } catch { return; }
    if (obj[name] === w) PRELOAD_SAVED.push([obj, name, real, w]);
  };
  put(Date, 'now', 'the clock');
  put(Math, 'random', 'Math.random');
  if (globalThis.performance) put(globalThis.performance, 'now', 'the clock');
  put(process, 'hrtime', 'the clock');
  if (process.hrtime && process.hrtime.bigint) put(process.hrtime, 'bigint', 'the clock');
  const c = require('node:crypto');
  for (const n of ['randomBytes', 'randomUUID', 'randomInt', 'randomFillSync', 'randomFill', 'getRandomValues']) put(c, n, `crypto.${n}`);
  const wc = globalThis.crypto;
  if (wc) for (const n of ['getRandomValues', 'randomUUID']) put(wc, n, `crypto.${n}`);
  // `new Date()` / `Date()` without arguments
  const RealDate = globalThis.Date;
  const D = new Proxy(RealDate, {
    construct(t, args, nt) { if (args.length === 0) hit('the clock'); return Reflect.construct(t, args, nt === D ? t : nt); },
    apply(t, th, args) { hit('the clock'); return Reflect.apply(t, th, args); },
  });
  globalThis.Date = D;
  PRELOAD_SAVED.push([globalThis, 'Date', RealDate, D]);
}

function uninstallPreloadClock() {
  while (PRELOAD_SAVED.length) {
    const [obj, name, real, w] = PRELOAD_SAVED.pop();
    try { if (obj[name] === w) obj[name] = real; } catch { /* ignore */ }
  }
}

/** The module named by `--loader` / `--experimental-loader` in this process's options (null when there is none). */
function offThreadLoader() {
  const opts = `${(process.execArgv || []).join(' ')} ${process.env.NODE_OPTIONS || ''}`;
  const m = /(?:^|\s)--(?:experimental-)?loader(?:=|\s+)(\S+)/.exec(opts);
  return m ? m[1] : null;
}

// in-thread module hooks registered by the capture (and early.js): Node refuses to mix them with off-thread hooks
// (`module.register`, `--loader`), so they are removed when such hooks are registered (the tests are then not
// cacheable: flag `loader`)
const SYNC_HOOKS = [];

function dropSyncHooks() {
  CAPTURE.loadHooked = false; // module loads are no longer seen: scan the registries every time
  while (SYNC_HOOKS.length) { try { SYNC_HOOKS.pop().deregister(); } catch { /* ignore */ } }
}

function installLoaderHooks(cap) {
  const m = require('node:module');
  // `module.register`: hooks that run in another thread, where reads are not observable (G4 of review r021b);
  // Vitest's own fallback loader (Node < 22.15) is infrastructure
  if (typeof m.register === 'function' && !m.register.__detjsCache) {
    const realRegister = m.register;
    const reg = function register(spec, ...rest) {
      if (cap.active && !cap.busy) {
        cap.busy++;
        let user;
        try { user = cap.preload || cap.caller() === 'user' || cap.pluginFrame(); } finally { cap.busy--; }
        if (user) cap.add(['flag', 'loader', `module.register(${String(spec).slice(0, 200)})`], cap.isGlobal);
      }
      dropSyncHooks();
      return realRegister.call(this, spec, ...rest);
    };
    realDefine(reg, '__detjsCache', { value: true });
    try { m.register = reg; } catch { /* read-only */ }
  }
  if (typeof m.registerHooks !== 'function') {
    cap.notes.add('module.registerHooks unavailable (Node < 22.15): ES modules loaded natively are not listed');
    return;
  }
  if (offThreadLoader()) return;
  try {
    const h = m.registerHooks({
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
        cap.loads++;
        if (cap.active && typeof u === 'string' && u.startsWith('file:')) {
          cap.nativeLoads.add(u.split('?')[0]); // a file: URL, converted by module()
        }
        return next(u, context);
      },
    });
    if (h && typeof h.deregister === 'function') SYNC_HOOKS.push(h);
    cap.loadHooked = true;
  } catch (e) {
    cap.notes.add(`module.registerHooks failed: ${e && e.message}`);
  }
}

const KEY = Symbol.for('detjs.cache.capture');
const CAPTURE = globalThis[KEY] || (globalThis[KEY] = new Capture());

module.exports = { CAPTURE, Capture, machineFacts, installEnv, installReflection, flagsOf, toPath, INFRA, SYNC_HOOKS, offThreadLoader, dropSyncHooks };
