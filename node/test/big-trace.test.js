'use strict';
// P0 big trace (harness/p0_big_trace/REPORT.md): no false green on a trace too large for one JavaScript string.
//
// On f67be4a3 every trace reader did fs.readFileSync(trace, 'utf8'), which throws ERR_STRING_TOO_LONG above ~512 MiB,
// caught the error and returned "nothing": agentic-qe (1.2 GB traces, 168-275 failed tests) exited 0. These tests
// generate traces over 600 MiB (records of 1 MiB each, so they are written and parsed in seconds) and drive the
// readers that decide an exit code, and inject the faults the fail-closed paths exist for.
//
// Scenarios that end in exit-status.recordUnknown run in a child process: it sets process.exitCode = 2, which must
// not become the exit code of this test file.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { stampStatus } = require('../src/session');
const { runExit } = require('../src/exit-status');
const { forEachLine, firstLine } = require('../src/trace-lines');
const { finishRerun, hazardFiles, writeRecordParts, readTrace: rerunReadTrace } = require('../src/parallel-rerun');
const { BIN, TMP } = require('./helpers');

const T = { timeout: 300000 };
const HOOK = path.join(__dirname, 'fixtures', 'big-trace-hook.js');
const SRC = path.join(__dirname, '..', 'src');
const BIG = 640; // records of 1 MiB: 640 MiB + headers, over 600 MiB and over V8's string limit (~512 MiB)
const PAYLOAD = 'q'.repeat(1 << 20);

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'big-trace-'));
test.after(() => fs.rmSync(dir, { recursive: true, force: true }));

/** A header line as the Rust writer serializes it (type first, then format, version, encoding, meta, order). */
function headerLine(meta) {
  return JSON.stringify({ type: 'header', format: 'detpy-trace', version: 1, encoding: 2, meta, order: [] });
}

/** A test line in the Rust writer's field order (crates/detpy-core/src/fingerprint.rs TestRecord), so a record the
 * merge re-serializes differs from its source only in `index`. */
function testLine(nodeid, index, outcome, { payload = PAYLOAD, neverStarted = false } = {}) {
  const events = [{ t: 0, s: 'time', o: 'time.now', at: 'f.js:1', v: payload }];
  if (neverStarted) events.push({ t: 0, s: 'sched', o: 'sched.never_started', at: 'f.js:1', v: '' });
  return JSON.stringify({ type: 'test', nodeid, index, outcome, fingerprint: '0123456789abcdef0123456789abcdef', n_events: events.length, truncated: false, counts: {}, checkpoints: [], events });
}

/** Write a trace: `recs` = [{nodeid, outcome, ...}]; returns its path. */
function writeTrace(name, meta, recs, { footer = true } = {}) {
  const p = path.join(dir, name);
  const fd = fs.openSync(p, 'w');
  try {
    fs.writeSync(fd, `${headerLine(meta)}\n`);
    recs.forEach((r, i) => fs.writeSync(fd, `${testLine(r.nodeid, i, r.outcome, r)}\n`));
    if (footer) fs.writeSync(fd, `${JSON.stringify({ type: 'footer', n_tests: recs.length, order_digest: 'x' })}\n`);
  } finally { fs.closeSync(fd); }
  return p;
}

function sha256From(p, start) {
  const h = crypto.createHash('sha256');
  const fd = fs.openSync(p, 'r');
  const buf = Buffer.allocUnsafe(1 << 22);
  try {
    let pos = start;
    for (;;) { const n = fs.readSync(fd, buf, 0, buf.length, pos); if (!n) break; h.update(buf.subarray(0, n)); pos += n; }
  } finally { fs.closeSync(fd); }
  return h.digest('hex');
}

/** Run `code` in a child node process (cwd = this directory); returns {status, stdout, stderr}. */
function child(code, env = {}) {
  const r = spawnSync(process.execPath, ['-e', code], { cwd: __dirname, encoding: 'utf8', env: { ...process.env, ...env }, timeout: 240000, maxBuffer: 1 << 26 });
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '', show: `status=${r.status}\nstdout=${(r.stdout || '').slice(-2000)}\nstderr=${(r.stderr || '').slice(-3000)}` };
}

const UNKNOWN = /^detjs: status: unknown \(.+\): exit 2, NOT PROVEN$/m;

let bigSerial = null;
function bigSerialTrace() {
  if (bigSerial) return bigSerial;
  const recs = [];
  for (let i = 0; i < BIG; i++) recs.push({ nodeid: `tests/f${i % 10}.test.js::case ${i}`, outcome: [100, 300, 500].includes(i) ? 'failed' : 'passed' });
  bigSerial = writeTrace('serial.jsonl', { runner: 'vitest', notes: [] }, recs);
  return bigSerial;
}

test('criterion 1: protects=stampStatus counts a trace over 600 MiB (3 failed of 640), stamps meta.status into the header only and copies the body byte for byte; fails_when=the trace is read into one string (ERR_STRING_TOO_LONG, status null, exit decided by the runner code 0) or any byte after the header changes; no_claim=bin/detjs.js end to end on such a trace (a real run of that size does not fit in test time; harness/p0_big_trace/REPORT.md re-measures agentic-qe)', T, () => {
  const p = bigSerialTrace();
  const size = fs.statSync(p).size;
  assert.ok(size > 600 * 1024 * 1024, `the trace is over 600 MiB (${size} bytes)`);
  // what f67be4a3 did, and why it gave no status
  assert.throws(() => fs.readFileSync(p, 'utf8'), (e) => e.code === 'ERR_STRING_TOO_LONG');
  const head0 = firstLine(p);
  const headLen = Buffer.byteLength(head0);
  const body0 = sha256From(p, headLen + 1);
  const st = stampStatus(p);
  assert.deepEqual(st, { failed: 3, not_proven: 0, passed: BIG - 3, skipped: 0 });
  assert.equal(runExit({ ...st, runnerCode: 0 }), 1, 'a runner that returned 0 does not make this run green');
  const head1 = firstLine(p);
  assert.equal(head1, head0.replace('"meta":{', `"meta":{"status":${JSON.stringify(st)},`), 'the header differs only by "status":{...}');
  assert.equal(sha256From(p, Buffer.byteLength(head1) + 1), body0, 'everything after the first line is unchanged');
  assert.deepEqual(fs.readdirSync(dir).filter((f) => f.includes('.status-')), [], 'no temporary file left');
});

test('criterion 2 (unit): protects=a stamp whose rename fails makes stampStatus throw, on the >600 MiB trace; fails_when=the failure is caught and the counts returned as if the trace carried them (the run then decides on counts its trace does not hold); no_claim=other write failures (same catch)', T, () => {
  const p = bigSerialTrace();
  const before = firstLine(p);
  const orig = fs.renameSync;
  fs.renameSync = function renameSync(a, b) {
    if (String(a).includes('.status-')) { const e = new Error('injected rename failure'); e.code = 'EIO'; throw e; }
    return orig.call(this, a, b);
  };
  try {
    assert.throws(() => stampStatus(p), /meta\.status not written into .*injected rename failure/);
  } finally { fs.renameSync = orig; }
  assert.equal(firstLine(p), before, 'the trace is unchanged');
  assert.deepEqual(fs.readdirSync(dir).filter((f) => f.includes('.status-')), [], 'the temporary file is removed');
});

/** A vitest project under test/.tmp (vitest resolves from node/node_modules). */
function project(name, files) {
  const d = path.join(TMP, 'big-trace', name);
  fs.rmSync(d, { recursive: true, force: true });
  fs.mkdirSync(path.join(d, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(d, 'package.json'), JSON.stringify({ name: `big-trace-${name}`, private: true }));
  fs.writeFileSync(path.join(d, 'vitest.config.mjs'), "export default { test: { include: ['tests/**/*.test.mjs'] } };\n");
  for (const [f, body] of Object.entries(files)) fs.writeFileSync(path.join(d, 'tests', f), `import { test, expect } from 'vitest';\n${body}\n`);
  return d;
}

function cleanEnv(extra) {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_SEED', 'DETJS_CACHE_DIR',
    'DETJS_HAZARD_RERUN', 'DETJS_HAZARD_PASS', 'DETJS_EARLY', 'DETJS_ISOLATE_CHILD', 'JEST_WORKER_ID', 'VITEST_POOL_ID', 'VITEST_WORKER_ID']) delete env[k];
  return { ...env, TZ: 'UTC', LC_ALL: 'C.UTF-8', LANG: 'C.UTF-8', ...extra };
}

function detjs(d, args, env) {
  fs.rmSync(path.join(d, '.detjs'), { recursive: true, force: true });
  const r = spawnSync(process.execPath, [BIN, 'vitest', 'run', '--det', ...args], { cwd: d, encoding: 'utf8', env: cleanEnv(env), timeout: 240000 });
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '', show: `status=${r.status} signal=${r.signal}\nstdout=${(r.stdout || '').slice(-2500)}\nstderr=${(r.stderr || '').slice(-2500)}` };
}

const PASSING = { 'a.test.mjs': "test('a', () => { expect(1).toBe(1); });", 'b.test.mjs': "test('b', () => { expect(2).toBe(2); });" };

test('criterion 2 (bin/detjs.js): protects=a run whose meta.status cannot be stamped (rename fails) exits 2 with the unknown line, although every test passed; fails_when=the stamp failure is swallowed and the run exits 0; no_claim=which runner (vitest, one lane, the normal path of bin/detjs.js)', T, () => {
  const d = project('rename', PASSING);
  const ok = detjs(d, ['--det-workers=1'], {});
  assert.equal(ok.status, 0, `without the fault the run is green\n${ok.show}`);
  const r = detjs(d, ['--det-workers=1'], { NODE_OPTIONS: `--require ${HOOK}`, BIG_TRACE_HOOK: 'rename' });
  assert.equal(r.status, 2, r.show);
  assert.match(r.stderr, UNKNOWN, r.show);
  assert.match(r.stderr, /detjs: status: unknown \(the trace .* could not be read back or stamped: meta\.status not written into .*injected rename failure.*\): exit 2, NOT PROVEN/, r.show);
  assert.doesNotMatch(r.stderr, /^detjs: status: failed=/m, 'no counts line for a status that is unknown');
});

test('criterion 3: protects=the parallel wrapper gives exit 2 when pass 1 wrote a trace it cannot read back (injected read error); fails_when=the wrapper forwards pass 1\'s code (0: the agentic-qe false green); no_claim=pass 2 (an unreadable re-run trace stays NOT PROVEN, exit 1: test/parallel-rerun-account.test.js)', T, () => {
  const d = project('wrapper-read', PASSING);
  const target = path.join(d, '.detjs', 'trace.jsonl');
  const ok = detjs(d, ['--det-workers=2'], {});
  assert.equal(ok.status, 0, `without the fault the run is green\n${ok.show}`);
  const r = detjs(d, ['--det-workers=2'], { NODE_OPTIONS: `--require ${HOOK}`, BIG_TRACE_HOOK: 'wrapper-read', BIG_TRACE_TARGET: target });
  assert.equal(r.status, 2, r.show);
  assert.match(r.stderr, /detjs: status: unknown \(the first run's trace .*trace\.jsonl could not be read back: injected read error.*\): exit 2, NOT PROVEN/, r.show);
});

test('criterion 3: protects=finishRerun gives exit 2 for a first trace that is not JSON; fails_when=an unreadable t1 is treated as "no hazard" and pass 1\'s code stands; no_claim=the >600 MiB case (next test)', T, () => {
  const t1 = path.join(dir, 'bad-t1.jsonl');
  fs.writeFileSync(t1, `${headerLine({})}\n{"type":"test", torn\n`);
  const r = child(`
    const { finishRerun } = require(${JSON.stringify(path.join(SRC, 'parallel-rerun'))});
    const out = finishRerun({ t1Path: ${JSON.stringify(t1)}, t2Path: ${JSON.stringify(path.join(dir, 'absent.jsonl'))}, status1: 0, status2: 0, affected: ['tests/h.test.js'], tracePath: ${JSON.stringify(t1)}, root: ${JSON.stringify(dir)} });
    process.stdout.write(JSON.stringify({ status: out.status }));
  `);
  assert.equal(JSON.parse(r.stdout).status, 2, r.show);
  assert.equal(r.status, 2, r.show);
  assert.match(r.stderr, /detjs: status: unknown \(the first run's trace bad-t1\.jsonl could not be read back: .*\): exit 2, NOT PROVEN/, r.show);
});

test('criterion 3: protects=the hazard re-run path runs on a first trace over 600 MiB: every test is in the merged trace and each record is a byte copy of its source line (index aside); fails_when=t1 is read into one string (no re-run, pass 1\'s code stands) or records are re-serialized/lost; no_claim=spawning the two passes (finishRerun is called directly with both traces)', T, () => {
  const affected = ['tests/h.test.js', 'tests/k.test.js'];
  const meta = { runner: 'vitest', parallel: { hazards: [{ kind: 'path', what: 'out/shared.txt', a: 'w0|tests/h.test.js', b: 'tests/k.test.js' }] } };
  const recs1 = [];
  for (let i = 0; i < BIG; i++) {
    const file = i % 50 === 7 ? 'tests/h.test.js' : i % 50 === 9 ? 'tests/k.test.js' : `tests/f${i % 10}.test.js`;
    recs1.push({ nodeid: `${file}::case ${i}`, outcome: file === 'tests/h.test.js' ? 'failed' : 'passed' });
  }
  const t1 = writeTrace('par-t1.jsonl', meta, recs1);
  assert.ok(fs.statSync(t1).size > 600 * 1024 * 1024);
  assert.deepEqual(hazardFiles({ meta }), affected);
  // the one-lane re-run: the hazard files' tests, passing now, small records
  const recs2 = recs1.filter((r) => affected.some((f) => r.nodeid.startsWith(`${f}::`))).map((r) => ({ nodeid: r.nodeid, outcome: 'passed', payload: `rerun ${r.nodeid}` }));
  const t2 = writeTrace('par-t2.jsonl', { runner: 'vitest' }, recs2);
  const src = new Map(); // nodeid -> source line generator
  for (const r of recs1) if (!affected.some((f) => r.nodeid.startsWith(`${f}::`))) src.set(r.nodeid, (i) => testLine(r.nodeid, i, r.outcome));
  for (const r of recs2) src.set(r.nodeid, (i) => testLine(r.nodeid, i, r.outcome, r));

  const { status, res } = finishRerun({ t1Path: t1, t2Path: t2, status1: 1, status2: 0, affected, tracePath: t1, root: dir });
  assert.equal(status, 1, 'pass 1 was red: the re-run never lowers it');
  assert.deepEqual(res.skipped, []);
  assert.equal(res.nTests, BIG);
  let header = null;
  let n = 0;
  const seen = new Set();
  forEachLine(t1, (line, i) => {
    if (i === 0) { header = JSON.parse(line); return; }
    if (!line.startsWith('{"type":"test"')) return;
    const id = JSON.parse(line.slice(0, 400).replace(/,"outcome".*$/, '}')).nodeid;
    assert.ok(src.has(id), `unknown record ${id}`);
    assert.equal(line, src.get(id)(n), `record ${id} is its source line (index ${n})`);
    seen.add(id);
    n++;
  });
  assert.equal(n, BIG, 'every test is in the merged trace');
  assert.equal(seen.size, BIG);
  assert.equal(header.meta.hazard_rerun.complete, true, 'the re-run path ran and accounted for every affected test');
  assert.equal(header.meta.hazard_rerun.reported, 'one-lane re-run');
  assert.deepEqual(header.meta.status, { failed: 0, not_proven: 0, passed: BIG, skipped: 0 });
});

test('criterion 3: protects=writeRecordParts copies each record\'s raw line byte for byte from t1 or t2 (a CRLF line and non-ASCII text included); fails_when=a record is re-serialized (JSON.stringify) or taken from the wrong trace; no_claim=what the Rust merge then writes (previous test)', () => {
  const a = path.join(dir, 'raw-t1.jsonl');
  const b = path.join(dir, 'raw-t2.jsonl');
  const l1 = '{"type":"test","nodeid":"x::é","index":0,  "outcome":"passed"}\r';
  const l2 = '{"type":"test" , "nodeid":"y::1","index":3,"outcome":"failed"}';
  fs.writeFileSync(a, `${headerLine({})}\n${l1}\n`);
  fs.writeFileSync(b, `${headerLine({})}\n${l2}`);
  const ta = rerunReadTrace(a);
  const tb = rerunReadTrace(b);
  const recs = [{ ...tb.tests[0], src: 2 }, { ...ta.tests[0], src: 1 }];
  const parts = writeRecordParts(recs, a, b, path.join(dir, 'raw-parts'));
  const body = (p) => fs.readFileSync(p).subarray(fs.readFileSync(p).indexOf(0x0a) + 1);
  assert.ok(body(parts[0]).equals(Buffer.from(`${l2}\n`)));
  assert.ok(body(parts[1]).equals(Buffer.from(`${l1}\n`)));
  assert.equal(ta.tests[0].never_started, false);
});

test('criterion 4 (parallel wrapper): protects=a part the merge cannot read makes finishRerun exit 2 with the unknown line; fails_when=the part is skipped with a printed line and its tests (and failures) vanish from a green trace; no_claim=why a part is unreadable (here: a record without n_events, which JavaScript reads and the Rust merge refuses)', T, () => {
  const t1 = path.join(dir, 'skip-t1.jsonl');
  const ok = (id, outcome) => testLine(id, 0, outcome, { payload: 'p' });
  const noEvents = JSON.stringify({ type: 'test', nodeid: 'tests/z.test.js::lost', index: 1, outcome: 'failed' });
  const meta = { parallel: { hazards: [{ a: 'tests/h.test.js', b: 'tests/k.test.js' }] } };
  fs.writeFileSync(t1, `${headerLine(meta)}\n${ok('tests/h.test.js::a', 'passed')}\n${noEvents}\n${ok('tests/k.test.js::b', 'passed')}\n`);
  const t2 = path.join(dir, 'skip-t2.jsonl');
  fs.writeFileSync(t2, `${headerLine({})}\n${ok('tests/h.test.js::a', 'passed')}\n${ok('tests/k.test.js::b', 'passed')}\n`);
  const r = child(`
    const { finishRerun } = require(${JSON.stringify(path.join(SRC, 'parallel-rerun'))});
    const out = finishRerun({ t1Path: ${JSON.stringify(t1)}, t2Path: ${JSON.stringify(t2)}, status1: 0, status2: 0, affected: ['tests/h.test.js', 'tests/k.test.js'], tracePath: ${JSON.stringify(t1)}, root: ${JSON.stringify(dir)} });
    process.stdout.write(JSON.stringify({ status: out.status, skipped: out.res.skipped.length }));
  `);
  const out = JSON.parse(r.stdout);
  assert.equal(out.skipped, 1, r.show);
  assert.equal(out.status, 2, r.show);
  assert.equal(r.status, 2, r.show);
  assert.match(r.stderr, /detjs: status: unknown \(unreadable trace parts, their tests are not counted: .*\): exit 2, NOT PROVEN/, r.show);
});

test('criterion 4 (session): protects=a worker part the merge cannot read makes the run exit 2 with the unknown line, every test passing; fails_when=the part is skipped and the run exits 0 (src/session.js printed one line and went on); no_claim=how a real part gets corrupted (injected: a line that is not JSON appended before the merge)', T, () => {
  const d = project('merge-skip', PASSING);
  const r = detjs(d, ['--det-workers=1'], { NODE_OPTIONS: `--require ${HOOK}`, BIG_TRACE_HOOK: 'merge-skip' });
  assert.equal(r.status, 2, r.show);
  assert.match(r.stderr, /detjs: status: unknown \(unreadable trace parts, their tests are not counted: .*\): exit 2, NOT PROVEN/, r.show);
});

test('criterion 4 (isolate): protects=--det-isolate exits 2 with the unknown line when a per-test part cannot be merged; fails_when=its tests vanish and the run exits 0; no_claim=the per-test sessions themselves (not faulted: DETJS_ISOLATE_CHILD)', T, () => {
  const d = project('isolate-skip', PASSING);
  const ok = detjs(d, ['--det-isolate'], {});
  assert.equal(ok.status, 0, `without the fault the run is green\n${ok.show}`);
  const r = detjs(d, ['--det-isolate'], { NODE_OPTIONS: `--require ${HOOK}`, BIG_TRACE_HOOK: 'merge-skip' });
  assert.equal(r.status, 2, r.show);
  assert.match(r.stderr, /detjs: status: unknown \(unreadable trace parts, their tests are not counted: .*\): exit 2, NOT PROVEN/, r.show);
});

test('repro: protects=an unreadable trace writes no --det-outcomes file and says why; fails_when=outcomes are taken from the side states instead (a result the trace does not back, which runner/fenvix-run would then accept); no_claim=the runner\'s own exit (runner/fenvix-run:759-766, tests/test_runner_node.py)', () => {
  const { afterMerge } = require('../src/repro');
  const out = path.join(dir, 'outcomes.json');
  const sub = path.join(dir, 'a-directory');
  fs.mkdirSync(sub, { recursive: true });
  const lines = afterMerge({ tracePath: sub, dir, cfg: { controls: new Set(), seed: 0n } }, { outcomes: out }, [], 'vitest');
  assert.equal(fs.existsSync(out), false, 'no outcomes file');
  assert.equal(lines.length, 1);
  assert.match(lines[0], /^detjs: --det-outcomes not written: the trace .* could not be read: .*EISDIR/);
});

test('exit-status: protects=recordUnknown is sticky: record(status) after it still gives 2, also when bin/detjs.js recomputes from recordedStatus(); fails_when=a later record() of a clean status clears it to 0; no_claim=the printed cause beyond its form', () => {
  const r = child(`
    const xs = require(${JSON.stringify(path.join(SRC, 'exit-status'))});
    xs.recordUnknown('a cause');
    xs.record({ failed: 0, not_proven: 0, passed: 5, skipped: 0 });
    const st = xs.recordedStatus();
    process.stdout.write(JSON.stringify({ exitCode: process.exitCode, recomputed: xs.runExit({ ...st, runnerCode: 0 }), st }));
  `);
  const out = JSON.parse(r.stdout);
  assert.equal(out.exitCode, 2, r.show);
  assert.equal(out.recomputed, 2, r.show);
  assert.deepEqual(out.st, { internalError: true, cause: 'a cause' });
  assert.equal(r.status, 2, r.show);
  assert.equal(r.stderr, 'detjs: status: unknown (a cause): exit 2, NOT PROVEN\n');
});

test('vitest exit 0 (item 5): protects=a runner\'s own process.exit(0) after detjs decided does not lower the exit code (agentic-qe tests/global-teardown.ts: setTimeout(() => process.exit(0), 5000) in vitest\'s main process, which is the detjs process); fails_when=a run whose status line says failed=1 exits 0; no_claim=a runner that kills the process with a signal', T, () => {
  const d = project('teardown-exit0', { 'a.test.mjs': "test('fails', () => { expect(1).toBe(2); });" });
  fs.writeFileSync(path.join(d, 'vitest.config.mjs'), "export default { test: { include: ['tests/**/*.test.mjs'], globalSetup: ['./teardown.mjs'] } };\n");
  // the agentic-qe teardown, with a handle that keeps the main process alive until the timer fires (as its native
  // modules did) and a shorter delay
  fs.writeFileSync(path.join(d, 'teardown.mjs'), 'export function setup() {}\nexport function teardown() {\n'
    + '  const keep = setInterval(() => {}, 1000);\n  const timer = setTimeout(() => { clearInterval(keep); process.exit(0); }, 1500);\n  timer.unref();\n}\n');
  const r = detjs(d, ['--det-workers=1'], {});
  assert.match(r.stderr, /^detjs: status: failed=1 not_proven=0 passed=0 skipped=0$/m, r.show);
  assert.equal(r.status, 1, r.show);
});

test('session (review fix): protects=the order of a part with 150 000 tests is read whole; fails_when=the ids are spread into push() (RangeError: Maximum call stack size exceeded, the part is reported unreadable and a clean run exits 2); no_claim=parts too large for the 256 MiB line limit', () => {
  const { partOrder } = require('../src/session');
  const p = path.join(dir, 'many.jsonl');
  const fd = fs.openSync(p, 'w');
  try {
    fs.writeSync(fd, `${headerLine({})}\n`);
    let chunk = '';
    for (let i = 0; i < 150000; i++) {
      chunk += `{"type":"test","nodeid":"t.test.js::case ${i}","index":${i},"outcome":"passed"}\n`;
      if (chunk.length > 1 << 20) { fs.writeSync(fd, chunk); chunk = ''; }
    }
    fs.writeSync(fd, chunk);
  } finally { fs.closeSync(fd); }
  const errors = [];
  const order = partOrder([p], (part, e) => errors.push(String(e && e.message)));
  assert.deepEqual(errors, []);
  assert.equal(order.length, 150000);
  assert.equal(order[149999], 't.test.js::case 149999');
});

test('session (review fix): protects=a part whose ids cannot be read makes the run exit 2 with the unknown line; fails_when=the read error is swallowed (partIds returning [] as on f67be4a3) and the run exits 0; no_claim=which part (the injected EIO hits every part)', T, () => {
  const d = project('part-read', PASSING);
  const r = detjs(d, ['--det-workers=1'], { NODE_OPTIONS: `--require ${HOOK}`, BIG_TRACE_HOOK: 'part-read' });
  assert.equal(r.status, 2, r.show);
  assert.match(r.stderr, /detjs: status: unknown \(trace part .* could not be read: injected read error.*\): exit 2, NOT PROVEN/, r.show);
});

test('session (review fix): protects=a merged trace that cannot be read back makes the run exit 2 with the unknown line; fails_when=stampStatus returns null and the runner\'s code 0 decides (the original agentic-qe false green); no_claim=why it cannot be read (an injected EIO here, ERR_STRING_TOO_LONG on f67be4a3)', T, () => {
  const d = project('trace-read', PASSING);
  const r = detjs(d, ['--det-workers=1'], { NODE_OPTIONS: `--require ${HOOK}`, BIG_TRACE_HOOK: 'trace-read' });
  assert.equal(r.status, 2, r.show);
  assert.match(r.stderr, /detjs: status: unknown \(the trace .*trace\.jsonl could not be read back\): exit 2, NOT PROVEN/, r.show);
});

test('parallel wrapper (review fix): protects=finishRerun writes the merged trace into a directory that does not exist yet; fails_when=its temporary merge directory is created inside that directory before it exists (ENOENT thrown before any status is decided); no_claim=a directory that cannot be created', () => {
  const meta = { parallel: { hazards: [{ a: 'tests/h.test.js', b: 'tests/k.test.js' }] } };
  const ok = (id) => testLine(id, 0, 'passed', { payload: 'p' });
  const t1 = path.join(dir, 'nodir-t1.jsonl');
  fs.writeFileSync(t1, `${headerLine(meta)}\n${ok('tests/h.test.js::a')}\n${ok('tests/k.test.js::b')}\n`);
  const t2 = path.join(dir, 'nodir-t2.jsonl');
  fs.writeFileSync(t2, `${headerLine({})}\n${ok('tests/h.test.js::a')}\n${ok('tests/k.test.js::b')}\n`);
  const out = path.join(dir, 'not-yet', 'deeper', 'trace.jsonl');
  const { status, res } = finishRerun({ t1Path: t1, t2Path: t2, status1: 0, status2: 0, affected: ['tests/h.test.js', 'tests/k.test.js'], tracePath: out, root: dir });
  assert.equal(status, 0);
  assert.equal(res.nTests, 2);
  assert.ok(fs.existsSync(out));
  assert.deepEqual(fs.readdirSync(path.dirname(out)), ['trace.jsonl'], 'no temporary merge directory left');
});
