'use strict';
/*
 * Environment-variable dependency capture for Node test runners (vitest, jest), loaded in every Node process and
 * worker thread through NODE_OPTIONS="--require <this file>". Active only when S2_ENVREC (output directory) is
 * set. Appends to <S2_ENVREC>/<pid>-<threadId>.txt, one line per name, as soon as it is first read:
 *
 *   NAME   a variable read through process.env (get, `in`, hasOwnProperty), or through os.homedir() (HOME) and
 *          os.tmpdir() (TMPDIR, TMP, TEMP), which libuv reads below process.env;
 *   *      the whole environment was enumerated by code that is not the toolchain (test or library code: it may
 *          depend on any variable).
 *
 * Enumerations by the toolchain itself (vitest, vite, tinypool, jest, pnpm, npm, corepack, yarn) forward the
 * environment to a child process or worker, whose own reads are recorded by this hook in that child; they are
 * not recorded, and the per-key lookups they make are not recorded either.
 */
const out = process.env.S2_ENVREC;
if (out) {
  const fs = require('fs');
  const path = require('path');
  let tid = 0;
  try { tid = require('worker_threads').threadId; } catch (e) { /* old node */ }
  const file = path.join(out, `${process.pid}-${tid}.txt`);
  const seen = new Set();
  const rec = (n) => {
    if (seen.has(n)) return;
    seen.add(n);
    try { fs.appendFileSync(file, n + '\n'); } catch (e) { /* output directory gone: nothing to record */ }
  };
  const RUNNER = /[\\/]node_modules[\\/](?:\.pnpm[\\/][^\\/]+[\\/]node_modules[\\/])?(?:vitest|vite|vite-node|@vitest[\\/][^\\/]+|tinypool|tinyexec|jest[^\\/]*|@jest[\\/][^\\/]+|pnpm|npm|corepack|yarn|@yarnpkg[\\/][^\\/]+)[\\/]/;
  let pendingDesc = new Set();
  let pendingGet = new Set();
  let clearScheduled = false;
  const scheduleClear = () => {
    if (clearScheduled) return;
    clearScheduled = true;
    queueMicrotask(() => { pendingDesc = new Set(); pendingGet = new Set(); clearScheduled = false; });
  };
  const enumerated = (keys) => {
    const lim = Error.stackTraceLimit;
    Error.stackTraceLimit = 60;
    const stack = (new Error().stack || '').split('\n').slice(1);
    Error.stackTraceLimit = lim;
    let user = null;
    for (const line of stack) {
      if (line.includes(__filename) || /\(node:|at node:/.test(line)) continue;
      user = line;
      break;
    }
    // the per-key lookups of the enumeration itself are not separate reads
    for (const k of keys) if (typeof k === 'string') pendingDesc.add(k);
    scheduleClear();
    // forwarded by the toolchain to a child whose own reads are recorded: not a dependency of the test
    if (user !== null && RUNNER.test(user)) return;
    rec('*');
  };
  const name = (k) => (typeof k === 'string' ? k : null);
  const wrap = (target) => new Proxy(target, {
    get(t, k) {
      const n = name(k);
      if (n !== null) { if (pendingGet.has(n)) pendingGet.delete(n); else rec(n); }
      return Reflect.get(t, k);
    },
    has(t, k) { const n = name(k); if (n !== null) rec(n); return Reflect.has(t, k); },
    getOwnPropertyDescriptor(t, k) {
      const n = name(k);
      if (n !== null) {
        if (pendingDesc.has(n)) { pendingDesc.delete(n); pendingGet.add(n); } else rec(n);
      }
      return Reflect.getOwnPropertyDescriptor(t, k);
    },
    ownKeys(t) { const keys = Reflect.ownKeys(t); enumerated(keys); return keys; },
    set(t, k, v) { t[k] = v; return true; },
    deleteProperty(t, k) { delete t[k]; return true; },
  });
  let proxy = wrap(process.env);
  Object.defineProperty(process, 'env', {
    configurable: true,
    enumerable: true,
    get() { return proxy; },
    set(v) { proxy = (v && typeof v === 'object') ? wrap(v) : v; },
  });
  const os = require('os');
  const homedir = os.homedir;
  const tmpdir = os.tmpdir;
  os.homedir = function homedirRecorded() { rec('HOME'); return homedir.apply(this, arguments); };
  os.tmpdir = function tmpdirRecorded() { rec('TMPDIR'); rec('TMP'); rec('TEMP'); return tmpdir.apply(this, arguments); };
  try { require('module').syncBuiltinESMExports(); } catch (e) { /* old node */ }
}
