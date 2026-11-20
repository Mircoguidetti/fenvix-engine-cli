'use strict';
// One-line shims through which the runners load detjs' own modules (docs/NODE.md J13, audit G-1477).
//
// A shim must sit in a directory whose path contains `/node_modules/`: Vitest then imports it natively (a file
// outside the project root that Vite serves is refused when the project restricts `server.fs`, found on jotai) and
// Jest does not compile it with the project's Babel configuration (`transformIgnorePatterns`, found on
// matrix-js-sdk). The preferred place is `<root>/node_modules/.detjs/` (inside the root: also allowed by a strict
// `server.fs`); when it cannot be written (a read-only or immutable `node_modules`, a layout without one), the shim
// goes to `<tmpdir>/detjs-shims-<pid>/node_modules/.detjs/`, outside the project and still under a `node_modules`
// segment. If neither can be written, the run stops with a message naming both places.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const made = new Set();
let hooked = false;

function cleanup() {
  for (const p of made) { try { fs.rmSync(p, { force: true, recursive: true }); } catch { /* ignore */ } }
  made.clear();
}

/** Candidate shim directories, in order (DETJS_SHIM_DIRS=a:b overrides, for tests). */
function candidates(root) {
  if (process.env.DETJS_SHIM_DIRS) return process.env.DETJS_SHIM_DIRS.split(path.delimiter).filter(Boolean);
  return [path.join(root, 'node_modules', '.detjs'), path.join(os.tmpdir(), `detjs-shims-${process.pid}`, 'node_modules', '.detjs')];
}

/**
 * Write `content` to a shim file named `name` and return its absolute path (removed at exit). Throws an Error with
 * a clear message when no candidate directory is writable.
 */
function writeShim(root, name, content) {
  const tried = [];
  for (const dir of candidates(root)) {
    const file = path.join(dir, name);
    try {
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(file, content);
      made.add(file);
      // the temporary fallback directory is ours entirely
      const top = path.resolve(dir, '..', '..');
      if (path.basename(top) === `detjs-shims-${process.pid}`) made.add(top);
      if (!hooked) { hooked = true; process.on('exit', cleanup); }
      return file;
    } catch (e) {
      tried.push(`${dir} (${e && e.code ? e.code : e && e.message})`);
    }
  }
  const err = new Error(`detjs: cannot write the runner shim ${name}: tried ${tried.join('; ')}. detjs needs one writable `
    + 'directory whose path contains node_modules (the project\'s node_modules/.detjs, or the temporary directory: set TMPDIR '
    + 'to a writable directory)');
  err.code = 'DETJS_NO_SHIM_DIR';
  throw err;
}

module.exports = { writeShim, candidates, cleanup };
