'use strict';
// P2 C3 (coordinator decision D3 = A, 2026-11-26): a Vitest project that runs its files in one shared worker
// (poolOptions.forks.singleFork / poolOptions.threads.singleThread; agentlang: "Run tests sequentially to prevent SQLite
// database lock issues") made detjs refuse parallel lanes. An explicit --det-workers=N now overrides that: each file
// runs in a fresh worker of its own, in N lanes, and the header and the summary say so. What the shared worker was
// protecting against (files touching the same database) is what the hazard check catches: such a pair is still found
// and re-run in one lane.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { project, run } = require('./helpers');

const T = { timeout: 600000 };
// agentlang's configuration, as far as the pool goes
const SINGLE = { pool: 'forks', poolOptions: { forks: { singleFork: true } }, fileParallelism: false };
const indep = (n) => Object.fromEntries(Array.from({ length: n }, (_, i) => [`f${i}`, `test('t${i}', () => { expect(${i} + 1).toBe(${i + 1}); });`]));

test('vitest singleFork: --det-workers=2 runs 2 lanes and the header and summary state the override (C3)', T, () => {
  // protects= the override applies to an explicit --det-workers and is written where a reviewer reads it;
  // fails_when= the run stays serial (refused), or the override is not in meta.parallel.requested / the isolation line
  const dir = project('vitest', 'p2c3-single', indep(4), { vitest: SINGLE });
  const r = run('vitest', dir, ['--det', '--det-workers=2']);
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const p = r.trace.header.meta.parallel;
  assert.equal(p.workers, 2, JSON.stringify(p));
  assert.equal(p.requested.refused, null, JSON.stringify(p.requested));
  assert.match(String(p.requested.override), /singleThread\/singleFork.*--det-workers=2/, JSON.stringify(p.requested));
  assert.match(String(r.trace.header.meta.isolation), /override/, String(r.trace.header.meta.isolation));
  assert.match(r.stderr, /--det-workers=2 overrides/, r.stderr);
  for (const t of r.trace.tests) assert.equal(t.outcome, 'passed', t.nodeid);
});

test('vitest singleFork: without an explicit --det-workers the run stays serial (C3)', T, () => {
  // protects= only the explicit detjs option overrides the project's setting; fails_when= Vitest's own --maxWorkers
  // or detjs' default worker count overrides it
  const dir = project('vitest', 'p2c3-single-mw', indep(3), { vitest: SINGLE });
  const r = run('vitest', dir, ['--det', '--maxWorkers=2']);
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const p = r.trace.header.meta.parallel;
  assert.equal(p.workers, 1, JSON.stringify(p));
  assert.match(String(p.requested.refused), /singleThread\/singleFork/, JSON.stringify(p.requested));
  assert.ok(!p.requested.override, JSON.stringify(p.requested));
});

test('vitest singleFork overridden: two files using the same database file are still a hazard, re-run in one lane (C3)', T, () => {
  // protects= what the shared worker protected against is caught by the hazard check; fails_when= the pair is not a
  // hazard, or its tests are reported from the parallel run instead of the one-lane re-run
  const db = (name) => `import fs from 'node:fs'; import path from 'node:path';
test('${name} uses the database', () => {
  const p = path.join(process.cwd(), 'shared.db');
  const before = fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : '';
  fs.writeFileSync(p, before + '${name};');
  expect(fs.readFileSync(p, 'utf8')).toContain('${name};');
});`;
  const other = (n) => `test('${n}', () => { expect(1).toBe(1); });`;
  const dir = project('vitest', 'p2c3-single-db', { a: db('a'), b: other('b'), c: db('c'), d: other('d') }, { vitest: SINGLE });
  fs.rmSync(path.join(dir, 'shared.db'), { force: true });
  const r = run('vitest', dir, ['--det', '--det-workers=2']);
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const m = r.trace.header.meta;
  // the two database users are in different lanes of the plan (otherwise there is nothing to catch)
  const laneOf = (f) => m.parallel.plan.lanes.findIndex((l) => l.includes(f));
  assert.notEqual(laneOf('tests/a.test.mjs'), laneOf('tests/c.test.mjs'), JSON.stringify(m.parallel.plan.lanes));
  const hz = (m.hazard_rerun && m.hazard_rerun.hazards) || [];
  assert.ok(hz.some((h) => /tests\/a\.test\.mjs/.test(`${h.a} ${h.b}`) && /tests\/c\.test\.mjs/.test(`${h.a} ${h.b}`)), JSON.stringify(m.hazard_rerun || m.parallel.hazards));
  assert.ok(m.hazard_rerun.complete, JSON.stringify(m.hazard_rerun));
  assert.deepEqual([...m.hazard_rerun.files].sort().filter((f) => /tests\/[ac]\.test/.test(f)).length, 2, JSON.stringify(m.hazard_rerun.files));
});
