'use strict';
// The installed dependencies of the project (review R-055 V5, docs/VERIFY-CONTRACT.md `inputs.deps`): every file under
// <root>/node_modules (packages, scoped packages, nested node_modules; not the tools' own output: .bin, .cache,
// .detjs, .vite-temp, ...), by relative path and content digest. It does not depend on which tests ran (a cached or
// parallel run has the same input as a full serial one). Contents are read once: digests are kept in
// <root>/.detjs/deps-digests.json keyed by path, size and mtime.
// Not covered: packages outside <root>/node_modules (a monorepo's hoisted parent directory, a global install),
// listed in docs/VERIFY-INPUTS.md.
const fs = require('node:fs');
const path = require('node:path');
const native = require('./native');

function walk(dir, rel, out) {
  let ents;
  try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
  for (const e of ents) {
    // a dot directory directly under a node_modules directory is a tool's output (.bin, .cache, .detjs, .vite-temp),
    // except pnpm's store of the packages (.pnpm; the top-level entries are links into it, and links are not followed)
    if (e.isDirectory() && e.name.startsWith('.') && e.name !== '.pnpm' && path.basename(dir) === 'node_modules') continue;
    const r = rel ? `${rel}/${e.name}` : e.name;
    const abs = path.join(dir, e.name);
    if (e.isDirectory()) walk(abs, r, out);
    else if (e.isFile()) out.push([r, abs]);
  }
}

/** `inputs.deps` of the run: `<n> files <digest>`, or null when the project has no node_modules. */
function depsInput(runDir) {
  const root = path.dirname(path.dirname(runDir)); // <root>/.detjs/run-<pid>
  const nm = path.join(root, 'node_modules');
  try { if (!fs.statSync(nm).isDirectory()) return null; } catch { return null; }
  const files = [];
  walk(nm, '', files);
  if (!files.length) return null;
  const cachePath = path.join(root, '.detjs', 'deps-digests.json');
  let cache = {};
  try { cache = JSON.parse(fs.readFileSync(cachePath, 'utf8')) || {}; } catch { /* none yet */ }
  const next = {};
  const lines = [];
  files.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  for (const [r, abs] of files) {
    let d = 'unreadable';
    try {
      const st = fs.statSync(abs);
      const key = `${st.size}:${st.mtimeMs}`;
      const c = cache[r];
      d = c && c[0] === key ? c[1] : native.digest(fs.readFileSync(abs));
      next[r] = [key, d];
    } catch { /* unreadable */ }
    lines.push(`${r}\t${d}\n`);
  }
  try { fs.writeFileSync(cachePath, JSON.stringify(next)); } catch { /* read-only: digests are recomputed next time */ }
  return `${lines.length} files ${native.digest(Buffer.from(lines.join('')))}`;
}

module.exports = { depsInput };
