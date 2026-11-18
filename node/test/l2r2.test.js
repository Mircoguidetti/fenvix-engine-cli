'use strict';
// Level 2 browser, round 2 (docs/L2-BROWSER.md): fixture apps for the sources of divergence the
// round 2 diagnosis found on real projects. Each test fails on the round 1 engine and passes after
// its fix. Needs @playwright/test and a Chromium (as test/playwright.test.js).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { TMP, BIN, readTrace } = require('./helpers');

function chromium() {
  if (process.env.DETJS_PW_EXECUTABLE) return process.env.DETJS_PW_EXECUTABLE;
  for (const p of ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser']) if (fs.existsSync(p)) return p;
  try {
    const pw = require('playwright-core');
    const p = pw.chromium.executablePath();
    if (p && fs.existsSync(p)) return p;
  } catch { /* not installed */ }
  return null;
}
function available() {
  try { require.resolve('@playwright/test/package.json', { paths: [__dirname] }); } catch { return 'no @playwright/test'; }
  return chromium() ? null : 'no Chromium (set DETJS_PW_EXECUTABLE)';
}
const skip = available() || false;

/** A fixture project: app.js (webServer), tests/*.spec.js, playwright.config.js. */
function project(name, { app, specs, port, extraFiles = {}, config = '' }) {
  const dir = path.join(TMP, 'l2r2', name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), `{"name":"fixture-${name}","private":true}`);
  fs.writeFileSync(path.join(dir, 'app.js'), app);
  for (const [f, body] of Object.entries(specs)) fs.writeFileSync(path.join(dir, 'tests', f), body);
  for (const [f, body] of Object.entries(extraFiles)) {
    fs.mkdirSync(path.dirname(path.join(dir, f)), { recursive: true });
    fs.writeFileSync(path.join(dir, f), body);
  }
  fs.writeFileSync(path.join(dir, 'playwright.config.js'), `module.exports = {
  testDir: './tests', fullyParallel: true, workers: 2, reporter: 'list', timeout: 30000,
  use: { baseURL: 'http://localhost:${port}', launchOptions: { executablePath: ${JSON.stringify(chromium())} } },
  webServer: { command: 'node app.js', url: 'http://localhost:${port}/health', reuseExistingServer: false },
  ${config}
};\n`);
  return dir;
}

function pw(dir, args, label, extraEnv = {}) {
  const env = { ...process.env, DETJS_PW_EXECUTABLE: chromium(), ...extraEnv };
  delete env.CI; delete env.DETJS; delete env.NODE_OPTIONS;
  const r = spawnSync(process.execPath, [BIN, 'playwright', 'test', ...args], { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  const tracePath = path.join(dir, '.detjs', 'trace.jsonl');
  let trace = null;
  if (args.includes('--det') && fs.existsSync(tracePath)) {
    const keep = path.join(dir, `trace-${label}.jsonl`);
    fs.renameSync(tracePath, keep);
    trace = { path: keep, ...readTrace(keep) };
  }
  return { status: r.status, out: r.stdout + r.stderr, trace };
}

function verify(paths) {
  const r = spawnSync(process.execPath, [BIN, 'verify', ...paths, '--json'], { encoding: 'utf8' });
  return JSON.parse(r.stdout);
}
const outcomes = (run) => run.trace.tests.map((t) => t.outcome);

// ---------------------------------------------------------------------------------------------
// 1. Start state. The app keeps users in a file; the test registers a user with a random e-mail
// (seeded under --det: the same e-mail in every replay). Without a restore, replay 2 finds the
// user of replay 1 and gets 409 (documenso in round 1: 510 of 595 tests broken this way).
const STATE_PORT = 4611;
const STATE_APP = `
const http = require('http');
const fs = require('fs');
const DB = 'data/users.json';
const load = () => (fs.existsSync(DB) ? JSON.parse(fs.readFileSync(DB, 'utf8')) : []);
http.createServer((req, res) => {
  if (req.url === '/health') return res.end('ok');
  if (req.url === '/api/register' && req.method === 'POST') {
    let b = ''; req.on('data', (c) => (b += c));
    return req.on('end', () => {
      const users = load();
      const { email } = JSON.parse(b);
      if (users.includes(email)) { res.statusCode = 409; return res.end('exists'); }
      users.push(email);
      fs.mkdirSync('data', { recursive: true });
      fs.writeFileSync(DB, JSON.stringify(users));
      res.statusCode = 201; res.end('created ' + users.length);
    });
  }
  res.statusCode = 404; res.end();
}).listen(${STATE_PORT});
`;
const STATE_SPEC = `
const { test, expect } = require('@playwright/test');
test('registers a new user', async ({ request }) => {
  const email = 'u' + Math.floor(Math.random() * 1e9) + '@example.com';
  const r = await request.post('/api/register', { data: { email } });
  expect(r.status()).toBe(201);
});
`;

test('--det-state: every replay starts from the saved files (a seeded registration replays 3/3 with one fingerprint)', { skip, timeout: 600000 }, () => {
  const dir = project('state', {
    app: STATE_APP, port: STATE_PORT, specs: { 'state.spec.js': STATE_SPEC },
    extraFiles: { 'data/users.json': '["seed@example.com"]', 'detjs-state.json': '{"files": ["data/"]}' },
  });
  // Without the restore the second replay collides with the first (the round 1 behaviour).
  const a = pw(dir, ['--det'], 'nostate-1');
  const b = pw(dir, ['--det'], 'nostate-2');
  assert.deepEqual([outcomes(a), outcomes(b)], [['passed'], ['failed']], a.out + b.out);
  // With --det-state: the first run saves the snapshot (the files as they are now: restore them first).
  fs.writeFileSync(path.join(dir, 'data', 'users.json'), '["seed@example.com"]');
  const runs = [1, 2, 3].map((i) => pw(dir, ['--det', '--det-state=detjs-state.json'], `state-${i}`));
  for (const r of runs) assert.deepEqual(outcomes(r), ['passed'], r.out);
  const v = verify(runs.map((r) => r.trace.path));
  assert.equal(v.summary.stable, 1, JSON.stringify(v.tests[0].divergence));
  assert.match(runs[0].out, /state saved and restored/);
  assert.equal(runs[0].trace.header.meta.state.digest, runs[2].trace.header.meta.state.digest);
});

// Postgres: CREATE DATABASE ... TEMPLATE copies (needs initdb/pg_ctl/psql; skipped without them).
function pgBin() {
  const roots = fs.existsSync('/usr/lib/postgresql') ? fs.readdirSync('/usr/lib/postgresql').sort().reverse() : [];
  for (const v of roots) {
    const b = path.join('/usr/lib/postgresql', v, 'bin');
    if (fs.existsSync(path.join(b, 'initdb')) && fs.existsSync(path.join(b, 'pg_ctl'))) return b;
  }
  return null;
}

test('detjs state: a Postgres database is restored to its snapshot (rows written after the save are gone)', { skip: !pgBin() ? 'no postgres binaries' : (process.getuid() === 0 && spawnSync('id', ['postgres']).status !== 0) ? 'root without a postgres user' : false, timeout: 120000 }, () => {
  const bin = pgBin();
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'detjs-pg-'));
  const data = path.join(base, 'data');
  const port = 5491;
  const asUser = process.getuid() === 0 ? ['runuser', '-u', 'postgres', '--'] : [];
  if (asUser.length) spawnSync('chown', ['-R', 'postgres', base]);
  const sh = (cmd, args) => {
    const full = [...asUser, cmd, ...args];
    const r = spawnSync(full[0], full.slice(1), { encoding: 'utf8', cwd: base });
    if (r.status !== 0) throw new Error(`${full.join(' ')}: ${r.stdout}${r.stderr}`);
    return r.stdout.trim();
  };
  sh(path.join(bin, 'initdb'), ['-D', data, '-A', 'trust', '-U', 'postgres']);
  sh(path.join(bin, 'pg_ctl'), ['-D', data, '-l', path.join(base, 'pg.log'), '-o', `-p ${port} -k ${base} -c listen_addresses=localhost`, '-w', 'start']);
  try {
    const url = `postgres://postgres@localhost:${port}/app`;
    const q = (sql, db = 'app') => sh('psql', [`postgres://postgres@localhost:${port}/${db}`, '-At', '-v', 'ON_ERROR_STOP=1', '-c', sql]);
    q('CREATE DATABASE app', 'postgres');
    q("CREATE TABLE users (email text unique); INSERT INTO users VALUES ('seed@example.com')");
    const specFile = path.join(base, 'state.json');
    fs.writeFileSync(specFile, JSON.stringify({ postgres: [url] }));
    if (asUser.length) spawnSync('chown', ['-R', 'postgres', base]);
    const st = (cmd) => {
      const r = spawnSync(process.execPath, [BIN, 'state', cmd, `--det-state=${specFile}`], { encoding: 'utf8', cwd: base });
      assert.equal(r.status, 0, r.stderr);
    };
    st('save');
    q("INSERT INTO users VALUES ('replay@example.com')");
    assert.equal(q('SELECT count(*) FROM users'), '2');
    st('restore');
    assert.equal(q('SELECT string_agg(email, \',\') FROM users'), 'seed@example.com');
    q("INSERT INTO users VALUES ('replay@example.com')"); // the replay's insert succeeds again
  } finally {
    sh(path.join(bin, 'pg_ctl'), ['-D', data, '-m', 'immediate', 'stop']);
    fs.rmSync(base, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------------------------
// 2. Server background work (S1 + S2). A pool reaper / stats job reads the clock and draws random
// numbers every few real milliseconds; requests return a timestamp and an id. With one clock counter
// and one stream per process, the values a request sees depend on how many background reads came
// before (uptime-kuma's createdAt), and the background events enter the test's server fingerprint
// (etherpad, solid-start).
const BG_PORT = 4612;
const BG_APP = `
const http = require('http');
const crypto = require('crypto');
let stats = 0;
setInterval(() => { stats += Date.now() % 7 + Math.floor(Math.random() * 3); }, 3);
http.createServer((req, res) => {
  if (req.url === '/health') return res.end('ok');
  if (req.url === '/') {
    res.setHeader('content-type', 'text/html');
    return res.end('<!doctype html><div id=out>...</div><script>fetch("/api/item").then(r => r.json()).then(j => { out.textContent = j.created + " " + j.id; })</script>');
  }
  if (req.url === '/api/item') {
    return setTimeout(() => {
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ created: new Date().toISOString(), id: crypto.randomUUID(), r: Math.random() }));
    }, 15);
  }
  res.statusCode = 404; res.end();
}).listen(${BG_PORT});
`;
const BG_SPEC = `
const { test, expect } = require('@playwright/test');
test('an item from a server with background work', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#out')).not.toHaveText('...');
  await page.waitForTimeout(200);
});
`;

test('server scope: a server with a background job gives one fingerprint in 4 runs (S1+S2; round 1 behaviour with DETJS_PW_SCOPE=0 diverges)', { skip, timeout: 600000 }, () => {
  const dir = project('bg', { app: BG_APP, port: BG_PORT, specs: { 'bg.spec.js': BG_SPEC } });
  const before = [1, 2, 3].map((i) => pw(dir, ['--det'], `noscope-${i}`, { DETJS_PW_SCOPE: '0' }));
  for (const r of before) assert.ok(r.trace, r.out);
  const vb = verify(before.map((r) => r.trace.path));
  assert.equal(vb.summary.stable, 0, 'round 1 behaviour: background work changes the fingerprint');
  const runs = [1, 2, 3, 4].map((i) => pw(dir, ['--det'], `scope-${i}`));
  for (const r of runs) assert.deepEqual(outcomes(r), ['passed'], r.out);
  const v = verify(runs.map((r) => r.trace.path));
  assert.equal(v.summary.stable, 1, JSON.stringify(v.tests[0].divergence));
  const ev = runs[0].trace.tests[0].events;
  assert.ok(ev.some((e) => e.o === 'server.fingerprint'), 'the server takes part in the fingerprint');
});

// ---------------------------------------------------------------------------------------------
// 3. Web worker randomness (S4): the app makes its ids in a dedicated worker (actual).
const WK_PORT = 4613;
const WK_APP = `
const http = require('http');
http.createServer((req, res) => {
  if (req.url === '/health') return res.end('ok');
  if (req.url === '/') {
    res.setHeader('content-type', 'text/html');
    return res.end('<!doctype html><div id=out>...</div><script>const w = new Worker("/worker.js"); w.onmessage = (e) => { out.textContent = e.data; }; w.postMessage("go");</script>');
  }
  if (req.url === '/worker.js') {
    res.setHeader('content-type', 'text/javascript');
    return res.end('onmessage = () => postMessage(crypto.randomUUID() + " " + Math.random().toFixed(8));');
  }
  res.statusCode = 404; res.end();
}).listen(${WK_PORT});
`;
const WK_SPEC = `
const { test, expect } = require('@playwright/test');
const fs = require('fs');
test('ids made in a web worker', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#out')).not.toHaveText('...');
  fs.appendFileSync(process.env.IDS_FILE, (await page.locator('#out').textContent()) + '\\n');
});
`;

test('web workers: ids drawn in a dedicated worker are the same in 3 runs, one fingerprint (S4)', { skip, timeout: 600000 }, () => {
  const dir = project('worker', { app: WK_APP, port: WK_PORT, specs: { 'worker.spec.js': WK_SPEC } });
  const ids = path.join(dir, 'ids.txt');
  const offIds = path.join(dir, 'ids-off.txt');
  const off = [1, 2, 3].map((i) => pw(dir, ['--det'], `wk-off-${i}`, { IDS_FILE: offIds, DETJS_PW_WORKER_SEEDS: '0' }));
  for (const r of off) assert.deepEqual(outcomes(r), ['passed'], r.out);
  assert.equal(new Set(fs.readFileSync(offIds, 'utf8').trim().split('\n')).size, 3, 'round 1 behaviour: the worker draws OS randomness');
  const runs = [1, 2, 3].map((i) => pw(dir, ['--det'], `wk-${i}`, { IDS_FILE: ids }));
  for (const r of runs) assert.deepEqual(outcomes(r), ['passed'], r.out);
  const lines = fs.readFileSync(ids, 'utf8').trim().split('\n');
  assert.equal(lines.length, 3);
  assert.equal(new Set(lines).size, 1, lines.join(' | '));
  const v = verify(runs.map((r) => r.trace.path));
  assert.equal(v.summary.stable, 1, JSON.stringify(v.tests[0].divergence));
  assert.ok(runs[0].trace.tests[0].events.some((e) => e.o === 'worker.seeded'));
});

// ---------------------------------------------------------------------------------------------
// 4. Server pushes vs responses (S5): the page sends a WebSocket message and fetches; the server
// answers the fetch and pushes a frame about it. Which one the page sees first depends on timing.
const WS_PORT = 4614;
const WS_APP = `
const http = require('http');
const { WebSocketServer } = require('ws');
const socks = new Set();
const srv = http.createServer((req, res) => {
  if (req.url === '/health') return res.end('ok');
  if (req.url === '/') {
    res.setHeader('content-type', 'text/html');
    return res.end('<!doctype html><div id=log></div><script>' +
      'const log = (x) => { const d = document.createElement("div"); d.textContent = x; document.getElementById("log").appendChild(d); };' +
      'const ws = new WebSocket("ws://" + location.host + "/ws");' +
      'ws.onmessage = (e) => log("push " + e.data);' +
      'ws.onopen = () => { ws.send("hello"); fetch("/api/save", { method: "POST" }).then(r => r.text()).then(t => log("response " + t)); };' +
      '</script>');
  }
  if (req.url === '/api/save') {
    // Real entropy (file reads are not seeded): the push follows the response by 0-60 real ms.
    const fd = require('fs').openSync('/dev/urandom', 'r'); const b = Buffer.alloc(1); require('fs').readSync(fd, b, 0, 1, null); require('fs').closeSync(fd);
    const n = b[0] % 60;
    res.end('ok');
    return setTimeout(() => { for (const s of socks) s.send('saved'); }, n);
  }
  res.statusCode = 404; res.end();
});
const wss = new WebSocketServer({ server: srv, path: '/ws' });
wss.on('connection', (s) => { socks.add(s); s.on('message', (m) => setTimeout(() => s.send('ack ' + m), Math.floor(Math.random() * 5))); });
srv.listen(${WS_PORT});
`;
const WS_SPEC = `
const { test, expect } = require('@playwright/test');
const fs = require('fs');
test('push and response order', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#log div')).toHaveCount(3);
  fs.appendFileSync(process.env.IDS_FILE, (await page.locator('#log').innerText()).replace(/\\n/g, ' / ') + '\\n');
});
`;

test('server pushes: push frames and responses reach the page in one order, one browser-side sequence in 6 runs (S5)', { skip, timeout: 600000 }, () => {
  const dir = project('push', { app: WS_APP, port: WS_PORT, specs: { 'push.spec.js': WS_SPEC } });
  const ids = path.join(dir, 'order.txt');
  // The fixture's push delay is real entropy, so the server fingerprint differs by design; the claim is about
  // what the page sees: the sequence of browser-side events (requests, responses, frames, DOM).
  const browserSide = (r) => JSON.stringify(r.trace.tests[0].events.filter((e) => e.o !== 'server.fingerprint').map((e) => [e.o, e.v]));
  // Round 1 behaviour (pushes relayed as they arrive): more than one browser-side sequence in 8 runs.
  const off = [1, 2, 3, 4, 5, 6, 7, 8].map((i) => pw(dir, ['--det'], `push-off-${i}`, { IDS_FILE: path.join(dir, 'order-off.txt'), DETJS_PW_SCOPE: '0', DETJS_PW_GATE_PUSH: '0' }));
  for (const r of off) assert.ok(r.trace, r.out);
  assert.ok(new Set(off.map(browserSide)).size > 1, 'round 1 behaviour: the push lands at different points');
  const runs = [1, 2, 3, 4, 5, 6].map((i) => pw(dir, ['--det'], `push-${i}`, { IDS_FILE: ids }));
  for (const r of runs) assert.deepEqual(outcomes(r), ['passed'], r.out);
  const lines = fs.readFileSync(ids, 'utf8').trim().split('\n');
  assert.equal(new Set(lines).size, 1, lines.join(' | '));
  assert.equal(new Set(runs.map(browserSide)).size, 1, runs.map(browserSide).join('\n'));
});

// ---------------------------------------------------------------------------------------------
// 5. The test code's clock (documenso: seed helpers in the test write `new Date()` into rows).
const CK_PORT = 4615;
const CK_APP = `
const http = require('http');
http.createServer((req, res) => {
  if (req.url === '/health') return res.end('ok');
  let b = ''; req.on('data', (c) => (b += c)); req.on('end', () => res.end('stored ' + b));
}).listen(${CK_PORT});
`;
const CK_SPEC = `
const { test, expect } = require('@playwright/test');
test('a row stamped by the test code', async ({ request }) => {
  const r = await request.post('/api/rows', { data: { verifiedAt: new Date().toISOString(), t0: performance.now() } });
  expect(r.status()).toBe(200);
});
`;

test('worker clock: dates made by the test code are the same in every run (round 1: real clock, 3 fingerprints)', { skip, timeout: 600000 }, () => {
  const dir = project('clock', { app: CK_APP, port: CK_PORT, specs: { 'clock.spec.js': CK_SPEC } });
  const off = [1, 2, 3].map((i) => pw(dir, ['--det'], `ck-off-${i}`, { DETJS_PW_WORKER_CLOCK: '0' }));
  for (const r of off) assert.deepEqual(outcomes(r), ['passed'], r.out);
  assert.equal(verify(off.map((r) => r.trace.path)).summary.stable, 0);
  const runs = [1, 2, 3].map((i) => pw(dir, ['--det'], `ck-${i}`));
  for (const r of runs) assert.deepEqual(outcomes(r), ['passed'], r.out);
  const v = verify(runs.map((r) => r.trace.path));
  assert.equal(v.summary.stable, 1, JSON.stringify(v.tests[0].divergence));
});
