// node:test for test files under `detjs node-test --det` (import): see facade.js.
import { createRequire } from 'node:module';

const w = createRequire(import.meta.url)('./facade.cjs');
export default w;
export const {
  after, afterEach, assert, before, beforeEach, describe, it, mock, only, run, skip, snapshot, suite, test, todo,
} = w;
