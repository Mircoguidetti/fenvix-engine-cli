'use strict';
// The one owner of the exit-status rule of detjs (spec "Engine P0: no false green", B1, B2, B6).
//
// Two pure functions over plain objects; every place that DECIDES a top-level exit code calls them:
//   * bin/detjs.js, normal path (`main(argv)` of a runner shell)   -> runExit
//   * src/parallel-rerun.js, the wrapper's final decision          -> runExit
//   * bin/detjs.js, `detjs verify`                                -> verifyExit / verifyStatus
// A path that only forwards a child's already-decided code (the TZ/early-capture re-exec, the wrapper forwarding the
// pass-1 child's code when nothing was re-run) keeps forwarding it.
//
// Input shapes:
//
//   runExit(run):
//     run.failed        number   tests whose outcome is failed or error            (default 0)
//     run.not_proven    number   tests NOT PROVEN by this run (B3)                  (default 0)
//     run.runnerCode    number   exit code the runner shell returned (0 when none)  (default 0)
//     run.internalError boolean  detjs itself failed: usage error or internal error (default false)
//   Other keys (passed, skipped, ...) are allowed and ignored.
//   First match wins: 2 = internalError, or runnerCode 2; 1 = failed > 0, or not_proven > 0, or any other non-zero
//   runnerCode; 0 = otherwise.
//
//   verifyExit(summary) -- the `summary` object of the verifier's report (crates/detpy-core/src/verify.rs `Summary`,
//   the dict python/detpy/fenvix.py `verify_exit_code` reads):
//     summary.tests            number
//     summary.diverged         number
//     summary.missing          number
//     summary.not_proven       number   (absent = 0)
//     summary.inputs_recorded  boolean  (absent = true; null, 0, false = not recorded, as in Python)
//     summary.input_differs    number   (absent = 0)
//   1 on tests == 0, diverged, missing, not_proven, or inputs_recorded === false; 3 when only input_differs; else 0.
//   (Unreadable traces and usage errors are exit 2, decided by the caller before a summary exists.)
//
//   verifyStatus(summary) -- the `status` field of `detjs verify --json`, precedence diverged > not_proven >
//   input_differs > identical:
//     "diverged"      diverged or missing                                (exit 1)
//     "not_proven"    not_proven, tests == 0, or inputs not recorded     (exit 1)
//     "input_differs" only environment inputs differ                     (exit 3)
//     "identical"     otherwise                                          (exit 0)

const n = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);

function runExit(run = {}) {
  const r = run || {};
  // no code (undefined, null) is 0; a code that is not a number is not a success
  const rc = r.runnerCode;
  const code = rc === undefined || rc === null ? 0 : (Number.isFinite(Number(rc)) ? Number(rc) : 1);
  if (r.internalError || code === 2) return 2;
  if (n(r.failed) > 0 || n(r.not_proven) > 0 || code !== 0) return 1;
  return 0;
}

function verifyStatus(summary = {}) {
  const s = summary || {};
  if (n(s.diverged) || n(s.missing)) return 'diverged';
  // inputs_recorded: absent counts as recorded, any other falsy value as not (python/detpy/fenvix.py verify_exit_code)
  if (!n(s.tests) || n(s.not_proven) || (s.inputs_recorded !== undefined && !s.inputs_recorded)) return 'not_proven';
  if (n(s.input_differs)) return 'input_differs';
  return 'identical';
}

const VERIFY_CODE = { diverged: 1, not_proven: 1, input_differs: 3, identical: 0 };

function verifyExit(summary = {}) {
  return VERIFY_CODE[verifyStatus(summary)];
}

/**
 * The counts of the status line (B7) over test records ({outcome, nodeid}): failed = failed or error, passed =
 * passed, skipped = skipped or todo. `notProven`: the nodeids NOT PROVEN by this run (B3); they are counted there
 * only, not under their recorded outcome. Any other outcome (`interrupted`, a test whose file ended while it ran,
 * or one this code does not know) counts as failed: the spec names failed and error only (B7), and leaving the rest
 * out of every count would let such a run end green where src/parallel-rerun.js always gave 1 (its `badFinal` was
 * every outcome other than passed, skipped and todo). docs/CLI.md (exit codes of a run) states it too.
 */
function countStatus(records, notProven = []) {
  const np = new Set(notProven);
  const st = { failed: 0, not_proven: 0, passed: 0, skipped: 0 };
  for (const r of records || []) {
    if (np.has(r.nodeid)) continue;
    const o = r.outcome;
    if (o === 'passed') st.passed++;
    else if (o === 'skipped' || o === 'todo') st.skipped++;
    else st.failed++;
  }
  st.not_proven = np.size;
  return st;
}

function statusLine(st) {
  return `detjs: status: failed=${n(st.failed)} not_proven=${n(st.not_proven)} passed=${n(st.passed)} skipped=${n(st.skipped)}`;
}

// The status of the trace this process wrote (session.finish), read by the process's own exit decision
// (bin/detjs.js normal path). One process writes at most one final trace.
//
// It also applies the rule to process.exitCode at once: a runner that ends the process itself (Jest --forceExit,
// process.exit in a runner) makes session.finish run in an 'exit' listener and never returns to bin/detjs.js, and
// Node exits with the exitCode an 'exit' listener leaves. The normal path decides again on the shell's return.
let recorded = null;
// P0 big trace: the engine could not establish the run's outcome (the trace could not be read back or stamped, a
// worker part could not be merged). Sticky: no later record() clears it, so the run ends 2 (NOT PROVEN), never 0.
let unknown = null;
// A runner whose own code calls process.exit(0) after detjs decided (agentic-qe's vitest global teardown: process.exit(0)
// 5 s after the tests, while the process is still alive) would set the exit code back to 0: the decision is applied
// again on 'exit', after that call. It only ever raises the code (runExit over the code being exited with).
let guarded = false;
function guardExit() {
  if (guarded) return;
  guarded = true;
  process.on('exit', () => {
    if (!recorded) return;
    const cur = process.exitCode === undefined || process.exitCode === null ? 0 : Number(process.exitCode);
    process.exitCode = runExit({ ...recorded, runnerCode: Number.isFinite(cur) ? cur : 1 });
  });
}
function record(st) {
  if (unknown) { process.exitCode = 2; return; }
  recorded = st ? { ...st } : null;
  if (recorded) {
    guardExit();
    const cur = process.exitCode === undefined || process.exitCode === null ? 0 : Number(process.exitCode);
    process.exitCode = runExit({ ...recorded, runnerCode: Number.isFinite(cur) ? cur : 1 });
  }
}
function recordedStatus() { return recorded; }

/**
 * The run's status is unknown: `cause` says why (one sentence). Sets the recorded status to `{internalError: true,
 * cause}` (runExit gives 2, also when bin/detjs.js decides again after main returns), sets process.exitCode = 2 and
 * prints `detjs: status: unknown (<cause>): exit 2, NOT PROVEN` (once per cause). Sticky: record() never clears it.
 */
const unknownCauses = new Set();
function recordUnknown(cause) {
  const c = String(cause);
  if (!unknown) unknown = c;
  recorded = { internalError: true, cause: unknown };
  process.exitCode = 2;
  guardExit();
  if (!unknownCauses.has(c)) {
    unknownCauses.add(c);
    try { require('node:fs').writeSync(2, `detjs: status: unknown (${c}): exit 2, NOT PROVEN\n`); } catch { /* not printed */ }
  }
}

module.exports = { runExit, verifyExit, verifyStatus, countStatus, statusLine, record, recordedStatus, recordUnknown };
