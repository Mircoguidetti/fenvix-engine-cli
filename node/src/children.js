'use strict';
// Worker threads, child processes and vm contexts started by the code under test (audit G-0124, G-0125, G-0134,
// G-0152; row JS-09).
//
// * worker_threads: a worker started inside a test gets the Level 0 controls (src/worker-preload.js, through the
//   worker's `execArgv`): its `Math.random`, Web Crypto, clock and timers are seeded / virtual with a key derived
//   from the test id and the worker's index in the test. The interleaving of the threads is not controlled: the test
//   gets one `uncontrolled.thread` event (the verifier never calls such a test identical), and every message the
//   worker posts back and its exit code are recorded (`worker.message`, `worker.exit`: digests).
// * child processes: they run as they are (determinism inside child processes is outside the release scope). The
//   test gets one `uncontrolled.child` event; synchronous calls record the exit status and output digests
//   (`child.result`), asynchronous ones the exit code (`child.exit`), so a different output is a divergence.
// * vm contexts created inside a test (`vm.createContext`, `vm.runInNewContext`, `Script#runInNewContext`) get the
//   realm controls (`Math.random`, `Date`, Web Crypto, the timers they have).
//
// The cache never reuses a test that started a worker or a process (src/cache/capture.js), nor one whose process
// loaded a native addon.
const path = require('node:path');
const { STATE } = require('./state');
const sites = require('./sites');
const native = require('./native');
const { toRealPidArgs } = require('./facts');

const WORKER_PRELOAD = path.join(__dirname, 'worker-preload.js');
let seen = new Set();
let workers = 0;
// per-test state of a concurrent test (src/concur.js)
require('./concur').register({ name: 'children', save: () => [seen, workers], restore: (x) => { [seen, workers] = x; } });

function site() {
  if (!STATE.config || !STATE.config.sites) return '';
  return STATE.quiet(() => sites.resolve());
}

/** One `uncontrolled.<kind>` event per test, at the site of the user code that used the source. */
function mark(kind, value, at) {
  if (STATE.testId === null || seen.has(kind)) return;
  seen.add(kind);
  STATE.recordAt('other', `uncontrolled.${kind}`, at, value);
}

function digestOf(v) {
  if (v === undefined || v === null) return '-';
  try {
    if (Buffer.isBuffer(v)) return native.digest(v).slice(0, 16);
    if (ArrayBuffer.isView(v)) return native.digest(Buffer.from(v.buffer, v.byteOffset, v.byteLength)).slice(0, 16);
    return native.digest(Buffer.from(typeof v === 'string' ? v : require('node:v8').serialize(v))).slice(0, 16);
  } catch {
    return native.digest(Buffer.from(String(v))).slice(0, 16);
  }
}

function argvOf(file, args) {
  return [String(file), ...(Array.isArray(args) ? args.map(String) : [])].join(' ').slice(0, 200);
}

function installWorkers(patcher) {
  const wt = require('node:worker_threads');
  const Real = wt.Worker;
  if (!Real || Real.__detjsLevel0) return;
  const W = new Proxy(Real, {
    construct(target, args, nt) {
      require('./outside').noteChild(); // P1 B2: a worker can write into this process's directories
      const at = STATE.testId !== null ? site() : null;
      if (at === null) return Reflect.construct(target, args, nt === W ? target : nt);
      const [file, opts0] = args;
      const opts = opts0 && typeof opts0 === 'object' ? opts0 : {};
      const key = `${STATE.testId}\u001fworker${workers++}`; // an environment value: no NUL byte (a NUL made every Worker constructor throw)
      const vpid = require('./facts').currentVpid(); // P1 C: the worker sees the test's pid (same process)
      const env = opts.env === wt.SHARE_ENV ? opts.env : { ...(opts.env || process.env), DETJS_WORKER_KEY: key, ...(vpid !== null ? { DETJS_WORKER_VPID: String(vpid) } : {}) };
      const withPreload = { ...opts, env, execArgv: [...(opts.execArgv !== undefined ? opts.execArgv : process.execArgv), '--require', WORKER_PRELOAD] };
      let w;
      try {
        w = Reflect.construct(target, [file, withPreload], nt === W ? target : nt);
      } catch (e) {
        if (!e || e.code !== 'ERR_WORKER_INVALID_EXEC_ARGV') throw e;
        // a parent option a worker does not accept: the worker runs without the controls (marked below)
        w = Reflect.construct(target, [file, { ...opts, env }], nt === W ? target : nt);
        STATE.recordAt('other', 'worker.uncontrolled', at, 'execArgv not accepted');
      }
      mark('thread', `worker ${String(file && file.href ? file.href : file).slice(0, 200)}`, at);
      const test = STATE.testId;
      w.on('message', (m) => { if (STATE.testId === test) STATE.recordAt('other', 'worker.message', at, digestOf(m)); });
      w.on('exit', (code) => { if (STATE.testId === test) STATE.recordAt('other', 'worker.exit', at, String(code)); });
      return w;
    },
    get(t, k, r) { return k === '__detjsLevel0' ? true : Reflect.get(t, k, r); },
  });
  patcher.set(wt, 'Worker', W);
}

function installChildren(patcher) {
  const cp = require('node:child_process');
  if (cp.__detjsLevel0) return;
  Object.defineProperty(cp, '__detjsLevel0', { value: true });
  for (const n of ['spawn', 'exec', 'execFile', 'fork']) {
    const real = cp[n];
    if (typeof real !== 'function') continue;
    const w = function (...a) {
      const at = STATE.testId !== null ? site() : null;
      require('./outside').noteChild(); // P1 B2: a child can write into this process's directories
      // a virtual pid in the command, its arguments or environment is the real one for the child (P1 C)
      const child = real.apply(this, toRealPidArgs(a));
      if (at !== null) {
        mark('child', `${n} ${argvOf(a[0], a[1])}`, at);
        const test = STATE.testId;
        if (child && typeof child.on === 'function') {
          child.on('exit', (code, signal) => { if (STATE.testId === test) STATE.recordAt('other', 'child.exit', at, `${code}|${signal || ''}`); });
        }
      }
      return child;
    };
    copyProps(real, w);
    patcher.set(cp, n, w);
  }
  for (const n of ['spawnSync', 'execSync', 'execFileSync']) {
    const real = cp[n];
    if (typeof real !== 'function') continue;
    const w = function (...a) {
      const at = STATE.testId !== null ? site() : null;
      require('./outside').noteChild(); // P1 B2
      a = toRealPidArgs(a); // P1 C: as for the asynchronous forms
      if (at === null) return real.apply(this, a);
      mark('child', `${n} ${argvOf(a[0], Array.isArray(a[1]) ? a[1] : [])}`, at);
      let r;
      try {
        r = real.apply(this, a);
      } catch (e) {
        STATE.recordAt('other', 'child.result', at, `${e && e.status}|${digestOf(e && e.stdout)}|${digestOf(e && e.stderr)}`);
        throw e;
      }
      const obj = r && typeof r === 'object' && !Buffer.isBuffer(r) && 'status' in r;
      STATE.recordAt('other', 'child.result', at, obj ? `${r.status}|${digestOf(r.stdout)}|${digestOf(r.stderr)}` : `0|${digestOf(r)}|-`);
      return r;
    };
    copyProps(real, w);
    patcher.set(cp, n, w);
  }
}

function copyProps(real, w) {
  for (const k of Reflect.ownKeys(real)) {
    if (['length', 'name', 'prototype', 'arguments', 'caller'].includes(k)) continue;
    try { Object.defineProperty(w, k, Object.getOwnPropertyDescriptor(real, k)); } catch { /* ignore */ }
  }
  try { Object.defineProperty(w, 'name', { value: real.name }); } catch { /* ignore */ }
}

function installVm(patcher, installRealm) {
  const vm = require('node:vm');
  if (vm.__detjsLevel0) return;
  Object.defineProperty(vm, '__detjsLevel0', { value: true });
  const realCreate = vm.createContext;
  const realRunIn = vm.runInContext;
  const control = (ctx) => {
    if (STATE.testId === null || site() === null) return;
    try {
      if (vm.constants && ctx === vm.constants.DONT_CONTEXTIFY) return;
      installRealm(realRunIn.call(vm, 'globalThis', ctx));
    } catch { /* a context that cannot be entered keeps its globals */ }
  };
  const createContext = function createContext(obj, opts) {
    const ctx = realCreate.call(vm, obj, opts);
    control(ctx);
    return ctx;
  };
  const ctxOpts = (o) => {
    if (!o || typeof o !== 'object') return undefined;
    const c = {};
    if (o.contextName !== undefined) c.name = o.contextName;
    if (o.contextOrigin !== undefined) c.origin = o.contextOrigin;
    if (o.contextCodeGeneration !== undefined) c.codeGeneration = o.contextCodeGeneration;
    if (o.microtaskMode !== undefined) c.microtaskMode = o.microtaskMode;
    return c;
  };
  const realRunInNew = vm.runInNewContext;
  const runInNewContext = function runInNewContext(code, sandbox, opts) {
    if (STATE.testId === null) return realRunInNew.call(vm, code, sandbox, opts);
    const ctx = createContext(sandbox === undefined ? {} : sandbox, ctxOpts(opts));
    return realRunIn.call(vm, code, ctx, typeof opts === 'string' ? opts : opts);
  };
  patcher.set(vm, 'createContext', createContext);
  patcher.set(vm, 'runInNewContext', runInNewContext);
  const P = vm.Script.prototype;
  const realScriptNew = P.runInNewContext;
  patcher.set(P, 'runInNewContext', function (sandbox, opts) {
    if (STATE.testId === null) return realScriptNew.call(this, sandbox, opts);
    const ctx = createContext(sandbox === undefined ? {} : sandbox, ctxOpts(opts));
    return this.runInContext(ctx, opts);
  });
}

function installProcess(patcher, installRealm) {
  if (!STATE.__childrenHooked) {
    STATE.__childrenHooked = true;
    STATE.onTestStart.push(() => { seen = new Set(); workers = 0; });
  }
  installWorkers(patcher);
  installChildren(patcher);
  installVm(patcher, installRealm);
}

module.exports = { installProcess, mark };
