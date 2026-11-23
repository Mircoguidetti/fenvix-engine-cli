import { test, expect } from 'vitest';
import crypto from 'node:crypto';

// Reads real OS entropy when FENVIX_FIXTURE_ENTROPY=1 (tests/test_runner_node.py: verify names it NOT PROVEN or DIVERGED, reason entropy), else skipped.
test.skipIf(process.env.FENVIX_FIXTURE_ENTROPY !== '1')('reads OS entropy', () => {
  expect(crypto.randomBytes(16).length).toBe(16);
});
