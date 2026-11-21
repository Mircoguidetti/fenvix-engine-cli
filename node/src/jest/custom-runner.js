'use strict';
// A project's own Jest `runner` under --det (audit G-0453, G-0402, G-1588; docs/NODE.md J16).
//
// Jest hands a custom runner (jest-light-runner as used by babel and prettier, create-jest-runner tools such as
// jest-runner-eslint or jest-runner-tsd) whole test files: detjs' `testRunner` (jest-circus wrapper) never sees them.
// Under --det Jest runs with --runInBand, and such runners then work in this process (jest-light-runner: its
// "main_thread" runtime, `maxWorkers === 1`; create-jest-runner: its in-band path). detjs wraps the runner class when
// Jest loads it and brings Level 0 to its files:
//
//   * per file (the runner's onStart / onResult callbacks, or its `test-file-*` events): the process and realm controls
//     (this process's own globals: the runner imports the test file natively here), the file's trace part (module-level
//     seeds), the cache capture's file context;
//   * per test, for runners that register tests with jest-circus's `describe`/`test` but run them themselves
//     (jest-light-runner): a jest-circus event handler on the runner's copy of jest-circus gives each describe block's
//     list of children an iterator that brackets every test while the runner walks the tree (beforeEach, the test,
//     afterEach), numbers ids in declaration order and applies the --det-seed shuffle; the test functions are wrapped
//     (arity kept) to see whether they ran and failed;
//   * a file in which no test was bracketed (a runner that is not a test runner: lint, type checks; a runner that ran
//     the file in another thread or process) is NOT covered: detjs prints it, writes one test per reported result with
//     an `uncontrolled.level0` event whose value differs on every run (`detjs verify` never calls it identical) and the
//     cache never reuses it.
//
// The files of such runners share one process (module cache, globals) one after the other, like Vitest's
// `isolate: false`: for the cache they form one group, reused all together or run all together (src/cache/groups.js).
const Module = require('node:module');
const path = require('node:path');
const controls = require('../controls');
const uncovered = require('../uncovered');

const { STATE } = controls;
const ROOT = () => process.env.DETJS_ROOT || process.cwd();
const MATCHERS = Symbol.for('$$jest-matchers-object');

let runnerPaths = new Map(); // resolved runner module path -> display name
const WRAPPED = new WeakMap();
const CIRCUS = new WeakSet();
let current = null; // the file being run: {fileId, project, label, bracketed, ids, root, test}
const covered = new Map(); // key -> true (some test bracketed) | false
let cap = null;

function capture() {
  if (cap === null) cap = globalThis[Symbol.for('detjs.cache.session')] ? require('../cache/capture').CAPTURE : false;
  return cap || null;
}

function displayName(p) {
  const m = /node_modules[\\/]((?:@[^\\/]+[\\/])?[^\\/]+)/.exec(p);
  return m ? m[1].replace(/\\/g, '/') : path.relative(ROOT(), p);
}

function fileOf(test) {
  const fileId = path.relative(ROOT(), test.path).split(path.sep).join('/');
  const cfg = test.context && test.context.config;
  const project = cfg && cfg.displayName ? cfg.displayName.name : '';
  return { fileId, project, label: project ? `${project}|${fileId}` : fileId, runner: cfg && cfg.runner };
}

// -- per test (jest-circus registration, runner-driven execution) ---------------------------------------------------
function idsOf(rootBlock, fileId) {
  const ids = new Map();
  const flat = [];
  const walk = (block, prefix) => {
    // index loop: the children lists carry detjs' own bracketing iterator (patchChildren)
    const list = block.children || [];
    for (let i = 0; i < list.length; i++) {
      const ch = list[i];
      const id = `${prefix}::${ch.name}`;
      if (ch.type === 'describeBlock') { ids.set(ch, id); walk(ch, id); } else if (ch.type === 'test') flat.push([ch, id]);
    }
  };
  ids.set(rootBlock, fileId);
  walk(rootBlock, fileId);
  const unique = controls.uniqueIds(flat.map(([, id]) => id));
  flat.forEach(([t], i) => ids.set(t, unique[i]));
  return ids;
}

function suppressed() {
  const m = globalThis[MATCHERS];
  return Boolean(m && m.state && Array.isArray(m.state.suppressedErrors) && m.state.suppressedErrors.length);
}

function beginTest(t) {
  const f = current;
  if (!f) return;
  if (!f.ids) f.ids = idsOf(f.root, f.fileId);
  const id = f.ids.get(t) || `${f.fileId}::${t.name}`;
  f.test = { t, id, ran: false, failed: false };
  f.bracketed++;
  STATE.beginTest(id);
  const C = capture();
  if (C) C.setCtx('t');
}

function endTest() {
  const f = current;
  if (!f || !f.test) return;
  const { id, ran, failed } = f.test;
  f.test = null;
  const outcome = !ran ? 'skipped' : failed ? 'failed' : 'passed';
  const fp = STATE.endTest(outcome);
  const C = capture();
  if (C) { C.testEnd(id, outcome, 0, fp); C.setCtx('f'); }
}

/** A function with the same arity that notes, for the running test, that it ran and whether it failed. */
function wrapFn(fn, isTest) {
  if (typeof fn !== 'function' || fn.__detjsCustom) return fn;
  const note = (err) => { if (current && current.test && (err || (isTest && suppressed()))) current.test.failed = true; };
  const w = function detjsTestFn(...a) {
    if (isTest && current && current.test) current.test.ran = true;
    if (fn.length >= 1 && typeof a[0] === 'function') {
      const done = a[0];
      a[0] = function detjsDone(err, ...rest) { note(err); return done.call(this, err, ...rest); };
    }
    let r;
    try { r = fn.apply(this, a); } catch (e) { note(e || true); throw e; }
    if (r && typeof r.then === 'function') return r.then((v) => { note(null); return v; }, (e) => { note(e || true); throw e; });
    if (!(fn.length >= 1)) note(null);
    return r;
  };
  Object.defineProperty(w, 'length', { value: fn.length });
  Object.defineProperty(w, 'name', { value: fn.name });
  Object.defineProperty(w, '__detjsCustom', { value: true });
  return w;
}

/** The children list of a describe block, iterated by the runner: every test is bracketed while the runner runs it. */
function patchChildren(block, rootBlock) {
  const list = block && block.children;
  if (!Array.isArray(list) || Object.prototype.hasOwnProperty.call(list, Symbol.iterator)) return;
  const values = Array.prototype.values;
  Object.defineProperty(list, Symbol.iterator, {
    configurable: true,
    writable: true,
    value: function* detjsChildren() {
      const f = current;
      // jest-circus's own walks of the tree (registration checks) are not the runner running it
      if (!f || f.root !== rootBlock || /[\\/]node_modules[\\/]jest-circus[\\/]/.test(String(new Error().stack))) { yield* values.call(this); return; }
      if (block === rootBlock && !f.ordered) {
        f.ordered = true;
        f.ids = idsOf(rootBlock, f.fileId);
        const c = controls.cfg();
        if (c.controls.has('order') && c.shuffle && rootBlock.children.length) {
          const keyOf = (b) => (b === rootBlock ? f.label : `${f.label}${f.ids.get(b).slice(f.fileId.length)}`);
          const out = controls.shuffleTree(rootBlock.children.slice(), c.seed, f.label, keyOf, (b) => (b.type === 'describeBlock' ? b.children : null));
          rootBlock.children.splice(0, rootBlock.children.length, ...out);
        }
      }
      const items = Array.prototype.slice.call(this);
      for (const ch of items) {
        if (ch && ch.type === 'test') beginTest(ch);
        try {
          yield ch;
        } finally {
          if (ch && ch.type === 'test') endTest();
        }
      }
    },
  });
}

function circusHandler(event, state) {
  if (!state || !state.rootDescribeBlock) return;
  switch (event.name) {
    case 'add_test':
    case 'add_hook':
    case 'start_describe_definition':
    case 'finish_describe_definition': {
      const rootBlock = state.rootDescribeBlock;
      if (current && !current.root) current.root = rootBlock;
      patchChildren(rootBlock, rootBlock);
      patchChildren(state.currentDescribeBlock, rootBlock);
      if (event.name === 'add_test') {
        const block = state.currentDescribeBlock;
        const t = block && block.children[block.children.length - 1];
        if (t && t.type === 'test') t.fn = wrapFn(t.fn, true);
      } else if (event.name === 'add_hook') {
        const block = state.currentDescribeBlock;
        const h = block && block.hooks && block.hooks[block.hooks.length - 1];
        if (h && (h.type === 'beforeEach' || h.type === 'afterEach')) h.fn = wrapFn(h.fn, false);
      }
      break;
    }
    default:
  }
}

/** Add the bracketing handler to the jest-circus copy the runner at `runnerPath` resolves (if it has one). */
function attachCircus(runnerPath) {
  let circus;
  try {
    const req = Module.createRequire(runnerPath);
    circus = req(req.resolve('jest-circus'));
  } catch { return; }
  if (!circus || typeof circus.addEventHandler !== 'function' || CIRCUS.has(circus)) return;
  CIRCUS.add(circus);
  circus.addEventHandler(circusHandler);
}

// -- per file ---------------------------------------------------------------------------------------------------------
function startFile(test, runnerPath) {
  const c = controls.cfg();
  if (!c.active) return;
  const f = fileOf(test);
  if (current) endFile(null);
  controls.installProcess();
  const C = capture();
  if (C) { C.reinstall(); C.resetFile(); C.setCtx('f', f.label); }
  controls.installRealm(globalThis, { sameRealm: true });
  attachCircus(runnerPath);
  controls.openFile(f.fileId, f.project);
  current = { ...f, runnerPath, root: null, ids: null, ordered: false, bracketed: 0, test: null, t0: Date.now() };
}

function endFile(result, failure) {
  const f = current;
  if (!f) return;
  if (f.test) endTest();
  current = null;
  const name = runnerPaths.get(f.runnerPath) || displayName(f.runnerPath || '');
  const C = capture();
  if (!f.bracketed) {
    // nothing bracketed: the runner checked or ran this file out of Level 0's reach
    const what = `custom Jest runner ${name} ran ${f.fileId} out of Level 0's reach (not a test runner detjs can bracket)`;
    uncovered.warnOnce(`custom Jest runner ${name}: its results are NOT covered by Level 0 (no test bracketed; never reused by the cache)`);
    const rows = (result && Array.isArray(result.testResults) && result.testResults.length) ? result.testResults : [null];
    const names = controls.uniqueIds(rows.map((r) => `${f.fileId}::${r ? [...(r.ancestorTitles || []), r.title || r.fullName || '?'].join('::') : name}`));
    rows.forEach((r, i) => {
      STATE.beginTest(names[i]);
      uncovered.mark(what);
      const st = r ? r.status : (failure || (result && (result.numFailingTests > 0 || result.testExecError)) ? 'failed' : 'passed');
      STATE.endTest(st === 'failed' ? 'failed' : st === 'pending' || st === 'skipped' || st === 'disabled' ? 'skipped' : st === 'todo' ? 'todo' : 'passed');
    });
  }
  covered.set(f.label, f.bracketed > 0);
  controls.closeFile();
  const c = controls.cfg();
  if (C && c.dir && f.bracketed) {
    try {
      const ok = Boolean(result) && !failure && !result.testExecError && !(result.numFailingTests > 0);
      const cap2 = C.fileCapture({ fileId: f.fileId, project: f.project, label: f.label, ok, duration: (Date.now() - f.t0) / 1000 });
      controls.writeJson(path.join(c.dir, 'cache', `${controls.partName(f.fileId, f.project).replace(/\.jsonl$/, '')}-${process.pid}.json`), cap2);
    } catch (e) {
      process.stderr.write(`detjs cache: capture of ${f.fileId} not written: ${e && e.stack}\n`);
    }
  }
  if (C) { C.resetFile(); C.setCtx('', ''); }
}

// -- the runner class -------------------------------------------------------------------------------------------------
function wrapRunnerClass(Runner, runnerPath) {
  if (typeof Runner !== 'function' || Runner.__detjsCustomRunner) return Runner;
  if (WRAPPED.has(Runner)) return WRAPPED.get(Runner);
  const Wrapped = class extends Runner {
    async runTests(tests, watcher, onStart, onResult, onFailure, options) {
      if (this.supportsEventEmitters || typeof onStart !== 'function') return super.runTests(tests, watcher, onStart, onResult, onFailure, options);
      const s = async (test) => { startFile(test, runnerPath); return onStart(test); };
      const r = async (test, result) => { if (current) endFile(result, null); return onResult(test, result); };
      const fl = async (test, error) => { if (current) endFile(null, error || true); return onFailure(test, error); };
      try {
        return await super.runTests(tests, watcher, s, r, fl, options);
      } finally {
        if (current) endFile(null, true);
      }
    }

    on(name, listener) {
      if (typeof super.on !== 'function') return undefined;
      let l = listener;
      if (name === 'test-file-start') l = (args) => { startFile(args[0], runnerPath); return listener(args); };
      else if (name === 'test-file-success') l = (args) => { if (current) endFile(args[1], null); return listener(args); };
      else if (name === 'test-file-failure') l = (args) => { if (current) endFile(null, args[1] || true); return listener(args); };
      return super.on(name, l);
    }
  };
  Object.defineProperty(Wrapped, '__detjsCustomRunner', { value: true });
  Object.defineProperty(Wrapped, 'name', { value: Runner.name });
  WRAPPED.set(Runner, Wrapped);
  return Wrapped;
}

function wrapRunnerExports(mod, runnerPath) {
  if (typeof mod === 'function') return wrapRunnerClass(mod, runnerPath);
  if (!mod || typeof mod !== 'object' || WRAPPED.has(mod)) return WRAPPED.get(mod) || mod;
  const d = Object.getOwnPropertyDescriptor(mod, 'default');
  if (!d || !('value' in d) || typeof d.value !== 'function') return mod;
  const descs = Object.getOwnPropertyDescriptors(mod);
  const out = Object.create(Object.getPrototypeOf(mod));
  for (const k of Reflect.ownKeys(descs)) Object.defineProperty(out, k, { ...descs[k], configurable: true });
  Object.defineProperty(out, 'default', { ...d, configurable: true, value: wrapRunnerClass(d.value, runnerPath) });
  WRAPPED.set(mod, out);
  return out;
}

let hooked = false;
/**
 * Wrap the custom runners `paths` (resolved module paths, from --showConfig) when Jest loads them in this process
 * (Module._load: CommonJS, and ES modules loaded with require(esm)). A runner Jest loads with import() instead is not
 * wrapped: its files then get no bracket and are reported as not covered at the end (`report`).
 */
function install(paths) {
  runnerPaths = new Map([...paths].map((p) => [p, displayName(p)]));
  if (hooked || !runnerPaths.size) return;
  hooked = true;
  const realLoad = Module._load;
  Module._load = function _load(request, parent, isMain) {
    const exp = realLoad.call(this, request, parent, isMain);
    if (!runnerPaths.size || typeof request !== 'string') return exp;
    let file;
    try { file = Module._resolveFilename(request, parent, isMain); } catch { return exp; }
    if (!runnerPaths.has(file)) return exp;
    try { return wrapRunnerExports(exp, file); } catch { return exp; }
  };
}

/**
 * After the run: the files of custom runners that detjs never saw start (a runner loaded as native ESM, or one that
 * ran out of process) are named, so that nothing they did is presented as covered.
 */
function report(orderFiles) {
  const out = [];
  for (const f of orderFiles || []) if (f.custom && !covered.has(f.key)) out.push(f.fileId);
  if (out.length) {
    uncovered.warnOnce(`${out.length} file(s) of a custom Jest runner ran without detjs seeing them start: NOT covered by Level 0 and not in the trace (${out.slice(0, 5).join(', ')}${out.length > 5 ? ', ...' : ''})`);
  }
  return out;
}

module.exports = { install, report, wrapRunnerClass, covered };
