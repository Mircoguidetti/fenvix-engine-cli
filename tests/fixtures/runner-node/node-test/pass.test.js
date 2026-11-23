const test = require('node:test');
const assert = require('node:assert');

test('adds', () => { assert.strictEqual(1 + 1, 2); });
test('concatenates', () => { assert.strictEqual('a' + 'b', 'ab'); });
test('sorts', () => { assert.deepStrictEqual([3, 1, 2].sort(), [1, 2, 3]); });
