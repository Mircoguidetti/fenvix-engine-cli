'use strict';
// What a repro driver (`fenvix repro`, `python -m detpy.fenvix_js`) needs from a --det run, shared by the Vitest
// and Jest shells:
//
//   --det-order=FILE     run exactly the listed test ids (one per line) in the listed order; the rest does not run
//   --det-outcomes=PATH  JSON: order, outcomes {id: passed|failed|skipped|error}, fingerprints, exceptions,
//                        controls, seed, shuffle, order_missing
//   --det-collect        collection only: the order a run with these options would use, written to the outcomes
//                        file; no test body and no hook runs (the test files are imported, as collection does)
//
// How an order is honoured. Vitest and Jest run one test file at a time, each file in its own module registry
// (Vitest's isolated worker, Jest's vm context), and the tests of a file inside that file's describe tree. An order
// is therefore honoured as: files in the order of their first listed test, then inside each file, at every level of
// the describe tree, children in the order of their first listed test; unlisted tests and describe blocks left
// without a listed test are removed before the file runs. Every order a whole-suite run produces (fixed or
// shuffled) and every sublist of it (what the repro minimisation tries) is contiguous per file and per describe
// block, so it is run exactly as listed; an order that interleaves two files or two describe blocks is run grouped
// as above and the outcomes file says so (`order_regrouped`), with the order really run in `order`.
//
// Worker side: the shells call `plan()`, `filterTree()`, `markCollected()`/`writeSide()`; main side:
// `session.finish` calls `afterMerge()` once the trace is merged.
const fs = require('node:fs');
const path = require('node:path');

let PLAN;

/** Ids as the trace stores them: lone UTF-16 surrogates (names built from binary data) become U+FFFD, as the native
 * core's string conversion does (found on yaml). */
function wf(s) {
  return typeof s.toWellFormed === 'function' ? s.toWellFormed() : s.replace(/[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/g, '\ufffd');
}

/** The --det-order plan of this process (DETJS_ORDER), or null. */
function plan() {
  if (PLAN !== undefined) return PLAN;
  const file = process.env.DETJS_ORDER;
  PLAN = file ? makePlan(readOrder(file)) : null;
  return PLAN;
}

function readOrder(file) {
  return fs.readFileSync(file, 'utf8').split('\n').map((l) => l.replace(/\r$/, '')).filter((l) => l.trim() && !l.startsWith('#'));
}

/** The test file of an id (`file::test`, or `file@@project::test` for a test of a named Vitest project). */
function fileOfId(id) {
  const i = id.indexOf('::');
  const head = i < 0 ? id : id.slice(0, i);
  const j = head.indexOf('@@');
  return j < 0 ? head : head.slice(0, j);
}

function makePlan(ids) {
  ids = ids.map(wf);
  const index = new Map();
  ids.forEach((id, i) => { if (!index.has(id)) index.set(id, i); });
  const files = new Map(); // fileId -> index of its first listed test
  for (const [id, i] of index) { const f = fileOfId(id); if (!files.has(f)) files.set(f, i); }
  return { ids: [...index.keys()], index, files };
}

/** Sequencer side: keep the planned files, in the order of their first listed test. `keyed`: [{fileId, ...}]. */
function orderFiles(keyed, p = plan()) {
  if (!p) return keyed;
  return keyed.filter((k) => p.files.has(k.fileId)).sort((a, b) => p.files.get(a.fileId) - p.files.get(b.fileId));
}

/**
 * Worker side: reduce and reorder a file's describe tree in place to the plan. `children`: the root's child list;
 * `idOf(node)`: a test's id (null for a group); `kidsOf(node)`: a group's child list (null for a test). Returns
 * the number of planned tests kept.
 */
function filterTree(children, idOf, kidsOf, p = plan()) {
  let kept = 0;
  const visit = (list) => {
    const keep = [];
    for (const ch of list) {
      const kids = kidsOf(ch);
      if (kids) {
        const first = visit(kids);
        if (first !== Infinity) keep.push([first, ch]);
      } else {
        const raw = idOf(ch);
        const id = raw === null ? null : wf(raw);
        if (id !== null && p.index.has(id)) { keep.push([p.index.get(id), ch]); kept++; }
      }
    }
    keep.sort((a, b) => a[0] - b[0]);
    list.splice(0, list.length, ...keep.map((x) => x[1]));
    return keep.length ? keep[0][0] : Infinity;
  };
  visit(children);
  return kept;
}

/** Tests of a (filtered, ordered) tree in execution order. */
function flatIds(children, idOf, kidsOf) {
  const out = [];
  const walk = (list) => { for (const ch of list) { const k = kidsOf(ch); if (k) walk(k); else { const id = idOf(ch); if (id !== null) out.push(wf(id)); } } };
  walk(children);
  return out;
}

const ANSI = /\u001b\[[0-9;]*[A-Za-z]/g;

const MSG_MAX = 200;
const CAUSE_MAX = 120;

/** The first lines of a message, joined (ANSI colors removed). */
function linesOf(msg) {
  return String(msg).replace(ANSI, '').split('\n').map((l) => l.trim()).filter(Boolean).slice(0, 4).join(' / ');
}

/** The message of an error's `cause`, or '' (a non-error cause: its string). */
function causeOf(e) {
  let c;
  try { c = e.cause; } catch { return ''; }
  if (c === null || c === undefined) return '';
  if (typeof c !== 'object') return linesOf(String(c));
  let m;
  try { m = c.message === undefined ? String(c) : c.message; } catch { return ''; }
  return linesOf(m);
}

/**
 * [exception type, phase, message (first lines, 200 chars), file:line of the first frame in the project]. An error
 * whose `cause` says something its own message does not (a `fetch()` wrapping the engine's network block reads only
 * "fetch failed") gets ` / cause: <cause message>` within the 200 characters.
 */
function exceptionOf(err, phase, root) {
  let e = err;
  if (Array.isArray(e)) e = e[0]; // jest-circus: [error, asyncError]
  if (e === null || e === undefined) return ['unknown', phase, '', ''];
  if (typeof e !== 'object') return ['thrown', phase, String(e).slice(0, MSG_MAX), ''];
  const name = String(e.name || (e.constructor && e.constructor.name) || 'Error');
  const lines = linesOf(String(e.message === undefined ? e : e.message));
  let text = lines.slice(0, MSG_MAX);
  const cause = causeOf(e);
  if (cause && !lines.includes(cause)) {
    const tail = ` / cause: ${cause}`.slice(0, CAUSE_MAX);
    text = `${lines.slice(0, MSG_MAX - tail.length)}${tail}`;
  }
  return [name, phase, text, whereOf(String(e.stack || ''), root)];
}

function whereOf(stack, root) {
  const r = path.resolve(root || process.cwd()) + path.sep;
  for (const line of stack.replace(ANSI, '').split('\n')) {
    // a frame line is short; a long line is a message (an assertion diff on one line): not scanned (the patterns
    // below are quadratic on very long lines)
    if (line.length > 4096) continue;
    // an absolute path, or (Mocha's stack filter) one relative to the working directory
    const m = /(?:^|[\s(])((?:file:\/\/)?\/[^():]+):(\d+):\d+\)?\s*$/.exec(line)
      || /^\s*at (?:.*\()?((?![a-z]+:)[^\s():/][^\s():]*\.[cm]?[jt]sx?):(\d+):\d+\)?\s*$/.exec(line);
    if (!m) continue;
    let f = path.resolve(m[1].replace(/^file:\/\//, ''));
    if (!f.startsWith(r) || /[\\/]node_modules[\\/]/.test(f) || f.startsWith(path.resolve(__dirname) + path.sep)) continue;
    return `${path.relative(r, f).split(path.sep).join('/')}:${m[2]}`;
  }
  return '';
}

/**
 * Worker side: write what a file's run says beyond the trace (main side reads it in `afterMerge`):
 * {file, project, collected: [ids in run order], states: {id: outcome} for tests the runner never bracketed,
 * exceptions: {id: [...]}, file_error: [...] | null}.
 */
function writeSide(dir, part, data) {
  if (!dir) return;
  try {
    const d = path.join(dir, 'side');
    fs.mkdirSync(d, { recursive: true });
    fs.writeFileSync(path.join(d, part.replace(/\.jsonl$/, '.json')), JSON.stringify(data));
  } catch (e) {
    process.stderr.write(`detjs: repro data of ${data && data.file} not written: ${e && e.message}\n`);
  }
}

function readSide(dir, part) {
  try { return JSON.parse(fs.readFileSync(path.join(dir, 'side', part.replace(/\.jsonl$/, '.json')), 'utf8')); } catch { return null; }
}

const OUTCOME = { passed: 'passed', failed: 'failed', skipped: 'skipped', todo: 'skipped', error: 'error', interrupted: 'error', unknown: 'error' };

/** nodeid -> {outcome, fingerprint} of the trace's tests. Streamed (P0 big trace); a trace that cannot be read
 * throws: no outcome is ever taken from side states in place of an unreadable trace. */
function traceTests(file) {
  const out = new Map();
  require('./trace-lines').forEachLine(file, (line) => {
    if (!line.startsWith('{"type":"test"')) return;
    try {
      const r = JSON.parse(line);
      if (!out.has(wf(r.nodeid))) out.set(wf(r.nodeid), { outcome: r.outcome, fingerprint: r.fingerprint });
    } catch { /* truncated line */ }
  });
  return out;
}

// Runners whose failures `fenvix repro` turns into defects (python/detpy/fenvix_js.py adapters); the detjs command of
// each runner name a shell reports.
const REPRO_RUNNERS = new Set(['vitest', 'jest', 'playwright', 'node-test']);
const COMMAND = { vitest: 'vitest run', deno: 'deno-test', bun: 'bun-test', playwright: 'playwright test' };

/**
 * G-0447, G-1460, G-1554 for Node: a failing --det run ends with the ready-to-paste commands that rerun the failing
 * file(s) with the same seeds and order, and (Vitest, Jest, Playwright) turn each failing test into a reproducible
 * defect.
 */
function failureLines(run, order, outcomes, runner, opts) {
  const failed = order.filter((id) => outcomes[id] === 'failed' || outcomes[id] === 'error');
  if (!failed.length) return [];
  const c = run.cfg;
  const own = c.orderSeed !== undefined && c.orderSeed !== c.seed;
  const seeds = c.shuffle ? ` --det-seed=${c.seed}${own ? ` --det-order-seed=${c.orderSeed}` : ''}` : (c.seed ? ` --det-seed=${c.seed}` : '');
  const what = c.shuffle ? `seed ${c.seed}${own ? `, order seed ${c.orderSeed}` : ''}, shuffled` : `seed ${c.seed}, fixed order`;
  const cmd = `detjs ${COMMAND[runner] || runner} --det${seeds}`;
  const lines = [];
  if (REPRO_RUNNERS.has(runner)) {
    // fenvix repro --seed=N: the configuration known to fail (one seed for the order and the generators)
    const known = c.shuffle && !own ? ` --seed=${c.seed}` : '';
    lines.push(`${failed.length} test(s) failed under --det (${what}). Turn each into a reproducible defect (cause, seed, order, replay command):`);
    for (const id of failed.slice(0, 5)) lines.push(`    fenvix repro ${shellQuote(id)} --runner=${runner}${known}`);
    if (failed.length > 5) lines.push(`    ... and ${failed.length - 5} more`);
  } else {
    lines.push(`${failed.length} test(s) failed under --det (${what}).`);
  }
  const files = [...new Set(failed.map(fileOfId))];
  lines.push(`  rerun the failing file${files.length > 1 ? 's' : ''} with the same seeds and order: ${cmd} ${files.slice(0, 5).map(shellQuote).join(' ')}`
    + `${files.length > 5 ? ` (and ${files.length - 5} more files)` : ''}`);
  if (opts.order) lines.push(`  this run's exact test list: ${cmd} --det-order=${shellQuote(opts.order)}`);
  lines.push(`  the same run again: ${cmd} (with the same arguments)`);
  return lines;
}

function shellQuote(s) {
  if (s === '') return "''";
  return /^[A-Za-z0-9_@%+=:,./-]+$/.test(s) ? s : `'${s.replace(/'/g, "'\"'\"'")}'`;
}

/**
 * Main side, after the merge of the trace (run.dir still present): writes the --det-outcomes file and returns the
 * lines to print (the `fenvix repro` command of every failing test).
 */
function afterMerge(run, opts, files, runner) {
  let tests;
  try {
    tests = traceTests(run.tracePath);
  } catch (e) {
    // P0 big trace: before, an unreadable trace gave an empty map and the outcomes came from the side states (a
    // runner reading them saw a result the trace does not back). Now no outcomes file is written, and why is said;
    // runner/fenvix-run then fails closed (no outcomes: exit 1).
    return [`detjs: --det-outcomes not written: the trace ${run.tracePath} could not be read: ${e && e.message}`];
  }
  const p = opts.order ? makePlan(readOrder(path.resolve(opts.order))) : null;
  const order = [];
  const seen = new Set();
  const outcomes = {};
  const fingerprints = {};
  const exceptions = {};
  const durations = {};
  const fileErrors = new Map();
  const push = (id) => { if (!seen.has(id)) { seen.add(id); order.push(id); } };
  for (const f of files) {
    const side = readSide(run.dir, f.side || f.part);
    if (!side) continue;
    if (side.file_error) fileErrors.set(f.fileId, side.file_error);
    for (const id of side.collected || []) push(wf(id));
    if (!opts.collect) for (const [id, st] of Object.entries(side.states || {})) if (!tests.has(wf(id))) outcomes[wf(id)] = OUTCOME[st] || st;
    for (const [id, e] of Object.entries(side.exceptions || {})) exceptions[wf(id)] = e;
    for (const [id, ms] of Object.entries(side.durations || {})) if (Number.isFinite(ms)) durations[wf(id)] = ms;
  }
  for (const id of tests.keys()) push(id); // bracketed tests the worker did not list (a runner path not covered)
  if (p) {
    // a listed test whose file failed before its tests ran (import or collection error): an error, not missing
    for (const id of p.ids) {
      if (seen.has(id)) continue;
      const fe = fileErrors.get(fileOfId(id));
      if (fe) { push(id); outcomes[id] = 'error'; exceptions[id] = fe; }
    }
  }
  for (const id of order) {
    const t = opts.collect ? null : tests.get(id);
    if (t) {
      outcomes[id] = OUTCOME[t.outcome] || t.outcome;
      if (t.fingerprint) fingerprints[id] = t.fingerprint;
    } else if (!(id in outcomes)) {
      const fe = fileErrors.get(fileOfId(id));
      outcomes[id] = opts.collect ? 'collected' : fe ? 'error' : 'skipped';
      if (fe && !opts.collect) exceptions[id] = fe;
    }
  }
  // the plan as really run: different from the listed order only when the list interleaved files or describe blocks
  const listed = p ? p.ids.filter((id) => seen.has(id)) : [];
  const ran = p ? order.filter((id) => p.index.has(id)) : [];
  const regrouped = listed.some((id, i) => ran[i] !== id);
  const lines = [];
  if (regrouped) lines.push('detjs: --det-order interleaves test files or describe blocks: run grouped by file and describe block (outcomes: order_regrouped)');
  if (opts.outcomes) {
    const data = {
      runner,
      order,
      outcomes,
      fingerprints,
      exceptions,
      // real elapsed ms of each test's bracket (side records; tests that never started have none)
      durations: Object.fromEntries(order.filter((id) => id in durations).map((id) => [id, durations[id]])),
      controls: [...run.cfg.controls].sort(),
      seed: Number(run.cfg.seed),
      shuffle: run.cfg.shuffle,
      order_missing: p ? p.ids.filter((id) => !seen.has(id)) : [],
      order_regrouped: regrouped,
      collect: Boolean(opts.collect),
      file_errors: Object.fromEntries(fileErrors),
      trace: run.tracePath,
    };
    const out = path.resolve(opts.outcomes);
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, JSON.stringify(data));
  }
  if (!opts.collect) lines.push(...failureLines(run, order, outcomes, runner, opts));
  return lines;
}

module.exports = { wf, plan, makePlan, readOrder, orderFiles, filterTree, flatIds, exceptionOf, writeSide, readSide, afterMerge, fileOfId, shellQuote };
