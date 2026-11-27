STANDS

# Market direction check: REPORT

## Changes after PREREG (each on its own line, with justification)

1. APPROVED (founder, /plan-eng-review D1 = A; coordinator 2026-11-24 18:54 UTC): PREREG amendment 1, discovery reads page 1 of each leaf. Justification: about 1.49M root files; reading every leaf in full does not fit the 24 h discovery budget.
2. APPROVED by the founder (D2 = A, ~19:20 UTC) (Part 2 interpretation 1, route): every Part 2 page fetch ran in the workflow runner with the pre-registered tool (Python requests 2.34.2, manual redirects); this container's proxy refuses most company hosts (probe/web_session).
3. APPROVED by the founder (D2 = A, ~19:20 UTC) (Part 2 interpretation 2): home URLs of 16 added companies came from one logged lookup query each (queries.md, L1-L16), used for the domain only.
4. APPROVED by the founder (D2 = A, ~19:20 UTC) (Part 2 interpretation 3): a round counts only if a cited company page or news page loaded (HTTP 200) and states the amount; funding-database profiles do not count. Within a round the company's figure wins; otherwise the news figure stated by the most pages, ties to the lower.
5. APPROVED by the founder (D2 = A, ~19:20 UTC) (Part 2 interpretation 4): two rows excluded: Buildkite $21M Series B (the 2022 round re-dated 2026-09-20) and Langfuse $50M Series B (a vendor's blog; Langfuse joined ClickHouse in 2026-01).
6. APPROVED by the founder (D2 = A, ~19:20 UTC) (Part 2 interpretation 5): Blacksmith Series C date completed from its page (Dealroom News, 2026-10-21).
7. APPROVED by the founder (D2 = A, ~19:20 UTC) (Part 2 interpretation 6): the 162 per-company queries were run by 6 subagents with one fixed brief; raw results in funding_queries/batch0-5.md.
8. Implementation (rule unchanged, db-serial-count gate note 7): a step whose script resolves to no runner command is not a test step, so it cannot make a job `unresolved` (found in debug run 4, sindresorhus/got).

## Numbers

| Item | Value |
|---|---|
| Part 1 | NO DECISION |
| Part 2 | R<3 |
| Complete pairs | 0 |
| Agent candidates read | 0 |
| Median g agent | - |
| Median g control | - |
| Difference of medians, 95% bootstrap (information) | - .. - |
| Level (agent, control) | - |
| Eval setup share agent / control (information) | - / - |
| F_T (USD) | 134,232,050 |
| F_E (USD) | 300,400,000 |
| R | 2.24 |
| Sensitivity (information): R without the largest round per category | 2.94 |
| Sensitivity (information): R with borderline counted as E | 12.06 |
| Sensitivity (information): R with borderline counted as T | 0.21 |
| Seed companies UNVERIFIED | 2 of 39 |
| T0_MIN | 2026-04-01 |

R < 3 depends on the pre-registered classification: with the borderline companies counted as E, R = 12.06.

## Dropped agent candidates by reason

| Reason | Count |
|---|---|
| excluded | 0 |
| no_language | 0 |
| no_root_file | 0 |
| t0_out_of_range | 0 |
| no_test_step | 0 |
| unresolved | 0 |
| too_few_runs | 0 |
| retention | 0 |
| zero_duration | 0 |
| no_control | 0 |
| error | 0 |


## Run status (in progress; replaced by the final build)

Updated 2026-11-27 05:12 UTC. Part 1 reading is running; this REPORT body is the earlier Part-2-only build and is not the final result.

- Reading deadline: 2026-11-28 01:44:55 UTC (48 h budget per PREREG section 1.4, coordinator 2026-11-26 14:21 UTC).
- Complete pairs so far: 34 (results/chunks.jsonl, chunks 8-11).
- Calls per new complete pair by chunk: 8: 2,091; 9: 2,831; 10: 1,463; 11: 1,433.
- Request 12 pushed 2026-11-27 04:31 UTC (27a052b), expected about 09:20 UTC.
- Projection at 8.5 pairs per chunk: about 72 pairs by the deadline, under 100, so Part 1 would be NO DECISION.
