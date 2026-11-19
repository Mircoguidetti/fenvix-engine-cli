'use strict';
// Shared glue for the runner shells that drive a test runner from the outside (tap, AVA, Jasmine, uvu, ...): the
// runner is started as a child process with a preload (src/runners/preload.js, through NODE_OPTIONS so that it also
// reaches the runner's own child processes and worker threads), the detjs main process decides reuse before the
// runner starts, and each test process writes its trace part and its cache capture into the run directory.
//
// Main side (the `detjs <runner>` process): `runShell(spec, argv)`
//   1. options; without --det the runner's CLI runs unchanged;
//   2. session.prepare (DETJS_* environment), ProofSession (--det-cache) with the main-process capture;
//   3. spec.discover(ctx): the test files the runner would run (absolute paths, usually listed by the runner itself in
//      a child process: `listChild`), the configuration parts of the digest, reasons that make everything
//      uncacheable;
//   4. order: files sorted by path (or the runner's own fixed order), shuffled with --det-seed (shared shuffle);
//   5. pc.decide(files) -> the reused files are not run;
//   6. spec.launch(ctx, files): runs the runner on the remaining files in that order, serially;
//   7. ProofSession.finish (records, receipts, summary) and the trace merge.
//
// Child side (inside a test process or worker thread): `child()` installs the Level 0 controls and the cache capture
// before the runner loads anything; `ChildFile` brackets the tests of one test file (trace part, per-test
// fingerprints, capture) and writes the file's capture when it ends (ok) or when the process exits (not ok unless
// it ended cleanly).
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const PRELOAD = path.join(__dirname, 'preload.js');

// -- main side ------------------------------------------------------------------------------------------------------

/** An installed package as the project resolves it: {dir (real path), pkg, bin(name)}. */
function findPackage(root, name) {
  const req = require('node:module').createRequire(path.join(root, 'noop.js'));
  let dir = null;
  try {
    dir = path.dirname(fs.realpathSync(req.resolve(`${name}/package.json`)));
  } catch {
    dir = pkgDir(root, name); // a package whose `exports` hide package.json
  }
  if (!dir) throw new Error(`detjs: ${name} is not installed in ${root}`);
  const pkg = JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8'));
  const bin = (b) => path.join(dir, typeof pkg.bin === 'string' ? pkg.bin : pkg.bin[b || name]);
  return { dir, pkg, version: pkg.version, bin };
}

/** Real directory of package `name` as seen from `fromDir` (node_modules lookup, ignoring `exports`). */
function pkgDir(fromDir, name) {
  let d = fromDir;
  for (;;) {
    const p = path.join(d, 'node_modules', name, 'package.json');
    if (fs.existsSync(p)) return fs.realpathSync(path.dirname(p));
    const up = path.dirname(d);
    if (up === d) return null;
    d = up;
  }
}

function fileIdOf(root, abs) {
  return path.relative(root, abs).split(path.sep).join('/');
}

/** NODE_OPTIONS with the detjs preload added (first, so that it runs before any other preload). */
function nodeOptions(base) {
  const own = `--require ${JSON.stringify(PRELOAD)}`;
  return base ? `${own} ${base}` : own;
}

/** Environment of a process started by the shell (role: 'runner' = the runner's main process, 'list', 'single'). */
function childEnv(role, extra = {}) {
  const env = { ...process.env, ...extra };
  env.DETJS_NODE_OPTIONS0 = process.env.NODE_OPTIONS || '';
  env.NODE_OPTIONS = nodeOptions(process.env.NODE_OPTIONS);
  env.DETJS_RUNNER_ROLE = role;
  // the capture sees Node's loader through asynchronous hooks: the runners' own loaders are asynchronous too
  env.DETJS_CAPTURE_LOADER = 'register';
  return env;
}

/** Run the runner in list mode: the preload writes a JSON document to DETJS_LIST_OUT and the result is returned. */
function listChild(ctx, args, extraEnv = {}) {
  const out = path.join(ctx.run.dir, `list-${process.pid}-${Date.now()}.json`);
  const env = childEnv('list', { ...extraEnv, DETJS_LIST_OUT: out });
  // the listing is the runner's own selection: Level 0 is not needed there (and must not change it)
  env.DETJS = '0';
  const r = spawnSync(process.execPath, args, { cwd: ctx.root, env, encoding: 'utf8', maxBuffer: 256 << 20 });
  let doc = null;
  try { doc = JSON.parse(fs.readFileSync(out, 'utf8')); } catch { /* below */ }
  try { fs.rmSync(out, { force: true }); } catch { /* ignore */ }
  return { doc, status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
}

/** Run a command with the preload; stdio inherited. Returns the exit status. */
function runChild(ctx, args, { role = 'runner', env: extra = {}, cwd } = {}) {
  const env = childEnv(role, { ...extra, DETJS_RUNNER_FILES: ctx.filesPath });
  const r = spawnSync(process.execPath, args, { cwd: cwd || ctx.root, env, stdio: 'inherit' });
  if (r.error) throw r.error;
  return r.status === null ? 1 : r.status;
}

/** Parts of a configuration digest that every adapter adds: the runner's configuration files by content. */
function fileParts(root, files) {
  const native = require('../native');
  const out = [];
  for (const f of files) {
    const abs = path.resolve(root, f);
    out.push([fileIdOf(root, abs), native.fileDigest(abs) || 'missing']);
  }
  return out.sort();
}

/**
 * `spec`: {
 *   name, findRunner(root) -> {version, ...}, plain(rest, runner) -> argv of the unchanged run,
 *   discover(ctx) -> {files: [abs], config: {part: value}, uncacheable: reason|null, notes: [], order: 'path'|'runner'},
 *   launch(ctx, files) -> exit status, isolation(ctx) -> text, compare(a, b) (optional fixed order of the runner),
 *   noFiles(ctx) -> exit status when nothing at all was found (default 1),
 * }
 */
async function runShell(spec, argv) {
  const session = require('../session');
  const native = require('../native');
  const env0 = { ...process.env }; // the environment at session start (cache inputs are digested against it)
  const root = process.cwd();
  const { opts, rest } = session.parseArgs(argv);
  const runner = spec.findRunner(root);
  if (!opts.det) {
    const r = spawnSync(process.execPath, spec.plain(rest, runner), { stdio: 'inherit' });
    return r.status ?? 1;
  }
  const run = session.prepare(opts, root, spec.name);
  const ctx = { root, opts, rest, runner, run, cfg: run.cfg, pc: null, filesPath: path.join(run.dir, 'files.json'), notes: [] };
  if (opts.cache) {
    const { ProofSession } = require('../cache/proof');
    ctx.pc = new ProofSession(opts, root, spec.name, run, env0);
    ctx.pc.installMain({ mainAnyReads: false });
    // content-addressed compile caches of loaders the runners use (ts-node's v8-compile-cache-lib): a cached result
    // equals recomputing it
    const { CAPTURE } = require('../cache/capture');
    const tmp = require('node:os').tmpdir();
    const uid = typeof process.getuid === 'function' ? `-${process.getuid()}` : '';
    for (const d of [`v8-compile-cache${uid}`, 'v8-compile-cache']) CAPTURE.addSkipDir(path.join(tmp, d));
  }
  for (const l of session.header(run, opts, { runner: spec.name, runnerVersion: runner.version, isolation: spec.isolation(ctx) })) {
    process.stdout.write(`${l}\n`);
  }
  const found = await spec.discover(ctx);
  ctx.found = found;
  for (const n of found.notes || []) process.stderr.write(`detjs: ${n}\n`);
  const keyed = found.files.map((abs) => {
    const fileId = fileIdOf(root, abs);
    return { abs, fileId, project: '', key: fileId };
  });
  if (found.order !== 'runner') keyed.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  let ordered = keyed;
  if (run.cfg.shuffle && run.cfg.controls.has('order')) ordered = native.shuffleIndices(keyed.length, run.cfg.seed, '').map((i) => keyed[i]);
  let skip = new Set();
  if (ctx.pc) {
    const parts = { runner: `${spec.name} ${runner.version}`, ...found.config };
    ctx.pc.setConfig(parts);
    if (found.uncacheable) ctx.pc.noteProject('', found.uncacheable);
    skip = await ctx.pc.decide(ordered.map((k) => ({ fileId: k.fileId, project: '', key: k.key })));
  }
  const toRun = ordered.filter((k) => !skip.has(k.key));
  fs.writeFileSync(ctx.filesPath, JSON.stringify(toRun.map((k) => ({ abs: k.abs, fileId: k.fileId }))));
  fs.writeFileSync(path.join(run.dir, 'order.json'), JSON.stringify(toRun.map((k) => ({ fileId: k.fileId, part: require('../controls').partName(k.fileId, '') }))));
  let status;
  if (!keyed.length) status = spec.noFiles ? spec.noFiles(ctx) : 1;
  else if (!toRun.length) status = 0; // every file reused with proof
  else status = await spec.launch(ctx, toRun.map((k) => k.abs), toRun);
  if (ctx.pc) {
    if (found.uncacheable) { /* recorded as misses by the project note */ }
    ctx.pc.finishSync();
    for (const l of await ctx.pc.finish()) process.stdout.write(`${l}\n`);
  }
  const { lines } = session.finish(run, opts, toRun.map((k) => ({ fileId: k.fileId, part: require('../controls').partName(k.fileId, '') })), {
    runner: spec.name, runner_version: runner.version, isolation: spec.isolation(ctx), serial: true, cli_args: rest,
  });
  for (const l of lines) process.stdout.write(`${l}\n`);
  return status;
}

/**
 * The runner's own verdict, from its main process: the captures of the files it reports as failed (or as never
 * finished) are rewritten with ok=false, so that a failure seen only by the runner (an unhandled rejection reported
 * after the file's tests ended, a killed worker) is never recorded as a pass.
 */
function markFailed(ctx, fileIds) {
  const ids = new Set(fileIds);
  if (!ids.size) return;
  const dir = path.join(ctx.run.dir, 'cache');
  let names = [];
  try { names = fs.readdirSync(dir); } catch { return; }
  for (const n of names) {
    const p = path.join(dir, n);
    try {
      const c = JSON.parse(fs.readFileSync(p, 'utf8'));
      if (ids.has(c.fileId) && c.ok) {
        c.ok = false;
        fs.writeFileSync(p, JSON.stringify(c));
      }
    } catch { /* unreadable: not recorded */ }
  }
}

/** Command-line arguments that never change a result (output, reporters, selection handled by detjs). */
function argsPart(rest, volatile) {
  return rest.filter((a) => !volatile.some((re) => re.test(a)));
}

// -- child side -----------------------------------------------------------------------------------------------------

let childStarted = false;
let filesOpened = 0;

/** Real milliseconds (the test's own clock is virtual under Level 0). */
function realNow() {
  return require('../clock').REAL.perfNow();
}

/** Install Level 0 (and the cache capture with --det-cache) in this process or worker thread. */
function child() {
  const controls = require('../controls');
  const c = controls.cfg();
  if (!c.active) return null;
  if (!childStarted) {
    childStarted = true;
    // the standard streams' handles exist before the virtual timers take their baseline of pending I/O (a pipe
    // created later would count as I/O and make every virtual timer wait for real)
    void process.stdout;
    void process.stderr;
    controls.installProcess();
    controls.installRealm(globalThis, { sameRealm: true });
    if (process.env.DETJS_CACHE === '1') {
      const { CAPTURE } = require('../cache/capture');
      CAPTURE.install({ role: 'worker', root: c.root });
      // OS entropy drawn by the runner itself (tap's mock service keys, ...) is the runner's business: only a draw
      // whose direct caller is not runner infrastructure makes a test not cacheable
      const realLevel = CAPTURE.levelEvent.bind(CAPTURE);
      CAPTURE.levelEvent = (source, value) => {
        if (source === 'entropy' && CAPTURE.active && !CAPTURE.busy) {
          CAPTURE.busy++;
          let who;
          try { who = CAPTURE.directCaller(); } finally { CAPTURE.busy--; }
          if (who === 'infra') return undefined;
        }
        return realLevel(source, value);
      };
    }
  }
  return c;
}

/** The files this run executes ([{abs, fileId}]), written by the main side. */
function runFiles() {
  const p = process.env.DETJS_RUNNER_FILES;
  if (!p) return [];
  try { return JSON.parse(quiet(() => fs.readFileSync(p, 'utf8'))); } catch { return []; }
}

/** Run fn without the capture recording detjs' own file accesses. */
function quiet(fn) {
  const cap = globalThis[Symbol.for('detjs.cache.capture')];
  if (cap) cap.busy++;
  try { return fn(); } finally { if (cap) cap.busy--; }
}

/** One test file inside a test process: trace part, test brackets, cache capture. */
class ChildFile {
  constructor(fileId) {
    const controls = require('../controls');
    this.fileId = fileId;
    this.c = controls.cfg();
    this.cap = process.env.DETJS_CACHE === '1' ? require('../cache/capture').CAPTURE : null;
    this.seen = new Map();
    this.closed = false;
    this.failed = false;
    this.t0 = realNow();
    this.current = null;
    this.extraModules = [];
    controls.openFile(fileId, '');
    if (this.cap) {
      // the first file of a process keeps everything logged since the preload (loaders and modules the runner
      // loaded for it before it knew the file's name); a later file of the same process starts afresh
      if (filesOpened > 0) this.cap.resetFile();
      this.cap.setCtx('f', fileId);
    }
    filesOpened++;
  }

  /** Unique id of a test of this file (`name #2` for a duplicate title). */
  id(name) {
    const base = `${this.fileId}::${name}`;
    const n = (this.seen.get(base) || 0) + 1;
    this.seen.set(base, n);
    return n === 1 ? base : `${base} #${n}`;
  }

  begin(id) {
    const { STATE } = require('../state');
    if (this.current !== null) this.end(this.current.id, 'interrupted');
    if (!this.baselined) {
      // pending I/O is counted from the file's first test on: the runner's own handles (its IPC channel, the pipes
      // of the standard streams) and what the file opened while loading are not I/O of the tests
      this.baselined = true;
      if (this.c.controls.has('time')) require('../clock').DRIVER.takeBaseline();
    }
    this.current = { id, t0: realNow() };
    // what the asynchronous loader hooks posted so far (node:sqlite imported by the test's module, ...)
    if (this.cap && this.cap.flushLoader) this.cap.flushLoader();
    STATE.beginTest(id);
    if (this.cap) this.cap.setCtx('t');
  }

  end(id, outcome, duration) {
    const { STATE } = require('../state');
    if (this.current === null || this.current.id !== id) return;
    const dur = duration ?? (realNow() - this.current.t0) / 1000;
    this.current = null;
    const fp = STATE.endTest(outcome);
    if (outcome !== 'passed' && outcome !== 'skipped' && outcome !== 'todo') this.failed = true;
    if (this.cap) {
      this.cap.testEnd(id, outcome, dur, fp);
      this.cap.setCtx('f');
    }
  }

  /** A test the runner reported without running it (skipped, todo). */
  notRun(id, outcome) {
    if (this.cap) this.cap.tests.push({ id, outcome, duration: 0, fingerprint: '', upto: this.cap.log.length });
  }

  /** End of the file: close the trace part and write the capture (`ok`: the runner's verdict for the file). */
  close(ok) {
    if (this.closed) return;
    this.closed = true;
    const controls = require('../controls');
    if (this.current !== null) this.end(this.current.id, 'interrupted');
    controls.closeFile();
    this.writeCapture(ok && !this.failed);
  }

  /** Rewrite the capture with ok=false (the process failed after the file ended). */
  fail() {
    this.failed = true;
    if (!this.closed) this.close(false);
    else if (this.written) this.writeCapture(false);
  }

  writeCapture(ok) {
    if (!this.cap || !this.c.dir) return;
    const controls = require('../controls');
    quiet(() => {
      try {
        const capture = this.cap.fileCapture({ fileId: this.fileId, project: '', label: this.fileId, ok, duration: (realNow() - this.t0) / 1000 }, this.extraModules);
        const name = `${controls.partName(this.fileId, '').replace(/\.jsonl$/, '')}-${process.pid}-${require('node:worker_threads').threadId}.json`;
        controls.writeJson(path.join(this.c.dir, 'cache', name), capture);
        this.written = true;
      } catch (e) {
        process.stderr.write(`detjs cache: capture of ${this.fileId} not written: ${e && e.stack}\n`);
      }
    });
  }

  /** Mark the file not cacheable (a runner mechanism the capture cannot see). */
  flag(flag, detail) {
    if (this.cap) this.cap.add(['flag', flag, String(detail || '')], false);
  }
}

/** The file being run in this process, when the process runs exactly one file (per-file processes). */
function onExit(file, isOk) {
  process.on('exit', (code) => {
    const ok = (code === 0 || code === undefined) && (process.exitCode === undefined || process.exitCode === 0) && isOk();
    if (!ok) file.fail();
    else file.close(true);
  });
}

module.exports = {
  PRELOAD, findPackage, pkgDir, fileIdOf, nodeOptions, childEnv, listChild, runChild, fileParts, runShell, argsPart, markFailed,
  child, runFiles, quiet, ChildFile, onExit,
};
