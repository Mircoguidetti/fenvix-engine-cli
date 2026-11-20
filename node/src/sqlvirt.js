'use strict';
// SQLite's clock and randomness under Level 0 (audit G-1427 better-sqlite3, G-1428 node:sqlite): the Node
// counterpart of python/detpy/sqlvirt.py (crates/detpy-py/src/sqlvirt.rs).
//
// SQLite evaluates 'now' (`date('now')`, `datetime()`, `strftime('%s')`, `CURRENT_TIMESTAMP`, a column default such
// as `DEFAULT CURRENT_TIMESTAMP`) on the real clock in C, and `random()` / `randomblob(N)` on its own PRNG seeded from
// the OS. Every database a test process opens through `node:sqlite` (`DatabaseSync`) or `better-sqlite3` gets, per
// connection, application-defined functions that override the built-ins of the same name (an application function
// replaces the built-in for that connection, column defaults and triggers included):
//
// * `date`, `time`, `datetime`, `julianday`, `unixepoch`, `strftime`, `timediff` (any number of arguments) and
//   `current_date`, `current_time`, `current_timestamp` (the keywords are calls of these names): a time value 'now'
//   (any case) or a missing one becomes the virtual wall clock (UTC, ms precision, `YYYY-MM-DD HH:MM:SS.SSS`); the
//   call is then evaluated by the real built-in on a private in-memory helper database of the same library, so every
//   modifier and format keeps SQLite's semantics. 'now' is read once per synchronous run of statements (until the next
//   microtask): one statement sees one instant. Each read is a clock event `sqlite.<function>`.
// * `random()` and `randomblob(N)`: a SplitMix64 stream seeded per test (`derive_seed(seed, test id + "\0sqlite")`,
//   per file outside tests), recorded as `random` events.
//
// node:sqlite is loaded when Level 0 is installed (its experimental warning, printed by Node 24 on load, is not
// repeated) and its `prepare` / `exec` / `function` install the functions on first use (so a function the test
// defines itself, also `random`, replaces Level 0's); better-sqlite3 is reached through its
// native addon (`Database` construction), whatever loads it (Vitest's native imports, Jest's registry).
const Module = require('node:module');
const native = require('./native');
const { STATE } = require('./state');

const DATE_FUNCS = ['date', 'time', 'datetime', 'julianday', 'unixepoch', 'strftime', 'timediff'];
const NOW_FUNCS = [['current_date', 'date'], ['current_time', 'time'], ['current_timestamp', 'datetime']];
const RealDate = globalThis.Date;
const M64 = (1n << 64n) - 1n;

// -- per-test stream -------------------------------------------------------------------------------------------
let streamKey = null;
let state = 0n;
function draw() {
  const key = STATE.testId !== null ? STATE.testId : `<file>\0${STATE.fileId || ''}`;
  if (key !== streamKey) {
    streamKey = key;
    const [hi, lo] = native.deriveSeedWords(STATE.config ? STATE.config.seed : 0n, `${key}\0sqlite`);
    state = (BigInt(hi >>> 0) << 32n) | BigInt(lo >>> 0);
  }
  state = (state + 0x9e3779b97f4a7c15n) & M64;
  let z = state;
  z = ((z ^ (z >> 30n)) * 0xbf58476d1ce4e5b9n) & M64;
  z = ((z ^ (z >> 27n)) * 0x94d049bb133111ebn) & M64;
  return z ^ (z >> 31n);
}

function random() {
  const v = BigInt.asIntN(64, draw());
  STATE.record('random', 'sqlite.random', String(v));
  return v;
}

function randomblob(n) {
  let len = Math.trunc(Number(n));
  if (!(len >= 1)) len = 1; // SQLite: N < 1 gives one byte
  const out = Buffer.alloc(len + 8);
  for (let i = 0; i < len; i += 8) out.writeBigUInt64LE(draw(), i);
  const b = out.subarray(0, len);
  STATE.record('random', 'sqlite.randomblob', `${len}:${native.digest(b).slice(0, 16)}`);
  return b;
}

// -- 'now' -----------------------------------------------------------------------------------------------------
let NOW = null;
function nowText(func) {
  if (NOW !== null) return NOW;
  let ms = null;
  try { ms = require('./clock').virtualNowMs(`sqlite.${func}`); } catch { ms = null; }
  if (ms === null) ms = RealDate.now(); // the clock is not installed: SQLite's own behaviour
  NOW = new RealDate(ms).toISOString().replace('T', ' ').replace('Z', '');
  queueMicrotask(() => { NOW = null; });
  return NOW;
}
const isNow = (a) => typeof a === 'string' && a.toLowerCase() === 'now';

/** The arguments of `name(...)` with 'now' (or the missing time value) replaced by the virtual clock. */
function withNow(name, args) {
  const a = [...args];
  let slots;
  let missing;
  if (name === 'strftime') { slots = [1]; missing = a.length === 1; } else if (name === 'timediff') { slots = [0, 1]; missing = false; } else { slots = [0]; missing = a.length === 0; }
  if (missing) a.push(nowText(name));
  else for (const i of slots) if (i < a.length && isNow(a[i])) a[i] = nowText(name);
  return a;
}

// -- one library: how to register a function and evaluate a built-in on the helper --------------------------------
function makeFns(builtin) {
  const fns = [];
  for (const name of DATE_FUNCS) fns.push([name, -1, (...args) => builtin(name, withNow(name, args))]);
  for (const [name, base] of NOW_FUNCS) fns.push([name, 0, () => builtin(base, [nowText(base)])]);
  fns.push(['random', 0, random]);
  fns.push(['randomblob', 1, randomblob]);
  return fns;
}

// node:sqlite ------------------------------------------------------------------------------------------------------
const NODE_VIRT = new WeakSet();
let nodeHelper = null;
const nodeStmts = new Map();

function nodeBuiltin(Real) {
  return (name, args) => {
    if (!nodeHelper) { nodeHelper = new Real(':memory:'); NODE_VIRT.add(nodeHelper); }
    const sql = `select ${name}(${args.map(() => '?').join(', ')}) as v`;
    let st = nodeStmts.get(sql);
    if (!st) { st = nodeHelper.prepare(sql); nodeStmts.set(sql, st); }
    const row = st.get(...args.map((x) => (typeof x === 'boolean' ? Number(x) : x)));
    return row ? row.v : null;
  };
}

function installNodeSqlite(patcher) {
  let m = null;
  const realEmit = process.emitWarning;
  process.emitWarning = function emitWarning(w, ...a) {
    const type = typeof a[0] === 'string' ? a[0] : (a[0] && a[0].type) || (w && w.name);
    if (/sqlite/i.test(String((w && w.message) || w)) && /Experimental/.test(String(type))) return undefined;
    return realEmit.call(this, w, ...a);
  };
  try {
    m = require('node:sqlite');
  } catch {
    return false; // not available (Node < 22.13 without --experimental-sqlite)
  } finally {
    process.emitWarning = realEmit;
  }
  const Real = m.DatabaseSync;
  const P = Real && Real.prototype;
  if (!P || typeof P.function !== 'function' || P.prepare.__detjsSql) return false;
  const realFunction = P.function;
  const fns = makeFns(nodeBuiltin(Real));
  const ensure = (db) => {
    if (NODE_VIRT.has(db)) return;
    try {
      if (db.isOpen === false) return;
      for (const [name, argc, fn] of fns) {
        realFunction.call(db, name, { varargs: argc < 0, deterministic: false }, argc === 1 ? (x) => fn(x) : (argc === 0 ? () => fn() : fn));
      }
      NODE_VIRT.add(db);
    } catch { /* a closed database: installed at its next use */ }
  };
  for (const n of ['prepare', 'exec', 'createTagStore', 'function', 'aggregate']) {
    const real = P[n];
    if (typeof real !== 'function') continue;
    const w = function (...a) { ensure(this); return real.apply(this, a); };
    Object.defineProperty(w, 'name', { value: n });
    Object.defineProperty(w, '__detjsSql', { value: true });
    patcher.set(P, n, w);
  }
  return true;
}

// better-sqlite3 ---------------------------------------------------------------------------------------------------
const BETTER = Symbol.for('detjs.betterSqlite');

function betterAddon(addon) {
  const Real = addon && addon.Database;
  if (typeof Real !== 'function' || Real[BETTER] || !addon.Statement) return;
  const P = Real.prototype;
  if (!P || typeof P.function !== 'function' || typeof P.prepare !== 'function') return;
  let helper = null;
  let helperArgs = null;
  const stmts = new Map();
  const builtin = (name, args) => {
    if (!helper) {
      helper = Reflect.construct(Real, helperArgs);
    }
    const sql = `select ${name}(${args.map(() => '?').join(', ')})`;
    let st = stmts.get(sql);
    // the native prepare's arguments after (source, database) as the library passes them (they changed across
    // versions: pragmaMode, then explainMode)
    if (!st) { st = realPrepare.call(helper, sql, {}, ...prepTail); st.pluck(true); stmts.set(sql, st); }
    return st.get(...args.map((x) => (typeof x === 'boolean' ? Number(x) : x)));
  };
  const fns = makeFns(builtin);
  const realPrepare = P.prepare;
  let prepTail = [false];
  P.prepare = function prepare(...a) {
    if (a.length > 2 && a.slice(2).every((x) => typeof x === 'boolean')) prepTail = a.slice(2).map(() => false);
    return realPrepare.apply(this, a);
  };
  const proxy = new Proxy(Real, {
    construct(t, a, nt) {
      const db = Reflect.construct(t, a, nt === proxy ? t : nt);
      try {
        // the helper: the same arguments with an anonymous in-memory database (positions stable since v7:
        // filename, filenameGiven, anonymous, readonly, fileMustExist, timeout, verbose, buffer, ...)
        if (!helperArgs) helperArgs = a.map((x, i) => (i < 5 ? [':memory:', ':memory:', true, false, false][i] : i === 5 ? x : null));
        for (const [name, argc, fn] of fns) {
          // (fn, name, argCount, safeIntegers, deterministic, directOnly)
          P.function.call(db, argc === 1 ? (x) => fn(x) : (argc === 0 ? () => fn() : fn), name, argc, 0, false, false);
        }
      } catch (e) {
        STATE.notes.push(`better-sqlite3: SQLite clock and randomness not virtualised (${e && e.message})`);
        if (STATE.testId !== null) STATE.recordAt('other', 'uncontrolled.level0', '<detjs>', 'better-sqlite3 functions');
      }
      return db;
    },
    get(t, k, r) { return k === BETTER ? true : Reflect.get(t, k, r); },
  });
  addon.Database = proxy;
}

function installBetterSqlite(patcher) {
  const realLoad = Module._load;
  if (realLoad.__detjsSql) return;
  const w = function _load(request, ...rest) {
    const r = realLoad.call(this, request, ...rest);
    if (typeof request === 'string' && request.endsWith('.node') && r && typeof r === 'object' && r.Database && r.Statement) {
      try { betterAddon(r); } catch { /* never break the load */ }
    }
    return r;
  };
  for (const k of Reflect.ownKeys(realLoad)) {
    if (['length', 'name', 'prototype', 'arguments', 'caller'].includes(k)) continue;
    try { Object.defineProperty(w, k, Object.getOwnPropertyDescriptor(realLoad, k)); } catch { /* ignore */ }
  }
  Object.defineProperty(w, '__detjsSql', { value: true });
  patcher.set(Module, '_load', w);
  // already loaded (an earlier file of this process)
  for (const [file, mod] of Object.entries(require.cache)) {
    if (file.endsWith('.node') && mod && mod.exports) { try { betterAddon(mod.exports); } catch { /* ignore */ } }
  }
}

function installProcess(patcher) {
  installNodeSqlite(patcher);
  installBetterSqlite(patcher);
}

module.exports = { installProcess, betterAddon };
