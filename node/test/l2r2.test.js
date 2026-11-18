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
