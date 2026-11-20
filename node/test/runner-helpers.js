'use strict';
// Shared helpers of the runner adapter suites (runner-node-test.test.js, runner-mocha.test.js): fixture projects in
// temporary directories, runs through bin/detjs.js, and the adversarial shape of review r021: record, reuse, change
// one input so that a fresh run fails, then the cached run must not reuse the file.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

function write(dir, files) {
  for (const [name, body] of Object.entries(files)) {
    const p = path.join(dir, name);
    if (body === null) { fs.rmSync(p, { force: true, recursive: true }); continue; }
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, body);
  }
}

function fixture(group, name, files) {
  const dir = path.join(TMP, group, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  write(dir, { 'package.json': JSON.stringify({ name: `${group}-${name}`, private: true }) });
  write(dir, files);
  return dir;
}

function cleanEnv(extra = {}) {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_SEED', 'DETJS_CACHE_DIR']) delete env[k];
  return { ...env, ...extra };
}

/** One detjs run: `runner` (node-test | mocha), `args` runner arguments; det options from `det`. */
function crun(runner, dir, args = [], { cache = true, det = ['--det'], env = {}, verify = false } = {}) {
  fs.rmSync(path.join(dir, '.detjs', 'cache-summary.json'), { force: true });
  const c = cache ? [`--det-cache=${path.join(dir, '.cache')}`] : [];
  const v = verify ? ['--det-cache-verify'] : [];
  const r = spawnSync(process.execPath, [BIN, runner, ...det, ...c, ...v, ...args],
    { cwd: dir, encoding: 'utf8', env: cleanEnv(env), timeout: 240000 });
  let summary = null;
  try { summary = JSON.parse(fs.readFileSync(path.join(dir, '.detjs', 'cache-summary.json'), 'utf8')); } catch { /* none */ }
  return { status: r.status, summary, stdout: r.stdout || '', stderr: r.stderr || '' };
}

const show = (r) => `status=${r.status}\nsummary=${JSON.stringify(r.summary && { reused: r.summary.reused_files_list, misses: r.summary.misses, nc: r.summary.not_cached_detail })}\nstdout=${(r.stdout || '').slice(-1500)}\nstderr=${(r.stderr || '').slice(-1500)}`;
const reused = (r) => ((r.summary && r.summary.reused_files_list) || []).map((f) => f.split('@@')[0]);

/**
 * The adversarial shape: run 1 records (passes), run 2 reuses `file`, `change` changes one input so that a fresh
 * run without cache fails, run 3 (cached) must not reuse `file` and must fail like the fresh run.
 * `o.args`: runner args of every run; `o.args3`: runner args after the change (CLI changes); `o.env3`: env after it.
 */
function noWrongReuse(runner, dir, file, change, o = {}) {
  const args = o.args || [];
  const r1 = crun(runner, dir, args, { env: o.env });
  assert.equal(r1.status, 0, `run 1 must pass\n${show(r1)}`);
  const r2 = crun(runner, dir, args, { env: o.env });
  assert.ok(reused(r2).includes(file), `run 2 must reuse ${file}\n${show(r2)}`);
  if (typeof change === 'function') change(); else if (change) write(dir, change);
  const args3 = o.args3 || args;
  const env3 = o.env3 || o.env;
  const fresh = crun(runner, dir, args3, { cache: false, env: env3 });
  assert.notEqual(fresh.status, 0, `the change must make a fresh run fail\n${show(fresh)}`);
  const r3 = crun(runner, dir, args3, { env: env3 });
  assert.ok(!reused(r3).includes(file), `WRONG REUSE of ${file}\n${show(r3)}`);
  assert.notEqual(r3.status, 0, `the cached run must fail like the fresh run\n${show(r3)}`);
  return { r1, r2, fresh, r3 };
}

/** The input cannot be keyed: the file is never reused; `why` must appear in the reason. */
function notCached(runner, dir, file, why, o = {}) {
  const r1 = crun(runner, dir, o.args || [], { env: o.env });
  assert.equal(r1.status, 0, `run 1 must pass\n${show(r1)}`);
  const r2 = crun(runner, dir, o.args || [], { env: o.env });
  assert.equal(r2.status, 0, show(r2));
  assert.ok(!reused(r2).includes(file), `${file} must not be reused\n${show(r2)}`);
  const detail = JSON.stringify(r1.summary && r1.summary.not_cached_detail);
  assert.ok(detail.includes(why), `not cached because of ${why}\n${show(r1)}`);
}

/** Trace of a --det run: {order, tests: {nodeid: {outcome, fingerprint}}}. */
function trace(dir) {
  const lines = fs.readFileSync(path.join(dir, '.detjs', 'trace.jsonl'), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
  const tests = {};
  const order = [];
  for (const l of lines) if (l.type === 'test') { tests[l.nodeid] = { outcome: l.outcome, fingerprint: l.fingerprint, events: l.events }; order.push(l.nodeid); }
  return { header: lines[0], order, tests };
}

module.exports = { write, fixture, crun, show, reused, noWrongReuse, notCached, trace, TMP };
