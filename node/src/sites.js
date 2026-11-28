'use strict';
// Call-site resolution: the first stack frame that is neither Node internals
// nor detjs itself. Events whose first such frame belongs to the test runner
// (vitest, jest, tinypool, ...) are infrastructure and are not recorded, like
// the pytest/detpy frames in the Python shell.
const path = require('node:path');
const PHASES = require('./phases').C; // P2 Phase B counters (written only with DETJS_PHASES=1)

const SHELL_DIR = path.resolve(__dirname) + path.sep; // node/src/
const INFRA = /[\\/]node_modules[\\/](?:\.pnpm[\\/][^\\/]+[\\/]node_modules[\\/])?(?:vitest|@vitest|vite|vite-node|tinypool|playwright|playwright-core|@playwright|tinyspy|jest-[a-z0-9-]+|@jest|jest|expect|babel-jest|ts-jest|@swc|source-map-support|pretty-format|mocha|tap|@tapjs|tap-parser|tap-yaml|tcompare|async-hook-domain|ava|@ava|emittery|p-map|currently-unhandled|jasmine|jasmine-core|@jasminejs|uvu|sade|kleur)[\\/]/;
const RUNNER_INTERNAL = /^(?:node:)?internal\/test_runner\//;
const DEPS = /^(.*[\\/]node_modules[\\/])((?:@[^\\/]+[\\/])?[^\\/]+)[\\/](.*)$/;

let root = process.cwd();

function setRoot(r) {
  root = path.resolve(r);
}

/** Machine-independent form of a path. */
function normPath(p) {
  if (p === undefined || p === null) return '<none>';
  let s = typeof p === 'string' ? p : Buffer.isBuffer(p) ? p.toString('utf8') : p && typeof p === 'object' && typeof p.href === 'string' && p.protocol === 'file:' ? require('node:url').fileURLToPath(p.href) : String(p);
  if (!path.isAbsolute(s)) s = path.resolve(s);
  const m = DEPS.exec(s);
  if (m) return `<deps>/${m[2].replace(/\\/g, '/')}/${m[3].replace(/\\/g, '/')}`;
  const rel = path.relative(root, s);
  if (!rel.startsWith('..') && !path.isAbsolute(rel)) return rel.replace(/\\/g, '/') || '.';
  const tmp = require('node:os').tmpdir();
  if (s.startsWith(tmp + path.sep)) return '<tmp>/' + path.relative(tmp, s).split(path.sep).slice(1).join('/');
  return '<abs>/' + path.basename(s);
}

// The Error constructor of the test realm (set by the shells): Vitest and Jest
// install source-map support on it, so its formatted stack gives the original
// .ts/.tsx file and line, which the shared event vocabulary requires.
let realmError = null;

function setRealmError(E) {
  realmError = typeof E === 'function' ? E : null;
}

const FRAME = /^\s*at (?:.*? \()?(.+?):(\d+):\d+\)?$/;

/** Source-mapped site for a stack, from the realm's formatted stack (slow path). */
function resolveFormatted() {
  PHASES.site_formatted++;
  const E = realmError || Error;
  const prevLimit = E.stackTraceLimit;
  E.stackTraceLimit = 30;
  let stack;
  try {
    stack = new E().stack;
  } finally {
    E.stackTraceLimit = prevLimit;
  }
  if (typeof stack !== 'string') return '<unknown>';
  const lines = stack.split('\n');
  for (let i = 1; i < lines.length; i++) {
    const m = FRAME.exec(lines[i]);
    if (!m) continue;
    let f = m[1];
    if (f.startsWith('file://')) {
      try { f = require('node:url').fileURLToPath(f); } catch { /* keep */ }
    }
    const q = f.indexOf('?');
    if (q >= 0) f = f.slice(0, q);
    if (RUNNER_INTERNAL.test(f)) return null; // node:test's own machinery (durations, timeouts)
    if (!f || f.startsWith('node:') || f.startsWith('internal/') || f.startsWith(SHELL_DIR) || f === 'native' || !f.includes('/')) continue;
    if (INFRA.test(f)) return null;
    return `${normPath(f)}:${m[2]}`;
  }
  return '<node>';
}

const structured = (_e, cs) => cs;

// Jest words a "module not found" error by listing the siblings of the missing file with `glob` (jest-resolve's
// findSiblingsWithFileExtension): a package's optional `require` (ws -> bufferutil) then makes glob stat files in the
// test window. That is the runner's own work (the cache capture already says so), not the test's.
const GLOB_DEPS = /[\\/]node_modules[\\/](?:\.pnpm[\\/][^\\/]+[\\/]node_modules[\\/])?(?:glob|minimatch|path-scurry)[\\/]/;
function runnerLookup() {
  const E = Error;
  const prevPrepare = E.prepareStackTrace;
  const prevLimit = E.stackTraceLimit;
  E.prepareStackTrace = structured;
  E.stackTraceLimit = 40;
  const holder = {};
  PHASES.stack_captures++;
  try {
    E.captureStackTrace(holder, runnerLookup);
    return Array.isArray(holder.stack) && holder.stack.some((cs) => (cs.getFunctionName && cs.getFunctionName()) === 'findSiblingsWithFileExtension');
  } catch {
    return false;
  } finally {
    E.prepareStackTrace = prevPrepare;
    E.stackTraceLimit = prevLimit;
  }
}
const CACHE = new Map(); // raw "file:line:column" of the first relevant frame -> site (or null)
const CACHE_MAX = 200000;

function rawFile(cs) {
  let f = cs.getFileName() || '';
  if (f.startsWith('file://')) {
    try { f = require('node:url').fileURLToPath(f); } catch { /* keep */ }
  }
  const q = f.indexOf('?');
  return q >= 0 ? f.slice(0, q) : f;
}

/**
 * Site of the caller of the patched API: `path:line` relative to the root,
 * source mapped when the realm maps stacks (Vitest, Jest), or null when the
 * event comes from runner infrastructure. One structured stack capture per
 * call; the source-mapped formatting runs once per distinct raw position.
 */
// P2 C6: the first capture's depth. Any depth up to 30 gives the same site (the first deciding frame within 30
// frames); 10 instead of 8 decides at once the calls whose deciding frame is the 9th or 10th, which on agentsys (Jest)
// were most of those needing the second capture (node/test/p2-c6-depth.test.js, harness/p2/C6.md).
const FIRST_DEPTH = 10;
function resolve() {
  // undefined = no decision within the captured frames; null = infrastructure.
  // (the body, not a call to resolveWith: one frame fewer above the caller's, as before)
  PHASES.resolve_calls++;
  let site = resolveDepth(FIRST_DEPTH);
  if (site === undefined) { PHASES.stack_deep++; site = resolveDepth(30); }
  return site === undefined ? '<node>' : site;
}

/** resolve() with a given first depth, for the test that the depth does not change the site (same frame count). */
function resolveWith(first) {
  // undefined = no decision within the captured frames; null = infrastructure.
  PHASES.resolve_calls++;
  let site = resolveDepth(first);
  if (site === undefined && first < 30) { PHASES.stack_deep++; site = resolveDepth(30); }
  return site === undefined ? '<node>' : site;
}

/** undefined when no decision within `depth` frames. */
function resolveDepth(depth) {
  // Raw positions through the host Error (its prepareStackTrace hook is honoured
  // whatever realm the frames belong to); source mapping on cache misses only.
  const E = Error;
  const prevPrepare = E.prepareStackTrace;
  const prevLimit = E.stackTraceLimit;
  E.prepareStackTrace = structured;
  E.stackTraceLimit = depth;
  const holder = {};
  PHASES.stack_captures++;
  try {
    E.captureStackTrace(holder, resolveDepth);
    // eslint-disable-next-line no-unused-expressions
    holder.stack;
  } finally {
    E.prepareStackTrace = prevPrepare;
    E.stackTraceLimit = prevLimit;
  }
  const frames = holder.stack;
  if (!Array.isArray(frames)) return resolveFormatted();
  for (const cs of frames) {
    const f = rawFile(cs);
    if (RUNNER_INTERNAL.test(f)) return null; // node:test's own machinery (durations, timeouts)
    if (!f || f.startsWith('node:') || f.startsWith('internal/') || f.startsWith(SHELL_DIR) || !f.includes('/')) continue;
    if (INFRA.test(f)) return null;
    if (GLOB_DEPS.test(f) && runnerLookup()) return null;
    const key = `${f}:${cs.getLineNumber()}:${cs.getColumnNumber()}`;
    let site = CACHE.get(key);
    if (site === undefined) {
      site = resolveFormatted();
      if (CACHE.size < CACHE_MAX) CACHE.set(key, site);
    }
    return site;
  }
  return frames.length < depth ? '<node>' : undefined;
}

/**
 * Whether the call was made for the runner: walking out from the caller past Node, detjs and installed libraries,
 * a runner frame (INFRA) comes before any project frame. A library working for the runner (source-map parsing a
 * map while Jest formats a stack) is then the runner's; a library a test calls is the test's.
 */
function runnerInitiated() {
  // a shallow capture first; a library's recursion (source-map's quick-sort) can fill it with library frames before
  // the runner's: then the whole stack decides (dom-testing-library: such draws were taken as the test's)
  const r = runnerInitiatedAt(40);
  return r === null ? runnerInitiatedAt(Infinity) === true : r;
}

/** true / false as decided by the first `limit` frames; null when they hold only library and Node frames. */
function runnerInitiatedAt(limit) {
  const E = Error;
  const prevPrepare = E.prepareStackTrace;
  const prevLimit = E.stackTraceLimit;
  E.prepareStackTrace = structured;
  E.stackTraceLimit = limit;
  const holder = {};
  PHASES.stack_runner++;
  try {
    E.captureStackTrace(holder, runnerInitiated);
    // eslint-disable-next-line no-unused-expressions
    holder.stack;
  } finally {
    E.prepareStackTrace = prevPrepare;
    E.stackTraceLimit = prevLimit;
  }
  // inside an Error.prepareStackTrace hook (source-map-support formatting a stack for Jest) V8 does not call the hook
  // again: the nested capture is the default text, read line by line
  const st = holder.stack;
  const files = Array.isArray(st) ? st.map(rawFile)
    : typeof st === 'string' ? st.split('\n').slice(1).map((l) => { const m = FRAME.exec(l); return m ? rawFile({ getFileName: () => m[1] }) : (/^\s*at (?:.*? \()?(node:[^)]*|native|<anonymous>)\)?$/.test(l) ? 'node:' : ''); })
      : null;
  if (!files) return false;
  for (const f of files) {
    if (RUNNER_INTERNAL.test(f)) return true;
    if (!f || f.startsWith('node:') || f.startsWith('internal/') || f.startsWith(SHELL_DIR) || !f.includes('/')) continue;
    if (INFRA.test(f)) return true;
    if (f.includes(`${path.sep}node_modules${path.sep}`)) continue;
    return false;
  }
  return files.length >= limit ? null : false;
}

module.exports = { resolve, resolveWith, normPath, setRoot, setRealmError, SHELL_DIR, INFRA, runnerInitiated };
