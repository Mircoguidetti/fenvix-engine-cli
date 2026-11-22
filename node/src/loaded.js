'use strict';
// The installed dependencies of the project (review R-055 V5, docs/VERIFY-CONTRACT.md `inputs.deps`): every file under
// <root>/node_modules (packages, scoped packages, nested node_modules, generated code such as .prisma; not the tools'
// own output: .bin, .cache, .detjs, .vite, .vite-temp, .vitest, .vitest-cache), by relative path and content digest.
// It does not depend on which tests ran (a cached or parallel run has the same input as a full serial one). Every file
// is hashed on every run: size and mtime prove nothing (npm extracts every file with the same 1985 mtime).
// Not covered: packages outside <root>/node_modules (a monorepo's hoisted parent directory, a global install),
// listed in docs/VERIFY-INPUTS.md.
const fs = require('node:fs');
const path = require('node:path');
const native = require('./native');

const TOOL_OUTPUT = new Set(['.bin', '.cache', '.detjs', '.vite', '.vite-temp', '.vitest', '.vitest-cache']);

function walk(dir, rel, out) {
  let ents;
  try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
  for (const e of ents) {
    // a tool's own output directly under a node_modules directory is not loaded code (generated code such as .prisma
    // and pnpm's store .pnpm are; links are not followed, so pnpm's top-level entries count once, in .pnpm)
    if (e.isDirectory() && TOOL_OUTPUT.has(e.name) && path.basename(dir) === 'node_modules') continue;
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
  const lines = [];
  files.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  for (const [r, abs] of files) {
    let d = 'unreadable';
    try { d = native.digest(fs.readFileSync(abs)); } catch { /* unreadable */ }
    lines.push(`${r}\t${d}\n`);
  }
  return `${lines.length} files ${native.digest(Buffer.from(lines.join('')))}`;
}

module.exports = { depsInput };
