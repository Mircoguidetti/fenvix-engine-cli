'use strict';
// Error paths of the det-host-values options (/review 2026-11-24, testing specialist): coverage of refusals that
// had no test. These pass before and after the review fixes; they guard the refusals against later edits.
// Run: cd node && node --test test/host-values-unit.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const session = require('../src/session');
const selfcert = require('../src/selfcert');

test('--det-net takes open or closed and refuses anything else', () => {
  assert.equal(session.parseArgs(['--det', '--det-net=closed']).opts.net, 'closed');
  assert.equal(session.parseArgs(['--det', '--det-net=open']).opts.net, 'open');
  assert.throws(() => session.parseArgs(['--det', '--det-net=block']), /--det-net: open or closed, got block/);
});

test('an invalid inherited DETJS_EPOCH is not used: the epoch falls back to the host time', () => {
  const opts = { epochExplicit: false };
  const before = Date.now();
  const e = session.resolveEpoch(opts, { DETJS_EPOCH: 'not-a-date', DETJS_EPOCH_RUN: '1' });
  assert.notEqual(e, 'not-a-date');
  assert.ok(Math.abs(Date.parse(e) - before) < 5000, e);
});

test('an inherited DETJS_EPOCH without a run mark is not used', () => {
  const opts = { epochExplicit: false };
  const e = session.resolveEpoch(opts, { DETJS_EPOCH: '2025-01-01T00:00:00Z' });
  assert.notEqual(e, '2025-01-01T00:00:00Z');
});

test('selfcert refuses a validity outside UTCTime (1950-2049) and a non-date', () => {
  assert.throws(() => selfcert.generate('x', { notBefore: '2050-01-01T00:00:00Z', notAfter: '2051-01-01T00:00:00Z' }), /outside 1950-2049/);
  assert.throws(() => selfcert.generate('x', { notBefore: 'garbage', notAfter: '2030-01-01T00:00:00Z' }), /not a date/);
});
