'use strict';
// P1 (docs/LIMITS.md section 10, row JS-07): the trace of a first parallel run reports what a serial run of the
// conflicting files shows; its exit code is never lowered below the first run's (Default-deny below).
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
// the re-run's outcomes replace the first run's records of those files in the trace. The exit code is the first
// run's or higher: the re-run can raise it (a failure that recurs, a NOT PROVEN test), never lower it.
//
// The shape is src/isolate.js's, which already re-executes `bin/detjs.js` as a child runner session and merges the
// resulting records with `native.mergeTraces`; the argument composition below is the same one, for the same reason
// (it is the form proven to work for all three runners).
//
// Cost: one extra node process per `--det` run of a wrapped runner (the wrapper itself), and in the common case
// not even that, because bin/detjs.js already re-executes itself to pin TZ and the locale. The second pass is paid
// only when a hazard is found, and only for the files it names.
//
// Default-deny: the re-run's outcomes replace the first pass's records of the hazard files in the trace when it
// accounts for every affected test; if its trace cannot be read, or an affected test left no record in it, the first
// run's records stay and every unaccounted test is NOT PROVEN (exit 1). The exit code is never lowered: a red first
// pass stays red whatever the re-run shows (wrapperRunnerCode), so no re-run can turn a red into a green.
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
// The runners' own file selectors: the second pass runs exactly the hazard files it is given. A shard, a changed-
// files or related-files filter could drop one of them -- and a hazard file that failed to load in the first pass
// has no test record to miss, so its absence would go unnoticed (gstack /review, pass 3).
const SELECT = /^(--shard|--changed|--changedSince|--related|--findRelatedTests|--onlyChanged|-o|--lastCommit|--onlyFailures|-f|--watchAll|--watch)(=|$)/;
const SELECT_VALUE = new Set(['--shard', '--changed', '--changedSince', '--related']);

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

/**
 * A trace, streamed (P0 big trace: a 1.2 GB trace does not fit in one JavaScript string): the header in full, and per
 * test only `{nodeid, outcome, never_started, offset, length}` -- `never_started`: its events hold a
 * `sched.never_started` event (B5); `offset`/`length`: its raw line in the file, so a record is copied byte for byte
 * (writeRecordParts) instead of being kept in memory. THROWS when the file cannot be read or a line is not JSON;
 * returns null when it has no header.
 */
function readTrace(p) {
  let header = null;
  const tests = [];
  require('./trace-lines').forEachLine(p, (line, i, offset, length) => {
    if (!line) return;
    const o = JSON.parse(line);
    if (o.type === 'header') { if (!header) header = o; return; }
    if (o.type !== 'test') return;
    const neverStarted = (o.events || []).some((e) => e && e.o === 'sched.never_started');
    tests.push({ nodeid: o.nodeid, outcome: o.outcome, never_started: neverStarted, offset, length });
  });
  if (!header) return null;
  return { header, tests };
}

/** readTrace, with null for a trace that cannot be read (pass 2: today's rule, NOT PROVEN, exit 1). */
function readTraceOrNull(p) {
  try { return readTrace(p); } catch { return null; }
}

/**
 * Write each record as a one-record part under `pdir` for native.mergeTraces: the header line, then the record's
 * raw line copied byte for byte from its trace (`r.src`: 1 = t1Path, 2 = t2Path; `r.offset`, `r.length` from
 * readTrace). Returns the part paths in order.
 */
function writeRecordParts(records, t1Path, t2Path, pdir) {
  const { readLineBytes } = require('./trace-lines');
  fs.mkdirSync(pdir, { recursive: true });
  const fds = { 1: fs.openSync(t1Path, 'r'), 2: t2Path && fs.existsSync(t2Path) ? fs.openSync(t2Path, 'r') : null };
  const head = Buffer.from(`${JSON.stringify({ type: 'header', format: 'detpy-trace', version: 1, encoding: 2, meta: {}, order: [] })}\n`);
  const nl = Buffer.from('\n');
  try {
    return records.map((r, i) => {
      const p = path.join(pdir, `${String(i).padStart(6, '0')}.jsonl`);
      const fd = fds[r.src];
      if (fd === null || fd === undefined) throw new Error(`detjs: parallel: record ${r.nodeid} has no source trace (${r.src})`);
      fs.writeFileSync(p, Buffer.concat([head, readLineBytes(fd, r.offset, r.length), nl]));
      return p;
    });
  } finally {
    for (const fd of Object.values(fds)) if (fd !== null) fs.closeSync(fd);
  }
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
  // a record detjs wrote for a test that never started (B5, controls.recordNeverStarted) is not a re-run of it
  // (readTrace computes it while streaming: `never_started`; a record with its events, as the unit tests give, is
  // read the same way)
  const ran = (r) => !(r.never_started || (r.events || []).some((e) => e && e.o === 'sched.never_started'));
  const got = new Set((rerunTests || []).filter(ran).map((r) => r.nodeid));
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
 * The runner code of the wrapper's final decision (exit-status.js `runExit`, appendix point 8). Default-deny
 * (founder decision of 2026-11-23, after four gstack /review rounds): the re-run may RAISE the first pass's code,
 * never lower it. Pass 1's exit code is one number that cannot say why it is red -- a hazard failure, a file that
 * failed to load, a coverage threshold, a global teardown, a file the runner failed after its tests ran -- and
 * every rule that tried to tell those apart left a way to a false green. So a red first pass stays red: 2 when
 * either pass returned 2 (a detjs or runner error), else pass 1's code, else pass 2's, else 1 when the re-run left
 * no trace. A lane-caused failure can therefore end red (a false red, the safe side); it never ends green.
 */
function wrapperRunnerCode(status1, status2, rerunTraced) {
  if (status1 === 2 || status2 === 2) return 2;
  if (status1 !== 0) return status1;
  if (status2 !== 0) return status2;
  if (!rerunTraced) return 1;
  return 0;
}

/** The identity of the trace file (null when absent): a trace pass 1 did not write must never be read as its own. */
function traceStamp(p) {
  try { const s = fs.statSync(p, { bigint: true }); return `${s.ino}:${s.size}:${s.mtimeNs}`; } catch { return null; }
}

/** The first pass's arguments, less the ones the second pass must not inherit. */
function rerunArgs(argv) {
  const out = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (OWN.test(a)) { if (OWN_VALUE.has(a)) i++; continue; }
    if (SELECT.test(a)) { if (SELECT_VALUE.has(a) && i + 1 < argv.length && !String(argv[i + 1]).startsWith('-')) i++; continue; }
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
  // P2 Phase B timing (DETJS_PHASES=1): both passes append to the phases file of the user's trace
  const phases = require('./phases');
  if (process.env.DETJS_PHASES === '1') {
    process.env.DETJS_PHASES_FILE = `${tracePath}.phases.jsonl`;
    fs.rmSync(process.env.DETJS_PHASES_FILE, { force: true });
    phases.mark('wrapper_start');
  }
  const childEnv = { ...process.env, DETJS_HAZARD_RERUN: '1' };
  // which pass a child is (src/session.js: pass 2, and pass 1 when it found a hazard, do not print the status line;
  // the merged trace this wrapper writes is then the final one and the wrapper prints it -- B7)
  const env1 = { ...childEnv, DETJS_HAZARD_PASS: '1' };
  const env2 = { ...childEnv, DETJS_HAZARD_PASS: '2' };

  // ---- pass 1: the run exactly as it is today, straight to the user's terminal and the user's files ----
  const before = traceStamp(tracePath);
  const p1 = spawnSync(process.execPath, [...process.execArgv, BIN, cmd, ...argv], { cwd: root, env: env1, stdio: 'inherit' });
  if (p1.signal) return { signal: p1.signal };
  const status1 = p1.status ?? 1;

  // a trace pass 1 did not write (it stopped before writing one, and an earlier run's is still there) is not read:
  // its hazards and failures are another run's, and clearing pass 1's red with them would be a false green
  const after = traceStamp(tracePath);
  let t1 = null;
  if (after !== null && after !== before) {
    let why = 'it has no header';
    try { t1 = readTrace(tracePath); } catch (e) { why = e && e.message; }
    if (!t1) {
      // P0 big trace: pass 1 wrote a trace this process cannot read (malformed, a line over the limit, a read
      // error): its hazards and failures are unknown, so the run is NOT PROVEN, exit 2 (before: no re-run, and pass
      // 1's code stood -- 0 on agentic-qe with 275 failed tests in the trace)
      exitStatus.recordUnknown(`the first run's trace ${path.relative(root, tracePath)} could not be read back: ${why}`);
      return { status: exitStatus.runExit({ internalError: true }) };
    }
  } else if (after !== null) {
    process.stderr.write(`detjs: parallel: the trace ${path.relative(root, tracePath)} was not written by this run; no one-lane re-run, its exit code ${status1} stands\n`);
  }
  const affected = t1 ? hazardFiles(t1.header) : [];
  if (!affected.length) return { status: status1 }; // the ordinary case: nothing re-run, nothing changed

  // ---- a hazard was reported: the files it names run again, together, in one lane ----
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
  const r0 = phases.now();
  const p2 = spawnSync(process.execPath, args2, { cwd: root, env: env2, stdio: 'inherit' });
  phases.mark('rerun_one_lane', { count: affected.length, ms: phases.now() - r0 });
  if (p2.signal) { fs.rmSync(work, { recursive: true, force: true }); return { signal: p2.signal }; }
  const status2 = p2.status ?? 1;
  try {
    const { status } = finishRerun({ t1Path: tracePath, t2Path: t2path, status1, status2, affected, tracePath, root, t1 });
    return { status };
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
}

/**
 * The merged records of a complete re-run: the first pass's records, each hazard file's replaced at its first position
 * by the re-run's (one record per nodeid: the first the re-run wrote), then hazard files only the re-run reported.
 */
function spliceRecords(firstTests, rerunTests, affected) {
  const set = new Set(affected);
  const byFile = new Map();
  // one record per nodeid: the first the re-run wrote. A runner that ran a file twice (see dropPatterns above)
  // must not put two records of one test in the merged trace, whatever the argument handling did.
  const seen = new Set();
  for (const r of rerunTests) {
    if (seen.has(r.nodeid)) continue;
    seen.add(r.nodeid);
    const f = fileOf(r.nodeid);
    if (!byFile.has(f)) byFile.set(f, []);
    byFile.get(f).push(r);
  }
  const spliced = new Set();
  const records = [];
  for (const r of firstTests) {
    const f = fileOf(r.nodeid);
    if (!set.has(f)) { records.push(r); continue; }
    if (spliced.has(f)) continue; // its records went in at the file's first position
    spliced.add(f);
    for (const x of byFile.get(f) || []) records.push(x); // one push per record: a spread overflows above ~100 000
  }
  // a file the re-run reports that the first pass never did (it died in its lane before recording)
  // (only hazard files: a file the runner's own filters made pass 2 run as well is already in the first pass's
  // records, and a second copy would count it twice)
  for (const [f, rs] of byFile) if (!spliced.has(f) && set.has(f)) for (const x of rs) records.push(x);
  return records;
}

/**
 * Everything after the one-lane re-run (split out of main so it can be tested on its own, P0 big trace criterion 3):
 * read the re-run's trace, account for the affected tests, write the merged trace to `tracePath` (records copied
 * byte for byte from t1 or t2) and decide the status. `t1` is t1Path already read with readTrace (read here when
 * absent). Returns {status, res}: `res` is native.mergeTraces' result.
 */
function finishRerun({ t1Path, t2Path, status1, status2, affected, tracePath, root, t1 }) {
  if (!t1) {
    let why = 'it has no header';
    try { t1 = readTrace(t1Path); } catch (e) { why = e && e.message; }
    if (!t1) {
      exitStatus.recordUnknown(`the first run's trace ${path.relative(root, t1Path)} could not be read back: ${why}`);
      return { status: exitStatus.runExit({ internalError: true }), res: null };
    }
  }
  const bad1 = t1.tests.filter((r) => !PASSED.has(r.outcome));
  // pass 2 unchanged: a missing or unreadable re-run trace is NOT PROVEN (wrapperRunnerCode: exit 1)
  const t2 = readTraceOrNull(t2Path);
  for (const r of t1.tests) r.src = 1;
  if (t2) for (const r of t2.tests) r.src = 2;

  // ---- the re-run's records replace the first pass's for those files, and are what gets reported ----
  const set = new Set(affected);
  // every affected test the first pass saw must be accounted for by the re-run, or the red stands; each one it did
  // not account for is NOT PROVEN (B3)
  const acc = accountRerun(t1.tests, t2 ? t2.tests : null, affected);
  const { want, unaccounted, complete } = acc;

  let records;
  if (complete) {
    records = spliceRecords(t1.tests, t2.tests, affected);
  } else {
    records = t1.tests;
    process.stderr.write(`detjs: parallel: the one-lane re-run could not account for ${t2 ? `${unaccounted.length} test(s) of the affected files` : 'its own trace'}`
      + `; the first run's records stay, nothing was cleared, and its unaccounted tests are NOT PROVEN${t2 && unaccounted.length ? ` (first: ${unaccounted[0]})` : ''}\n`);
  }
  for (const { file, cause } of acc.notProvenFiles) {
    process.stderr.write(`detjs: parallel: NOT PROVEN ${file}: the one-lane re-run did not account for its tests (${cause})\n`);
  }
  // B7: the counts of the final trace, in its header and on one status line, and the exit decision on them
  const status = exitStatus.countStatus(records, acc.notProven);

  // the merged trace, written where the user asked for it; each record's line copied byte for byte from its trace
  const order = records.map((r) => r.nodeid);
  fs.mkdirSync(path.dirname(tracePath), { recursive: true });
  const work = fs.mkdtempSync(path.join(path.dirname(tracePath), '.detjs-merge-'));
  let res;
  try {
    const parts = writeRecordParts(records, t1Path, t2Path, path.join(work, 'parts'));
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
    res = native.mergeTraces(parts, tracePath, JSON.stringify(meta), order);
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
  // P0 big trace: a part the merge could not read is missing from the trace with its tests: status unknown, exit 2
  if (res.skipped.length) {
    exitStatus.recordUnknown(`unreadable trace parts, their tests are not counted: ${res.skipped.join('; ')}`);
    return { status: exitStatus.runExit({ internalError: true }), res };
  }

  process.stderr.write(`${exitStatus.statusLine(status)}\n`);
  const badFinal = records.filter((r) => !PASSED.has(r.outcome));
  const badIds = new Set(badFinal.map((r) => r.nodeid));
  const cleared = bad1.filter((r) => set.has(fileOf(r.nodeid)) && !badIds.has(r.nodeid));
  process.stdout.write(`detjs: trace ${path.relative(root, tracePath)}: ${res.nTests} tests, order digest ${res.orderDigest}`
    + ` (${affected.length} file(s) re-run in one lane)\n`);
  if (complete) {
    process.stdout.write(`detjs: parallel: the one-lane re-run is what is reported for ${affected.join(', ')}:`
      + ` ${badFinal.filter((r) => set.has(fileOf(r.nodeid))).length} failed of ${want.length} test(s)`
      + `${cleared.length ? `; ${cleared.length} failure(s) of the first run did not recur in one lane (the exit code is not lowered): ${cleared.slice(0, 5).map((r) => r.nodeid).join(', ')}${cleared.length > 5 ? ` (+${cleared.length - 5})` : ''}` : ''}\n`);
  }

  // The status (B1, src/exit-status.js). A green is only ever given when the re-run accounted for everything: an
  // unaccounted test is NOT PROVEN, which is exit 1.
  if (status1 !== 0 && complete && badFinal.length === 0) {
    process.stderr.write(`detjs: parallel: the one-lane re-run of the hazard files passed, but the first run's exit code ${status1}`
      + ' stands: a re-run never turns a red into a green (src/parallel-rerun.js wrapperRunnerCode)\n');
  }
  return { status: exitStatus.runExit({ ...status, runnerCode: wrapperRunnerCode(status1, status2, Boolean(t2)) }), res };
}

module.exports = { main, finishRerun, spliceRecords, readTrace, writeRecordParts, shouldWrap, hazardFiles, rerunArgs, fileOf, labelFile, accountRerun, wrapperRunnerCode };
