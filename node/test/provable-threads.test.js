'use strict';
// C2 (spec "false greens on release-1"): Vitest pool=threads workers share one pid. The sensor's declaration was a
// file per pid (prov/<pid>.txt), so a thread's `absent` line could be overwritten by another thread's `ok`, and a
// thread that wrote nothing went unnoticed: the header said "watched" when one thread was not.
//
// The fault is injected into the FIRST worker thread to start (a --require hook through NODE_OPTIONS, which Node
// runs in every worker thread too: MEASURED, one line per <pid>-<threadId>), so that the faulty thread declares
// before the others and, with a file per pid, a later `ok` overwrote it.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

const T = { timeout: 300000 };

function hook(dir, fault) {
  return `'use strict';
const wt = require('node:worker_threads');
const fs = require('node:fs');
if (!wt.isMainThread && process.env.C2_FAULT) {
  let first = false;
  try { fs.closeSync(fs.openSync(${JSON.stringify(path.join(dir, 'first-thread'))}, 'wx')); first = true; } catch { /* another thread was first */ }
  if (first && process.env.C2_FAULT === 'absent') process.env.FENVIX_NO_PROVABLE_SENSOR = '1'; // this thread's env only
  if (first && process.env.C2_FAULT === 'silent') {
    const orig = fs.writeFileSync;
    fs.writeFileSync = function (p, ...rest) {
      if (/[\\\\/]prov[\\\\/][^\\\\/]+\\.txt$/.test(String(p))) throw Object.assign(new Error('injected: no declaration'), { code: 'EIO' });
      return orig.call(this, p, ...rest);
    };
  }
}
`;
}

function project(name) {
  const dir = path.join(TMP, 'provable-threads', name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: `fixture-${name}`, private: true, type: 'module' }));
  fs.writeFileSync(path.join(dir, 'vitest.config.mjs'), "export default { test: { include: ['tests/**/*.test.mjs'], pool: 'threads' } };\n");
  for (const n of ['a', 'b', 'c', 'd']) {
    fs.writeFileSync(path.join(dir, 'tests', `${n}.test.mjs`), `import { test, expect } from 'vitest';\ntest('${n}', () => { expect(1).toBe(1); });\n`);
  }
  fs.writeFileSync(path.join(dir, 'hook.cjs'), hook(dir));
  return dir;
}

function run(dir, fault) {
  const e = { ...process.env, NODE_OPTIONS: `--require ${path.join(dir, 'hook.cjs')}` };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_TEST_CONTEXT', 'FENVIX_NO_PROVABLE_SENSOR', 'C2_FAULT']) delete e[k];
  if (fault) e.C2_FAULT = fault;
  fs.rmSync(path.join(dir, 'first-thread'), { force: true });
  const r = spawnSync(process.execPath, [BIN, 'vitest', 'run', '--det', '--det-workers=2'], { cwd: dir, env: e, encoding: 'utf8', maxBuffer: 64 << 20 });
  const tr = path.join(dir, '.detjs', 'trace.jsonl');
  const meta = fs.existsSync(tr) ? JSON.parse(fs.readFileSync(tr, 'utf8').split('\n')[0]).meta : null;
  return { status: r.status, meta, injected: fs.existsSync(path.join(dir, 'first-thread')), show: `exit ${r.status}\n${(r.stdout || '').slice(-2500)}\n${(r.stderr || '').slice(-2500)}` };
}

test('protects=a Vitest worker thread whose sensor is absent removes provable from the run, though another thread of the same pid declared ok; fails_when=the threads share prov/<pid>.txt and the later ok overwrites the absent line (release-1 6e79a62c); no_claim=how a sensor fails in the field (forced: FENVIX_NO_PROVABLE_SENSOR in the first thread only)', T, () => {
  const dir = project('absent');
  const r = run(dir, 'absent');
  assert.ok(r.injected, `the fault was injected into a worker thread\n${r.show}`);
  assert.ok(r.meta, r.show);
  assert.equal(r.meta.provable, undefined, JSON.stringify(r.meta.provable));
  assert.match(String(r.meta.provable_absent), /FENVIX_NO_PROVABLE_SENSOR/, r.show);
});

test('protects=a worker thread that installed the engine\'s test hooks and wrote no declaration removes provable; fails_when=a part that declared nothing is not noticed and the others\' single declaration is taken as the run\'s (release-1 6e79a62c: decls.size === 1); no_claim=why a part writes nothing in the field (forced: its declaration write fails)', T, () => {
  const dir = project('silent');
  const r = run(dir, 'silent');
  assert.ok(r.injected, `the fault was injected into a worker thread\n${r.show}`);
  assert.ok(r.meta, r.show);
  assert.equal(r.meta.provable, undefined, JSON.stringify(r.meta.provable));
  assert.match(String(r.meta.provable_absent), /installed the test hooks and declared no sensor/, r.show);
});

test('protects=positive control (gate note 1): a clean two-thread Vitest run keeps provable and is green; fails_when=the per-thread files or the .ran markers make a clean run lose its sensor; no_claim=the forks pool (one thread per process: unchanged path)', T, () => {
  const dir = project('clean');
  const r = run(dir, null);
  assert.equal(r.status, 0, r.show);
  assert.ok(r.meta, r.show);
  assert.equal(r.meta.provable && r.meta.provable.sensor, 'node-surface/1', r.show);
  assert.equal(r.meta.provable_absent, undefined, r.show);
  assert.equal(r.meta.parallel && r.meta.parallel.workers, 2, 'two lanes: two worker threads of one process');
});
