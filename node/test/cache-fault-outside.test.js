'use strict';
// Fault injection, channel (c): a file outside the repository the test read (cache measurement B, B1 step 2).
// protects=  a test file is never reused after a file outside the project, read by its test by absolute path, changed.
// fails_when= the cached run after the outside file changed reports tests/target a hit.
// no_claim=  machines with different work paths (NODE-CACHE.md: machines sharing a cache use the same paths).
const { test, describe } = require('node:test');
const path = require('node:path');
const { RUNNERS, project, cycle, write, TMP } = require('./cache-fault-lib');

for (const runner of RUNNERS) {
  describe(`fault (c) file outside the repository: ${runner}`, () => {
    test('changed outside file read by the test -> miss', { timeout: 600000 }, () => {
      const outside = path.join(TMP, 'cache-fault-outside', runner, 'in.txt');
      write('/', { [outside]: 'one\n' });
      const dir = project(runner, 'outside', () => `test('target', () => { expect(fs.readFileSync(${JSON.stringify(outside)}, 'utf8').length).toBeGreaterThan(0); });`);
      cycle(runner, dir, () => write('/', { [outside]: 'two\n' }));
    });
  });
}
