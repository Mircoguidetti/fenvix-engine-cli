'use strict';
// `detjs uvu [--det ...] [dir] [pattern] [-r module] [-i ignore] [-b]` (uvu 0.5).
//
// uvu's CLI finds the test files (`uvu/parse`), loads them all in one process (each file queues its suites) and then
// runs the queue (`exec`). detjs:
//   * discovery: uvu itself in list mode (the preload wraps `parse`, which also loads the `-r` modules);
//     the configuration digest is the command line (uvu has no configuration file) and the runner version;
//   * --det: one process; `parse`'s result is restricted to and ordered by detjs' list (sorted by path; --det-seed:
//     shared shuffle), so the files load and run in that order;
//   * --det-cache: every file in its own fresh process (`-r` modules load in each), see docs/ALL-RUNNERS.md;
//   * tests: uvu's runner is a closure, so its source is hooked when it loads (module.registerHooks, both the
//     CommonJS and the ES module build): the start of each test (before its `before.each` hooks), its end (after its
//     `after.each` hooks), the order of the tests of a suite and of the suites of a file (--det-seed: shared
//     shuffle). A uvu build without the expected source makes the shell refuse (no silent fallback).
const fs = require('node:fs');
const path = require('node:path');
const common = require('./common');

function findRunner(root) {
  const p = common.findPackage(root, 'uvu');
  return { ...p, binPath: p.bin('uvu') };
}

async function discover(ctx) {
  const { runner, rest } = ctx;
  const notes = [];
  const l = common.listChild(ctx, [runner.binPath, ...rest], { DETJS_UVU_DIR: runner.dir });
  const doc = l.doc || {};
  if (!l.doc) notes.push(`uvu list failed (status ${l.status}): ${(l.stderr || l.stdout).slice(-800)}`);
  const files = (doc.suites || []).map((s) => s.file);
  const config = {
    args: rest.filter((a) => !/^(-c|--color|--no-color)(=|$)/.test(a)),
    requires: doc.requires || [],
    mode: ctx.pc ? 'process per file' : 'one process',
  };
  return { files, config, uncacheable: null, notes, order: 'path' };
}

function launch(ctx, files) {
  const { runner, rest } = ctx;
  const env = { DETJS_UVU_DIR: runner.dir };
  if (!ctx.pc) return common.runChild(ctx, [runner.binPath, ...rest], { role: 'single', env });
  let status = 0;
  for (const f of files) {
    const s = common.runChild(ctx, [runner.binPath, ...rest], { role: 'single', env: { ...env, DETJS_RUNNER_FILE: f } });
    if (s !== 0) status = s;
  }
  return status;
}

function main(argv) {
  return common.runShell({
    name: 'uvu',
    findRunner,
    plain: (rest, r) => [r.binPath, ...rest],
    discover,
    launch,
    isolation: (ctx) => (ctx.pc ? 'uvu: one process per test file (--det-cache), tests in sequence' : 'uvu: one process, files in sequence'),
  }, argv);
}

// -- preload --------------------------------------------------------------------------------------------------------

function wrapParse(fn) {
  const mod = require(path.join(process.env.DETJS_UVU_DIR, 'parse', 'index.js'));
  const real = mod.parse;
  mod.parse = async function parse(...a) {
    const ctx = await real.apply(this, a);
    return fn(ctx);
  };
}

/** List mode: the files uvu would load, none run. */
function preloadList() {
  const out = process.env.DETJS_LIST_OUT;
  wrapParse((ctx) => {
    try {
      fs.writeFileSync(out, JSON.stringify({ suites: ctx.suites.map((s) => ({ name: s.name, file: path.resolve(s.file) })), requires: ctx.requires }));
    } catch { /* reported by the main side */ }
    return { ...ctx, suites: [] };
  });
}

const HOOK = 'globalThis[Symbol.for("detjs.uvu")]';
const PATCHES = [
  // the tests of a suite: order (seeded shuffle) before the loop
  ['for (test of arr) {', `arr = ${HOOK} ? ${HOOK}.order(name, arr) : arr;\n\t\tfor (test of arr) {`],
  // start of a test (before its before.each hooks)
  ['state.__test__ = test.name;', `state.__test__ = test.name; ${HOOK} && ${HOOK}.begin(name, test.name);`],
  // end of a test (after its after.each hooks)
  ['write(PASS);', `${HOOK} && ${HOOK}.end('passed'); write(PASS);`],
  ['write(FAIL);', `${HOOK} && ${HOOK}.end('failed'); write(FAIL);`],
  // a file's group of suites: its name, and the order of its suites
  ['let name = group.shift();', `let name = group.shift(); ${HOOK} && ${HOOK}.group(name, group);`],
];

/** Hook uvu's runner source (CommonJS and ES module builds) when it loads. */
function hookSource() {
  const m = require('node:module');
  const url = require('node:url');
  const dist = path.join(process.env.DETJS_UVU_DIR, 'dist') + path.sep;
  const state = { patched: 0, refused: [] };
  m.registerHooks({
    load(u, context, next) {
      const r = next(u, context);
      if (typeof u !== 'string' || !u.startsWith('file:')) return r;
      let f;
      try { f = url.fileURLToPath(u); } catch { return r; }
      if (!f.startsWith(dist) || !/^index\.m?js$/.test(path.basename(f)) || !r || r.source == null) return r;
      let src = String(r.source);
      for (const [from, to] of PATCHES) {
        if (!src.includes(from)) { state.refused.push(`${path.basename(f)}: ${from}`); return r; }
        src = src.replace(from, to);
      }
      state.patched++;
      return { ...r, source: src };
    },
  });
  return state;
}

/** The test process ('single'): Level 0, capture, uvu's tests as tests. */
function preloadSingle() {
  process.env.DETJS_RUNNER_ROLE = 'nested';
  if (process.env.DETJS_NODE_OPTIONS0) process.env.NODE_OPTIONS = process.env.DETJS_NODE_OPTIONS0;
  else delete process.env.NODE_OPTIONS;
  const c = common.child();
  if (!c) return;
  const native = require('../native');
  const files = common.runFiles();
  const rank = new Map(files.map((f, i) => [f.abs, i]));
  const byAbs = new Map(files.map((f) => [f.abs, f]));
  const single = process.env.DETJS_RUNNER_FILE || null;
  const hooked = hookSource();
  const nameToFile = new Map(); // suite name (relative to uvu's dir) -> file
  wrapParse((ctx) => {
    const suites = ctx.suites.map((s) => ({ ...s, abs: path.resolve(s.file) }))
      .filter((s) => (single ? s.abs === single : rank.has(s.abs)))
      .sort((a, b) => rank.get(a.abs) - rank.get(b.abs));
    for (const s of suites) nameToFile.set(s.name, byAbs.get(s.abs));
    return { ...ctx, suites: suites.map(({ abs, ...s }) => s) };
  });
  let file = null;
  let ok = true;
  let cur = null;
  const open = (f) => {
    if (!f || (file && file.fileId === f.fileId)) return file;
    if (file) file.close(ok);
    ok = true;
    file = new common.ChildFile(f.fileId);
    return file;
  };
  if (single && byAbs.has(single)) {
    open(byAbs.get(single));
    common.onExit(file, () => ok && hooked.patched > 0);
  } else {
    process.on('exit', (code) => { if (file) { if (code || !hooked.patched) file.fail(); else file.close(ok); } });
  }
  const shuffle = (list, key) => (c.controls.has('order') && c.shuffle && list.length > 1
    ? native.shuffleIndices(list.length, c.seed, key).map((i) => list[i]) : list);
  globalThis[Symbol.for('detjs.uvu')] = {
    group(name, runners) {
      const f = nameToFile.get(name);
      open(f);
      if (f) {
        const out = shuffle(runners.slice(), f.fileId);
        runners.splice(0, runners.length, ...out);
      }
    },
    order(suite, arr) {
      return file ? shuffle(arr.slice(), `${file.fileId}::${suite || ''}`) : arr;
    },
    begin(suite, name) {
      if (!file) return;
      cur = file.id(suite ? `${suite}::${name}` : name);
      file.begin(cur);
    },
    end(outcome) {
      if (!file || cur === null) return;
      file.end(cur, outcome);
      if (outcome !== 'passed') ok = false;
      cur = null;
    },
  };
  if (single || files.length) {
    process.on('beforeExit', () => {
      if (!hooked.patched) process.stderr.write(`detjs: uvu runner source not recognised (${hooked.refused.join('; ')}): tests are not bracketed\n`);
    });
  }
}

function preload(role) {
  if (role === 'list') preloadList();
  else if (role === 'single') preloadSingle();
}

module.exports = { main, preload };
