const assert = require('node:assert');

describe('pass', () => {
  it('adds', () => { assert.strictEqual(1 + 1, 2); });
  it('concatenates', () => { assert.strictEqual('a' + 'b', 'ab'); });
  it('sorts', () => { assert.deepStrictEqual([3, 1, 2].sort(), [1, 2, 3]); });
});
