const test = require('node:test');
const assert = require('node:assert');
const crypto = require('node:crypto');

// Reads real OS entropy when FENVIX_FIXTURE_ENTROPY=1 (tests/test_runner_node.py: NOT PROVEN), else skipped.
test('reads OS entropy', { skip: process.env.FENVIX_FIXTURE_ENTROPY !== '1' }, () => {
  assert.strictEqual(crypto.randomBytes(16).length, 16);
});
