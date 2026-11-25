'use strict';
// Fault injection, channel (b): an environment variable the test read (cache measurement B, B1 step 2).
// protects=  a test file is never reused after the value of an environment variable its test read changed.
// fails_when= the cached run with FAULT_B=two after a seed with FAULT_B=one reports tests/target a hit.
// no_claim=  coverage of C getenv in native code (NODE-CACHE.md Limits).
const { test, describe } = require('node:test');
const { RUNNERS, project, cycle } = require('./cache-fault-lib');

for (const runner of RUNNERS) {
  describe(`fault (b) environment variable: ${runner}`, () => {
    test('changed variable read by the test -> miss', { timeout: 600000 }, () => {
      const dir = project(runner, 'env', () => "test('target', () => { expect(typeof process.env.FAULT_B).toBe('string'); });");
      cycle(runner, dir, () => {}, { seedOpts: { env: { FAULT_B: 'one' } }, cachedOpts: { env: { FAULT_B: 'two' } } });
    });
  });
}
