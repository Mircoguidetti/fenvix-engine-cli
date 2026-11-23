'use strict';
// AC3 of the spec "Engine P0: no false green" (B2): `detjs verify` exits as Python's verify_exit_code. Two pairs of
// trace fixtures (JSONL: header + test lines, the format src/parallel-rerun.js readTrace reads), built from one real
// `detjs node-test --det` trace of a one-test suite:
//   * NOT PROVEN: both headers carry `not_proven_outside_tests: ["env:HTTPS_PROXY"]` (an uncontrolled variable read
//     while no test ran; crates/detpy-core/src/verify.rs `outside_not_proven`): every test is NOT PROVEN;
//   * inputs not recorded: both headers lack `inputs` (verify.rs: `inputs_recorded` = every run has meta.inputs).
// On bfaf70b4 both pairs exit 0 (detjs verify only looked at diverged and missing); now both exit 1, `--json` status
// "not_proven". The unchanged pair is the control: identical, exit 0 (so the fixtures are not NOT PROVEN for an
// unrelated reason such as an unknown sensor).
const { test, before } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BIN, TMP } = require('./helpers');

const DIR = path.join(TMP, 'verify-exit');
const T = { timeout: 300000 };

function cleanEnv() {
  const env = { ...process.env };
  for (const k of ['CI', 'GITHUB_ACTIONS', 'DETJS', 'NODE_OPTIONS', 'NODE_TEST_CONTEXT', 'DETJS_SEED', 'DETJS_CACHE_DIR', 'DETJS_HAZARD_RERUN']) delete env[k];
  return env;
}

function run(args) {
  const r = spawnSync(process.execPath, [BIN, ...args], { cwd: DIR, encoding: 'utf8', env: cleanEnv(), timeout: 120000 });
  return { ...r, show: `status=${r.status}\nstdout=${(r.stdout || '').slice(-2000)}\nstderr=${(r.stderr || '').slice(-2000)}` };
}

/** Write `name` as the base trace with its header's meta changed by `edit`. */
function variant(base, name, edit) {
  const lines = fs.readFileSync(base, 'utf8').split('\n').filter(Boolean);
  const header = JSON.parse(lines[0]);
  assert.equal(header.type, 'header');
  edit(header.meta);
  fs.writeFileSync(path.join(DIR, name), `${[JSON.stringify(header), ...lines.slice(1)].join('\n')}\n`);
  return name;
}

before(() => {
  fs.rmSync(DIR, { recursive: true, force: true });
  fs.mkdirSync(path.join(DIR, 't'), { recursive: true });
  fs.writeFileSync(path.join(DIR, 'package.json'), JSON.stringify({ name: 'verify-exit', private: true }));
  fs.writeFileSync(path.join(DIR, 't', 'a.test.js'), "const test = require('node:test');\nconst assert = require('node:assert');\ntest('adds', () => { assert.equal(1 + 1, 2); });\n");
  const r = run(['node-test', '--det', 't/a.test.js']);
  assert.equal(r.status, 0, r.show);
  const base = path.join(DIR, '.detjs', 'trace.jsonl');
  const lines = fs.readFileSync(base, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
  assert.equal(lines.filter((l) => l.type === 'test').length, 1);
  for (const s of ['a', 'b']) {
    variant(base, `same-${s}.jsonl`, () => {});
    variant(base, `np-${s}.jsonl`, (m) => { m.not_proven_outside_tests = ['env:HTTPS_PROXY']; });
    variant(base, `noinputs-${s}.jsonl`, (m) => { delete m.inputs; });
  }
});

test('control: the unchanged pair is identical, exit 0', T, () => {
  const r = run(['verify', 'same-a.jsonl', 'same-b.jsonl']);
  assert.equal(r.status, 0, r.show);
  const j = run(['verify', 'same-a.jsonl', 'same-b.jsonl', '--json']);
  assert.equal(j.status, 0, j.show);
  assert.equal(JSON.parse(j.stdout).status, 'identical', j.show);
});

test('a pair the verifier reports NOT PROVEN exits 1, --json status not_proven', T, () => {
  const r = run(['verify', 'np-a.jsonl', 'np-b.jsonl']);
  assert.equal(r.status, 1, r.show);
  const j = run(['verify', 'np-a.jsonl', 'np-b.jsonl', '--json']);
  assert.equal(j.status, 1, j.show);
  const rep = JSON.parse(j.stdout);
  assert.equal(rep.summary.not_proven, 1, j.show);
  assert.equal(rep.status, 'not_proven', j.show);
});

test('a pair whose headers lack recorded inputs exits 1, --json status not_proven', T, () => {
  const r = run(['verify', 'noinputs-a.jsonl', 'noinputs-b.jsonl']);
  assert.equal(r.status, 1, r.show);
  const j = run(['verify', 'noinputs-a.jsonl', 'noinputs-b.jsonl', '--json']);
  assert.equal(j.status, 1, j.show);
  const rep = JSON.parse(j.stdout);
  assert.equal(rep.summary.inputs_recorded, false, j.show);
  assert.equal(rep.status, 'not_proven', j.show);
});
