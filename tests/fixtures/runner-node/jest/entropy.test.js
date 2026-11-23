const crypto = require('node:crypto');

// Reads real OS entropy when FENVIX_FIXTURE_ENTROPY=1 (tests/test_runner_node.py: NOT PROVEN), else skipped.
(process.env.FENVIX_FIXTURE_ENTROPY === '1' ? test : test.skip)('reads OS entropy', () => {
  expect(crypto.randomBytes(16).length).toBe(16);
});
