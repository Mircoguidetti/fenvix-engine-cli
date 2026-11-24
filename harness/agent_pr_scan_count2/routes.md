# Count 2: routes to third-party CI results (every attempt)

A route "works" only if it returns head check results (name, conclusion, head SHA) and base-side run results for at
least 5 different third-party PRs from the pool, committed as raw JSON (HTTP 200 with an empty list counts; 403 /
404 do not). The probe is the first 5 PRs of the seeded draw (`draw.jsonl.gz`, after static exclusions).

## Route 1: GitHub Actions in this repository (workflow `.github/workflows/agent-pr-count2.yml`, GITHUB_TOKEN)

| # | When (UTC) | Attempt | Exact result | Real data? |
|---|---|---|---|---|
| 1a | 2026-11-24 09:10 | push of the branch with the workflow file (commit 6d15f0b, no request file) | run 45362656643 started on `push`, conclusion `success` (no request file: nothing read, nothing committed) | no (trigger check only) |

## Route 2: search API qualifiers (`is:pr status:failure` / `status:success`), denominator only

(see below)

## Route 3: other public sources (at most 1 hour, no login, no account, no paid service)

| # | When (UTC) | Command | Exact result (first 300 characters) | Real data? |
|---|---|---|---|---|
| 3a | 2026-11-24 09:12 | `curl -sS -o h.json.gz https://data.gharchive.org/2026-06-10-12.json.gz` (GH Archive hourly events) | `curl: (56) CONNECT tunnel failed, response 403` | no |
| 3b | 2026-11-24 09:13 | `curl -sS -m 30 https://huggingface.co/api/datasets?search=github%20actions%20runs` | `curl: (56) CONNECT tunnel failed, response 403` | no |
| 3c | 2026-11-24 09:13 | `curl -sS -m 30 https://www.gharchive.org/` | `curl: (56) CONNECT tunnel failed, response 403` | no |
| 3d | 2026-11-24 09:13 | `curl -sS -m 30 https://zenodo.org/api/records?q=github%20actions%20workflow%20runs` | `curl: (56) CONNECT tunnel failed, response 403` | no |

Note on 3a: even where reachable, GH Archive records the public events API, which (to the reporter's knowledge, not
checked here) carries no check-run or workflow-run events, so it could not give head or base CI results.
