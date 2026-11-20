'use strict';
// `detjs ava [--det ...] [ava args]` (AVA 6+; built against AVA 8).
//
// AVA runs every test file in its own worker thread (default) or child process (`--no-worker-threads`,
// `workerThreads: false`); detjs keeps the configured model and adds:
//   * discovery: AVA itself in list mode (the preload replaces the scheduler's ordering step, which receives the
//     files AVA selected from its configuration, globs and command-line filters, writes them and runs none);
//     the configuration digest is AVA's resolved configuration (`loadConfig`: ava.config.*, package.json "ava"),
//     the configuration file and the command-line options;
//   * the run: `--concurrency=1 --serial` (one file at a time, the tests of a file one after the other); the
//     scheduler step returns detjs' order restricted to the files that are not reused (AVA's own order puts the
//     files that failed last time first: `failingTestsFirst`, a cross-run dependency);
//   * each worker thread or worker process: Level 0 and the cache capture are installed by the preload (NODE_OPTIONS
//     reaches worker threads), before AVA loads the test file; AVA's Runner (lib/runner.js) is patched in that
//     realm: `runTest` brackets every test (beforeEach and afterEach hooks included), `start` orders the tasks
//     (fixed: declaration order, serial tests first as AVA does; --det-seed: shuffle), `saveSnapshotState` ends the
//     file (snapshots written);
//   * the main process reports every file AVA saw fail (hook failures, uncaught exceptions, unhandled rejections,
//     timeouts, workers that never finished): their captures are never recorded as passes.
// Not cached: a test file that uses a shared worker (`ava/plugin`: code running in AVA's main process).
const fs = require('node:fs');
const path = require('node:path');
const common = require('./common');

const VOLATILE_CONF = new Set(['tap', 'verbose', 'color', 'concurrency', 'serial', 'cache', 'failFast', 'watchMode', 'sortTestFiles', 'utilizeParallelBuilds', 'match']);
const FAIL_EVENTS = new Set(['hook-failed', 'test-failed', 'internal-error', 'process-exit', 'uncaught-exception', 'unhandled-rejection',
  'worker-failed', 'missing-ava-import', 'line-number-selection-error', 'shared-worker-error', 'timeout', 'interrupt']);

function findRunner(root) {
  const p = common.findPackage(root, 'ava');
  return { ...p, binPath: p.bin('ava') };
}

const VALUE_FLAGS = new Set(['--match', '-m', '--concurrency', '-c', '--timeout', '-T', '--node-arguments', '--config']);

/** The user's arguments minus the scheduling options detjs sets. */
function userArgs(rest) {
  const out = [];
  for (let i = 0; i < rest.length; i++) {
    const a = rest[i];
    if (/^(--concurrency|-c)(=|$)/.test(a)) { if (!a.includes('=')) i++; continue; }
    if (a === '--serial' || a === '-s' || a === '--no-serial' || a === '--fail-fast') continue;
    out.push(a);
  }
  return out;
}

async function discover(ctx) {
  const { runner, rest } = ctx;
  const args = userArgs(rest);
  const l = common.listChild(ctx, [runner.binPath, ...args], { DETJS_AVA_DIR: runner.dir });
  const doc = l.doc || {};
  const files = (doc.files || []).map((f) => path.resolve(ctx.root, f));
  const notes = [];
  if (!l.doc) notes.push(`ava list failed (status ${l.status}): ${(l.stderr || l.stdout).slice(-800)}`);
  // AVA's resolved configuration, loaded here like AVA's CLI does (its imports are start-up reads of this process)
  let conf = null;
  let configFile = null;
  try {
    const { loadConfig } = require(path.join(runner.dir, 'lib', 'load-config.js'));
    const configArg = args.find((a) => a.startsWith('--config='));
    const res = await loadConfig({ resolveFrom: ctx.root, ...(configArg ? { configFile: configArg.slice('--config='.length) } : {}) });
    const loaded = (res && res.config) || {};
    conf = {};
    for (const [k, v] of Object.entries(loaded)) if (!VOLATILE_CONF.has(k) && k !== 'projectDir' && k !== 'configFile') conf[k] = v;
    configFile = loaded.configFile || null;
  } catch (e) {
    notes.push(`ava configuration not loaded: ${e && e.message}`);
  }
  const { stable } = require('../cache/proof');
  const cfgFiles = fs.readdirSync(ctx.root).filter((n) => /^ava\.config\.[cm]?js$|^ava\.config\.json$/.test(n));
  const config = {
    ava: conf ? stable(conf) : `unknown ${Date.now()}`,
    avaConfigFiles: common.fileParts(ctx.root, [...cfgFiles, ...(configFile ? [configFile] : [])]),
    args: args.filter((a) => a.startsWith('-') && !/^--(tap|verbose|color|no-color|reset-cache)\b|^-[tv]$/.test(a)).sort(),
    workerThreads: conf && conf.workerThreads === false || args.includes('--no-worker-threads') ? 'processes' : 'threads',
  };
  return { files, config, uncacheable: null, notes, order: 'path' };
}

function launch(ctx, files, toRun) {
  const { runner, rest } = ctx;
  const out = path.join(ctx.run.dir, 'ava-status.json');
  const status = common.runChild(ctx, [runner.binPath, ...userArgs(rest), '--concurrency=1', '--serial'], {
    env: { DETJS_AVA_DIR: runner.dir, DETJS_AVA_STATUS: out },
  });
  // the runner's verdict per file (see the header)
  let st = null;
  try { st = JSON.parse(fs.readFileSync(out, 'utf8')); } catch { /* none: every file is suspect */ }
  const failed = [];
  for (const k of toRun) {
    if (!st || st.failed.includes(k.abs) || !st.finished.includes(k.abs)) failed.push(k.fileId);
  }
  common.markFailed(ctx, failed);
  return status;
}

function main(argv) {
  return common.runShell({
    name: 'ava',
    findRunner,
    plain: (rest, r) => [r.binPath, ...rest],
    discover,
    launch,
    isolation: () => 'ava --concurrency=1 --serial: one test file at a time (worker thread or process as configured), tests in sequence',
  }, argv);
}

// -- preload --------------------------------------------------------------------------------------------------------

function avaModule(rel) {
  return require(path.join(process.env.DETJS_AVA_DIR, 'lib', rel));
}

/** List mode: write the files AVA selected, run none. */
function preloadList() {
  const out = process.env.DETJS_LIST_OUT;
  const scheduler = avaModule('scheduler.js').default;
  scheduler.failingTestsFirst = (selected) => {
    try { fs.writeFileSync(out, JSON.stringify({ files: [...selected] })); } catch { /* reported by the main side */ }
    return [];
  };
}

/** AVA's main process: detjs' order and selection; the per-file verdicts for the main side. */
function preloadRunner() {
  process.env.DETJS_RUNNER_ROLE = 'child';
  const files = common.runFiles();
  const rank = new Map(files.map((f, i) => [f.abs, i]));
  const scheduler = avaModule('scheduler.js').default;
  scheduler.failingTestsFirst = (selected) => selected.filter((f) => rank.has(f)).sort((a, b) => rank.get(a) - rank.get(b));
  const RunStatus = avaModule('run-status.js').default;
  const failed = new Set();
  const finished = new Set();
  const real = RunStatus.prototype.emitStateChange;
  RunStatus.prototype.emitStateChange = function emitStateChange(event) {
    try {
      if (event && FAIL_EVENTS.has(event.type)) {
        if (event.testFile) failed.add(event.testFile);
        if (event.pendingTests) for (const f of event.pendingTests.keys()) failed.add(f);
      }
      if (event && event.type === 'worker-finished' && event.testFile) finished.add(event.testFile);
    } catch { /* never break the reporter */ }
    return real.call(this, event);
  };
  process.on('exit', () => {
    try { fs.writeFileSync(process.env.DETJS_AVA_STATUS, JSON.stringify({ failed: [...failed], finished: [...finished] })); } catch { /* main side: all suspect */ }
  });
}

/** A worker thread or worker process: Level 0, capture, test brackets. */
function preloadChild() {
  const wt = require('node:worker_threads');
  const isThread = !wt.isMainThread && wt.workerData && wt.workerData.options && wt.workerData.options.file;
  const isProcess = wt.isMainThread && /[\\/]lib[\\/]worker[\\/]base\.js$/.test(process.argv[1] || '');
  if (!isThread && !isProcess) return;
  const files = common.runFiles();
  const byAbs = new Map(files.map((f) => [f.abs, f]));
  if (isThread && !byAbs.has(wt.workerData.options.file)) return;
  process.env.DETJS_RUNNER_ROLE = 'nested';
  if (process.env.DETJS_NODE_OPTIONS0) process.env.NODE_OPTIONS = process.env.DETJS_NODE_OPTIONS0;
  else delete process.env.NODE_OPTIONS;
  const c = common.child();
  if (!c) return;
  const native = require('../native');
  let file = null;
  let ok = true;
  const open = (abs) => {
    if (file || !byAbs.has(abs)) return file;
    file = new common.ChildFile(byAbs.get(abs).fileId);
    common.onExit(file, () => ok);
    return file;
  };
  if (isThread) open(wt.workerData.options.file);
  const Runner = avaModule('runner.js').default;
  // the Runner learns its file in its constructor (`this.file = options.file`): worker processes get it there
  Object.defineProperty(Runner.prototype, 'file', {
    configurable: true,
    get() { return undefined; },
    set(v) {
      Object.defineProperty(this, 'file', { value: v, writable: true, enumerable: true, configurable: true });
      open(v);
    },
  });
  const realRunTest = Runner.prototype.runTest;
  Runner.prototype.runTest = async function runTest(task, contextRef) {
    if (!file) return realRunTest.call(this, task, contextRef);
    const id = file.id(task.title);
    file.begin(id);
    let r = false;
    try {
      r = await realRunTest.call(this, task, contextRef);
      return r;
    } finally {
      file.end(id, r ? 'passed' : 'failed');
    }
  };
  const realStart = Runner.prototype.start;
  Runner.prototype.start = function start(...a) {
    if (file) {
      this.on('stateChange', ({ data }) => { if (data && FAIL_EVENTS.has(data.type)) ok = false; });
      if (c.controls.has('order') && c.shuffle) {
        for (const k of ['serial', 'concurrent']) {
          const list = this.tasks[k];
          if (!list || list.length < 2) continue;
          const perm = native.shuffleIndices(list.length, c.seed, `${file.fileId}\u0000${k}`);
          const out = perm.map((i) => list[i]);
          list.splice(0, list.length, ...out);
        }
      }
      for (const k of ['serial', 'concurrent']) {
        for (const t of this.tasks[k] || []) if (t.metadata && t.metadata.skipped) file.notRun(file.id(t.title), 'skipped');
      }
      for (const t of this.tasks.todo || []) file.notRun(file.id(t.title), 'todo');
    }
    return realStart.apply(this, a);
  };
  const realSave = Runner.prototype.saveSnapshotState;
  Runner.prototype.saveSnapshotState = async function saveSnapshotState(...a) {
    const r = await realSave.apply(this, a);
    if (file) {
      // a test file that talks to a shared worker (code in AVA's main process) depends on state outside its realm
      const cap = file.cap;
      if (cap && [...cap.nativeLoads].some((f) => /[\\/]ava[\\/]lib[\\/]worker[\\/]plugin\.js$/.test(f))) cap.add(['flag', 'worker', 'AVA shared worker (ava/plugin)'], false);
      file.close(ok);
    }
    return r;
  };
}

function preload(role) {
  if (role === 'list') preloadList();
  else if (role === 'runner') preloadRunner();
  else if (role === 'child') preloadChild();
}

module.exports = { main, preload };
