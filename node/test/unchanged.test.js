'use strict';
// --det must not change the outcome of deterministic suites: the same
// fixture passes without --det, with --det and with --det --det-seed=N, and
// the APIs the controls replace keep their behaviour (types, instanceof,
// arguments, errors, fake timers, local servers, async ordering).
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const { project, run, failed, RUNNERS } = require('./helpers');

const T = { timeout: 300000 };

const SUITE = `
test('runner environment variables', () => {
  expect(process.env.NODE_ENV).toBe('test');
  if (typeof vi !== 'undefined') expect(process.env.VITEST).toBe('true');
});

describe('Date', () => {
  test('constructor forms and statics', () => {
    expect(new Date(0).toISOString()).toBe('1970-01-01T00:00:00.000Z');
    expect(new Date(2020, 0, 2).getFullYear()).toBe(2020);
    expect(new Date('2021-03-04T05:06:07Z').getTime()).toBe(Date.UTC(2021, 2, 4, 5, 6, 7));
    expect(Date.parse('2000-01-01T00:00:00Z')).toBe(946684800000);
    expect(typeof Date()).toBe('string');
    expect(new Date() instanceof Date).toBe(true);
    expect(Object.prototype.toString.call(new Date())).toBe('[object Date]');
    class Sub extends Date {}
    expect(new Sub(5).getTime()).toBe(5);
    expect(new Sub() instanceof Date).toBe(true);
    expect(structuredClone(new Date(7)).getTime()).toBe(7);
    expect(Date.now()).toBeGreaterThan(0);
    expect(new Date().getTime() - Date.now()).toBeLessThan(1000);
  });
  test('elapsed time is non-negative and monotonic', () => {
    const a = performance.now(); const b = performance.now();
    expect(b).toBeGreaterThanOrEqual(a);
    const h = process.hrtime(); const d = process.hrtime(h);
    expect(d[0]).toBeGreaterThanOrEqual(0);
    expect(typeof process.hrtime.bigint()).toBe('bigint');
  });
});

describe('timers', () => {
  test('ordering by delay, then creation', async () => {
    const out = [];
    await new Promise((resolve) => {
      setTimeout(() => out.push('b30'), 30);
      setTimeout(() => out.push('a10'), 10);
      setTimeout(() => out.push('c10'), 10);
      setTimeout(() => { out.push('end'); resolve(); }, 50);
    });
    expect(out).toEqual(['a10', 'c10', 'b30', 'end']);
  });
  test('clearTimeout, clearInterval, refresh, unref, args', async () => {
    let n = 0;
    const t = setTimeout(() => { n += 100; }, 5);
    clearTimeout(t);
    const iv = setInterval((k) => { n += k; if (n >= 3) clearInterval(iv); }, 1, 1);
    const u = setTimeout(() => {}, 10000); u.unref(); expect(u.hasRef()).toBe(false); clearTimeout(u);
    const r = setTimeout(() => {}, 5); r.refresh(); clearTimeout(Number(r));
    await new Promise((res) => setTimeout(res, 20));
    expect(n).toBe(3);
  });
  test('promise and nextTick ordering inside timers', async () => {
    const out = [];
    await new Promise((resolve) => setTimeout(() => {
      process.nextTick(() => out.push('tick'));
      Promise.resolve().then(() => out.push('micro'));
      setImmediate(() => { out.push('immediate'); resolve(); });
      out.push('sync');
    }, 1));
    expect(out).toEqual(['sync', 'tick', 'micro', 'immediate']);
  });
  test('a setImmediate chain finishes before a later timer (act()-style flushing)', async () => {
    let steps = 0;
    const chain = () => { steps += 1; if (steps < 200) setImmediate(chain); };
    await new Promise((resolve) => {
      setTimeout(() => setImmediate(chain), 1);
      setTimeout(() => { expect(steps).toBe(200); resolve(); }, 30);
    });
  });
  test('timers/promises with abort', async () => {
    expect(await sleepP(10, 'v')).toBe('v');
    const ac = new AbortController();
    const p = sleepP(1000, null, { signal: ac.signal });
    ac.abort();
    await expect(p).rejects.toThrow();
  });
  test('runner fake timers still work', () => {
    fake.useFakeTimers();
    let hit = false;
    setTimeout(() => { hit = true; }, 1000);
    fake.advanceTimersByTime(1000);
    expect(hit).toBe(true);
    fake.useRealTimers();
  });
});

describe('random', () => {
  test('ranges and APIs', () => {
    for (let i = 0; i < 1000; i++) { const x = Math.random(); expect(x >= 0 && x < 1).toBe(true); }
    expect(crypto.randomUUID()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(crypto.getRandomValues(new Uint32Array(4)).length).toBe(4);
    expect(nodeCrypto.randomBytes(16).length).toBe(16);
    const n = nodeCrypto.randomInt(10); expect(n >= 0 && n < 10).toBe(true);
    expect(() => crypto.getRandomValues(new Float64Array(2))).toThrow();
  });
  test('web crypto digest', async () => {
    const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode('abc'));
    expect(Buffer.from(d).toString('hex').slice(0, 8)).toBe('ba7816bf');
  });
});

describe('fs and local network', () => {
  test('directory listing contents', async () => {
    const d = fs.mkdtempSync(path.join(os.tmpdir(), 'detjs-u-'));
    for (const n of ['b', 'a', 'c']) fs.writeFileSync(path.join(d, n), n);
    expect(new Set(fs.readdirSync(d))).toEqual(new Set(['a', 'b', 'c']));
    expect((await fs.promises.readdir(d)).length).toBe(3);
    const dir = fs.opendirSync(d); let k = 0; while (dir.readSync()) k++; dir.closeSync(); expect(k).toBe(3);
  });
  test('local http server round trip', async () => {
    const server = http.createServer((req, res) => res.end('pong'));
    await new Promise((r) => server.listen(0, '127.0.0.1', r));
    const body = await new Promise((resolve, reject) => {
      http.get({ host: '127.0.0.1', port: server.address().port, path: '/' }, (r) => {
        let b = ''; r.on('data', (c) => { b += c; }); r.on('end', () => resolve(b));
      }).on('error', reject);
    });
    server.close();
    expect(body).toBe('pong');
  });
  test('local fetch', async () => {
    const server = http.createServer((req, res) => res.end(JSON.stringify({ ok: true })));
    await new Promise((r) => server.listen(0, '127.0.0.1', r));
    const r = await fetch('http://127.0.0.1:' + server.address().port + '/');
    expect(await r.json()).toEqual({ ok: true });
    server.close();
  });
  test('local server with a timeout race', async () => {
    const server = http.createServer((req, res) => setTimeout(() => res.end('slow'), 20));
    await new Promise((r) => server.listen(0, '127.0.0.1', r));
    const got = await Promise.race([
      fetch('http://127.0.0.1:' + server.address().port + '/').then((r) => r.text()),
      new Promise((r) => setTimeout(() => r('timeout'), 2000)),
    ]);
    server.close();
    expect(got).toBe('slow');
  });
});
`;

for (const runner of RUNNERS) {
  describe(runner, () => {
    test('deterministic suite: same outcomes without --det, with --det and with --det-seed', T, () => {
      const dir = project(runner, 'unchanged', { suite: SUITE });
      const results = {
        normal: run(runner, dir),
        det: run(runner, dir, ['--det']),
        seed3: run(runner, dir, ['--det', '--det-seed=3']),
        seed11: run(runner, dir, ['--det', '--det-seed=11']),
      };
      for (const [mode, r] of Object.entries(results)) {
        assert.ok(Object.keys(r.outcomes).length >= 14, `${mode}: ${JSON.stringify(r.outcomes)}\n${r.stderr}`);
        assert.deepEqual(failed(r), [], `${mode}\n${r.stdout}\n${r.stderr}`);
      }
      assert.deepEqual(Object.keys(results.det.outcomes).sort(), Object.keys(results.normal.outcomes).sort());
      assert.equal(results.det.trace.tests.length, Object.keys(results.normal.outcomes).length);
    });
  });
}
