'use strict';
// One test per Level 0 control and runner: the fixture suite fails without
// --det (a realistic run: parallel workers, random order where configured,
// real time, real randomness, real directory order, live network) and passes
// with --det. Golden-value fixtures store what the first run saw and compare
// on later runs, which is what a flaky test does in practice.
const { test, describe } = require('node:test');
const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { project, run, failed, resetGolden, RUNNERS } = require('./helpers');
const native = require('../src/native');

const T = { timeout: 300000 };

function assertAllPass(r, what) {
  assert.ok(Object.keys(r.outcomes).length > 0, `${what}: no test results\n${r.stdout}\n${r.stderr}`);
  assert.deepEqual(failed(r), [], `${what}: failures\n${r.stdout}\n${r.stderr}`);
}

function assertSomeFail(r, what) {
  assert.ok(failed(r).length > 0, `${what}: expected failures, got ${JSON.stringify(r.outcomes)}\n${r.stderr}`);
}

/** Golden fixtures: baseline run 2 differs from run 1; --det runs 1 and 2 agree. */
function goldenCheck(runner, dir, detArgs = []) {
  resetGolden(dir);
  const b1 = run(runner, dir, ['--maxWorkers=2']);
  assert.ok(Object.keys(b1.outcomes).length > 0, `baseline run 1: no results\n${b1.stderr}`);
  const b2 = run(runner, dir, ['--maxWorkers=2']);
  assertSomeFail(b2, 'baseline run 2');
  resetGolden(dir);
  const d1 = run(runner, dir, ['--det', ...detArgs]);
  assertAllPass(d1, '--det run 1');
  const d1Trace = d1.tracePath + '.1';
  fs.copyFileSync(d1.tracePath, d1Trace);
  const d2 = run(runner, dir, ['--det', ...detArgs]);
  assertAllPass(d2, '--det run 2');
  const rep = JSON.parse(native.verify([d1Trace, d2.tracePath]));
  assert.equal(rep.summary.diverged, 0, JSON.stringify(rep.tests.filter((t) => t.status !== 'stable'), null, 1));
  assert.ok(rep.summary.order_identical);
  return { b2, d1, d2 };
}

const SEEDS = `
test('Math.random', () => { golden('math', [Math.random(), Math.random()]); });
test('crypto.randomUUID', () => { golden('uuid', [crypto.randomUUID(), nodeCrypto.randomUUID()]); });
test('crypto.getRandomValues', () => { golden('grv', Array.from(crypto.getRandomValues(new Uint8Array(12)))); });
`;

const TIME = `
test('Date', () => { golden('date', [Date.now(), new Date().toISOString(), new Date().getTime()]); });
test('performance.now and hrtime', () => {
  golden('mono', [performance.now(), process.hrtime(), String(process.hrtime.bigint())]);
});
`;

const TIMERS = `
test('setTimeout longer than the test timeout', async () => { await new Promise((r) => setTimeout(r, 3000)); }, 1000);
test('timers/promises longer than the test timeout', async () => { await sleepP(3000); }, 1000);
test('setInterval ticks in a measured window', async () => {
  let n = 0;
  const iv = setInterval(() => { n++; }, 10);
  const t0 = performance.now();
  while (performance.now() - t0 < 200) await new Promise((r) => setTimeout(r, 7));
  clearInterval(iv);
  golden('interval', [n, performance.now() - t0]);
});
`;

const FS = `
const NAMES = ['golf', 'mike', 'bravo', 'zulu', 'echo', 'kilo', 'alpha', 'delta', 'tango', 'oscar'];
const SORTED = [...NAMES].sort();
function mk() {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'detjs-fs-'));
  for (const n of NAMES) fs.writeFileSync(path.join(d, n), n);
  return d;
}
test('readdirSync', () => { expect(fs.readdirSync(mk())).toEqual(SORTED); });
test('readdir callback', async () => {
  const d = mk();
  const names = await new Promise((res, rej) => fs.readdir(d, (e, n) => (e ? rej(e) : res(n))));
  expect(names).toEqual(SORTED);
});
test('promises.readdir withFileTypes', async () => {
  expect((await fs.promises.readdir(mk(), { withFileTypes: true })).map((e) => e.name)).toEqual(SORTED);
});
test('opendir', async () => {
  const out = [];
  for await (const e of await fs.promises.opendir(mk())) out.push(e.name);
  expect(out).toEqual(SORTED);
});
`;

const NET = `
const lookup = (h, o, cb) => {
  if (typeof o === 'function') cb = o;
  return o && o.all ? cb(null, [{ address: '127.0.0.1', family: 4 }]) : cb(null, '127.0.0.1', 4);
};
function get(mod, host, port, extra = {}) {
  return new Promise((resolve, reject) => {
    mod.get({ host, port, path: '/', lookup, agent: false, ...extra }, (r) => {
      let b = '';
      r.setEncoding('utf8');
      r.on('data', (d) => { b += d; });
      r.on('end', () => resolve(b));
    }).on('error', reject);
  });
}
test('http response', async () => {
  golden('http', await get(http, 'counter.detjs.test', Number(process.env.COUNTER_PORT)));
});
test('https response', async () => {
  golden('https', await get(https, 'tls.detjs.test', Number(process.env.COUNTER_TLS_PORT), { rejectUnauthorized: false }));
});
`;

function isolationFile(name) {
  return `
const LOG = path.join(process.cwd(), 'shared.log');
const log = (s) => fs.appendFileSync(LOG, s + '\\n');
const tail = () => fs.readFileSync(LOG, 'utf8').trim().split('\\n').slice(-2);
test('${name} writes a contiguous block', async () => {
  log('${name}-start');
  await new Promise((r) => setTimeout(r, 500));
  log('${name}-end');
  expect(tail()).toEqual(['${name}-start', '${name}-end']);
});
`;
}

const FILE_ORDER = {
  a_writer: `
test('writer', async () => {
  await new Promise((r) => setTimeout(r, 500));
  fs.writeFileSync(path.join(process.cwd(), 'marker'), 'x');
});`,
  b_reader: `
test('reader', () => { expect(fs.existsSync(path.join(process.cwd(), 'marker'))).toBe(true); });`,
};

const TEST_ORDER = `
let state = 0;
describe('suite', () => {
  test('t1 sets state', () => { state = 1; });
  test('t2 needs state', () => { expect(state).toBe(1); });
  test('t3', () => {});
  test('t4', () => {});
  test('t5', () => {});
});
`;

for (const runner of RUNNERS) {
  describe(`${runner}`, () => {
    test('seeds: Math.random, crypto.randomUUID, crypto.getRandomValues', T, () => {
      const dir = project(runner, 'seeds', { seeds: SEEDS });
      const { d1 } = goldenCheck(runner, dir);
      const ev = d1.trace.tests.flatMap((t) => t.events.map((e) => e.o));
      for (const op of ['Math.random', 'crypto.randomUUID', 'crypto.getRandomValues']) assert.ok(ev.includes(op), op);
      // another seed gives other values
      resetGolden(dir);
      run(runner, dir, ['--det']);
      const other = run(runner, dir, ['--det', '--det-seed=5']);
      assertSomeFail(other, '--det-seed=5 against seed-0 golden values');
    });

    test('time: Date, performance.now, process.hrtime', T, () => {
      const dir = project(runner, 'time', { time: TIME });
      const { d1 } = goldenCheck(runner, dir);
      const date = d1.trace.tests.find((t) => t.nodeid.endsWith('::Date'));
      assert.ok(date.events.some((e) => e.o === 'Date.now'));
    });

    test('timers: setTimeout, timers/promises, setInterval', T, () => {
      const dir = project(runner, 'timers', { timers: TIMERS });
      const t0 = Date.now();
      const { b2, d1 } = goldenCheck(runner, dir);
      assert.ok(failed(b2).some((n) => n.includes('longer than the test timeout')));
      const iv = d1.trace.tests.find((t) => t.nodeid.includes('setInterval'));
      assert.ok(iv.events.some((e) => e.o === 'setInterval.fire'));
      assert.ok(Date.now() - t0 < 120000);
    });

    test('fs: readdir, readdirSync, promises.readdir, opendir', T, () => {
      const dir = project(runner, 'fs', { fs: FS });
      const b = run(runner, dir, ['--maxWorkers=2']);
      assertSomeFail(b, 'baseline');
      const d = run(runner, dir, ['--det']);
      assertAllPass(d, '--det');
      assert.ok(d.trace.tests.every((t) => t.events.some((e) => e.s === 'fs')));
    });

    test('net: closed by default, record then replay (http, https)', T, async () => {
      // The "external" service runs in its own process: the fixture runs are
      // synchronous child processes and would block a server in this process.
      const srv = spawn(process.execPath, [path.join(__dirname, 'counter-server.js')], { stdio: ['ignore', 'pipe', 'inherit'] });
      const ports = await new Promise((resolve) => srv.stdout.once('data', (d) => resolve(JSON.parse(String(d)))));
      try {
        const dir = project(runner, 'net', { net: NET });
        fs.rmSync(path.join(dir, '.detjs'), { recursive: true, force: true });
        resetGolden(dir);
        const env = { COUNTER_PORT: String(ports.http), COUNTER_TLS_PORT: String(ports.https) };
        // baseline: live service, the response changes between runs
        assertAllPass(run(runner, dir, [], { env }), 'baseline run 1');
        assertSomeFail(run(runner, dir, [], { env }), 'baseline run 2');
        resetGolden(dir);
        // --det without cassette: closed
        const blocked = run(runner, dir, ['--det'], { env });
        assert.equal(failed(blocked).length, 2);
        assert.match(JSON.stringify(blocked.trace.tests), /blocked/);
        resetGolden(dir);
        // record once, then replay with the service stopped
        assertAllPass(run(runner, dir, ['--det', '--det-record'], { env }), '--det --det-record');
        assert.ok(fs.existsSync(path.join(dir, '.detjs', 'cassette.json')));
        srv.kill();
        for (let i = 0; i < 2; i++) {
          const r = run(runner, dir, ['--det'], { env });
          assertAllPass(r, `--det replay ${i + 1}`);
          assert.equal(r.trace.header.meta.network, 'replay');
          assert.ok(r.trace.tests.every((t) => t.events.some((e) => e.s === 'net' && /replay#/.test(e.v))));
        }
      } finally {
        srv.kill();
      }
    });

    test('isolation: parallel workers interleave, --det runs files serially', T, () => {
      const dir = project(runner, 'isolation', { x: isolationFile('X'), y: isolationFile('Y') });
      const log = path.join(dir, 'shared.log');
      fs.rmSync(log, { force: true });
      assertSomeFail(run(runner, dir, ['--maxWorkers=2']), 'baseline (2 workers)');
      fs.rmSync(log, { force: true });
      const d = run(runner, dir, ['--det']);
      assertAllPass(d, '--det');
      assert.equal(d.trace.header.meta.serial, true);
      assert.match(d.trace.header.meta.isolation, runner === 'vitest' ? /maxWorkers=1/ : /runInBand/);
    });

    test('order: files run in sorted order, --det-seed shuffles reproducibly', T, () => {
      const dir = project(runner, 'file-order', FILE_ORDER);
      const marker = path.join(dir, 'marker');
      fs.rmSync(marker, { force: true });
      assertSomeFail(run(runner, dir, ['--maxWorkers=2']), 'baseline (2 workers)');
      fs.rmSync(marker, { force: true });
      const d = run(runner, dir, ['--det']);
      assertAllPass(d, '--det');
      assert.deepEqual(d.trace.header.meta.files, ['tests/a_writer' + (runner === 'vitest' ? '.test.mjs' : '.test.js'), 'tests/b_reader' + (runner === 'vitest' ? '.test.mjs' : '.test.js')]);
      // seeds give reproducible file orders; some seed puts the reader first
      const orders = new Set();
      for (let s = 1; s <= 6; s++) {
        fs.rmSync(marker, { force: true });
        const a = run(runner, dir, ['--det', `--det-seed=${s}`]);
        fs.rmSync(marker, { force: true });
        const b = run(runner, dir, ['--det', `--det-seed=${s}`]);
        assert.deepEqual(a.trace.header.meta.files, b.trace.header.meta.files, `seed ${s}`);
        assert.deepEqual(a.outcomes, b.outcomes, `seed ${s}`);
        orders.add(a.trace.header.meta.files.join(','));
      }
      assert.equal(orders.size, 2);
    });

    test('order: tests of a file run in declaration order, --det-seed shuffles reproducibly', T, () => {
      const cfg = { vitest: { sequence: { shuffle: true } }, jest: { randomize: true } };
      const dir = project(runner, 'test-order', { order: TEST_ORDER }, cfg);
      const seedArg = (s) => (runner === 'vitest' ? `--sequence.seed=${s}` : `--seed=${s}`);
      let baselineFailed = false;
      for (let s = 1; s <= 10 && !baselineFailed; s++) baselineFailed = failed(run(runner, dir, [seedArg(s)])).length > 0;
      assert.ok(baselineFailed, 'some random order of the baseline fails');
      const d = run(runner, dir, ['--det']);
      assertAllPass(d, '--det (random order configured, fixed under --det)');
      assert.deepEqual(d.trace.tests.map((t) => t.nodeid.split('::').pop()), ['t1 sets state', 't2 needs state', 't3', 't4', 't5']);
      let explored = false;
      for (let s = 1; s <= 10; s++) {
        const a = run(runner, dir, ['--det', `--det-seed=${s}`]);
        const b = run(runner, dir, ['--det', `--det-seed=${s}`]);
        assert.deepEqual(a.trace.tests.map((t) => t.nodeid), b.trace.tests.map((t) => t.nodeid), `seed ${s}`);
        assert.deepEqual(a.outcomes, b.outcomes, `seed ${s}`);
        if (failed(a).length) explored = true;
      }
      assert.ok(explored, 'seed exploration reproduces the order dependency');
    });
  });
}
