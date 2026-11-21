'use strict';
// `detjs node-test [--det ...] [node flags] [file patterns]`: the Node.js test runner (`node --test`).
//
// Without --det (and without DETJS=1): `node --test <args>` unchanged.
// With --det, the main process (this file):
//   * finds the test files as `node --test` does (the same glob patterns and default pattern, sorted; --test-shard),
//     orders them (sorted, or shuffled with --det-seed), and, with --det-cache, decides which files are reused
//     with proof (src/cache/proof.js) before any of them runs;
//   * runs the others through a driver process (src/nodetest/driver.js) started with the user's node flags plus
//     detjs' preload (src/nodetest/preload.js): node:test's run() with the ordered file list, one file at a time,
//     each in its own process (the default isolation; with `--test-isolation=none` all files share the driver,
//     except under --det-cache, where every file gets its own process: skipping one file must not change the
//     context another file runs in);
//   * merges the trace parts, records the cache entries and writes receipts and the summary.
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const session = require('../session');
const native = require('../native');
const controls = require('../controls');

// node flags that take a separate value (`--flag value`); `--flag=value` needs no entry
const TAKES_VALUE = new Set(['-r', '--require', '--import', '--loader', '--experimental-loader', '--env-file', '--env-file-if-exists',
  '-C', '--conditions', '--input-type', '--test-reporter', '--test-reporter-destination', '--test-name-pattern',
  '--test-skip-pattern', '--test-concurrency', '--test-timeout', '--test-shard', '--test-isolation',
  '--experimental-test-isolation', '--test-coverage-include', '--test-coverage-exclude', '--test-coverage-lines',
  '--test-coverage-branches', '--test-coverage-functions', '--watch-path', '--inspect-port', '--debug-port', '--title',
  '--disable-warning', '--localstorage-file', '--experimental-config-file', '--test-global-setup', '--redirect-warnings',
  '--openssl-config', '--icu-data-dir', '--unhandled-rejections', '--trace-event-categories', '--diagnostic-dir',
  '--report-dir', '--report-directory', '--report-filename', '--report-signal', '--heapsnapshot-signal', '--cpu-prof-dir',
  '--cpu-prof-name', '--heap-prof-dir', '--heap-prof-name', '--dns-result-order', '--experimental-default-type',
  '--secure-heap', '--secure-heap-min', '--stack-trace-limit', '--max-old-space-size', '--max-semi-space-size',
  '--use-largepages', '--tls-cipher-list', '--tls-keylog', '--watch-kill-signal', '--network-family-autoselection-attempt-timeout',
  '--experimental-sea-config', '--snapshot-blob', '--env-file-if-exists']);
// flags the driver handles itself (not passed to the test processes as such)
const OWN = new Set(['--test', '--test-reporter', '--test-reporter-destination', '--test-concurrency', '--test-shard',
  '--test-isolation', '--experimental-test-isolation', '--test-only', '--test-name-pattern', '--test-skip-pattern',
  '--test-force-exit', '--experimental-test-coverage', '--test-coverage-include', '--test-coverage-exclude',
  '--test-coverage-lines', '--test-coverage-branches', '--test-coverage-functions', '--watch', '--watch-path']);
// flags that select or report, never change a test file's result: not in the configuration digest
const OUTPUT_ONLY = new Set(['--test-reporter', '--test-reporter-destination', '--test-concurrency', '--test-shard',
  '--experimental-test-coverage', '--test-coverage-include', '--test-coverage-exclude', '--test-coverage-lines',
  '--test-coverage-branches', '--test-coverage-functions', '--test-force-exit', '--test', '--title',
  '--redirect-warnings', '--diagnostic-dir', '--report-dir', '--report-directory', '--report-filename',
  '--cpu-prof-dir', '--cpu-prof-name', '--heap-prof-dir', '--heap-prof-name']);
// node flags that load or configure code before the test file: their files are keyed by content
const FILE_FLAGS = new Set(['-r', '--require', '--import', '--loader', '--experimental-loader', '--env-file',
  '--env-file-if-exists', '--experimental-config-file', '--localstorage-file', '--test-global-setup']);

/** Split node args into flags ([name, value|null, raw...]) and file patterns. */
function parseNodeArgs(args) {
  const flags = [];
  const patterns = [];
  let afterDashDash = false;
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (afterDashDash || !a.startsWith('-') || a === '-') { patterns.push(a); continue; }
    if (a === '--') { afterDashDash = true; continue; }
    const eq = a.indexOf('=');
    if (eq > 0) { flags.push({ name: a.slice(0, eq), value: a.slice(eq + 1), raw: [a] }); continue; }
    if (TAKES_VALUE.has(a) && i + 1 < args.length) { flags.push({ name: a, value: args[i + 1], raw: [a, args[i + 1]] }); i++; continue; }
    flags.push({ name: a, value: null, raw: [a] });
  }
  return { flags, patterns };
}

const values = (flags, ...names) => flags.filter((f) => names.includes(f.name)).map((f) => f.value);
const has = (flags, ...names) => flags.some((f) => names.includes(f.name));

/** Whether type stripping is on for the test processes (it adds .ts/.mts/.cts to the default pattern). */
function stripTypes(flags) {
  const opts = `${process.env.NODE_OPTIONS || ''}`;
  if (has(flags, '--no-experimental-strip-types', '--no-strip-types') || /--no-(experimental-)?strip-types/.test(opts)) return false;
  if (has(flags, '--experimental-strip-types', '--experimental-transform-types', '--strip-types')) return true;
  return Boolean(process.features && process.features.typescript);
}

/** The test files `node --test` would run (node's createTestFileList: glob, node_modules excluded, sorted). */
function findFiles(root, patterns, flags) {
  let pats = patterns;
  const user = pats.length > 0;
  if (!user) {
    const ext = ['js', 'mjs', 'cjs', ...(stripTypes(flags) ? ['ts', 'mts', 'cts'] : [])];
    pats = [`**/{test,test/**/*,test-*,*[._-]test}.{${ext.join(',')}}`];
  }
  const found = new Set();
  for (const p of pats) {
    for (const f of fs.globSync(p, { cwd: root, exclude: (n) => (typeof n === 'string' ? path.basename(n) : n && n.name) === 'node_modules' })) {
      found.add(typeof f === 'string' ? f : path.join(f.parentPath || f.path, f.name));
    }
  }
  if (user && found.size === 0 && pats.every((p) => !/[*?[\]{}!]/.test(p))) {
    return { error: `Could not find '${pats.join(', ')}'` };
  }
  return { files: [...found].sort() };
}

function nodeTestConfigParts(root, flags, isolation, nodeOptions) {
  const keyed = [];
  const early = nodeOptions ? parseNodeArgs(splitNodeOptions(nodeOptions).early).flags : [];
  for (const f of [...early, ...flags]) {
    if (OUTPUT_ONLY.has(f.name)) continue;
    let v = f.value;
    if (FILE_FLAGS.has(f.name) && v) {
      // a project file (setup module, env file, loader): its bytes; an installed package: the runtime identity
      const p = path.resolve(root, v.startsWith('file:') ? require('node:url').fileURLToPath(v) : v);
      if (v.startsWith('.') || v.startsWith('/') || v.startsWith('file:') || fs.existsSync(p)) v = `${v}#${native.fileDigest(p) || 'missing'}`;
    }
    keyed.push([f.name, v]);
  }
  return {
    runner: `node:test ${process.version}`,
    flags: keyed,
    isolation,
    node_options: nodeOptions || '',
    strip_types: String(stripTypes(flags)),
  };
}

/** NODE_OPTIONS split into the module-loading flags (-r, --require, --import, --loader) and the rest. */
function splitNodeOptions(text) {
  const toks = String(text).match(/(?:[^\s"']+|"[^"]*"|'[^']*')+/g) || [];
  const unq = (t) => t.replace(/^(["'])(.*)\1$/, '$2');
  const early = [];
  const rest = [];
  for (let i = 0; i < toks.length; i++) {
    const t = toks[i];
    const name = t.split('=')[0];
    if (['-r', '--require', '--import', '--loader', '--experimental-loader'].includes(name)) {
      if (t.includes('=')) early.push(name, unq(t.slice(t.indexOf('=') + 1)));
      else if (i + 1 < toks.length) { early.push(name, unq(toks[i + 1])); i++; }
    } else {
      rest.push(t);
    }
  }
  return { early, rest: rest.join(' ') };
}

async function main(argv) {
  const env0 = { ...process.env }; // the environment at session start (cache inputs are digested against it)
  const root = process.cwd();
  const { opts, rest } = session.parseArgs(argv);
  if (!opts.det) {
    const r = spawnSync(process.execPath, ['--test', ...rest.filter((a) => a !== '--test')], { stdio: 'inherit' });
    return r.status ?? 1;
  }
  const { flags, patterns } = parseNodeArgs(rest);
  if (has(flags, '--watch', '--watch-path')) throw new Error('detjs node-test: --watch is not supported under --det');
  const userIso = values(flags, '--test-isolation', '--experimental-test-isolation').pop() || 'process';
  const isolation = opts.cache ? 'process' : userIso;
  const found = findFiles(root, patterns, flags);
  if (found.error) { process.stderr.write(`${found.error}\n`); return 1; }
  let files = found.files;
  const shardV = values(flags, '--test-shard').pop();
  if (shardV) {
    const m = /^(\d+)\/(\d+)$/.exec(shardV);
    if (!m) throw new Error(`detjs node-test: --test-shard must be <index>/<total>, got ${shardV}`);
    files = files.filter((_, i) => i % Number(m[2]) === Number(m[1]) - 1);
  }
  const run = session.prepare(opts, root, 'node-test');
  const cfg = run.cfg;
  let keyed = files.map((f) => ({ f, fileId: path.relative(root, path.resolve(root, f)).split(path.sep).join('/') }));
  keyed.sort((a, b) => (a.fileId < b.fileId ? -1 : a.fileId > b.fileId ? 1 : 0));
  if (cfg.shuffle && cfg.controls.has('order')) keyed = native.shuffleIndices(keyed.length, cfg.orderSeed, '').map((i) => keyed[i]);
  // --det-order (src/repro.js): the listed files only, in the order of their first listed test (the tests of each
  // file are reduced to the listed ones by the facade, src/nodetest/facade.js)
  if (opts.order) {
    const repro = require('../repro');
    keyed = repro.orderFiles(keyed, repro.makePlan(repro.readOrder(path.resolve(opts.order))));
  }

  const nodeOptions = env0.NODE_OPTIONS;
  let pc = null;
  const notes = [];
  // parallel lanes (row JS-07): --det-workers, or node --test's own --test-concurrency when given on the command line;
  // a fixed plan (src/parallel.js), one driver per lane, each file still in its own process
  const parallel = require('../parallel');
  if (opts.plan) {
    opts.plan = path.resolve(opts.plan);
    if (opts.workers == null) opts.workers = String(parallel.readReplay(opts.plan).lanes.length);
  }
  const tc = values(flags, '--test-concurrency').pop();
  const want = parallel.resolveWorkers(opts, { workers: tc !== undefined ? parallel.workerCount(tc) : null, source: '--test-concurrency' });
  const par = { workers: want.workers, source: want.source, refused: null, plan: null, result: null };
  if (par.workers > 1) {
    const reasons = [];
    if (isolation === 'none') reasons.push('--test-isolation=none (every file in one process)');
    if (run.netMode === 'record') reasons.push('--det-record (one cassette per process)');
    if (opts.order || opts.collect) reasons.push('--det-order / --det-collect (one exact order)');
    if (reasons.length) { par.refused = reasons.join('; '); par.workers = 1; notes.push(`parallel refused, serial: ${par.refused}`); }
  }
  process.env.DETJS_WORKERS = String(par.workers);
  if (userIso === 'none' && opts.cache) notes.push('--test-isolation=none: under --det-cache every file runs in its own process (skipping a file must not change the context of another)');
  if (opts.cache && (opts.order || opts.collect)) throw new Error('detjs node-test: --det-cache cannot be combined with --det-order or --det-collect');
  if (opts.cache) {
    const { ProofSession } = require('../cache/proof');
    pc = new ProofSession(opts, root, 'node-test', run, env0);
    pc.installMain({ mainAnyReads: false });
    pc.setConfig(nodeTestConfigParts(root, flags, isolation, nodeOptions));
    if (has(flags, '--test-global-setup')) pc.noteProject('', 'a --test-global-setup module runs in the runner process, outside the capture');
    const skip = await pc.decide(keyed.map((k) => ({ fileId: k.fileId, project: '', key: k.fileId })));
    keyed = keyed.filter((k) => !skip.has(k.fileId));
  }
  const executed = keyed.map((k) => ({ fileId: k.fileId, part: controls.partName(k.fileId, '') }));
  if (par.workers > 1 && keyed.length > 1) {
    par.plan = parallel.makePlan(root, keyed.map((k) => k.fileId), par.workers, { replay: opts.plan ? parallel.readReplay(opts.plan) : null });
    parallel.writeRunPlan(run.dir, par.plan, 'node-test');
  }
  const iso = isolation === 'none'
    ? 'node:test isolation=none: every file in the driver process, files and tests one at a time'
    : 'node:test isolation=process: each file in its own process, one file at a time';
  const header = { runner: 'node-test', runnerVersion: process.version, isolation: iso };
  if (par.plan) {
    header.parallel = `parallel execution in ${par.plan.workers} lanes with a fixed plan (${par.source})`;
    header.isolation = 'node:test isolation=process: one file at a time per lane, each in its own process';
  }
  for (const l of session.header(run, opts, header)) process.stdout.write(`${l}\n`);
  for (const n of notes) process.stdout.write(`detjs: ${n}\n`);

  // the driver: the user's node flags (minus the ones it handles) after detjs' preload
  const childFlags = [];
  for (const f of flags) if (!OWN.has(f.name)) childFlags.push(...f.raw);
  const covFlags = has(flags, '--experimental-test-coverage') ? {
    coverage: true,
    coverageIncludeGlobs: values(flags, '--test-coverage-include'),
    coverageExcludeGlobs: values(flags, '--test-coverage-exclude'),
    lineCoverage: Number(values(flags, '--test-coverage-lines').pop() || 0),
    branchCoverage: Number(values(flags, '--test-coverage-branches').pop() || 0),
    functionCoverage: Number(values(flags, '--test-coverage-functions').pop() || 0),
  } : null;
  if (covFlags && !covFlags.coverageIncludeGlobs.length) delete covFlags.coverageIncludeGlobs;
  if (covFlags && !covFlags.coverageExcludeGlobs.length) delete covFlags.coverageExcludeGlobs;
  const timeoutV = values(flags, '--test-timeout').pop();
  const plan = {
    files: keyed.map((k) => k.f),
    isolation,
    reporters: values(flags, '--test-reporter'),
    destinations: values(flags, '--test-reporter-destination'),
    defaultReporter: Number(process.versions.node.split('.')[0]) >= 23 || process.stdout.isTTY ? 'spec' : 'tap',
    testNamePatterns: values(flags, '--test-name-pattern'),
    testSkipPatterns: values(flags, '--test-skip-pattern'),
    only: has(flags, '--test-only'),
    forceExit: has(flags, '--test-force-exit'),
    timeout: timeoutV ? Number(timeoutV) : null,
    coverage: covFlags,
    results: path.join(run.dir, 'node-test-results.json'),
  };
  const lanes = par.plan ? par.plan.lanes.map((l) => l.map((fileId) => keyed.find((k) => k.fileId === fileId).f)) : [plan.files];
  const driverEnv = { ...process.env, DETJS_NT_DRIVER: '1', DETJS_NT_ISOLATION: isolation };
  delete driverEnv.NODE_TEST_CONTEXT;
  // modules NODE_OPTIONS preloads would run before detjs' preload (their reads unseen): they move to the command
  // line after it; test processes get NODE_OPTIONS back for the processes they start
  const early = [];
  if (nodeOptions !== undefined) {
    driverEnv.DETJS_NT_NODE_OPTIONS = nodeOptions;
    const { early: e, rest: keep } = splitNodeOptions(nodeOptions);
    early.push(...e);
    driverEnv.NODE_OPTIONS = keep;
  }
  const preload = path.join(__dirname, 'preload.js');
  const driverArgs = ['--require', preload, ...early, ...childFlags, path.join(__dirname, 'driver.js')];
  let status = 0;
  let results = { files: {}, failed: false, unmapped: 0 };
  if (lanes.length === 1) {
    const planPath = path.join(run.dir, 'node-test-plan.json');
    fs.writeFileSync(planPath, JSON.stringify(plan));
    const r = spawnSync(process.execPath, driverArgs, { stdio: 'inherit', env: { ...driverEnv, DETJS_NT_PLAN: planPath }, cwd: root });
    status = r.status ?? 1;
    if (r.error) process.stderr.write(`detjs node-test: driver failed: ${r.error.message}\n`);
    try { results = JSON.parse(fs.readFileSync(plan.results, 'utf8')); } catch { results = null; /* none: every capture counts as failed */ }
  } else {
    // one driver per lane, at the same time; each reporter's output is kept apart and printed lane by lane
    const { spawn } = require('node:child_process');
    const outs = await Promise.all(lanes.map((laneFiles, i) => new Promise((resolve) => {
      const lp = { ...plan, files: laneFiles, results: path.join(run.dir, `node-test-results-${i}.json`) };
      const planPath = path.join(run.dir, `node-test-plan-${i}.json`);
      fs.writeFileSync(planPath, JSON.stringify(lp));
      const chunks = [];
      const ch = spawn(process.execPath, driverArgs, { stdio: ['ignore', 'pipe', 'pipe'], env: { ...driverEnv, DETJS_NT_PLAN: planPath }, cwd: root });
      ch.stdout.on('data', (d) => chunks.push(d));
      ch.stderr.on('data', (d) => chunks.push(d));
      ch.on('error', (e) => { chunks.push(Buffer.from(`detjs node-test: lane ${i + 1} driver failed: ${e.message}\n`)); });
      ch.on('close', (code) => resolve({ code: code ?? 1, out: Buffer.concat(chunks), results: lp.results }));
    })));
    for (const [i, o] of outs.entries()) {
      process.stdout.write(`detjs: lane ${i + 1}/${outs.length}: ${lanes[i].length} files\n`);
      process.stdout.write(o.out);
      if (o.code !== 0) status = o.code;
      let lr = null;
      try { lr = JSON.parse(fs.readFileSync(o.results, 'utf8')); } catch { lr = null; }
      if (!lr) { results = null; continue; }
      if (results) {
        Object.assign(results.files, lr.files);
        results.failed = results.failed || lr.failed;
        results.unmapped += lr.unmapped;
      }
    }
  }
  {
    // placement against the plan, hazards and the cost of serial (G-1458), parallel or not
    par.result = parallel.collect(root, run.dir, keyed.map((k) => k.fileId), par.plan, {
      shared: false, planned: { workers: par.workers, source: par.source, refused: par.refused },
    });
    for (const l of par.result.lines) process.stderr.write(`${l}\n`);
  }
  if (pc && par.result) pc.parallelFlags = par.result.flags;
  if (pc) {
    // a file is recorded as passed only when the runner saw it pass (its summary) and its process exited cleanly
    pc.captureFilter = (c) => {
      const fr = results && results.files[c.fileId];
      // (a file that does not use node:test has no summary of its own: its file-level test passed)
      const ok = Boolean(c.ok && results && !results.unmapped && fr && fr.fail === 0 && (fr.summary === true || (fr.summary === null && fr.pass > 0)));
      return { ...c, ok };
    };
    for (const l of pc.finishSync()) process.stdout.write(`${l}\n`);
    await pc.finish();
  }
  const { lines } = session.finish(run, opts, executed, {
    runner: 'node-test', runner_version: process.version, isolation: header.isolation, serial: !par.plan, cli_args: rest,
    // What the order comparison may scope by (`isolation_unit`, read by crates/detpy-core/src/verify.rs
    // `Predecessors`). node:test's own `run({ isolation: 'process' })` -- which src/nodetest/driver.js passes and
    // this shell therefore knows it asked for -- runs every test file in its own fresh process, so no in-process
    // state crosses a file boundary and a test's only meaningful predecessors are the earlier tests of its own
    // file. A test's file is the part of its nodeid before the first `::` (src/fileproc.js idFor:
    // `<fileId>::<suite>::<test>`, ` #n` for a repeated name).
    //
    // Why it matters: without it a serial node:test trace is one undivided sequence, so comparing a subset run (a
    // shard) against the full run reports every test whose file moved as order-divergent although no test ran
    // differently (MEASURED on simple-statistics, exam run 44958011775: 151 order / 125 missing on shard 1/2).
    // Absent means today's whole-run scoping, unchanged: this flag alone changes no verdict until the verifier
    // reads it, which is Block 1's side (docs/LIMITS.md P4).
    //
    // Deliberately NOT set under `--test-isolation=none`: every file then shares the driver process and the claim
    // would be false. Deliberately not set for Vitest or Jest: a fresh worker per file looks like the same
    // guarantee, but that a worker is never reused across files in those pools is not measured here, and
    // declaring it unmeasured is the kind of green on a doubt this engine exists to refuse.
    ...(isolation === 'none' ? {} : { isolation_unit: 'per-file' }),
    ...(par.result ? { parallel: par.result.meta } : {}),
  });
  for (const l of lines) process.stdout.write(`${l}\n`);
  if (status === 0 && results && results.failed) status = 1;
  return status;
}

module.exports = { main, parseNodeArgs, findFiles, splitNodeOptions };
