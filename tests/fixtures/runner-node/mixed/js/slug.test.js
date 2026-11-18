import { it, expect } from 'vitest';
import { slug } from './slug.js';
it('slugs', () => { expect(slug('Hello World')).toBe('hello-world'); });
it('slugs empty', () => { expect(slug('')).toBe(''); });
