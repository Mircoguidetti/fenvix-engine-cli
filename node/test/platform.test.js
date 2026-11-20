'use strict';
// F-09 / JS-01 (audit G-0240, G-0442..G-0446): the engine's native core exists for Linux x86_64 with glibc 2.28+;
// every other platform gets one sentence naming the supported one, never a raw loader error; the `fenvix` command
// answers --version and --help and names an unknown runner (G-2173..G-2176).
const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { platformTriple } = require('../src/platform');

const report = (glibc) => ({ getReport: () => ({ header: glibc ? { glibcVersionRuntime: glibc } : {} }) });

test('supported: Linux x64 with glibc 2.28 and newer', () => {
  assert.deepStrictEqual(platformTriple({ platform: 'linux', arch: 'x64', report: report('2.28') }), { triple: 'linux-x64-gnu' });
  assert.deepStrictEqual(platformTriple({ platform: 'linux', arch: 'x64', report: report('2.39') }), { triple: 'linux-x64-gnu' });
});

test('refused with a reason: musl, old glibc, arm64, macOS, Windows', () => {
  const cases = [
    [{ platform: 'linux', arch: 'x64', report: report(undefined) }, /musl/],
    [{ platform: 'linux', arch: 'x64', report: report('2.26') }, /glibc 2\.26 is older than 2\.28/],
    [{ platform: 'linux', arch: 'arm64', report: report('2.39') }, /arm64 is not supported/],
    [{ platform: 'darwin', arch: 'arm64', report: report(undefined) }, /macOS is not supported/],
    [{ platform: 'win32', arch: 'x64', report: report(undefined) }, /win32 is not supported/],
  ];
  for (const [proc, re] of cases) assert.match(platformTriple(proc).problem, re);
});

const bin = path.join(__dirname, '..', 'bin', 'fenvix.js');
const run = (...a) => spawnSync(process.execPath, [bin, ...a], { encoding: 'utf8' });

test('fenvix --version and --help exit 0; an unknown runner is named', () => {
  const v = run('--version');
  assert.strictEqual(v.status, 0);
  assert.strictEqual(v.stdout.trim(), `fenvix ${require('../package.json').version}`);
  const h = run('--help');
  assert.strictEqual(h.status, 0);
  assert.match(h.stdout, /usage:/);
  const u = run('tape');
  assert.strictEqual(u.status, 2);
  assert.match(u.stderr, /unknown runner or command 'tape'; supported runners: vitest, jest/);
});

test('a user error of the shell is printed without a JavaScript stack', () => {
  const r = run('jest', '--det', '--det-seed=abc');
  assert.notStrictEqual(r.status, 0);
  assert.match(r.stderr, /detjs: /);
  assert.doesNotMatch(r.stderr, /\n\s+at /);
});

test('a --det run leaves the checkout clean: .detjs carries a .gitignore (G-2177)', () => {
  const fs = require('node:fs');
  const os = require('node:os');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'detjs-gi-'));
  fs.writeFileSync(path.join(dir, 'a.test.js'), "require('node:test')('a', () => {});\n");
  spawnSync('git', ['init', '-q', dir]);
  spawnSync('git', ['-C', dir, 'add', '-A']);
  const r = spawnSync(process.execPath, [bin, 'node-test', '--det', 'a.test.js'], { cwd: dir, encoding: 'utf8' });
  assert.strictEqual(r.status, 0, r.stdout + r.stderr);
  assert.ok(fs.existsSync(path.join(dir, '.detjs', '.gitignore')));
  const st = spawnSync('git', ['-C', dir, 'status', '--porcelain'], { encoding: 'utf8' }).stdout;
  assert.doesNotMatch(st, /\.detjs/, st);
  fs.rmSync(dir, { recursive: true, force: true });
});
