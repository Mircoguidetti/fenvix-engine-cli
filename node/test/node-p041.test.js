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
