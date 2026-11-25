# Runner fixtures (PREREG 2.5)

Written by the session (2026-11-25) from each runner's default summary output, wrapped as GitHub Actions job logs
(UTF-8 byte-order mark, `YYYY-MM-DDTHH:MM:SS.fffffffZ ` prefix on every line): not copied from a third-party log.

- `vitest.log`: Vitest 2.x default reporter summary (` Test Files  1 failed | 3 passed (4)`), with the ANSI colour
  escapes Vitest writes when colours are on, so the fixture exercises both timestamp and ANSI stripping.
- `jest.log`: Jest default reporter summary (`Test Suites:` / `Tests:` lines, `--ci`).
- `node-test.log`: `node --test` spec reporter summary (`ℹ fail 2`; the TAP reporter's `# fail 2` is the same rule).
- `pytest.log`: pytest's final summary line (`==== 1 failed, 5 passed in 0.12s ====`).
- `*-pass.log`: one negative per pattern: the same runner's passing summary (count 0 or no `failed`).
- `ambiguous.log`: a jest and a pytest failing summary in one log.
