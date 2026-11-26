# §0 route probes (2026-11-26, after the coordinator's "search budget free" at 17:22Z)

| Query | Session (`gh api`) | Workflow (`GITHUB_TOKEN`, run 45867356605) |
|---|---|---|
| (a) `stryker path:.github/workflows` | HTTP 200, total_count 3,284 | HTTP 200, total_count 3,284 |
| (b) `stryker filename:package.json` | HTTP 200, total_count 10,592 | HTTP 200, total_count 10,592 (after one 429 retry) |
| (b) `mutants filename:mutants.toml path:.cargo` | HTTP 200, total_count 1,024 | HTTP 429 on all 6 attempts ("try again in 15.99s") |
| (c) issues query, first form | HTTP 422 (needs `is:issue`/`is:pull-request`; CHANGES.md 15) | not sent |
| (c) issues `... is:issue` | HTTP 200, total_count 193 | HTTP 200, total_count 193 |
| (c) issues `... is:pull-request` | HTTP 200, total_count 106 | HTTP 200, total_count 106 |

All incomplete_results false. Raw JSON: `results/probe_session.json`, `results/probe_session_first.json`,
`results/probe_workflow.json`. No shape answered 422 or `total_count` 0 after the fix.

Decision: code search (§1 discovery) runs on the work-session route: the totals are equal and only the session route
answered every shape with HTTP 200. §4.3 issues search runs on the work-session route (both answered 200; session
preferred), so chunk requests use `"issues_route": "session"` and the session runs `issues.py` per chunk.
§2-§4.2 reads run in the workflow (`GITHUB_TOKEN`).
