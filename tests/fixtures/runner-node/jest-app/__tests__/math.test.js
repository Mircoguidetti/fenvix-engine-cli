test('adds', () => { expect(1 + 1).toBe(2); });
test('a real failure (fails alone too)', () => { expect(0.1 + 0.2).toBe(0.3); });
test('uses the clock and randomness', () => { expect(Date.now()).toBeGreaterThan(0); expect(Math.random()).toBeLessThan(1); });
