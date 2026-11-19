'use strict';
// Call-site resolution: the first stack frame that is neither Node internals
// nor detjs itself. Events whose first such frame belongs to the test runner
// (vitest, jest, tinypool, ...) are infrastructure and are not recorded, like
// the pytest/detpy frames in the Python shell.
const path = require('node:path');

const SHELL_DIR = path.resolve(__dirname) + path.sep; // node/src/
const INFRA = /[\\/]node_modules[\\/](?:\.pnpm[\\/][^\\/]+[\\/]node_modules[\\/])?(?:vitest|@vitest|vite|vite-node|tinypool|playwright|playwright-core|@playwright|tinyspy|jest-[a-z-]+|@jest|jest|expect|babel-jest|ts-jest|@swc|source-map-support|pretty-format|mocha)[\\/]/;
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
function resolve() {
  // undefined = no decision within the captured frames; null = infrastructure.
  let site = resolveDepth(8);
  if (site === undefined) site = resolveDepth(30);
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

module.exports = { resolve, normPath, setRoot, setRealmError, SHELL_DIR };
