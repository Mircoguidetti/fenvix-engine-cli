# detjs Level 0 (Node / TypeScript): measurement report (`node-final`)

Generated 2026-11-17 17:41 UTC with detjs 0.1.0 on GitHub Actions (ubuntu-latest) ([run](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44050766953)). Per repository: 10 baseline runs interleaved with 10 `--det` runs. Baseline = the realistic configuration: random order with a different seed per run where the runner supports it (Vitest `--sequence.shuffle --sequence.seed=N`; Jest `--randomize --seed=N`, Jest >= 29.2 only) and two parallel workers (`--maxWorkers=2`). `--det` = fixed order (files sorted by path, tests in declaration order), one worker, files in sequence, all Level 0 controls. Then, for every test unstable in the baseline, `--det --det-seed=1..20` with 10/10 confirmation of the seed that makes it fail. Labels: MEASURED (by this harness), DECLARED (with source), UNKNOWN; NOISY = shared host.

Verifier: Rust verifier through the Python binding (detpy 0.1.0).

## Main metric

**Baseline-unstable tests made reproducible: 129/421 = 30.6%** (MEASURED). A test counts as reproduced when some `--det-seed` (or the fixed `--det` order) makes it fail 10 times out of 10 AND some `--det` configuration makes it pass.

| pool | repositories | tests | unstable in baseline | reproduced | % | never fail under --det | always fail under --det | fail sometimes under --det |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| documented flaky | 16 | 43250 | 192 | 51 | 26.6% | 99 | 1 | 41 |
| popular (HEAD) | 25 | 41986 | 229 | 78 | 34.1% | 63 | 36 | 52 |
| total | 41 | 85236 | 421 | 129 | 30.6% | 162 | 37 | 93 |

**Seeds explored before the reproducing seed was found** (reproduced tests, MEASURED): 1: 70, 2-5: 21, 6-10: 27, 11-20: 11; median 1.

**First diverging event between the fingerprints of a passing and a failing `--det` run** (MEASURED): `outcome-only` 98, `time` 13, `random` 12, `fs` 5.

## Documented flaky tests (MEASURED)

Documented = tests in the files changed by the flaky-test fix of the Hashemi et al. dataset, or matching the file/test named by the GitHub issue (issue titles often name no test: then nothing matches).

| documented flaky tests found in the measured projects | flaky in our baseline | reproduced |
|---:|---:|---:|
| 31 | 0 | 0 |

## Causes of baseline-flaky tests not reproduced under `--det` (MEASURED, keyword heuristics)

Classes: `concurrency/event-order` (async ordering, timers racing real I/O, timeouts), `external` (network, processes, files, environment), `l0-gap` (a source Level 0 controls still differs, or shared state Level 0 should reset), `unknown`. Evidence per test in `<repo>.causes.json`.

| pool | concurrency/event-order | external | l0-gap | unknown |
|---|---:|---:|---:|---:|
| flaky | 25 | 1 | 40 | 75 |
| popular | 5 | 37 | 12 | 97 |
| total | 30 | 38 | 52 | 172 |

* `concurrency/event-order`: apollo-client-flaky `pLink.ts::SharedHttpTest::passes all arguments to multiple fetch body including extensions` (test source uses settimeout); apollo-client-flaky `h-http/__tests__/batchHttpLink.ts::SharedHttpTest::unsubscribes without calling subscriber` (test source uses settimeout); apollo-client-flaky `eQuery.test.tsx::useQuery Hook::Error handling::should render data and errors with refetch` (test source uses async , await , waitfor; also fetch()
* `external`: apollo-client-flaky `rc/link/batch-http/__tests__/batchHttpLink.ts::SharedHttpTest::allows uri to be a function` (test source uses fetch(); recharts `test/component/Text.spec.tsx::scaleToFit=true::scales text to fit the width` (test source uses https://); tanstack-table `.cache/e2e-artifacts-96sIYJ/first/tests/e2e/failure.spec.ts::<file>` (exception unknown / diverging event -)
* `l0-gap`: apollo-client-flaky `st.tsx::useQuery Hook::Refetching::refetchWritePolicy::should support explicit "overwrite"` (diverging event `time`: a controlled source still differs between runs); apollo-client-flaky `useSubscription.test.tsx::useSubscription Hook::only warns once using `onSubscriptionData`` (diverging event `time`: a controlled source still differs between runs); happy-dom-flaky `::Object.keys()::Returns an array of storage's own enumerable string-keyed property names.` (shared state not reset by Level 0: mockimplementation, spyon)
* `unknown`: apollo-client-flaky `ests__/batchHttpLink.ts::SharedHttpTest::adds fetchOptions to the request from the context` (no marker in the source, exception or fingerprint); apollo-client-flaky `hHttpLink.ts::SharedHttpTest::adds headers w/ preserved case to the request from the setup` (no marker in the source, exception or fingerprint); apollo-client-flaky `pLink.ts::SharedHttpTest::prioritizes context headers w/ preserved case over setup headers` (no marker in the source, exception or fingerprint)

## Tests broken by Level 0

A test is *broken by `--det`* when it fails in at least one fixed-order `--det` run but in at most one baseline run (and less often than under `--det`). **48 tests** (MEASURED), of which 41 fail in every `--det` run.

Cause: `fixed-order` = the test also fails under `--det` with every Level 0 control disabled (only the fixed order and serial execution remain): an order/isolation dependency hidden by the random parallel baseline, not a Level 0 control; otherwise the controls whose `--det-disable` makes it pass; `unexplained` = none does.

| cause &#124; exception | tests | examples |
|---|---:|---|
| `time &#124; Error` | 15 | react-admin-flaky: packages/ra-ui-materialui/src/detail/ShowGuesser.spec.tsx::<ShowGuesser />::should log the guessed Show view based on the fetched record: Error: Unknown dataProvider function: getMa<br>react-admin-flaky: packages/ra-ui-materialui/src/list/filter/FilterButton.spec.tsx::<FilterButton />::filter selection menu::should close the filter menu on removing all filters: Error: thrown: "Excee |
| `time &#124; AssertionError` | 6 | assistant-ui-flaky: lib/repo-sandbox.test.ts::createRepoSandbox::cannot reach the host filesystem outside the mounted root: AssertionError: expected 'bash: Maximum call stack size exceeded' to contain<br>assistant-ui-flaky: lib/repo-sandbox.test.ts::createRepoSandbox::falls back to an empty mount before the tree is generated: AssertionError: expected 'bash: Maximum call stack size exceeded' to be '' / |
| `time+timers &#124; Error` | 5 | apollo-client-flaky: src/link/persisted-queries/__tests__/persisted-queries.test.ts::failure path::clears the cache when receiving NotSupported error (error code): Error: thrown: "Exceeded timeout of <br>apollo-client-flaky: src/link/persisted-queries/__tests__/persisted-queries.test.ts::failure path::clears the cache when receiving NotSupported error (error message): Error: thrown: "Exceeded timeout  |
| `net &#124; Error` | 5 | react-admin-flaky: examples/crm/src/providers/commons/getContactAvatar.spec.ts::should return gravatar URL for anthony@marmelab.com: Error: expect(received).toBe(expected) // Object.is equality (first<br>unstorage: test/drivers/github.test.ts::drivers: github::can check for a file presence: Error: [unstorage] [github] Failed to fetch git tree (first diverging source: -) |
| `time+timers &#124; AssertionError` | 4 | assistant-ui-flaky: lib/xulux/fetch-sandbox.test.ts::fetchSandboxResource::keeps the deadline over the response body by default: AssertionError: expected false to be true // Object.is equality (first <br>assistant-ui-flaky: lib/xulux/fetch-sandbox.test.ts::fetchSandboxResource::rejects at the budget rather than waiting out the backoff: AssertionError: expected "vi.fn()" to be called 1 times, but got 3 |
| `fixed-order (fails without --det too) &#124; unknown` | 4 | tanstack-table: .cache/e2e-artifacts-LvUzfv/first/tests/e2e/failure.spec.ts::<file>: Playwright Test did not expect test() to be called here. (first diverging source: -)<br>tanstack-table: .cache/e2e-artifacts-LvUzfv/second/tests/e2e/failure.spec.ts::<file>: Playwright Test did not expect test() to be called here. (first diverging source: -) |
| `seeds+time+timers+fs+net &#124; AssertionError` | 3 | excalidraw-flaky: packages/excalidraw/tests/search.test.tsx::search::should match frame names: AssertionError: expected undefined to be 3 // Object.is equality (first diverging source: time)<br>excalidraw-flaky: packages/excalidraw/tests/search.test.tsx::search::should match text and cycle through matches on Enter: AssertionError: expected undefined to be 2 // Object.is equality (first diver |
| `unexplained &#124; Error` | 2 | react-admin-flaky: examples/crm/src/providers/commons/getCompanyAvatar.spec.ts::should return favicon URL if website url exist: Error: expect(received).toStrictEqual(expected) // deep equality (first <br>react-admin-flaky: examples/crm/src/providers/commons/getContactAvatar.spec.ts::should return favicon URL if gravatar does not exist: Error: expect(received).toBe(expected) // Object.is equality (firs |
| `time+timers &#124; TypeError` | 2 | vercel-flaky: packages/cli/test/unit/util/events.test.ts::printEvents()::does not signal alias assignment when the stream errors: TypeError: Invalid state: ReadableStream is locked (first diverging so<br>unstorage: test/drivers/mongodb.test.ts::drivers: mongodb::should have different dates when an entry was updated: TypeError: The "callback" argument must be of type function. Received type number (100 |
| `time &#124; ApolloError` | 1 | apollo-client-flaky: src/__tests__/optimistic.ts::optimistic mutation results::optimistic updates using `update`::will insert a single itemAsync to the beginning: ApolloError: expect(received).toBe(ex |
| `unexplained &#124; AssertionError` | 1 | assistant-ui-flaky: lib/repo-sandbox.test.ts::createRepoSandbox::serves reads from the generated source tree: AssertionError: expected 'bash: Maximum call stack size exceeded' to be '# assistant-ui' / |

## Timing

Quiet timing pass: 9 repositories, one per GitHub-hosted runner, 3 serial runs without `--det` (one worker, runner's default order) vs 3 `--det` runs, interleaved; median per repository. Machine: cpus=4, platform=linux, RUNNER_NAME=GitHub Actions 1000009537, RUNNER_OS=Linux, RUNNER_ARCH=X64, RUNNER_ENVIRONMENT=github-hosted, ImageOS=ubuntu26, ImageVersion=20261111.196.1, cpu_model=AMD EPYC 7763 64-Core Processor. **DECLARED-NOISY** (shared virtual machines).

**Slowdown of `--det` (MEASURED, DECLARED-NOISY): median 3.1%**, min -13.8%, max 76.1%.

| repo | runner | tests | serial s (median) | --det s (median) | slowdown % |
|---|---|---:|---:|---:|---:|
| apollo-client-flaky | jest 29.7.0 | 2632 | 150.07 | 264.23 | 76.1 |
| assistant-ui-flaky | vitest 4.1.11 | 702 | 33.21 | 34.25 | 3.1 |
| cheerio | vitest 5.1.0 | 846 | 4.84 | 5.15 | 6.6 |
| date-fns | vitest 5.0.1 | 222 | 3.95 | 4.34 | 9.9 |
| dom-testing-library | jest 29.7.0 | 664 | 8.78 | 7.57 | -13.8 |
| growi-flaky | vitest 3.2.6 | 5959 | 213.83 | 215.40 | 0.7 |
| h3 | vitest 5.0.5 | 3386 | 23.91 | 24.33 | 1.8 |
| happy-dom-flaky | vitest 4.1.8 | 8096 | 187.58 | 192.89 | 2.8 |
| immer | vitest 3.2.6 | 4192 | 9.33 | 10.01 | 7.3 |

* Round timings, serial `--det` vs the random parallel baseline: median 61.5% — **NOT COMPARABLE** (different parallelism and order).

## Other metrics (MEASURED)

* tests unstable under `--det` (fixed order, 10 runs): 39; unstable in the baseline and stable under `--det`: 387
* stable in both modes but with a different majority outcome: 94
* identical fingerprint in every fixed-order `--det` run (covered by Level 0): 79661 (98.8%); not covered: 988 (`time` 807, `fs` 91, `entropy` 87, `random` 2, `beyond-trace` 1)

## Per repository (MEASURED)

| repo | pool | pinned at | node | runner | random baseline | tests | unstable | reproduced | seeds explored | broken by det | not covered | documented present / flaky / reproduced |
|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| [apollo-client-flaky](https://github.com/apollographql/apollo-client) | flaky | [cde7e247f1](https://github.com/apollographql/apollo-client/commit/cde7e247f145d759d67d8596ec98b9aaafda04da) ([doc](https://github.com/apollographql/apollo-client/issues/11782)) | node v20.20.2 | jest 29.7.0 | yes | 2632 | 24 | 3 | 3 (budget) | 6 | 237 | 26 / 0 / 0 |
| [assistant-ui-flaky](https://github.com/assistant-ui/assistant-ui) | flaky | [b8c5e68298](https://github.com/assistant-ui/assistant-ui/commit/b8c5e68298a81ff6c9c99b504bc57479c5dd4f05) ([doc](https://github.com/assistant-ui/assistant-ui/issues/7007)) | node v22.23.5 | vitest 4.1.11 | yes | 702 | 0 | 0 | 0 | 8 | 1 | 0 / 0 / 0 |
| [growi-flaky](https://github.com/growilabs/growi) | flaky | [3fc185a4e6](https://github.com/growilabs/growi/commit/3fc185a4e696d614d08f3e9cfd4040226f9d772f) ([doc](https://github.com/growilabs/growi/issues/12252)) | node v22.23.5 | vitest 3.2.6 | yes | 5959 | 2 | 0 | 1 (budget) | 0 | 11 | 1 / 0 / 0 |
| [happy-dom-flaky](https://github.com/capricorn86/happy-dom) | flaky | [875ef5c647](https://github.com/capricorn86/happy-dom/commit/875ef5c647b336cc933c82426c9d780a5aab84f9) ([doc](https://github.com/capricorn86/happy-dom/issues/2526)) | node v20.20.2 | vitest 4.1.8 | yes | 8106 | 21 | 2 | 2 (budget) | 2 | 25 | 0 / 0 / 0 |
| [mermaid-flaky](https://github.com/mermaid-js/mermaid) | flaky | [89818e854e](https://github.com/mermaid-js/mermaid/commit/89818e854e6e517726e49e6625b3a1ccd62e1935) ([doc](https://github.com/mermaid-js/mermaid/issues/7729)) | node v22.23.5 | vitest 3.2.4 | yes | 4015 | 17 | 6 | 2 (budget) | 0 | 4 | 0 / 0 / 0 |
| [msw-flaky](https://github.com/mswjs/msw) | flaky | [d3113a9556](https://github.com/mswjs/msw/commit/d3113a95564292c4d180b3e1f50b8f3a536d26e0) ([doc](https://github.com/mswjs/msw/issues/2557)) | node v20.20.2 | vitest 3.1.4 | yes | 254 | 1 | 1 | 2 | 0 | 2 | 0 / 0 / 0 |
| [nuxt-flaky](https://github.com/nuxt/nuxt) | flaky | [0344123b3c](https://github.com/nuxt/nuxt/commit/0344123b3c2c46c6f591c42696eef8ffc6504947) ([doc](https://github.com/nuxt/nuxt/issues/32557)) | node v22.23.5 | vitest 3.2.4 | yes | 696 | 1 | 1 | 1 | 0 | 15 | 0 / 0 / 0 |
| [quasar-flaky](https://github.com/quasarframework/quasar) | flaky | [6d531cf190](https://github.com/quasarframework/quasar/commit/6d531cf190aa6c2fa0c5990ecbe1349bc801c718) ([doc](https://github.com/quasarframework/quasar/issues/18333)) | node v22.23.5 | vitest 4.1.8 | yes | 1041 | 17 | 15 | 3 (budget) | 0 | 2 | 0 / 0 / 0 |
| [query-flaky](https://github.com/TanStack/query) | flaky | [e3aca98134](https://github.com/TanStack/query/commit/e3aca9813440b950947d8d10e48cc90cad568db3) ([doc](https://github.com/TanStack/query/issues/8163)) | node v22.23.5 | vitest 2.0.5 | yes | 479 | 0 | 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| [react-admin-flaky](https://github.com/marmelab/react-admin) | flaky | [3ff5554b10](https://github.com/marmelab/react-admin/commit/3ff5554b10342fc8467348d35143c805a2ff81e5) ([doc](https://github.com/marmelab/react-admin/issues/10301)) | node v20.20.2 | jest 29.5.0 | yes | 2087 | 27 | 11 | 2 (budget) | 5 | 52 | 0 / 0 / 0 |
| [svelte-flaky](https://github.com/sveltejs/svelte) | flaky | [7a2435471c](https://github.com/sveltejs/svelte/commit/7a2435471c96c43d6f00144cdb5889772703d786) ([doc](https://github.com/sveltejs/svelte/issues/17110)) | node v22.23.5 | vitest 2.1.9 | yes | 6969 | 20 | 8 | 15 (budget) | 0 | 88 | 0 / 0 / 0 |
| [tiptap-flaky](https://github.com/ueberdosis/tiptap) | flaky | [1ecf81434f](https://github.com/ueberdosis/tiptap/commit/1ecf81434f0fa7a40c1b7815719836e82a77d4b9) ([doc](https://github.com/ueberdosis/tiptap/issues/8080)) | node v22.23.5 | vitest 4.1.2 | yes | 1420 | 1 | 1 | 1 | 0 | 0 | 0 / 0 / 0 |
| [zod-flaky](https://github.com/colinhacks/zod) | flaky | [ead9fcb310](https://github.com/colinhacks/zod/commit/ead9fcb310bf65a70427f92ca76545efe954037e) ([doc](https://github.com/colinhacks/zod/issues/6359)) | node v22.23.5 | vitest 4.1.5 | yes | 3817 | 1 | 1 | 2 | 0 | 1 | 4 / 0 / 0 |
| [react-testing-library-flaky](https://github.com/testing-library/react-testing-library) | flaky | [1c931a6c03](https://github.com/testing-library/react-testing-library/commit/1c931a6c03091d725eccee7767d9ec696d5d33c6) ([doc](https://github.com/testing-library/react-testing-library/issues/1419)) | node v18.20.8 | jest 29.7.0 | yes | 250 | 2 | 2 | 7 | 0 | 0 | 0 / 0 / 0 |
| [vercel-flaky](https://github.com/vercel/vercel) | flaky | [17d9ebaf8e](https://github.com/vercel/vercel/commit/17d9ebaf8e9b335d550dea1a243743a74edc772e) ([doc](https://github.com/vercel/vercel/issues/17501)) | node v22.23.5 | vitest 2.0.3 | yes | 3212 | 1 | 0 | 4 (budget) | 1 | 32 | 0 / 0 / 0 |
| [excalidraw-flaky](https://github.com/excalidraw/excalidraw) | flaky | [5cf547650b](https://github.com/excalidraw/excalidraw/commit/5cf547650b700b35507e83773695098150b810d2) ([doc](https://github.com/excalidraw/excalidraw/issues/11713)) | node v18.20.8 | vitest 3.0.6 | yes | 1611 | 57 | 0 | 1 (budget) | 14 | 461 | 0 / 0 / 0 |
| [cheerio](https://github.com/cheeriojs/cheerio) | popular | [d013f2b6f7](https://github.com/cheeriojs/cheerio/commit/d013f2b6f735b324aa66fba88804d6edc37d8136) | node v22.23.5 | vitest 5.1.0 | yes | 846 | 0 | 0 | 0 | 0 | 0 |  |
| [date-fns](https://github.com/date-fns/date-fns) | popular | [a9739fb3e5](https://github.com/date-fns/date-fns/commit/a9739fb3e5384a810e90d7376446f6d84ecc5029) | node v22.23.5 | vitest 5.0.1 | yes | 222 | 0 | 0 | 0 | 0 | 0 |  |
| [dom-testing-library](https://github.com/testing-library/dom-testing-library) | popular | [6049cc0bc7](https://github.com/testing-library/dom-testing-library/commit/6049cc0bc7cf2201625c476c95fa6299d0e2fa8b) | node v18.20.8 | jest 29.7.0 | yes | 664 | 4 | 4 | 1 | 0 | 0 |  |
| [h3](https://github.com/unjs/h3) | popular | [2f29b87561](https://github.com/unjs/h3/commit/2f29b875617e8daf39d25118f7474fd4c24fbfe1) | node v20.20.2 | vitest 5.0.5 | yes | 3386 | 5 | 5 | 2 | 0 | 7 |  |
| [immer](https://github.com/immerjs/immer) | popular | [784c86bb23](https://github.com/immerjs/immer/commit/784c86bb234e805566481c9425fcb2a3897e8bcc) | node v22.23.5 | vitest 3.2.6 | yes | 4192 | 1 | 1 | 1 | 0 | 0 |  |
| [immutable-js](https://github.com/immutable-js/immutable-js) | popular | [a6c7429e09](https://github.com/immutable-js/immutable-js/commit/a6c7429e096bf9900a591626ca009b6a8baa860e) | node v22.23.5 | jest 29.7.0 | yes | 899 | 0 | 0 | 0 | 0 | 0 |  |
| [jotai](https://github.com/pmndrs/jotai) | popular | [9de9377d10](https://github.com/pmndrs/jotai/commit/9de9377d10a5ac01388764b89458e2d7091d29d4) | node v22.23.5 | vitest 5.1.0 | yes | 412 | 1 | 1 | 1 | 0 | 0 |  |
| [luxon](https://github.com/moment/luxon) | popular | [f427515a38](https://github.com/moment/luxon/commit/f427515a38f6a671f8de663e6bcc040ed81f114e) | node v18.20.8 | jest 29.4.3 | no (Jest < 29.2) | 1204 | 0 | 0 | 0 | 0 | 0 |  |
| [mobx](https://github.com/mobxjs/mobx) | popular | [016642e064](https://github.com/mobxjs/mobx/commit/016642e064bcf0d8cafb4d765dcb8b5994393c83) | node v22.23.5 | jest 30.3.0 | yes | 1027 | 6 | 6 | 4 | 0 | 0 |  |
| [pinia](https://github.com/vuejs/pinia) | popular | [4817135a25](https://github.com/vuejs/pinia/commit/4817135a25431172d363bd928476db7cdbf875c4) | node v22.23.5 | vitest 4.1.11 | yes | 276 | 0 | 0 | 0 | 0 | 0 |  |
| [preact-signals](https://github.com/preactjs/signals) | popular | [395fd7ebd4](https://github.com/preactjs/signals/commit/395fd7ebd440cbc4d1ced05b4b498b08f3ed33d0) | node v22.23.5 | vitest 4.0.17 | yes | 1099 | 0 | 0 | 0 | 0 | 0 |  |
| [react-redux](https://github.com/reduxjs/react-redux) | popular | [8e54f5b9db](https://github.com/reduxjs/react-redux/commit/8e54f5b9dbbdcc972c120ad3ce3c1c57fc2e89fd) | node v22.23.5 | vitest 4.1.11 | yes | 140 | 0 | 0 | 0 | 1 | 0 |  |
| [recharts](https://github.com/recharts/recharts) | popular | [f27aeba629](https://github.com/recharts/recharts/commit/f27aeba6293c66c0e8b602e4351faf6d2de42875) | node v22.23.5 | vitest 4.1.11 | yes | 9348 | 67 | 0 | 1 (budget) | 0 | 0 |  |
| [redux](https://github.com/reduxjs/redux) | popular | [39bd88011b](https://github.com/reduxjs/redux/commit/39bd88011b0c7c6f67cec8230ada49fac20ad989) | node v22.23.5 | vitest 4.0.5 | yes | 82 | 0 | 0 | 0 | 0 | 0 |  |
| [tanstack-form](https://github.com/TanStack/form) | popular | [eba4084b70](https://github.com/TanStack/form/commit/eba4084b706699e4c4d8cfc39f895f722ea9cdfc) | node v22.23.5 | vitest 5.0.5 | yes | 474 | 2 | 2 | 3 | 0 | 0 |  |
| [tanstack-table](https://github.com/TanStack/table) | popular | [564a459b74](https://github.com/TanStack/table/commit/564a459b74834c77631e0d6fdba7661383bbc1b4) | node v22.23.5 | vitest 5.1.0 | yes | 1856 | 36 | 0 | 7 (budget) | 4 | 0 |  |
| [ufo](https://github.com/unjs/ufo) | popular | [f06c800d0c](https://github.com/unjs/ufo/commit/f06c800d0c59f2a4a1b9ba65eb6cb61a84419be6) | node v22.23.5 | vitest 4.1.5 | yes | 487 | 0 | 0 | 0 | 0 | 0 |  |
| [unstorage](https://github.com/unjs/unstorage) | popular | [5781aae96f](https://github.com/unjs/unstorage/commit/5781aae96f7f34820a99e447df29ceead97e9210) | node v22.23.5 | vitest 5.0.5 | yes | 885 | 1 | 1 | 2 | 5 | 41 |  |
| [user-event](https://github.com/testing-library/user-event) | popular | [930fb1ee1a](https://github.com/testing-library/user-event/commit/930fb1ee1a6ccb2a492bfd3f790b60619af9d872) | node v18.20.8 | jest 28.1.3 | no (Jest < 29.2) | 569 | 0 | 0 | 0 | 2 | 0 |  |
| [valibot](https://github.com/fabian-hiller/valibot) | popular | [d72f76fcf7](https://github.com/fabian-hiller/valibot/commit/d72f76fcf70ccfa0a5ca341b80da1d440ac60b11) | node v22.23.5 | vitest 4.1.8 | yes | 3220 | 51 | 51 | 11 | 0 | 0 |  |
| [vue-core](https://github.com/vuejs/core) | popular | [2e2f7c6bef](https://github.com/vuejs/core/commit/2e2f7c6bef54a85a3ce8db768b11c5562385b65d) | node v20.20.2 | vitest 4.1.11 | yes | 3168 | 6 | 4 | 20 | 0 | 0 |  |
| [vueuse](https://github.com/vueuse/vueuse) | popular | [bed1dce149](https://github.com/vueuse/vueuse/commit/bed1dce149ce6760fec13d4798c047f51a563180) | node v22.23.5 | vitest 5.1.0 | yes | 1023 | 0 | 0 | 0 | 0 | 4 |  |
| [xstate](https://github.com/statelyai/xstate) | popular | [8e53990c2f](https://github.com/statelyai/xstate/commit/8e53990c2f9318d2d649b8af1a3c96af970d9bf2) | node v22.23.5 | vitest 3.2.7 | yes | 5043 | 6 | 0 | 1 (budget) | 0 | 5 |  |
| [yaml](https://github.com/eemeli/yaml) | popular | [528ef30d6d](https://github.com/eemeli/yaml/commit/528ef30d6ded4bd9f2c3521b670eb2b29d503c5c) | node v20.20.2 | vitest 4.1.11 | yes | 988 | 1 | 1 | 1 | 0 | 0 |  |
| [yup](https://github.com/jquense/yup) | popular | [ff31eee8a2](https://github.com/jquense/yup/commit/ff31eee8a2b10c938bb3a22544d9e33957a8cf01) | node v22.23.5 | vitest 3.2.4 | yes | 476 | 42 | 2 | 20 | 0 | 0 |  |

## Discarded candidates

| repo | pool | reason | detail |
|---|---|---|---|
| freecodecamp-flaky | flaky | unsupported | jest 24.9.0 (detjs needs jest-circus, the default runner since Jest 27) |
| react-flaky | flaky | install-failed | error at process.processTicksAndRejections (node:internal/process/task_queues:77:11) npm error A complete log of this run can be found in: /home/runner/.npm/_logs/2026-11-16T21_18_51_146Z-debug-0.log  |
| bootstrap-flaky | flaky | install-failed | error at process.processTicksAndRejections (node:internal/process/task_queues:77:11) npm error A complete log of this run can be found in: /home/runner/.npm/_logs/2026-11-16T20_45_40_925Z-debug-0.log  |
| electron-flaky | flaky | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| node-flaky | flaky | no-runner | no package.json at the repository root |
| material-ui-flaky | flaky | baseline-broken | 811/811 tests fail in the first baseline run |
| storybook-flaky | flaky | install-failed | s git://github.com/CharlesMangwa/simple-markdown.git Directory: /tmp/work/src/storybook-flaky Output: fatal: unable to connect to github.com: github.com[0: 20.169.109.160]: errno=Connection timed out  |
| atom-flaky | flaky | install-failed | 000Z-debug-0.log,/home/runner/.npm/_logs/2026-11-16T21_12_41_000Z-debug-1.log,/home/runner/.npm/_logs/2026-11-16T21_12_41_000Z-debug-2.log,/home/runner/.npm/_logs/2026-11-16T21_12_41_000Z-debug-3.log  |
| jquery-flaky | flaky | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| chart.js-flaky | flaky | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| element-flaky | flaky | install-failed | ss_ldflags=" "--libsass_library=" gyp ERR! cwd /tmp/work/src/element-flaky/node_modules/node-sass gyp ERR! node -v v18.20.8 gyp ERR! node-gyp -v v3.6.2 gyp ERR! not ok Build failed with error code: 1  |
| lodash-flaky | flaky | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| moment-flaky | flaky | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| meteor-flaky | flaky | no-runner | no package.json at the repository root |
| yarn-flaky | flaky | unsupported | jest 22.4.3 (detjs needs jest-circus, the default runner since Jest 27) |
| vite-flaky | flaky | unsupported | vitest 0.29.7 (detjs needs >= 1.4) |
| jest-flaky | flaky | baseline-broken | events:517:28) at maybeClose (node:internal/child_process:1098:16) at Socket.<anonymous> (node:internal/child_process:450:11) at Socket.emit (node:events:517:28) at Pipe.<anonymous> (node:net:350:12)  |
| react-router-flaky | flaky | baseline-broken | e (node:internal/modules/cjs/loader:1289:19) at require (node:internal/modules/helpers:182:18) at Object.<anonymous> (/tmp/work/src/react-router-flaky/packages/create-react-router/jest.config.js:3:6)  |
| dayjs-flaky | flaky | unsupported | jest 22.4.4 (detjs needs jest-circus, the default runner since Jest 27) |
| tldraw-flaky | flaky | too-slow | first baseline run took 209s |
| trpc-flaky | flaky | unsupported | vitest 0.28.5 (detjs needs >= 1.4) |
| pnpm-flaky | flaky | baseline-broken | st-worker/build/processChild.js:189:7) at process.emit (node:events:519:28) at emit (node:internal/child_process:949:14) at process.processTicksAndRejections (node:internal/process/task_queues:90:21)  |
| typescript-eslint-flaky | flaky | too-slow | first baseline run took 410s |
| sentry-javascript-flaky | flaky | too-slow | first baseline run took 438s |
| posthog-js-flaky | flaky | too-few-tests | m/build/ScriptTransformer.js:726:19) Seed: 1000 Test Suites: 8 failed, 8 total Tests: 0 total Snapshots: 0 total Time: 0.705 s Test results written to: ../../../../runs/posthog-js-flaky/normal_0.json  |
| webdriverio-flaky | flaky | too-slow | first baseline run took 293s |
| vitest-flaky | flaky | too-slow | first baseline run took 616s |
| material-ui-flaky | flaky | baseline-broken | 811/811 tests fail in the first baseline run |
| next.js-flaky | flaky | baseline-broken | 2119/2119 tests fail in the first baseline run |
| sequelize-flaky | flaky | install-failed | .node --module_name=odbc --module_path=/tmp/work/src/sequelize-flaky/node_modules/odbc/lib/bindings/napi-v6 --napi_version=9 --node_abi_napi=napi --napi_build_version=6 --node_napi_label=napi-v6' (1)  |
| astro-flaky | flaky | unsupported | vitest 0.20.3 (detjs needs >= 1.4) |
| vuetify-flaky | flaky | baseline-broken | 88/88 tests fail in the first baseline run |
| ionic-framework-flaky | flaky | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| react-three-fiber-flaky | flaky | too-few-tests | ex.js:72:44) Seed: 1000 Test Suites: 15 failed, 15 total Tests: 0 total Snapshots: 0 total Time: 0.299 s Ran all test suites. Test results written to: ../../runs/react-three-fiber-flaky/normal_0.json  |
| pixijs-flaky | flaky | unsupported | jest 26.6.3 (detjs needs jest-circus, the default runner since Jest 27) |
| n8n-flaky | flaky | baseline-broken | 466/583 tests fail in the first baseline run |
| medusa-flaky | flaky | too-slow | first baseline run took 476s |
| nx-flaky | flaky | too-slow | first baseline run took 198s |
| primitives-flaky | flaky | install-failed | [94m➤[39m YN0013: │ No packages were cached - 1728 packages had to be fetched ::endgroup:: [94m➤[39m [90mYN0000[39m: └ Completed in 43s 698ms [91m➤[39m YN0000: Failed with errors in 43s 932ms  |
| ariakit-flaky | flaky | too-slow | first baseline run took 528s |
| mui-x-flaky | flaky | too-slow | first baseline run took 445s |
| blueprint-flaky | flaky | too-few-tests | ld/index.js:1505:14) Seed: 1000 Test Suites: 11 failed, 11 total Tests: 0 total Snapshots: 0 total Time: 0.543 s Ran all test suites. Test results written to: ../../runs/blueprint-flaky/normal_0.json  |
| eui-flaky | flaky | unsupported | jest 24.9.0 (detjs needs jest-circus, the default runner since Jest 27) |
| grafana-flaky | flaky | too-slow | first baseline run took 362s |
| outline-flaky | flaky | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| nocodb-flaky | flaky | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| appsmith-flaky | flaky | no-runner | no package.json at the repository root |
| twenty-flaky | flaky | install-failed | 2.cjs:175:1995) at async wC.execute (/tmp/work/src/twenty-flaky/.yarn/releases/yarn-4.9.2.cjs:462:18086) [94m➤[39m [90mYN0000[39m: └ Completed [91m➤[39m YN0000: · Failed with errors in 34s 55ms  |
| documenso-flaky | flaky | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| leaflet-flaky | flaky | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| openlayers-flaky | flaky | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| maplibre-gl-js-flaky | flaky | install-failed | RR! node -v v18.20.8 npm error gyp ERR! node-gyp -v v8.4.1 npm error gyp ERR! not ok npm error A complete log of this run can be found in: /home/runner/.npm/_logs/2026-11-16T23_42_37_717Z-debug-0.log  |
| undici-flaky | flaky | too-few-tests | scope.test.js Seed: 1000 Test Suites: 7 passed, 7 total Tests: 11 passed, 11 total Snapshots: 0 total Time: 2.986 s Ran all test suites. Test results written to: ../../runs/undici-flaky/normal_0.json  |
| got-flaky | flaky | install-failed | mp/work/src/got-flaky npm error command failed npm error command sh -c npm run build npm error A complete log of this run can be found in: /home/runner/.npm/_logs/2026-11-16T23_43_36_002Z-debug-0.log  |
| fastify-flaky | flaky | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| mongoose-flaky | flaky | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| node-redis-flaky | flaky | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| element-web-flaky | flaky | baseline-broken | 224/335 tests fail in the first baseline run |
| opencti-flaky | flaky | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| okou-flaky | flaky | no-runner | no package.json at the repository root |
| kibana-flaky | flaky | too-slow | first baseline run took 388s |
| theia-flaky | flaky | install-failed | ative-keymap npm error gyp ERR! $npm_package_version 2.5.0 npm error gyp ERR! not ok npm error A complete log of this run can be found in: /home/runner/.npm/_logs/2026-11-17T01_03_10_789Z-debug-0.log  |
| opencove-flaky | flaky | too-slow | first baseline run took 737s |
| open-mercato-flaky | flaky | too-slow | first baseline run took 221s |
| workers-sdk-flaky | flaky | too-slow | first baseline run took 191s |
| langfuse-flaky | flaky | baseline-broken | USER: [ 'Invalid input: expected string, received undefined' ], CLICKHOUSE_PASSWORD: [ 'Invalid input: expected string, received undefined' ] } [31m[1mError[22m: Invalid environment variables[39m  |
| qwen-code-flaky | flaky | too-slow | first baseline run took 900s |
| tunarr-flaky | flaky | baseline-broken | t _createServer (file:///tmp/work/src/tunarr-flaky/node_modules/.pnpm/vite@7.1.10_@types+node@22.10.7_jiti@2.7.0_tsx@4.20.6_yaml@2.8.2/node_modules/vite/dist/node/chunks/dep-B0GuR2De.js:27937:67) ] }  |
| hapi-flaky | flaky | unsupported | bun project |
| vinext-flaky | flaky | too-slow | first baseline run took 900s |
| podman-desktop-flaky | flaky | install-failed | an-desktop-flaky". Expected version: >=24.0.0 Got: v22.23.5 This is happening because the package's manifest has an engines.node field specified. To fix this issue, install the required Node version.  |
| librechat-flaky | flaky | unsupported | bun project |
| yosemite-crew-flaky | flaky | baseline-broken | 1424/1424 tests fail in the first baseline run |
| app-flaky | flaky | install-failed | 20.19.4","npm":"10.8.2"} npm error notsup Actual: {"npm":"10.8.2","node":"v20.20.2"} npm error A complete log of this run can be found in: /home/runner/.npm/_logs/2026-11-17T01_36_15_989Z-debug-0.log  |
| puppeteer-flaky | flaky | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| zod | popular | duplicate | repository already in the flaky pool |
| dayjs | popular | unsupported | jest 22.4.4 (detjs needs jest-circus, the default runner since Jest 27) |
| zustand | popular | install-failed | version of pnpm requires at least Node.js v22.13 The current version of Node.js is v18.20.8 Visit https://r.pnpm.io/comp to see the list of past pnpm versions with respective Node.js version support.  |
| valtio | popular | install-failed | version of pnpm requires at least Node.js v22.13 The current version of Node.js is v18.20.8 Visit https://r.pnpm.io/comp to see the list of past pnpm versions with respective Node.js version support.  |
| redux-toolkit | popular | baseline-broken | 100/115 tests fail in the first baseline run |
| react-hook-form | popular | baseline-broken | 167/167 tests fail in the first baseline run |
| formik | popular | unsupported | jest 25.5.4 (detjs needs jest-circus, the default runner since Jest 27) |
| hono | popular | baseline-broken | ono/node_modules/.pnpm/vitest@5.0.1_@types+node@24.13.6_@vitest+browser-preview@5.0.1_@vitest+coverage-v8@5.0._68c5305fb163089a9626a63dab7b643c/node_modules/vitest/dist/chunks/cac.fSuRXrAx.js:2346:2)  |
| happy-dom | popular | duplicate | repository already in the flaky pool |
| commander | popular | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| rxjs | popular | baseline-broken | 511/751 tests fail in the first baseline run |
| floating-ui | popular | baseline-broken | 67/76 tests fail in the first baseline run |
| stylelint | popular | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| fastify-ajv-compiler | popular | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| ky | popular | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| superjson | popular | unsupported | vitest 0.34.6 (detjs needs >= 1.4) |
| effect | popular | too-slow | first baseline run took 310s |
| kysely | popular | no-runner | neither vitest nor jest resolvable from the repository root or a package with a runner config |
| pw-slate | playwright | no-runner | olvable: t evalTypeScript (node:internal/process/execution:291:3) at node:internal/main/eval_string:74:3 { code: 'MODULE_NOT_FOUND', requireStack: [ '/tmp/work/src/pw-slate/x.js' ] } Node.js v22.23.5  |
| pw-react-router | playwright | too-slow | first baseline run took 900s |
| pw-floating-ui | playwright | browser-install-failed | Failed to install browsers Error: ERROR: Playwright does not support chromium on ubuntu26.04-x64  |
| pw-lexical | playwright | baseline-broken | <anonymous> (file:///tmp/work/src/pw-lexical/node_modules/.pnpm/vite@8.3.3_@types+node@26.4.1_esbuild@0.28.2_jiti@2.7.0_terser@5.51.2_tsx@4.23.15_yaml@2.9.0/node_modules/vite/dist/node/cli.js:811:18)  |
| pw-material-ui | playwright | baseline-broken | tring') as typeof LZStringModule; / ^ 10 / 11 / const test = base.extend<TestFixture>({}); 12 / at Object.<anonymous> (/tmp/work/src/pw-material-ui/test/e2e-website/demo-docs-production.spec.ts:9:18)  |
| pw-tanstack-router | playwright | baseline-broken | /work/src/pw-tanstack-router/examples/react/start-basic-react-query/node_modules/@tanstack/react-start/dist/esm/plugin/vite.js' [WebServer] } [WebServer] [ELIFECYCLE] Command failed with exit code 1.  |
| pw-astro | playwright | too-slow | first baseline run took 501s |
| pw-sveltekit | playwright | baseline-broken | uild/analyse.js:153:34) [WebServer] at async MessagePort.<anonymous> (file:///tmp/work/src/pw-sveltekit/packages/kit/src/utils/fork.js:21:22) [WebServer] [ELIFECYCLE] Command failed with exit code 1.  |
| pw-qwik | playwright | baseline-broken | /ssg-snapshot.e2e.ts Error: Cannot find module '/tmp/work/src/pw-qwik/node_modules/@qwik.dev/core/dist/optimizer.mjs' imported from /tmp/work/src/pw-qwik/e2e/qwik-e2e/tests/server-only-modules.e2e.ts  |
| pw-tldraw | playwright | baseline-broken | 0 test outcomes (exit 1): Error: http://localhost:5420 is already used, make sure that nothing is running on the port/url or set reuseExistingServer:true in config.webServer.  |
| pw-ariakit | playwright | baseline-broken | eview --port 4321 [WebServer] 04:29:44 [ERROR] [@astrojs/cloudflare] No build output found. Run `astro build` before running `astro preview`. [WebServer] [ELIFECYCLE] Command failed with exit code 1.  |
| pw-swr | playwright | browser-install-failed | Failed to install browsers Error: ERROR: Playwright does not support chromium on ubuntu26.04-x64  |
| pw-remix | playwright | baseline-broken | .ts:38:41 Error: No tests found (node:4924) ExperimentalWarning: SQLite is an experimental feature and might change at any time (Use `node --trace-warnings ...` to show where the warning was created)  |
| pw-base-ui | playwright | baseline-broken | wright@1.65.0/node_modules/playwright/lib/cli/testActions.js:44:18) at _Command.<anonymous> (/tmp/work/src/pw-base-ui/node_modules/.pnpm/playwright@1.65.0/node_modules/playwright/lib/program.js:55:7)  |
| pw-ark | playwright | unsupported | bun project |
| pw-nuxt-ui | playwright | no-runner | no playwright.config.* found |
| pw-vercel-ai | playwright | too-few-tests | 2 test outcomes (exit 0): Running 2 tests using 1 worker ·· 2 passed (4.0s) [WebServer] $ next  |
| pw-zag | playwright | baseline-broken | 0 test outcomes (exit 1): Error: http://localhost:3000 is already used, make sure that nothing is running on the port/url or set reuseExistingServer:true in config.webServer.  |
| matrix-js-sdk-flaky | flaky | det-no-trace | TestInternal (/tmp/work/src/matrix-js-sdk-flaky/node_modules/jest-runner/build/runTest.js:367:16) at async runTest (/tmp/work/src/matrix-js-sdk-flaky/node_modules/jest-runner/build/runTest.js:444:34)  |

## Playwright end-to-end suites (measured, not built on)

3 projects at HEAD, Chromium only, `--retries=0`. Baseline: the project's own parallel workers. `--det`: `--workers=1` and the Level 0 controls inside the Playwright worker processes (seeds, clock, timers, fs order, closed network for the test process; `node/src/register.js`). The browser and the web servers are separate processes and are not controlled; Playwright has no test shuffle, so `--det-seed` only changes the seeds. No per-test fingerprints (no hook into the Playwright runner).

**Baseline-unstable browser tests: 1 of 125 (0.8%)** (MEASURED); of these, never fail under `--det`: 1, fail sometimes under `--det`: 0, always fail under `--det`: 0, reproduced 0. Tests broken by `--det`: 0.

| repo | runner | tests | unstable baseline | unstable --det | became stable | broken by --det |
|---|---|---:|---:|---:|---:|---:|
| [pw-msw](https://github.com/mswjs/msw) | playwright 1.63.0 | 52 | 1 | 0 | 1 | 0 |
| [pw-solid-start](https://github.com/solidjs/solid-start) | playwright 1.62.0 | 47 | 0 | 0 | 0 | 0 |
| [pw-starlight](https://github.com/withastro/starlight) | playwright 1.61.1 | 26 | 0 | 0 | 0 | 0 |

Share of the baseline-unstable tests of this round that are browser tests: 1/422 = 0.2% (MEASURED, not weighted by project size).

## Notes

* Flaky pool: the dataset of Hashemi, Tahir, Rasheed, 'An Empirical Study of Flaky Tests in JavaScript' (ICSME 2022, Zenodo 10.5281/zenodo.6673741) is the public dataset of JavaScript flaky tests used first: each project is pinned at the parent of a commit that fixes a flaky test. It covers only 18 projects, most of which do not run their suites with Jest or Vitest (Node core, Atom, Electron, Meteor, jQuery/QUnit, Karma suites), so it cannot supply 25 projects; the pool is completed with popular projects that have GitHub issues documenting flaky Jest/Vitest tests, each pinned at the last commit before the issue was opened.
* The JS-TOD (order-dependent Jest tests) and environmental-flakiness replication packages were not fetched.
* Only GitHub-hosted runners were used; numbers labelled NOISY come from shared virtual machines.
