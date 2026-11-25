'use strict';
// Fault injection, channel (f): the clock day, for a test that reads the clock (cache measurement B, B1 step 2).
// protects=  a test that read the clock is never reused on another day: two runs whose --det-cache epochs are one
//            day apart (explicit --det-epoch, as the virtual day of two consecutive UTC days).
// fails_when= the cached run with the next day's epoch reports tests/target a hit.
// no_claim=  real-clock reads Level 0 does not control (native code, TLS validity: --det-cache-max-age bounds them).
const { test, describe } = require('node:test');
const { RUNNERS, project, cycle } = require('./cache-fault-lib');

for (const runner of RUNNERS) {
  describe(`fault (f) clock day: ${runner}`, () => {
    test('next day epoch for a test that reads the clock -> miss', { timeout: 600000 }, () => {
      const dir = project(runner, 'clock', () => "test('target', () => { expect(new Date().getUTCFullYear()).toBeGreaterThan(2000); });");
      cycle(runner, dir, () => {}, {
        seedOpts: { args: ['--det-epoch=2026-12-05T00:00:00Z'] },
        cachedOpts: { args: ['--det-epoch=2026-12-06T00:00:00Z'] },
      });
    });
  });
}
