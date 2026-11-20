'use strict';
// F-03 (audit G-0139, G-0140 and their family on Node): the trace header records the run inputs (time zone,
// locale, environment variables as digests, seed, clock, network, runtime) and `verify` never reports two runs
// identical when one of them differs, naming the input as the first divergent event.
// Run: cd node && node --test test/verifier-inputs.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const native = require('../src/native');
const { fixture, crun, show } = require('./runner-helpers');

const T = { timeout: 600000 };
const BODY = "import { test } from 'node:test'; import assert from 'node:assert/strict';\n"
  + "test('local date', () => { assert.ok(String(new Date()).length > 0); });\n"
  + "test('plain', () => { assert.ok(true); });\n";

function runTo(dir, name, env, det = ['--det']) {
  const r = crun('node-test', dir, [], { cache: false, det, env });
  assert.equal(r.status, 0, show(r));
  const dst = path.join(dir, `${name}.jsonl`);
  fs.copyFileSync(path.join(dir, '.detjs', 'trace.jsonl'), dst);
  return dst;
}

test('the header records the run inputs; same inputs are identical', T, () => {
  const dir = fixture('verifier-inputs', 'same', { 'tests/a.test.mjs': BODY });
  const a = runTo(dir, 'a', { TZ: 'UTC' });
  const b = runTo(dir, 'b', { TZ: 'UTC' });
  const hdr = JSON.parse(fs.readFileSync(a, 'utf8').split('\n')[0]).meta;
  for (const k of ['runtime', 'runner', 'seed', 'clock', 'tz', 'locale', 'network', 'urandom']) assert.ok(k in hdr.inputs, k);
  assert.ok(Object.keys(hdr.inputs).some((k) => k.startsWith('env:')));
  const rep = JSON.parse(native.verify([a, b]));
  assert.equal(rep.summary.stable, rep.summary.tests, JSON.stringify(rep.input_differences));
  assert.equal(rep.summary.inputs_recorded, true);
});

for (const [name, envA, envB, reason] of [
  ['tz', { TZ: 'UTC' }, { TZ: 'Asia/Tokyo' }, 'tz'],
  ['env', { TZ: 'UTC', NODE_TRUTH_FLAG: 'a' }, { TZ: 'UTC', NODE_TRUTH_FLAG: 'b' }, 'env'],
  ['seed', { TZ: 'UTC', DETJS_SEED: '1' }, { TZ: 'UTC', DETJS_SEED: '2' }, 'seed'],
]) {
  test(`runs differing only in ${name} are divergent and name it`, T, () => {
    const dir = fixture('verifier-inputs', name, { 'tests/a.test.mjs': BODY });
    const a = runTo(dir, 'a', envA);
    const b = runTo(dir, 'b', envB);
    const rep = JSON.parse(native.verify([a, b]));
    assert.equal(rep.summary.stable, 0, JSON.stringify(rep.summary));
    assert.equal(rep.input_differences[0].reason, reason, JSON.stringify(rep.input_differences));
    for (const t of rep.tests) assert.equal(t.divergence.reason, reason, t.nodeid);
  });
}
