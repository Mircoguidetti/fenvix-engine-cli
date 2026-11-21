'use strict';
// Review R-055 (full review of PR #12 @ 688e4fe): channels docs/VERIFY-INPUTS.md misses or gets wrong, on Node.
// Each case runs one project twice under --det, changing only that channel between the runs; the test writes what it
// observed. Every case FAILS on 688e4fe (verify: all tests stable). The invariant: verify says IDENTICAL only if the test observed the same value in both runs.
// Run: cd node && node --test test/review-r055.test.js   (R055_ONLY=name1,name2 runs a subset)
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const native = require('../src/native');
const { fixture, crun, show } = require('./runner-helpers');

const T = { timeout: 600000 };
const W = "import fs from 'node:fs';\nconst _w = (v) => fs.writeFileSync(process.env.ATK_OUT, JSON.stringify(v));\n";
const NT = "import { test } from 'node:test';\n";
const OUT = path.join(os.tmpdir(), `r055-node-${process.pid}`);
fs.mkdirSync(OUT, { recursive: true });
const env2 = (a, b) => (i, dir, env) => Object.assign(env, [a, b][i]);
const outside = (name) => path.join(OUT, name);

// name: [runner, files (may use the outside() paths), before(i, dir, env) | undefined]
const CASES = {
  'volatile TMPDIR through process.env': ['node-test', { 'tests/a.test.mjs': `${NT}${W}test('x', () => _w(process.env.TMPDIR));\n` },
    (i, dir, env) => { const d = outside(`tmp${i}`); fs.mkdirSync(d, { recursive: true }); env.TMPDIR = d; }],
  'proxy variable while the network is closed': ['node-test', { 'tests/a.test.mjs': `${NT}${W}test('x', () => _w(process.env.HTTPS_PROXY));\n` },
    env2({ HTTPS_PROXY: 'http://a:1' }, { HTTPS_PROXY: 'http://b:2' })],
  'file read at module scope': ['node-test', { 'tests/a.test.mjs': `${NT}${W}const V = fs.readFileSync(${JSON.stringify(outside('mod.txt'))}, 'utf8');\ntest('x', () => _w(V));\n` },
    (i) => fs.writeFileSync(outside('mod.txt'), `v${i}`)],
  'project file read at module scope': ['node-test', { 'tests/a.test.mjs': `${NT}${W}const V = fs.readFileSync('data.txt', 'utf8');\ntest('x', () => _w(V));\n` },
    (i, dir) => fs.writeFileSync(path.join(dir, 'data.txt'), `v${i}`)],
  'fs.existsSync': ['node-test', { 'tests/a.test.mjs': `${NT}${W}test('x', () => _w(fs.existsSync(${JSON.stringify(outside('ex.txt'))})));\n` },
    (i) => { if (i === 0) fs.writeFileSync(outside('ex.txt'), 'x'); else fs.rmSync(outside('ex.txt'), { force: true }); }],
  'a dependency in node_modules changes': ['node-test', {
    'tests/a.test.mjs': `${NT}${W}import { V } from 'atkdep';\ntest('x', () => _w(V));\n`,
    'node_modules/atkdep/package.json': JSON.stringify({ name: 'atkdep', main: 'index.js' }),
  }, (i, dir) => fs.writeFileSync(path.join(dir, 'node_modules/atkdep/index.js'), `exports.V = 'v${i}';\n`)],
  'process.loadEnvFile (.env read in C++)': ['node-test', { 'tests/a.test.mjs': `${NT}${W}process.loadEnvFile('.env');\ntest('x', () => _w(process.env.ATK_E));\n` },
    (i, dir) => fs.writeFileSync(path.join(dir, '.env'), `ATK_E=v${i}\n`)],
  'udp to localhost': ['node-test', { 'tests/a.test.mjs': `${NT}${W}import dgram from 'node:dgram';\ntest('x', async () => _w(await new Promise((r) => { const s = dgram.createSocket('udp4'); s.on('message', (m) => { s.close(); r(String(m)); }); s.send('q', Number(process.env.ATK_PORT), '127.0.0.1'); })));\n` }, 'udp'],
};

// a server in its own process
function server(kind, payload, sock) {
  const src = {
    http: `const s = require('node:http').createServer((q, r) => r.end(${JSON.stringify(payload)})); s.listen(0, '127.0.0.1', () => console.log(s.address().port));`,
    udp: `const s = require('node:dgram').createSocket('udp4'); s.on('message', (m, a) => s.send(${JSON.stringify(payload)}, a.port, a.address)); s.bind(0, '127.0.0.1', () => console.log(s.address().port));`,
    unix: `try { require('fs').rmSync(${JSON.stringify(sock)}); } catch {} const s = require('node:net').createServer((c) => c.end(${JSON.stringify(payload)})); s.listen(${JSON.stringify(sock)}, () => console.log(0));`,
  }[kind];
  const cp = require('node:child_process').spawn(process.execPath, ['-e', src], { stdio: ['ignore', 'pipe', 'inherit'] });
  return new Promise((r) => cp.stdout.once('data', (d) => r({ port: Number(String(d).trim()), close: () => cp.kill() })));
}

const ONLY = process.env.R055_ONLY ? process.env.R055_ONLY.split(',') : null;
for (const [name, [runner, files, before]] of Object.entries(CASES)) {
  if (ONLY && !ONLY.includes(name)) continue;
  test(`R-055 ${name}: verify is IDENTICAL only if the test observed the same value`, T, async () => {
    const dir = fixture('r055', name.replace(/[^a-z0-9]+/gi, '-'), files);
    const vals = [];
    const traces = [];
    for (const i of [0, 1]) {
      const out = path.join(dir, `out${i}`);
      const env = { ATK_OUT: out, FENVIX_VOLATILE_ENV: 'ATK_OUT,ATK_FILE,ATK_PORT,ATK_SOCK', TZ: 'UTC' };
      const args = [];
      let srv = null;
      if (typeof before === 'function') before(i, dir, env, args);
      else if (before === 'http' || before === 'udp') { srv = await server(before, `v${i}`); env.ATK_PORT = String(srv.port); }
      else if (before === 'unix') { const s = outside('s.sock'); srv = await server('unix', `v${i}`, s); env.ATK_SOCK = s; }
      const r = await new Promise((res) => setImmediate(() => res(crun(runner, dir, args, { cache: false, env }))));
      if (srv) srv.close();
      assert.ok(fs.existsSync(out), `${name}: no value written\n${show(r)}`);
      vals.push(fs.readFileSync(out, 'utf8'));
      const dst = path.join(dir, `t${i}.jsonl`);
      fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), dst);
      traces.push(dst);
    }
    const rep = JSON.parse(native.verify(traces));
    const identical = rep.summary.tests > 0 && rep.summary.stable === rep.summary.tests && rep.summary.inputs_recorded;
    assert.notEqual(vals[0], vals[1], `${name}: the attack did not change what the test observed (${vals})`);
    assert.ok(!identical, `${name}: IDENTICAL although the test observed ${JSON.stringify(vals)}\n${JSON.stringify(rep.tests)}`);
  });
}
