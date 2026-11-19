'use strict';
// Preload of every `bun test` process that `detjs bun-test --det` starts (one test file per process; the main side
// is src/runners/bun.js). Loaded first (detjs replaces bunfig's preloads by its own `--config` and passes them after
// this one), before any module of the project:
//
// 1. Level 0: the shared controls (seeds, clock, timers, fs order, closed network) and Bun's own APIs
//    (bun-runtime.js installLevel0);
// 2. --det-cache: the shared capture (cache/capture.js) and Bun's own APIs and module loader (installCapture);
// 3. the bracket of every test: bun:test's registration functions (test/it/describe and their modifiers, also
//    the globals) are wrapped so that each test body runs between begin and end of its id
//    (`<file>::<describe>::<name>`, `#n` for duplicates, `[k]` for the k-th row of `.each`);
// 4. a global afterAll (registered here, so it runs after the file's own afterAll hooks) closes the file: trace part
//    and capture written. The process exit status decides whether the file passed (src/runners/common.js).
const path = require('node:path');
const controls = require('../controls');

const c = controls.cfg();
const fileId = process.env.DETJS_FILE;
if (c.active && fileId) {
  const notes = [];
  controls.installProcess();
  controls.installRealm(globalThis, { sameRealm: true });
  const runtime = require('./bun-runtime');
  runtime.installLevel0(c, notes);
  let cap = null;
  if (process.env.DETJS_CACHE === '1') {
    cap = require('../cache/capture').CAPTURE;
    cap.install({ role: 'worker', root: c.root, mainAnyReads: false });
  }
  const { Bracket } = require('./bracket');
  const bracket = new Bracket(fileId, cap);
  bracket.doneStyle = true;
  bracket.runtimeName = `bun ${Bun.version}`;
  // DETJS_RUNTIME_NAIVE=1 (tests only): the shared Node capture alone, to measure what Bun's own capture adds
  if (cap && process.env.DETJS_RUNTIME_NAIVE !== '1') {
    runtime.installCapture(cap, bracket, notes);
    // toMatchSnapshot reads the file's snapshot file natively
    cap.read(runtime.snapshotPath(path.resolve(c.root, fileId)), 'f');
    for (const n of notes) cap.notes.add(n);
  }
  for (const n of notes) controls.STATE.notes.push(n);
  installTimersBridge();
  installRegistrars(bracket);
}

/**
 * bun:test's fake timers (jest/vi.useFakeTimers) and setSystemTime work on Bun's native timers and Date: while they
 * are on, the native functions are put back (the test asked for its own clock); useRealTimers restores Level 0's.
 */
function installTimersBridge() {
  const bt = require('bun:test');
  const clock = require('../clock');
  const names = ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'setImmediate'];
  const ours = {};
  for (const n of names) ours[n] = globalThis[n];
  const oursDate = globalThis.Date;
  const toNative = () => { for (const n of names) globalThis[n] = clock.REAL[n]; };
  const toOurs = () => { for (const n of names) globalThis[n] = ours[n]; globalThis.Date = oursDate; };
  for (const holder of [bt.jest, bt.vi].filter(Boolean)) {
    for (const [k, f] of [['useFakeTimers', toNative], ['useRealTimers', toOurs]]) {
      const real = holder[k];
      if (typeof real !== 'function') continue;
      holder[k] = function (...a) {
        if (k === 'useFakeTimers') { f(); globalThis.Date = oursDate.__detjsReal || globalThis.Date; }
        const r = real.apply(this, a);
        if (k === 'useRealTimers') f();
        return r;
      };
    }
  }
  if (typeof bt.setSystemTime === 'function') {
    const real = bt.setSystemTime;
    bt.setSystemTime = function setSystemTime(t) {
      // a pinned system time: Bun's native Date serves it; no argument (or null) resets to Level 0's clock
      if (t === undefined || t === null) globalThis.Date = oursDate;
      else globalThis.Date = oursDate.__detjsReal || globalThis.Date;
      return real.apply(this, arguments);
    };
  }
}

const REGISTRAR_KEYS = new Set(['skip', 'only', 'todo', 'failing', 'concurrent', 'serial', 'if', 'skipIf', 'todoIf', 'failingIf',
  'each', 'concurrentIf', 'serialIf']);

function installRegistrars(bracket) {
  const bt = require('bun:test');
  let prefix = []; // describe names of the block whose callback is running
  const targets = new WeakMap(); // our proxies -> what they wrap (Bun checks `this` of .each/.if/...)
  const unwrap = (x) => (x && targets.has(x) ? targets.get(x) : x);
  const mk = (real, handler) => { const p = new Proxy(real, handler); targets.set(p, real); return p; };
  const wrapTest = (real, each) => mk(real, {
    apply(t, self, args) {
      self = unwrap(self);
      if (typeof args[0] === 'string' || (args[0] && typeof args[0] === 'object' && typeof args[0].name === 'string')) {
        const name = typeof args[0] === 'string' ? args[0] : args[0].name;
        const fi = args.findIndex((x, i) => i > 0 && typeof x === 'function');
        if (fi > 0) {
          const id = bracket.register([...prefix, name]);
          const fn = args[fi];
          if (each) {
            let k = 0;
            const run = function (...a) { k++; return bracket.wrap(k === 1 ? id : `${id} [${k}]`, fn).apply(this, a); };
            Object.defineProperty(run, 'length', { value: fn.length });
            args = [...args];
            args[fi] = run;
          } else {
            args = [...args];
            args[fi] = bracket.wrap(id, fn);
          }
        }
        return Reflect.apply(t, self, args);
      }
      const r = Reflect.apply(t, self, args); // .each(table), .if(cond), ...: a registrar
      return typeof r === 'function' ? wrapTest(r, each || t.__detjsEach) : r;
    },
    get(t, k) {
      const v = Reflect.get(t, k, t);
      if (typeof v === 'function' && typeof k === 'string' && REGISTRAR_KEYS.has(k)) return wrapTest(v, each || k === 'each');
      return v;
    },
  });
  const wrapDescribe = (real) => mk(real, {
    apply(t, self, args) {
      self = unwrap(self);
      const name = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].name) || String(args[0]);
      const fi = args.findIndex((x, i) => i > 0 && typeof x === 'function');
      if (fi > 0) {
        const at = prefix;
        const fn = args[fi];
        args = [...args];
        args[fi] = function (...a) {
          const saved = prefix;
          prefix = [...at, name];
          try { return fn.apply(this, a); } finally { prefix = saved; }
        };
        Object.defineProperty(args[fi], 'length', { value: fn.length });
        return Reflect.apply(t, self, args);
      }
      const r = Reflect.apply(t, self, args);
      return typeof r === 'function' ? wrapDescribe(r) : r;
    },
    get(t, k) {
      const v = Reflect.get(t, k, t);
      if (typeof v === 'function' && typeof k === 'string' && REGISTRAR_KEYS.has(k)) return wrapDescribe(v);
      return v;
    },
  });
  const test = wrapTest(bt.test, false);
  const it = bt.it === bt.test ? test : wrapTest(bt.it, false);
  const describe = wrapDescribe(bt.describe);
  bt.test = test;
  bt.it = it;
  bt.describe = describe;
  for (const [k, v] of [['test', test], ['it', it], ['describe', describe]]) {
    if (typeof globalThis[k] === 'function') globalThis[k] = v;
  }
  // after the file's own afterAll hooks (registered later, so they run first)
  bt.afterAll(() => bracket.finish());
}
