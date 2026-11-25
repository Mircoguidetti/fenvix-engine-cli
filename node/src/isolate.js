'use strict';
// `detjs vitest|jest --det --det-isolate`: every test in a fresh runner process (audit G-1394), and with
// --det-cache a test is reused or run on its own inputs (audit G-1397).
//
// The Python shell forks per test from the session's snapshot (python/detpy/isolate.py). A Node test runner has no
// such snapshot, so the isolation is made from runner sessions:
//   1. collection: one session with a test-name filter that matches no test: every test is registered and recorded
//      as skipped in its trace, which gives the tests in run order (file order and declaration order, or the seeded
//      shuffle);
//   2. one session per test: the file alone and a filter that matches exactly that test (`-t ^<full name>$`), so the
//      test runs in a worker of its own after its file's collection, and nothing of another test ran in that
//      process before it. Tests whose full names are equal cannot be told apart by a filter: they run together, as
//      one (said in the output);
//   3. the trace of the run is the tests' own records, in run order (`meta.isolate_tests`); the receipts and the
//      summary are those of the per-test sessions, and the run fails when one of its tests did not pass.
// Cache: each per-test session keeps its entries under a scope of its own (DETJS_CACHE_SCOPE, src/cache/proof.js),
// so its file entry is the test's collection plus the test itself: a change of an input only one test reads
// reruns that test alone. The key holds no earlier test (there is none in that process), the carried-set rule's
// smallest case. Each per-test session pays the runner's start-up (measured: about one to two seconds).
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const native = require('./native');

const BIN = path.join(__dirname, '..', 'bin', 'detjs.js');
// detjs options of the outer run that the per-test sessions must not inherit as they are
const OWN = /^--det-(isolate|trace|compare|cache-receipts|cache-summary)(=|$)/;
const OWN_VALUE = new Set(['--det-trace', '--det-compare', '--det-cache-receipts', '--det-cache-summary']);
const NO_MATCH = '^detjs-collect-only-[0-9a-f]{32}$';

function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');
}

/** {header, tests} of a trace, streamed (P0 big trace); null when it cannot be read or a line is not JSON. */
function readTrace(p) {
  try {
    let header;
    const tests = [];
    require('./trace-lines').forEachLine(p, (l) => {
      if (!l) return;
      const o = JSON.parse(l);
      if (o.type === 'header' && header === undefined) header = o;
      else if (o.type === 'test') tests.push(o);
    });
    return { header, tests };
  } catch { return null; }
}

function readJson(p) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return null; }
}

/** The runner's full name of a test from its detjs id (`file::suite::name`, a duplicate's ` #n` removed). */
function fullName(id) {
  const parts = id.split('::').slice(1);
  if (parts.length) parts[parts.length - 1] = parts[parts.length - 1].replace(/ #\d+$/, '');
  return parts.join(' ');
}

/**
 * The `-t` pattern (a regular expression, anchored by the caller) that matches exactly the runner's full name of a
 * test from its detjs id. Built from the id, the name is ambiguous in two ways the plain `fullName` got wrong
 * (gstack /review, 2026-11-23: a filter that matches nothing skips the test, and the session passed):
 *   * ` #<n>` is detjs' suffix for a duplicate (controls.uniqueIds) only when the same id without it exists in the
 *     run (`ids`); otherwise it is part of the test's own name ("regression for issue #42") and stays;
 *   * `::` separates describe blocks and test in the id, which the runner joins with a space -- but a name can contain
 *     `::` itself ("Parser::parse"), so every `::` matches either.
 */
function namePattern(id, ids) {
  const parts = id.split('::').slice(1);
  if (parts.length) {
    const last = parts[parts.length - 1];
    const m = / #\d+$/.exec(last);
    if (m && ids && ids.has(id.slice(0, id.length - m[0].length))) parts[parts.length - 1] = last.slice(0, m.index);
  }
  return parts.map(escapeRe).join('(?: |::)');
}

async function main(runner, argv) {
  const session = require('./session');
  const { opts, rest } = session.parseArgs(argv);
  const root = process.cwd();
  const det = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--det')) continue;
    if (OWN.test(a)) { if (OWN_VALUE.has(a)) i++; continue; }
    det.push(a);
    if (!a.includes('=') && ['--det-seed', '--det-cache', '--det-epoch', '--det-disable', '--det-cassette', '--det-allow-host', '--det-tick',
      '--det-tick-adapt', '--det-timers', '--det-timer-budget', '--det-max-events', '--det-sites', '--det-cache-max-age', '--det-tz', '--det-locale', '--det-net'].includes(a) && i + 1 < argv.length) det.push(argv[++i]);
  }
  if (!det.includes('--det') && !opts.det) det.unshift('--det');
  const runnerArgs = runner === 'vitest' && ['run', 'watch', 'dev'].includes(rest[0]) ? rest.slice(1) : rest;
  const work = path.join(root, '.detjs', `isolate-${process.pid}`);
  fs.rmSync(work, { recursive: true, force: true });
  fs.mkdirSync(work, { recursive: true });
  const tracePath = path.resolve(root, opts.trace || path.join('.detjs', 'trace.jsonl'));
  const receiptsPath = path.resolve(root, opts.cacheReceipts || path.join('.detjs', 'receipts.jsonl'));
  const summaryPath = path.resolve(root, opts.cacheSummary || path.join('.detjs', 'cache-summary.json'));
  const childEnv = { ...process.env, DETJS_ISOLATE_CHILD: '1' };
  const runSession = (extraDet, extraArgs, env, capture = true) => spawnSync(process.execPath,
    [BIN, runner, ...det.filter((a) => !(extraDet.collect && a.startsWith('--det-cache'))), ...extraDet.det, ...(runner === 'vitest' ? ['run'] : []), ...runnerArgs, ...extraArgs],
    { cwd: root, env: { ...childEnv, ...env }, encoding: 'utf8', maxBuffer: 256 << 20, stdio: capture ? 'pipe' : 'inherit' });

  // 1. collection
  const collectTrace = path.join(work, 'collect.jsonl');
  let col;
  let collected;
  const patternOf = new Map(); // test id -> the runner's full name (Vitest's list names)
  if (runner === 'vitest') {
    // Vitest records no test a name filter excludes: its own listing (`vitest list --json`), files sorted, tests in
    // declaration order (the per-test sessions run alone, so the order is only the trace's)
    const out = path.join(work, 'list.json');
    const vdir = path.dirname(fs.realpathSync(require('node:module').createRequire(path.join(root, 'noop.js')).resolve('vitest/package.json')));
    const vpkg = JSON.parse(fs.readFileSync(path.join(vdir, 'package.json'), 'utf8'));
    const vbin = path.join(vdir, typeof vpkg.bin === 'string' ? vpkg.bin : vpkg.bin.vitest);
    const env = { ...process.env };
    delete env.DETJS;
    col = spawnSync(process.execPath, [vbin, 'list', `--json=${out}`, ...runnerArgs], { cwd: root, env, encoding: 'utf8', maxBuffer: 256 << 20 });
    const list = readJson(out) || [];
    const byFile = new Map();
    for (const e of list) {
      const f = path.relative(root, e.file).split(path.sep).join('/');
      if (!byFile.has(f)) byFile.set(f, []);
      byFile.get(f).push(e.name);
    }
    const tests = [];
    for (const f of [...byFile.keys()].sort()) {
      const seen = new Map();
      for (const name of byFile.get(f)) {
        const base = `${f}::${name.split(' > ').join('::')}`;
        const n = (seen.get(base) || 0) + 1;
        seen.set(base, n);
        const id = n === 1 ? base : `${base} #${n}`;
        patternOf.set(id, name);
        tests.push({ nodeid: id });
      }
    }
    collected = { tests };
  } else {
    col = runSession({ collect: true, det: [`--det-trace=${collectTrace}`] }, ['-t', NO_MATCH], {});
    collected = readTrace(collectTrace);
  }
  if (!collected || !collected.tests.length) {
    process.stdout.write(col.stdout || '');
    process.stderr.write(col.stderr || '');
    process.stderr.write(`detjs ${runner} --det-isolate: no test collected\n`);
    fs.rmSync(work, { recursive: true, force: true });
    return col.status || 1;
  }
  // tests in run order, grouped by what a name filter can tell apart
  const groups = [];
  const byKey = new Map();
  const allIds = new Set(collected.tests.map((t) => t.nodeid));
  for (const t of collected.tests) {
    const file = t.nodeid.split('::', 1)[0];
    const real = patternOf.get(t.nodeid);
    const name = real || fullName(t.nodeid);
    const pattern = real ? escapeRe(real) : namePattern(t.nodeid, allIds);
    const key = `${file}\u0000${pattern}`;
    if (!byKey.has(key)) { byKey.set(key, { file, name, pattern, ids: [] }); groups.push(byKey.get(key)); }
    byKey.get(key).ids.push(t.nodeid);
  }
  process.stdout.write(`detjs ${runner} --det-isolate: ${collected.tests.length} tests, each in a fresh process (one runner session per test)\n`);

  // 2. one session per test
  const records = [];
  const rows = [];
  const summaries = [];
  // the collection run itself failed (Jest: a file that fails to load has no test to collect, and every per-test
  // session of the others passes): the run is red, whatever the per-test sessions say (gstack /review, pass 3)
  let failed = Boolean(col && (col.status !== 0 || col.signal));
  if (failed) {
    process.stderr.write(col.stderr || '');
    process.stderr.write(`detjs ${runner} --det-isolate: the collection run failed (exit ${col.status}); the run is reported failed\n`);
  }
  // the header of every per-test session that wrote a trace, merged below (src/isolate-meta.js): a later session's
  // signals (a read outside any test, a sensor that could not start) are the run's too
  const sessionMetas = [];
  const sessionLabels = [];
  groups.forEach((g, i) => {
    const tr = path.join(work, `t-${i}.jsonl`);
    const rc = path.join(work, `r-${i}.jsonl`);
    const sm = path.join(work, `s-${i}.json`);
    const scope = `iso.${native.digest(`${g.file}\u0000${g.name}`).slice(0, 12)}`;
    const fileArg = runner === 'jest' ? ['--runTestsByPath', path.resolve(root, g.file)] : [path.resolve(root, g.file)];
    const r = runSession({ det: [`--det-trace=${tr}`, `--det-cache-receipts=${rc}`, `--det-cache-summary=${sm}`] },
      [...fileArg, '-t', `^${g.pattern}$`], { DETJS_CACHE_SCOPE: scope });
    const t = readTrace(tr);
    // a trace with records but no header line still counts its tests: its meta is then empty, so the merge finds
    // no sensor for that session and fails closed (/review F2)
    if (t) { sessionMetas.push((t.header && t.header.meta) || {}); sessionLabels.push(g.ids[0]); }
    const mine = t ? t.tests.filter((x) => g.ids.includes(x.nodeid)) : [];
    const outcomes = g.ids.map((id) => { const x = mine.find((m) => m.nodeid === id); return x ? x.outcome : 'missing'; });
    const s = readJson(sm);
    const reusedHere = Boolean(s && s.reused_files > 0);
    const reusedIds = new Set(((t && t.header && t.header.meta && t.header.meta.reused_tests) || []).filter((id) => g.ids.includes(id)));
    summaries.push({ g, s, reused: reusedHere, status: r.status });
    for (const x of mine) records.push(x);
    for (const id of g.ids) if (!mine.some((m) => m.nodeid === id)) records.push({ type: 'test', nodeid: id, index: 0, outcome: 'failed', fingerprint: '', n_events: 0, truncated: true, counts: {}, checkpoints: [], events: [] });
    try { for (const l of fs.readFileSync(rc, 'utf8').split('\n').filter(Boolean)) rows.push(l); } catch { /* no cache */ }
    const bad = r.status !== 0 || outcomes.some((o) => !['passed', 'skipped', 'todo'].includes(o));
    if (bad) failed = true;
    const label = g.ids.length > 1 ? `${g.ids[0]} (+${g.ids.length - 1} of the same name, run together)` : g.ids[0];
    process.stdout.write(`detjs isolate: ${bad ? 'FAIL' : 'ok  '} ${label}: ${outcomes.join(',')}${reusedHere || reusedIds.size ? ' (reused with proof)' : ''}\n`);
    if (bad) {
      process.stdout.write((r.stdout || '').split('\n').slice(-60).join('\n'));
      process.stderr.write((r.stderr || '').split('\n').slice(-40).join('\n'));
    }
  });

  // 3. trace, receipts, summary
  const order = records.map((x) => x.nodeid);
  const parts = [];
  const pdir = path.join(work, 'parts');
  fs.mkdirSync(pdir, { recursive: true });
  records.forEach((x, i) => {
    const p = path.join(pdir, `${String(i).padStart(6, '0')}.jsonl`);
    fs.writeFileSync(p, `${JSON.stringify({ type: 'header', format: 'detpy-trace', version: 1, encoding: 2, meta: {}, order: [] })}\n${JSON.stringify(x)}\n`);
    parts.push(p);
  });
  const merged = require('./isolate-meta').mergeSessionMeta(sessionMetas, sessionLabels, argv);
  const meta = merged.meta;
  for (const why of merged.failClosed) process.stderr.write(`detjs ${runner} --det-isolate: NOT PROVEN: ${why}\n`);
  meta.isolate_tests = true;
  meta.isolation = `${runner}: --det-isolate, one runner session (a fresh worker process) per test`;
  meta.files = [...new Set(records.map((x) => x.nodeid.split('::', 1)[0]))];
  const reusedTests = summaries.filter((x) => x.reused).flatMap((x) => x.g.ids);
  if (reusedTests.length) meta.reused_tests = reusedTests; else delete meta.reused_tests;
  // B7 (spec "Engine P0: no false green"): this process writes the final trace, so it carries the counts and prints
  // the one status line (the per-test sessions do not: src/session.js printsStatus); bin/detjs.js decides on them
  const exitStatus = require('./exit-status');
  const status = exitStatus.countStatus(records);
  meta.status = status;
  exitStatus.record(status);
  fs.mkdirSync(path.dirname(tracePath), { recursive: true });
  const res = native.mergeTraces(parts, tracePath, JSON.stringify(meta), order);
  // P0 big trace: a part the merge could not read is missing from the trace: the status is unknown (exit 2)
  if (res.skipped.length) exitStatus.recordUnknown(`unreadable trace parts, their tests are not counted: ${res.skipped.join('; ')}`);
  process.stdout.write(`detjs: trace ${path.relative(root, tracePath)}: ${res.nTests} tests, order digest ${res.orderDigest}\n`);
  process.stderr.write(`${exitStatus.statusLine(status)}\n`);
  if (det.some((a) => a.startsWith('--det-cache'))) {
    fs.mkdirSync(path.dirname(receiptsPath), { recursive: true });
    fs.writeFileSync(receiptsPath, rows.length ? `${rows.join('\n')}\n` : '');
    const merged = {
      isolate_tests: true,
      runner,
      reused_tests_list: reusedTests,
      ran_tests_list: summaries.filter((x) => !x.reused).flatMap((x) => x.g.ids),
      reused_files_list: [],
      reused_tests: reusedTests.length,
      recorded: summaries.reduce((n, x) => n + ((x.s && x.s.recorded) || 0), 0),
      misses: Object.assign({}, ...summaries.map((x) => (x.s && x.s.misses) || {})),
      not_cached: {},
      not_cached_detail: Object.assign({}, ...summaries.map((x) => (x.s && x.s.not_cached_detail) || {})),
      sessions: summaries.map((x) => ({ tests: x.g.ids, reused: x.reused, status: x.status, run: x.s && x.s.run })),
      receipts: receiptsPath,
    };
    // a file whose every test was reused
    const files = new Map();
    for (const x of summaries) { const f = x.g.file; files.set(f, (files.get(f) ?? true) && x.reused); }
    merged.reused_files_list = [...files].filter(([, all]) => all).map(([f]) => f);
    for (const x of summaries) for (const [k, v] of Object.entries((x.s && x.s.not_cached) || {})) merged.not_cached[k] = (merged.not_cached[k] || 0) + v;
    fs.writeFileSync(summaryPath, JSON.stringify(merged, null, 1));
    process.stdout.write(`detjs cache: --det-isolate: reused with proof ${reusedTests.length} of ${order.length} tests; ran ${order.length - reusedTests.length}\n`);
  }
  fs.rmSync(work, { recursive: true, force: true });
  return failed ? 1 : 0;
}

module.exports = { main, fullName, namePattern };
