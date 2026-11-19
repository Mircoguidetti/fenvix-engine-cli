'use strict';
// `detjs tap [--det ...] [tap args]` (node-tap, the `tap` package, v18+: @tapjs/run and @tapjs/core).
//
// tap runs every test file in its own child process (`node <loaders> file`); detjs keeps that model:
//   * discovery: `tap list` (the runner's own file selection and configuration: .taprc, package.json "tap",
//     command line), in a child process whose preload also reports tap's resolved configuration values;
//   * the runner process (`tap --jobs=1 --save=<the files to run>`): files run one at a time; the preload releases
//     the runner's per-file subtests in detjs' order (tap's own order depends on the completion order of
//     asynchronous `stat` calls); `--save` restricts the run to the files that are not reused;
//   * each test process (TAP_CHILD_ID set, argv[1] one of the files to run): Level 0 and the cache capture are
//     installed before tap loads; the root TAP object (caught when tap registers its singleton on globalThis) is
//     forced to jobs=1, and every top-level subtest (`t.test`) is a test of the file (begin: subtestStart, end:
//     subtestEnd; nested subtests and assertions belong to it). The file's verdict is the root's results and the
//     process exit code.
// Not cached: tap `before` / `after` scripts (they run outside the test processes and can change what tests read).
const fs = require('node:fs');
const path = require('node:path');
const common = require('./common');

const RUNNER_ENV = /^(TAP_CHILD_ID|TAP_JOB_ID|TAP_CHILD_KEY|_TAPJS_PROCESSINFO_\w*)$/;
// configuration values that never change a test's result (output, scheduling detjs replaces, selection by detjs)
const VOLATILE = new Set(['reporter', 'reporter-arg', 'reporter-file', 'color', 'no-color', 'jobs', 'save', 'changed', 'coverage-report',
  'disable-coverage', 'allow-empty-coverage', 'allow-incomplete-coverage', 'show-full-coverage', 'output-file', 'output-dir',
  'help', 'version', 'versions', 'debug', 'omit-version', 'passes', 'serial', 'statements', 'branches', 'functions', 'lines']);

function findRunner(root) {
  const p = common.findPackage(root, 'tap');
  const runDir = common.pkgDir(p.dir, '@tapjs/run');
  const coreDir = common.pkgDir(runDir || p.dir, '@tapjs/core');
  if (!runDir || !coreDir) throw new Error(`detjs: tap ${p.version} without @tapjs/run and @tapjs/core (need tap >= 18)`);
  return { ...p, binPath: p.bin('tap'), runDir, coreDir };
}

const isOpt = (a, names) => names.some((n) => a === n || a.startsWith(`${n}=`));

/** The user's arguments minus what detjs sets itself (jobs, save list). */
function userArgs(rest) {
  const out = [];
  for (let i = 0; i < rest.length; i++) {
    const a = rest[i];
    if (isOpt(a, ['--jobs', '--save', '--changed', '--disable-coverage'])) {
      if (!a.includes('=') && ['--jobs', '--save'].includes(a)) i++;
      continue;
    }
    if (/^-j\d*$/.test(a)) { if (a === '-j') i++; continue; }
    out.push(a);
  }
  return out;
}

async function discover(ctx) {
  const { runner, rest } = ctx;
  const args = userArgs(rest);
  const l = common.listChild(ctx, [runner.binPath, 'list', ...args], { DETJS_TAP_RUN_DIR: runner.runDir });
  const doc = l.doc || {};
  const projectRoot = doc.projectRoot || ctx.root;
  ctx.projectRoot = projectRoot;
  const files = l.stdout.split('\n').map((s) => s.trim()).filter(Boolean).filter((s) => s !== '-' && s !== '/dev/stdin')
    .map((s) => path.resolve(projectRoot, s));
  const notes = [];
  if (l.status !== 0 && !files.length) notes.push(`tap list failed (status ${l.status}): ${l.stderr.slice(-500)}`);
  const values = {};
  for (const [k, v] of Object.entries(doc.values || {})) if (!VOLATILE.has(k)) values[k] = v;
  const { stable } = require('../cache/proof');
  const config = {
    tap: doc.values ? stable(values) : `unknown ${Date.now()}`, // never equal: nothing is reused without a known configuration
    tapConfigFile: doc.configFile ? common.fileParts(ctx.root, [doc.configFile]) : null,
    pluginSignature: doc.pluginSignature || null,
    args: common.argsPart(args, [/^--?(reporter|R)\b/, /^--(color|no-color)\b/, /^-c$/]).filter((a) => a.startsWith('-')).sort(),
  };
  let uncacheable = null;
  if (doc.values && (doc.values.before || doc.values.after)) uncacheable = 'tap before/after script (runs outside the test processes)';
  if (ctx.pc) {
    const { CAPTURE } = require('../cache/capture');
    // tap's own bookkeeping (process info for coverage and --changed, saved results): never test inputs
    for (const d of ['processinfo', 'test-results', 'coverage', 'report']) CAPTURE.addSkipDir(path.join(projectRoot, '.tap', d));
  }
  return { files, config, uncacheable, notes, order: 'path' };
}

function launch(ctx, files) {
  const { runner, rest } = ctx;
  const save = path.join(ctx.run.dir, 'tap-save.txt');
  fs.writeFileSync(save, `${files.map((f) => common.fileIdOf(ctx.projectRoot || ctx.root, f)).join('\n')}\n`);
  // coverage of a run that skips files is meaningless (and tap fails a run whose coverage is incomplete)
  const extra = ['--jobs=1', `--save=${save}`, ...(ctx.pc ? ['--disable-coverage'] : [])];
  return common.runChild(ctx, [runner.binPath, ...userArgs(rest), ...extra], {
    env: { DETJS_TAP_RUN_DIR: runner.runDir, DETJS_TAP_CORE_DIR: runner.coreDir },
  });
}

function main(argv) {
  return common.runShell({
    name: 'tap',
    findRunner,
    plain: (rest, r) => [r.binPath, ...rest],
    discover,
    launch,
    isolation: () => 'tap --jobs=1: one test file at a time, each in its own process; top-level subtests in declaration order',
  }, argv);
}

// -- preload --------------------------------------------------------------------------------------------------------

const TAP_KEY = Symbol.for('TAP private constructor');

/** Catch tap's root singleton when it is created (tap stores it on globalThis). */
function onTapRoot(fn) {
  let inst;
  Object.defineProperty(globalThis, TAP_KEY, {
    configurable: true,
    enumerable: false,
    get() { return inst; },
    set(v) {
      const first = inst === undefined;
      inst = v;
      if (first && v) fn(v);
    },
  });
}

/** List mode: report tap's parsed configuration (the listing itself is `tap list` on stdout). */
function preloadList() {
  const out = process.env.DETJS_LIST_OUT;
  const runDir = process.env.DETJS_TAP_RUN_DIR;
  if (!out || !runDir) return;
  const doc = {};
  const { pathToFileURL } = require('node:url');
  import(pathToFileURL(path.join(runDir, 'dist', 'esm', 'main-config.js')).href).then((m) => {
    doc.values = m.values;
    doc.args = m.args;
    doc.projectRoot = m.config && m.config.projectRoot;
    doc.configFile = m.config && m.config.configFile;
    doc.pluginSignature = m.config && m.config.pluginSignature;
  }, (e) => { doc.error = String(e && e.stack); });
  process.on('exit', () => {
    try { fs.writeFileSync(out, JSON.stringify(doc)); } catch { /* the main side reports a missing listing */ }
  });
}

/** The runner process: release the per-file subtests in detjs' order. */
function preloadRunner() {
  process.env.DETJS_RUNNER_ROLE = 'child';
  const coreDir = process.env.DETJS_TAP_CORE_DIR;
  const files = common.runFiles();
  const order = new Map(files.map((f, i) => [f.abs, i]));
  const { TestBase } = require(path.join(coreDir, 'dist', 'esm', 'test-base.js'));
  const real = TestBase.prototype.sub;
  const RUNNER = Symbol.for('tap.isRunner');
  const realSetTimeout = setTimeout;
  let pending = [];
  let timer = null;
  let released = false;
  const flush = () => {
    if (released) return;
    released = true;
    if (timer) clearTimeout(timer);
    const rank = (x) => {
      const abs = path.resolve(x.extra.cwd || process.cwd(), String(x.extra.externalID));
      return order.has(abs) ? order.get(abs) : files.length;
    };
    const list = pending.map((x, i) => ({ x, i, r: rank(x) })).sort((a, b) => a.r - b.r || a.i - b.i).map((e) => e.x);
    pending = [];
    for (const x of list) {
      const p = real.call(x.self, x.Class, x.extra, x.caller);
      p.then(x.resolve, x.reject);
    }
  };
  TestBase.prototype.sub = function sub(Class, extra = {}, caller = undefined) {
    if (released || this.context !== RUNNER || !extra || extra.externalID === undefined) {
      return real.call(this, Class, extra, caller || sub);
    }
    let resolve;
    let reject;
    const promise = new Promise((a, b) => { resolve = a; reject = b; });
    pending.push({ self: this, Class, extra, caller: caller || sub, resolve, reject });
    if (pending.length >= files.length) flush();
    else {
      if (timer) clearTimeout(timer);
      timer = realSetTimeout(flush, 3000); // a file tap did not schedule (filtered out): release what arrived
    }
    return Object.assign(promise, { subtest: null });
  };
}

/** A test process: Level 0, capture, and the test brackets of its file. */
function preloadChild() {
  if (process.env.TAP_CHILD_ID === undefined || !process.argv[1]) return;
  const files = common.runFiles();
  let me = path.resolve(process.argv[1]);
  let match = files.find((f) => f.abs === me);
  if (!match) {
    try { me = fs.realpathSync(me); } catch { /* keep */ }
    match = files.find((f) => { try { return fs.realpathSync(f.abs) === me; } catch { return false; } });
  }
  if (!match) return;
  // processes a test starts are not test processes, and see the user's NODE_OPTIONS
  process.env.DETJS_RUNNER_ROLE = 'nested';
  if (process.env.DETJS_NODE_OPTIONS0) process.env.NODE_OPTIONS = process.env.DETJS_NODE_OPTIONS0;
  else delete process.env.NODE_OPTIONS;
  const c = common.child();
  if (!c) return;
  const file = new common.ChildFile(match.fileId);
  if (file.cap) {
    // variables tap sets per child process (child and job ids, coverage bookkeeping) differ from the session's
    // environment, against which reads are keyed: a test that reads them is not cached
    const cap = file.cap;
    const realEnv = cap.env.bind(cap);
    cap.env = (name) => {
      if (typeof name === 'string' && RUNNER_ENV.test(name) && cap.active && !cap.busy) {
        cap.busy++;
        let user;
        try { user = cap.directCaller() === 'user'; } finally { cap.busy--; }
        if (user) cap.add(['flag', 'env-unobserved', `${name} (set by tap for each test process)`], false);
      }
      return realEnv(name);
    };
  }
  let rootOk = null;
  onTapRoot((t) => {
    try {
      Object.defineProperty(t, 'jobs', {
        configurable: true,
        get() { return 1; },
        set(v) { if (v > 1) require('../state').STATE.notes.push(`tap: t.jobs=${v} ignored (serial under --det)`); },
      });
    } catch { /* keep tap's value */ }
    let cur = null;
    t.on('subtestStart', (p) => {
      cur = { p, id: file.id(p.name) };
      file.begin(cur.id);
    });
    // the end of a subtest: 'subtestProcess' (its result is final and printed; 'subtestEnd' can come after the
    // next subtest started)
    const ended = (p) => {
      if (cur && cur.p === p) {
        const ok = typeof p.passing === 'function' ? p.passing() : !(p.results && !p.results.ok);
        file.end(cur.id, ok ? 'passed' : 'failed');
        cur = null;
      }
    };
    t.on('subtestProcess', ended);
    t.on('subtestEnd', ended);
    t.on('complete', (results) => {
      rootOk = Boolean(results && results.ok);
      file.close(rootOk);
    });
  });
  common.onExit(file, () => rootOk !== false);
}

function preload(role) {
  if (role === 'list') preloadList();
  else if (role === 'runner') preloadRunner();
  else if (role === 'child') preloadChild();
}

module.exports = { main, preload };
