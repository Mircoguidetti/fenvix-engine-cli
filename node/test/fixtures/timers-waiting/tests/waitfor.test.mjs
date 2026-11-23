// Shape of codex-multi-auth b9886168 test/api-model-runtime.test.ts:320 ("does not hold native model discovery open
// while probes run"), the first test of that file to time out under --det: the code under test leaves an unrelated
// long timer pending (its fetch's `AbortSignal.timeout(15000)`), and the test waits with `vi.waitFor`, whose polling
// runs on the runner's own (real) timers. The 401/403 flip of the same file fails only after this one (see REPORT.md).
import { test, expect, vi } from 'vitest';

test('vi.waitFor while an unrelated long timer is pending', async () => {
  AbortSignal.timeout(15000);
  let ready = false;
  setImmediate(() => { ready = true; });
  await vi.waitFor(() => expect(ready).toBe(true));
});

test('the next test of the file (the 401/403 flip runs after the timed-out one)', () => {
  expect(503).toBe(503);
});
