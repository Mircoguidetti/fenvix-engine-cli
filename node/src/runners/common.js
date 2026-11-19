'use strict';
// Runner shells that drive a test runner from the outside: the main-process glue they share, and the two ways a
// shell runs the test files.
//
// Shared (main side): the run's file order (sorted, or the core's reproducible shuffle with --det-seed: the same
// permutation as the Vitest/Jest shells), the capture files of a test file in the run directory, and the rewrite of
// a capture as failed when the runner (not the in-process bracket) saw the file fail. Options are session.js's, the
// reuse decision and the records cache/proof.js's ProofSession, the trace merge session.finish: never copied here.
//
// 1. Non-Node runtimes (`detjs bun-test`, `detjs deno-test`): `runFileProcesses`.
//    The test runtime (Bun, Deno) is not Node, but it loads the same detjs modules and the same native core
//    (crates/detpy-node through Node-API, see docs/runners/bun.md and deno.md): its preload installs the Level 0
//    controls and the capture, brackets every test, and writes the trace part (<run dir>/parts) and, under
//    --det-cache, the capture of its file (<run dir>/cache) in the formats the Vitest and Jest shells write. This
//    process (Node) does everything else. Unit of execution: one test file per runtime process. Both runtimes share
//    state between the files of one process (Bun: one global object for every file; Deno: one OS process, so the
//    environment, the working directory and written files), so a file never runs in a context the reference run did
//    not have (docs/ALL-RUNNERS.md, "a fresh process per file").
//
// 2. Node runners started with a preload (`detjs tap|ava|jasmine|uvu`): `runShell(spec, argv)`.
//    The runner is started as a child process with a preload (src/runners/preload.js, through NODE_OPTIONS so that
//    it also reaches the runner's own child processes and worker threads):
//      1. options; without --det the runner's CLI runs unchanged;
//      2. session.prepare (DETJS_* environment), ProofSession (--det-cache) with the main-process capture;
//      3. spec.discover(ctx): the test files the runner would run (absolute paths, usually listed by the runner itself
//         in a child process: `listChild`), the configuration parts of the digest, reasons that make everything
//         uncacheable;
//      4. order: `orderFiles` (sorted, or the runner's own fixed order; shuffled with --det-seed);
//      5. pc.decide(files) -> the reused files are not run;
//      6. spec.launch(ctx, files): runs the runner on the remaining files in that order, serially;
//      7. ProofSession.finish (records, receipts, summary) and the trace merge.
//    Child side (inside a test process or worker thread): `child()` installs the Level 0 controls and the cache
//    capture before the runner loads anything; `ChildFile` brackets the tests of one test file (trace part, per-test
//    fingerprints, capture) and writes the file's capture when it ends (ok) or when the process exits (not ok unless
//    it ended cleanly).
//
// This module is also loaded inside test processes (by the preload): detjs modules are required lazily.
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const PRELOAD = path.join(__dirname, 'preload.js');

// -- shared (main side) ---------------------------------------------------------------------------------------------

/**
 * Files in run order: sorted by `key` (unless `sorted: false`: the runner's own fixed order), then the core's
 * reproducible shuffle with the seed (the same permutation as the other shells).
 */
function orderFiles(items, cfg, { key = (x) => x, sorted = true } = {}) {
  const list = [...items];
  if (sorted) list.sort((a, b) => { const ka = key(a); const kb = key(b); return ka < kb ? -1 : ka > kb ? 1 : 0; });
  if (cfg.shuffle && cfg.controls.has('order')) return require('../native').shuffleIndices(list.length, cfg.seed, '').map((i) => list[i]);
  return list;
}

/** Capture files written for one test file (by its test processes) in the run directory. */
function captureFiles(run, fileId) {
  const dir = path.join(run.dir, 'cache');
  const prefix = require('../controls').partName(fileId, '').replace(/\.jsonl$/, '');
  let names = [];
  try { names = fs.readdirSync(dir); } catch { return []; }
  return names.filter((n) => n.startsWith(`${prefix}-`) && n.endsWith('.json')).map((n) => path.join(dir, n));
}

/**
 * The runner's own verdict, from its main process: the captures of the files it reports as failed (or as never
 * finished) are rewritten with ok=false, so that a failure seen only by the runner (an unhandled rejection reported
 * after the file's tests ended, a killed worker) is never recorded as a pass.
 */
function markFailed(ctx, fileIds) {
  for (const id of new Set(fileIds)) {
    for (const p of captureFiles(ctx.run, id)) {
      try {
        const c = JSON.parse(fs.readFileSync(p, 'utf8'));
        if (c.fileId === id && c.ok) {
          c.ok = false;
          fs.writeFileSync(p, JSON.stringify(c));
        }
      } catch { /* unreadable: not recorded */ }
    }
  }
}

// -- 1. non-Node runtimes: one runtime process per file ------------------------------------------------------------

/** An executable on PATH (or the value of `envName`), or null. */
function findBinary(name, envName) {
  const fromEnv = process.env[envName];
  if (fromEnv) return fromEnv;
  for (const dir of String(process.env.PATH || '').split(path.delimiter)) {
    if (!dir) continue;
    const p = path.join(dir, name);
    try {
      fs.accessSync(p, fs.constants.X_OK);
      if (fs.statSync(p).isFile()) return p;
    } catch { /* next */ }
  }
  for (const p of [path.join(require('node:os').homedir(), `.${name}`, 'bin', name)]) {
    try { fs.accessSync(p, fs.constants.X_OK); return p; } catch { /* none */ }
  }
  return null;
}

/**
 * Split runner arguments into options and positional paths/filters. `valueFlags`: options that take a value in
 * the next argument when written without `=`.
 */
function splitArgs(rest, valueFlags) {
  const options = [];
  const positional = [];
  for (let i = 0; i < rest.length; i++) {
    const a = rest[i];
    if (a === '--') { positional.push(...rest.slice(i + 1)); break; }
    if (a.startsWith('-')) {
      options.push(a);
      if (!a.includes('=') && valueFlags.has(a) && i + 1 < rest.length) options.push(rest[++i]);
      continue;
    }
    positional.push(a);
  }
  return { options, positional };
}

/** Value of option `names` in `options` (last one wins), or undefined. */
function optionValue(options, names) {
  let v;
  for (let i = 0; i < options.length; i++) {
    const a = options[i];
    for (const n of names) {
      if (a === n && i + 1 < options.length && !options[i + 1].startsWith('-')) v = options[i + 1];
      else if (a.startsWith(`${n}=`)) v = a.slice(n.length + 1);
    }
  }
  return v;
}

/** Remove options `names` (and their values) from `options`. */
function dropOptions(options, names, valueFlags) {
  const out = [];
  for (let i = 0; i < options.length; i++) {
    const a = options[i];
    const base = a.includes('=') ? a.slice(0, a.indexOf('=')) : a;
    if (names.has(base)) {
      if (!a.includes('=') && valueFlags.has(base) && i + 1 < options.length && !options[i + 1].startsWith('-')) i++;
      continue;
    }
    out.push(a);
  }
  return out;
}

/** Seed for the runner's own ordering of the tests inside one file (derived by the core from the run's seed). */
function fileSeed(cfg, fileId) {
  return BigInt.asUintN(31, BigInt(require('../native').deriveSeed(cfg.seed, `${fileId}\0tests`))).toString();
}

/**
 * After the process of a test file ended: its capture is ok only when the runtime itself reported success (exit
 * status 0). Anything the preload did not see failing (a timeout, a failed hook, a leak the runner's sanitizer
 * found, an unhandled error between tests) makes the whole file a failure, which is never reused. `extra(capture)`
 * may add items (Deno: the module graph and the audit of the runtime's permission checks).
 */
function settleCapture(run, fileId, status, extra) {
  const files = captureFiles(run, fileId);
  for (const f of files) {
    let c;
    try { c = JSON.parse(fs.readFileSync(f, 'utf8')); } catch { fs.rmSync(f, { force: true }); continue; }
    c.ok = Boolean(c.ok) && status === 0;
    c.status = status;
    if (extra) extra(c);
    fs.writeFileSync(f, JSON.stringify(c));
  }
  return files.length;
}

/** Merge JUnit XML reports (one per file process) into one file: the content of each part's <testsuites>. */
function mergeJunit(parts, out, name) {
  const bodies = [];
  const tot = { tests: 0, failures: 0, errors: 0, skipped: 0, time: 0 };
  for (const p of parts) {
    let x;
    try { x = fs.readFileSync(p, 'utf8'); } catch { continue; }
    const open = /<testsuites\b([^>]*)>/.exec(x);
    const close = x.lastIndexOf('</testsuites>');
    if (!open || close < 0) continue;
    bodies.push(x.slice(open.index + open[0].length, close).trim());
    for (const k of Object.keys(tot)) {
      const r = new RegExp(`\\b${k}="([^"]*)"`).exec(open[1]);
      if (r) tot[k] += Number(r[1]) || 0;
    }
  }
  fs.mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
  fs.writeFileSync(out, `<?xml version="1.0" encoding="UTF-8"?>\n<testsuites name="${name}" tests="${tot.tests}" failures="${tot.failures}" `
    + `errors="${tot.errors}" skipped="${tot.skipped}" time="${tot.time}">\n${bodies.join('\n')}\n</testsuites>\n`);
}

/**
 * Run the files of a --det session, one runtime process per file.
 *
 * @param {object} p
 *   runner, runnerVersion: names for the header and the trace;
 *   root, opts, run (session.prepare), pc (ProofSession or null);
 *   fileIds: test files (paths relative to root) in the order to run;
 *   spawnFile(fileId, index, env) -> {status} (synchronous);
 *   isolation: text for the header and the trace; meta: trace metadata;
 *   extra(capture, fileId): optional, see settleCapture.
 */
async function runFileProcesses(p) {
  const session = require('../session');
  const controls = require('../controls');
  const { run, opts, pc } = p;
  let ordered = p.fileIds;
  let skip = new Set();
  if (pc) {
    if (!ordered.length) pc.noTestsFound = true;
    skip = await pc.decide(ordered.map((f) => ({ fileId: f, project: '', key: f })));
  }
  for (const l of session.header(run, opts, { runner: p.runner, runnerVersion: p.runnerVersion, isolation: p.isolationShort || 'process per file' })) {
    process.stdout.write(`${l}\n`);
  }
  const executed = [];
  let failed = 0;
  let ran = 0;
  for (let i = 0; i < ordered.length; i++) {
    const f = ordered[i];
    if (skip.has(f)) continue;
    const env = { DETJS_FILE: f };
    const r = p.spawnFile(f, i, env);
    const status = r.status === null || r.status === undefined ? 1 : r.status;
    ran++;
    if (status !== 0) failed++;
    executed.push({ fileId: f, part: controls.partName(f, '') });
    if (pc) settleCapture(run, f, status, p.extra ? (c) => p.extra(c, f, r) : null);
  }
  ordered = executed;
  if (p.afterRun) p.afterRun();
  let lines = [];
  if (pc) {
    lines = await pc.finish();
  }
  const fin = session.finish(run, opts, ordered, {
    runner: p.runner, runner_version: p.runnerVersion, isolation: p.isolation, serial: true, cli_args: p.cliArgs || [], ...(p.meta || {}),
  });
  for (const l of [...lines, ...fin.lines]) process.stdout.write(`${l}\n`);
  if (!p.fileIds.length) {
    process.stderr.write(`detjs ${p.runner}: no test files found\n`);
    return 1;
  }
  process.stdout.write(`detjs ${p.runner}: ${ran} files ran (${failed} failed), ${p.fileIds.length - ran} reused\n`);
  return failed ? 1 : 0;
}

/** Digest of a file, or a marker (missing files are configuration too). */
function fileDigestOr(p) {
  if (!p) return '';
  return require('../native').fileDigest(p) || `missing:${p}`;
}

/** spawnSync with inherited output, returning {status}. */
function runInherit(cmd, args, opts) {
  const r = spawnSync(cmd, args, { stdio: 'inherit', ...opts });
  if (r.error) process.stderr.write(`detjs: ${cmd}: ${r.error.message}\n`);
  return { status: r.status === null ? (r.signal ? 128 : 1) : r.status, signal: r.signal };
}

// -- 2. Node runners started with a preload: main side -------------------------------------------------------------

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
  const ordered = orderFiles(keyed, run.cfg, { key: (k) => k.key, sorted: found.order !== 'runner' });
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

/** Command-line arguments that never change a result (output, reporters, selection handled by detjs). */
function argsPart(rest, volatile) {
  return rest.filter((a) => !volatile.some((re) => re.test(a)));
}

// -- 2. child side -----------------------------------------------------------------------------------------------------

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
  // shared
  PRELOAD, orderFiles, captureFiles, markFailed,
  // 1. non-Node runtimes
  findBinary, splitArgs, optionValue, dropOptions, fileSeed, settleCapture, mergeJunit, runFileProcesses, fileDigestOr, runInherit,
  // 2. Node runners with a preload (main side, then child side)
  findPackage, pkgDir, fileIdOf, nodeOptions, childEnv, listChild, runChild, fileParts, runShell, argsPart,
  child, runFiles, quiet, ChildFile, onExit,
};
