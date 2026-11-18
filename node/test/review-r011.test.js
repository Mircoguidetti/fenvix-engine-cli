'use strict';
// Review R-011 (L2 browser, round 2): defects of the per-source controls that change a test's outcome.
// Each test FAILS on the delivered commit (claude/l2-browser-r2 @ 786181b) and passes once the defect is fixed.
// Needs @playwright/test and a Chromium (as test/l2r2.test.js). Run: node --test test/review-r011.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { TMP, BIN } = require('./helpers');

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

function project(name, { app, spec, port }) {
  const dir = path.join(TMP, 'review-r011', name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), `{"name":"fixture-${name}","private":true}`);
  fs.writeFileSync(path.join(dir, 'app.js'), app);
  fs.writeFileSync(path.join(dir, 'tests', `${name}.spec.js`), spec);
  fs.writeFileSync(path.join(dir, 'playwright.config.js'), `module.exports = {
  testDir: './tests', workers: 1, reporter: 'list', timeout: 30000,
  use: { baseURL: 'http://localhost:${port}', launchOptions: { executablePath: ${JSON.stringify(chromium())} } },
  webServer: { command: 'node app.js', url: 'http://localhost:${port}/health', reuseExistingServer: false },
};\n`);
  return dir;
}

/** Exit status of `detjs playwright test` (0 = every test passed), plain or with --det. */
function run(dir, args) {
  const env = { ...process.env, DETJS_PW_EXECUTABLE: chromium() };
  delete env.CI; delete env.DETJS; delete env.NODE_OPTIONS;
  const r = spawnSync(process.execPath, [BIN, 'playwright', 'test', ...args], { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  return { passed: r.status === 0, out: `${r.stdout}${r.stderr}` };
}

// ---------------------------------------------------------------------------------------------
// R1. The test code's clock advances 1 ms per read (worker.js installWorkerSeeds), not with the time the test
// waits: an elapsed-time budget asserted by the test (a request within 1 s, a page within 3 s) can no longer fail.
// A test that fails without detjs passes under --det, and no harness counter sees it (broken_by_controls counts
// pass -> fail only).
const SLOW_PORT = 4691;
const SLOW_APP = `
const http = require('http');
http.createServer((req, res) => {
  if (req.url === '/health') return res.end('ok');
  // 1.5 s of real work (blocks the thread: no timer the controls could shorten)
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 1500);
  res.end('slow');
}).listen(${SLOW_PORT});
`;
const SLOW_SPEC = `
const { test, expect } = require('@playwright/test');
test('the report endpoint answers within its 1 s budget', async ({ request }) => {
  const t0 = Date.now();
  const r = await request.get('/report');
  expect(r.status()).toBe(200);
  const elapsed = Date.now() - t0;
  console.log('ELAPSED_MS=' + elapsed);
  expect(elapsed).toBeLessThan(1000);
});
`;

test('R1: an elapsed-time budget that fails without detjs also fails under --det (the test-code clock must not hide it)', { skip, timeout: 600000 }, () => {
  const dir = project('slow', { app: SLOW_APP, spec: SLOW_SPEC, port: SLOW_PORT });
  const plain = run(dir, []);
  assert.equal(plain.passed, false, `precondition: the 1.5 s endpoint misses the 1 s budget without detjs\n${plain.out}`);
  const det = run(dir, ['--det']);
  const seen = (det.out.match(/ELAPSED_MS=\d+/) || ['?'])[0];
  assert.equal(det.passed, plain.passed, `--det changed the outcome from failed to passed (${seen} under --det)\n${det.out.slice(-1500)}`);
});

// ---------------------------------------------------------------------------------------------
// R2. The test code's clock starts at epoch + (hash of the test id mod 2^31) ms (round 2 fix 697c9729), while the
// app server's and the page's clocks start at the epoch: test code and app disagree on "now" by up to 24.8 days.
// Any test that builds a time in test code and lets the server compare it with its own clock (expiry, "created
// before", scheduling) changes outcome. The report gives this as the ESTIMATED cause of documenso's 3 broken
// "expired" tests; here it is shown directly.
const NOW_PORT = 4692;
const NOW_APP = `
const http = require('http');
http.createServer((req, res) => {
  if (req.url === '/health') return res.end('ok');
  res.end(String(Date.now()));
}).listen(${NOW_PORT});
`;
const NOW_SPEC = `
const { test, expect } = require('@playwright/test');
test('server and test agree on the current time within one hour', async ({ request }) => {
  const server = Number(await (await request.get('/now')).text());
  const mine = Date.now();
  console.log('SKEW_MS=' + (mine - server));
  expect(Math.abs(mine - server)).toBeLessThan(60 * 60 * 1000);
});
`;

test('R2: test code and app server share one notion of "now" under --det (skew under one hour)', { skip, timeout: 600000 }, () => {
  const dir = project('now', { app: NOW_APP, spec: NOW_SPEC, port: NOW_PORT });
  const plain = run(dir, []);
  assert.equal(plain.passed, true, `precondition: passes without detjs\n${plain.out}`);
  const det = run(dir, ['--det']);
  const seen = (det.out.match(/SKEW_MS=-?\d+/) || ['?'])[0];
  assert.equal(det.passed, true, `--det broke a passing test: test clock vs server clock ${seen}\n${det.out.slice(-1500)}`);
});
