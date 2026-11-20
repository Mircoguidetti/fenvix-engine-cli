'use strict';
// A customer-shaped node:test project (rows JS-02, JS-07, F-06, F-02 Node): TypeScript run directly with
// --experimental-strip-types (no build step), `node --test`, files sharded with --test-shard=N/4, PGlite (in-process
// Postgres, WASM) in most tests, `fetch` replaced by fakes, a module shared by part of the files. Proved here:
//   * --det: the same per-test fingerprints in two runs, and the four shards together give exactly the whole run's
//     tests and fingerprints;
//   * --test-concurrency=2 (node --test's own option) runs a fixed plan in two lanes that overlap in time, with the
//     same fingerprints as the serial run;
//   * --det-cache: every file reused when nothing changed; a change to the shared module reruns exactly its
//     dependents; PGlite state never leaks between files (each file checks it starts from an empty database);
//   * a flaky (order-dependent) test becomes a reproducible defect: `fenvix repro` names the polluter and prints the
//     replay command, the bundle fails 10/10 with one fingerprint.
// Not here: the real Postgres service of a few of the customer's tests (no database server in this test job).
// Needs the npm registry once (PGlite into test/.tmp/customer-deps) and python with detpy (FENVIX_PYTHON).
// Run: cd node && node --test --test-concurrency=1 test/customer-nodetest.test.js
const { test, before } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync, execFileSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

const T = { timeout: 1800000 };
const DEPS = path.join(TMP, 'customer-deps');
const DIR = path.join(TMP, 'customer-nodetest');
const NFILES = 36;
// type stripping: a flag before Node 23.6, on by default after (the flag is still accepted where it exists)
const STRIP = process.features && process.features.typescript ? [] : ['--experimental-strip-types'];

function write(rel, body) {
  const p = path.join(DIR, rel);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, body);
}

function project() {
  fs.rmSync(DIR, { recursive: true, force: true });
  fs.mkdirSync(DIR, { recursive: true });
  write('package.json', JSON.stringify({ name: 'customer-shaped', private: true, type: 'module', scripts: { test: 'node --experimental-strip-types --test' } }));
  fs.symlinkSync(path.join(DEPS, 'node_modules'), path.join(DIR, 'node_modules'), 'dir');
  write('src/db.ts', `import { PGlite } from '@electric-sql/pglite';
export type Item = { id: number; qty: number };
export async function freshDb(): Promise<PGlite> {
  const db = new PGlite();
  await db.exec('create table items (id serial primary key, qty int not null)');
  return db;
}
`);
  write('src/price.ts', 'export const RATE: number = 1.2;\nexport function price(n: number): number { return Math.round(n * RATE * 100) / 100; }\n');
  write('src/api.ts', `export type User = { id: number; name: string };
export async function getUser(id: number): Promise<User> {
  const r = await fetch(\`https://api.example.test/users/\${id}\`);
  if (!r.ok) throw new Error(\`status \${r.status}\`);
  return (await r.json()) as User;
}
`);
  for (let i = 0; i < NFILES; i++) {
    const usesPrice = i % 4 === 0;
    write(`test/f${String(i).padStart(2, '0')}.test.ts`, `import { test, describe, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { freshDb, type Item } from '../src/db.ts';
import { getUser } from '../src/api.ts';
${usesPrice ? "import { price } from '../src/price.ts';\n" : ''}
describe('file ${i}', () => {
  test('starts from an empty database, then inserts', async () => {
    const db = await freshDb();
    const before = await db.query<{ n: number }>('select count(*)::int as n from items');
    assert.equal(before.rows[0].n, 0);
    for (let k = 1; k <= ${(i % 5) + 1}; k++) await db.query('insert into items (qty) values ($1)', [k]);
    const r = await db.query<Item>('select id, qty from items order by id');
    assert.equal(r.rows.length, ${(i % 5) + 1});
    await db.close();
  });
  test('fetch is a fake', async () => {
    const real = globalThis.fetch;
    globalThis.fetch = (async (url: string) => new Response(JSON.stringify({ id: Number(String(url).split('/').pop()), name: 'u${i}' }), { status: 200 })) as typeof fetch;
    try { assert.deepEqual(await getUser(${i}), { id: ${i}, name: 'u${i}' }); } finally { globalThis.fetch = real; }
  });
  test('ids and clock', () => {
    assert.equal(crypto.randomUUID().length, 36);
    assert.ok(Date.now() > 0 && Math.random() < 1);
  });
${usesPrice ? `  test('price', () => { assert.equal(price(10), 12); });\n` : ''}});
`);
  }
  // an order-dependent test: passes in declaration order, fails when the shuffle puts 'reads' before 'sets'
  write('test/flaky.test.ts', `import { test } from 'node:test';
import assert from 'node:assert/strict';
let config: { mode?: string } = {};
test('sets', () => { config.mode = 'fast'; });
test('a', () => {});
test('b', () => {});
test('reads', () => { assert.equal(config.mode, 'fast'); });
`);
}

function cleanEnv(extra = {}) {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_SEED', 'DETJS_CACHE_DIR']) delete env[k];
  return { ...env, ...extra };
}

/** One detjs node-test run: {status, stdout, stderr, tests: {id: outcome|fp}, header, summary}. */
function det(args = [], { cache = null } = {}) {
  fs.rmSync(path.join(DIR, '.detjs', 'cache-summary.json'), { force: true });
  fs.rmSync(path.join(DIR, '.detjs', 'trace.jsonl'), { force: true });
  const c = cache ? [`--det-cache=${cache}`] : [];
  const r = spawnSync(process.execPath, [BIN, 'node-test', '--det', ...c, ...STRIP, ...args], { cwd: DIR, encoding: 'utf8', env: cleanEnv(), timeout: 900000 });
  const tests = {};
  let header = null;
  try {
    for (const l of fs.readFileSync(path.join(DIR, '.detjs', 'trace.jsonl'), 'utf8').split('\n').filter(Boolean)) {
      const j = JSON.parse(l);
      if (j.type === 'header') header = j;
      if (j.type === 'test') tests[j.nodeid] = `${j.outcome}|${j.fingerprint}`;
    }
  } catch { /* none */ }
  let summary = null;
  try { summary = JSON.parse(fs.readFileSync(path.join(DIR, '.detjs', 'cache-summary.json'), 'utf8')); } catch { /* none */ }
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '', tests, header, summary };
}
const show = (r) => `status=${r.status}\nstdout=${r.stdout.slice(-3000)}\nstderr=${r.stderr.slice(-3000)}`;
const reusedFiles = (r) => ((r.summary && r.summary.reused_files_list) || []).map((f) => f.split('@@')[0]);

before(() => {
  if (!fs.existsSync(path.join(DEPS, 'node_modules', '@electric-sql', 'pglite', 'package.json'))) {
    fs.mkdirSync(DEPS, { recursive: true });
    fs.writeFileSync(path.join(DEPS, 'package.json'), '{"name":"customer-deps","private":true}');
    execFileSync('npm', ['install', '--no-audit', '--no-fund', '--no-save', '@electric-sql/pglite@0.3.15'], { cwd: DEPS, stdio: 'inherit' });
  }
  project();
});

test('--det: same fingerprints in two runs; the four shards together are the whole run', T, () => {
  const a = det();
  const b = det();
  const ids = Object.keys(a.tests);
  assert.equal(ids.length, NFILES * 3 + Math.ceil(NFILES / 4) + 4, show(a));
  assert.ok(ids.every((id) => !a.tests[id].startsWith('failed')), show(a));
  assert.deepEqual(b.tests, a.tests);
  const union = {};
  for (let k = 1; k <= 4; k++) {
    const s = det([`--test-shard=${k}/4`]);
    assert.equal(s.status, 0, show(s));
    for (const [id, v] of Object.entries(s.tests)) {
      assert.ok(!(id in union), `${id} in two shards`);
      union[id] = v;
    }
  }
  assert.deepEqual(union, a.tests);
});

test('--test-concurrency=2: two lanes with a fixed plan, overlapping, same fingerprints as the serial run', T, () => {
  const serial = det();
  const par = det(['--test-concurrency=2']);
  assert.equal(par.status, 0, show(par));
  const p = par.header.meta.parallel;
  assert.equal(p.plan.workers, 2, JSON.stringify(p));
  assert.deepEqual(p.placement.deviations, [], JSON.stringify(p.placement));
  assert.deepEqual(p.hazards, [], JSON.stringify(p.hazards));
  // the lanes really ran at the same time: some file of lane 2 started before a file of lane 1 ended
  const spans = p.placement.spans;
  const lane = (k) => p.plan.lanes.findIndex((l) => l.includes(k));
  const keys = Object.keys(spans);
  assert.ok(keys.some((x) => keys.some((y) => lane(x) !== lane(y) && spans[y][0] < spans[x][1] && spans[y][0] >= spans[x][0])), JSON.stringify(spans));
  assert.deepEqual(par.tests, serial.tests);
  // the same plan again (sticky), and replayed from the trace
  const again = det(['--test-concurrency=2']);
  assert.equal(again.header.meta.parallel.plan.digest, p.plan.digest);
});

test('--det-cache: every file reused; a shared module change reruns exactly its dependents; PGlite state stays per file', T, () => {
  const cache = path.join(DIR, '.cache');
  fs.rmSync(cache, { recursive: true, force: true });
  const r1 = det([], { cache });
  assert.equal(r1.status, 0, show(r1));
  const r2 = det([], { cache });
  assert.equal(r2.status, 0, show(r2));
  const all = fs.readdirSync(path.join(DIR, 'test')).map((f) => `test/${f}`).sort();
  assert.deepEqual(reusedFiles(r2).sort(), all, show(r2));
  // the shared module changes: its dependents rerun (and fail like a fresh run), the other files stay reused
  write('src/price.ts', 'export const RATE: number = 1.3;\nexport function price(n: number): number { return Math.round(n * RATE * 100) / 100; }\n');
  const fresh = det();
  const failedFresh = Object.keys(fresh.tests).filter((id) => fresh.tests[id].startsWith('failed')).map((id) => id.split('::')[0]);
  const deps = all.filter((f) => /f(\d+)/.test(f) && Number(/f(\d+)/.exec(f)[1]) % 4 === 0);
  assert.deepEqual([...new Set(failedFresh)].sort(), deps);
  const r3 = det([], { cache });
  assert.deepEqual(reusedFiles(r3).sort(), all.filter((f) => !deps.includes(f)), show(r3));
  assert.notEqual(r3.status, 0);
  // in lanes, from the same store: the unchanged files are reused, the dependents rerun
  const r4 = det(['--test-concurrency=2'], { cache });
  assert.deepEqual(reusedFiles(r4).sort(), all.filter((f) => !deps.includes(f)), show(r4));
  write('src/price.ts', 'export const RATE: number = 1.2;\nexport function price(n: number): number { return Math.round(n * RATE * 100) / 100; }\n');
});

test('a flaky (order-dependent) test becomes a defect with a replay command', T, () => {
  const py = process.env.FENVIX_PYTHON || 'python3';
  const out = path.join(DIR, 'repro-out');
  fs.rmSync(out, { recursive: true, force: true });
  const r = spawnSync(py, ['-m', 'detpy.fenvix', 'repro', 'test/flaky.test.ts::reads', '--runner', 'node-test', '--seeds', '20',
    '--confirm', '10', '--out', out, '--', ...STRIP, 'test/flaky.test.ts'], { cwd: DIR, encoding: 'utf8', env: cleanEnv({ FENVIX_DETJS: `${process.execPath} ${BIN}` }), timeout: 1200000 });
  assert.equal(r.status, 0, `${r.stdout}\n${r.stderr}`);
  assert.match(r.stdout, /status: {2}REPRODUCED: failed 10\/10 replays with one fingerprint/);
  assert.match(r.stdout, /cause: [^\n]*test\/flaky\.test\.ts::sets/);
  const bundle = JSON.parse(fs.readFileSync(path.join(out, fs.readdirSync(out).find((d) => d !== '.work'), 'bundle.json'), 'utf8'));
  assert.equal(bundle.runner, 'node-test');
  assert.ok(bundle.command.startsWith('detjs node-test --det'), bundle.command);
  assert.ok(bundle.replay_command, JSON.stringify(bundle));
  assert.equal(bundle.order[bundle.order.length - 1], 'test/flaky.test.ts::reads');
});
