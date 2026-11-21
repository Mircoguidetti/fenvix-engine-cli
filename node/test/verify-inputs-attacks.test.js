'use strict';
// Attacks on the verifier, one per channel a Node test can read its environment or inputs through
// (docs/VERIFY-INPUTS.md). Each case runs one project twice under --det, changing only that channel between the
// runs; the test writes what it observed. The invariant: `verify` says IDENTICAL only if the test observed the same
// value in both runs. For a channel --det does not control ("raw"), the attack must also show the change.
// Run: cd node && node --test test/verify-inputs-attacks.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const native = require('../src/native');
const { fixture, crun, show } = require('./runner-helpers');

const T = { timeout: 600000 };
const W = "import fs from 'node:fs';\nconst _w = (v) => fs.writeFileSync(process.env.ATK_OUT, JSON.stringify(v));\n";
const NT = "import { test, before } from 'node:test';\n";
const VT = "import { test, beforeAll, beforeEach } from 'vitest';\n";
const V12 = [{ ATK_V: '1' }, { ATK_V: '2' }];

// name: [runner, files, kind, change: two env objects | 'file' | 'sleep' | 'server' | 'taskset' | 'tz']
const CASES = {
  'body process.env': ['node-test', { 'tests/a.test.mjs': `${NT}${W}test('x', () => _w(process.env.ATK_V));\n` }, 'raw', V12],
  'body enumeration': ['node-test', { 'tests/a.test.mjs': `${NT}${W}test('x', () => _w({ ...process.env }.ATK_V));\n` }, 'raw', V12],
  'body Object.entries': ['node-test', { 'tests/a.test.mjs': `${NT}${W}test('x', () => _w(Object.entries(process.env).find(([k]) => k === 'ATK_V')));\n` }, 'raw', V12],
  'module scope': ['node-test', { 'tests/a.test.mjs': `${NT}${W}const V = process.env.ATK_V;\ntest('x', () => _w(V));\n` }, 'raw', V12],
  'before hook': ['node-test', { 'tests/a.test.mjs': `${NT}${W}let V;\nbefore(() => { V = process.env.ATK_V; });\ntest('x', () => _w(V));\n` }, 'raw', V12],
  'vitest beforeAll': ['vitest', { 'tests/a.test.mjs': `${VT}${W}let V;\nbeforeAll(() => { V = process.env.ATK_V; });\ntest('x', () => _w(V));\n` }, 'raw', V12],
  'vitest beforeEach': ['vitest', { 'tests/a.test.mjs': `${VT}${W}let V;\nbeforeEach(() => { V = process.env.ATK_V; });\ntest('x', () => _w(V));\n` }, 'raw', V12],
  'vitest setupFiles': ['vitest', {
    'tests/a.test.mjs': `${VT}${W}test('x', () => _w(globalThis.__atk));\n`,
    'tests/setup.mjs': 'globalThis.__atk = process.env.ATK_V;\n',
    'vitest.config.mjs': "export default { test: { include: ['tests/**/*.test.mjs'], setupFiles: ['tests/setup.mjs'] } };\n",
  }, 'raw', V12],
  'vitest config file': ['vitest', {
    'tests/a.test.mjs': `${VT}${W}test('x', () => _w(globalThis.__cfg));\n`,
    'vitest.config.mjs': "export default { test: { include: ['tests/**/*.test.mjs'], globals: false, define: {}, provide: {}, env: { ATK_CFG: String(process.env.ATK_V) } } };\n",
  }, 'raw', V12, (files) => { files['tests/a.test.mjs'] = `${VT}${W}test('x', () => _w(process.env.ATK_CFG));\n`; }],
  'dependency at import': ['node-test', {
    'tests/a.test.mjs': `${NT}${W}import { V } from 'atklib';\ntest('x', () => _w(V));\n`,
    'node_modules/atklib/package.json': JSON.stringify({ name: 'atklib', main: 'index.js' }),
    'node_modules/atklib/index.js': 'exports.V = process.env.ATK_V;\n',
  }, 'raw', V12],
  'dependency imported in the test': ['node-test', {
    'tests/a.test.mjs': `${NT}${W}test('x', async () => _w((await import('atklib2')).V));\n`,
    'node_modules/atklib2/package.json': JSON.stringify({ name: 'atklib2', main: 'index.js' }),
    'node_modules/atklib2/index.js': 'exports.V = process.env.ATK_V;\n',
  }, 'raw', V12],
  'child process': ['node-test', { 'tests/a.test.mjs': `${NT}${W}import { execFileSync } from 'node:child_process';\ntest('x', () => _w(execFileSync('sh', ['-c', 'echo $ATK_V']).toString()));\n` }, 'raw', V12],
  'worker thread': ['node-test', { 'tests/a.test.mjs': `${NT}${W}import { Worker } from 'node:worker_threads';\ntest('x', async () => { const v = await new Promise((r) => { const w = new Worker('require("node:worker_threads").parentPort.postMessage(process.env.ATK_V)', { eval: true }); w.on('message', r); }); _w(v); });\n` }, 'raw', V12],
  'file outside the project': ['node-test', { 'tests/a.test.mjs': `${NT}${W}test('x', () => _w(fs.readFileSync(process.env.ATK_FILE, 'utf8')));\n` }, 'raw', 'file'],
  'file in the project': ['node-test', { 'tests/a.test.mjs': `${NT}${W}import path from 'node:path';\ntest('x', () => _w(fs.readFileSync(path.join(process.cwd(), 'data.txt'), 'utf8')));\n` }, 'raw', 'file-inside'],
  'network localhost': ['node-test', { 'tests/a.test.mjs': `${NT}${W}import net from 'node:net';\ntest('x', async () => { const v = await new Promise((r) => { const s = net.connect(Number(process.env.ATK_PORT), '127.0.0.1'); let d = ''; s.on('data', (x) => { d += x; }); s.on('end', () => r(d)); }); _w(v); });\n` }, 'raw', 'server'],
  'entropy (crypto.randomBytes)': ['node-test', { 'tests/a.test.mjs': `${NT}${W}import crypto from 'node:crypto';\ntest('x', () => _w(crypto.randomBytes(8).toString('hex')));\n` }, 'any', [{}, {}]],
  // controlled by --det: the value the test sees does not change
  'time': ['node-test', { 'tests/a.test.mjs': `${NT}${W}test('x', () => _w(Date.now()));\n` }, 'controlled', 'sleep'],
  'Math.random': ['node-test', { 'tests/a.test.mjs': `${NT}${W}test('x', () => _w(Math.random()));\n` }, 'controlled', [{}, {}]],
  'hostname': ['node-test', { 'tests/a.test.mjs': `${NT}${W}import os from 'node:os';\ntest('x', () => _w(os.hostname()));\n` }, 'controlled', [{}, {}]],
  'cpu count': ['node-test', { 'tests/a.test.mjs': `${NT}${W}import os from 'node:os';\ntest('x', () => _w([os.cpus().length, os.availableParallelism()]));\n` }, 'controlled', 'taskset'],
  'time zone': ['node-test', { 'tests/a.test.mjs': `${NT}${W}test('x', () => _w(new Date(0).toString()));\n` }, 'controlled', [{ TZ: 'UTC' }, { TZ: 'Asia/Tokyo' }]],
  // review R-055 (docs/VERIFY-CONTRACT.md); review-r055.test.js has the reviewer's cases, these are other ways in
  // V1: a CI-volatile variable kept as it is (not pinned): the test is NOT PROVEN
  'volatile GITHUB_WORKSPACE': ['node-test', { 'tests/a.test.mjs': `${NT}${W}test('x', () => _w(process.env.GITHUB_WORKSPACE));\n` }, 'raw', [{ GITHUB_WORKSPACE: '/a' }, { GITHUB_WORKSPACE: '/b' }]],
  // V2: a lower-case proxy variable at module scope while the network is closed: every test NOT PROVEN
  'proxy http_proxy at module scope': ['node-test', { 'tests/a.test.mjs': `${NT}${W}const V = process.env.http_proxy;\ntest('x', () => _w(V));\n` }, 'raw', [{ http_proxy: 'http://a:1' }, { http_proxy: 'http://b:2' }]],
  // V3: a file read in a before hook (no test runs): files_read_outside_tests
  'file read in a before hook': ['node-test', { 'tests/a.test.mjs': `${NT}${W}let V;\nbefore(async () => { V = await fs.promises.readFile(process.env.ATK_FILE, 'utf8'); });\ntest('x', () => _w(V));\n` }, 'raw', 'file'],
  // V5: a CommonJS dependency's nested file changes (required, not imported)
  'dependency nested file (require)': ['node-test', {
    'tests/a.test.cjs': "const { test } = require('node:test');\nconst fs = require('node:fs');\nconst { V } = require('atkdep');\ntest('x', () => fs.writeFileSync(process.env.ATK_OUT, JSON.stringify(V)));\n",
    'node_modules/atkdep/package.json': JSON.stringify({ name: 'atkdep', main: 'index.js' }),
    'node_modules/atkdep/index.js': "exports.V = require('./lib/v.js');\n",
  }, 'raw', 'dep'],
  // V6: existence through fs.promises.access
  'fs.promises.access': ['node-test', { 'tests/a.test.mjs': `${NT}${W}test('x', async () => _w(await fs.promises.access(process.env.ATK_FILE).then(() => true, () => false)));\n` }, 'raw', 'exists'],
  // V8: UDP through a connected socket
  'udp connected socket': ['node-test', { 'tests/a.test.mjs': `${NT}${W}import dgram from 'node:dgram';\ntest('x', async () => _w(await new Promise((r) => { const s = dgram.createSocket('udp4'); s.on('message', (m) => { s.close(); r(String(m)); }); s.connect(Number(process.env.ATK_PORT), '127.0.0.1', () => s.send('q')); })));\n` }, 'raw', 'udp'],
  // V16: process.loadEnvFile inside the test
  'process.loadEnvFile in the test': ['node-test', { 'tests/a.test.mjs': `${NT}${W}test('x', () => { process.loadEnvFile('cfg.env'); _w(process.env.ATK_E); });\n` }, 'raw', 'dotenv'],
};

// a server in its own process (the runs are spawned synchronously: one in this process would never answer)
function udpServer(payload) {
  const cp = require('node:child_process').spawn(process.execPath, ['-e',
    `const s = require('node:dgram').createSocket('udp4'); s.on('message', (m, a) => s.send(${JSON.stringify(payload)}, a.port, a.address)); s.bind(0, '127.0.0.1', () => console.log(s.address().port));`],
  { stdio: ['ignore', 'pipe', 'inherit'] });
  return new Promise((r) => cp.stdout.once('data', (d) => r({ port: Number(String(d).trim()), close: () => cp.kill() })));
}

function server(payload) {
  const cp = require('node:child_process').spawn(process.execPath, ['-e',
    `const s = require('node:net').createServer((c) => c.end(${JSON.stringify(payload)})); s.listen(0, '127.0.0.1', () => console.log(s.address().port));`],
  { stdio: ['ignore', 'pipe', 'inherit'] });
  return new Promise((r) => cp.stdout.once('data', (d) => r({ port: Number(String(d).trim()), close: () => cp.kill() })));
}

for (const [name, [runner, files0, kind, change, adjust]] of Object.entries(CASES)) {
  test(`${name}: verify is IDENTICAL only if the test observed the same value`, T, async () => {
    const files = { ...files0 };
    if (adjust) adjust(files);
    if (runner === 'vitest' && !files['vitest.config.mjs']) files['vitest.config.mjs'] = "export default { test: { include: ['tests/**/*.test.mjs'] } };\n";
    const dir = fixture('atk', name.replace(/[^a-z0-9]+/gi, '-'), files);
    const vals = [];
    const traces = [];
    for (const i of [0, 1]) {
      const out = path.join(dir, `out${i}`);
      const env = { ATK_OUT: out, FENVIX_VOLATILE_ENV: 'ATK_OUT,ATK_FILE,ATK_PORT', TZ: 'UTC' };
      let srv = null;
      let prefixTaskset = false;
      if (Array.isArray(change)) Object.assign(env, change[i]);
      else if (change === 'file') { const f = path.join(os.tmpdir(), `atk-outside-${process.pid}.txt`); fs.writeFileSync(f, `v${i}`); env.ATK_FILE = f; }
      else if (change === 'file-inside') fs.writeFileSync(path.join(dir, 'data.txt'), `v${i}`);
      else if (change === 'sleep' && i === 1) await new Promise((r) => setTimeout(r, 1100));
      else if (change === 'server') { srv = await server(`v${i}`); env.ATK_PORT = String(srv.port); }
      else if (change === 'udp') { srv = await udpServer(`v${i}`); env.ATK_PORT = String(srv.port); }
      else if (change === 'dep') { fs.mkdirSync(path.join(dir, 'node_modules/atkdep/lib'), { recursive: true }); fs.writeFileSync(path.join(dir, 'node_modules/atkdep/lib/v.js'), `module.exports = 'v${i}';\n`); }
      else if (change === 'exists') { const f = path.join(os.tmpdir(), `atk-exists-${process.pid}.txt`); if (i === 0) fs.writeFileSync(f, 'x'); else fs.rmSync(f, { force: true }); env.ATK_FILE = f; }
      else if (change === 'dotenv') fs.writeFileSync(path.join(dir, 'cfg.env'), `ATK_E=v${i}\n`);
      else if (change === 'taskset' && i === 1) prefixTaskset = true;
      if (prefixTaskset && (!fs.existsSync('/usr/bin/taskset') || os.availableParallelism() < 2)) return;
      const r = prefixTaskset
        ? require('node:child_process').spawnSync('taskset', ['-c', '0', process.execPath, path.join(__dirname, '..', 'bin', 'detjs.js'), runner, '--det', ...(runner === 'vitest' ? ['run'] : [])],
          { cwd: dir, encoding: 'utf8', env: { ...process.env, ...env }, timeout: 240000 })
        : await new Promise((res) => setImmediate(() => res(crun(runner, dir, runner === 'vitest' ? ['run'] : [], { cache: false, env }))));
      if (srv) srv.close();
      assert.ok(fs.existsSync(out), `${name}: no value written\n${show(r)}`);
      vals.push(fs.readFileSync(out, 'utf8'));
      const dst = path.join(dir, `t${i}.jsonl`);
      fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), dst);
      traces.push(dst);
    }
    const rep = JSON.parse(native.verify(traces));
    const identical = rep.summary.tests > 0 && rep.summary.stable === rep.summary.tests && rep.summary.inputs_recorded;
    if (kind === 'raw') assert.notEqual(vals[0], vals[1], `${name}: the attack did not change what the test observed`);
    if (kind === 'controlled') assert.equal(vals[0], vals[1], `${name}: not controlled`);
    assert.ok(!(identical && vals[0] !== vals[1]), `${name}: IDENTICAL although the test observed ${JSON.stringify(vals)}\n${JSON.stringify(rep.tests)}`);
  });
}
