'use strict';
// Test-process side of `detjs deno-test --det` (loaded by deno-preload.mjs, before any module of the project; one
// test file per process, the main side is src/runners/deno.js):
//
// 1. Level 0: the shared controls (seeds, clock, timers, fs order, closed network) and Deno's own connections
//    (deno-runtime.js installLevel0);
// 2. --det-cache: the shared capture (cache/capture.js) and the Deno namespace (installCapture); a marker in Deno's
//    permission audit log (an environment read of DETJS_AUDIT_START) separates detjs' own set-up from the file's
//    accesses;
// 3. the bracket of every test: `Deno.test` (and .only / .ignore / .each) wrapped so that each test body runs between
//    begin and end of its id (`<file>::<name>`, `#n` for duplicates); `t.step()` steps belong to their test;
// 4. the `unload` event (after the file's last test, hooks and sanitizers) closes the file: trace part and capture.
const controls = require('../controls');

const c = controls.cfg();
const fileId = process.env.DETJS_FILE;
if (c.active && fileId && !globalThis[Symbol.for('detjs.deno.setup')]) {
  globalThis[Symbol.for('detjs.deno.setup')] = true;
  const notes = [];
  controls.installProcess();
  controls.installRealm(globalThis, { sameRealm: true });
  const runtime = require('./deno-runtime');
  runtime.installLevel0(c, notes);
  let cap = null;
  if (process.env.DETJS_CACHE === '1') {
    cap = require('../cache/capture').CAPTURE;
    cap.install({ role: 'worker', root: c.root, mainAnyReads: false });
    runtime.installCapture(cap, notes);
    for (const n of notes) cap.notes.add(n);
  }
  for (const n of notes) controls.STATE.notes.push(n);
  const { Bracket } = require('./bracket');
  const bracket = new Bracket(fileId, cap);
  bracket.doneStyle = false;
  bracket.runtimeName = `deno ${Deno.version.deno}`;
  if (cap) {
    bracket.extraCapture = () => ({
      explained: { paths: [...runtime.explained.paths], env: [...runtime.explained.env], sys: [...runtime.explained.sys] },
    });
    // the start of the file's own accesses in the permission audit log
    Deno.env.get('DETJS_AUDIT_START');
  }
  installRegistrar(bracket);
  globalThis.addEventListener('unload', () => bracket.finish());
}

function installRegistrar(bracket) {
  const wrapCall = (args) => {
    const a = [...args];
    let name;
    let fi = a.findIndex((x) => typeof x === 'function');
    const oi = a.findIndex((x) => x && typeof x === 'object');
    if (typeof a[0] === 'string') name = a[0];
    else if (oi >= 0 && typeof a[oi].name === 'string') name = a[oi].name;
    if (fi < 0 && oi >= 0 && typeof a[oi].fn === 'function') {
      const o = { ...a[oi] };
      if (name === undefined) name = o.fn.name;
      o.fn = bracket.wrap(bracket.register([name || '<anonymous>']), o.fn);
      a[oi] = o;
      return a;
    }
    if (fi >= 0) {
      if (name === undefined) name = a[fi].name;
      a[fi] = bracket.wrap(bracket.register([name || '<anonymous>']), a[fi]);
    }
    return a;
  };
  const targets = new WeakMap();
  const wrapRegistrar = (real) => {
    const p = new Proxy(real, {
      apply(t, self, args) {
        if (targets.has(self)) self = targets.get(self);
        const hasBody = args.some((x) => typeof x === 'function' || (x && typeof x === 'object' && typeof x.fn === 'function'));
        if (hasBody) return Reflect.apply(t, self, wrapCall(args));
        const r = Reflect.apply(t, self, args); // .each(table): a registrar
        return typeof r === 'function' ? wrapRegistrar(r) : r;
      },
      get(t, k) {
        const v = Reflect.get(t, k, t);
        if (typeof v === 'function' && (k === 'only' || k === 'ignore' || k === 'each')) return wrapRegistrar(v);
        return v;
      },
    });
    targets.set(p, real);
    return p;
  };
  Deno.test = wrapRegistrar(Deno.test);
}
