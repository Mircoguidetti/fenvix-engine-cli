'use strict';
// `detjs node-test`: preloaded (`--require`) in the driver process and, through Node's own propagation of the
// driver's execArgv, in every test file process that `node:test`'s run() starts.
//
// Test file process (NODE_TEST_CONTEXT=child-v8): installs Level 0 and the cache capture before any user module
// (user `--require`/`--import` modules and loaders run after this one), opens the file, and registers on the
// root test of the file, when the file first resolves `node:test`, a beforeEach hook (inherited by every test of
// the file, prepended to the user's hooks) that brackets each test, and an afterEach hook (appended) that marks
// it finished. A test ends when the next one begins or when the process exits (its afterEach hooks, and the
// file's after hooks for the last test, are inside its bracket, as with the Jest shell). The outcome is read from
// the test's own context (`passed`, final once the test's subtests and hooks have run; `t.skip()` -> skipped).
// The file's cache capture is written at process exit; the main process checks it against the run() events.
//
// Driver with `--test-isolation=none` (only without --det-cache): the driver is the single test process; the
// driver attaches the hooks after run() created the root test, and a new trace part starts whenever a test of
// another file begins.
const path = require('node:path');
const { AsyncResource } = require('node:async_hooks');

const env = process.env;
let role = null;
if (env.DETJS === '1' && !env.DETJS_NT_INNER) {
  if (env.NODE_TEST_CONTEXT === 'child-v8' || env.NODE_TEST_CONTEXT === 'child') role = 'file';
  else if (env.DETJS_NT_DRIVER === '1') role = env.DETJS_NT_ISOLATION === 'none' ? 'shared' : 'driver';
}

const KEY = Symbol.for('detjs.nodetest');

if (role === 'file' || role === 'shared') {
  const { FileProcess } = require('../fileproc');
  const root = env.DETJS_ROOT || process.cwd();
  // processes the tests start do not take part (they inherit this environment and, sometimes, the execArgv)
  env.DETJS_NT_INNER = '1';
  if (env.DETJS_NT_NODE_OPTIONS !== undefined) env.NODE_OPTIONS = env.DETJS_NT_NODE_OPTIONS;
  const fp = new FileProcess(root);
  let attached = false;
  let allowAttach = role === 'file';
  let cur = null; // {ctx, name, done}
  const skippedCtx = new WeakSet();

  const outcomeOf = (ctx) => {
    if (skippedCtx.has(ctx)) return 'skipped';
    let passed;
    try { passed = ctx.passed; } catch { passed = false; }
    return passed ? 'passed' : 'failed';
  };
  const endCurrent = () => {
    if (!cur) return;
    const o = outcomeOf(cur.ctx);
    cur = null;
    fp.end(o);
  };
  const begin = (ctx) => {
    let name;
    try { name = String(ctx.fullName); } catch { name = String(ctx.name); }
    // a subtest (t.test) of the running test belongs to it
    if (cur && !cur.done && name.startsWith(`${cur.name} > `)) return;
    endCurrent();
    if (role === 'shared') {
      let f = null;
      try { f = ctx.filePath; } catch { /* older node */ }
      if (f) fp.open(fp.fileIdOf(f));
      if (fp.fileId === null) fp.open('<unknown>');
    }
    const id = fp.idFor(name.split(' > '));
    fp.begin(id);
    cur = { ctx, name, done: false };
    for (const k of ['skip', 'todo']) {
      const realFn = ctx[k];
      if (typeof realFn !== 'function') continue;
      ctx[k] = function detjsSkip(...a) { skippedCtx.add(ctx); return realFn.apply(this, a); };
    }
  };
  const attach = () => {
    if (attached || !allowAttach || !fp.active) return;
    attached = true;
    const nt = require('node:test');
    // a fresh async scope: the hooks go to the root test, whatever test is running when node:test is resolved
    new AsyncResource('detjs').runInAsyncScope(() => {
      nt.beforeEach(function detjsBegin(t) { begin(t); });
      nt.afterEach(function detjsEnd(t) { if (cur && cur.ctx === t) cur.done = true; });
    });
  };
  globalThis[KEY] = {
    role,
    fp,
    attachShared() { allowAttach = true; attach(); },
  };
  const m = require('node:module');
  if (typeof m.registerHooks === 'function') {
    m.registerHooks({
      resolve(spec, context, next) {
        if (spec === 'node:test' && allowAttach && !attached) attach();
        return next(spec, context);
      },
    });
  } else if (role === 'file') {
    attach(); // Node < 22.15: attach now (the file's root test exists from here on)
  }
  if (role === 'file') {
    const file = process.argv[1] ? path.resolve(process.argv[1]) : '<unknown>';
    fp.open(fp.fileIdOf(file));
  }
  process.on('exit', (code) => {
    endCurrent();
    fp.close({ ok: code === 0 && !process.exitCode });
  });
}
