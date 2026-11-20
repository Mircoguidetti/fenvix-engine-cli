'use strict';
// P-041 network and randomness package (rows JS-02, F-06): the 2026-11-20 audit gaps G-1415..G-1421, G-1426..G-1429
// and G-2165, each with its regression test. Every test runs on Vitest and Jest (DETJS_TEST_RUNNERS selects).
//
//   G-1415 loopback traffic in the fingerprint        G-1416 --det-allow-host connections in the fingerprint
//   G-1417 bytes of recorded / replayed connections   G-1418 cassette age: recorded_at, warning, --det-cassette-max-age
//   G-1419 connections outside test bodies recorded and replayed (module level, beforeAll, globalSetup)
//   G-1420 TLS replay negotiates the recorded ALPN (HTTP/2)
//   G-1421 WebSocket handshake keys and frame masks deterministic
//   G-1426 OS entropy: observed by default (the Python contract), never silent; --det-urandom=on|off
//   G-1427 better-sqlite3 / G-1428 node:sqlite: random(), randomblob(), 'now' and CURRENT_TIMESTAMP virtual
//   G-1429 WASI random_get / clock_time_get     G-2165 no shipped TLS key; verification bypass only for replay
//
// Run: cd node && node --test test/network-p041.test.js
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const { fixture, crun, show, reused, trace, TMP } = require('./runner-helpers');
const native = require('../src/native');

const T = { timeout: 600000 };
const RUNNERS = (process.env.DETJS_TEST_RUNNERS || 'vitest,jest').split(',').filter((r) => r === 'vitest' || r === 'jest');
const EXT = { vitest: '.test.mjs', jest: '.test.js' };
const HEAD = {
  vitest: "import { test, expect, beforeAll } from 'vitest'; import fs from 'node:fs'; import path from 'node:path'; import http from 'node:http'; import https from 'node:https'; import http2 from 'node:http2'; import tls from 'node:tls'; import nodeCrypto from 'node:crypto'; import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);",
  jest: "const fs = require('node:fs'); const path = require('node:path'); const http = require('node:http'); const https = require('node:https'); const http2 = require('node:http2'); const tls = require('node:tls'); const nodeCrypto = require('node:crypto');",
};

function proj(runner, name, files, extra = {}, cfg = {}) {
  const f = {};
  if (runner === 'vitest') f['vitest.config.mjs'] = `export default { test: ${JSON.stringify({ include: ['t/**/*.test.mjs'], ...(cfg.vitest || {}) })} };\n`;
  else f['jest.config.js'] = `module.exports = ${JSON.stringify({ testMatch: ['**/t/**/*.test.js'], testEnvironment: 'node', ...(cfg.jest || {}) })};\n`;
  for (const [n, body] of Object.entries(files)) f[`t/${n}${EXT[runner]}`] = `${HEAD[runner]}\n${body}\n`;
  return fixture(`netp041-${runner}`, name, { ...f, ...extra });
}
const args = (runner, a = []) => (runner === 'vitest' ? ['run', ...a] : a);
const run = (runner, dir, a = [], o = {}) => crun(runner, dir, args(runner, a), { cache: false, ...o });
const PUT = "const put = (k, v) => { fs.mkdirSync('out', { recursive: true }); fs.writeFileSync(path.join('out', k + '.txt'), String(v)); };";
const got = (dir, k) => fs.readFileSync(path.join(dir, 'out', `${k}.txt`), 'utf8');
const save = (dir, name) => fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), path.join(dir, name));
const verify = (dir, a, b) => JSON.parse(native.verify([path.join(dir, a), path.join(dir, b)]));
const events = (dir, filter = () => true) => Object.values(trace(dir).tests).flatMap((t) => t.events || []).filter(filter);
const divergences = (rep) => rep.tests.filter((t) => t.status === 'diverged').map((t) => `${t.nodeid} [${t.divergence && t.divergence.reason}] ${t.divergence && t.divergence.description}`);

async function withCounter(fn) {
  const srv = spawn(process.execPath, [path.join(__dirname, 'counter-server.js')], { stdio: ['ignore', 'pipe', 'inherit'] });
  const ports = await new Promise((resolve) => srv.stdout.once('data', (d) => resolve(JSON.parse(String(d)))));
  try { return await fn(ports, () => srv.kill()); } finally { srv.kill(); }
}

// a host name resolved to the loopback counter server: external for Level 0 (record / replay / allow-host)
const LOOKUP = "const lookup = (h, o, cb) => { if (typeof o === 'function') cb = o; return o && o.all ? cb(null, [{ address: '127.0.0.1', family: 4 }]) : cb(null, '127.0.0.1', 4); };";
const GET = `${LOOKUP}
function get(host, port, p = '/') {
  return new Promise((resolve, reject) => {
    http.get({ host, port: Number(port), path: p, lookup, agent: false }, (r) => {
      let b = ''; r.setEncoding('utf8'); r.on('data', (d) => { b += d; }); r.on('end', () => resolve(b));
    }).on('error', reject);
  });
}`;

// ---------------------------------------------------------------------------------------------------------------
// G-1415 G-1417: loopback traffic reaches the fingerprint; a different answer diverges [net]
const LOCAL_SERVER = `${PUT}
function answer() { return fs.readFileSync('answer.txt', 'utf8'); }
async function serve() {
  const srv = http.createServer((q, r) => r.end(answer() + ' ' + q.url));
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  return srv;
}
function fetchLocal(port, p) {
  return new Promise((resolve, reject) => http.get({ host: '127.0.0.1', port, path: p, agent: false }, (r) => {
    let b = ''; r.on('data', (d) => { b += d; }); r.on('end', () => resolve([r.headers.date, b]));
  }).on('error', reject));
}
test('local service', async () => {
  const srv = await serve();
  const [date, body] = await fetchLocal(srv.address().port, '/x');
  srv.close();
  put('date', date);
  expect(body.length > 0).toBe(true);
});
test('no network', () => { expect(1).toBe(1); });`;

// G-1416: a host allowed with --det-allow-host
const ALLOWED = `${GET}
test('allowed host', async () => { expect(await get('allowed.detjs.test', process.env.COUNTER_PORT)).toMatch(/^response #/); });`;

// G-1417 G-1419: record / replay, in a test and outside test bodies (module level, beforeAll)
const SETUP = `${GET}
${PUT}
const modLevel = get('svc.detjs.test', process.env.COUNTER_PORT, '/module');
let fixtureBody = null;
beforeAll(async () => { fixtureBody = await get('svc.detjs.test', process.env.COUNTER_PORT, '/fixture'); });
test('uses the fixture', async () => {
  put('module', await modLevel);
  put('fixture', fixtureBody);
  expect(fixtureBody).toMatch(/^response #/);
});
test('in the test', async () => { const b = await get('svc.detjs.test', process.env.COUNTER_PORT, '/test'); put('intest', b); expect(b).toMatch(/^response #/); });`;
const GLOBAL_SETUP = {
  // globalSetup: runs in the runner's main process before any test file
  'gs.cjs': `const http = require('node:http'); const fs = require('node:fs');
${LOOKUP}
module.exports = async function () {
  const b = await new Promise((resolve, reject) => http.get({ host: 'svc.detjs.test', port: Number(process.env.COUNTER_PORT), path: '/global', lookup, agent: false }, (r) => {
    let s = ''; r.on('data', (d) => { s += d; }); r.on('end', () => resolve(s));
  }).on('error', reject));
  fs.mkdirSync('out', { recursive: true });
  fs.writeFileSync('out/global.txt', b);
};
`,
};

for (const runner of RUNNERS) {
  describe(`${runner}: network fingerprint`, () => {
    test('G-1415 G-1417: loopback bytes are in the fingerprint; the HTTP Date header is virtual; a different answer diverges [net]', T, () => {
      const dir = proj(runner, 'loopback', { a: LOCAL_SERVER }, { 'answer.txt': 'first' });
      const r1 = run(runner, dir);
      assert.equal(r1.status, 0, show(r1));
      assert.equal(got(dir, 'date'), new Date(Date.parse('2025-01-01T00:00:00Z')).toUTCString(), 'the local HTTP server dates its answer on the virtual clock');
      const ev = events(dir, (e) => e.s === 'net');
      assert.ok(ev.some((e) => e.o === 'net.connect' && /^127\.0\.0\.1:<port> local$/.test(e.v)), JSON.stringify(ev));
      assert.ok(ev.some((e) => e.o === 'net.stream' && /^127\.0\.0\.1:<port> send=\d+:[0-9a-f]{16} recv=\d+:[0-9a-f]{16}$/.test(e.v)), JSON.stringify(ev));
      save(dir, 'run1.jsonl');
      assert.equal(run(runner, dir).status, 0);
      save(dir, 'run2.jsonl');
      const same = verify(dir, 'run1.jsonl', 'run2.jsonl');
      assert.equal(same.summary.stable, same.summary.tests, `same answer, other ephemeral port: identical\n${divergences(same)}`);
      fs.writeFileSync(path.join(dir, 'answer.txt'), 'second');
      assert.equal(run(runner, dir).status, 0);
      save(dir, 'run3.jsonl');
      const diff = verify(dir, 'run1.jsonl', 'run3.jsonl');
      const d = diff.tests.find((t) => t.nodeid.endsWith('::local service'));
      assert.equal(d.status, 'diverged', JSON.stringify(diff.summary));
      assert.equal(d.divergence.reason, 'net', JSON.stringify(d.divergence));
      assert.match(d.divergence.description, /net\.stream/);
      assert.equal(diff.tests.find((t) => t.nodeid.endsWith('::no network')).status, 'stable');
    });

    test('G-1416: a connection to a host given with --det-allow-host is an event with its bytes; a different answer diverges', T, async () => {
      const dir = proj(runner, 'allowhost', { a: ALLOWED });
      await withCounter(async (ports) => {
        const det = ['--det', '--det-allow-host=allowed.detjs.test'];
        const env = { COUNTER_PORT: String(ports.http) };
        const r1 = run(runner, dir, [], { det, env });
        assert.equal(r1.status, 0, show(r1));
        const ev = events(dir, (e) => e.s === 'net');
        assert.ok(ev.some((e) => e.o === 'net.connect' && e.v === `allowed.detjs.test:${ports.http} allowed`), JSON.stringify(ev));
        assert.ok(ev.some((e) => e.o === 'net.stream' && e.v.startsWith(`allowed.detjs.test:${ports.http} send=`)), JSON.stringify(ev));
        save(dir, 'run1.jsonl');
        assert.equal(run(runner, dir, [], { det, env }).status, 0); // the counter answers "response #2"
        save(dir, 'run2.jsonl');
        const rep = verify(dir, 'run1.jsonl', 'run2.jsonl');
        assert.equal(rep.summary.diverged, 1, JSON.stringify(rep.summary));
        assert.equal(rep.tests[0].divergence.reason, 'net', JSON.stringify(rep.tests[0].divergence));
      });
    });

    test('G-1417 G-1419: recorded and replayed bytes are in the fingerprint; connections outside test bodies are recorded and replayed', T, async () => {
      const dir = proj(runner, 'setup', { a: SETUP }, GLOBAL_SETUP, { vitest: { globalSetup: ['./gs.cjs'] }, jest: { globalSetup: './gs.cjs' } });
      await withCounter(async (ports, stop) => {
        const env = { COUNTER_PORT: String(ports.http) };
        const rec = run(runner, dir, [], { det: ['--det', '--det-record'], env });
        assert.equal(rec.status, 0, show(rec));
        save(dir, 'rec1.jsonl');
        const recorded = { global: got(dir, 'global'), module: got(dir, 'module'), fixture: got(dir, 'fixture'), intest: got(dir, 'intest') };
        const cas = JSON.parse(fs.readFileSync(path.join(dir, '.detjs', 'cassette.json'), 'utf8'));
        const keys = Object.keys(cas.tests);
        assert.ok(keys.includes('<startup>'), `globalSetup recorded: ${keys}`);
        assert.ok(keys.some((k) => k.endsWith('::<setup>')), `module level and beforeAll recorded: ${keys}`);
        const setupKey = keys.find((k) => k.endsWith('::<setup>'));
        assert.equal(cas.tests[setupKey].length, 2, 'module level + beforeAll');
        for (const k of keys) for (const c of cas.tests[k]) assert.match(c.recorded_at, /^\d{4}-\d\d-\d\dT/, 'each recording carries its time');
        const ev = events(dir, (e) => e.s === 'net');
        assert.ok(ev.some((e) => e.o === 'net.stream' && /^svc\.detjs\.test:\d+ send=\d+:\w+ recv=\d+:\w+$/.test(e.v)), JSON.stringify(ev));
        assert.ok(ev.some((e) => e.o === 'net.setup' && /file=2:\w+ startup=1:\w+/.test(e.v)), `set-up traffic summarised in the tests: ${JSON.stringify(ev)}`);
        // a second recording gets other answers (the counter moved on): not identical
        assert.equal(run(runner, dir, [], { det: ['--det', '--det-record'], env }).status, 0);
        save(dir, 'rec2.jsonl');
        const two = verify(dir, 'rec1.jsonl', 'rec2.jsonl');
        assert.equal(two.summary.diverged, two.summary.tests, `different answers while recording: ${JSON.stringify(two.summary)}`);
        for (const t of two.tests) assert.equal(t.divergence.reason, 'net', JSON.stringify(t.divergence));
        const second = { global: got(dir, 'global'), module: got(dir, 'module'), fixture: got(dir, 'fixture'), intest: got(dir, 'intest') };
        stop();
        // replay with the service gone: every answer comes from the cassette, the trace equals the last recording
        fs.rmSync(path.join(dir, 'out'), { recursive: true, force: true });
        const rep = run(runner, dir, [], { env });
        assert.equal(rep.status, 0, `replay of start-up, set-up and test connections\n${show(rep)}`);
        assert.deepEqual({ global: got(dir, 'global'), module: got(dir, 'module'), fixture: got(dir, 'fixture'), intest: got(dir, 'intest') }, second);
        assert.notDeepEqual(second, recorded);
        save(dir, 'rep.jsonl');
        // the replayed bytes are the recorded ones (the connect events say record# / replay#)
        const streams = (f) => fs.readFileSync(path.join(dir, f), 'utf8').match(/"o":"net\.(?:stream|setup)"[^}]*/g);
        assert.deepEqual(streams('rep.jsonl'), streams('rec2.jsonl'));
        assert.equal(run(runner, dir, [], { env }).status, 0);
        save(dir, 'rep2.jsonl');
        const same = verify(dir, 'rep.jsonl', 'rep2.jsonl');
        assert.equal(same.summary.stable, same.summary.tests, `two replays identical\n${divergences(same)}`);
      });
    });
  });
}

// ---------------------------------------------------------------------------------------------------------------
// G-1418: cassette staleness
const STALE = `${GET}
test('old api', async () => { expect(await get('svc.detjs.test', process.env.COUNTER_PORT)).toMatch(/^response #/); });`;
function ageCassette(dir, days) {
  const p = path.join(dir, '.detjs', 'cassette.json');
  const j = JSON.parse(fs.readFileSync(p, 'utf8'));
  for (const conns of Object.values(j.tests)) for (const c of conns) c.recorded_at = new Date(Date.now() - days * 86400000).toISOString();
  fs.writeFileSync(p, JSON.stringify(j, null, 2));
}
for (const runner of RUNNERS) {
  test(`${runner}: G-1418 cassette recordings carry their age: old ones are reported, --det-cassette-max-age refuses them, the cache keys it`, T, async () => {
    const dir = proj(runner, 'stale', { a: STALE });
    await withCounter(async (ports, stop) => {
      const env = { COUNTER_PORT: String(ports.http) };
      assert.equal(run(runner, dir, [], { det: ['--det', '--det-record'], env }).status, 0);
      stop();
      const fresh = run(runner, dir, [], { env, det: ['--det', '--det-cassette-max-age=7'] });
      assert.equal(fresh.status, 0, show(fresh));
      assert.doesNotMatch(fresh.stderr, /stale|days old/, show(fresh));
      ageCassette(dir, 400);
      const old = run(runner, dir, [], { env });
      assert.equal(old.status, 0, show(old));
      assert.match(old.stderr, /recordings up to 400 days old .*re-record with --det-record/, show(old));
      // with the cache: a result replayed from a fresh-enough recording is reused; once the limit makes the recording
      // stale the result is not reused and the test fails like a fresh run
      const c1 = run(runner, dir, [], { env, cache: true, det: ['--det', '--det-cassette-max-age=1000'] });
      assert.equal(c1.status, 0, show(c1));
      const c2 = run(runner, dir, [], { env, cache: true, det: ['--det', '--det-cassette-max-age=1000'] });
      assert.ok(reused(c2).includes(`t/a${EXT[runner]}`), show(c2));
      const refused = run(runner, dir, [], { env, cache: true, det: ['--det', '--det-cassette-max-age=90'] });
      assert.notEqual(refused.status, 0, `a 400-day-old recording must not be replayed with a 90-day limit\n${show(refused)}`);
      assert.deepEqual(reused(refused), [], show(refused));
      assert.match(refused.stdout + refused.stderr, /400 days old \(--det-cassette-max-age=90\): re-record with --det-record/, show(refused));
      assert.match(fs.readFileSync(path.join(dir, '.detjs', 'trace.jsonl'), 'utf8'), /svc\.detjs\.test:\d+ stale/);
    });
  });
}

// ---------------------------------------------------------------------------------------------------------------
// G-1420: HTTP/2 over TLS (ALPN h2) recorded and replayed; G-2165: the replay certificate is generated, verification
// is bypassed for replayed sockets only
const H2 = `${LOOKUP}
${PUT}
function h2get(port, p) {
  return new Promise((resolve, reject) => {
    const c = http2.connect('https://h2.detjs.test:' + port, { lookup, rejectUnauthorized: false });
    c.on('error', reject);
    const rq = c.request({ ':path': p });
    let b = ''; rq.setEncoding('utf8'); rq.on('data', (d) => { b += d; }); rq.on('error', reject);
    rq.on('end', () => { resolve(c.alpnProtocol + ' ' + b); c.close(); });
    rq.end();
  });
}
function httpsGet(port, p, extra = {}) {
  return new Promise((resolve, reject) => https.get({ host: 'h1.detjs.test', port, path: p, lookup, agent: false, rejectUnauthorized: false, ...extra }, (r) => {
    let b = ''; r.on('data', (d) => { b += d; }); r.on('end', () => resolve(b));
  }).on('error', reject));
}
test('http2 over tls', async () => { const b = await h2get(Number(process.env.H2_PORT), '/h2'); put('h2', b); expect(b).toMatch(/^h2 response #/); });
test('https and a strict local tls connection', async () => {
  put('https', await httpsGet(Number(process.env.HTTPS_PORT), '/h1'));
  // a local TLS server with an untrusted self-signed certificate: verification is NOT bypassed outside replay
  const err = await new Promise((resolve) => {
    const s = tls.connect({ host: '127.0.0.1', port: Number(process.env.STRICT_PORT || process.env.HTTPS_PORT), servername: 'localhost' }, () => { resolve('connected'); s.destroy(); });
    s.on('error', (e) => resolve(e.code));
  });
  put('strict', err);
});`;
for (const runner of RUNNERS) {
  test(`${runner}: G-1420 G-2165 HTTP/2 over TLS replays with the recorded ALPN; the replay certificate is per process; verification stays on outside replay`, T, async () => {
    const dir = proj(runner, 'h2', { a: H2 });
    let recordedEnv;
    await withCounter(async (ports, stop) => {
      const env = { H2_PORT: String(ports.h2), HTTPS_PORT: String(ports.https) };
      recordedEnv = env;
      const rec = run(runner, dir, [], { det: ['--det', '--det-record'], env });
      assert.equal(rec.status, 0, show(rec));
      const recorded = { h2: got(dir, 'h2'), https: got(dir, 'https') };
      assert.match(recorded.h2, /^h2 response #/);
      const cas = JSON.parse(fs.readFileSync(path.join(dir, '.detjs', 'cassette.json'), 'utf8'));
      const conns = Object.values(cas.tests).flat();
      assert.ok(conns.some((c) => c.host === 'h2.detjs.test' && c.tls && c.alpn === 'h2'), JSON.stringify(conns.map((c) => [c.host, c.alpn])));
      assert.ok(conns.find((c) => c.host === 'h2.detjs.test').segments.length > 1, 'the HTTP/2 frames are recorded');
      stop();
      const rep = run(runner, dir, [], { env });
      assert.equal(rep.status, 0, `replay of HTTP/2 over TLS\n${show(rep)}`);
      assert.deepEqual({ h2: got(dir, 'h2'), https: got(dir, 'https') }, recorded);
      assert.equal(got(dir, 'strict'), 'ECONNREFUSED', 'the counter is stopped: refused, not "verified"');
    });
    // in the same test, the replayed HTTPS connection (verification bypassed for it) answers, and a strict connection
    // to a live untrusted local TLS server fails verification under --det
    await withCounter(async (ports) => {
      const rep = run(runner, dir, ['-t', 'strict'], { env: { ...recordedEnv, STRICT_PORT: String(ports.https) } });
      assert.equal(rep.status, 0, show(rep));
      assert.match(got(dir, 'https'), /^response #/);
      assert.equal(got(dir, 'strict'), 'DEPTH_ZERO_SELF_SIGNED_CERT');
    });
  });
}

test('G-2165: no private key is shipped in the engine sources', () => {
  const src = path.join(__dirname, '..', 'src');
  const hits = [];
  const walk = (d) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p);
      else if (/BEGIN (?:RSA |EC )?PRIVATE KEY/.test(fs.readFileSync(p, 'utf8'))) hits.push(p);
    }
  };
  walk(src);
  assert.deepEqual(hits, []);
  const { replayCert, generate } = require('../src/selfcert');
  const a = generate();
  const b = generate();
  assert.notEqual(a.cert, b.cert, 'a new certificate each time');
  assert.equal(replayCert(), replayCert(), 'one per process');
  assert.match(new (require('node:crypto').X509Certificate)(a.cert).subject, /detjs network replay/);
});
