'use strict';
// Playwright cache with proof (Level 2, src/pw/cache.js): the selection of a project is reused when every input of
// its recorded run is unchanged (files read and modules loaded by the runner, its workers and the app server; the
// start state; the environment), and run again when the app changed. A run that talks to a server the run did not
// start under detjs is never recorded. Real Chromium (headless shell). Run: node --test test/pw-cache.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync, spawn } = require('node:child_process');
const { TMP, BIN } = require('./helpers');

function shell() {
  if (process.env.DETJS_PW_EXECUTABLE) return process.env.DETJS_PW_EXECUTABLE;
  try {
    const p = require('playwright-core').chromium.executablePath().replace(/chromium-(\d+)\/chrome-linux64\/chrome$/, 'chromium_headless_shell-$1/chrome-headless-shell-linux64/chrome-headless-shell');
    if (fs.existsSync(p)) return p;
  } catch { /* not installed */ }
  return null;
}
const skip = shell() ? false : 'no chromium headless shell (set DETJS_PW_EXECUTABLE)';
const FX = path.join(__dirname, 'fixtures-lockstep');

function project(name, { webServer = true, port = 4811 } = {}) {
  const dir = path.join(TMP, 'pw-cache', name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), '{"name":"fixture-pw-cache","private":true}');
  fs.writeFileSync(path.join(dir, 'app.js'), fs.readFileSync(path.join(FX, 'app.js'), 'utf8').replace('listen(4801)', `listen(${port})`));
  fs.copyFileSync(path.join(FX, 'a.spec.js'), path.join(dir, 'tests', 'a.spec.js'));
  fs.writeFileSync(path.join(dir, 'playwright.config.js'), `module.exports = {
  testDir: './tests', workers: 1, reporter: 'list', timeout: 30000,
  use: { baseURL: 'http://localhost:${port}', launchOptions: { executablePath: ${JSON.stringify(shell())} } },
  ${webServer ? `webServer: { command: 'node app.js', url: 'http://localhost:${port}/health', reuseExistingServer: false },` : ''}
};\n`);
  return dir;
}

function run(dir, extra = []) {
  const e = { ...process.env, DETJS_PW_EXECUTABLE: shell() };
  delete e.CI; delete e.DETJS; delete e.NODE_OPTIONS;
  const r = spawnSync(process.execPath, [BIN, 'playwright', '--det', '--det-epoch=2026-01-01T00:00:00Z', '--det-cache=cache', ...extra, 'test'],
    { cwd: dir, encoding: 'utf8', env: e, timeout: 300000 });
  const summary = JSON.parse(fs.readFileSync(path.join(dir, '.detjs', 'cache-summary.json'), 'utf8'));
  return { status: r.status, out: r.stdout + r.stderr, summary };
}

test('an unchanged rerun is reused with proof; an edit of the app server reruns the tests; outcomes equal', { skip, timeout: 900000 }, () => {
  const dir = project('app');
  const r1 = run(dir);
  assert.equal(r1.status, 0, r1.out);
  assert.equal(r1.summary.recorded, true, r1.out);
  assert.equal(r1.summary.ran, 1);
  assert.ok(r1.summary.inputs.processes.server >= 1, JSON.stringify(r1.summary.inputs));
  const r2 = run(dir);
  assert.equal(r2.status, 0, r2.out);
  assert.equal(r2.summary.reused, 1, r2.out);
  assert.equal(r2.summary.ran, 0);
  assert.deepEqual(r2.summary.outcomes, r1.summary.outcomes);
  assert.match(r2.out, /selection reused with proof/);
  // the app changes (a page text the test checks): run again, and the new outcome is the real one
  fs.writeFileSync(path.join(dir, 'app.js'), fs.readFileSync(path.join(dir, 'app.js'), 'utf8').replace("'done ' + t", "'gone ' + t"));
  const r3 = run(dir);
  assert.equal(r3.summary.reused, 0, r3.out);
  assert.match(r3.summary.miss, /input changed: app\.js/);
  assert.equal(r3.summary.outcomes['tests/a.spec.js::lockstep fixture'], 'failed', r3.out);
  assert.equal(r3.status, 1);
  // the failing result is recorded too, and reused while the app stays as it is
  const r4 = run(dir);
  assert.equal(r4.summary.reused, 1, r4.out);
  assert.equal(r4.status, 1);
  assert.deepEqual(r4.summary.outcomes, r3.summary.outcomes);
});

test('a server the run did not start under detjs: the run is not recorded (its inputs are not seen)', { skip, timeout: 900000 }, async () => {
  const dir = project('external', { webServer: false, port: 4812 });
  const env = { ...process.env };
  delete env.NODE_OPTIONS; delete env.DETJS;
  const srv = spawn(process.execPath, ['app.js'], { cwd: dir, env, stdio: 'ignore' });
  try {
    await new Promise((r) => setTimeout(r, 800));
    const r1 = run(dir);
    assert.equal(r1.summary.recorded, false, r1.out);
    assert.ok(r1.summary.not_cacheable.some((w) => /connection to .*4812/.test(w)), JSON.stringify(r1.summary.not_cacheable));
    const r2 = run(dir);
    assert.equal(r2.summary.reused, 0, r2.out);
  } finally { srv.kill(); }
});
