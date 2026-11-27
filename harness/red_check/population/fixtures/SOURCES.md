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

Revision 2 (PREREG_R2.md R2.4), written the same way (2026-11-27), each a shape rev 1's patterns miss:
- `pytest-q.log`: `pytest -q` final line without the `=` banner (`1 failed, 5 passed, 2 warnings in 0.31s`), with a
  private-mode escape (`\x1b[?25l`) on the progress line.
- `turbo-vitest.log`: Vitest output inside a turborepo task (`web:test: ` prefix).
- `pnpm-r-jest.log`: Jest output under `pnpm -r test` (`packages/core test: ` prefix).
- `yarn-foreach-node-test.log`: `node --test` output under `yarn workspaces foreach` (`[api]: ` prefix).
- `pytest-q-pass.log`, `turbo-pass.log`: the passing counterparts (no runner).
