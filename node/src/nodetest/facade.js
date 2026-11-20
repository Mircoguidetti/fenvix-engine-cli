'use strict';
// What a test file gets for `node:test` under --det (the preload redirects the specifier here, for `require` to
// facade.cjs, for `import` to facade.mjs; both build on makeFacade).
//
// * `concurrency` in the options of a test or suite (and of `t.test`) becomes 1: the tests of a file run one at a
//   time, in order (the Jest shell's maxConcurrency=1);
// * with --det-seed: the tests and suites declared at the top of the file and in each suite are declared in a
//   reproducible shuffled order (native.shuffleIndices, keyed like the other shells: file -> suite -> test). The
//   top-level declarations are held until the test file's module finished evaluating (the preload flushes them at
//   that point: after the CommonJS entry returned, or from a call appended to the ES module entry), suite children
//   until the suite's callback returned. Nothing runs before that, so the order does not depend on timing.
//
// Every call reaches node:test through a one-line trampoline compiled with the caller's file name and position:
// node:test records the location of its caller (`getCallerLocation`), which reporters show (spec failures, junit
// `file`/`line`); without it, every test would appear to be declared in this file.
const vm = require('node:vm');
const native = require('../native');

const PRE = '(function (f, t, a) { return ';
const CALL = 'f.apply(t, a)';
const AT = CALL.indexOf('apply'); // V8 reports a call frame at the called property
const tramps = new Map();

function callerSite(below) {
  const E = Error;
  const pp = E.prepareStackTrace;
  const lim = E.stackTraceLimit;
  E.prepareStackTrace = (_e, cs) => cs;
  E.stackTraceLimit = 2;
  const h = {};
  try {
    E.captureStackTrace(h, below);
    // eslint-disable-next-line no-unused-expressions
    h.stack;
  } finally {
    E.prepareStackTrace = pp;
    E.stackTraceLimit = lim;
  }
  const cs = Array.isArray(h.stack) ? h.stack[0] : null;
  if (!cs) return null;
  const file = cs.getScriptNameOrSourceURL && cs.getScriptNameOrSourceURL();
  const line = cs.getLineNumber();
  const col = cs.getColumnNumber();
  if (!file || !line || !col) return null;
  return { file, line, col };
}

/** A function that calls `f` with `this`/args from a frame located at `site` (or directly when unknown). */
function trampoline(site) {
  if (!site || site.col - 1 - PRE.length - AT < 0 && site.line === 1) return (f, t, a) => f.apply(t, a);
  const k = `${site.file}\u0000${site.line}\u0000${site.col}`;
  let t = tramps.get(k);
  if (!t) {
    try {
      const col = site.col - 1 - PRE.length - AT;
      t = new vm.Script(`${PRE}${CALL} })`, { filename: site.file, lineOffset: site.line - 1, columnOffset: col }).runInThisContext();
    } catch {
      t = (f, th, a) => f.apply(th, a);
    }
    if (tramps.size < 100000) tramps.set(k, t);
  }
  return t;
}

const isFn = (x) => typeof x === 'function';
const isOpts = (x) => x !== null && typeof x === 'object' && !Array.isArray(x);

/** node:test's argument forms: (name?, options?, fn?) */
function split(args) {
  let name; let options; let fn;
  const a = [...args];
  if (typeof a[0] === 'string' || a[0] === undefined) name = a.shift();
  if (isOpts(a[0])) options = a.shift();
  if (isFn(a[0])) fn = a.shift();
  return { name, options, fn, rest: a };
}

function join({ name, options, fn, rest }, original) {
  const out = [];
  if (typeof original[0] === 'string' || (original[0] === undefined && original.length > 0)) out.push(name);
  if (options !== undefined) out.push(options);
  if (fn !== undefined) out.push(fn);
  return [...out, ...rest];
}

function serialOptions(options) {
  if (!options || !Object.prototype.hasOwnProperty.call(options, 'concurrency')) return options;
  return { ...options, concurrency: 1 };
}

function keepLength(w, fn) {
  try { Object.defineProperty(w, 'length', { value: fn.length }); } catch { /* ignore */ }
  try { Object.defineProperty(w, 'name', { value: fn.name }); } catch { /* ignore */ }
  return w;
}

/**
 * @param real the node:test module (the `test` function with its properties)
 * @param st {shuffle, seed, fileKey(): string|null, rootOpen(): bool, holdRoot(item), note(text)}
 */
function makeFacade(real, st) {
  const scopes = []; // open suite callbacks: {key, items}
  const scope = () => (scopes.length ? scopes[scopes.length - 1] : null);

  const flush = (buf) => {
    const perm = native.shuffleIndices(buf.items.length, st.seed, buf.key);
    for (const i of perm) buf.items[i]();
  };

  const declare = (realFn, isSuite) => {
    const w = function detjsDeclare(...args) {
      const site = callerSite(detjsDeclare);
      const parts = split(args);
      parts.options = serialOptions(parts.options);
      const name = typeof parts.name === 'string' ? parts.name : (parts.fn && parts.fn.name) || '<anonymous>';
      const parent = scope();
      const parentKey = parent ? parent.key : st.fileKey();
      if (isSuite && st.shuffle && parts.fn) {
        const fn = parts.fn;
        const key = `${parentKey}::${name}`;
        parts.fn = keepLength(function detjsSuite(...a) {
          const buf = { key, items: [] };
          scopes.push(buf);
          let r;
          try { r = fn.apply(this, a); } finally {
            scopes.pop();
            flush(buf);
          }
          return r;
        }, fn);
      }
      const call = () => trampoline(site)(realFn, this, join(parts, args));
      if (st.shuffle) {
        if (parent) { parent.items.push(call); return Promise.resolve(); }
        if (st.rootOpen()) { st.holdRoot(call); return Promise.resolve(); }
      }
      return call();
    };
    return w;
  };

  const facade = declare(real, false);
  for (const k of Reflect.ownKeys(real)) {
    if (['length', 'name', 'prototype', 'arguments', 'caller'].includes(k)) continue;
    try { Object.defineProperty(facade, k, Object.getOwnPropertyDescriptor(real, k)); } catch { /* ignore */ }
  }
  const wrapFamily = (base, isSuite) => {
    const w = declare(base, isSuite);
    for (const kw of ['skip', 'todo', 'only']) if (isFn(base[kw])) w[kw] = declare(base[kw], isSuite);
    return w;
  };
  facade.test = facade;
  for (const kw of ['skip', 'todo', 'only']) {
    if (isFn(real[kw])) { facade[kw] = declare(real[kw], false); }
  }
  if (isFn(real.it)) facade.it = wrapFamily(real.it, false);
  if (isFn(real.describe)) facade.describe = wrapFamily(real.describe, true);
  if (isFn(real.suite)) facade.suite = wrapFamily(real.suite, true);
  return facade;
}

/** `t.test` of a running test: options serialized, location kept. */
function wrapContextTest(ctx) {
  const realTest = ctx.test;
  if (!isFn(realTest) || realTest.__detjs) return;
  const w = function test(...args) {
    const site = callerSite(test);
    const parts = split(args);
    parts.options = serialOptions(parts.options);
    return trampoline(site)(realTest, this, join(parts, args));
  };
  Object.defineProperty(w, '__detjs', { value: true });
  ctx.test = w;
}

module.exports = { makeFacade, wrapContextTest, trampoline, callerSite };
