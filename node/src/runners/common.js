'use strict';
// Process-per-file runner shells (`detjs bun-test`, `detjs deno-test`): the main-process side they share.
//
// The test runtime (Bun, Deno) is not Node, but it loads the same detjs modules and the same native core
// (crates/detpy-node through Node-API, see docs/runners/bun.md and deno.md): its preload installs the Level 0
// controls and the capture, brackets every test, and writes the trace part (<run dir>/parts) and, under
// --det-cache, the capture of its file (<run dir>/cache) in the formats the Vitest and Jest shells write. This
// process (Node) does everything else with the shared code: options (session.js), the reuse decision and the
// records (cache/proof.js ProofSession), receipts, the summary and the merged trace.
//
// Unit of execution: one test file per runtime process, in detjs' order (sorted paths, or the core's reproducible
// shuffle with --det-seed). Both runtimes share state between the files of one process (Bun: one global object for
// every file; Deno: one OS process, so the environment, the working directory and written files), so a file never
// runs in a context the reference run did not have (docs/ALL-RUNNERS.md, "a fresh process per file").
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const session = require('../session');
const native = require('../native');
const controls = require('../controls');

/** An executable on PATH (or the value of `envName`), or null. */
function findBinary(name, envName) {
  const fromEnv = process.env[envName];
  if (fromEnv) return fromEnv;
  for (const dir of String(process.env.PATH || '').split(path.delimiter)) {
    if (!dir) continue;
    const p = path.join(dir, name);
    try {
      fs.accessSync(p, fs.constants.X_OK);
      if (fs.statSync(p).isFile()) return p;
    } catch { /* next */ }
  }
  for (const p of [path.join(require('node:os').homedir(), `.${name}`, 'bin', name)]) {
    try { fs.accessSync(p, fs.constants.X_OK); return p; } catch { /* none */ }
  }
  return null;
}

/**
 * Split runner arguments into options and positional paths/filters. `valueFlags`: options that take a value in
 * the next argument when written without `=`.
 */
function splitArgs(rest, valueFlags) {
  const options = [];
  const positional = [];
  for (let i = 0; i < rest.length; i++) {
    const a = rest[i];
    if (a === '--') { positional.push(...rest.slice(i + 1)); break; }
    if (a.startsWith('-')) {
      options.push(a);
      if (!a.includes('=') && valueFlags.has(a) && i + 1 < rest.length) options.push(rest[++i]);
      continue;
    }
    positional.push(a);
  }
  return { options, positional };
}

/** Value of option `names` in `options` (last one wins), or undefined. */
function optionValue(options, names) {
  let v;
  for (let i = 0; i < options.length; i++) {
    const a = options[i];
    for (const n of names) {
      if (a === n && i + 1 < options.length && !options[i + 1].startsWith('-')) v = options[i + 1];
      else if (a.startsWith(`${n}=`)) v = a.slice(n.length + 1);
    }
  }
  return v;
}

/** Remove options `names` (and their values) from `options`. */
function dropOptions(options, names, valueFlags) {
  const out = [];
  for (let i = 0; i < options.length; i++) {
    const a = options[i];
    const base = a.includes('=') ? a.slice(0, a.indexOf('=')) : a;
    if (names.has(base)) {
      if (!a.includes('=') && valueFlags.has(base) && i + 1 < options.length && !options[i + 1].startsWith('-')) i++;
      continue;
    }
    out.push(a);
  }
  return out;
}

/** File order: sorted, or the core's reproducible shuffle with the seed (same permutation as the other shells). */
function orderFiles(fileIds, cfg) {
  const sorted = [...fileIds].sort();
  if (cfg.shuffle && cfg.controls.has('order')) return native.shuffleIndices(sorted.length, cfg.seed, '').map((i) => sorted[i]);
  return sorted;
}

/** Seed for the runner's own ordering of the tests inside one file (derived by the core from the run's seed). */
function fileSeed(cfg, fileId) {
  return BigInt.asUintN(31, BigInt(native.deriveSeed(cfg.seed, `${fileId}\0tests`))).toString();
}

/** Capture files written for one test file (by its runtime process). */
function captureFiles(run, fileId) {
  const dir = path.join(run.dir, 'cache');
  const prefix = controls.partName(fileId, '').replace(/\.jsonl$/, '');
  let names = [];
  try { names = fs.readdirSync(dir); } catch { return []; }
  return names.filter((n) => n.startsWith(`${prefix}-`) && n.endsWith('.json')).map((n) => path.join(dir, n));
}

/**
 * After the process of a test file ended: its capture is ok only when the runtime itself reported success (exit
 * status 0). Anything the preload did not see failing (a timeout, a failed hook, a leak the runner's sanitizer
 * found, an unhandled error between tests) makes the whole file a failure, which is never reused. `extra(capture)`
 * may add items (Deno: the module graph and the audit of the runtime's permission checks).
 */
function settleCapture(run, fileId, status, extra) {
  const files = captureFiles(run, fileId);
  for (const f of files) {
    let c;
    try { c = JSON.parse(fs.readFileSync(f, 'utf8')); } catch { fs.rmSync(f, { force: true }); continue; }
    c.ok = Boolean(c.ok) && status === 0;
    c.status = status;
    if (extra) extra(c);
    fs.writeFileSync(f, JSON.stringify(c));
  }
  return files.length;
}

/** Merge JUnit XML reports (one per file process) into one file: the content of each part's <testsuites>. */
function mergeJunit(parts, out, name) {
  const bodies = [];
  const tot = { tests: 0, failures: 0, errors: 0, skipped: 0, time: 0 };
  for (const p of parts) {
    let x;
    try { x = fs.readFileSync(p, 'utf8'); } catch { continue; }
    const open = /<testsuites\b([^>]*)>/.exec(x);
    const close = x.lastIndexOf('</testsuites>');
    if (!open || close < 0) continue;
    bodies.push(x.slice(open.index + open[0].length, close).trim());
    for (const k of Object.keys(tot)) {
      const r = new RegExp(`\\b${k}="([^"]*)"`).exec(open[1]);
      if (r) tot[k] += Number(r[1]) || 0;
    }
  }
  fs.mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
  fs.writeFileSync(out, `<?xml version="1.0" encoding="UTF-8"?>\n<testsuites name="${name}" tests="${tot.tests}" failures="${tot.failures}" `
    + `errors="${tot.errors}" skipped="${tot.skipped}" time="${tot.time}">\n${bodies.join('\n')}\n</testsuites>\n`);
}

/**
 * Run the files of a --det session, one runtime process per file.
 *
 * @param {object} p
 *   runner, runnerVersion: names for the header and the trace;
 *   root, opts, run (session.prepare), pc (ProofSession or null);
 *   fileIds: test files (paths relative to root) in the order to run;
 *   spawnFile(fileId, index, env) -> {status} (synchronous);
 *   isolation: text for the header and the trace; meta: trace metadata;
 *   extra(capture, fileId): optional, see settleCapture.
 */
async function runFiles(p) {
  const { run, opts, pc } = p;
  let ordered = p.fileIds;
  let skip = new Set();
  if (pc) {
    if (!ordered.length) pc.noTestsFound = true;
    skip = await pc.decide(ordered.map((f) => ({ fileId: f, project: '', key: f })));
  }
  for (const l of session.header(run, opts, { runner: p.runner, runnerVersion: p.runnerVersion, isolation: p.isolationShort || 'process per file' })) {
    process.stdout.write(`${l}\n`);
  }
  const executed = [];
  let failed = 0;
  let ran = 0;
  for (let i = 0; i < ordered.length; i++) {
    const f = ordered[i];
    if (skip.has(f)) continue;
    const env = { DETJS_FILE: f };
    const r = p.spawnFile(f, i, env);
    const status = r.status === null || r.status === undefined ? 1 : r.status;
    ran++;
    if (status !== 0) failed++;
    executed.push({ fileId: f, part: controls.partName(f, '') });
    if (pc) settleCapture(run, f, status, p.extra ? (c) => p.extra(c, f, r) : null);
  }
  ordered = executed;
  if (p.afterRun) p.afterRun();
  let lines = [];
  if (pc) {
    lines = await pc.finish();
  }
  const fin = session.finish(run, opts, ordered, {
    runner: p.runner, runner_version: p.runnerVersion, isolation: p.isolation, serial: true, cli_args: p.cliArgs || [], ...(p.meta || {}),
  });
  for (const l of [...lines, ...fin.lines]) process.stdout.write(`${l}\n`);
  if (!p.fileIds.length) {
    process.stderr.write(`detjs ${p.runner}: no test files found\n`);
    return 1;
  }
  process.stdout.write(`detjs ${p.runner}: ${ran} files ran (${failed} failed), ${p.fileIds.length - ran} reused\n`);
  return failed ? 1 : 0;
}

/** Digest of a file, or a marker (missing files are configuration too). */
function fileDigestOr(p) {
  if (!p) return '';
  return native.fileDigest(p) || `missing:${p}`;
}

/** spawnSync with inherited output, returning {status}. */
function runInherit(cmd, args, opts) {
  const r = spawnSync(cmd, args, { stdio: 'inherit', ...opts });
  if (r.error) process.stderr.write(`detjs: ${cmd}: ${r.error.message}\n`);
  return { status: r.status === null ? (r.signal ? 128 : 1) : r.status, signal: r.signal };
}

module.exports = {
  findBinary, splitArgs, optionValue, dropOptions, orderFiles, fileSeed, captureFiles, settleCapture, mergeJunit, runFiles,
  fileDigestOr, runInherit,
};
