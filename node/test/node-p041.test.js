'use strict';
// P-041 (rows JS-02, F-06, JS-09): the Node wrong-result gaps of the 2026-11-20 audit, closed by family, each with
// its regression test. Every test runs on Vitest and Jest (DETJS_TEST_RUNNERS selects).
//
//   clock      G-0122 G-0142 (runner fake timers start from the real clock), G-0123 (--det-disable=time with the
//              cache), G-0120 (virtual day), G-0121 (nightly real-clock run), G-0135 process.uptime, G-0136
//              performance.timeOrigin, G-0137 performance.mark/measure, G-0138 AbortSignal.timeout, G-0141
//              perf_hooks.performance under Jest
// Run: cd node && node --test test/node-p041.test.js
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { fixture, crun, show, reused, trace } = require('./runner-helpers');
const native = require('../src/native');

const T = { timeout: 600000 };
const RUNNERS = (process.env.DETJS_TEST_RUNNERS || 'vitest,jest').split(',').filter((r) => r === 'vitest' || r === 'jest');

const EXT = { vitest: '.test.mjs', jest: '.test.js' };
const HEAD = {
  vitest: "import { test, expect, vi } from 'vitest'; import fs from 'node:fs'; import path from 'node:path'; import { performance as hp } from 'node:perf_hooks'; const fake = vi;",
  jest: "const fs = require('node:fs'); const path = require('node:path'); const { performance: hp } = require('node:perf_hooks'); const fake = jest;",
};

/** A Vitest or Jest fixture with test files `files` = {name: body}; bodies use `fake` for vi / jest. */
function proj(runner, name, files, extra = {}) {
  const f = {};
  if (runner === 'vitest') f['vitest.config.mjs'] = `export default { test: { include: ['t/**/*.test.mjs'] } };\n`;
  else f['jest.config.js'] = `module.exports = { testMatch: ['**/t/**/*.test.js'], testEnvironment: 'node' };\n`;
  for (const [n, body] of Object.entries(files)) f[`t/${n}${EXT[runner]}`] = `${HEAD[runner]}\n${body}\n`;
  return fixture(`p041-${runner}`, name, { ...f, ...extra });
}

const args = (runner, a = []) => (runner === 'vitest' ? ['run', ...a] : a);
const run = (runner, dir, a = [], o = {}) => crun(runner, dir, args(runner, a), o);
const fileOf = (runner, n) => `t/${n}${EXT[runner]}`;

/** Values a test printed as `name=value` lines into out/<name>.txt (stable across runners' output formats). */
const PUT = "const put = (k, v) => { fs.mkdirSync('out', { recursive: true }); fs.writeFileSync(path.join('out', k + '.txt'), String(v)); };";
const got = (dir, k) => fs.readFileSync(path.join(dir, 'out', `${k}.txt`), 'utf8');

function receipt(dir, nodeid) {
  const lines = fs.readFileSync(path.join(dir, '.detjs', 'receipts.jsonl'), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
  return lines.find((l) => l.nodeid === nodeid);
}

for (const runner of RUNNERS) {
  describe(`${runner}: clock family`, () => {
    test('G-0142: runner fake timers start at the virtual epoch, recorded; two runs identical', T, () => {
      const dir = proj(runner, 'fake-epoch', {
        a: `${PUT}\ntest('fake now', () => { fake.useFakeTimers(); put('fake', Date.now()); put('fakeDate', new Date().toISOString()); fake.useRealTimers(); });`,
      });
      const r1 = run(runner, dir, [], { cache: false });
      assert.equal(r1.status, 0, show(r1));
      assert.equal(got(dir, 'fake'), String(Date.parse('2025-01-01T00:00:00Z')), 'fake clock starts at the virtual epoch');
      assert.equal(got(dir, 'fakeDate'), '2025-01-01T00:00:00.000Z');
      const t1 = trace(dir);
      fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), path.join(dir, 'run1.jsonl'));
      const ev = t1.tests[Object.keys(t1.tests)[0]];
      assert.ok(ev.events && Object.keys(ev.events).some((k) => /time/.test(k)) || JSON.stringify(ev).includes('time'), JSON.stringify(ev));
      const r2 = run(runner, dir, [], { cache: false });
      assert.equal(r2.status, 0, show(r2));
      const rep = JSON.parse(native.verify([path.join(dir, 'run1.jsonl'), path.join(dir, '.detjs', 'trace.jsonl')]));
      assert.equal(rep.summary.stable, rep.summary.tests, JSON.stringify(rep.summary));
    });

    test('G-0122: a fake-timer test that reads the date is keyed by the epoch (no reuse on another day)', T, () => {
      const dir = proj(runner, 'fake-reuse', {
        a: "test('before expiry', () => { fake.useFakeTimers(); const now = Date.now(); fake.useRealTimers(); expect(now < Date.parse('2025-06-01T00:00:00Z')).toBe(true); });",
      });
      const day1 = ['--det-epoch=2025-01-01T00:00:00Z'];
      const day2 = ['--det-epoch=2025-07-01T00:00:00Z'];
      const r1 = run(runner, dir, [], { det: ['--det', ...day1] });
      assert.equal(r1.status, 0, show(r1));
      const r2 = run(runner, dir, [], { det: ['--det', ...day1] });
      assert.ok(reused(r2).includes(fileOf(runner, 'a')), show(r2));
      const rc = receipt(dir, `${fileOf(runner, 'a')}::before expiry`);
      assert.ok(rc && rc.epoch !== null && rc.epoch !== undefined, `the epoch is an input: ${JSON.stringify(rc)}`);
      const fresh = run(runner, dir, [], { cache: false, det: ['--det', ...day2] });
      assert.notEqual(fresh.status, 0, show(fresh));
      const r3 = run(runner, dir, [], { det: ['--det', ...day2] });
      assert.ok(!reused(r3).includes(fileOf(runner, 'a')), `WRONG REUSE\n${show(r3)}`);
      assert.notEqual(r3.status, 0, show(r3));
    });

    test('G-0123: --det-disable=time (or seeds, net, fs) switches the cache off for the session', T, () => {
      const dir = proj(runner, 'disable-time', { a: "test('date', () => { expect(new Date().getFullYear() > 2000).toBe(true); });" });
      for (const off of ['time', 'seeds', 'net', 'fs']) {
        const r1 = run(runner, dir, [], { det: ['--det', `--det-disable=${off}`] });
        assert.equal(r1.status, 0, show(r1));
        assert.match(r1.stdout + r1.stderr, new RegExp(`cache: off for this session \\(Level 0 control\\(s\\) off: ${off}`), show(r1));
        const r2 = run(runner, dir, [], { det: ['--det', `--det-disable=${off}`] });
        assert.deepEqual(reused(r2), [], show(r2));
      }
    });

    test('G-0120: with the cache, the epoch is today 00:00 UTC (the virtual day)', T, () => {
      const dir = proj(runner, 'virtual-day', { a: `${PUT}\ntest('today', () => { put('now', new Date().toISOString()); });` });
      const r1 = run(runner, dir);
      assert.equal(r1.status, 0, show(r1));
      const d = new Date();
      const day = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
      assert.equal(got(dir, 'now').slice(0, 10), day.toISOString().slice(0, 10));
      const r2 = run(runner, dir);
      const rc = receipt(dir, `${fileOf(runner, 'a')}::today`);
      assert.ok(rc && rc.reused, show(r2));
      assert.equal(rc.epoch, day.getTime(), JSON.stringify(rc));
    });

    test('G-0121: --det-cache-real-clock runs on the real clock and removes expired results', T, () => {
      const d = new Date();
      const limit = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), 0, 0, 1)).toISOString();
      const dir = proj(runner, 'real-clock', {
        exp: `test('certificate still valid', () => { expect(Date.now() < Date.parse('${limit}')).toBe(true); });`,
        ok: "test('plain', () => { expect(1).toBe(1); });",
      });
      assert.equal(run(runner, dir).status, 0);
      const r2 = run(runner, dir);
      assert.ok(reused(r2).includes(fileOf(runner, 'exp')), show(r2));
      const rc = run(runner, dir, [], { det: ['--det', '--det-cache-real-clock'] });
      assert.notEqual(rc.status, 0, `the expired test fails on the real clock\n${show(rc)}`);
      assert.match(rc.stdout + rc.stderr, new RegExp(`EXPIRY ${fileOf(runner, 'exp').replace(/\./g, '\\.')}::certificate still valid: cached passed, real clock failed`), show(rc));
      assert.equal(rc.summary.expiries.filter((e) => e.nodeid.includes('::')).length, 1, show(rc));
      const r3 = run(runner, dir);
      assert.ok(!reused(r3).includes(fileOf(runner, 'exp')), `the expired file runs again\n${show(r3)}`);
      assert.ok(reused(r3).includes(fileOf(runner, 'ok')), show(r3));
    });

    test('G-0135 G-0136 G-0137 G-0138 G-0141: uptime, timeOrigin, marks, AbortSignal.timeout, perf_hooks on the virtual clock', T, () => {
      const dir = proj(runner, 'clocks', {
        a: `${PUT}
test('clocks', async () => {
  put('uptime', process.uptime());
  put('origin', performance.timeOrigin);
  const m = performance.mark('m1');
  put('mark', m.startTime);
  put('measure', performance.measure('ms', 'm1').duration);
  put('hp', hp.now());
  put('hpOrigin', hp.timeOrigin);
  const s = AbortSignal.timeout(3000);
  const first = await Promise.race([
    new Promise((res) => s.addEventListener('abort', () => res('abort:' + s.reason.name))),
    new Promise((res) => setTimeout(() => res('timer'), 10000)),
  ]);
  put('abort', first);
});`,
      });
      const vals = [];
      for (let i = 0; i < 2; i++) {
        const r = run(runner, dir, [], { cache: false });
        assert.equal(r.status, 0, show(r));
        vals.push(Object.fromEntries(['uptime', 'origin', 'mark', 'measure', 'hp', 'hpOrigin', 'abort'].map((k) => [k, got(dir, k)])));
      }
      assert.deepEqual(vals[0], vals[1], 'identical in two runs');
      const v = vals[0];
      assert.equal(v.origin, String(Date.parse('2025-01-01T00:00:00Z')));
      assert.equal(v.hpOrigin, v.origin);
      assert.ok(Number(v.uptime) >= 1 && Number(v.uptime) < 2, v.uptime);
      assert.ok(Number(v.mark) >= 1000 && Number(v.mark) < 1001, `mark on the virtual performance clock: ${v.mark}`);
      assert.ok(Number(v.hp) >= 1000 && Number(v.hp) < 1001, `perf_hooks performance.now virtual: ${v.hp}`);
      assert.equal(v.abort, 'abort:TimeoutError', 'AbortSignal.timeout(3000) fires before setTimeout(10000)');
    });
  });
}

// -- JS-09 and the processes family: native addons, worker_threads, child_process, vm contexts (G-0124, G-0125,
// G-0134, G-0152), async crypto (G-0132, G-0133), control installation (G-0181) -----------------------------------
const ADDON = path.join(__dirname, '..', `detjs.${process.platform}-${process.arch}.node`);
const REQ = {
  vitest: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url); const cp = require('node:child_process'); const wt = require('node:worker_threads'); const vm = require('node:vm'); const nodeCrypto = require('node:crypto');",
  jest: "const cp = require('node:child_process'); const wt = require('node:worker_threads'); const vm = require('node:vm'); const nodeCrypto = require('node:crypto');",
};
const evOps = (t) => Object.values(t.tests).flatMap((x) => (x.events || []).map((e) => (Array.isArray(e) ? e[1] : e.op)));

function traceEvents(dir) {
  const lines = fs.readFileSync(path.join(dir, '.detjs', 'trace.jsonl'), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
  const out = {};
  for (const l of lines) if (l.type === 'event' || l.op) (out[l.nodeid || l.test || '?'] = out[l.nodeid || l.test || '?'] || []).push(l);
  return lines;
}

function notReused(runner, dir, file, why) {
  const r1 = run(runner, dir);
  assert.equal(r1.status, 0, `run 1 must pass (the source runs)\n${show(r1)}`);
  const r2 = run(runner, dir);
  assert.equal(r2.status, 0, show(r2));
  assert.ok(!reused(r2).includes(file), `${file} must never be reused\n${show(r2)}`);
  const detail = JSON.stringify(r1.summary && r1.summary.not_cached_detail);
  assert.ok(detail.includes(why), `not cached because of ${why}: ${detail}`);
  return { r1, r2 };
}

for (const runner of RUNNERS) {
  describe(`${runner}: JS-09 native addons, worker threads, child processes`, () => {
    test('a test that loads a native addon runs and is never reused', T, () => {
      const dir = proj(runner, 'native', {
        a: `${REQ[runner]}\ntest('addon', () => { const a = require('../addon.node'); expect(typeof a.digest(Buffer.from('x'))).toBe('string'); });`,
        b: "test('plain', () => { expect(1).toBe(1); });",
        c: `${REQ[runner]}\ntest('same addon again', () => { const a = require('../addon.node'); expect(typeof a.digest(Buffer.from('y'))).toBe('string'); });`,
      });
      fs.copyFileSync(ADDON, path.join(dir, 'addon.node'));
      const { r2 } = notReused(runner, dir, fileOf(runner, 'a'), 'native addon');
      assert.ok(!reused(r2).includes(fileOf(runner, 'c')), `a second file loading the same addon is never reused either\n${show(r2)}`);
      const r3 = run(runner, dir);
      assert.ok(reused(r3).includes(fileOf(runner, 'b')), `the other file is reused\n${show(r3)}`);
    });

    test('worker_threads: the worker runs under Level 0 (seeded, virtual clock); never reused; uncontrolled.thread recorded', T, () => {
      const dir = proj(runner, 'worker', {
        a: `${REQ[runner]}\n${PUT}
test('worker', async () => {
  const code = "const { parentPort } = require('node:worker_threads'); parentPort.postMessage([Math.random(), Date.now(), require('node:crypto').randomUUID()].join('|'));";
  const v = await new Promise((res, rej) => { const w = new wt.Worker(code, { eval: true }); w.once('message', res); w.once('error', rej); });
  put('worker', v);
});`,
      });
      const vals = [];
      for (let i = 0; i < 2; i++) {
        const r = run(runner, dir, [], { cache: false });
        assert.equal(r.status, 0, show(r));
        vals.push(got(dir, 'worker'));
        fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), path.join(dir, `run${i}.jsonl`));
      }
      assert.equal(vals[0], vals[1], 'the worker is controlled: same values in two runs');
      assert.match(vals[0], /\|1735689600\d{3}\|/, `the worker's clock is virtual: ${vals[0]}`);
      const text = fs.readFileSync(path.join(dir, 'run0.jsonl'), 'utf8');
      assert.match(text, /uncontrolled\.thread/);
      assert.match(text, /worker\.message/);
      notReused(runner, dir, fileOf(runner, 'a'), 'worker thread');
    });

    test('child_process: it runs; never reused; its result is in the trace, so a different output diverges', T, () => {
      const dir = proj(runner, 'child', {
        a: `${REQ[runner]}\n${PUT}
test('child', () => {
  const out = cp.execFileSync(process.execPath, ['-e', 'process.stdout.write(require("node:fs").readFileSync("data.txt", "utf8"))'], { encoding: 'utf8' });
  put('child', out);
  expect(out.length).toBeGreaterThan(0);
});`,
      });
      fs.writeFileSync(path.join(dir, 'data.txt'), 'one');
      const r1 = run(runner, dir, [], { cache: false });
      assert.equal(r1.status, 0, show(r1));
      fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), path.join(dir, 'one.jsonl'));
      const text = fs.readFileSync(path.join(dir, 'one.jsonl'), 'utf8');
      assert.match(text, /uncontrolled\.child/);
      assert.match(text, /child\.result/);
      fs.writeFileSync(path.join(dir, 'data.txt'), 'two');
      const r2 = run(runner, dir, [], { cache: false });
      assert.equal(r2.status, 0, show(r2));
      const rep = JSON.parse(native.verify([path.join(dir, 'one.jsonl'), path.join(dir, '.detjs', 'trace.jsonl')]));
      assert.equal(rep.summary.stable, 0, `the child's different output is a divergence: ${JSON.stringify(rep.summary)}`);
      notReused(runner, dir, fileOf(runner, 'a'), 'subprocess');
    });

    test('G-0134: vm contexts created by a test get the realm controls', T, () => {
      const dir = proj(runner, 'vm', {
        a: `${REQ[runner]}\n${PUT}
test('vm', () => {
  put('vm', vm.runInNewContext('[Math.random(), Date.now(), new Date().toISOString()].join("|")'));
  const ctx = vm.createContext({});
  put('vm2', vm.runInContext('Math.random() + "|" + typeof setTimeout', ctx));
});`,
      });
      const vals = [];
      for (let i = 0; i < 2; i++) {
        const r = run(runner, dir, [], { cache: false });
        assert.equal(r.status, 0, show(r));
        vals.push([got(dir, 'vm'), got(dir, 'vm2')]);
      }
      assert.deepEqual(vals[0], vals[1]);
      assert.match(vals[0][0], /\|2025-01-01T00:00:00\.\d{3}Z$/);
      assert.match(vals[0][1], /\|undefined$/, 'a bare context gets no timers');
    });

    test('G-0132 G-0133: async crypto.randomFill / randomInt(cb) are controlled (--det-urandom) and recorded', T, () => {
      const dir = proj(runner, 'crypto-async', {
        a: `${REQ[runner]}\n${PUT}
test('async entropy', async () => {
  const b = await new Promise((res, rej) => nodeCrypto.randomFill(Buffer.alloc(8), (e, x) => (e ? rej(e) : res(x.toString('hex')))));
  const i = await new Promise((res, rej) => nodeCrypto.randomInt(1000000, (e, x) => (e ? rej(e) : res(x))));
  put('rnd', b + '|' + i);
});`,
      });
      const vals = [];
      for (let i = 0; i < 2; i++) {
        const r = run(runner, dir, [], { cache: false, det: ['--det', '--det-urandom'] });
        assert.equal(r.status, 0, show(r));
        vals.push(got(dir, 'rnd'));
      }
      assert.equal(vals[0], vals[1], 'controlled with --det-urandom');
      const r = run(runner, dir, [], { cache: false });
      assert.equal(r.status, 0, show(r));
      const text = fs.readFileSync(path.join(dir, '.detjs', 'trace.jsonl'), 'utf8');
      assert.match(text, /crypto\.randomFillSync|crypto\.randomFill/);
      assert.match(text, /crypto\.randomInt/);
    });
  });
}

// -- network family: G-0128 UDP, G-0129 keep-alive across tests, G-0130 replay of a changed request, G-0131 secrets --
const { spawn } = require('node:child_process');
const NETH = {
  vitest: "import http from 'node:http'; import dgram from 'node:dgram';",
  jest: "const http = require('node:http'); const dgram = require('node:dgram');",
};
const NETBODY = `
const lookup = (h, o, cb) => { if (typeof o === 'function') cb = o; return o && o.all ? cb(null, [{ address: '127.0.0.1', family: 4 }]) : cb(null, '127.0.0.1', 4); };
const agent = new http.Agent({ keepAlive: true, maxSockets: 1 });
function get(p) {
  return new Promise((resolve, reject) => {
    http.get({ host: 'counter.detjs.test', port: Number(process.env.COUNTER_PORT), path: p, lookup, agent,
      headers: { authorization: 'Bearer SUPERSECRETTOKEN0123456789' } }, (r) => {
      let b = ''; r.setEncoding('utf8'); r.on('data', (d) => { b += d; }); r.on('end', () => resolve(b));
    }).on('error', reject);
  });
}
test('one', async () => { expect(await get('/one' + (process.env.SUFFIX || ''))).toMatch(/^response #/); });
test('two', async () => { expect(await get('/two')).toMatch(/^response #/); });
`;

async function withCounter(fn) {
  const srv = spawn(process.execPath, [path.join(__dirname, 'counter-server.js')], { stdio: ['ignore', 'pipe', 'inherit'] });
  const ports = await new Promise((resolve) => srv.stdout.once('data', (d) => resolve(JSON.parse(String(d)))));
  try { return await fn(ports, () => srv.kill()); } finally { srv.kill(); }
}

for (const runner of RUNNERS) {
  describe(`${runner}: network family`, () => {
    test('G-0129 G-0131: keep-alive connections do not cross tests; credentials are not stored in the cassette', T, async () => {
      await withCounter(async (ports, stop) => {
        const dir = proj(runner, 'keepalive', { a: `${NETH[runner]}\n${NETBODY}` });
        const env = { COUNTER_PORT: String(ports.http) };
        const rec = run(runner, dir, [], { cache: false, det: ['--det', '--det-record'], env });
        assert.equal(rec.status, 0, show(rec));
        const cas = fs.readFileSync(path.join(dir, '.detjs', 'cassette.json'), 'utf8');
        assert.ok(!cas.includes('SUPERSECRETTOKEN') && !cas.includes(Buffer.from('SUPERSECRETTOKEN').toString('base64').slice(0, 16)), 'no credential in the cassette');
        stop();
        // the second test alone, and both in a shuffled order, replay
        const alone = run(runner, dir, ['-t', 'two'], { cache: false, env });
        assert.equal(alone.status, 0, `replaying "two" alone\n${show(alone)}`);
        for (const seed of [1, 2, 3]) {
          const sh = run(runner, dir, [], { cache: false, det: ['--det', `--det-seed=${seed}`], env });
          assert.equal(sh.status, 0, `shuffled replay (seed ${seed})\n${show(sh)}`);
        }
      });
    });

    test('G-0130: a request that differs from the recording is not answered with the recorded response', T, async () => {
      await withCounter(async (ports, stop) => {
        const dir = proj(runner, 'mismatch', { a: `${NETH[runner]}\n${NETBODY}` });
        const env = { COUNTER_PORT: String(ports.http) };
        assert.equal(run(runner, dir, [], { cache: false, det: ['--det', '--det-record'], env }).status, 0);
        stop();
        const same = run(runner, dir, [], { cache: false, env });
        assert.equal(same.status, 0, show(same));
        const changed = run(runner, dir, [], { cache: false, env: { ...env, SUFFIX: 'X' } });
        assert.notEqual(changed.status, 0, `the changed request must not get the stale answer\n${show(changed)}`);
        assert.match(changed.stdout + changed.stderr, /differs from the recording/);
      });
    });

    test('G-0128: UDP to an external address is refused and recorded', T, () => {
      const dir = proj(runner, 'udp', {
        a: `${NETH[runner]}
test('udp', async () => {
  const s = dgram.createSocket('udp4');
  const err = await new Promise((res) => s.send(Buffer.from('x'), 9, '203.0.113.7', (e) => res(e)));
  s.close();
  expect(err && err.name).toBe('NetworkBlockedError');
});`,
      });
      const r = run(runner, dir, [], { cache: false });
      assert.equal(r.status, 0, show(r));
      assert.match(fs.readFileSync(path.join(dir, '.detjs', 'trace.jsonl'), 'utf8'), /dgram\.send/);
    });
  });
}

// G-0127: a mocking library that intercepts sockets the way nock >= 14 (@mswjs/interceptors) does: an own `connect`
// on the socket instance and an own `connect` on its handle that answers without the network. Under --det the
// mocked connection must work; a socket whose handle is not intercepted must still be refused. (Measured with real
// nock 15.0 as well: see the P-041 report.)
const INTERCEPT = `
const net = require('node:net');
function connectTo(host, mock) {
  return new Promise((resolve) => {
    const s = new net.Socket();
    const proto = s.connect;
    s.connect = new Proxy(proto, { apply(t, th, a) {
      const r = Reflect.apply(t, th, a);
      return r;
    } });
    if (mock) {
      s.once('lookup', () => {});
      const wrap = () => {
        const h = s._handle;
        if (!h || h.__mock) return;
        h.__mock = true;
        h.connect = h.connect6 = (req) => { process.nextTick(() => req.oncomplete(0, h, req, true, true)); return 0; };
        h.readStart = () => 0; h.readStop = () => 0;
      };
      const origLookup = (hn, o, cb) => { if (typeof o === 'function') cb = o; wrap(); return o && o.all ? cb(null, [{ address: '203.0.113.9', family: 4 }]) : cb(null, '203.0.113.9', 4); };
      s.on('connect', () => { resolve('connected'); s.destroy(); });
      s.on('error', (e) => resolve('error ' + e.code));
      s.connect({ host, port: 80, lookup: origLookup });
    } else {
      const lk = (hn, o, cb) => { if (typeof o === 'function') cb = o; return o && o.all ? cb(null, [{ address: '203.0.113.9', family: 4 }]) : cb(null, '203.0.113.9', 4); };
      s.on('connect', () => { resolve('connected'); s.destroy(); });
      s.on('error', (e) => resolve('error ' + e.code));
      s.connect({ host, port: 80, lookup: lk });
    }
  });
}
test('mocked socket connects', async () => { expect(await connectTo('api.example.com', true)).toBe('connected'); });
test('unmocked socket with an overridden connect is refused', async () => { expect(await connectTo('api.example.com', false)).toMatch(/^error /); });
`;
for (const runner of RUNNERS) {
  test(`${runner}: G-0127 an intercepting mock library works under --det; the network stays closed`, T, () => {
    const dir = proj(runner, 'intercept', { a: (runner === 'vitest' ? "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);\n" : '') + INTERCEPT });
    const r = run(runner, dir, [], { cache: false });
    assert.equal(r.status, 0, show(r));
  });
}
