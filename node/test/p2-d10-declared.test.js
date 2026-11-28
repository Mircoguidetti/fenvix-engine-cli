'use strict';
// P2 D10 = A (founder decision 2026-11-28): a project declares in-repo directories that its test files do not share
// (agentlang: `logs/`, its logger's files, which no test outcome depends on: harness/p2/HAZARDS.md). The project writes
// the list in its own package.json, `"detjs": { "notShared": ["logs"] }`. The engine leaves the paths under an accepted
// directory out of the cross-lane hazards; it refuses the project root, a parent of it or anything outside it, and a
// directory that holds a test file of the run. The proof header shows the list as `meta.parallel.declared_not_shared`,
// with the project's package.json as its source, apart from the tool skip dirs (`skip_dirs`), whose rule (parallel-proof-
// gaps (c): only node_modules and the temporary directory) is unchanged.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { project, run } = require('./helpers');

const T = { timeout: 600000 };

// two files that write and read the same file under `dir`, and two that touch nothing; a and c land in different lanes
function fixture(name, { dir = 'logs', also = null, notShared = null } = {}) {
  const user = (n) => `import fs from 'node:fs'; import path from 'node:path';
test('${n} writes the shared file', () => {
  const p = path.join(process.cwd(), '${dir}', 'app.log');
  fs.mkdirSync(path.dirname(p), { recursive: true });
  const before = fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : '';
  fs.writeFileSync(p, before + '${n};');
  ${also ? `fs.writeFileSync(path.join(process.cwd(), '${also}'), '${n}');` : ''}
  expect(fs.readFileSync(p, 'utf8')).toContain('${n};');
});`;
  const other = (n) => `test('${n}', () => { expect(1).toBe(1); });`;
  const d = project('vitest', name, { a: user('a'), b: other('b'), c: user('c'), d: other('d') });
  const pkg = { name: `fixture-${name}`, private: true };
  if (notShared) pkg.detjs = { notShared };
  fs.writeFileSync(path.join(d, 'package.json'), JSON.stringify(pkg));
  return d;
}

function go(dir, env = {}) {
  const r = run('vitest', dir, ['--det', '--det-workers=2'], { env });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const m = r.trace.header.meta;
  const lanes = m.parallel.plan.lanes;
  const laneOf = (f) => lanes.findIndex((l) => l.includes(f));
  assert.notEqual(laneOf('tests/a.test.mjs'), laneOf('tests/c.test.mjs'), JSON.stringify(lanes));
  const hz = (m.hazard_rerun && m.hazard_rerun.hazards) || m.parallel.hazards || [];
  return { m, hz, pair: hz.filter((h) => /a\.test/.test(`${h.a} ${h.b}`) && /c\.test/.test(`${h.a} ${h.b}`)) };
}

test('a declared directory is left out of the hazards and shown in the header (D10)', T, () => {
  // protects= the project's declaration takes effect and is visible; fails_when= the shared log file still pairs the
  // files, or the header does not show the declared list and its source
  const { m, pair } = go(fixture('p2-d10-declared', { notShared: ['logs'] }));
  assert.deepEqual(pair, [], JSON.stringify(pair));
  const d = m.parallel.declared_not_shared;
  assert.ok(d, JSON.stringify(m.parallel));
  assert.deepEqual(d.dirs, ['logs']);
  assert.deepEqual(d.refused, []);
  assert.match(d.source, /package\.json/);
  assert.ok(!(m.parallel.skip_dirs || []).some((x) => /logs/.test(x)), JSON.stringify(m.parallel.skip_dirs));
});

test('the same directory given through the tool variables is still ignored, and the hazard stays (D10)', T, () => {
  // protects= gate (c) is unchanged: an in-repo directory in DETJS_FOOTPRINT_SKIP_DIRS is not skipped; fails_when= the
  // tool variable now skips it
  const dir = fixture('p2-d10-toolvar');
  const { m, pair } = go(dir, { DETJS_FOOTPRINT_SKIP_DIRS: path.join(dir, 'logs') });
  assert.ok(pair.length > 0, JSON.stringify(m.parallel.hazards));
  assert.ok((m.parallel.skip_dirs_ignored || []).some((x) => /logs$/.test(x.dir)), JSON.stringify(m.parallel.skip_dirs_ignored));
  assert.ok(!m.parallel.declared_not_shared || m.parallel.declared_not_shared.dirs.length === 0, JSON.stringify(m.parallel.declared_not_shared));
});

test('a declared directory that holds a test file of the run is refused, and its hazard stays (D10)', T, () => {
  // protects= a test file's own directory cannot be declared away; fails_when= it is accepted, or the pair on a file in it
  // is no longer a hazard
  const { m, pair } = go(fixture('p2-d10-tests', { dir: 'tests/data', notShared: ['tests'] }));
  assert.ok(pair.length > 0, JSON.stringify(m.parallel.hazards));
  const d = m.parallel.declared_not_shared;
  assert.deepEqual(d.dirs, []);
  assert.equal(d.refused.length, 1, JSON.stringify(d));
  assert.match(d.refused[0].reason, /test file/);
});

test('an undeclared shared file is still a hazard when another directory is declared (D10)', T, () => {
  // protects= the declaration covers its directory only; fails_when= a pair on a file outside it is lost
  const { m, pair } = go(fixture('p2-d10-other', { also: 'shared.txt', notShared: ['logs'] }));
  assert.ok(pair.some((h) => h.what === 'shared.txt' || /shared\.txt/.test(h.what)), JSON.stringify(m.parallel.hazards));
  assert.deepEqual(m.parallel.declared_not_shared.dirs, ['logs']);
});

test('the project root, a parent of it and a path outside it are refused (D10)', () => {
  // protects= the declaration cannot cover the whole project; fails_when= '.', '..' or an outside path is accepted
  const { declaredNotShared } = require('../src/parallel');
  const root = path.join(__dirname, '.tmp', 'p2-d10-unit');
  fs.mkdirSync(path.join(root, 'tests'), { recursive: true });
  fs.writeFileSync(path.join(root, 'package.json'), JSON.stringify({ detjs: { notShared: ['.', '..', '/etc', 'logs', 'tests'] } }));
  const d = declaredNotShared(root, ['tests/a.test.mjs', 'proj|tests/b.test.mjs']);
  assert.deepEqual(d.dirs, ['logs']);
  assert.deepEqual(d.refused.map((x) => x.dir), ['.', '..', '/etc', 'tests']);
  for (const x of d.refused) assert.ok(x.reason, JSON.stringify(x));
});
