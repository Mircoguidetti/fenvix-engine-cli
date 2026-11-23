import { test, expect } from 'vitest';

test('adds', () => { expect(1 + 1).toBe(2); });
test('concatenates', () => { expect('a' + 'b').toBe('ab'); });
test('sorts', () => { expect([3, 1, 2].sort()).toEqual([1, 2, 3]); });
