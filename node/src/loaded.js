'use strict';
// Installed dependencies a run loaded (review R-055 V5, docs/VERIFY-CONTRACT.md `inputs.deps`): every file under a
// node_modules directory in the CommonJS module cache (packages required, and CommonJS packages imported from ESM), by
// machine-independent path (`<deps>/<package>/<file>`, src/sites.js) and content digest. Each test process appends
// what it loaded to <run dir>/loaded/<pid>.txt (at every test end and at exit); src/session.js digests the union.
// Not covered: ESM-only packages (the ESM loader has no cache to read), listed in docs/VERIFY-INPUTS.md.
const fs = require('node:fs');
const path = require('node:path');
const { STATE } = require('./state');
const sites = require('./sites');
const native = require('./native');

const DEPS = `${path.sep}node_modules${path.sep}`;
const TOOL_OUTPUT = /[\\/]node_modules[\\/]\.(?!pnpm[\\/])/;
const done = new Set();
let dir = null;

function flush() {
  if (!dir) return;
  const lines = [];
  STATE.quietDepth++;
  try {
    for (const f of Object.keys(require.cache)) {
      // tools' own output under node_modules (.detjs, .cache, .vite-temp: generated, per run) is no installed package
      if (done.has(f) || !f.includes(DEPS) || TOOL_OUTPUT.test(f)) continue;
      done.add(f);
      let d;
      try { d = native.digest(fs.readFileSync(f)); } catch { d = 'unreadable'; }
      lines.push(`${sites.normPath(f)}\t${d}`);
    }
    if (lines.length) {
      fs.mkdirSync(path.join(dir, 'loaded'), { recursive: true });
      fs.appendFileSync(path.join(dir, 'loaded', `${process.pid}.txt`), `${lines.join('\n')}\n`);
    }
  } catch { /* the run directory is gone (the run ended) */ } finally { STATE.quietDepth--; }
}

function installProcess(runDir) {
  if (dir || !runDir) return;
  dir = runDir;
  STATE.onTestEnd.push(flush);
  process.on('exit', flush);
}

/** `inputs.deps` of the run: `<n> files <digest>`, or null when no process recorded any. */
function depsInput(runDir) {
  const m = new Map();
  const d = path.join(runDir, 'loaded');
  let names;
  try { names = fs.readdirSync(d); } catch { return null; }
  for (const f of names) {
    let text;
    try { text = fs.readFileSync(path.join(d, f), 'utf8'); } catch { continue; }
    for (const l of text.split('\n')) {
      const i = l.indexOf('\t');
      if (i > 0) m.set(l.slice(0, i), l.slice(i + 1));
    }
  }
  if (!m.size) return null;
  const keys = [...m.keys()].sort();
  return `${keys.length} files ${native.digest(Buffer.from(keys.map((k) => `${k}\t${m.get(k)}\n`).join('')))}`;
}

module.exports = { installProcess, depsInput, flush };
