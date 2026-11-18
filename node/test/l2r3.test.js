'use strict';
// Level 2 browser, round 3 (review R-011 fixes and the cheap experiments E2/E6). Fixture apps, real Chromium.
// Needs @playwright/test and a Chromium (as test/l2r2.test.js). Run: node --test test/l2r3.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { TMP, BIN, readTrace } = require('./helpers');

function chromium() {
  if (process.env.DETJS_PW_EXECUTABLE) return process.env.DETJS_PW_EXECUTABLE;
  for (const p of ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser']) if (fs.existsSync(p)) return p;
  try {
    const p = require('playwright-core').chromium.executablePath();
    if (p && fs.existsSync(p)) return p;
  } catch { /* not installed */ }
  return null;
}
const skip = chromium() ? false : 'no Chromium (set DETJS_PW_EXECUTABLE)';

/** A fixture project. `config` replaces the default config body (between the braces). */
function project(name, { app, specs, port, config }) {
  const dir = path.join(TMP, 'l2r3', name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), `{"name":"fixture-${name}","private":true}`);
  fs.writeFileSync(path.join(dir, 'app.js'), app);
  for (const [f, body] of Object.entries(specs)) fs.writeFileSync(path.join(dir, 'tests', f), body);
  fs.writeFileSync(path.join(dir, 'playwright.config.js'), `module.exports = {
  testDir: './tests', workers: 1, reporter: 'list', timeout: 30000,
  use: { baseURL: 'http://localhost:${port}', launchOptions: { executablePath: ${JSON.stringify(chromium())} } },
  webServer: { command: 'node app.js', url: 'http://localhost:${port}/health', reuseExistingServer: false },
  ${config || ''}
};\n`);
  return dir;
}

/** `detjs playwright <args>` (args as given, no implicit `test`). */
function pw(dir, args, label, extraEnv = {}) {
  const env = { ...process.env, DETJS_PW_EXECUTABLE: chromium(), ...extraEnv };
  delete env.CI; delete env.DETJS; delete env.NODE_OPTIONS;
  const r = spawnSync(process.execPath, [BIN, 'playwright', ...args], { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  const tracePath = path.join(dir, '.detjs', 'trace.jsonl');
  let trace = null;
  if (fs.existsSync(tracePath)) {
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
const outcomes = (run) => (run.trace ? run.trace.tests.map((t) => t.outcome) : []);

// ---------------------------------------------------------------------------------------------
// H3 (review R-011). actual runs `playwright test --browser=chromium` with a config without projects: Playwright
// makes a project named "chromium". The printed replay command kept `--project=chromium` and dropped
// `--browser=chromium`, so it matched no project and ran no test (outcome "missing" in run 44284824592).
const BR_PORT = 4701;
const BR_APP = `
const http = require('http');
http.createServer((req, res) => res.end(req.url === '/health' ? 'ok' : 'hello')).listen(${BR_PORT});
`;
const BR_SPEC = `
const { test, expect } = require('@playwright/test');
test('fails on purpose', async ({ request }) => {
  expect(await (await request.get('/')).text()).toBe('something else');
});
`;
test('H3: the printed replay command runs its test when the run used --browser (config without projects)', { skip, timeout: 600000 }, () => {
  const dir = project('browser', { app: BR_APP, port: BR_PORT, specs: { 'br.spec.js': BR_SPEC } });
  const first = pw(dir, ['--det', 'test', '--browser=chromium'], 'br-first');
  assert.deepEqual(outcomes(first), ['failed'], first.out);
  const m = /detjs: replay [^\n]*:\n {2}npx detjs playwright ([^\n]*)/.exec(first.out);
  assert.ok(m, `no replay command printed\n${first.out}`);
  const args = m[1].split(' ').map((a) => a.replace(/^'(.*)'$/, '$1'));
  const replay = pw(dir, args, 'br-replay');
  assert.deepEqual(outcomes(replay), ['failed'], `the printed command (${m[1]}) did not run its test\n${replay.out.slice(-1500)}`);
});

// ---------------------------------------------------------------------------------------------
// E6 (review R-011): can the seed space reproduce a load-induced failure? The page asks the server for data and
// the test expects it within 2 s; the server answers at once. On a loaded CI machine the answer can come late:
// the flake. Round 2's latency choices (max 25 chunks = 500 ms) never reach the deadline: no seed of 1-8 fails.
// With a choice past the deadline (`D`), some seed of 1-8 fails and its replays fail with one fingerprint.
const DL_PORT = 4702;
const DL_APP = `
const http = require('http');
http.createServer((req, res) => {
  if (req.url === '/health') return res.end('ok');
  if (req.url.startsWith('/api/data')) { res.setHeader('content-type', 'application/json'); return res.end('{"v":"loaded"}'); }
  res.setHeader('content-type', 'text/html');
  res.end('<!doctype html><div id=out>wait</div><script>' +
    'const get = (u) => fetch(u).then((r) => r.json());' +
    'get("/api/data?a").then(() => get("/api/data?b")).then(() => get("/api/data")).then((j) => { out.textContent = j.v; });</script>');
}).listen(${DL_PORT});
`;
const DL_SPEC = `
const { test, expect } = require('@playwright/test');
test('data arrives within its deadline', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#out')).toHaveText('loaded', { timeout: 2000 });
});
`;
test('E6: a seed space reaching the deadline reproduces a slow-response failure with one fingerprint (round 2 list: no seed fails)', { skip, timeout: 900000 }, () => {
  const dir = project('deadline', { app: DL_APP, port: DL_PORT, specs: { 'dl.spec.js': DL_SPEC } });
  const env = { DETJS_PW_DEADLINE_MS: '2000' };
  const seeds = [1, 2, 3, 4, 5, 6, 7, 8];
  const old = seeds.map((sd) => outcomes(pw(dir, ['--det', `--det-seed=${sd}`, 'test'], `old-${sd}`, env))[0]);
  assert.deepEqual(old, seeds.map(() => 'passed'), `round 2 latency list: ${old}`);
  const wide = seeds.map((sd) => outcomes(pw(dir, ['--det', `--det-seed=${sd}`, '--det-latency=0,0,1,5,25,D', 'test'], `wide-${sd}`, env))[0]);
  const failing = seeds.filter((sd, i) => wide[i] === 'failed' || wide[i] === 'timedOut');
  assert.ok(failing.length >= 1, `no seed of 1-8 reaches the deadline: ${wide}`);
  assert.ok(failing.length < seeds.length, `every seed fails (the choice is not exploration): ${wide}`);
  const sd = failing[0];
  const reps = [1, 2, 3].map((i) => pw(dir, ['--det', `--det-seed=${sd}`, '--det-latency=0,0,1,5,25,D', 'test'], `rep-${sd}-${i}`, env));
  for (const r of reps) assert.deepEqual(outcomes(r), ['failed'], r.out.slice(-1200));
  const v = verify(reps.map((r) => r.trace.path));
  assert.equal(v.summary.stable, 1, JSON.stringify(v.tests[0].divergence));
});

// ---------------------------------------------------------------------------------------------
// E2 (review R-011): freeze-before-observe, the switch measured on actual's targets in Actions. Here only its
// mechanics: at the end of the test function the page stops receiving virtual time and the final DOM is taken
// at once (event `observe frozen`), the run does not stall, and later page activity is not observed. What the
// fixture also shows (logged, not asserted): a page that keeps ticking while the runner polls in real time still
// gives a real-time-dependent final DOM, frozen or not: that part is class A (when the runner acts).
const FZ_PORT = 4703;
const FZ_APP = `
const http = require('http');
http.createServer((req, res) => {
  if (req.url === '/health') return res.end('ok');
  res.setHeader('content-type', 'text/html');
  res.end('<!doctype html><button id=b>go</button><div id=n>0</div><script>' +
    'let n = 0; b.onclick = () => { setInterval(() => { n++; document.getElementById("n").textContent = String(n); }, 7); };</script>');
}).listen(${FZ_PORT});
`;
const FZ_SPEC = `
const { test, expect } = require('@playwright/test');
test('starts a ticking counter', async ({ page }) => {
  await page.goto('/');
  await page.click('#b');
  await expect(page.locator('#n')).not.toHaveText('0');
});
`;
test('E2: freeze-before-observe takes the final state at the end of the test function and does not stall (3 runs)', { skip, timeout: 900000 }, () => {
  const dir = project('freeze', { app: FZ_APP, port: FZ_PORT, specs: { 'fz.spec.js': FZ_SPEC } });
  const runs = [1, 2, 3].map((i) => pw(dir, ['--det', '--det-freeze=on', 'test'], `fz-${i}`));
  for (const r of runs) assert.deepEqual(outcomes(r), ['passed'], r.out.slice(-1200));
  for (const r of runs) assert.match(fs.readFileSync(r.trace.path, 'utf8'), /"observe","at":"[^"]*","v":"frozen"|observe[^\n]*frozen/, 'no frozen observation');
  const v = verify(runs.map((r) => r.trace.path));
  console.log(`E2 fixture (page ticking during real-time polling): ${v.tests[0].distinct_fingerprints} fingerprints in 3 runs`);
});
