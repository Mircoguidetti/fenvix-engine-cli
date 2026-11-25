'use strict';
// Fault injection, channel (e): a runner configuration file (cache measurement B, B1 step 2).
// protects=  no test file is reused after the runner's configuration file changed (configuration digest and start-up
//            reads; gate rev 3 note 10: both contributions are removed by this channel's mutation).
// fails_when= the cached run after vitest.config.mjs / jest.config.js changed reports tests/target a hit.
// no_claim=  configuration a plugin reads in the main process outside the keyed files (NODE-CACHE.md Limits).
const { test, describe } = require('node:test');
const { RUNNERS, project, cycle, write } = require('./cache-fault-lib');

const CONFIG = {
  vitest: ['vitest.config.mjs', "export default { test: { include: ['tests/**/*.test.mjs'], testTimeout: 7000 } };\n"],
  jest: ['jest.config.js', "module.exports = { testMatch: ['**/tests/**/*.test.js'], testEnvironment: 'node', testTimeout: 7000 };\n"],
};

for (const runner of RUNNERS) {
  describe(`fault (e) runner configuration file: ${runner}`, () => {
    test('changed configuration file -> miss', { timeout: 600000 }, () => {
      const dir = project(runner, 'config', () => "test('target', () => { expect(2 * 2).toBe(4); });");
      cycle(runner, dir, () => write(dir, { [CONFIG[runner][0]]: CONFIG[runner][1] }), { otherReused: false });
    });
  });
}
