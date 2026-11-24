# §0 route probe (query `postgres jest path:.github/workflows`)

| # | When (UTC) | Route | Result | Raw |
|---|---|---|---|---|
| 0 | 2026-11-24 17:39:13 | work session, `gh api -X GET search/code` | HTTP 200, total_count 4,488, incomplete_results false, `X-RateLimit-Limit` 10 (code_search) | `results/probe_session.json` |
| 1 | 2026-11-24 17:39:55 | workflow, `GITHUB_TOKEN` (run 45450935955, request 0) | HTTP 429 `try again in 2.044344713s`, `X-RateLimit-Remaining` 10, `Used` 0 | `results/probe_workflow.json` (overwritten by #3; first response quoted here) |
| 2 | 2026-11-24 17:40 | workflow (run 45451129158, request 1) | still retrying after 10 min (client then waited on every 429); cancelled by me, no response kept | none |
| 3 | 2026-11-24 17:52:29 | workflow (run 45452808901, request 2; every attempt recorded, waits bounded) | 4 attempts, all HTTP 429 (`Retry-After: 1`, `X-RateLimit-Remaining` 10, `Used` 0) | `results/probe_workflow.json` |

Decision: discovery (§1) and the §4 code searches run on the work-session route, the only route that returned HTTP 200.
The workflow route (`X-RateLimit-Limit` 5000/h core, seen in the debug run 45452808901) does every non-search read
(§2, §3 and the §4 file reads): the work session's proxy answers HTTP 403 for REST reads of third-party repositories.
