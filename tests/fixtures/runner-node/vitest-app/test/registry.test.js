import { describe, it, expect } from 'vitest';
import { add, register, registry } from '../src/registry.js';

describe('registry', () => {
  it('adds numbers', () => { expect(add(2, 3)).toBe(5); });
  it('registers a plugin', () => { expect(register('plugin')).toBe(1); });
  // Order-dependent: passes alone, fails after "registers a plugin" (which leaves an entry behind).
  it('starts empty', () => { expect(registry).toEqual([]); });
  it('adds numbers', () => { expect(add(-1, 1)).toBe(0); }); // same name twice: detjs id gets " #2"
});
