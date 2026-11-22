'use strict';
// P1 (docs/LIMITS.md section 10, row JS-07): a first parallel run must never report a failure a serial run does
// not.
//
// The lanes are planned before anything is known about what the test files touch, so a path or a fixed port that
// two files share is found only AFTER the run, from the recorded footprints (src/parallel.js `hazards`). Until this
// wrapper the first run's outcome had already been reported by then and only the NEXT plan was corrected: the
// signature was "run 1 red, runs 2 and later green", which is exactly the retry-flakiness this engine exists to
// remove. `docs/PARALLEL-PROOF-DESIGN.md` P6 lists "0 new failures caused by the split" as an acceptance
// criterion, and the brief's own rule is "if you cannot prove a placement is safe, run the test the safe way".
//
// What this does: run the runner once as a child, exactly as it runs today. If that run reported cross-worker
// hazards, run the files those hazards name again in ONE lane (`--det-workers=1`, which always wins over the
// runner's own worker options -- src/parallel.js `resolveWorkers`, precedence rule 1), so they cannot interfere;
// the re-run's outcomes are then the ones reported, in the exit status and in the trace.
//
// The shape is src/isolate.js's, which already re-executes `bin/detjs.js` as a child runner session and merges the
// resulting records with `native.mergeTraces`; the argument composition below is the same one, for the same reason
// (it is the form proven to work for all three runners).
//
// Cost: one extra node process per `--det` run of a wrapped runner (the wrapper itself), and in the common case
// not even that, because bin/detjs.js already re-executes itself to pin TZ and the locale. The second pass is paid
// only when a hazard is found, and only for the files it names.
//
// Default-deny: the re-run clears a red only when it can account for every affected test. If its trace cannot be
// read, or an affected test left no record in it, the first run's status stands and the reason is printed. A
// re-run that cannot prove the files are clean must never turn a red into a green.
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const native = require('./native');
const exitStatus = require('./exit-status');

const BIN = path.join(__dirname, '..', 'bin', 'detjs.js');

// The runners whose `--det` runs use lanes (src/parallel.js). Playwright reports its placement as not controlled
// and the launch-only shells are serial, so neither can raise a cross-worker hazard.
const WRAPPED = new Set(['vitest', 'jest', 'node-test']);

// detjs options of the first pass the second pass must not inherit as they are:
//   * `--det-trace`/`--det-compare`/`--det-order`/`--det-outcomes`: they name files of the user's that the subset
//     run must not overwrite -- the merged trace below is what the user asked for;
//   * `--det-workers`/`--det-plan`: the second pass is one lane by construction, and a replayed plan would put the
//     conflicting files back in separate lanes;
//   * `--det-cache*`: the re-run has to really run the files. Reusing a recorded result would defeat the whole
//     point, and the entries of the affected files are in any case flagged `cross-worker` and never reused;
//   * `--det-isolate`: a per-test session has one file and one test, so it has no lanes to fix.
const OWN = /^--det-(trace|compare|order|outcomes|workers|plan|cache|cache-verify|cache-real-clock|cache-receipts|cache-summary|cache-max-age|isolate)(=|$)/;
// of those, the ones whose value is a separate argument (session.js `takes`)
const OWN_VALUE = new Set(['--det-trace', '--det-compare', '--det-order', '--det-outcomes', '--det-workers',
  '--det-plan', '--det-cache', '--det-cache-receipts', '--det-cache-summary', '--det-cache-max-age']);

const PASSED = new Set(['passed', 'skipped', 'todo']);

/**
 * The test file a detjs test id belongs to: `<fileId>::<suite>::<test>` (src/fileproc.js `idFor`), or
 * `<fileId>@@<project>::...` in a named Vitest project (src/vitest/shell.js `qualified`): the project is dropped, so
 * the id matches its hazard file (B4 of the spec "Engine P0: no false green"; before, `fileOf` kept
 * `<fileId>@@<project>`, nothing matched, and the re-run reported "0 failed of 0 test(s)").
 */
function fileOf(nodeid) {
  return String(nodeid).split('::', 1)[0].split('@@', 1)[0];
}

/**
 * The test file of a hazard's side: a lane label is `<project>|<fileId>` in a named Vitest project or a Jest project
 * with a displayName (src/vitest/shell.js `__open`, src/jest/runner.js `label`), else the file id.
 */
function labelFile(label) {
  const s = String(label);
  const bar = s.indexOf('|');
  return bar >= 0 ? s.slice(bar + 1) : s;
}

function readTrace(p) {
  try {
    const lines = fs.readFileSync(p, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
    const header = lines.find((l) => l.type === 'header');
    if (!header) return null;
    return { header, tests: lines.filter((l) => l.type === 'test') };
  } catch { return null; }
}

/** Whether this command should be wrapped at all: a `--det` run of a runner that uses lanes, not already a pass. */
function shouldWrap(cmd, argv, env = process.env) {
  if (!WRAPPED.has(cmd)) return false;
  if (env.DETJS_HAZARD_RERUN === '1') return false; // we are one of the two passes
  const det = argv.includes('--det') || env.DETJS === '1' || env.DETJS === 'true';
  if (!det || argv.includes('--no-det')) return false;
  // one lane was asked for explicitly: there are no lanes to conflict, so no hazard is possible
  if (argv.some((a) => a === '--det-workers=1' || a === '--det-workers' && argv[argv.indexOf(a) + 1] === '1')) return false;
  if (argv.some((a) => /^--det-isolate(=(1|true))?$/.test(a))) return false;
  return true;
}

/** The files named by the hazards of a finished run, in a stable order (project labels reduced to their file). */
function hazardFiles(header) {
  const par = header && header.meta && header.meta.parallel;
  const hz = (par && par.hazards) || [];
  return [...new Set(hz.flatMap((h) => [h.a, h.b]).filter(Boolean).map(labelFile))].sort();
}

/**
 * Whether the one-lane re-run accounted for the first pass's tests of the hazard files (B3 of the spec "Engine P0:
 * no false green"). Pure: no file system, no process.
 *   firstTests   the first pass's test records ([{nodeid, outcome}])
 *   rerunTests   the re-run's test records, or null when its trace is missing or unreadable
 *   files        the hazard files (hazardFiles)
 * Returns {want, unaccounted, complete, notProven, notProvenFiles}:
 *   want            nodeids of the first pass's tests of the hazard files
 *   unaccounted     those the re-run has no record of (all of them when its trace is missing)
 *   complete        the re-run's trace exists and accounts for every wanted test
 *   notProven       = unaccounted: each such test is NOT PROVEN (appendix point 4: also when the re-run accounted
 *                   for only some of them)
 *   notProvenFiles  [{file, cause}], one per hazard file with a NOT PROVEN test, in `files` order
 */
function accountRerun(firstTests, rerunTests, files) {
  const set = new Set(files);
  const want = (firstTests || []).filter((r) => set.has(fileOf(r.nodeid))).map((r) => r.nodeid);
  const got = new Set((rerunTests || []).map((r) => r.nodeid));
  const unaccounted = want.filter((id) => !got.has(id));
  const complete = Array.isArray(rerunTests) && unaccounted.length === 0;
  const notProvenFiles = [];
  for (const f of files) {
    const mine = want.filter((id) => fileOf(id) === f);
    const lost = unaccounted.filter((id) => fileOf(id) === f);
    if (!lost.length) continue;
    const cause = !Array.isArray(rerunTests)
      ? 'its trace is missing'
      : `it ran ${mine.length - lost.length} of its ${mine.length} test(s)`;
    notProvenFiles.push({ file: f, cause });
  }
  return { want, unaccounted, complete, notProven: unaccounted, notProvenFiles };
}

/**
 * The runner code of the wrapper's final decision (exit-status.js `runExit`, appendix point 8): a pass's code
 * counts when it is not explained by test outcomes -- pass 1's when it had no failed test (or was 2: a detjs or
 * runner error), pass 2's always (its failed tests are in the reported records when the re-run is complete, and the
 * run is NOT PROVEN when it is not), and 1 when the re-run left no trace at all.
 */
function wrapperRunnerCode(status1, status2, firstFailed, rerunTraced) {
  if (status1 === 2 || status2 === 2) return 2;
  if (status1 !== 0 && firstFailed === 0) return status1;
  if (status2 !== 0) return status2;
  if (!rerunTraced) return 1;
  return 0;
}

/** The first pass's arguments, less the ones the second pass must not inherit. */
function rerunArgs(argv) {
  const out = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (OWN.test(a)) { if (OWN_VALUE.has(a)) i++; continue; }
    out.push(a);
  }
  return out;
}

async function main(cmd, argv) {
  const session = require('./session');
  const { opts } = session.parseArgs(argv);
  const root = process.cwd();
  // the trace the user asked for; the shells' own default when they did not (src/isolate.js uses the same one)
  const tracePath = path.resolve(root, opts.trace || path.join('.detjs', 'trace.jsonl'));
  const childEnv = { ...process.env, DETJS_HAZARD_RERUN: '1' };
  // which pass a child is (src/session.js: pass 2, and pass 1 when it found a hazard, do not print the status line;
  // the merged trace this wrapper writes is then the final one and the wrapper prints it -- B7)
  const env1 = { ...childEnv, DETJS_HAZARD_PASS: '1' };
  const env2 = { ...childEnv, DETJS_HAZARD_PASS: '2' };

  // ---- pass 1: the run exactly as it is today, straight to the user's terminal and the user's files ----
  const p1 = spawnSync(process.execPath, [...process.execArgv, BIN, cmd, ...argv], { cwd: root, env: env1, stdio: 'inherit' });
  if (p1.signal) return { signal: p1.signal };
  const status1 = p1.status ?? 1;

  const t1 = readTrace(tracePath);
  const affected = t1 ? hazardFiles(t1.header) : [];
  if (!affected.length) return { status: status1 }; // the ordinary case: nothing re-run, nothing changed

  // ---- a hazard was reported: the files it names run again, together, in one lane ----
  const bad1 = t1.tests.filter((r) => !PASSED.has(r.outcome));
  process.stderr.write(`detjs: parallel: ${affected.length} file(s) named by a cross-worker hazard run again in one lane, `
    + `because a placement must never decide an outcome: ${affected.join(', ')}\n`);

  const work = path.join(root, '.detjs', `hazard-rerun-${process.pid}`);
  fs.rmSync(work, { recursive: true, force: true });
  fs.mkdirSync(work, { recursive: true });
  const t2path = path.join(work, 'rerun.jsonl');
  // The argument form of src/isolate.js: the user's own arguments, then the files. Jest needs --runTestsByPath for
  // paths to be paths; Vitest and node:test take them as they are.
  //
  // node:test needs the user's own file patterns dropped first. Its patterns and my paths are a UNION, so
  // `t/*.test.js` plus the explicit path of a file in it makes node:test run that file TWICE -- measured: the
  // merged trace held every record of the affected files twice, and the second copy of a file had seen the state
  // the first one left. `parseNodeArgs` is the same splitter the node:test shell itself uses, so flags that take a
  // separate value (`--test-reporter foo`) keep theirs instead of being read as patterns.
  const fileArgs = cmd === 'jest'
    ? ['--runTestsByPath', ...affected.map((f) => path.resolve(root, f))]
    : affected.map((f) => path.resolve(root, f));
  const dropPatterns = (a) => {
    if (cmd !== 'node-test') return a;
    try {
      const { parseNodeArgs } = require('./nodetest/cli');
      const { patterns } = parseNodeArgs(a);
      const drop = new Set(patterns);
      return a.filter((x) => !drop.has(x));
    } catch { return a; }
  };
  // Vitest's subcommand is positional: drop whatever the user wrote (`run`, `watch`, `dev`) and always re-run with
  // `run`, as src/isolate.js does. Appending `run` to a `watch` would have produced `watch ... run`.
  const kept = dropPatterns(rerunArgs(argv));
  const args2 = cmd === 'vitest'
    ? [...process.execArgv, BIN, cmd, 'run', ...(['run', 'watch', 'dev'].includes(kept[0]) ? kept.slice(1) : kept),
      '--det-workers=1', `--det-trace=${t2path}`, ...fileArgs]
    : [...process.execArgv, BIN, cmd, ...kept, '--det-workers=1', `--det-trace=${t2path}`, ...fileArgs];
  const p2 = spawnSync(process.execPath, args2, { cwd: root, env: env2, stdio: 'inherit' });
  if (p2.signal) { fs.rmSync(work, { recursive: true, force: true }); return { signal: p2.signal }; }
  const status2 = p2.status ?? 1;
  const t2 = readTrace(t2path);

  // ---- the re-run's records replace the first pass's for those files, and are what gets reported ----
  const set = new Set(affected);
  // every affected test the first pass saw must be accounted for by the re-run, or the red stands; each one it did
  // not account for is NOT PROVEN (B3)
  const acc = accountRerun(t1.tests, t2 ? t2.tests : null, affected);
  const { want, unaccounted, complete } = acc;

  let records;
  if (complete) {
    const byFile = new Map();
    // one record per nodeid: the first the re-run wrote. A runner that ran a file twice (see dropPatterns above)
    // must not put two records of one test in the merged trace, whatever the argument handling did.
    const seen = new Set();
    for (const r of t2.tests) {
      if (seen.has(r.nodeid)) continue;
      seen.add(r.nodeid);
      const f = fileOf(r.nodeid);
      if (!byFile.has(f)) byFile.set(f, []);
      byFile.get(f).push(r);
    }
    const spliced = new Set();
    records = [];
    for (const r of t1.tests) {
      const f = fileOf(r.nodeid);
      if (!set.has(f)) { records.push(r); continue; }
      if (spliced.has(f)) continue; // its records went in at the file's first position
      spliced.add(f);
      records.push(...(byFile.get(f) || []));
    }
    // a file the re-run reports that the first pass never did (it died in its lane before recording)
    for (const [f, rs] of byFile) if (!spliced.has(f)) records.push(...rs);
  } else {
    records = t1.tests;
    process.stderr.write(`detjs: parallel: the one-lane re-run could not account for ${t2 ? `${unaccounted.length} test(s) of the affected files` : 'its own trace'}`
      + `; the first run's result stands and nothing was cleared${t2 && unaccounted.length ? ` (first: ${unaccounted[0]})` : ''}\n`);
  }
  for (const { file, cause } of acc.notProvenFiles) {
    process.stderr.write(`detjs: parallel: NOT PROVEN ${file}: the one-lane re-run did not account for its tests (${cause})\n`);
  }
  // B7: the counts of the final trace, in its header and on one status line, and the exit decision on them
  const status = exitStatus.countStatus(records, acc.notProven);

  // the merged trace, written where the user asked for it
  const order = records.map((r) => r.nodeid);
  const pdir = path.join(work, 'parts');
  fs.mkdirSync(pdir, { recursive: true });
  const parts = records.map((r, i) => {
    const p = path.join(pdir, `${String(i).padStart(6, '0')}.jsonl`);
    fs.writeFileSync(p, `${JSON.stringify({ type: 'header', format: 'detpy-trace', version: 1, encoding: 2, meta: {}, order: [] })}\n${JSON.stringify(r)}\n`);
    return p;
  });
  const meta = { ...(t1.header.meta || {}) };
  // what was done and why, so the trace says it and `verify` and the reviewer can see it
  meta.hazard_rerun = {
    files: affected,
    hazards: ((t1.header.meta && t1.header.meta.parallel && t1.header.meta.parallel.hazards) || [])
      .map((h) => ({ kind: h.kind, what: h.what, a: h.a, b: h.b })),
    reported: complete ? 'one-lane re-run' : 'first run (the re-run was not complete)',
    complete,
    unaccounted,
    not_proven: acc.notProvenFiles,
    first_run_failed: bad1.map((r) => r.nodeid),
  };
  meta.status = status;
  fs.mkdirSync(path.dirname(tracePath), { recursive: true });
  const res = native.mergeTraces(parts, tracePath, JSON.stringify(meta), order);

  process.stderr.write(`${exitStatus.statusLine(status)}\n`);
  const badFinal = records.filter((r) => !PASSED.has(r.outcome));
  const cleared = bad1.filter((r) => set.has(fileOf(r.nodeid)) && !badFinal.some((x) => x.nodeid === r.nodeid));
  process.stdout.write(`detjs: trace ${path.relative(root, tracePath)}: ${res.nTests} tests, order digest ${res.orderDigest}`
    + ` (${affected.length} file(s) re-run in one lane)\n`);
  if (complete) {
    process.stdout.write(`detjs: parallel: the one-lane re-run is what is reported for ${affected.join(', ')}:`
      + ` ${badFinal.filter((r) => set.has(fileOf(r.nodeid))).length} failed of ${want.length} test(s)`
      + `${cleared.length ? `; ${cleared.length} failure(s) the lanes had caused are gone: ${cleared.slice(0, 5).map((r) => r.nodeid).join(', ')}${cleared.length > 5 ? ` (+${cleared.length - 5})` : ''}` : ''}\n`);
  }
  fs.rmSync(work, { recursive: true, force: true });

  // The status (B1, src/exit-status.js). A green is only ever given when the re-run accounted for everything: an
  // unaccounted test is NOT PROVEN, which is exit 1.
  return { status: exitStatus.runExit({ ...status, runnerCode: wrapperRunnerCode(status1, status2, bad1.length, Boolean(t2)) }) };
}

module.exports = { main, shouldWrap, hazardFiles, rerunArgs, fileOf, labelFile, accountRerun, wrapperRunnerCode };
