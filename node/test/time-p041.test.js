'use strict';
// P-041 package "time, timers and scheduling under --det" (rows JS-02, F-06): the gaps of the 2026-11-20 audit,
// each with its regression test. Every test runs on Vitest and Jest (DETJS_TEST_RUNNERS selects).
//
//   file times   G-0143 (file timestamps on the virtual clock, utimes inverse), G-1410 (stat ino/dev, cache)
//   runner       G-0144 (the runners' test and hook timeouts on the virtual clock, J15)
//   Level 1      G-0463 G-0464 (sched.* events), G-1478 (timer against local I/O), G-1484 (idle workers),
//                G-1435 (stdio), G-1412 (parallel directory walks), G-1411 (fs.watch events)
//   others       G-1434 (Temporal.Now), G-1468 (Jest legacy fake timers), G-2167 (Buffer.allocUnsafe),
//                G-2168 (ShadowRealm)
// Run: cd node && node --test test/time-p041.test.js
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { fixture, crun, show, reused, trace } = require('./runner-helpers');
const native = require('../src/native');

const T = { timeout: 600000 };
const RUNNERS = (process.env.DETJS_TEST_RUNNERS || 'vitest,jest').split(',').filter((r) => r === 'vitest' || r === 'jest');
const NODE24 = fs.existsSync('/opt/node24/bin/node') ? '/opt/node24/bin/node' : null;

const EXT = { vitest: '.test.mjs', jest: '.test.js' };
const HEAD = {
  vitest: "import { test, expect, beforeEach, vi } from 'vitest'; import fs from 'node:fs'; import path from 'node:path'; import os from 'node:os'; import cp from 'node:child_process'; import http from 'node:http'; import wt from 'node:worker_threads'; import { setTimeout as sleep } from 'node:timers/promises'; const fake = vi;",
  jest: "const fs = require('node:fs'); const path = require('node:path'); const os = require('node:os'); const cp = require('node:child_process'); const http = require('node:http'); const wt = require('node:worker_threads'); const { setTimeout: sleep } = require('node:timers/promises'); const fake = jest;",
};
const PUT = "const put = (k, v) => { fs.mkdirSync('out', { recursive: true }); fs.writeFileSync(path.join('out', k + '.txt'), String(v)); };";
const got = (dir, k) => fs.readFileSync(path.join(dir, 'out', `${k}.txt`), 'utf8');

function proj(runner, name, files, extra = {}, execArgv = null) {
  const f = {};
  const ea = execArgv ? `, execArgv: ${JSON.stringify(execArgv)}` : '';
  if (runner === 'vitest') f['vitest.config.mjs'] = `export default { test: { include: ['t/**/*.test.mjs']${ea} } };\n`;
  else f['jest.config.js'] = `module.exports = { testMatch: ['**/t/**/*.test.js'], testEnvironment: 'node' };\n`;
  for (const [n, body] of Object.entries(files)) f[`t/${n}${EXT[runner]}`] = `${HEAD[runner]}\n${PUT}\n${body}\n`;
  return fixture(`time-${runner}`, name, { ...f, ...extra });
}
const args = (runner, a = []) => (runner === 'vitest' ? ['run', ...a] : a);
const { spawnSync } = require('node:child_process');
const { BIN } = require('./helpers');

/** A detjs run; `o.node` / `o.nodeArgs`: another Node binary or V8 flags (Temporal, ShadowRealm). */
function run(runner, dir, a = [], o = {}) {
  if (!o.node && !o.nodeArgs) return crun(runner, dir, args(runner, a), { cache: false, ...o });
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_SEED', 'DETJS_CACHE_DIR']) delete env[k];
  const r = spawnSync(o.node || process.execPath, [...(o.nodeArgs || []), BIN, runner, ...(o.det || ['--det']), ...args(runner, a)],
    { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  return { status: r.status, summary: null, stdout: r.stdout || '', stderr: r.stderr || '' };
}
const fileOf = (runner, n) => `t/${n}${EXT[runner]}`;
const all = (r) => `${r.stdout}\n${r.stderr}`;

/** Events of a test in the merged trace: [[source, op, site, value], ...] (from the per-test event list). */
function events(dir, nodeidPart) {
  const lines = fs.readFileSync(path.join(dir, '.detjs', 'trace.jsonl'), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
  const t = lines.find((l) => l.type === 'test' && l.nodeid.includes(nodeidPart));
  assert.ok(t, `no test ${nodeidPart} in the trace`);
  return (t.events || []).map((e) => [e.s, e.o, e.at, e.v]);
}

function verify(dir, a, b) {
  return JSON.parse(native.verify([a, b]));
}

function timed(fn) {
  const t0 = Date.now();
  const r = fn();
  r.ms = Date.now() - t0;
  return r;
}

module.exports = { proj, run, events, got, fileOf, all, verify, timed, RUNNERS, T, NODE24, show, reused, trace };

for (const runner of RUNNERS) {
  describe(`${runner}: runner timeouts on the virtual clock (G-0144)`, () => {
    test('G-0144: a test and a hook within their virtual timeout pass however long they take in real time', T, () => {
      // 6 iterations: 10 virtual ms each, 150 real ms each (a blocking child process): ~0.9 s real, 60 virtual ms,
      // against a 500 ms timeout
      const body = "for (let i = 0; i < 6; i++) { await sleep(10); cp.spawnSync('sleep', ['0.15']); }";
      const dir = proj(runner, 'virtual-timeout', {
        a: `beforeEach(async () => { ${body} }, 500);
test('slow in real time', async () => { ${body} put('done', 'yes'); }, 500);`,
      });
      const r = run(runner, dir);
      assert.equal(r.status, 0, show(r));
      assert.equal(got(dir, 'done'), 'yes');
    });

    test('G-0144: a test whose virtual time passes its timeout fails with the runner timeout at once', T, () => {
      const dir = proj(runner, 'virtual-exceeded', {
        a: "test('too long', async () => { await sleep(60000); }, 1000);",
      });
      const r = timed(() => run(runner, dir));
      assert.notEqual(r.status, 0, show(r));
      assert.match(all(r), /timed out in 1000ms|Exceeded timeout of 1000 ms/, show(r));
      const ev = events(dir, 'too long');
      assert.ok(ev.some((e) => e[1] === 'runner.timeout' && e[3] === 'virtual:1000'), JSON.stringify(ev));
    });

    test('G-0144: a background timer does not fire the runner deadline while local I/O or thread-pool work runs', T, () => {
      // an HTTP server starts a 30 s interval of its own; a polling interval runs while pbkdf2 and zlib work in the
      // thread pool (not libuv requests): none of them may push virtual time past the 2 s timeout before the work ends
      const dir = proj(runner, 'background', {
        a: `test('loopback', async () => {
  const s = http.createServer((q, r) => r.end('ok'));
  await new Promise((r) => s.listen(0, '127.0.0.1', r));
  const body = await new Promise((res) => http.get({ host: '127.0.0.1', port: s.address().port }, (r) => { let d = ''; r.on('data', (c) => { d += c; }); r.on('end', () => res(d)); }));
  s.close();
  put('body', body);
}, 2000);
test('thread pool', async () => {
  const crypto = typeof require === 'function' ? require('node:crypto') : process.getBuiltinModule('node:crypto');
  const zlib = typeof require === 'function' ? require('node:zlib') : process.getBuiltinModule('node:zlib');
  let ticks = 0;
  const iv = setInterval(() => { ticks++; }, 10);
  await new Promise((r, j) => crypto.pbkdf2('pw', 'salt', 400000, 32, 'sha256', (e) => (e ? j(e) : r())));
  await new Promise((r, j) => zlib.gzip(Buffer.alloc(1 << 22), (e) => (e ? j(e) : r())));
  clearInterval(iv);
  put('pool', 'done');
}, 2000);`,
      });
      const r = run(runner, dir);
      assert.equal(r.status, 0, show(r));
      assert.equal(got(dir, 'body'), 'ok');
      assert.equal(got(dir, 'pool'), 'done');
    });

    test('G-0144: a test that truly hangs still fails with the runner timeout (real watchdog)', T, () => {
      const dir = proj(runner, 'hangs', {
        a: "test('hangs', async () => { await new Promise(() => {}); }, 700);\ntest('after', () => { put('after', 'ran'); });",
      });
      const r = run(runner, dir);
      assert.notEqual(r.status, 0, show(r));
      assert.match(all(r), /timed out in 700ms|Exceeded timeout of 700 ms/, show(r));
      assert.equal(got(dir, 'after'), 'ran');
      const ev = events(dir, 'hangs');
      assert.ok(ev.some((e) => e[1] === 'runner.timeout' && e[3] === 'real:700'), JSON.stringify(ev));
    });
  });
}

const RACE = `
const srv = http.createServer((q, s) => s.end('pong'));
const get = (port) => new Promise((res, rej) => http.get({ host: '127.0.0.1', port, path: '/', agent: false }, (r) => { let b = ''; r.on('data', (c) => { b += c; }); r.on('end', () => res(b)); }).on('error', rej));
test('race', async () => {
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  await get(srv.address().port); // warm-up (not raced)
  const wins = [];
  for (let i = 0; i < 5; i++) {
    const ac = new AbortController();
    wins.push(await Promise.race([get(srv.address().port).then(() => 'io'), sleep(3, 'timer', { signal: ac.signal }).catch(() => 'aborted')]));
    ac.abort();
  }
  await new Promise((r) => srv.close(r));
  put('wins', wins.join(','));
});`;

const IDLE = `
test('stdio', async () => { void process.stdout.isTTY; void process.stdin; await sleep(20000); put('stdio', 'ok'); }, 60000);
test('idle worker', async () => {
  const w = new wt.Worker("const { parentPort } = require('node:worker_threads'); parentPort.on('message', (m) => parentPort.postMessage(m));", { eval: true });
  const echo = (m) => new Promise((r) => { w.once('message', r); w.postMessage(m); });
  expect(await echo('ping')).toBe('ping');
  await sleep(20000);
  put('worker', 'ok');
  put('busy', await Promise.race([echo('again'), sleep(1000).then(() => 'timer')]));
  await w.terminate();
}, 60000);`;

const WALK = `
test('parallel walks', async () => {
  fs.rmSync('w', { recursive: true, force: true });
  fs.mkdirSync('w/big', { recursive: true }); fs.mkdirSync('w/small', { recursive: true });
  for (let i = 0; i < 4000; i++) fs.writeFileSync('w/big/f' + i, '');
  fs.writeFileSync('w/small/a', '');
  const order = [];
  await Promise.all([fs.promises.readdir('w/big').then(() => order.push('big')), fs.promises.readdir('w/small').then(() => order.push('small'))]);
  const cb = [];
  await new Promise((done) => { let n = 0; const fin = (k) => () => { cb.push(k); if (++n === 2) done(); }; fs.readdir('w/big', fin('big')); fs.readdir('w/small', fin('small')); });
  put('order', order.join() + ';' + cb.join());
});`;

const WATCH = `
test('watch', async () => {
  fs.mkdirSync('wd', { recursive: true });
  const w = fs.watch('wd');
  const ev = new Promise((r) => w.once('change', (t, f) => r(String(f))));
  fs.writeFileSync('wd/x.txt', String(Math.random()));
  put('watched', await ev);
  w.close();
});`;

for (const runner of RUNNERS) {
  describe(`${runner}: Level 1, timers against I/O`, () => {
    test('G-1478 G-0463 G-0464: a timer racing local I/O: I/O first in every run, the choice recorded (sched.io)', T, () => {
      const dir = proj(runner, 'race', { a: RACE });
      const r1 = run(runner, dir);
      assert.equal(r1.status, 0, show(r1));
      assert.equal(got(dir, 'wins'), 'io,io,io,io,io');
      const ev = events(dir, 'race');
      const s = ev.filter((e) => e[0] === 'sched');
      assert.ok(s.length >= 5 && s.every((e) => /^sched\.(io|timer)$/.test(e[1]) && /^\d+\/\d+:/.test(e[3])), JSON.stringify(ev));
      fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), path.join(dir, 'run1.jsonl'));
      const r2 = run(runner, dir);
      assert.equal(r2.status, 0, show(r2));
      assert.equal(got(dir, 'wins'), 'io,io,io,io,io');
      const rep = verify(dir, path.join(dir, 'run1.jsonl'), path.join(dir, '.detjs', 'trace.jsonl'));
      assert.equal(rep.summary.stable, rep.summary.tests, JSON.stringify(rep.summary));
    });

    test('G-1435 G-1484: stdio and an idle worker do not turn virtual timers into real waits; a busy worker does', T, () => {
      const dir = proj(runner, 'idle', { a: IDLE });
      const r = timed(() => run(runner, dir));
      assert.equal(r.status, 0, show(r));
      assert.equal(got(dir, 'stdio'), 'ok');
      assert.equal(got(dir, 'worker'), 'ok');
      assert.equal(got(dir, 'busy'), 'again', 'a busy worker answers before a 1 s virtual timer');
      assert.ok(r.ms < 15000, `two 20 s virtual sleeps took ${r.ms} ms of real time`);
    });

    test('G-1412: concurrent directory reads complete in start order (promises and callbacks)', T, () => {
      const dir = proj(runner, 'walk', { a: WALK });
      for (let i = 0; i < 2; i++) {
        const r = run(runner, dir);
        assert.equal(r.status, 0, show(r));
        assert.equal(got(dir, 'order'), 'big,small;big,small');
      }
      const ev = events(dir, 'parallel walks');
      assert.ok(ev.some((e) => e[1] === 'io.complete' && e[3] === 'fs.readdir#0'), JSON.stringify(ev));
    });

    test('G-1411: fs.watch events delivered to the test are recorded', T, () => {
      const dir = proj(runner, 'watch', { a: WATCH });
      const r = run(runner, dir);
      assert.equal(r.status, 0, show(r));
      assert.equal(got(dir, 'watched'), 'x.txt');
      const ev = events(dir, 'watch');
      assert.ok(ev.some((e) => e[1] === 'fs.watch' && e[3].includes('x.txt')), JSON.stringify(ev));
    });
  });
}

const FILES = `
test('new file', () => {
  fs.writeFileSync('f1.txt', 'x');
  const st = fs.statSync('f1.txt');
  put('age', Date.now() - st.mtimeMs);
  put('year', st.mtime.getUTCFullYear());
  const d = new Date(Date.now() - 3600e3);
  fs.utimesSync('f1.txt', d, d);
  put('roundtrip', fs.statSync('f1.txt').mtime.getTime() === d.getTime());
  fs.rmSync('f2.txt', { force: true });
  fs.linkSync('f1.txt', 'f2.txt');
  const l = fs.statSync('f2.txt');
  put('ino', [st.ino, l.ino, st.dev, fs.statSync('.').ino].join());
  fs.rmSync('f2.txt');
});
test('async stat', async () => {
  fs.writeFileSync('f3.txt', 'x');
  const st = await fs.promises.stat('f3.txt', { bigint: true });
  put('asyncAge', BigInt(Date.now()) * 1000000n - st.mtimeNs);
  await new Promise((r) => fs.stat('f3.txt', (e, s) => { put('cbYear', s.mtime.getUTCFullYear()); r(); }));
});
test('old file', () => { put('oldAge', Date.now() - fs.statSync('package.json').mtimeMs); });`;

for (const runner of RUNNERS) {
  describe(`${runner}: file times on the virtual clock (G-0143, G-1410)`, () => {
    test('G-0143 G-1410: a new file is not in the future, utimes takes virtual times, ino/dev are virtual; recorded', T, () => {
      const dir = proj(runner, 'files', { a: FILES });
      const r1 = run(runner, dir);
      assert.equal(r1.status, 0, show(r1));
      const age = Number(got(dir, 'age'));
      assert.ok(age >= 0 && age < 1000, `new file age ${age} ms`);
      assert.equal(got(dir, 'year'), '2025');
      assert.equal(got(dir, 'roundtrip'), 'true');
      assert.equal(got(dir, 'ino'), '1,1,1,2');
      const aage = BigInt(got(dir, 'asyncAge'));
      assert.ok(aage >= 0n && aage < 1000000000n, `bigint age ${aage}`);
      assert.equal(got(dir, 'cbYear'), '2025');
      const oldAge = Number(got(dir, 'oldAge'));
      assert.ok(oldAge > 0 && oldAge < 3600e3, `an existing file keeps its age: ${oldAge}`);
      // the file on disk has the real time the virtual time maps to (an hour before the real test start)
      const real = fs.statSync(path.join(dir, 'f1.txt')).mtimeMs;
      assert.ok(Math.abs(real - (Date.now() - 3600e3)) < 300e3, `real mtime ${new Date(real).toISOString()}`);
      const ev = events(dir, 'new file');
      assert.ok(ev.some((e) => e[1] === 'fs.stat.mtimeMs') && ev.some((e) => e[1] === 'fs.stat.ino' && e[3] === '1'), JSON.stringify(ev));
      fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), path.join(dir, 'run1.jsonl'));
      const r2 = run(runner, dir);
      assert.equal(r2.status, 0, show(r2));
      const rep = verify(dir, path.join(dir, 'run1.jsonl'), path.join(dir, '.detjs', 'trace.jsonl'));
      const byId = Object.fromEntries((rep.tests || []).map((t) => [t.nodeid, t]));
      const st = (n) => JSON.stringify(byId[`${fileOf(runner, 'a')}::${n}`]);
      assert.match(st('new file'), /"stable":true|"status":"stable"/, JSON.stringify(rep));
      assert.match(st('async stat'), /"stable":true|"status":"stable"/, JSON.stringify(rep));
      assert.doesNotMatch(st('old file'), /"stable":true|"status":"stable"/, `the age of an existing file depends on when the run happens\n${JSON.stringify(rep)}`);
    });

    test('G-0143: the cache never reuses a test that read a file time mapped from the real clock', T, () => {
      const dir = proj(runner, 'files-cache', {
        b: "test('old file', () => { expect(Number.isFinite(fs.statSync('package.json').mtimeMs)).toBe(true); });",
        c: "test('size only', () => { expect(fs.statSync('package.json').size > 0).toBe(true); });",
      });
      const r1 = run(runner, dir, [], { cache: true });
      assert.equal(r1.status, 0, show(r1));
      const r2 = run(runner, dir, [], { cache: true });
      assert.equal(r2.status, 0, show(r2));
      assert.ok(reused(r2).includes(fileOf(runner, 'c')), show(r2));
      assert.ok(!reused(r2).includes(fileOf(runner, 'b')), `WRONG REUSE\n${show(r2)}`);
      assert.match(JSON.stringify(r1.summary.not_cached_detail), /fs\.stat mtimeMs/, show(r1));
    });
  });

  describe(`${runner}: Temporal, Buffer, ShadowRealm, legacy fake timers`, () => {
    test('G-2167: Buffer.allocUnsafe / allocUnsafeSlow are zero-filled under --det', T, () => {
      const dir = proj(runner, 'unsafe', {
        a: `test('unsafe', () => {
  const req = typeof require === 'function' ? require : process.getBuiltinModule;
  req('node:v8').setFlagsFromString('--expose-gc'); const gc = req('node:vm').runInNewContext('gc');
  for (let i = 0; i < 50; i++) { Buffer.allocUnsafeSlow(1 << 16).fill(0xab); gc(); }
  let dirty = 0;
  for (let i = 0; i < 50; i++) { if (Buffer.allocUnsafeSlow(1 << 16).some((x) => x !== 0)) dirty++; if (Buffer.allocUnsafe(4096).some((x) => x !== 0)) dirty++; }
  put('dirty', dirty);
});`,
      });
      const r = run(runner, dir);
      assert.equal(r.status, 0, show(r));
      assert.equal(got(dir, 'dirty'), '0');
    });

    test('G-1468: Jest legacy fake timers restore the virtual timers', { ...T, skip: runner !== 'jest' }, () => {
      const dir = proj(runner, 'legacy', {
        a: "test('legacy', async () => { jest.useFakeTimers({ legacyFakeTimers: true }); jest.useRealTimers(); await new Promise((r) => setTimeout(r, 8000)); put('done', 'yes'); }, 30000);",
      });
      const r = timed(() => run(runner, dir));
      assert.equal(r.status, 0, show(r));
      assert.ok(r.ms < 7000, `an 8 s virtual timer took ${r.ms} ms`);
      const ev = events(dir, 'legacy');
      assert.ok(ev.some((e) => e[1] === 'setTimeout' && e[3] === 'schedule:8000000000'), JSON.stringify(ev));
    });

    test('G-1434: Temporal.Now on the virtual clock (Node 24 --harmony-temporal)', { ...T, skip: NODE24 ? false : 'no Node 24' }, () => {
      const dir = proj(runner, 'temporal', {
        a: "test('temporal', () => { put('ms', Temporal.Now.instant().epochMilliseconds); put('date', Temporal.Now.plainDateISO('UTC').toString()); put('z', Temporal.Now.zonedDateTimeISO('UTC').year); });",
      }, {}, ['--harmony-temporal']);
      const r = run(runner, dir, [], { node: NODE24, nodeArgs: ['--harmony-temporal'] });
      assert.equal(r.status, 0, show(r));
      const ms = Number(got(dir, 'ms'));
      assert.ok(ms >= Date.parse('2025-01-01T00:00:00Z') && ms < Date.parse('2025-01-01T00:00:01Z'), `instant ${ms}`);
      assert.equal(got(dir, 'date'), '2025-01-01');
      assert.equal(got(dir, 'z'), '2025');
      const ev = events(dir, 'temporal');
      assert.ok(ev.some((e) => e[1] === 'Temporal.Now.instant'), JSON.stringify(ev));
    });

    test('G-2168: a ShadowRealm gets the seeded Math.random and the virtual Date', T, () => {
      const dir = proj(runner, 'shadow', {
        a: "test('shadow', () => { const r = new ShadowRealm(); put('rnd', r.evaluate('Math.random()')); put('now', r.evaluate('Date.now()')); put('date', r.evaluate('new Date().getUTCFullYear()')); });",
      }, {}, ['--experimental-shadow-realm']);
      const r1 = run(runner, dir, [], { nodeArgs: ['--experimental-shadow-realm'] });
      assert.equal(r1.status, 0, show(r1));
      const rnd1 = got(dir, 'rnd');
      const now = Number(got(dir, 'now'));
      assert.ok(now >= Date.parse('2025-01-01T00:00:00Z') && now < Date.parse('2025-01-01T00:00:01Z'), `Date.now ${now}`);
      assert.equal(got(dir, 'date'), '2025');
      const r2 = run(runner, dir, [], { nodeArgs: ['--experimental-shadow-realm'] });
      assert.equal(r2.status, 0, show(r2));
      assert.equal(got(dir, 'rnd'), rnd1, 'the same draw in every run');
    });
  });
}
