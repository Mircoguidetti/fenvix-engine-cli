'use strict';
// Call-site resolution: the first stack frame that is neither Node internals
// nor detjs itself. Events whose first such frame belongs to the test runner
// (vitest, jest, tinypool, ...) are infrastructure and are not recorded, like
// the pytest/detpy frames in the Python shell.
const path = require('node:path');

const SHELL_DIR = path.resolve(__dirname, '..') + path.sep;
const INFRA = /[\\/]node_modules[\\/](?:\.pnpm[\\/][^\\/]+[\\/]node_modules[\\/])?(?:vitest|@vitest|vite|vite-node|tinypool|tinyspy|jest-[a-z-]+|@jest|jest|expect|babel-jest|ts-jest|@swc|source-map-support|pretty-format)[\\/]/;
const DEPS = /^(.*[\\/]node_modules[\\/])((?:@[^\\/]+[\\/])?[^\\/]+)[\\/](.*)$/;

let root = process.cwd();

function setRoot(r) {
  root = path.resolve(r);
}

function fileOf(cs) {
  let f = cs.getFileName() || cs.getScriptNameOrSourceURL?.() || '';
  if (f.startsWith('file://')) {
    try { f = require('node:url').fileURLToPath(f); } catch { /* keep */ }
  }
  const q = f.indexOf('?');
  return q >= 0 ? f.slice(0, q) : f;
}

/** Machine-independent form of a path. */
function normPath(p) {
  if (p === undefined || p === null) return '<none>';
  let s = typeof p === 'string' ? p : Buffer.isBuffer(p) ? p.toString('utf8') : p instanceof URL ? p.pathname : String(p);
  if (!path.isAbsolute(s)) s = path.resolve(s);
  const m = DEPS.exec(s);
  if (m) return `<deps>/${m[2].replace(/\\/g, '/')}/${m[3].replace(/\\/g, '/')}`;
  const rel = path.relative(root, s);
  if (!rel.startsWith('..') && !path.isAbsolute(rel)) return rel.replace(/\\/g, '/') || '.';
  const tmp = require('node:os').tmpdir();
  if (s.startsWith(tmp + path.sep)) return '<tmp>/' + path.relative(tmp, s).split(path.sep).slice(1).join('/');
  return '<abs>/' + path.basename(s);
}

const prepare = (_e, stack) => stack;

/**
 * Site of the caller of the patched API: `path:line`, or null when the
 * event comes from runner infrastructure. `skip` = frames to drop first.
 */
function resolve() {
  const prevPrepare = Error.prepareStackTrace;
  const prevLimit = Error.stackTraceLimit;
  Error.prepareStackTrace = prepare;
  Error.stackTraceLimit = 24;
  const holder = {};
  Error.captureStackTrace(holder, resolve);
  const stack = holder.stack;
  Error.prepareStackTrace = prevPrepare;
  Error.stackTraceLimit = prevLimit;
  if (!Array.isArray(stack)) return '<unknown>';
  for (const cs of stack) {
    const f = fileOf(cs);
    if (!f || f.startsWith('node:') || f.startsWith('internal/') || f.startsWith(SHELL_DIR)) continue;
    if (INFRA.test(f)) return null;
    return `${normPath(f)}:${cs.getLineNumber() || 0}`;
  }
  return '<node>'; // only Node internals on the stack (async continuation of a core module)
}

module.exports = { resolve, normPath, setRoot, SHELL_DIR };
