'use strict';
// Level 2 browser prototype (`detjs playwright --det`, docs/L2-BROWSER.md) on a
// fixture app with three flaky-by-design races between browser, runner and
// server. Needs @playwright/test (devDependency) and a Chromium: the browser
// Playwright installed, or DETJS_PW_EXECUTABLE (e.g. /usr/bin/google-chrome).
// Skipped when neither is available.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { TMP, BIN, readTrace } = require('./helpers');

const DIR = path.join(TMP, 'playwright', 'races');
const PORT = 4597;

function chromium() {
  if (process.env.DETJS_PW_EXECUTABLE) return process.env.DETJS_PW_EXECUTABLE;
  for (const p of ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser']) if (fs.existsSync(p)) return p;
  return null;
}

function available() {
  try { require.resolve('@playwright/test/package.json', { paths: [__dirname] }); } catch { return 'no @playwright/test'; }
  return chromium() ? null : 'no Chromium (set DETJS_PW_EXECUTABLE)';
}

const APP = `
const http = require('http');
const crypto = require('crypto');
let counter = 0;
const notes = [];
const page = (body) => '<!doctype html><html><body>' + body + '</body></html>';
http.createServer((req, res) => {
  const u = new URL(req.url, 'http://x');
  const delay = Math.floor(Math.random() * 40);
  if (u.pathname === '/race') {
    res.setHeader('content-type', 'text/html');
    return res.end(page('<div id=out>loading</div><script>' +
      "fetch('/api/slow?n=a').then(r => r.text()).then(x => { out.textContent = x; });" +
      "fetch('/api/slow?n=b').then(r => r.text()).then(x => { out.textContent = x; });</script>"));
  }
  if (u.pathname === '/ids') {
    res.setHeader('content-type', 'text/html');
    return res.end(page('<div id=sid>' + crypto.randomUUID() + '</div><div id=when>' + new Date().toISOString() +
      '</div><div id=r></div><script>r.textContent = Math.random().toFixed(6) + " " + crypto.randomUUID() + " " + new Date().toISOString();</script>'));
  }
  if (u.pathname === '/api/slow') { counter++; const n = u.searchParams.get('n'); return setTimeout(() => res.end(n + counter), delay); }
  if (u.pathname === '/api/note' && req.method === 'POST') {
    let b = ''; req.on('data', (c) => (b += c));
    return req.on('end', () => setTimeout(() => { notes.push(b); res.end('ok'); }, delay));
  }
  if (u.pathname === '/api/notes') return res.end(JSON.stringify(notes));
  res.statusCode = 404; res.end('nf');
}).listen(${PORT});
`;

const SPEC = `
const { test, expect } = require('@playwright/test');
const fs = require('fs');
test('race: the last response wins', async ({ page }) => {
  await page.goto('/race');
  await expect(page.locator('#out')).not.toHaveText('loading');
  await page.waitForTimeout(100);
  await expect(page.locator('#out')).toHaveText(/^b/);
});
test('ids', async ({ page }) => {
  await page.goto('/ids');
  await expect(page.locator('#r')).not.toBeEmpty();
  const v = [await page.locator('#sid').textContent(), await page.locator('#when').textContent(), await page.locator('#r').textContent(), Math.random()];
  fs.appendFileSync(process.env.IDS_FILE, JSON.stringify(v) + '\\n');
});
test('runner write vs browser read', async ({ page, request }) => {
  const name = 'n' + Math.floor(Math.random() * 1e6);
  const write = request.post('/api/note', { data: name });
  await page.goto('/api/notes');
  await write;
  expect(await page.locator('body').textContent()).toContain(name);
});
`;

function fixture() {
  fs.rmSync(DIR, { recursive: true, force: true });
  fs.mkdirSync(path.join(DIR, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(DIR, 'package.json'), '{"name":"fixture-pw","private":true}');
  fs.writeFileSync(path.join(DIR, 'app.js'), APP);
  fs.mkdirSync(path.join(DIR, 'node_modules', '.bin'), { recursive: true });
  fs.writeFileSync(path.join(DIR, 'node_modules', '.bin', 'fixture-tool'), '#!/bin/sh\nexit 0\n', { mode: 0o755 });
  fs.writeFileSync(path.join(DIR, 'tests', 'races.spec.js'), SPEC);
  fs.writeFileSync(path.join(DIR, 'playwright.config.js'), `module.exports = {
  testDir: './tests', fullyParallel: true, workers: 2, reporter: 'list',
  use: { baseURL: 'http://localhost:${PORT}', launchOptions: { executablePath: ${JSON.stringify(chromium())} } },
  webServer: { command: 'fixture-tool && node app.js', url: 'http://localhost:${PORT}/api/notes', reuseExistingServer: false },
};\n`);
}

function pw(args, label) {
  const ids = path.join(DIR, `ids-${label}.jsonl`);
  fs.rmSync(ids, { force: true });
  const env = { ...process.env, IDS_FILE: ids, DETJS_PW_EXECUTABLE: chromium() };
  delete env.CI; delete env.DETJS; delete env.NODE_OPTIONS;
  const r = spawnSync(process.execPath, [BIN, 'playwright', 'test', ...args], { cwd: DIR, encoding: 'utf8', env, timeout: 180000 });
  const tracePath = path.join(DIR, '.detjs', 'trace.jsonl');
  let trace = null;
  if (args.includes('--det') && fs.existsSync(tracePath)) {
    const keep = path.join(DIR, `trace-${label}.jsonl`);
    fs.renameSync(tracePath, keep);
    trace = { path: keep, ...readTrace(keep) };
  }
  const idsValue = fs.existsSync(ids) ? fs.readFileSync(ids, 'utf8') : '';
  return { status: r.status, out: r.stdout + r.stderr, trace, ids: idsValue };
}

function verify(paths) {
  const r = spawnSync(process.execPath, [BIN, 'verify', ...paths, '--json'], { encoding: 'utf8' });
  return JSON.parse(r.stdout);
}

const outcome = (run, name) => run.trace.tests.find((t) => t.nodeid.includes(name)).outcome;
const skip = available() || false;

// The webServer command uses a node_modules/.bin tool, as projects do (cross-env): found on uptime-kuma.
test('playwright without --det: server and page randomness differ between runs', { skip, timeout: 240000 }, () => {
  fixture();
  const a = pw([], 'plain-a');
  const b = pw([], 'plain-b');
  assert.ok(a.ids && b.ids, a.out + b.out);
  assert.notEqual(a.ids, b.ids);
});

test('playwright --det: three runs, identical fingerprints and values for every test', { skip, timeout: 360000 }, () => {
  fixture();
  const runs = [1, 2, 3].map((i) => pw(['--det'], `det-${i}`));
  for (const r of runs) assert.ok(r.trace, r.out);
  assert.equal(runs[0].trace.tests.length, 3);
  assert.equal(runs[0].trace.header.meta.level, 'L2-browser');
  assert.equal(runs[0].ids, runs[1].ids);
  assert.equal(runs[0].ids, runs[2].ids);
  const v = verify(runs.map((r) => r.trace.path));
  assert.equal(v.summary.stable, 3, JSON.stringify(v.summary));
  assert.equal(v.summary.outcome_unstable, 0);
  // The fingerprint covers the network order, the server and the page.
  const ev = runs[0].trace.tests.find((t) => t.nodeid.includes('ids')).events.map((e) => e.o);
  for (const o of ['sched.io', 'browser.request', 'server.fingerprint', 'page.random', 'dom.digest']) assert.ok(ev.includes(o), `${o} in ${ev}`);
});

test('playwright --det-seed: a seed replays its outcome, seeds explore both outcomes of the race', { skip, timeout: 600000 }, () => {
  fixture();
  const seen = new Set();
  let replayed = null;
  for (let seed = 1; seed <= 8 && seen.size < 2; seed++) {
    const r = pw(['--det', `--det-seed=${seed}`], `seed-${seed}`);
    assert.ok(r.trace, r.out);
    seen.add(outcome(r, 'race'));
    if (seed === 1) {
      const again = pw(['--det', '--det-seed=1'], 'seed-1-again');
      const v = verify([r.trace.path, again.trace.path]);
      assert.equal(v.summary.stable, 3, JSON.stringify(v.summary));
      replayed = outcome(again, 'race');
      assert.equal(replayed, outcome(r, 'race'));
    }
  }
  assert.deepEqual([...seen].sort(), ['failed', 'passed']);
});

test('playwright --det: a run whose first action is a navigation never deadlocks (6 single-test runs, one fingerprint)', { skip, timeout: 360000 }, () => {
  // Before the fix, about one run in three hung: page.goto issued right after a virtual time
  // grant left the DevTools session suspended while the queue waited for the chunk to end.
  fixture();
  const runs = [1, 2, 3, 4, 5, 6].map((i) => pw(['--det', 'races.spec.js:4', '--timeout=15000'], `single-${i}`));
  if (!runs[0].trace.tests.length) assert.fail(runs[0].out);
  for (const r of runs) assert.ok(r.trace, r.out);
  const v = verify(runs.map((r) => r.trace.path));
  assert.equal(v.summary.tests, 1);
  assert.equal(v.summary.stable, 1, JSON.stringify(v.tests[0].divergence));
});

test('playwright --det: a runner API request and a page.goto issued together are ordered the same way in every run', { skip, timeout: 360000 }, () => {
  // Before the fix the document request reached the queue after a browser round trip, inside
  // or outside the quiet window by chance: two fingerprints in ten runs, and a seed that failed
  // once and passed twice.
  fixture();
  const line = SPEC.split('\n').findIndex((l) => l.includes("test('runner write")) + 1;
  const runs = [1, 2, 3, 4, 5, 6].map((i) => pw(['--det', `races.spec.js:${line}`], `nav-${i}`));
  for (const r of runs) assert.ok(r.trace && r.trace.tests.length === 1, r.out);
  const v = verify(runs.map((r) => r.trace.path));
  assert.equal(v.summary.stable, 1, JSON.stringify(v.tests[0].divergence));
  assert.ok(runs[0].trace.tests[0].events.some((e) => e.o === 'sched.io' && e.v.startsWith('0/2:')), 'both requests pending at the first choice');
});
