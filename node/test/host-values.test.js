'use strict';
// Spec "Engine: --det uses the machine's values by default" (2026-11-23), regression tests (a), (c), (d), (e).
// (b) (virtual timers waiting on the I/O a test waits for) is in test/host-values-timers.test.js.
//
// protects: the new defaults (host clock, host time zone and locale, open network), one epoch per run, cache
//   soundness with an open network.
// fails_when: the default epoch is 2025-01-01; an external host is refused by default; a test that used the live
//   network is reused by the cache; two sessions of one run (parallel lanes, the one-lane re-run's passes,
//   --det-isolate's per-test sessions, a --det-compare / --det-plan run) see different start times.
// no_claim: (c) and (d) use a local server standing in for an external host (a fake lookup resolves the external
//   name to 127.0.0.1); nothing here reaches the internet.
// Run: cd node && node --test --test-concurrency=1 test/host-values.test.js
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { fixture, crun, show, trace } = require('./runner-helpers');
const { BIN, TMP } = require('./helpers');

const T = { timeout: 600000 };
const SELFCERT = JSON.stringify(path.join(__dirname, '..', 'src', 'selfcert.js'));
const HEAD = "import { test } from 'node:test'; import assert from 'node:assert/strict'; import fs from 'node:fs'; import path from 'node:path'; import http from 'node:http'; import tls from 'node:tls'; import net from 'node:net'; import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);";
const tf = (name, body) => ({ [`tests/${name}.test.mjs`]: `${HEAD}\n${body}\n` });

// an external host name answered by a local server: the lookup hook resolves it to 127.0.0.1
const EXTERNAL = [
  "const lookup = (host, opts, cb) => { if (typeof opts === 'function') cb = opts; if (opts && opts.all) cb(null, [{ address: '127.0.0.1', family: 4 }]); else cb(null, '127.0.0.1', 4); };",
  'async function external(host) {',
  "  const server = http.createServer((req, res) => { res.end('hello from ' + req.headers.host); });",
  "  await new Promise((r) => server.listen(0, '127.0.0.1', r));",
  '  const port = server.address().port;',
  '  try {',
  "    return await new Promise((resolve, reject) => { const req = http.get({ host, port, path: '/', lookup, agent: false }, (res) => { let b = ''; res.on('data', (c) => { b += c; }); res.on('end', () => resolve({ body: b, port })); }); req.on('error', reject); });",
  '  } finally { server.close(); }',
  '}',
].join('\n');

const netEvents = (t) => (t.events || []).filter((e) => e.s === 'net').map((e) => `${e.o} ${e.v}`);

describe('(a) the clock is the host clock by default; certificates made in a test validate', () => {
  test('Date.now() within 10 minutes of the real time; a certificate valid from now-1h to now+1h passes the TLS handshake', T, () => {
    const dir = fixture('host-values', 'clock-cert', tf('clock', [
      `const selfcert = require(${SELFCERT});`,
      "test('wall clock', () => {",
      '  const before = Number(process.env.REAL_NOW_BEFORE_RUN);',
      '  assert.ok(Math.abs(Date.now() - before) < 10 * 60 * 1000, `Date.now() ${new Date().toISOString()} vs real ${new Date(before).toISOString()}`);',
      '});',
      "test('certificate made in the test', async () => {",
      '  const now = new Date();',
      "  const { key, cert } = selfcert.generate('localhost', { notBefore: new Date(now.getTime() - 3600e3), notAfter: new Date(now.getTime() + 3600e3) });",
      "  const server = tls.createServer({ key, cert }, (s) => { s.end('ok'); });",
      "  await new Promise((r) => server.listen(0, '127.0.0.1', r));",
      '  try {',
      '    const got = await new Promise((resolve, reject) => {',
      "      const s = tls.connect({ host: '127.0.0.1', port: server.address().port, ca: cert, checkServerIdentity: () => undefined }, () => {});",
      "      let b = ''; s.on('data', (c) => { b += c; }); s.on('end', () => resolve(b)); s.on('error', reject);",
      '    });',
      "    assert.equal(got, 'ok');",
      '  } finally { server.close(); }',
      '});',
    ].join('\n')));
    const r = crun('node-test', dir, [], { cache: false, det: ['--det'], env: { REAL_NOW_BEFORE_RUN: String(Date.now()) } });
    assert.equal(r.status, 0, show(r));
    const t = trace(dir);
    assert.equal(t.tests['tests/clock.test.mjs::wall clock'].outcome, 'passed', show(r));
    assert.equal(t.tests['tests/clock.test.mjs::certificate made in the test'].outcome, 'passed', show(r));
  });
});

describe('(c) network policy: open by default, closed on request', () => {
  const body = [
    EXTERNAL,
    "test('external host', async () => {",
    "  const { body, port } = await external('api.external.example');",
    "  assert.match(body, /hello from api.external.example/);",
    "  fs.writeFileSync('port.txt', String(port));",
    '});',
  ].join('\n');

  test('default: a non-local host goes through and is recorded `<host>:<port> allowed`', T, () => {
    const dir = fixture('host-values', 'net-open', tf('net', body));
    const r = crun('node-test', dir, [], { cache: false, det: ['--det'] });
    assert.equal(r.status, 0, show(r));
    const port = fs.readFileSync(path.join(dir, 'port.txt'), 'utf8');
    const t = trace(dir);
    const ev = netEvents(t.tests['tests/net.test.mjs::external host']);
    assert.ok(ev.includes(`net.connect api.external.example:${port} allowed`), JSON.stringify(ev));
    assert.equal(t.header.meta.network, 'open');
    assert.match(r.stdout + r.stderr, /network=open/);
  });

  test('--det-net=closed: the same connection is refused with NetworkBlockedError', T, () => {
    const dir = fixture('host-values', 'net-closed', tf('net', [
      EXTERNAL,
      "test('external host refused', async () => {",
      "  await assert.rejects(external('api.external.example'), (e) => e.name === 'NetworkBlockedError');",
      '});',
    ].join('\n')));
    const r = crun('node-test', dir, [], { cache: false, det: ['--det', '--det-net=closed'] });
    assert.equal(r.status, 0, show(r));
    const t = trace(dir);
    assert.equal(t.tests['tests/net.test.mjs::external host refused'].outcome, 'passed', show(r));
    assert.equal(t.header.meta.network, 'block');
  });
});

describe('(d) the cache with an open network', () => {
  // The reason is in the run's cache summary (`not_cached_detail`, the engine's place for why a file was not stored);
  // the receipts (written by the Rust core) carry the reuse decision of every file.
  test('a test that reached an external host is never reused; the reason is in the cache summary, the receipt says re-run', T, () => {
    const dir = fixture('host-values', 'cache-open', {
      ...tf('net', [EXTERNAL, "test('external host', async () => { assert.match((await external('api.external.example')).body, /hello/); });"].join('\n')),
      ...tf('plain', "test('pure', () => { assert.equal(1 + 1, 2); });"),
    });
    const det = ['--det', '--det-net=open'];
    const r1 = crun('node-test', dir, [], { det });
    assert.equal(r1.status, 0, show(r1));
    const r2 = crun('node-test', dir, [], { det });
    assert.equal(r2.status, 0, show(r2));
    const reused = ((r2.summary && r2.summary.reused_files_list) || []).map((f) => f.split('@@')[0]);
    assert.ok(reused.includes('tests/plain.test.mjs'), `the file without network use is reused\n${show(r2)}`);
    assert.ok(!reused.includes('tests/net.test.mjs'), `WRONG REUSE of the file that used the live network\n${show(r2)}`);
    for (const [n, r] of [['run 1', r1], ['run 2', r2]]) {
      const why = (r.summary && r.summary.not_cached_detail && r.summary.not_cached_detail['tests/net.test.mjs']) || '';
      assert.match(why, /api\.external\.example:\d+ \(external host, open network\)/, `${n}: the reason names the external host\n${show(r)}`);
    }
    const receipts = fs.readFileSync(path.join(dir, '.detjs', 'receipts.jsonl'), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
    const mine = receipts.find((x) => x.nodeid === 'tests/net.test.mjs');
    assert.ok(mine && mine.reused === false, `run 2's receipt: re-run\n${JSON.stringify(receipts)}`);
  });

  test('the *_PROXY variables are run inputs while the network is open (the default)', T, () => {
    const dir = fixture('host-values', 'proxy-inputs', tf('p', "test('p', () => {});"));
    const r = crun('node-test', dir, [], { cache: false, det: ['--det'], env: { HTTPS_PROXY: 'http://127.0.0.1:9', https_proxy: 'http://127.0.0.1:9' } });
    assert.equal(r.status, 0, show(r));
    const inputs = trace(dir).header.meta.inputs;
    assert.ok(inputs['env:HTTPS_PROXY'], JSON.stringify(Object.keys(inputs)));
    assert.ok(inputs['env:https_proxy'], JSON.stringify(Object.keys(inputs)));
  });
});

describe('(e) one epoch per run', () => {
  // a real wait (not the virtual clock): sessions started one after the other start more than a second apart
  const SLEEP = 'const realSleep = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);';
  const LOG = "const log = (what) => fs.appendFileSync(path.join(process.cwd(), 'starts-' + what + '.log'), what + ' ' + Math.floor(Date.now() / 1000) + '\\n');";

  function vproject(name, files) {
    const dir = path.join(TMP, 'host-values', name);
    fs.rmSync(dir, { recursive: true, force: true });
    fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: `host-values-${name}`, private: true }));
    fs.writeFileSync(path.join(dir, 'vitest.config.mjs'), "export default { test: { include: ['tests/**/*.test.mjs'] } };\n");
    const head = `import { test, expect } from 'vitest'; import fs from 'node:fs'; import path from 'node:path';\n${SLEEP}\n${LOG}`;
    for (const [f, b] of Object.entries(files)) fs.writeFileSync(path.join(dir, 'tests', f), `${head}\n${b}\n`);
    fs.writeFileSync(path.join(dir, 'plan.json'), JSON.stringify({ lanes: Object.keys(files).map((f) => [`tests/${f}`]) }));
    return dir;
  }
  function vrun(dir, args, trace = path.join('.detjs', 'trace.jsonl')) {
    const env = { ...process.env };
    for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_SEED', 'DETJS_CACHE_DIR', 'DETJS_EPOCH',
      'DETJS_PINNED', 'DETJS_HAZARD_RERUN', 'DETJS_HAZARD_PASS', 'DETJS_ISOLATE_CHILD', 'DETJS_EARLY', 'VITEST_POOL_ID', 'VITEST_WORKER_ID']) delete env[k];
    const r = spawnSync(process.execPath, [BIN, 'vitest', 'run', '--det', `--det-trace=${trace}`, ...args], { cwd: dir, encoding: 'utf8', env, timeout: 300000 });
    const lines = fs.readFileSync(path.join(dir, trace), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
    return { ...r, header: lines[0], show: `status=${r.status}\nstdout=${(r.stdout || '').slice(-2000)}\nstderr=${(r.stderr || '').slice(-2000)}` };
  }
  const starts = (dir) => fs.readdirSync(dir).filter((f) => /^starts-.*\.log$/.test(f)).sort()
    .flatMap((f) => fs.readFileSync(path.join(dir, f), 'utf8').split('\n').filter(Boolean).map((l) => l.split(' ')));
  function sameStart(dir, header, n, r) {
    const s = starts(dir);
    assert.equal(s.length, n, `${n} test starts expected: ${JSON.stringify(s)}\n${r.show}`);
    const epochS = String(Math.floor(Number(BigInt(header.meta.epoch_ns) / 1000000n) / 1000));
    for (const [what, sec] of s) assert.equal(sec, epochS, `${what} started at ${sec}, the run's epoch is ${epochS}: ${JSON.stringify(s)}\n${r.show}`);
  }
  function epochMeta(header) {
    assert.equal(typeof header.meta.epoch, 'string', `meta.epoch (ISO) in the trace header: ${JSON.stringify(header.meta).slice(0, 400)}`);
    assert.equal(BigInt(Date.parse(header.meta.epoch)) * 1000000n, BigInt(header.meta.epoch_ns));
    assert.ok(Math.abs(Date.parse(header.meta.epoch) - Date.now()) < 10 * 60 * 1000, `the default epoch is the host time: ${header.meta.epoch}`);
  }

  test('a parallel run and its one-lane re-run (passes 1 and 2) see one start time', T, () => {
    const dir = vproject('epoch-hazard', {
      'a.test.mjs': "test('a', () => { log('a'); realSleep(1100); fs.writeFileSync(path.join(process.cwd(), 'shared.txt'), 'a'); });",
      'b.test.mjs': "test('b', () => { log('b'); realSleep(1100); fs.writeFileSync(path.join(process.cwd(), 'shared.txt'), 'b'); });",
    });
    const r = vrun(dir, ['--det-plan=plan.json']);
    assert.match(r.stderr, /run again in one lane/, r.show);
    epochMeta(r.header);
    sameStart(dir, r.header, 4, r); // pass 1: a, b in two lanes; pass 2: a, b in one lane
  });

  test('--det-isolate: every per-test session sees one start time', T, () => {
    const dir = vproject('epoch-isolate', {
      'a.test.mjs': ["test('a1', () => { log('a1'); realSleep(1100); });", "test('a2', () => { log('a2'); realSleep(1100); });"].join('\n'),
      'b.test.mjs': "test('b1', () => { log('b1'); realSleep(1100); });",
    });
    const r = vrun(dir, ['--det-isolate', '--det-workers=1']);
    assert.equal(r.status, 0, r.show);
    epochMeta(r.header);
    sameStart(dir, r.header, 3, r);
  });

  test('--det-compare=T and --det-plan=T without --det-epoch use the epoch of T', T, () => {
    const dir = vproject('epoch-compare', {
      'a.test.mjs': "test('a', () => { log('a'); });",
      'b.test.mjs': "test('b', () => { log('b'); });",
    });
    const t1 = vrun(dir, ['--det-plan=plan.json'], 'first.jsonl');
    assert.equal(t1.status, 0, t1.show);
    epochMeta(t1.header);
    realSleep(1100);
    const t2 = vrun(dir, ['--det-workers=1', '--det-compare=first.jsonl'], 'second.jsonl');
    assert.equal(t2.status, 0, t2.show);
    assert.equal(t2.header.meta.epoch_ns, t1.header.meta.epoch_ns, '--det-compare: the epoch of the compared trace');
    realSleep(1100);
    const t3 = vrun(dir, ['--det-plan=first.jsonl'], 'third.jsonl');
    assert.equal(t3.status, 0, t3.show);
    assert.equal(t3.header.meta.epoch_ns, t1.header.meta.epoch_ns, '--det-plan=TRACE: the epoch of that trace');
    sameStart(dir, t1.header, 6, t3);
  });
});

function realSleep(ms) { Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms); }
