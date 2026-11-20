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

// HANDOFF P-041 "verifier: constant uncontrolled.* values": a test that runs a child process records a constant
// `uncontrolled.child` event (no per-run nonce, so its replays keep one fingerprint); the verifier never reports it
// identical and names the source; a test without such a source is stable.
test('a constant uncontrolled source: same fingerprint in both runs, never identical, the source named', T, () => {
  const body = "import { test } from 'node:test'; import assert from 'node:assert/strict'; import cp from 'node:child_process';\n"
    + "test('child', () => { assert.equal(cp.execFileSync(process.execPath, ['-e', 'process.stdout.write(\"1\")']).toString(), '1'); });\n"
    + "test('plain', () => { assert.ok(true); });\n";
  const dir = fixture('verifier-inputs', 'uncontrolled', { 'tests/a.test.mjs': body });
  const a = runTo(dir, 'a', { TZ: 'UTC' });
  const b = runTo(dir, 'b', { TZ: 'UTC' });
  const tests = (f) => Object.fromEntries(fs.readFileSync(f, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l))
    .filter((j) => j.type === 'test').map((j) => [j.nodeid.split('::').pop(), j]));
  const ta = tests(a);
  const tb = tests(b);
  assert.ok(ta.child.events.some((e) => e.o === 'uncontrolled.child'), JSON.stringify(ta.child.events));
  assert.equal(ta.child.fingerprint, tb.child.fingerprint, 'no per-run value in the event');
  const rep = JSON.parse(native.verify([a, b]));
  const by = Object.fromEntries(rep.tests.map((t) => [t.nodeid.split('::').pop(), t]));
  assert.equal(by.plain.status, 'stable', JSON.stringify(by.plain));
  assert.notEqual(by.child.status, 'stable', JSON.stringify(by.child));
  assert.equal(by.child.divergence.reason, 'child', JSON.stringify(by.child));
});
