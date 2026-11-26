// P3 timers P1 (founder decision A, 2026-11-26): the runner's own polling (vi.waitFor, expect.poll) runs on Vitest's
// safe timers, which are real. While a test waits on them with an unrelated long timer pending, the virtual clock
// must not jump to that timer (and past the runner's 5000 ms deadline). Shape of ironcurtain / codex-multi-auth /
// agentic-qe / drydock L1 cases (harness/p3_flips/CLASSIFY.md, cause "timers progression (virtual) (L1)").
import { test, expect, vi } from 'vitest';

test('vi.waitFor while a test-started 15 s timer is pending', async () => {
  const t = setTimeout(() => {}, 15000);
  let ready = false;
  setImmediate(() => { ready = true; });
  await vi.waitFor(() => expect(ready).toBe(true));
  clearTimeout(t);
});

test('expect.poll while a test-started 15 s timer is pending', async () => {
  const t = setTimeout(() => {}, 15000);
  let ready = false;
  setImmediate(() => { ready = true; });
  await expect.poll(() => ready).toBe(true);
  clearTimeout(t);
});
