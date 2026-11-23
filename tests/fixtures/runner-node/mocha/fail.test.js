const assert = require('node:assert');

// Fails only when FENVIX_FIXTURE_FAIL=1 (tests/test_runner_node.py: the exit status of a failing suite).
describe('fail', () => {
  it('fails on demand', () => { assert.strictEqual(process.env.FENVIX_FIXTURE_FAIL === '1' ? 'failed' : 'ok', 'ok'); });
});
