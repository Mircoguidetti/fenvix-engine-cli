'use strict';
// Fault injection, channel (d): a node_modules file of a module the test loaded (cache measurement B, B1 step 2).
// protects=  a test file is never reused after an installed package it loaded changed (runtime identity and module
//            content; gate rev 3 note 10: both contributions are removed by this channel's mutation).
// fails_when= the cached run after node_modules/faultmod/index.js changed reports tests/target a hit.
// no_claim=  packages outside every node_modules tree and NODE_PATH.
const { test, describe } = require('node:test');
const { RUNNERS, project, cycle, write } = require('./cache-fault-lib');

const MOD = (v) => ({
  'node_modules/faultmod/package.json': JSON.stringify({ name: 'faultmod', version: '1.0.0', main: 'index.js' }),
  'node_modules/faultmod/index.js': `module.exports = { v: ${JSON.stringify(v)} };\n`,
});

for (const runner of RUNNERS) {
  describe(`fault (d) node_modules file: ${runner}`, () => {
    test('changed installed module loaded by the test -> miss', { timeout: 600000 }, () => {
      const body = runner === 'vitest'
        ? "import faultmod from 'faultmod';\ntest('target', () => { expect(typeof faultmod.v).toBe('string'); });"
        : "const faultmod = require('faultmod');\ntest('target', () => { expect(typeof faultmod.v).toBe('string'); });";
      const dir = project(runner, 'node-modules', () => body, MOD('one'));
      // every installed file is part of the runtime identity (NODE-CACHE.md), so the other file misses too
      cycle(runner, dir, () => write(dir, MOD('two')), { otherReused: false });
    });
  });
}
