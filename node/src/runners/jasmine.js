'use strict';
// `detjs jasmine [--det ...] [jasmine args]` (the `jasmine` package for Node, 4+; built against jasmine 7).
//
// Jasmine runs every spec file in one process. detjs:
//   * discovery: Jasmine itself in list mode (the preload replaces `execute`: the configuration file, helpers,
//     requires and spec files as Jasmine resolved them, and the configuration object); the configuration digest is
//     that configuration, the configuration file by content, and the command-line options;
//   * --det: one process, the spec files in detjs' order (sorted by path; --det-seed: shared shuffle), `random:
//     false` (Jasmine's default `random: true` draws a seed per run); with --det-seed the children of every suite
//     are shuffled with the shared shuffle (keys file -> suite path), through Jasmine's `orderChildren` hook;
//   * --det-cache: every spec file in its own fresh process (helpers, requires and globalSetup run in each), because
//     in one process a reused file A would change the context file B runs in (docs/ALL-RUNNERS.md);
//   * every spec is a test: Jasmine's reporter events (specStarted: before its beforeEach functions; specDone:
//     after its afterEach functions); a failure outside specs (beforeAll / afterAll, load errors) fails the file.
// Not supported under --det: `--parallel` (removed, noted).
const fs = require('node:fs');
const path = require('node:path');
const common = require('./common');

const VOLATILE_ENV = new Set(['random', 'seed']);

function findRunner(root) {
  const p = common.findPackage(root, 'jasmine');
  const coreDir = common.pkgDir(p.dir, 'jasmine-core');
  return { ...p, binPath: p.bin('jasmine'), coreDir };
}

/** The user's options (positionals are spec files: detjs passes its own list); --parallel and --random removed. */
function userOptions(rest, notes) {
  const out = [];
  for (const a of rest) {
    // positionals are spec files (detjs passes its own list); `NAME=value` arguments are Jasmine's environment-style
    // options (`JASMINE_CONFIG_PATH=tests/jasmine.json`) and stay
    if (!a.startsWith('-') && !/^[A-Z_][A-Z0-9_]*=/.test(a)) continue;
    if (/^--parallel=/.test(a)) { if (notes) notes.push(`${a} ignored: one process per file under --det-cache, serial under --det`); continue; }
    if (/^--(random|seed)=/.test(a)) continue;
    out.push(a);
  }
  return out;
}

async function discover(ctx) {
  const { runner, rest } = ctx;
  const notes = [];
  const l = common.listChild(ctx, [runner.binPath, ...rest.filter((a) => !/^--parallel=/.test(a))], { DETJS_JASMINE_DIR: runner.dir });
  const doc = l.doc || {};
  if (!l.doc) notes.push(`jasmine list failed (status ${l.status}): ${(l.stderr || l.stdout).slice(-800)}`);
  const files = (doc.specFiles || []).map((f) => path.resolve(ctx.root, f));
  const { stable } = require('../cache/proof');
  const env = { ...((doc.config && doc.config.env) || {}) };
  for (const k of VOLATILE_ENV) delete env[k];
  const config = {
    jasmine: l.doc ? stable({ ...(doc.config || {}), env, random: undefined, seed: undefined, reporters: undefined }) : `unknown ${Date.now()}`,
    jasmineConfigFile: common.fileParts(ctx.root, doc.configFile ? [doc.configFile]
      : ['spec/support/jasmine.mjs', 'spec/support/jasmine.json', 'spec/support/jasmine.js'].filter((f) => fs.existsSync(path.join(ctx.root, f)))),
    helpers: (doc.helperFiles || []).map((f) => common.fileIdOf(ctx.root, path.resolve(ctx.root, f))),
    requires: doc.requires || [],
    args: userOptions(rest).sort(),
    mode: ctx.pc ? 'process per file' : 'one process',
  };
  userOptions(rest, notes);
  return { files, config, uncacheable: null, notes, order: 'path' };
}

function launch(ctx, files) {
  const { runner, rest } = ctx;
  const opts = [...userOptions(rest), '--random=false'];
  const env = { DETJS_JASMINE_DIR: runner.dir, DETJS_JASMINE_CORE: runner.coreDir };
  if (!ctx.pc) return common.runChild(ctx, [runner.binPath, ...opts, ...files], { role: 'single', env });
  // --det-cache: a fresh process per spec file
  let status = 0;
  for (const f of files) {
    const s = common.runChild(ctx, [runner.binPath, ...opts, f], { role: 'single', env: { ...env, DETJS_RUNNER_FILE: f } });
    if (s !== 0) status = s;
  }
  return status;
}

function main(argv) {
  return common.runShell({
    name: 'jasmine',
    findRunner,
    plain: (rest, r) => [r.binPath, ...rest],
    discover,
    launch,
    isolation: (ctx) => (ctx.pc ? 'jasmine: one process per spec file (--det-cache), specs in sequence' : 'jasmine: one process, spec files in sequence, random=false'),
  }, argv);
}

// -- preload --------------------------------------------------------------------------------------------------------

function jasmineClass() {
  return require(path.join(process.env.DETJS_JASMINE_DIR, 'lib', 'jasmine.js'));
}

/** List mode: what Jasmine would load and run, then exit without running. */
function preloadList() {
  const out = process.env.DETJS_LIST_OUT;
  const RunnerBase = require(path.join(process.env.DETJS_JASMINE_DIR, 'lib', 'runner_base.js'));
  const doc = {};
  const realLoadConfig = RunnerBase.prototype.loadConfig;
  RunnerBase.prototype.loadConfig = function loadConfig(config) {
    try { doc.config = JSON.parse(JSON.stringify(config, (k, v) => (typeof v === 'function' ? `fn:${String(v)}` : v))); } catch { doc.config = null; }
    return realLoadConfig.call(this, config);
  };
  const realLoadSpecific = RunnerBase.prototype.loadSpecificConfigFile_;
  if (typeof realLoadSpecific === 'function') {
    RunnerBase.prototype.loadSpecificConfigFile_ = function loadSpecificConfigFile_(file, ...a) {
      doc.configFile = path.resolve(this.projectBaseDir || process.cwd(), file);
      return realLoadSpecific.call(this, file, ...a);
    };
  }
  const Jasmine = jasmineClass();
  Jasmine.prototype.execute = async function execute(files) {
    if (files && files.length) {
      this.specDir = '';
      this.specFiles = [];
      this.addMatchingSpecFiles(files);
    }
    doc.specFiles = this.specFiles;
    doc.helperFiles = this.helperFiles;
    doc.requires = this.requires;
    fs.writeFileSync(out, JSON.stringify(doc));
    process.exit(0);
  };
}

const ORDER_KEY = Symbol.for('detjs.jasmine.orderChildren');
const ORDER_SRC = 'return order.sort(node.children);';

/** Jasmine's ordering step, made visible: `orderChildren(node)` of the execution tree (jasmine-core source hook). */
function hookOrder() {
  const m = require('node:module');
  const core = path.join(process.env.DETJS_JASMINE_CORE || '', 'lib', 'jasmine-core', 'jasmine.js');
  if (typeof m.registerHooks !== 'function') return false;
  let found = false;
  m.registerHooks({
    load(u, context, next) {
      const r = next(u, context);
      if (typeof u === 'string' && u.startsWith('file:') && require('node:url').fileURLToPath(u) === core && r && r.source) {
        const src = String(r.source);
        if (src.includes(ORDER_SRC)) {
          found = true;
          return { ...r, source: src.replace(ORDER_SRC, `return (globalThis[Symbol.for('detjs.jasmine.orderChildren')] || ((n, s) => s(n.children)))(node, (c) => order.sort(c));`) };
        }
      }
      return r;
    },
  });
  return () => found;
}

/** The spec process ('single'): Level 0, capture, specs as tests. */
function preloadSingle() {
  process.env.DETJS_RUNNER_ROLE = 'nested';
  if (process.env.DETJS_NODE_OPTIONS0) process.env.NODE_OPTIONS = process.env.DETJS_NODE_OPTIONS0;
  else delete process.env.NODE_OPTIONS;
  const c = common.child();
  if (!c) return;
  const native = require('../native');
  const files = common.runFiles();
  const byAbs = new Map(files.map((f) => [f.abs, f]));
  const single = process.env.DETJS_RUNNER_FILE ? byAbs.get(process.env.DETJS_RUNNER_FILE) : null;
  const orderFound = hookOrder();
  let file = null;
  let ok = true;
  let sawDone = false;
  const open = (abs) => {
    const f = abs && byAbs.get(path.resolve(abs));
    if (!f) return file;
    if (file && file.fileId === f.fileId) return file;
    if (file) file.close(ok);
    ok = true;
    file = new common.ChildFile(f.fileId);
    return file;
  };
  if (single) {
    open(single.abs);
    common.onExit(file, () => ok && sawDone);
  } else {
    process.on('exit', (code) => { if (file) { if (code || !sawDone) file.fail(); else file.close(ok); } });
  }
  const fileOfNode = (node) => {
    for (let n = node; n; n = n.parentSuite) if (n.filename) return n.filename;
    return null;
  };
  // seeded order: shared shuffle of every suite's children (top suite: keep the files' order, shuffle inside)
  globalThis[ORDER_KEY] = (node, jasmineSort) => {
    const kids = node.children || [];
    if (!(c.controls.has('order') && c.shuffle) || kids.length < 2) return jasmineSort(kids);
    const keyOf = (n) => {
      const parts = [];
      for (let x = n; x && x.parentSuite; x = x.parentSuite) parts.unshift(x.description);
      const fname = fileOfNode(n);
      const fid = fname && byAbs.get(path.resolve(fname)) ? byAbs.get(path.resolve(fname)).fileId : '';
      return [fid, ...parts].join('::');
    };
    const shuffle = (list, key) => native.shuffleIndices(list.length, c.seed, key).map((i) => list[i]);
    if (node.parentSuite) return shuffle(kids, keyOf(node));
    // top suite: group by file (in load order), shuffle each group
    const groups = new Map();
    for (const k of kids) {
      const f = fileOfNode(k) || '';
      if (!groups.has(f)) groups.set(f, []);
      groups.get(f).push(k);
    }
    const out = [];
    for (const [f, list] of groups) {
      const fid = byAbs.get(path.resolve(f || '.')) ? byAbs.get(path.resolve(f)).fileId : f;
      out.push(...shuffle(list, fid));
    }
    return out;
  };
  // the spec files of this process are detjs' list (execute(files) replaces the configured ones), and the helper
  // files the configuration's globs match are part of the configuration digest (main side, from the listing): the
  // globs Jasmine expands here are discovery, not inputs of the specs (glob's path-scurry copies every Stats field,
  // times included, which would make every spec uncacheable). The helpers themselves are loaded modules: inputs.
  const RunnerBase = require(path.join(process.env.DETJS_JASMINE_DIR, 'lib', 'runner_base.js'));
  for (const n of ['addMatchingSpecFiles', 'addMatchingHelperFiles']) {
    const real = RunnerBase.prototype[n];
    if (typeof real !== 'function') continue;
    RunnerBase.prototype[n] = function addMatching(...a) {
      return common.quiet(() => real.apply(this, a));
    };
  }
  const Jasmine = jasmineClass();
  const realExecute = Jasmine.prototype.execute;
  Jasmine.prototype.execute = async function execute(...a) {
    if (c.controls.has('order')) this.env.configure({ random: false });
    let cur = null;
    const reporter = {
      jasmineStarted() {
        if (c.controls.has('order') && c.shuffle && !orderFound()) {
          require('../state').STATE.notes.push('jasmine: orderChildren hook not found in jasmine-core: specs keep declaration order with --det-seed');
        }
      },
      specStarted(r) {
        const f = open(r.filename) || file;
        if (!f) return;
        cur = { id: f.id(r.fullName), f };
        f.begin(cur.id);
      },
      specDone(r) {
        const f = cur ? cur.f : file;
        if (!f) return;
        const outcome = r.status === 'passed' ? 'passed' : r.status === 'failed' ? 'failed' : r.status === 'pending' ? 'skipped' : 'skipped';
        if (cur) f.end(cur.id, outcome, typeof r.duration === 'number' ? r.duration / 1000 : undefined);
        else f.notRun(f.id(r.fullName), outcome);
        if (outcome === 'failed') ok = false;
        cur = null;
      },
      suiteDone(r) {
        if (r.status === 'failed' || (r.failedExpectations && r.failedExpectations.length)) ok = false;
      },
      jasmineDone(r) {
        sawDone = true;
        if (!r || r.overallStatus !== 'passed' || (r.failedExpectations && r.failedExpectations.length)) ok = false;
        if (file && single) file.close(ok);
      },
    };
    // helpers often replace the reporters (`jasmine.getEnv().clearReporters()` + a spec reporter): detjs' reporter is
    // added once the helpers are loaded (Jasmine loads the spec files right after); a file whose run detjs' reporter
    // did not see end (removed by a spec file) is never recorded as a pass (see jasmineDone)
    const env = this.env;
    const realLoadSpecs = this.loadSpecs;
    if (typeof realLoadSpecs === 'function') {
      this.loadSpecs = async function loadSpecs(...x) {
        env.addReporter(reporter);
        return realLoadSpecs.apply(this, x);
      };
    } else {
      env.addReporter(reporter);
    }
    return realExecute.apply(this, a);
  };
}

function preload(role) {
  if (role === 'list') preloadList();
  else if (role === 'single') preloadSingle();
}

module.exports = { main, preload };
