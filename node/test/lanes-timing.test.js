'use strict';
// C3 (spec "false greens on release-1"): the lanes' wall time of a parallel run is computed over the lane markers
// whose start and end are both numbers. A marker without them made `lanes_wall_seconds` NaN (written null), and the
// runner (runner/fenvix-run node_proof) reads a null as "proof incomplete": a false red on a clean run. It is a
// timing field, not a completeness check: a test with no outcome record is `missing` and fails the run
// (src/exit-status.js countStatus), which the second test checks on a real run.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { collect } = require('../src/parallel');
const { BIN, TMP } = require('./helpers');

function lanesDir(markers) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'lanes-'));
  const dir = path.join(root, 'run');
  fs.mkdirSync(path.join(dir, 'lanes'), { recursive: true });
  markers.forEach((m, i) => fs.writeFileSync(path.join(dir, 'lanes', `m${i}.json`), JSON.stringify(m)));
  return { root, dir };
}

test('protects=lanes_wall_seconds is a finite number when one lane marker has no end (its file\'s leave() did not run); fails_when=the marker without end makes it NaN, written null, which the runner reads as "proof incomplete" (release-1 24962a94); no_claim=the placement checks on such a marker (deviations: their own fields)', () => {
  const plan = { workers: 2, lanes: [['a.test.js'], ['b.test.js']], digest: 'd', mode: 'node-test' };
  const { root, dir } = lanesDir([
    { label: 'a.test.js', pid: 1, thread: 0, start: 1000, end: 1400, preds: [] },
    { label: 'b.test.js', pid: 2, thread: 0, start: 1100, preds: [] }, // no end
  ]);
  const { meta } = collect(root, dir, ['a.test.js', 'b.test.js'], plan, { shared: false, write: false });
  const w = JSON.parse(JSON.stringify(meta)).timing.lanes_wall_seconds;
  assert.equal(typeof w, 'number', JSON.stringify(meta.timing));
  assert.ok(Number.isFinite(w) && w >= 0, String(w));
  assert.equal(w, 0.4);
});

test('protects=a parallel run in which a test file crashes in the middle of a test is red; fails_when=the crash leaves the run green (its tests have no outcome record); no_claim=the exit code\'s exact value beyond non-zero', { timeout: 300000 }, () => {
  const dir = path.join(TMP, 'lanes-timing', 'crash');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'test'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: 'fixture-crash', private: true }));
  fs.writeFileSync(path.join(dir, 'test', 'a.test.js'), "const test = require('node:test');\ntest('a', () => { process.exit(0); });\ntest('a2', () => {});\n");
  for (const n of ['b', 'c']) fs.writeFileSync(path.join(dir, 'test', `${n}.test.js`), `const test = require('node:test');\ntest('${n}', () => {});\n`);
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_TEST_CONTEXT', 'NODE_OPTIONS']) delete env[k];
  const r = spawnSync(process.execPath, [BIN, 'node-test', '--det', '--det-workers=2', 'test/a.test.js', 'test/b.test.js', 'test/c.test.js'],
    { cwd: dir, env, encoding: 'utf8', maxBuffer: 64 << 20 });
  assert.notEqual(r.status, 0, `${r.stdout}\n${r.stderr}`);
});
