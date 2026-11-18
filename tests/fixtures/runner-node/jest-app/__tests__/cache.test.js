const cache = require('../lib/cache');

describe('cache', () => {
  test('stores a value', () => { cache.set('a', 1); expect(cache.get('a')).toBe(1); });
  // Order-dependent: passes alone, fails after "stores a value".
  test('starts empty', () => { expect(cache.size()).toBe(0); });
  test.skip('is skipped', () => {});
});
