'use strict';
// Fault injection, negative: a file no test read changes (cache measurement B, B1 step 2).
// protects=  the fault tests' meaning: a miss in channels (a)-(f) comes from the changed input, not from a cache that
//            misses on any change (a cache that never reuses would pass every channel test).
// fails_when= the cached run after data/unread.txt changed (no test reads it, it is no configuration file) reports
//            tests/target a miss.
// no_claim=  that every unread file is ignored (configuration files are keyed whether read or not).
const { test, describe } = require('node:test');
const { RUNNERS, project, cycle, write } = require('./cache-fault-lib');

for (const runner of RUNNERS) {
  describe(`fault negative (unread file): ${runner}`, () => {
    test('changed file no test read -> hit', { timeout: 600000 }, () => {
      const dir = project(runner, 'negative', () => "test('target', () => { expect(fs.readFileSync('data/in.txt', 'utf8').length).toBeGreaterThan(0); });",
        { 'data/in.txt': 'one\n', 'data/unread.txt': 'one\n' });
      cycle(runner, dir, () => write(dir, { 'data/unread.txt': 'two\n' }), { expectMiss: false });
    });
  });
}
