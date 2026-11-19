'use strict';
// Fixtures and runs for the Bun and Deno shells (runner-bun.test.js, runner-deno.test.js): the binary is found on
// PATH (or DETJS_BUN / DETJS_DENO); when it is missing the suites skip with a message.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');
const { findBinary } = require('../src/runners/common');

const BINARY = { bun: findBinary('bun', 'DETJS_BUN'), deno: findBinary('deno', 'DETJS_DENO') };
const CMD = { bun: 'bun-test', deno: 'deno-test' };

function write(dir, files) {
  for (const [name, body] of Object.entries(files)) {
    const p = path.join(dir, name);
    if (body === null) { fs.rmSync(p, { force: true, recursive: true }); continue; }
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, body);
  }
}

function fixture(rt, name, files) {
  const dir = path.join(TMP, `runner-${rt}`, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  write(dir, { 'package.json': JSON.stringify({ name: `fx-${name}`, private: true }) });
  write(dir, files);
  return dir;
}

function childEnv(extra) {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS']) delete env[k];
  for (const [rt, b] of Object.entries(BINARY)) if (b) env[rt === 'bun' ? 'DETJS_BUN' : 'DETJS_DENO'] = b;
  return { ...env, ...(extra || {}) };
}

/** detjs <rt> run: {status, summary, trace, stdout, stderr}; `cache: false` = plain --det; `det: false` = the runner alone. */
function crun(rt, dir, { cache = true, det = true, args = [], env = {}, seed = null } = {}) {
  fs.rmSync(path.join(dir, '.detjs', 'cache-summary.json'), { force: true });
  fs.rmSync(path.join(dir, '.detjs', 'trace.jsonl'), { force: true });
  const base = rt === 'deno' ? ['-A'] : [];
  const d = det ? ['--det', ...(seed !== null ? [`--det-seed=${seed}`] : []), ...(cache ? [`--det-cache=${path.join(dir, '.cache')}`] : [])] : [];
  const r = spawnSync(process.execPath, [BIN, CMD[rt], ...d, ...base, ...args], { cwd: dir, encoding: 'utf8', env: childEnv(env), timeout: 240000 });
  let summary = null;
  try { summary = JSON.parse(fs.readFileSync(path.join(dir, '.detjs', 'cache-summary.json'), 'utf8')); } catch { /* none */ }
  let trace = null;
  try {
    const lines = fs.readFileSync(path.join(dir, '.detjs', 'trace.jsonl'), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
    trace = { header: lines[0], tests: lines.filter((l) => l.type === 'test') };
  } catch { /* none */ }
  return { status: r.status, summary, trace, stdout: r.stdout, stderr: r.stderr };
}

function show(r) {
  return `status=${r.status}\nreused=${JSON.stringify(r.summary && r.summary.reused_files_list)}\nmisses=${JSON.stringify(r.summary && r.summary.misses)}\n`
    + `not_cached=${JSON.stringify(r.summary && r.summary.not_cached_detail)}\nstdout=${(r.stdout || '').slice(-2500)}\nstderr=${(r.stderr || '').slice(-2000)}`;
}

const reused = (r) => (r.summary && r.summary.reused_files_list) || [];

function apply(dir, change) {
  if (!change) return;
  if (typeof change === 'function') change(); else write(dir, change);
}

/**
 * A keyed input: record (pass), reuse (the file must be reused, else the test proves nothing), change one input so that
 * a fresh run fails, then the cached run must not reuse the file and must agree with the fresh run.
 */
function noWrongReuse(rt, dir, file, change, opts = {}) {
  const env1 = opts.env1 || {};
  const r1 = crun(rt, dir, { env: env1, args: opts.args1 });
  assert.equal(r1.status, 0, `run 1 (record) must pass\n${show(r1)}`);
  const r2 = crun(rt, dir, { env: env1, args: opts.args1 });
  assert.equal(r2.status, 0, `run 2 must pass\n${show(r2)}`);
  assert.ok(reused(r2).includes(file), `run 2 must reuse ${file} (otherwise this test proves nothing)\n${show(r2)}`);
  apply(dir, change);
  const env2 = opts.env2 || env1;
  const fresh = crun(rt, dir, { cache: false, env: env2, args: opts.args2 || opts.args1 });
  assert.notEqual(fresh.status, 0, `the change must make a fresh run fail (test precondition)\n${show(fresh)}`);
  const r3 = crun(rt, dir, { env: env2, args: opts.args2 || opts.args1 });
  assert.ok(!reused(r3).includes(file), `WRONG REUSE: ${file} reused after its input changed; a fresh run fails\n${show(r3)}`);
  assert.equal(r3.status, fresh.status, `cached run must agree with the fresh run\n${show(r3)}`);
  return r3;
}

/**
 * An input the capture does not key: the file must never be reused (not cached, with `why` matching), and after the
 * change the cached run must agree with the fresh run.
 */
function neverReused(rt, dir, file, change, why, opts = {}) {
  const r1 = crun(rt, dir, { env: opts.env1 });
  assert.equal(r1.status, 0, `run 1 must pass\n${show(r1)}`);
  const r2 = crun(rt, dir, { env: opts.env1 });
  assert.equal(r2.status, 0, `run 2 must pass\n${show(r2)}`);
  assert.ok(!reused(r2).includes(file), `${file} must not be reused (input not keyed)\n${show(r2)}`);
  const detail = JSON.stringify((r2.summary && r2.summary.not_cached_detail) || {});
  assert.match(detail, why, `${file} not cached for the expected reason\n${show(r2)}`);
  if (change) {
    apply(dir, change);
    const fresh = crun(rt, dir, { cache: false, env: opts.env2 || opts.env1 });
    const r3 = crun(rt, dir, { env: opts.env2 || opts.env1 });
    assert.ok(!reused(r3).includes(file), `WRONG REUSE: ${file}\n${show(r3)}`);
    assert.equal(r3.status, fresh.status, `cached run must agree with the fresh run\n${show(r3)}`);
  }
  return r2;
}

function fingerprints(r) {
  return Object.fromEntries(((r.trace && r.trace.tests) || []).map((t) => [t.nodeid, `${t.outcome}:${t.fingerprint}`]));
}

module.exports = { BINARY, fixture, write, crun, show, reused, noWrongReuse, neverReused, fingerprints, TMP };
