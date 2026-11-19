'use strict';
// Level 2 browser, round 4: lockstep (runner, pages and app server on one engine clock). Real Chromium (a headless
// shell, for begin-frame control). Run: node --test test/lockstep.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { TMP, BIN, readTrace } = require('./helpers');

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

function project() {
  const dir = path.join(TMP, 'lockstep');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), '{"name":"fixture-lockstep","private":true}');
  fs.copyFileSync(path.join(FX, 'app.js'), path.join(dir, 'app.js'));
  for (const f of ['a.spec.js', 'c.spec.js']) fs.copyFileSync(path.join(FX, f), path.join(dir, 'tests', f));
  fs.writeFileSync(path.join(dir, 'playwright.config.js'), `module.exports = {
  testDir: './tests', workers: 1, reporter: 'list', timeout: 30000,
  use: { baseURL: 'http://localhost:4801', launchOptions: { executablePath: ${JSON.stringify(shell())} } },
  webServer: { command: 'node app.js', url: 'http://localhost:4801/health', reuseExistingServer: false },
};\n`);
  return dir;
}

function run(dir, label, env = {}) {
  const e = { ...process.env, DETJS_PW_EXECUTABLE: shell(), ...env };
  delete e.CI; delete e.DETJS; delete e.NODE_OPTIONS;
  const r = spawnSync(process.execPath, [BIN, 'playwright', '--det', '--det-epoch=2026-01-01T00:00:00Z', 'test'], { cwd: dir, encoding: 'utf8', env: e, timeout: 300000 });
  const keep = path.join(dir, `trace-${label}.jsonl`);
  fs.renameSync(path.join(dir, '.detjs', 'trace.jsonl'), keep);
  return { out: r.stdout + r.stderr, path: keep, ...readTrace(keep) };
}

test('lockstep: a page with background polling, rAF draws, a server timer and a runner API request replays with one fingerprint', { skip, timeout: 1500000 }, () => {
  const dir = project();
  const runs = [1, 2, 3].map((i) => run(dir, `ls${i}`));
  for (const r of runs) assert.deepEqual(r.tests.map((t) => t.outcome), ['passed', 'passed'], r.out);
  const v = JSON.parse(spawnSync(process.execPath, [BIN, 'verify', ...runs.map((r) => r.path), '--json'], { encoding: 'utf8' }).stdout);
  for (const t of v.tests) assert.equal(t.distinct_fingerprints, 1, JSON.stringify(t.divergence));
  // The page clock follows the engine clock (Chromium's own per-fetch virtual time is read back and absorbed).
  const m = /engine (\d+) page (\d+)/.exec(runs[0].out);
  assert.ok(m, runs[0].out);
  assert.ok(Math.abs(Number(m[1]) - Number(m[2])) <= 20, m[0]);
});

test('lockstep off (round 3 engine): the same fixture gives more than one fingerprint', { skip, timeout: 1500000 }, () => {
  const dir = project();
  const runs = [1, 2, 3].map((i) => run(dir, `off${i}`, { DETJS_PW_LOCKSTEP: '0' }));
  const v = JSON.parse(spawnSync(process.execPath, [BIN, 'verify', ...runs.map((r) => r.path), '--json'], { encoding: 'utf8' }).stdout);
  assert.ok(v.tests.some((t) => t.distinct_fingerprints > 1), JSON.stringify(v.tests.map((t) => t.distinct_fingerprints)));
});
