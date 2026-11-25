'use strict';
// Cache measurement B, B1 fix 1: the shared cache's push sent entries whose data and environment were chunk-group
// addresses (the on-disk store format of py-cache item 4, ca7b647f), so no other machine could use them: every pull
// with candidates failed ("pull: observed: invalid type: string \"g...\", expected a tuple of size 2") and nothing was
// reused from the service. Found by the B1 harden campaign on yalc in the URL form (gate rev 3 note 9).
//
// protects=  the URL form of --det-cache (B2.2): an entry pushed by one machine is a usable candidate on another,
//            checked against the second machine's inputs (a changed input still proves nothing).
// fails_when= machine 2 (empty local mirror) reports a remote error, pull_proven = 0 or no reused file for an
//            unchanged project; or, after the input changed, reuses anything; or a pushed entry document lists a
//            chunk or group address instead of (key, dependency) pairs.
// no_claim=  the service's trust model (docs/SHARED-CACHE.md), or Python's push.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const { BIN, TMP, NODE_DIR } = require('./helpers');

const RUNNERS = (process.env.DETJS_TEST_RUNNERS || 'vitest,jest').split(',');
const SCRIPT = path.resolve(NODE_DIR, '..', 'python', 'detpy', 'cache_service.py');
const DATA = path.join(TMP, 'cache-b1-remote', 'service');
let svc;
let token;
let port;

before(async () => {
  fs.rmSync(DATA, { recursive: true, force: true });
  fs.mkdirSync(DATA, { recursive: true });
  token = spawnSync('python3', [SCRIPT, 'token', '--data', DATA, '--org', 'b'], { encoding: 'utf8' }).stdout.trim().split('\n')[0];
  port = 19300 + Math.floor(Math.random() * 500);
  svc = spawn('python3', [SCRIPT, 'serve', '--data', DATA, '--host', '127.0.0.1', '--port', String(port)], { stdio: 'ignore' });
  for (let i = 0; i < 100; i++) {
    const r = spawnSync('curl', ['-s', `http://127.0.0.1:${port}/v1/health`], { encoding: 'utf8' });
    if (r.stdout.includes('ok')) break;
    await new Promise((r2) => setTimeout(r2, 100));
  }
});
after(() => { if (svc) svc.kill(); });

function project(runner) {
  const dir = path.join(TMP, 'cache-b1-remote', runner);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: `b1-remote-${runner}`, private: true }));
  const ext = runner === 'vitest' ? '.test.mjs' : '.test.js';
  const head = runner === 'vitest' ? "import { test, expect } from 'vitest'; import fs from 'node:fs';" : "const fs = require('node:fs');";
  if (runner === 'vitest') fs.writeFileSync(path.join(dir, 'vitest.config.mjs'), "export default { test: { include: ['tests/**/*.test.mjs'] } };\n");
  else fs.writeFileSync(path.join(dir, 'jest.config.js'), "module.exports = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node' };\n");
  fs.writeFileSync(path.join(dir, 'data.txt'), '1');
  fs.writeFileSync(path.join(dir, 'tests', `a${ext}`), `${head}\ntest('a', () => { expect(process.env.HOME === undefined).toBe(false); expect(fs.readFileSync('data.txt', 'utf8')).toBe('1'); });\n`);
  fs.writeFileSync(path.join(dir, 'tests', `b${ext}`), `${head}\ntest('b', () => { expect(1).toBe(1); });\n`);
  return dir;
}

function run(runner, dir, n) {
  const env = { ...process.env, FENVIX_CACHE_TOKEN: token, FENVIX_CACHE_LOCAL: path.join(dir, `.mirror-${n}`) };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS']) delete env[k];
  const sum = path.join(dir, '.detjs', 'cache-summary.json');
  fs.rmSync(sum, { force: true });
  const r = spawnSync(process.execPath, [BIN, runner, ...(runner === 'vitest' ? ['run'] : []), '--det', '--det-workers=1',
    `--det-cache=http://127.0.0.1:${port}/b/${runner}`, ...(runner === 'jest' ? [`--cacheDirectory=${path.join(dir, '.jest-cache')}`] : [])],
  { cwd: dir, encoding: 'utf8', env, timeout: 240000 });
  const summary = JSON.parse(fs.readFileSync(sum, 'utf8'));
  return { status: r.status, summary, out: `status=${r.status}\n${JSON.stringify(summary.remote)}\n${(r.stdout || '').slice(-2000)}\n${(r.stderr || '').slice(-2000)}` };
}

function entryDocs() {
  // the service's own store: every entry document must list (key, dependency) pairs
  const r = spawnSync('python3', ['-c', `
import sqlite3, zlib, json, sys
c = sqlite3.connect('file:${DATA}/cache.sqlite3?mode=ro', uri=True)
out = []
for (b,) in c.execute("select data from blobs where kind='entry'"):
    b = bytes(b)
    for f in (lambda x: zlib.decompress(x, 31), zlib.decompress, lambda x: x):
        try:
            d = json.loads(f(b)); break
        except Exception:
            d = None
    out.append(d)
print(json.dumps(out))`], { encoding: 'utf8' });
  return JSON.parse(r.stdout);
}

for (const runner of RUNNERS) {
  test(`${runner}: an entry pushed by machine 1 proves reuse on machine 2; a changed input still runs`, { timeout: 600000 }, () => {
    const dir = project(runner);
    const r1 = run(runner, dir, 1);
    assert.equal(r1.status, 0, r1.out);
    assert.equal(r1.summary.remote.error, null, r1.out);
    assert.ok(r1.summary.remote.push_entry_docs_new >= 4, r1.out);
    const r2 = run(runner, dir, 2);
    assert.equal(r2.summary.remote.error, null, `pull of machine 1's entries\n${r2.out}`);
    assert.ok(r2.summary.remote.pull_proven >= 4, r2.out);
    assert.equal(r2.summary.reused_files, 2, r2.out);
    fs.writeFileSync(path.join(dir, 'data.txt'), '2');
    const r3 = run(runner, dir, 3);
    assert.ok(!(r3.summary.reused_files_list || []).some((f) => f.startsWith('tests/a.')), `changed input: tests/a must run\n${r3.out}`);
  });
}

test('pushed entry documents list pairs, never chunk or group addresses', () => {
  const docs = entryDocs().filter(Boolean);
  assert.ok(docs.length >= 8, `entries pushed: ${docs.length}`);
  for (const d of docs) {
    for (const k of ['env', 'data']) {
      for (const x of d.entry[k]) assert.ok(Array.isArray(x) && x.length === 2, `${d.nodeid} ${k}: ${JSON.stringify(x)}`);
    }
  }
});
