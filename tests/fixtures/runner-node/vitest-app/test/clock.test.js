import { it, expect } from 'vitest';

it('reads the clock', () => { expect(new Date().getUTCFullYear()).toBeGreaterThanOrEqual(2025); });
it('draws a random number', () => { const x = Math.random(); expect(x >= 0 && x < 1).toBe(true); });
it.skip('is skipped', () => { throw new Error('never runs'); });
it.todo('is todo');
