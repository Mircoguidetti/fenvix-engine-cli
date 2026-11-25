# P2 baseline (Phase A)

Printed by `harness/p2/table.py baseline harness/p2/data/baseline` from `results.jsonl` (every row carries its `cmd`). Seconds. Median of 3 rounds; `cold` = round 1 (engine state and node_modules caches cold for the engine rows). E = par + verify of the same round and w; best = min over w=2,4. allowance = min(1.3, speedup/2).

## Bounds (median of 3 rounds; cold round in brackets)

| repo | PS | PP best (w) | speedup | allowance | E best (w) | par / verify at E's w | E/PP | PS/E | meets | meets (par only) |
|---|---|---|---|---|---|---|---|---|---|---|
| nestjs-pino | 21.26 [25.12] | 8.01 (w4) [8.01] | 2.65 | 1.30 | 10.70 (w4) [10.30] | 10.53 / 0.14 [10.17 / 0.13] | 1.34 [1.29] | 1.99 [2.44] | no [yes] | no [yes] |
| agentsys | 15.13 [19.50] | 6.88 (w4) [6.56] | 2.20 | 1.10 | 18.59 (w4) [25.26] | 18.13 / 0.46 [24.85 / 0.41] | 2.70 [3.85] | 0.81 [0.77] | no [no] | no [no] |
| alakajam | 36.97 [41.45] | 9.67 (w4) [8.46] | 3.82 | 1.30 | 54.60 (w2) [81.21] | 54.46 / 0.22 [100.25 / 0.25] | 5.65 [9.60] | 0.68 [0.51] | no [no] | no [no] |
| agentlang | 84.35 [91.99] | 28.67 (w4) [31.13] | 2.94 | 1.30 | 90.37 (w2) [90.37] | 89.98 / 0.34 [89.98 / 0.39] | 3.15 [2.90] | 0.93 [1.02] | no [no] | no [no] |
| yalc | 92.28 [114.07] | 33.62 (w4) [39.20] | 2.74 | 1.30 | 63.75 (w4) [117.39] | 63.50 / 0.24 [117.20 / 0.19] | 1.90 [2.99] | 1.45 [0.97] | no [no] | no [no] |
| ironcurtain | 251.07 [257.05] | 80.68 (w4) [80.68] | 3.11 | 1.30 | 95.25 (w4) [184.26] | 93.55 / 1.70 [208.60 / 1.75] | 1.18 [2.28] | 2.64 [1.40] | yes [no] | yes [no] |
| codex-multi-auth | 403.44 [427.87] | 111.53 (w4) [114.27] | 3.62 | 1.30 | 182.92 (w4) [320.80] | 180.07 / 2.85 [317.82 / 2.98] | 1.64 [2.81] | 2.21 [1.33] | no [no] | no [no] |
| drydock | 564.85 [571.77] | 162.78 (w4) [170.43] | 3.47 | 1.30 | 235.14 (w4) [277.77] | 233.99 / 1.13 [276.64 / 1.13] | 1.44 [1.63] | 2.40 [2.06] | no [no] | no [no] |
| lerna-lite | 616.93 [616.98] | 283.32 (w4) [283.32] | 2.18 | 1.09 | 606.25 (w2) [923.31] | 606.11 / 0.14 [1138.54 / 0.19] | 2.14 [3.26] | 1.02 [0.67] | no [no] | no [no] |

Repositories meeting both bounds: **1 of 9** on the medians, 1 of 9 on the cold round.

## Per worker count (median [cold])

| repo | PP w2 | PP w4 | E w2 (par+verify) | E w4 (par+verify) | rounds | noisy rows | engine_commit | machine |
|---|---|---|---|---|---|---|---|---|
| nestjs-pino | 12.08 [12.12] | 8.01 [8.01] | 15.36 (15.13+0.14) [15.36] | 10.70 (10.53+0.14) [10.30] | 1,2,3 | 0 | 6e79a62c79aae391b3e96c25bfca29ead64cc02f | Intel(R) Xeon(R) Processor @ 2.10GHz / vm / ded5bcf2 |
| agentsys | 8.53 [8.26] | 6.88 [6.56] | 22.88 (22.43+0.45) [28.71] | 18.59 (18.13+0.46) [25.26] | 1,2,3 | 0 | 6e79a62c79aae391b3e96c25bfca29ead64cc02f | Intel(R) Xeon(R) Processor @ 2.10GHz / vm / ded5bcf2 |
| alakajam | 13.36 [13.36] | 9.67 [8.46] | 54.60 (54.46+0.22) [100.50] | 62.67 (62.47+0.20) [81.21] | 1,2,3 | 0 | 6e79a62c79aae391b3e96c25bfca29ead64cc02f | Intel(R) Xeon(R) Processor @ 2.10GHz / vm / ded5bcf2 |
| agentlang | 41.28 [43.83] | 28.67 [31.13] | 90.37 (89.98+0.34) [90.37] | 91.63 (91.22+0.37) [94.84] | 1,2,3 | 0 | 6e79a62c79aae391b3e96c25bfca29ead64cc02f | Intel(R) Xeon(R) Processor @ 2.10GHz / vm / ded5bcf2 |
| yalc | 48.66 [57.84] | 33.62 [39.20] | 68.16 (67.90+0.26) [132.39] | 63.75 (63.50+0.24) [117.39] | 1,2,3 | 0 | 6e79a62c79aae391b3e96c25bfca29ead64cc02f | Intel(R) Xeon(R) Processor @ 2.10GHz / vm / ded5bcf2 |
| ironcurtain | 130.52 [130.52] | 80.68 [80.68] | 184.26 (182.26+1.88) [184.26] | 95.25 (93.55+1.70) [210.35] | 1,2,3 | 0 | 6e79a62c79aae391b3e96c25bfca29ead64cc02f | Intel(R) Xeon(R) Processor @ 2.10GHz / vm / ded5bcf2 |
| codex-multi-auth | 206.55 [210.40] | 111.53 [114.27] | 296.91 (293.64+2.95) [422.14] | 182.92 (180.07+2.85) [320.80] | 1,2,3 | 0 | 6e79a62c79aae391b3e96c25bfca29ead64cc02f | Intel(R) Xeon(R) Processor @ 2.10GHz / vm / ded5bcf2 |
| drydock | 292.91 [296.98] | 162.78 [170.43] | 311.80 (310.44+1.36) [373.55] | 235.14 (233.99+1.13) [277.77] | 1,2,3 | 0 | 6e79a62c79aae391b3e96c25bfca29ead64cc02f | Intel(R) Xeon(R) Processor @ 2.10GHz / vm / ded5bcf2 |
| lerna-lite | 307.73 [307.73] | 283.32 [283.32] | 606.25 (606.11+0.14) [1138.73] | 609.73 (609.60+0.13) [923.31] | 1,2,3 | 0 | 6e79a62c79aae391b3e96c25bfca29ead64cc02f | Intel(R) Xeon(R) Processor @ 2.10GHz / vm / ded5bcf2 |

## Outcome counts (median over rounds; spread = max - min) and exit codes

**nestjs-pino**

| run | counts (median, spread) | exit codes |
|---|---|---|
| par w2 | passed 269 (±0) | [0] |
| par w4 | passed 269 (±0) | [0] |
| plain w1 | passed 269 (±0) | [0] |
| plain_par w2 | passed 269 (±0) | [0] |
| plain_par w4 | passed 269 (±0) | [0] |
| serial w1 | passed 269 (±0) | [0] |
| verify w2 | | [1] |
| verify w4 | | [1] |

VARIABLE tests (outcome varied over the 3 rounds of one kind; excluded from correctness rule 3): 0

**agentsys**

| run | counts (median, spread) | exit codes |
|---|---|---|
| par w2 | failed 1 (±0), passed 2183 (±0), skipped 40 (±0) | [1] |
| par w4 | failed 1 (±0), passed 2183 (±0), skipped 40 (±0) | [1] |
| plain w1 | failed 1 (±0), passed 2183 (±0), skipped 40 (±0) | [1] |
| plain_par w2 | failed 1 (±0), passed 2183 (±0), skipped 40 (±0) | [1] |
| plain_par w4 | failed 1 (±0), passed 2183 (±0), skipped 40 (±0) | [1] |
| serial w1 | failed 1 (±0), passed 2183 (±0), skipped 40 (±0) | [1] |
| verify w2 | | [1] |
| verify w4 | | [1] |

VARIABLE tests (outcome varied over the 3 rounds of one kind; excluded from correctness rule 3): 0

**alakajam**

| run | counts (median, spread) | exit codes |
|---|---|---|
| par w2 | failed 112 (±15), passed 105 (±15), skipped 4 (±0) | [1] |
| par w4 | failed 114 (±4), passed 103 (±4), skipped 4 (±0) | [1] |
| plain w1 | passed 217 (±0), skipped 4 (±0) | [0] |
| plain_par w2 | failed 0 (±26), passed 80 (±2), skipped 141 (±24) | [1] |
| plain_par w4 | passed 78 (±20), skipped 143 (±20) | [1] |
| serial w1 | failed 109 (±10), passed 108 (±10), skipped 4 (±0) | [1] |
| verify w2 | | [1] |
| verify w4 | | [1] |

VARIABLE tests (outcome varied over the 3 rounds of one kind; excluded from correctness rule 3): 18
- `server/core/security.spec.ts::Security::add user right::should create a role on a post` (serial, par w2, par w4)
- `server/core/security.spec.ts::Security::add user right::should not duplicate an existing role` (serial, par w2, par w4)
- `server/core/security.spec.ts::Security::add user right::should upgrade an existing role to a higher permission, but never downgrade it` (serial, par w2, par w4)
- `server/core/security.spec.ts::Security::comment permissions::should only let the comment author edit it` (serial, par w2, par w4)
- `server/core/security.spec.ts::Security::event permissions::should let anyone read events but only mods edit them, and only admins once closed` (serial, par w2, par w4)
- `server/core/security.spec.ts::Security::post permissions::should always refuse when no model is given` (par w2, par w4)
- `server/core/security.spec.ts::Security::post permissions::should require user roles to be loaded` (serial, par w2)
- `server/post/comment/comment.service.spec.ts::Comment service::anonymous comments::should create anonymous comments on entries allowing them` (serial, par w2)
- `server/post/comment/comment.service.spec.ts::Comment service::anonymous comments::should not create anonymous comments for users disallowed to` (serial, par w2)
- `server/post/comment/comment.service.spec.ts::Comment service::anonymous comments::should not create anonymous comments on entries disallowing them` (serial, par w2)
- `server/post/comment/comment.service.spec.ts::Comment service::anonymous comments::should not create anonymous comments on posts` (serial, par w2)
- `server/post/comment/comment.service.spec.ts::Comment service::anonymous comments::should only find own anonymous comments of the requested node` (serial, par w2)
- `server/post/comment/comment.service.spec.ts::Comment service::anonymous comments::should tell that a regular comment is not an own anonymous comment` (serial, par w2)
- `server/post/comment/comment.service.spec.ts::Comment service::anonymous comments::should tell that an anonymous comment belongs to its author` (serial, par w2)
- `server/post/comment/comment.service.spec.ts::Comment service::delete comment::should delete a post comment` (serial, par w2)
- `server/post/comment/comment.service.spec.ts::Comment service::delete comment::should delete an anonymous entry comment along with its author link` (serial, par w2)
- `server/post/comment/comment.service.spec.ts::Comment service::edit comment::should only allow the comment author to edit it` (serial, par w2)
- `server/user/user.service.spec.ts::User service::approved user::should not approve users without entries` (par w2, par w4)

**agentlang**

| run | counts (median, spread) | exit codes |
|---|---|---|
| par w2 | failed 2 (±0), passed 437 (±0) | [1] |
| par w4 | failed 2 (±0), passed 437 (±0) | [1] |
| plain w1 | passed 439 (±0) | [0] |
| plain_par w2 | failed 53 (±33), passed 386 (±33) | [1] |
| plain_par w4 | failed 27 (±36), passed 412 (±36) | [1] |
| serial w1 | failed 2 (±0), passed 437 (±0) | [1] |
| verify w2 | | [1] |
| verify w4 | | [1] |

VARIABLE tests (outcome varied over the 3 rounds of one kind; excluded from correctness rule 3): 0

**yalc**

| run | counts (median, spread) | exit codes |
|---|---|---|
| par w2 | failed 3 (±0), passed 1472 (±0), skipped 8 (±0) | [1] |
| par w4 | failed 3 (±0), passed 1472 (±0), skipped 8 (±0) | [1] |
| plain w1 | failed 3 (±1), passed 1472 (±1), skipped 8 (±0) | [1] |
| plain_par w2 | failed 3 (±1), passed 1472 (±1), skipped 8 (±0) | [1] |
| plain_par w4 | failed 9 (±12), passed 1466 (±12), skipped 8 (±0) | [1] |
| serial w1 | failed 3 (±0), passed 1472 (±0), skipped 8 (±0) | [1] |
| verify w2 | | [1] |
| verify w4 | | [1] |

VARIABLE tests (outcome varied over the 3 rounds of one kind; excluded from correctness rule 3): 1
- `src/__tests__/capability-adapters.test.ts::icp-company-search adapters::crustdata adapter calls autocomplete_filter BEFORE company_search_db` (plain)

**ironcurtain**

| run | counts (median, spread) | exit codes |
|---|---|---|
| par w2 | failed 384 (±1), passed 6280 (±1), skipped 369 (±0) | [1] |
| par w4 | failed 384 (±1), passed 6280 (±1), skipped 369 (±0) | [1] |
| plain w1 | failed 19 (±0), passed 6901 (±0), skipped 113 (±0) | [1] |
| plain_par w2 | failed 19 (±0), passed 6901 (±0), skipped 113 (±0) | [1] |
| plain_par w4 | failed 19 (±0), passed 6901 (±0), skipped 113 (±0) | [1] |
| serial w1 | failed 36 (±3), passed 6874 (±3), skipped 123 (±0) | [1] |
| verify w2 | | [1] |
| verify w4 | | [1] |

VARIABLE tests (outcome varied over the 3 rounds of one kind; excluded from correctness rule 3): 3
- `test/docker-workload/apple-vm-egress-relay.test.ts@@main::purpose-built Apple VM egress relay::bounds package lifetime without preempting a reused registry connection in one profile` (serial, par w2, par w4)
- `test/docker/mitm-domain-model.test.ts@@main::MITM dynamic domain and tunnel model::closes an unfinished proxy request on 'stop' ('decline')` (serial)
- `test/docker/mitm-domain-model.test.ts@@main::MITM dynamic domain and tunnel model::closes an unfinished proxy request on 'stop' ('hold')` (serial)

**codex-multi-auth**

| run | counts (median, spread) | exit codes |
|---|---|---|
| par w2 | failed 69 (±2), passed 8581 (±2), skipped 12 (±0) | [1] |
| par w4 | failed 67 (±6), passed 8583 (±6), skipped 12 (±0) | [1] |
| plain w1 | failed 7 (±1), passed 8643 (±1), skipped 12 (±0) | [1] |
| plain_par w2 | failed 6 (±0), passed 8644 (±0), skipped 12 (±0) | [1] |
| plain_par w4 | failed 6 (±0), passed 8644 (±0), skipped 12 (±0) | [1] |
| serial w1 | failed 76 (±7), passed 8574 (±7), skipped 12 (±0) | [1] |
| verify w2 | | [1] |
| verify w4 | | [1] |

VARIABLE tests (outcome varied over the 3 rounds of one kind; excluded from correctness rule 3): 31
- `test/app-bind.test.ts::Codex app runtime rotation bind::validates legacy router timestamps and command identity before stopping` (par w2)
- `test/automatic-api-checks.test.ts::keeps the next tick anchored when a slow run rejects: false` (par w2, par w4)
- `test/automatic-api-checks.test.ts::keeps the next tick anchored when a slow run rejects: true` (par w2, par w4)
- `test/automatic-api-checks.test.ts::uses persisted claim deadlines despite slow claim I/O and later routes` (par w2)
- `test/codex-bin-wrapper.test.ts::codex bin wrapper::force-stops an app helper that ignores SIGTERM (#647)` (par w2, par w4)
- `test/codex-bin-wrapper.test.ts::codex bin wrapper::injects rotation helper args before a `--` on the resume path (#673)` (serial, par w2, par w4)
- `test/codex-bin-wrapper.test.ts::codex bin wrapper::keeps a native openai rollout visible while routing its resumed requests through rotation` (par w2, par w4)
- `test/codex-bin-wrapper.test.ts::codex bin wrapper::keeps both sessions' state when two canonical TUI sessions overlap` (par w4)
- `test/codex-bin-wrapper.test.ts::codex bin wrapper::resolves the resume provider from a bounded prefix of a large rollout` (serial)
- `test/codex-bin-wrapper.test.ts::codex bin wrapper::stress: metadata stays bounded across many launch/exit cycles` (plain)
- `test/codex-bin-wrapper.test.ts::codex bin wrapper::uses the canonical Codex home for `fork` runtime routing (#647)` (par w2, par w4)
- `test/codex-bin-wrapper.test.ts::codex bin wrapper::uses the canonical Codex home for `resume` runtime routing (#647)` (par w4)
- `test/model-inventory-cancellation.test.ts::does not publish an inventory temp file after cancellation during its write` (par w4)
- `test/model-inventory-cancellation.test.ts::retries exhausted preparation errors shortly without repeating claimed routes` (par w4)
- `test/persisted-api-capabilities.test.ts::caps paid probes across independent routes at four` (serial)
- `test/persisted-api-capabilities.test.ts::does not overwrite unrelated evidence updated at the same timestamp` (serial)
- `test/persisted-api-capabilities.test.ts::keeps only fresh matching retained evidence after write then read failure: fresh` (serial)
- `test/persisted-api-capabilities.test.ts::preserves unreadable EACCES cache without paid probes` (serial)
- `test/persisted-api-capabilities.test.ts::preserves unreadable corrupt cache without paid probes` (serial)
- `test/persisted-api-capabilities.test.ts::returns completed evidence after ENOSPC and avoids immediate duplicate probes` (serial)
- `test/persisted-api-capabilities.test.ts::returns documentation without paid probes when another lease times out` (serial)
- `test/refresh-lease.test.ts::RefreshLeaseCoordinator::does not reclaim an expired lock, even after owner exit: 15041` (plain)
- `test/refresh-lease.test.ts::RefreshLeaseCoordinator::does not reclaim an expired lock, even after owner exit: 27816` (plain)
- `test/refresh-lease.test.ts::RefreshLeaseCoordinator::does not reclaim an expired lock, even after owner exit: 5769` (plain)
- `test/runtime-policy-cache.test.ts::runtime policy cache::never caches a store read raced by a concurrent rewrite` (par w2, par w4)
- `test/runtime-policy-cache.test.ts::runtime policy cache::re-reads a same-size rewrite that pins mtime back` (serial, par w4)
- `test/runtime-policy-cache.test.ts::runtime policy cache::re-resolves when a project marker appears in a previously rootless dir` (serial, par w2, par w4)
- `test/runtime-rotation-proxy.test.ts::catalog review concurrency and backoff::caps a catalog Retry-After of Fri, 25 Dec 2026 14:19:56 GMT at fifteen minutes` (plain)
- `test/runtime-rotation-proxy.test.ts::catalog review concurrency and backoff::caps a catalog Retry-After of Fri, 25 Dec 2026 14:55:03 GMT at fifteen minutes` (plain)
- `test/runtime-rotation-proxy.test.ts::catalog review concurrency and backoff::caps a catalog Retry-After of Fri, 25 Dec 2026 15:23:40 GMT at fifteen minutes` (plain)
- `test/runtime-rotation-proxy.test.ts::keeps session affinity when the client disconnects mid-stream` (serial)

**drydock**

| run | counts (median, spread) | exit codes |
|---|---|---|
| par w2 | failed 82 (±3), passed 21495 (±3), skipped 1 (±0) | [1] |
| par w4 | failed 83 (±5), passed 21494 (±5), skipped 1 (±0) | [1] |
| plain w1 | passed 21577 (±0), skipped 1 (±0) | [0] |
| plain_par w2 | passed 21577 (±0), skipped 1 (±0) | [0] |
| plain_par w4 | passed 21577 (±0), skipped 1 (±0) | [0] |
| serial w1 | failed 82 (±3), passed 21495 (±3), skipped 1 (±0) | [1] |
| verify w2 | | [1] |
| verify w4 | | [1] |

VARIABLE tests (outcome varied over the 3 rounds of one kind; excluded from correctness rule 3): 93
- `agent/edge-registration-ownership.test.ts::edge registration ownership with real component lifecycles::a disconnected initializer cannot replace the new owner (cleanup throws: true)` (serial, par w4)
- `agent/edge-registration-ownership.test.ts::edge registration ownership with real component lifecycles::a retired remote trigger initializer cannot publish over the replacement` (serial, par w2, par w4)
- `agent/edge-registration-ownership.test.ts::edge registration ownership with real component lifecycles::a retired synthetic trigger initializer cannot publish over the replacement` (par w4)
- `api/api.test.ts::API Router::should mount all sub-routers` (serial, par w2, par w4)
- `api/index.test.ts::API Index::real Express: /api/v1/* traffic is never reached by the removed-alias tombstone mounted at /api` (par w2)
- `api/index.test.ts::API Index::real Express: GET /api/auth/methods is no longer registered and is answered by the removed-alias tombstone` (par w2, par w4)
- `api/index.test.ts::API Index::real Express: UI paths return a JSON 404 explaining DD_SERVER_UI_ENABLED=false, while /api/v1 and /health are unaffected` (par w2, par w4)
- `api/index.test.ts::API Index::real Express: a non-GET request to a GET-only /api/v1/* route falls through the tombstone to a 404, not a false 410` (par w2, par w4)
- `api/index.test.ts::API Index::real Express: a non-whitelisted /api/* request returns 410 JSON (not 404, not SPA HTML) when DD_COMPAT_WUDCARD is disabled` (par w4)
- `api/index.test.ts::API Index::real Express: sendUiDisabledResponse lets unmatched API, health, and metrics paths fall through instead of returning the UI-disabled body` (par w2, par w4)
- `api/index.test.ts::API Index::real Express: the legacy-alias usage tracker still records a hit for a request the tombstone answers with 410` (par w2, par w4)
- `api/index.test.ts::API Index::real Express: whitelisted wud-card endpoints still serve via the compat router while a non-whitelisted /api route still 410s when DD_COMPAT_WUDCARD is enabled` (par w4)
- `api/log-stream.test.ts::api/log-stream::createSystemLogStreamGateway::resets consecutive-drop counter when buffer drains below cap` (par w4)
- `configuration/index.fuzz.test.ts::configuration/index fuzz tests::get handles unusual env var values without crashing (with seed=-1160648669)` (plain)
- `configuration/index.fuzz.test.ts::configuration/index fuzz tests::get handles unusual env var values without crashing (with seed=1249447308)` (plain)
- `configuration/index.fuzz.test.ts::configuration/index fuzz tests::get handles unusual env var values without crashing (with seed=1962412639)` (plain)
- `configuration/index.fuzz.test.ts::configuration/index fuzz tests::get never throws on arbitrary property paths and env objects (with seed=-1156792128)` (plain)
- `configuration/index.fuzz.test.ts::configuration/index fuzz tests::get never throws on arbitrary property paths and env objects (with seed=-981787410)` (plain)
- `configuration/index.fuzz.test.ts::configuration/index fuzz tests::get never throws on arbitrary property paths and env objects (with seed=1872761938)` (plain)
- `configuration/index.fuzz.test.ts::configuration/index fuzz tests::get never throws on arbitrary property paths with empty env (with seed=-1183671370)` (plain)
- `configuration/index.fuzz.test.ts::configuration/index fuzz tests::get never throws on arbitrary property paths with empty env (with seed=-140790555)` (plain)
- `configuration/index.fuzz.test.ts::configuration/index fuzz tests::get never throws on arbitrary property paths with empty env (with seed=1009024787)` (plain)
- `configuration/index.fuzz.test.ts::configuration/index fuzz tests::get with realistic DD_ env vars never throws (with seed=1235359425)` (plain)
- `configuration/index.fuzz.test.ts::configuration/index fuzz tests::get with realistic DD_ env vars never throws (with seed=1855604842)` (plain)
- `configuration/index.fuzz.test.ts::configuration/index fuzz tests::get with realistic DD_ env vars never throws (with seed=2002608825)` (plain)
- `model/container.fuzz.test.ts::model/container fuzz tests::flatten handles validated containers (with seed=-1400469272)` (plain)
- `model/container.fuzz.test.ts::model/container fuzz tests::flatten handles validated containers (with seed=1580087321)` (plain)
- `model/container.fuzz.test.ts::model/container fuzz tests::flatten handles validated containers (with seed=549447365)` (plain)
- `model/container.fuzz.test.ts::model/container fuzz tests::getLink handles arbitrary string pairs for container/tag (with seed=-378697862)` (plain)
- `model/container.fuzz.test.ts::model/container fuzz tests::getLink handles arbitrary string pairs for container/tag (with seed=313092111)` (plain)
- `model/container.fuzz.test.ts::model/container fuzz tests::getLink handles arbitrary string pairs for container/tag (with seed=547624520)` (plain)
- `model/container.fuzz.test.ts::model/container fuzz tests::getLink never throws on arbitrary container and tag (with seed=-110396330)` (plain)
- `model/container.fuzz.test.ts::model/container fuzz tests::getLink never throws on arbitrary container and tag (with seed=1128257184)` (plain)
- `model/container.fuzz.test.ts::model/container fuzz tests::getLink never throws on arbitrary container and tag (with seed=360480395)` (plain)
- `model/container.fuzz.test.ts::model/container fuzz tests::validate accepts valid container-shaped objects (with seed=1358800818)` (plain)
- `model/container.fuzz.test.ts::model/container fuzz tests::validate accepts valid container-shaped objects (with seed=1419976607)` (plain)
- `model/container.fuzz.test.ts::model/container fuzz tests::validate accepts valid container-shaped objects (with seed=2095754116)` (plain)
- `model/container.fuzz.test.ts::model/container fuzz tests::validate handles arbitrary input without crashing (with seed=-1508754779)` (plain)
- `model/container.fuzz.test.ts::model/container fuzz tests::validate handles arbitrary input without crashing (with seed=1552102637)` (plain)
- `model/container.fuzz.test.ts::model/container fuzz tests::validate handles arbitrary input without crashing (with seed=1902562786)` (plain)
- ... 53 more (correctness.py prints all)

**lerna-lite**

| run | counts (median, spread) | exit codes |
|---|---|---|
| par w2 | passed 107 (±0) | [0] |
| par w4 | passed 107 (±0) | [0] |
| plain w1 | passed 107 (±0) | [0] |
| plain_par w2 | passed 107 (±0) | [0] |
| plain_par w4 | passed 107 (±0) | [0] |
| serial w1 | passed 107 (±0) | [0] |
| verify w2 | | [1] |
| verify w4 | | [1] |

VARIABLE tests (outcome varied over the 3 rounds of one kind; excluded from correctness rule 3): 0


## Notes (written by hand, not by table.py)

**Fixed-epoch runs.** `F-base1..3` are serial `--det-epoch=fixed` runs (`harness/p2/fixed_run.py`, rows in each repo's `fixed.jsonl`). Correctness rule 2 compares a fix only on tests whose outcome and fingerprint are identical across all three.

| repo | tests in all 3 | identical outcome + fingerprint | unstable (left out of rule 2) |
|---|---|---|---|
| nestjs-pino | 269 | 269 | 0 |
| agentsys | 2224 | 2209 | 15 |
| alakajam | 221 | 118 | 103 |
| agentlang | 439 | 435 | 4 |
| yalc | 1483 | 1454 | 29 |
| ironcurtain | 7033 | 6496 | 537 |
| codex-multi-auth | 8662 | 7365 | 1297 |
| drydock | 21578 | 21275 | 303 |
| lerna-lite | 107 | 88 | 19 |

**Tests that fail under the baseline engine but not under plain runs** (engine 6e79a62, pre-existing; out of scope for P2, which changes speed only). These counts come from the outcome tables above:

- alakajam: plain serial 217 passed. Engine serial and par: about 110 failed, in the server service specs. 18 tests are VARIABLE.
- agentlang: plain 439 passed. Engine: 2 failed, in `test/runtime/basic.test.ts` and `test/runtime/harness.test.ts`.
- ironcurtain: plain 19 failed. Engine serial about 36 failed, engine par 384 failed.
- codex-multi-auth: plain 6-7 failed. Engine about 67-76 failed.
- drydock: plain 0 failed. Engine about 82 failed.

The plain parallel runs of alakajam, agentlang and yalc also vary on their own (shared state between test files). Correctness rule 3 keeps each fix's counts within the baseline spread shown above.
