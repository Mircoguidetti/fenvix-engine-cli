# `fenvix repro` on the Node Block 1 flaky set, every test (MEASURED, CI run 44785725528)

Engine ba8f08000dbda4b2e1c30851c1e1bf3e0792d81c. Rows: `run_shared.py` (in-process `fenvix repro` per test; full-suite search runs shared per repository shard), aggregated by `report_final.py` (definitions in its docstring). GitHub-hosted ubuntu-latest runners, Node 22.

| repo | runner | tests in set | attempted | REPRODUCED | cause named | separate replay 10/10 | stable id used | not collected | not-found | other | median s/test | causes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| apollo-client-flaky | jest 29.7.0 | 24 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| dom-testing-library | jest 29.7.0 | 4 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| excalidraw-flaky | vitest 3.0.6 | 67 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| growi-flaky | vitest 3.2.6 | 2 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| h3 | vitest 5.0.5 | 5 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| happy-dom-flaky | vitest 4.1.8 | 21 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| immer | vitest 3.2.6 | 1 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| jotai | vitest 5.1.0 | 1 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| mermaid-flaky | vitest 3.2.4 | 17 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| mobx | jest 30.3.0 | 6 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| msw-flaky | vitest 3.1.4 | 1 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| nuxt-flaky | vitest 3.2.4 | 1 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| quasar-flaky | vitest 4.1.8 | 17 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| react-admin-flaky | jest 29.5.0 | 27 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| react-testing-library-flaky | jest 29.7.0 | 2 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| recharts | vitest 4.1.11 | 82 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| svelte-flaky | vitest 2.1.9 | 20 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| tanstack-form | vitest 5.0.5 | 2 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| tiptap-flaky | vitest 4.1.2 | 1 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| unstorage | vitest 5.0.5 | 1 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| valibot | vitest 4.1.8 | 51 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| vercel-flaky | vitest 2.0.3 | 1 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| vue-core | vitest 4.1.11 | 6 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| xstate | vitest 3.2.7 | 7 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| yaml | vitest 4.1.11 | 1 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| yup | vitest 3.2.4 | 42 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| zod-flaky | vitest 4.1.5 | 1 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |
| matrix-js-sdk-flaky (apart) | jest 29.7.0 | 138 | 0 (not prepared) | 0 | 0 | 0/0 | 0 | 0 | 0 | 0 | - |  |

**Totals, set (Vitest/Jest, without matrix-js-sdk-flaky): 411 tests.** Attempted 0/411 = 0.0 %; REPRODUCED 0/0 of attempted; cause named 0/0; separate replay 10/10 with the bundle's fingerprint 0/0; reproduced through a stable id 0 (ids with run-dependent values; 0 distinct tests); not collected 0; not reproduced under the fixed order and seeds 1..20 (`not-found`) 0; other verdicts 0; not attempted 411; time per test median None s, mean None s. Verdicts: .

**matrix-js-sdk-flaky (apart):** 138 tests, attempted 0, REPRODUCED 0, not-found 0, other 0; verdicts .

## Per test

| repo | test | status | cause | bundle replays failed | separate replay failed | stable id | wall s |
|---|---|---|---|---|---|---|---:|
