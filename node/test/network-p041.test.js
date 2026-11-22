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
      // the server reads answer.txt in the test, so the first difference is that read (fs, R-050 N1); the loopback
      // bytes must differ too
      const streams = (f) => fs.readFileSync(path.join(dir, f), 'utf8').split('\n').filter((l) => l.startsWith('{"type":"test"'))
        .map((l) => JSON.parse(l)).filter((t) => t.nodeid.endsWith('::local service')).flatMap((t) => (t.events || []).filter((e) => e.o === 'net.stream').map((e) => e.v));
      const [s1, s3] = [streams('run1.jsonl'), streams('run3.jsonl')];
      assert.ok(s1.length === 1 && s3.length === 1 && s1[0] !== s3[0], `the loopback bytes differ: ${s1} vs ${s3}`);
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

// ---------------------------------------------------------------------------------------------------------------
// G-1421: WebSocket handshake keys and frame masks (global WebSocket = undici, and the `ws` package when it can be
// installed) are deterministic: two runs are identical, no entropy event
const PKGS = path.join(TMP, 'pkgs');
function packages() {
  // ws and better-sqlite3 for the tests that need them (network once; later runs reuse the directory)
  const want = ['ws', 'better-sqlite3'];
  if (want.every((p) => fs.existsSync(path.join(PKGS, 'node_modules', p, 'package.json')))) return true;
  fs.mkdirSync(PKGS, { recursive: true });
  fs.writeFileSync(path.join(PKGS, 'package.json'), JSON.stringify({ name: 'pkgs', private: true }));
  const r = spawnSync('npm', ['install', '--no-audit', '--no-fund', ...want], { cwd: PKGS, encoding: 'utf8', timeout: 300000 });
  return r.status === 0;
}
const linkPkgs = (dir) => { try { fs.symlinkSync(path.join(PKGS, 'node_modules'), path.join(dir, 'node_modules'), 'dir'); } catch { /* exists */ } };

const WS = `${PUT}
function wsServer() {
  const srv = http.createServer();
  srv.on('upgrade', (req, sock) => {
    const key = req.headers['sec-websocket-key'];
    put('key-' + req.url.slice(1), key);
    const acc = nodeCrypto.createHash('sha1').update(key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
    sock.write('HTTP/1.1 101 Switching Protocols\\r\\nUpgrade: websocket\\r\\nConnection: Upgrade\\r\\nSec-WebSocket-Accept: ' + acc + '\\r\\n\\r\\n');
    sock.once('data', (d) => {
      put('frame-' + req.url.slice(1), d.toString('hex'));
      const len = d[1] & 0x7f; const mask = d.subarray(2, 6); const p = Buffer.from(d.subarray(6, 6 + len)).map((b, i) => b ^ mask[i % 4]);
      sock.write(Buffer.concat([Buffer.from([0x81, p.length]), p]));
    });
    sock.on('error', () => {});
  });
  return new Promise((r) => srv.listen(0, '127.0.0.1', () => r(srv)));
}
async function echo(Ctor, name) {
  const srv = await wsServer();
  const ws = new Ctor('ws://127.0.0.1:' + srv.address().port + '/' + name);
  const got = await new Promise((resolve, reject) => {
    ws.onopen = () => ws.send('hello ' + name);
    ws.onmessage = (m) => resolve(String(m.data));
    ws.onerror = (e) => reject(e.error || e);
  });
  ws.close(); srv.close();
  return got;
}
test('global WebSocket', async () => { expect(await echo(globalThis.WebSocket, 'global')).toBe('hello global'); });
test('ws package', async () => {
  let WS; try { WS = require('ws'); } catch { put('key-ws', 'absent'); return; }
  expect(await echo(WS, 'ws')).toBe('hello ws');
});`;
const WS_REPLAY = `${PUT}
${LOOKUP}
function talk(msgs) {
  const WS = require('ws');
  const ws = new WS('ws://ws.detjs.test:' + process.env.COUNTER_PORT + '/', { lookup });
  const got = [];
  return new Promise((resolve, reject) => {
    ws.on('open', () => ws.send(msgs[0]));
    ws.on('message', (m) => { got.push(String(m)); if (got.length < msgs.length) ws.send(msgs[got.length]); else { ws.close(); resolve(got); } });
    ws.on('error', reject);
  });
}
test('first socket', async () => { const g = await talk(['first a', 'first b', 'first c']); put('one', g.join('|')); });
test('second socket', async () => { const g = await talk(['second a', 'second b']); put('two', g[1]); });`;
for (const runner of RUNNERS) {
  test(`${runner}: G-1421 WebSocket handshake keys and frame masks are deterministic (global WebSocket, ws)`, T, () => {
    const dir = proj(runner, 'websocket', { a: WS });
    if (packages()) linkPkgs(dir);
    const r1 = run(runner, dir);
    assert.equal(r1.status, 0, show(r1));
    const first = { g: got(dir, 'key-global'), gf: got(dir, 'frame-global'), w: got(dir, 'key-ws') };
    save(dir, 'run1.jsonl');
    const ev = events(dir);
    assert.ok(!ev.some((e) => e.s === 'entropy'), `no real entropy: ${JSON.stringify(ev.filter((e) => e.s === 'entropy'))}`);
    assert.ok(ev.some((e) => e.s === 'random' && /^nonce 16:/.test(e.v)), 'the handshake key is a recorded nonce');
    assert.doesNotMatch(r1.stdout + r1.stderr, /real OS entropy/, show(r1));
    const r2 = run(runner, dir);
    assert.equal(r2.status, 0, show(r2));
    assert.deepEqual({ g: got(dir, 'key-global'), gf: got(dir, 'frame-global'), w: got(dir, 'key-ws') }, first);
    save(dir, 'run2.jsonl');
    const rep = verify(dir, 'run1.jsonl', 'run2.jsonl');
    assert.equal(rep.summary.stable, rep.summary.tests, divergences(rep).join('\n'));
    if (first.w === 'absent') process.stderr.write(`(${runner}: the ws package could not be installed: checked with the global WebSocket only)\n`);
  });

  // a recorded WebSocket conversation replays in another order of tests: client frames are compared unmasked
  test(`${runner}: G-1421 a recorded WebSocket conversation (ws) replays alone and shuffled`, T, async () => {
    if (!packages()) { process.stderr.write(`(${runner}: ws not installable: skipped)\n`); return; }
    const dir = proj(runner, 'ws-replay', { a: WS_REPLAY });
    linkPkgs(dir);
    await withCounter(async (ports, stop) => {
      const env = { COUNTER_PORT: String(ports.http) };
      const rec = run(runner, dir, [], { det: ['--det', '--det-record'], env });
      assert.equal(rec.status, 0, show(rec));
      const recorded = { one: got(dir, 'one'), two: got(dir, 'two') };
      assert.match(recorded.two, /^echo #\d+ second b$/);
      stop();
      const alone = run(runner, dir, ['-t', 'second'], { env });
      assert.equal(alone.status, 0, `replaying the second WebSocket test alone\n${show(alone)}`);
      assert.equal(got(dir, 'two'), recorded.two);
      const shuffled = run(runner, dir, [], { env, det: ['--det', '--det-seed=3'] });
      assert.equal(shuffled.status, 0, show(shuffled));
    });
  });
}

// ---------------------------------------------------------------------------------------------------------------
// G-1426: crypto.randomBytes & co. stay observed by default (the Python shell's contract: OS entropy observed,
// --det-urandom controls it), and the run says so; --det-urandom=on controls them, =off is the explicit default
const ENT = `${PUT}
test('session token', () => { put('token', nodeCrypto.randomBytes(8).toString('hex')); });
test('plain', () => { expect(1).toBe(1); });`;
for (const runner of RUNNERS) {
  test(`${runner}: G-1426 OS entropy is observed by default and never silent; --det-urandom=on|off`, T, () => {
    const dir = proj(runner, 'entropy', { a: ENT });
    const r1 = run(runner, dir);
    assert.equal(r1.status, 0, show(r1));
    const out = r1.stdout + r1.stderr;
    assert.match(out, /entropy=observed \(--det-urandom to control\)/, show(r1));
    assert.match(out, /1 test\(s\) used real OS entropy, observed but not controlled \(crypto\.randomBytes\).*--det-urandom makes .* deterministic.*session token/, show(r1));
    assert.equal(trace(dir).header.meta.entropy, 'observed');
    const off = run(runner, dir, [], { det: ['--det', '--det-urandom=off'] });
    assert.match(off.stdout + off.stderr, /used real OS entropy/, show(off));
    const on1 = run(runner, dir, [], { det: ['--det', '--det-urandom=on'] });
    assert.equal(on1.status, 0, show(on1));
    assert.doesNotMatch(on1.stdout + on1.stderr, /used real OS entropy/, show(on1));
    assert.match(on1.stdout + on1.stderr, /entropy=controlled/);
    const t1 = got(dir, 'token');
    assert.equal(run(runner, dir, [], { det: ['--det', '--det-urandom'] }).status, 0);
    assert.equal(got(dir, 'token'), t1, 'controlled: the same token');
    const bad = run(runner, dir, [], { det: ['--det', '--det-urandom=maybe'] });
    assert.notEqual(bad.status, 0);
  });
}

// ---------------------------------------------------------------------------------------------------------------
// G-1427 better-sqlite3, G-1428 node:sqlite: random(), randomblob(), 'now', CURRENT_TIMESTAMP (column default
// included) are virtual and recorded; two runs identical
const SQLQ = "select random() % 1000000 as r, hex(randomblob(6)) as b, datetime('now') as n, CURRENT_TIMESTAMP as c, strftime('%s') as s, date('now', '+1 day') as d, julianday('2020-01-01') as j";
const SQL = `${PUT}
const big = (k, v) => (typeof v === 'bigint' ? String(v) : v);
test('node sqlite', () => {
  let DatabaseSync; try { ({ DatabaseSync } = require('node:sqlite')); } catch { put('node', 'absent'); return; }
  const db = new DatabaseSync(':memory:');
  db.exec('create table t (id integer primary key, at text default CURRENT_TIMESTAMP, r integer default (random() % 1000))');
  db.exec('insert into t (id) values (1)');
  put('node', JSON.stringify({ ...db.prepare("${SQLQ}").get(), t: { ...db.prepare('select * from t').get() } }, big));
});
test('better sqlite3', () => {
  let Database; try { Database = require('better-sqlite3'); } catch { put('better', 'absent'); return; }
  const db = new Database(':memory:');
  db.exec('create table t (id integer primary key, at text default CURRENT_TIMESTAMP, r integer default (random() % 1000))');
  db.prepare('insert into t (id) values (1)').run();
  put('better', JSON.stringify({ ...db.prepare("${SQLQ}").get(), t: db.prepare('select * from t').get() }, big));
});
test('a function the test defines replaces Level 0s', () => {
  const { DatabaseSync } = require('node:sqlite');
  const db = new DatabaseSync(':memory:');
  db.function('random', () => 4);
  put('override', db.prepare('select random() as r').get().r);
});`;
for (const runner of RUNNERS) {
  test(`${runner}: G-1427 G-1428 SQLite random(), randomblob(), 'now' and CURRENT_TIMESTAMP are virtual and recorded (node:sqlite, better-sqlite3)`, T, () => {
    const dir = proj(runner, 'sqlite', { a: SQL });
    if (packages()) linkPkgs(dir);
    const r1 = run(runner, dir);
    assert.equal(r1.status, 0, show(r1));
    const first = { node: got(dir, 'node'), better: got(dir, 'better') };
    for (const [lib, text] of Object.entries(first)) {
      if (text === 'absent') { process.stderr.write(`(${runner}: ${lib} not available here)\n`); continue; }
      const v = JSON.parse(text);
      assert.equal(v.n, '2025-01-01 00:00:00', `${lib}: 'now' is the virtual epoch`);
      assert.equal(v.c, '2025-01-01 00:00:00', `${lib}: CURRENT_TIMESTAMP`);
      assert.equal(v.s, '1735689600');
      assert.equal(v.d, '2025-01-02', `${lib}: modifiers keep SQLite's semantics`);
      assert.equal(v.j, 2458849.5);
      assert.equal(v.t.at, '2025-01-01 00:00:00', `${lib}: column default`);
    }
    assert.notEqual(first.node, 'absent', 'node:sqlite is available on the release Node versions');
    assert.equal(got(dir, 'override'), '4', 'a user-defined random() wins');
    const ev = events(dir);
    assert.ok(ev.some((e) => e.o === 'sqlite.random') && ev.some((e) => e.o === 'sqlite.randomblob') && ev.some((e) => e.s === 'time' && e.o === 'sqlite.datetime'), JSON.stringify(ev.filter((e) => /sqlite/.test(e.o))));
    save(dir, 'run1.jsonl');
    assert.equal(run(runner, dir).status, 0);
    assert.deepEqual({ node: got(dir, 'node'), better: got(dir, 'better') }, first, 'the same values in a second run');
    save(dir, 'run2.jsonl');
    const rep = verify(dir, 'run1.jsonl', 'run2.jsonl');
    // `better-sqlite3` is a third-party COMPILED extension and no audited list names it, so the general rule
    // refuses that one test and names the addon (founder decision 2026-11-21, route 1, docs/NATIVE-AUDITS.md).
    // The two tests that use the BUILTIN `node:sqlite`, which the engine virtualises, must stay stable, and
    // the refusal must name the addon -- a blanket refusal of the file would fail this.
    // MEASURED: "covered by Level 0: 2  not proven: 1", the one being `better sqlite3`, named
    // `native:.../better-sqlite3/prebuilds/linux-x64.node`.
    const refused = (rep.tests || []).filter((t) => t.status !== 'stable');
    assert.equal(rep.summary.stable, rep.summary.tests - refused.length, divergences(rep).join('\n'));
    for (const t of refused) {
      assert.match(String(t.nodeid), /better sqlite3/, `only the better-sqlite3 test may be refused: ${t.nodeid}`);
      assert.match(JSON.stringify(t), /better-sqlite3/, `the refusal must name the addon: ${JSON.stringify(t)}`);
    }
  });
}

// ---------------------------------------------------------------------------------------------------------------
// G-1429: WASI random_get and clock_time_get
function wasmModule() {
  const u = (n) => { const o = []; do { let b = n & 0x7f; n >>>= 7; if (n) b |= 0x80; o.push(b); } while (n); return o; };
  const str = (s) => [...u(s.length), ...Buffer.from(s)];
  const sec = (id, b) => [id, ...u(b.length), ...b];
  const vec = (items) => [...u(items.length), ...items.flat()];
  const types = vec([[0x60, 2, 0x7f, 0x7f, 1, 0x7f], [0x60, 3, 0x7f, 0x7e, 0x7f, 1, 0x7f], [0x60, 0, 0]]);
  const W = 'wasi_snapshot_preview1';
  const imports = vec([[...str(W), ...str('random_get'), 0, 0], [...str(W), ...str('clock_time_get'), 0, 1]]);
  // random_get(0, 16); clock_time_get(0 realtime, 1, 64); clock_time_get(1 monotonic, 1, 72)
  const body = [0, 0x41, 0, 0x41, 16, 0x10, 0, 0x1a, 0x41, 0, 0x42, 1, 0x41, 0xc0, 0x00, 0x10, 1, 0x1a, 0x41, 1, 0x42, 1, 0x41, 0xc8, 0x00, 0x10, 1, 0x1a, 0x0b];
  return Buffer.from([0, 0x61, 0x73, 0x6d, 1, 0, 0, 0, ...sec(1, types), ...sec(2, imports), ...sec(3, vec([[2]])),
    ...sec(5, vec([[0, 1]])), ...sec(7, vec([[...str('memory'), 2, 0], [...str('_start'), 0, 2]])), ...sec(10, vec([[...u(body.length), ...body]]))]);
}
const WASI_T = `${PUT}
test('wasi', async () => {
  const { WASI } = require('node:wasi');
  const wasi = new WASI({ version: 'preview1' });
  const { instance } = await WebAssembly.instantiate(fs.readFileSync('mod.wasm'), wasi.getImportObject());
  wasi.start(instance);
  const dv = new DataView(instance.exports.memory.buffer);
  put('rand', Buffer.from(instance.exports.memory.buffer, 0, 16).toString('hex'));
  put('wall', dv.getBigUint64(64, true));
  put('mono', dv.getBigUint64(72, true));
});`;
for (const runner of RUNNERS) {
  test(`${runner}: G-1429 WASI random_get and clock_time_get are seeded / virtual and recorded`, T, () => {
    const dir = proj(runner, 'wasi', { a: WASI_T }, { 'mod.wasm': wasmModule() });
    const r1 = run(runner, dir);
    assert.equal(r1.status, 0, show(r1));
    const first = { rand: got(dir, 'rand'), wall: got(dir, 'wall'), mono: got(dir, 'mono') };
    assert.equal(BigInt(first.wall) / 1000000000n, 1735689600n, `the virtual wall clock: ${first.wall}`);
    assert.notEqual(first.rand, '0'.repeat(32));
    const ev = events(dir);
    assert.ok(ev.some((e) => e.s === 'random' && e.o === 'wasi.random_get') && ev.some((e) => e.s === 'time' && e.o === 'wasi.clock_time_get'), JSON.stringify(ev));
    save(dir, 'run1.jsonl');
    assert.equal(run(runner, dir).status, 0);
    assert.deepEqual({ rand: got(dir, 'rand'), wall: got(dir, 'wall'), mono: got(dir, 'mono') }, first);
    save(dir, 'run2.jsonl');
    const rep = verify(dir, 'run1.jsonl', 'run2.jsonl');
    assert.equal(rep.summary.stable, rep.summary.tests, divergences(rep).join('\n'));
  });
}
