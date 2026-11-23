const assert = require('node:assert');
const crypto = require('node:crypto');

// Reads real OS entropy when FENVIX_FIXTURE_ENTROPY=1 (tests/test_runner_node.py: NOT PROVEN), else skipped.
describe('entropy', () => {
  (process.env.FENVIX_FIXTURE_ENTROPY === '1' ? it : it.skip)('reads OS entropy', () => {
    assert.strictEqual(crypto.randomBytes(16).length, 16);
  });
});
