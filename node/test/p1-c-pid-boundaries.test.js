'use strict';
// P1 C, second attempt (coordinator 2026-11-24, D1 = A: map the virtual pid at every boundary). Test code reads a
// virtual process.pid (above Linux's PID_MAX_LIMIT); wherever that number leaves the process to the operating system
// it must name the real process. The first attempt mapped process.kill only, and ironcurtain's docker suites failed
// (207 tests): `execFileSync('ps', ['-o', 'lstart=', '-p', String(process.pid)])` found no such process.
//
// protects=each boundary a pid crosses to the operating system resolves a virtual pid to the real process: child_process
//   argument lists (spawn, spawnSync, execFile, execFileSync, fork), command strings (exec, execSync), the environment
//   given to a child, /proc/<pid> paths (sync, callback, promise) without changing stat results (inode numbers), os.getPriority / os.setPriority, process.kill,
//   and another process of the run (a worker running detjs: through <run dir>/vpid/); and a pid that differs between two runs and changes a test's outcome is never called stable;
// fails_when=a test does not see a virtual pid (above 4194304: on ea110c8 it sees the real one), or the operating
//   system cannot find the process behind it at any boundary listed, or the parity case is called stable;
// no_claim=native code (getpid(2) in an addon), and a process that does not run detjs (a child the test started:
//   src/runners/preload.js leaves it alone) handed the number over a socket or in a file, still see the virtual number.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const native = require('../src/native');
const { project, run, RUNNERS } = require('./helpers');

const T = { timeout: 600000 };
const OUT = fs.mkdtempSync(path.join(os.tmpdir(), 'p1cb-'));
const VOL = { FENVIX_VOLATILE_ENV: 'P1C_OUT,P1C_RUN' };
const CP = {
  vitest: "import cp from 'node:child_process'; import { openSync as nOpen, fstatSync as nFstat, lstatSync as nLstat, statSync as nStat, closeSync as nClose } from 'node:fs';",
  jest: "const cp = require('node:child_process'); const { openSync: nOpen, fstatSync: nFstat, lstatSync: nLstat, statSync: nStat, closeSync: nClose } = require('node:fs');",
};
const V = 'expect(process.pid > 4194304).toBe(true);';

// boundary -> the body of one test (`pid` is the virtual pid the test sees)
const CASES = {
  'ps -o lstart= -p <pid> (ironcurtain docker-resource-lifecycle.ts:76)': `${V}
    const out = cp.execFileSync('ps', ['-o', 'lstart=', '-p', String(process.pid)], { encoding: 'utf8', env: { ...process.env, LC_ALL: 'C', TZ: 'UTC' } }).trim();
    expect(out.length > 0).toBe(true);`,
  'spawnSync argument list': `${V}
    const r = cp.spawnSync('kill', ['-0', String(process.pid)]);
    expect(r.status).toBe(0);`,
  'spawn argument list': `${V}
    const code = await new Promise((res) => cp.spawn('kill', ['-0', String(process.pid)]).on('exit', res));
    expect(code).toBe(0);`,
  'execFile argument list': `${V}
    const code = await new Promise((res) => cp.execFile('kill', ['-0', String(process.pid)], (e) => res(e ? e.code : 0)));
    expect(code).toBe(0);`,
  'exec command string': `${V}
    const code = await new Promise((res) => cp.exec('kill -0 ' + process.pid, (e) => res(e ? e.code : 0)));
    expect(code).toBe(0);`,
  'execSync command string': `${V}
    cp.execSync('kill -0 ' + process.pid + ' && test -d /proc/' + process.pid);`,
  'child environment': `${V}
    const r = cp.spawnSync('sh', ['-c', 'kill -0 "$P1C_PID"'], { env: { ...process.env, P1C_PID: String(process.pid) } });
    expect(r.status).toBe(0);`,
  'fork argument list': `${V}
    const f = path.join(process.env.P1C_OUT, 'fork-child.cjs');
    fs.writeFileSync(f, "process.exitCode = process.ppid === Number(process.argv[2]) ? 0 : 3;");
    const code = await new Promise((res) => cp.fork(f, [String(process.pid)]).on('exit', res));
    expect(code).toBe(0);`,
  '/proc/<pid> paths': `${V}
    const stat = fs.readFileSync('/proc/' + process.pid + '/stat', 'utf8');
    expect(stat.length > 0).toBe(true);
    expect(fs.existsSync('/proc/' + process.pid)).toBe(true);
    const st = await fs.promises.readFile('/proc/' + process.pid + '/status', 'utf8');
    expect(st.includes('Pid:')).toBe(true);
    await new Promise((res, rej) => fs.readFile('/proc/' + process.pid + '/cmdline', (e) => (e ? rej(e) : res())));`,
  'os.getPriority / os.setPriority': `${V}
    expect(os.getPriority(process.pid)).toBe(os.getPriority());
    os.setPriority(process.pid, os.getPriority());`,
  // the /proc wrappers must not break the virtual inode numbers (src/fstime.js keeps its wrapper outermost: a wrapper
  // installed over it made lstatSync and fstatSync disagree, ironcurtain's src/docker/ca.ts:345 identity check)
  'stat identity unchanged by the /proc wrappers': `${V}
    const d = fs.mkdtempSync(path.join(os.tmpdir(), 'p1cs-'));
    // named bindings, taken at import as ca.ts does: they keep the function they got then
    const fd = nOpen(d, 'r');
    const a = nFstat(fd); const b = nLstat(d); const c = nStat(d);
    nClose(fd);
    expect([a.ino === b.ino, a.dev === b.dev, b.ino === c.ino]).toEqual([true, true, true]);`,
  'process.kill': `${V}
    expect(process.kill(process.pid, 0)).toBe(true);`,
};

function trace(r, dir, name) {
  const p = path.join(dir, `${name}.jsonl`);
  fs.copyFileSync(r.tracePath, p);
  return p;
}

for (const runner of RUNNERS) {
  const names = Object.keys(CASES);
  const body = `${CP[runner]}\n` + names.map((n, i) => `test(${JSON.stringify(`b${i} ${n}`)}, async () => {\n    ${CASES[n]}\n});`).join('\n');
  let outcomes = null;
  const outcomesOf = () => {
    if (outcomes) return outcomes;
    const dir = project(runner, 'p1c-bound', { b: body });
    const r = run(runner, dir, ['--det', '--det-workers=1'], { env: { ...VOL, P1C_OUT: OUT, P1C_RUN: `${runner}b` } });
    outcomes = { r, by: Object.fromEntries(Object.entries(r.outcomes).map(([k, s]) => [k.replace(/^.* > /, ''), s])) };
    return outcomes;
  };
  names.forEach((n, i) => {
    test(`P1 C ${runner}: the virtual pid reaches the real process at the boundary: ${n}`, T, () => {
      const { r, by } = outcomesOf();
      assert.equal(by[`b${i} ${n}`], 'passed', `${JSON.stringify(by)}\n${r.stdout}\n${r.stderr}`);
    });
  });

  // another process of the run: file a (one worker) publishes its virtual pid, file b (another worker) checks it
  test(`P1 C ${runner}: another process of the run reaches a file's virtual pid through the run's table`, T, () => {
    // The two files talk through files written and read by child processes (`sh`, `cat`): detjs' parallel planner
    // pins two test files that share a file through the test's own fs calls to one lane (one after the other), and
    // this case needs them running at the same time. Waits are real time and keep the event loop free (the test
    // timers are virtual; a blocked worker would hold back its runner's messages): a `sleep` child per step.
    const io = `${CP[runner]}
      const put = (f, v) => cp.execFileSync('sh', ['-c', 'printf %s "$2" > "$1"', 'sh', f, v]);
      const get = (f) => cp.execFileSync('sh', ['-c', 'cat "$1" 2>/dev/null || true', 'sh', f], { encoding: 'utf8' });
      const until = async (f) => { for (let i = 0; i < 300 && !get(f); i++) await new Promise((r) => cp.execFile('sleep', ['0.1'], r)); return get(f); };
      const X = (n) => path.join(process.env.P1C_OUT, n + '-' + process.env.P1C_RUN);`;
    const a = `${io} test('a', async () => { ${V}
      put(X('xa'), String(process.pid).split('').join('-')); // spelled out: a decimal pid in a child's argument is mapped
      expect(await until(X('xb'))).toBe('done');
    }, 60000);`;
    const b = `${io} test('b', async () => {
      const p = Number((await until(X('xa'))).split('-').join(''));
      try {
        expect(p > 4194304 && p !== process.pid).toBe(true);
        expect(process.kill(p, 0)).toBe(true);
        expect(fs.readFileSync('/proc/' + p + '/stat', 'utf8').length > 0).toBe(true);
      } finally { put(X('xb'), 'done'); }
    }, 60000);`;
    const dir = project(runner, 'p1c-table', { a, b });
    const r = run(runner, dir, ['--det', '--det-workers=2'], { env: { ...VOL, P1C_OUT: OUT, P1C_RUN: `${runner}x` } });
    assert.equal(r.status, 0, r.stdout + r.stderr);
  });

  // acceptance 2: the pid decides the outcome (odd fails); two seeds whose pids differ in parity -> not stable
  test(`P1 C ${runner}: a different pid that changes the outcome is reported diverged or NOT PROVEN`, T, () => {
    const dir = project(runner, 'p1c-parity', { p: `test('p1', () => { fs.writeFileSync(path.join(process.env.P1C_OUT, 'par-' + process.env.P1C_RUN), String(process.pid)); expect(process.pid % 2).toBe(0); });` });
    const runs = [];
    for (let seed = 1; seed <= 12; seed++) {
      const r = run(runner, dir, ['--det', `--det-seed=${seed}`, '--det-workers=1'], { env: { ...VOL, P1C_OUT: OUT, P1C_RUN: `${runner}s${seed}` } });
      const pid = Number(fs.readFileSync(path.join(OUT, `par-${runner}s${seed}`), 'utf8'));
      assert.ok(pid > 4194304, `seed ${seed}: the test saw a real pid ${pid}`);
      runs.push({ pid, t: trace(r, dir, `s${seed}`), status: r.status });
      if (new Set(runs.map((x) => x.pid % 2)).size === 2) break;
    }
    const even = runs.find((x) => x.pid % 2 === 0);
    const odd = runs.find((x) => x.pid % 2 === 1);
    assert.ok(even && odd, `no two seeds of 12 gave pids of different parity: ${runs.map((x) => x.pid)}`);
    assert.equal(even.status, 0);
    assert.notEqual(odd.status, 0);
    const rep = JSON.parse(native.verify([even.t, odd.t]));
    const t = rep.tests.find((x) => x.nodeid.endsWith('p1'));
    assert.ok(t && ['diverged', 'not_proven'].includes(t.status), JSON.stringify(t));
  });
}
