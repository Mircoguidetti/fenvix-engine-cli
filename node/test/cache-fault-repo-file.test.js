'use strict';
// Fault injection, channel (a): a repository file the test read (cache measurement B, B1 step 2).
// protects=  a test file is never reused after a repository file its test read changed.
// fails_when= the cached run after the change reports tests/target a hit (reused) instead of a miss that runs it.
// no_claim=  coverage of reads through native code or fs references taken before the capture (NODE-CACHE.md Limits).
const { test, describe } = require('node:test');
const { RUNNERS, project, cycle, write } = require('./cache-fault-lib');

for (const runner of RUNNERS) {
  describe(`fault (a) repository file: ${runner}`, () => {
    test('changed file read by the test -> miss', { timeout: 600000 }, () => {
      const dir = project(runner, 'repo-file', () => "test('target', () => { expect(fs.readFileSync('data/in.txt', 'utf8').length).toBeGreaterThan(0); });",
        { 'data/in.txt': 'one\n' });
      cycle(runner, dir, () => write(dir, { 'data/in.txt': 'two\n' }));
    });
  });
}
