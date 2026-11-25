'use strict';
// Unit tests of the --det-isolate header merge (src/isolate-meta.js; spec "false greens on release-1", Phase B).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mergeSessionMeta, EQUAL, UNION, OWN, SENSOR, OTHER } = require('../src/isolate-meta');

const SENS = { contract: 1, runtime: 'node22', sensor: 'node-surface/1', surface: 'abc' };
const base = (extra = {}) => ({
  runner: 'vitest', seed: 0, epoch_ns: '1', controls: ['fs', 'net', 'order', 'seeds', 'time', 'timers'], inputs: { env: { 'env:A': '1' } }, provable: SENS,
  not_proven_outside_tests: [], env_read_outside_tests: ['X'], files_read_outside_tests: [], notes: [],
  parallel: { workers: 4, requested: null, plan: { workers: 4 }, placement: { deviations: [], processes: [['f']] }, hazards: [], timing: { files: 1, test_file_seconds: 0.1, lanes_wall_seconds: 0.1 } },
  files: ['f'], cli_args: ['f', '-t', 'x'], isolation: 'one session', status: { failed: 0 }, unordered_parts: 0, cassette_oldest_days: null,
  ...extra,
});

test('protects=a read outside any test in a LATER session reaches the final header (not_proven_outside_tests, env_read_outside_tests); fails_when=only the first session\'s lists are kept; no_claim=how the sessions record the reads (integration: isolate-signals.test.js)', () => {
  const { meta, failClosed } = mergeSessionMeta([
    base({ not_proven_outside_tests: [], env_read_outside_tests: ['X'] }),
    base({ not_proven_outside_tests: ['env:GITHUB_WORKSPACE=d@tests/b.test.mjs'], env_read_outside_tests: ['FOO', 'X'] }),
    base({ not_proven_outside_tests: ['env:GITHUB_WORKSPACE=d@tests/b.test.mjs', 'env:RUNNER_TEMP=e@c'] }),
  ], ['a', 'b', 'c']);
  assert.deepEqual(failClosed, []);
  assert.deepEqual(meta.not_proven_outside_tests, ['env:GITHUB_WORKSPACE=d@tests/b.test.mjs', 'env:RUNNER_TEMP=e@c'], 'union, first appearance, deduplicated');
  assert.deepEqual(meta.env_read_outside_tests, ['X', 'FOO']);
  assert.deepEqual(meta.provable, SENS, 'the same sensor in every session: kept');
  assert.equal(meta.provable_absent, undefined);
});

test('protects=a later session whose sensor is absent removes provable from the run; fails_when=the first session\'s provable is kept; no_claim=none beyond protects', () => {
  const { meta } = mergeSessionMeta([base(), base({ provable: undefined, provable_absent: 'switched off' }), base({ provable: undefined, provable_absent: 'other' })], ['a', 'b', 'c']);
  assert.equal(meta.provable, undefined);
  assert.equal(meta.provable_absent, 'switched off (+1 more sessions)');
});

test('protects=a session that declared nothing, or another sensor, removes provable and is named; fails_when=a missing or different declaration is ignored; no_claim=which sensors the core knows (provable::judge)', () => {
  const missing = mergeSessionMeta([base(), base({ provable: undefined })], ['a', 'b']).meta;
  assert.equal(missing.provable, undefined);
  assert.match(missing.provable_absent, /no sensor declared by b/);
  const differ = mergeSessionMeta([base(), base({ provable: { ...SENS, surface: 'zzz' } })], ['a', 'b']).meta;
  assert.equal(differ.provable, undefined);
  assert.match(differ.provable_absent, /different sensors \(b differ from a\)/);
  const none = mergeSessionMeta([], []).meta;
  assert.equal(none.provable, undefined);
  assert.match(none.provable_absent, /no per-test session wrote a trace/);
});

test('protects=run configuration that differs between sessions, and a key the merge has no rule for, fail closed; fails_when=the first session\'s value is taken as the run\'s; no_claim=that every such key exists in real sessions (the list: harness/release1_false_greens/isolate-meta-keys.md)', () => {
  const r = mergeSessionMeta([base(), base({ epoch_ns: '2' })], ['a', 'b']);
  assert.equal(r.meta.provable, undefined);
  assert.match(r.meta.provable_absent, /differ in epoch_ns \(b\)/);
  const u = mergeSessionMeta([base(), base({ brand_new_signal: true })], ['a', 'b']);
  assert.equal(u.meta.provable, undefined);
  assert.match(u.meta.provable_absent, /brand_new_signal, which the --det-isolate merge has no rule for/);
  assert.equal(u.meta.brand_new_signal, undefined);
});

test('protects=the run as a whole has no parallel lanes and no session\'s timing: parallel is {workers: 1, isolate: true}; fails_when=the first session\'s plan and lanes timing are reported as the run\'s; no_claim=the runner\'s reading of it (runner-proof node_proof: workers 1 is no proof due)', () => {
  const { meta, failClosed } = mergeSessionMeta([base(), base()], ['a', 'b'], ['--det', '--det-isolate']);
  assert.deepEqual(meta.parallel, { workers: 1, isolate: true });
  assert.deepEqual(failClosed, []);
  assert.deepEqual(meta.cli_args, ['--det', '--det-isolate']);
  const hz = mergeSessionMeta([base(), base({ parallel: { workers: 4, hazards: [{ kind: 'path' }] } })], ['a', 'b']);
  assert.equal(hz.meta.provable, undefined, 'a session with hazards fails closed');
  const rr = mergeSessionMeta([base(), base({ hazard_rerun: { files: [] } })], ['a', 'b']);
  assert.equal(rr.meta.provable, undefined, 'a session with a one-lane re-run fails closed');
});

test('protects=every key of a session header has exactly one rule; fails_when=a key is in two rule sets (its merge would be ambiguous); no_claim=none beyond protects', () => {
  const all = [EQUAL, UNION, OWN, SENSOR, OTHER].flatMap((s) => [...s]);
  assert.equal(new Set(all).size, all.length);
});

const REUSE = { ...SENS, sensor: 'cache-reuse/1' };
const reusedSession = (extra = {}) => base({ provable: REUSE, reused_tests: ['tests/a.test.mjs::a'], ...extra });

test('protects=a partly reused --det-isolate run (one session all reused: cache-reuse/1, one that ran: node-surface/1) keeps the running sensor (founder decision 2026-11-25); fails_when=the mixed run is NOT PROVEN, or takes cache-reuse/1 as the run\'s sensor; no_claim=that the reused entries were recorded under these controls (the cache key\'s job)', () => {
  const { meta, failClosed } = mergeSessionMeta([reusedSession(), base()], ['a', 'b']);
  assert.deepEqual(failClosed, []);
  assert.deepEqual(meta.provable, SENS);
  assert.equal(meta.provable_absent, undefined);
});

test('protects=a mixed run with a control the sensors require switched off is NOT PROVEN; fails_when=the cache-reuse/1 session is waved through with timers off; no_claim=the core\'s list itself (read from the engine: provableRequiredControls)', () => {
  const ctl = ['fs', 'net', 'order', 'seeds', 'time'];
  const { meta } = mergeSessionMeta([reusedSession({ controls: ctl }), base({ controls: ctl })], ['a', 'b']);
  assert.equal(meta.provable, undefined);
  assert.match(meta.provable_absent, /a control the sensors require was off \(required: .*timers/);
});

test('protects=a mixed run whose cache-reuse/1 session carries another runtime key is NOT PROVEN; fails_when=only the sensor name is compared; no_claim=which runtimes the core audited', () => {
  const { meta } = mergeSessionMeta([reusedSession({ provable: { ...REUSE, runtime: 'node24' } }), base()], ['a', 'b']);
  assert.equal(meta.provable, undefined);
  assert.match(meta.provable_absent, /a: cache-reuse\/1 with another contract, accounting table or runtime key/);
  const notReused = mergeSessionMeta([reusedSession({ reused_tests: undefined }), base()], ['a', 'b']).meta;
  assert.equal(notReused.provable, undefined, 'cache-reuse/1 from a session that reused nothing');
});

test('protects=a run whose sessions were all reused keeps cache-reuse/1; fails_when=the all-reused run loses its sensor; no_claim=none beyond protects', () => {
  const { meta } = mergeSessionMeta([reusedSession(), reusedSession({ reused_tests: ['tests/b.test.mjs::b'] })], ['a', 'b']);
  assert.deepEqual(meta.provable, REUSE);
  assert.equal(meta.provable_absent, undefined);
});

test('protects=the merge\'s other fail-closed branches (/review): a configuration key present in one session and absent from another, a signal list that is not a list, a session with test records and no header (its meta is empty), an engine that cannot name the required controls; and inputs_error is carried with the count; fails_when=absence is taken for agreement, a malformed list is dropped silently, or an unknown list of controls passes; no_claim=none beyond protects', () => {
  const noEpoch = base(); delete noEpoch.epoch_ns;
  const missing = mergeSessionMeta([base(), noEpoch], ['a', 'b']).meta;
  assert.equal(missing.provable, undefined);
  assert.match(missing.provable_absent, /differ in epoch_ns \(b\)/);
  const notList = mergeSessionMeta([base(), base({ notes: 'x' })], ['a', 'b']).meta;
  assert.equal(notList.provable, undefined);
  assert.match(notList.provable_absent, /notes is not a list/);
  const headerless = mergeSessionMeta([base(), {}], ['a', 'b']).meta;
  assert.equal(headerless.provable, undefined, 'a session without a header declares no sensor');
  const thrower = () => { throw new Error('no engine'); };
  const noList = mergeSessionMeta([reusedSession(), base()], ['a', 'b'], null, (s) => (s === 'cache-reuse/1' ? thrower() : ['time'])).meta;
  assert.equal(noList.provable, undefined, 'a required-controls lookup that throws is not a pass');
  const errs = mergeSessionMeta([base({ inputs_error: 'e1' }), base({ inputs_error: 'e2' })], ['a', 'b']).meta;
  assert.equal(errs.inputs_error, 'e1 (+1 more sessions)');
});

test('protects=a session whose meta.parallel lists (hazards, carried, placement.deviations) are not arrays fails closed; fails_when=a truthy non-array (`{}`: no .length) passes as an empty list (this branch at f3ecbe73, /review adversarial); no_claim=what a session writes there (one-file sessions: empty lists)', () => {
  const p = base().parallel;
  for (const bad of [{ ...p, hazards: {} }, { ...p, carried: 'x' }, { ...p, placement: { ...p.placement, deviations: {} } }, { ...p, placement: 'x' }, { ...p, placement: [] }, [p]]) {
    const { failClosed } = mergeSessionMeta([base(), base({ parallel: bad })], ['a', 'b']);
    assert.ok(failClosed.some((r) => /^b: /.test(r)), `${JSON.stringify(bad)} -> ${JSON.stringify(failClosed)}`);
  }
  assert.deepEqual(mergeSessionMeta([base(), base()], ['a', 'b']).failClosed, [], 'control: empty lists pass');
});
