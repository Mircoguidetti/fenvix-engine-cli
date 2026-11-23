import { test, expect } from 'vitest';

// Fails only when FENVIX_FIXTURE_FAIL=1 (tests/test_runner_node.py: the exit status of a failing suite).
test('fails on demand', () => { expect(process.env.FENVIX_FIXTURE_FAIL === '1' ? 'failed' : 'ok').toBe('ok'); });
