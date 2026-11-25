DONE

# Public count of security advisories whose root cause is order, timing or shared state

Pre-registration: `PREREG.md` (committed before any data). Branch `claude/advisory-security-count`. Every number below is written `<n><!--key-->` and re-derived by `verify.py`.

## Decision

DROP: 5.3%<!--share--> ours (16<!--ours--> of 300<!--included--> included).

Wilson 95% interval: 3.3%<!--wilson_lo--> to 8.5%<!--wilson_hi-->. The `ours` count is a lower bound for the frame (only `ours` rows confirmed by the independent double read are counted; disputed rows are `unclear`).

## PREREG changes (listed before the result)

- Change 1 (`prereg_changes.md`): class-rule clarifications C1 (principal), C2 (O1 limited to in-memory or caching layers), C3 (O4 versus a precondition the attacker creates), C4 (tie-break reminder), made because the double read at the first 300th included row failed (kappa 0.76<!--r1_kappa-->, confirmed 19<!--r1_confirmed--> of 24<!--r1_ours_first--> = 79.2%<!--r1_confirmed_share--> < 80%). Every included row was re-read (300<!--reread_rows--> rows, 5<!--reread_changed--> labels changed, `reread/cp300b.jsonl`); reading resumed in the same order to a new 300th included row (checkpoint `cp300b`) and the double read was repeated with fresh subagents. Thresholds, lists, regexes, seeds, budget and decision line unchanged.
- Interpretations recorded in PREREG.md before data: quote check after whitespace collapsing; gate rev 3 notes 5, 8, 9 applied.
- First-reader label correction before any double read: `corrections.md`.

## Route (§0)

Session route: both probe calls answered 403 from the session proxy (`probe/session-*.json`). Workflow route (`.github/workflows/advisory-security-count.yml`, `wf_job.py`): both answered 200 (`probe/workflow-*.json`). Listing and fix material were read through the workflow route.
Requests logged: 1487<!--requests--> (1485<!--requests_workflow--> through the workflow); non-GET 0<!--requests_non_get-->; search endpoints 0<!--requests_search-->. Budget clock started 2026-11-25T07:26:31Z (first data request).

## Funnel

Listed (reviewed, not withdrawn, published 2024-01-01..2026-11-25): total 18413<!--listed_total--> rows over 7 ecosystem listings → 18243<!--frame--> distinct advisories.

| ecosystem | listed | in frame |
|---|---|---|
| npm | 4546<!--listed_npm--> | 4546<!--frame_npm--> |
| pip | 3975<!--listed_pip--> | 3975<!--frame_pip--> |
| rubygems | 395<!--listed_rubygems--> | 395<!--frame_rubygems--> |
| maven | 2285<!--listed_maven--> | 2285<!--frame_maven--> |
| composer | 3016<!--listed_composer--> | 3016<!--frame_composer--> |
| go | 3564<!--listed_go--> | 3564<!--frame_go--> |
| nuget | 632<!--listed_nuget--> | 632<!--frame_nuget--> |

Candidates: 5796<!--candidates--> — route (a) CWE list 4645<!--route_a-->, (b) narrow regex only 1138<!--route_b--> (of which CWE-79 197<!--route_b_cwe79-->, CWE-352 15<!--route_b_cwe352-->), (c) no CWE + broad regex 13<!--route_c-->. Memberships: (a) 4645<!--member_a-->, (b) 2133<!--member_b-->, (c) 21<!--member_c-->.

Read in the seeded order: 580<!--read--> rows; the 300th included row is the last of the first 565<!--cp_rows--> rows of the reading order (zero-based position one less). Checkpoint scope: 565<!--cp_read--> read → 300<!--included--> included, 265<!--excluded--> excluded.

| exclusion reason | rows |
|---|---|
| crypto | 6<!--exc_crypto--> |
| csrf | 7<!--exc_csrf--> |
| dos | 40<!--exc_dos--> |
| injection | 27<!--exc_injection--> |
| memory | 1<!--exc_memory--> |
| no-I1-I3 | 20<!--exc_no-I1-I3--> |
| no-principal-disclosure | 17<!--exc_no-principal-disclosure--> |
| not-web | 77<!--exc_not-web--> |
| one-principal | 10<!--exc_one-principal--> |
| open-redirect | 3<!--exc_open-redirect--> |
| path-traversal | 20<!--exc_path-traversal--> |
| ssrf | 12<!--exc_ssrf--> |
| supply-chain | 1<!--exc_supply-chain--> |
| xss | 24<!--exc_xss--> |

Included → `ours` 16<!--ours--> (first reader 19<!--ours_first-->, disputed 3<!--disputed-->), `read-the-code` 261<!--read_the_code-->, `unclear` 23<!--unclear-->. Included rows with fix material (at least one commit, PR or compare read): 180<!--with_fix--> (60.0%<!--with_fix_share-->). Rows whose quote failed the verbatim check: 0<!--quote_flags-->.

## `ours` breakdown

| subclass | rows |
|---|---|
| O1-shared-state | 4<!--sub_O1-shared-state--> |
| O2-context-loss | 3<!--sub_O2-context-loss--> |
| O3-concurrency | 6<!--sub_O3-concurrency--> |
| O4-order | 1<!--sub_O4-order--> |
| O5-time | 2<!--sub_O5-time--> |

By ecosystem: go 5, maven 2, npm 5, pip 3, rubygems 1. By severity: critical 1, high 5, low 4, medium 6.

Share without the (b)/(c)-route candidates: 5.2%<!--share_a--> (15<!--ours_a--> of 290<!--included_a--> included via the CWE list).

Top 10 projects by included rows: openclaw/openclaw 24, mattermost/mattermost 10, go-gitea/gitea 8, magento/magento2 7, open-webui/open-webui 7, go-vikunja/vikunja 7, craftcms/cms 6, keycloak/keycloak 4, siyuan-note/siyuan 4, n8n-io/n8n 4.

## Every `ours` advisory

| ghsa_id | package | ecosystem | severity | subclass | quote | fix |
|---|---|---|---|---|---|---|
| GHSA-2phq-3phc-84px | vllm | pip | medium | O1-shared-state | caches query embeddings under a caller-controlled request id | https://github.com/vllm-project/vllm/pull/51445 |
| GHSA-3492-cvg7-9mr2 | djust | pip | high | O2-context-loss | The current tenant was stored in `threading.local()` and set exclusively by the HTTP-only `TenantMiddleware` |  |
| GHSA-38f7-945m-qr2g | effect | npm | high | O3-concurrency | context lost/contaminated inside Effect fibers under concurrent load |  |
| GHSA-4hfh-6x8g-gwpp | org.springframework:spring-webflux | maven | medium | O3-concurrency | Avoid race in InMemoryWebSession | https://github.com/spring-projects/spring-framework/commit/b8ddd2c690fe3f00bb5e3d9f913a37504aab49a0 |
| GHSA-5957-c7qm-m469 | actionmailbox | rubygems | low | O5-time | rejects only timestamps more than 2 minutes in the past | https://github.com/rails/rails/commit/4aa2ec66822bc4eb8b341a0608f1c90a3e371a34 |
| GHSA-59qj-jcjv-662j | DIRAC, dirac | pip | critical | O1-shared-state | Any user could get a token that has been requested by another user/agent | https://github.com/DIRACGrid/DIRAC/commit/9487921684e2925b4cf72d6c423718cf4950f3fe |
| GHSA-5c3f-6486-3g7g | gogs.io/gogs | go | medium | O5-time | Password-reset tokens are generated using `conf.Auth.ActivateCodeLives` (the account-activation lifetime), not `conf.Auth.ResetPasswordCodeLives`. | https://github.com/gogs/gogs/pull/8328 |
| GHSA-6x8v-2fq5-2229 | github.com/zitadel/zitadel | go | low | O4-order | Recreating a deleted user under a distinct organization can cause the new user instance to be incorrectly provisioned within the original organization | https://github.com/zitadel/zitadel/commit/6082e59d47c17a9d54a6b0556b3f31559d7c620a |
| GHSA-9623-mj7j-p9v4 | io.quarkus:quarkus-vertx | maven | medium | O2-context-loss | With the new semantic data from one transaction can leak to the | https://github.com/quarkusio/quarkus/commit/2b58f59f4bf0bae7d35b1abb585b65f2a66787d1 |
| GHSA-f23p-vx2j-j53r | hono | npm | medium | O1-shared-state | a response can contain HTML rendered for another user's request | https://github.com/honojs/hono/commit/0c45036d6b0ddf42ab2fa44639dc8710825d5c0f |
| GHSA-f899-4mr4-fqpv | github.com/apache/incubator-answer | go | low | O3-concurrency | Concurrent Execution using Shared Resource with Improper Synchronization ('Race Condition') vulnerability in Apache Answer. |  |
| GHSA-h3hw-29fv-2x75 | @envelop/graphql-modules | npm | high | O3-concurrency | When 2 or more parallel requests are made which trigger the same service, the context of the requests is mixed up in the service | https://github.com/graphql-hive/envelop/commit/ab49fa259a51d976c437e084114e070b99720ba9 |
| GHSA-hwr4-mq23-wcv5 | github.com/dunglas/mercure | go | high | O1-shared-state | A cache key collision vulnerability in `TopicSelectorStore` allows an attacker to poison the match result cache, potentially causing private updates to be delivered to unauthorized subscribers | https://github.com/dunglas/mercure/commit/4964a69be904fd61e35b5f1e691271663b6fdd64 |
| GHSA-j48m-h7xq-2xpj | goshs.de/goshs/v2 | go | medium | O3-concurrency | redemption races past download limit |  |
| GHSA-r77c-2cmr-7p47 | openclaw | npm | low | O2-context-loss | Recovered queued outbound media could be replayed without the original session context needed to enforce group tool policy | https://github.com/openclaw/openclaw/pull/66025 |
| GHSA-w2fm-25vw-vh7f | mcp-handler | npm | high | O3-concurrency | causes concurrent requests from different clients to share server-side state |  |

Disputed by the double read (counted as `unclear`): GHSA-3h9f-r86x-qvjx, GHSA-75vq-qvhr-7ffr, GHSA-q62f-h9x2-gcqc.

## Calibration and double read

Gold set (6 unlabeled cases, `gold/input.jsonl`): first reader 6<!--gold_first_ok--> of 6<!--gold_n--> (not blind); independent reader before any real row 6<!--gold_pre_ok--> of 6; first double-read subagent of round 1 before its rows 6<!--r1_gold_ok--> of 6; first double-read subagent of round 2 before its rows 6<!--gold_dr_ok--> of 6.

Round 1 (checkpoint `cp300`, before change 1): sample 64<!--r1_sample-->, kappa 0.76<!--r1_kappa-->, confirmed 19<!--r1_confirmed--> of 24<!--r1_ours_first--> (79.2%<!--r1_confirmed_share-->): failed; no decision taken there (`doubleread/cp300/stats.json`).

Checkpoint `cp300b`: sample 59<!--dr_sample--> rows (every first-reader `ours` plus `random.Random(6).sample` of 40 not-`ours` included rows), second labels 59<!--dr_read-->. Cohen's kappa (ours vs not-ours) 0.84<!--dr_kappa-->; first-reader `ours` confirmed 16<!--dr_confirmed--> of 19<!--dr_ours_first--> (84.2%<!--dr_confirmed_share-->); rows only the second reader calls `ours` 1<!--dr_second_only--> (never promoted). Thresholds (kappa ≥ 0.6, confirmed ≥ 80%) met: yes<!--dr_ok-->.

## Frame bias

The CWE list and regexes can miss `ours` advisories tagged with other CWEs and wording (bias toward DROP) and bring in authorization advisories that are almost always `read-the-code` (bias toward DROP); keyword-only candidates may lean toward `ours` (bias toward CONTINUE); the share without (b)/(c) is printed above.

## Limits

- GitHub reviewed advisories only (libraries and frameworks, not private applications).
- Classification by reading; the second reader is the same model family, not a human.
- The double read can only demote `ours` rows, never promote a not-`ours` one; excluded rows are never re-read.
- Many vendor advisories (Magento, some VulDB-sourced entries) do not describe the mechanism and are `unclear`.
- rust, erlang, pub and swift, and advisories published after 2026-11-25, are not covered.
