'use strict';
// Jest test environments under --det (audit G-1312, G-1436, G-1466, G-2164; cache: review r021b).
//
// Jest builds a test file's environment, then runs the project's `setupFiles` in it, and only then calls the test
// runner (`testRunner`, where detjs used to install the controls). Every test environment class is wrapped here so
// that its constructor, right after the environment's own, installs the Level 0 controls into the environment's
// global object, re-creates Jest's fake timers on top of them, opens the file's trace part (module-level seeds) and
// starts the file for the cache capture: `setupFiles` then run with the virtual clock, the seeded generators and the
// closed network, and what they read is recorded like the test file's own module-level code.
//
// Which classes: the environments `--showConfig` names (wrapped in the module cache before Jest loads them), and any
// other module Jest (or a custom environment) loads in this process whose export looks like a Jest environment
// (`prototype.getVmContext` and `setup`): a `@jest-environment` docblock, a custom environment extending
// jest-environment-node. Nested wrappers (a wrapped custom environment extending a wrapped base) act once, in the
// outermost constructor. An environment Jest loads as native ESM is not seen here: the test runner installs the
// controls then (after setupFiles, as before) and says so.
//
// Test code's view of the process (G-2164): Jest under --det runs in band in the detjs process, so the file's
// `process.argv` is set to what `jest <args>` in band shows (`[node, <jest bin>, ...args]`), not detjs' command line.
const Module = require('node:module');
const path = require('node:path');

const ROOT = () => process.env.DETJS_ROOT || process.cwd();
let opts = { cache: false, argv: null };
let depth = 0;
const WRAPPED = new WeakMap(); // original class or exports object -> wrapped
const MARK = Symbol.for('detjs.jest.environment');

function looksLikeEnv(C) {
  return typeof C === 'function' && C.prototype && typeof C.prototype.getVmContext === 'function'
    && typeof C.prototype.setup === 'function' && typeof C.prototype.teardown === 'function';
}

function fileOf(config, context) {
  const testPath = context && context.testPath;
  if (!testPath) return null;
  const fileId = path.relative(ROOT(), testPath).split(path.sep).join('/');
  const pc = config && config.projectConfig;
  const project = pc && pc.displayName ? pc.displayName.name : '';
  return { fileId, project, label: project ? `${project}|${fileId}` : fileId };
}

function before(f) {
  if (!opts.cache || !f) return;
  const { CAPTURE } = require('../cache/capture');
  CAPTURE.resetFile();
  CAPTURE.setCtx('f', f.label);
}

function after(env, config, f) {
  const g = env.global;
  const controls = require('../controls');
  const c = controls.cfg();
  let CAP = null;
  if (opts.cache) {
    const cap = require('../cache/capture');
    CAP = cap.CAPTURE;
    if (g && g.process) cap.installEnv(CAP, g.process);
    // the test file's realm has its own Object / Reflect: descriptor reads of recording Stats objects (G1)
    if (g && g !== globalThis) cap.installReflection(CAP, g);
  }
  if (!c.active || !g || !f) return;
  // the in-band process's own command line is detjs'; a plain in-band Jest shows its own bin and arguments
  if (opts.argv && g.process && g.process !== process) {
    try { g.process.argv = opts.argv.slice(); } catch { /* keep */ }
  }
  controls.installProcess();
  if (CAP) CAP.reinstall();
  controls.installRealm(g, { sameRealm: g === globalThis });
  const pc = config && config.projectConfig;
  recreateFakeTimers(env, pc, c);
  controls.openFile(f.fileId, f.project);
  Object.defineProperty(env, MARK, { value: f.fileId, configurable: true });
}

/**
 * Jest's fake timers capture the realm's timers when the environment is built: re-created on top of the virtual ones,
 * so that `useRealTimers()` restores them (modern and legacy). The modern clock starts at the virtual epoch.
 */
function recreateFakeTimers(env, config, c) {
  const g = env.global;
  if (env.fakeTimersModern) {
    try {
      env.fakeTimersModern = new env.fakeTimersModern.constructor({ config, global: g });
    } catch { /* keep Jest's instance */ }
    if (c.controls.has('time')) require('./runner').virtualFakeClock(env.fakeTimersModern, config);
  }
  const legacy = env.fakeTimers;
  if (legacy && typeof legacy.constructor === 'function' && legacy._timerConfig) {
    try {
      env.fakeTimers = new legacy.constructor({
        config: legacy._config || config, global: g, moduleMocker: legacy._moduleMocker, timerConfig: legacy._timerConfig, maxLoops: legacy._maxLoops,
      });
    } catch { /* keep Jest's instance: its useRealTimers() then restores the realm's original timers */ }
  }
  // whichever instance is kept restores the virtual timers (G-1468)
  if (c.controls.has('timers')) require('../realmx').virtualLegacyTimers(env.fakeTimers, g);
}

function wrapClass(Env) {
  if (!looksLikeEnv(Env) || Env.__detjsEnv) return Env;
  if (WRAPPED.has(Env)) return WRAPPED.get(Env);
  const Wrapped = class extends Env {
    constructor(config, context) {
      const outer = depth === 0;
      const f = outer ? fileOf(config, context) : null;
      if (outer) before(f);
      depth++;
      try {
        super(config, context);
      } finally {
        depth--;
      }
      if (outer) after(this, config, f);
    }
  };
  Object.defineProperty(Wrapped, '__detjsEnv', { value: true });
  Object.defineProperty(Wrapped, '__detjsCache', { value: true }); // the cache's former marker
  Object.defineProperty(Wrapped, 'name', { value: Env.name });
  WRAPPED.set(Env, Wrapped);
  return Wrapped;
}

/** The exports of a module with every environment class in it wrapped (the same object when there is none). */
function wrapExports(mod) {
  if (mod === null || mod === undefined) return mod;
  if (typeof mod === 'function') return wrapClass(mod);
  if (typeof mod !== 'object') return mod;
  if (WRAPPED.has(mod)) return WRAPPED.get(mod);
  // data properties only: an accessor (a lazy re-export) is never evaluated here
  const descs = Object.getOwnPropertyDescriptors(mod);
  const keys = Object.keys(descs).filter((k) => descs[k].enumerable && 'value' in descs[k] && looksLikeEnv(descs[k].value) && !descs[k].value.__detjsEnv);
  if (!keys.length) return mod;
  const out = Object.create(Object.getPrototypeOf(mod));
  for (const k of Reflect.ownKeys(descs)) Object.defineProperty(out, k, { ...descs[k], configurable: true });
  for (const k of keys) Object.defineProperty(out, k, { ...descs[k], value: wrapClass(descs[k].value) });
  WRAPPED.set(mod, out);
  return out;
}

let hooked = false;
/**
 * Wrap the environments of the run (call before Jest starts). `shown`: `--showConfig` output; `o.cache`: the cache
 * capture is on; `o.argv`: the `process.argv` test code sees.
 */
function install(shown, o = {}) {
  opts = { ...opts, ...o };
  for (const c of (shown && shown.configs) || []) {
    const file = c.testEnvironment;
    if (!file || !path.isAbsolute(file)) continue;
    let mod;
    try { mod = require(file); } catch { continue; }
    const resolved = require.resolve(file);
    if (require.cache[resolved]) require.cache[resolved].exports = wrapExports(mod);
  }
  if (hooked) return;
  hooked = true;
  const realLoad = Module._load;
  Module._load = function _load(request, parent, isMain) {
    const exp = realLoad.call(this, request, parent, isMain);
    try { return wrapExports(exp); } catch { return exp; }
  };
}

/** Whether the wrapper already opened `fileId` for this environment (the test runner then does not reopen it). */
function opened(environment, fileId) {
  return Boolean(environment) && environment[MARK] === fileId;
}

module.exports = { install, opened, wrapExports, looksLikeEnv };
