NOT DONE

# Agent-determinism count: agent repositories with agent-test non-determinism pain

Printed by `report.py` from the committed raw rows; `verify.py` re-derives every row from the raw responses, recomputes every number and re-prints this file. Rules: `PREREG.md`.

## Changes after PREREG

1. 2026-11-25, before the first request (coordinator, founder D1 = A, partial "search budget free" received
   2026-11-25T10:47Z): the search budget is split. Issues and commits search (§0.2c probes, the OR and
   is:issue/is:pr checks, §1 S2 and S3 pre-pass and bisection) run now and only through the workflow route
   (GITHUB_TOKEN, <= 25/min), never the session token; the §0.2d registry pages run in the same workflow request.
   Code search (§0.2a, the code shapes of §0.2b, S1, the population counts) waits for the coordinator's second
   message. Each family (code; issues+commits) has its own 24 h discovery budget from its own first request and its
   own pre-pass stop (> 20 h projected); reading (§2-§5) starts when the last family's discovery ends; read order
   unchanged. The issues and commits routes are chosen separately: if search/commits does not answer 200 on the
   workflow route, S3 waits for the second message. Implemented by scopes in results/search_budget_free.json that
   ghapi.py enforces. Reason: market-direction's code-search discovery shares this account's session budget.
2. 2026-11-25, before any repository search (probe p1, `paren`: `repo:langchain-ai/langchain (flaky OR
   nondeterministic) llm` answered 8,918 against 101 and 7 for its parts, i.e. the repo: scope leaks when a term
   follows the parentheses): repository-search hits whose repository is not the member are dropped from the
   member's texts (`texts.member_texts`). No query shape changes: no §1 or §3.2 query has a term after its
   parentheses, and the OR check (`flaky OR nondeterministic` 108 >= 101, 7) passed. Reason: §Definitions, a text is
   a commit, pull request or issue of the repository.
3. 2026-11-25 14:50Z, during S2/S3 bisection (storage only, no rule, query or count change): the discovery leaf file
   (trimmed search items with issue bodies) passed GitHub's 100 MB per-file push limit near 13:21Z (57 MB gzip at
   12:51Z, ~40 MB per 30 min), so run 45603465040's checkpoint pushes were refused while it kept bisecting. Leaf files
   now stay out of git: each run writes results/discovery/leaves_<family>/<family>-<run>.jsonl.gz, uploads it as the
   artifact agent-determinism-count-leaves-<run>, and commits the index leaf_parts_<family>.json (artifact, path,
   sha256, bytes, lines). The next discovery request restores state, splits, pre-pass and leaf file of run
   45603465040 from its results artifact (results/discovery/restore_text.json; only if that state is not behind the
   committed one). `parts.py fetch` downloads every indexed part and checks its sha256 before `discover.py build`.
4. 2026-11-26 03:05Z, coordinator's second message (code search free; workflow route while market-direction's leaf
   reading uses the account token): results/search_budget_free.json gains the scope `code`; `session` stays closed.
   S1 runs in a second workflow (agent-determinism-count-code.yml: requests_code/, its own concurrency group and done
   markers results/requests_done_code/) beside S2/S3, and commits only the code family's files (commit_results.sh,
   ADC_FAMILY=code; no file is staged for removal). Requests: c1 the §0.2a and §0.2b code probes (probe.py
   workflow-code: only the code fields of probe_decisions.json change, every text decision stays), c2 the S1 pre-pass,
   c3 the population counts, c4 S1 bisection. A code request waits while the code route is not the workflow route.
   No rule, query or count change; S1's 24 h budget runs from its own first request.
5. 2026-11-26 04:10Z, harness fix (coordinator): the c1 probe b-code-recordings answered 429 on all 6 attempts
   (03:32Z), and decide() dropped the code shape path:recordings for every host because it treated a rate-limited
   answer as 0 results. A 429 is no answer, so the §0.2b drop rule (0 results or an error) had not fired. decide()
   now keeps a rate-limited shape and lists it in code_reprobe; merge_code_decisions recomputes the code drops from
   the code probes, so a re-probe can restore a shape. Request c1b re-probes b-code-recordings (its record replaces
   the 429 one); the shape is dropped only if the re-probe answers 200 with 0 results or a real error. Until then
   the S1 pre-pass runs without path:recordings; c4's pre-pass adds those queries. Test:
   test_rate_limited_code_probe_never_drops_a_shape (fails before the fix).
6. 2026-11-26 04:55Z, harness fix (no rule change): a discovery request that stopped at its max_minutes was marked
   done (d1 earlier; d2 at 04:22Z), so run 45726858242 found no pending discovery and S2/S3 sent nothing from
   04:22Z to the next push. job.py now marks a discovery request done only when the family finished or reached its
   24 h budget; d3 resumes S2/S3. Test: test_discovery_time_limit_leaves_request_pending.
7. 2026-11-26 07:37Z, request order only (coordinator): the code pre-pass c2 finished at 05:30Z with 32 shapes, 30
   answered and 2 at 429 (generativelanguage.googleapis.com path:vcr, openai.azure.com path:cassettes); earlier
   status messages that gave "14/52" and "30/52" were wrong (they counted the population answers as pre-pass ones).
   From 05:31Z the code run worked on c3 (population counts, §1, information only): 27 of 102 queries by 07:35Z at
   about 13 per hour, so S1 discovery c4 would have started near 13:30Z. Discovery feeds the count and population is
   information only, so requests_code/c3.json is renamed c6.json: after the current code run (deadline ~08:25Z) the
   order is c1b, c4, c6. The 27 population answers in population.json are kept and c6 resumes after them. No rule,
   query or threshold change.
8. 2026-11-26 09:30Z, S1 route switch (coordinator, after "market reading done" at 09:27Z). The §0.2a re-probe on the
   session route (09:28Z, results/probe_session_code.json): a1 api.openai.com path:cassettes 200 tc=2, a2
   api.openai.com path:tests/cassettes 200 tc=1394, both in 7.8 s. The workflow route's answers (03:19Z,
   probe_workflow_code.json) are the same: a1 tc=2, a2 tc=1394. The totals tie, so the spec rule picks the faster
   route. Session: about 4 s per request, no 429. Workflow, during c4 08:43-09:25Z: 47 code requests in 42 min, 27 of
   them 429. Route: session. search_budget_free.json gains the scope `session`.
   Run 45776621427 (c4, workflow route) is stopped after a checkpoint, and S1 bisection resumes from its committed
   state in the work session (session_run.sh, harness-tracked chunks, checkpoint commits every 30 min). budget_end
   stays 2026-11-27T03:49:30Z. probe_decisions.json code_route becomes `session`, so the code workflow's requests
   (c4, c6) wait and the two routes never run at once. The session's leaves go to
   leaves_code/code-session.jsonl.gz, committed to git; the index marks it in_git, and parts.py fetch checks its
   sha256 instead of downloading it. Leaf records carry their route. If a session root-range answer is below the
   workflow pre-pass answer for the same query, discovery stops (state route_check) for a report. The build also
   keeps the leaves before a gzip member cut by a cancelled job. Tests: test_session_route_answer_below_workflow_prepass_stops,
   test_cut_gzip_member_and_session_part_in_git (both fail before the change). No rule, query or threshold change.
9. 2026-11-26 11:05Z, harness only (no rule, query or count change). The candidate build moves to the text workflow.
   The text leaf parts are about 1.2 GB gzip in four artifacts, and the work session cannot download artifacts (the
   proxy refuses the blob storage host). Request {"build": true} (requests/e1.json) runs `parts.py fetch` for both
   families (sha256 checked against the committed index), checks that each family finished or reached its 24 h
   budget, then runs `discover.py build`. Otherwise the request stays pending. read_leaves streams the parts in two
   passes, keeping the last record per (query, a, b), and memory holds candidates, not leaves. Hits keep the order
   of the leaves sorted by (stratum, query, a, b), then item order, then the first hit per (url, query). This is the
   order of the earlier in-memory build. candidates.jsonl.gz holds issue/commit bodies, so it stays out of git: the
   build run uploads it as the artifact agent-determinism-count-candidates-<run>, and git holds
   results/candidates_index.json (sha256, bytes, lines). Every later chunk request fetches it by that index
   (sha256 checked) before it runs. pool.json and orders.json are committed. The same run resumes d3 first, which
   records S2/S3's budget_reached and marks d3 done. Gap: S2/S3 sent nothing from 09:56Z (run 45758051807 stopped
   d3 at its max_minutes and no next run was queued) to its budget end at 10:54:28Z, about 58 min. The 1 unfinished
   query enters N_s as truncated with its pre-pass total. Tests: test_build_streams_leaves_and_keeps_hit_order,
   test_fetch_candidates_checks_sha (both fail before the change).
10. 2026-11-26 11:25Z, an extension the founder decided (main-eng-review-adc-s3-extension-20261126-112500.md,
    relayed by the coordinator at 11:18Z). One S3 extension runs on the session route, for the 88 S3 queries the
    24 h budget never started and the 1 it left unfinished, and for no other query. It has a hard stop 6 h after its
    first request, and any query not done by then stays truncated with its pre-pass total. Rules, shapes and caps are
    unchanged. `discover.py run --family text --route session --extension` (session_run.sh s3ext, harness-tracked
    chunks, checkpoint commits every 30 min) keeps its own state (discovery_state_s3ext.json, which copies the
    unfinished query's stack from the text state), splits (splits_s3ext.jsonl) and leaf parts
    (leaves_s3ext/s3ext-session-<HHMM>.jsonl.gz, one per chunk, committed to git and indexed in_git). This way the
    text workflow's commits, whose own list includes discovery_state_text.json, never overwrite it. When it ends, a
    new {"build": true} request fetches all parts and rebuilds, and the extension's queries replace their unfinished
    text entries. Reading chunks already started may continue; S3 is read further only after that rebuild. PREREG §1
    gains the note. Test: test_s3_extension_runs_only_uncovered_s3_queries (fails before the change).
11. 2026-11-26 11:35Z, harness only (no rule change). The rebuild after the S3 extension keeps every earlier
    candidate's idx: rows, raw records and the reading orders refer to candidates by idx. New candidates are numbered
    after the earlier ones. The {"build": true} request first fetches the earlier candidates.jsonl.gz by its index.
    Test: test_rebuild_keeps_earlier_candidate_idx (fails before the change).
12. 2026-11-26 11:31Z, a coordinator change to the coordinator's own route guard (not a founder rule). At 11:28Z the
    S3 extension stopped on the guard: 'committer-date:>=2024-01-01 xfail "model output" test' answered 251 on the
    session route, against 253 in its workflow pre-pass of 2026-11-25. A 2-hit difference on a pre-pass 24 h old is
    the commit index changing. For the extension, the guard now stops only if a session total_count is lower than
    the workflow pre-pass by more than 1% AND by more than 5 hits. S1 kept the strict guard. The 6 h hard stop is
    unchanged. Test: test_extension_route_guard_tolerates_small_index_drift (fails before the change).
13. 2026-11-26 11:45Z, harness only (no rule change). The work session cannot download candidates.jsonl.gz: the
    proxy refuses the artifact storage host. Each chunk request now appends the candidate records it reads to
    results/cands_read.jsonl.gz, which is committed by the text workflow. Hand reads and REPORT use the full file
    when present (in the workflow) and cands_read otherwise. Request r002x ({"cands_backfill": true}) adds the
    records of chunks 1-2, which were read before this existed. The comments passes r001c and r002c (§3.1) are
    queued after their chunks.
14. 2026-11-26 12:31Z, a listed order note caused by the founder's S3 extension (coordinator; no rule change). Until
    the rebuild that merges the extension, chunk 3 and later chunks read S2 only, in §4.1 order within S2. After the
    rebuild, S3 catches up in its own §4.1 order, so S3's first 300 are still read in order. The reading order inside
    a stratum is seeded, so this changes only when S3 is read, not which S3 candidates are read. Chunks 1 (S1) and 2
    (S2/S3 one to one) were read before the note.
    Correction (2026-11-26 19:20Z, item 22): that claim was wrong. The order is a seeded shuffle of the stratum's
    candidates sorted by URL (rules.stratum_order). The rebuild e2 added 30,473 S3 candidates, so the S3 order is a new
    permutation, and none of the 75 S3 candidates read in chunk 2 is among its first 75.
15. 2026-11-26 13:13Z, a coordinator change to the coordinator's route guard. At 13:11Z the S3 extension stopped on
    'committer-date:>=2024-01-01 unstable anthropic test': 51,826 on the session route, against 52,961 in the
    workflow pre-pass of 2026-11-25 (1,135 fewer, 2.1%). That query is above QUERY_CAP, so it is capped and not
    bisected: its total only feeds N_S3 and changes no candidate. The guard therefore no longer applies to capped
    queries (pre-pass total above QUERY_CAP). It stays for bisected queries at more than 1% AND more than 5 hits.
    The hard stop 17:20:43Z is unchanged. Test: test_extension_route_guard_tolerates_small_index_drift gains this
    case (it fails before the change).
16. 2026-11-26 15:00Z, a fix with no rule change. Text run 45820191350 (chunk 3, r003) lost its runner at 12:34:56Z,
    about 90 s after it loaded the candidates file. job.py held all 163,528 candidate records (about 0.9 GB
    uncompressed) for cands_read while run_chunk loaded a second full copy, so the runner most likely ran out of
    memory. Nothing was read and nothing was committed. Run 11 had loaded the file only once, because the backfill
    returns before run_chunk. Now each request loads only the idx it reads: the chunk's candidates, or the rows of
    the chunk named by a comments request. Reading was stopped from 12:34Z until this push re-queued r003 and r003c,
    and the work session noticed the failure only at 14:58Z.
17. 2026-11-26 15:05Z, the coordinator's watchdog (14:57Z, after the gaps 09:56-10:54Z and 12:34-14:56Z; no rule
    change). Every 20 minutes a harness-tracked timer wakes the work session. The session reads the latest text run's
    status with the GitHub tools (the session's gh is limited to search), and runs watchdog.py check. The API serves
    no log of a job still in progress (HTTP 404 at 15:04Z), so the activity time is the later of the run's start
    and its latest results commit (a checkpoint every 30 minutes), with a 35-minute limit. A run is healthy when it
    is queued, or in progress within that limit, or completed with no pending request. A runner that is shut down
    ends the run (as at 12:34Z), so the check catches it at the next wake. Otherwise watchdog.py gap records the gap and its cause in
    results/report_notes.json (REPORT "Notes") and results/watchdog.jsonl, and watchdog.py queue writes a noop
    request whose push starts a run. The 12:34:56-14:56:23Z gap is recorded. Test:
    test_watchdog_flags_stale_or_missing_text_run.
18. 2026-11-26 16:47Z, a watchdog fix (no rule change). Run 45852220950 fetched the branch after chunk 5 was pushed
    and read chunks 4 and 5 together. Run 45852260571 then found no request, and reading stopped at 16:40Z. The
    watchdog counted a completed run with nothing pending as healthy, so the 16:46Z check reported ok. It now counts
    an idle workflow as a gap while reading goes on. At each wake the session keeps at least one unread chunk pending
    or running. The 16:40-16:47Z gap is recorded in the REPORT notes.
19. 2026-11-26 17:25Z, a fix (no rule change). The S3 extension's hard stop was 17:20:43Z, but it stopped at 17:21:18Z.
    On the session route the search client had no deadline. A 60 s rate-limit sleep that began at about 17:19:57Z ran
    past the hard stop, and then one leaf was read: 'committer-date:>=2024-01-01 retry "ai sdk" test',
    2025-12-30..2026-01-31, 594 hits, about 6 search requests between 17:20:56 and 17:21:18Z. The coordinator decided at
    17:23Z (option b) that the leaf is dropped, because the 6 h hard stop is the founder's. The new part
    s3ext-session-1722drop records it again as a truncated leaf with 0 read; the build keeps the last record per leaf.
    So the 594 hits enter N_S3 as missing and add no candidate. The committed parts are unchanged, and the state
    records the drop (extension.dropped_after_hard_stop). Now the client's deadline
    is the budget end (or the hard stop), and no request is sent once it has passed. A deadline reached at the budget
    end stops discovery cleanly with budget_reached set, and the node cut short stays truncated. Test:
    test_no_request_past_the_deadline_and_extension_stops_at_hard_stop.
20. 2026-11-26 17:58Z, harness bookkeeping (coordinator 17:53Z; no rule change). Discovery is over, so test-quality-count
    now shares the account's search limit. Each chunk's record in chunks.jsonl and requests_done/ now carries n_429,
    the rate-limited answers (429, or 403 with a rate-limit message). It also carries sleep_s, the seconds slept by
    cause: rate_limit, pacing and server_error. Chunk 8 is the first chunk recorded this way; chunk 6 took 47.0 min
    against 18-30 min for chunks 4-5, with no count recorded. Test: test_client_counts_rate_limits_and_sleep_by_cause.
21. 2026-11-26 19:01Z, a founder decision ("lettura A", main-ceo-review-adc-reading-time-20261126-190500.md, relayed by
    the coordinator). Reading time must not decide the idea. The 24 h reading budget (READ_BUDGET_H) is withdrawn,
    and so is the `DROP (memo line)` it triggered. Reading goes on in §4.1 order until 50 pain-yes members are
    confirmed (CONTINUE) or until 15 Dec 2026. Fewer than 50 then gives `NOT ENOUGH DATA`: the read count, the rate,
    and the projected count over the whole pool with its interval. DROP only if that projection's upper bound is
    below 50. Membership and pain rules, the threshold 50 and the date are unchanged. The shared search budget is
    still yielded (test-quality-count, then idea 3 C5.3), with 429 numbers reported per chunk. The watchdog keeps
    running. Reports go out at each 10 pain-yes and once a day. Implementation (coordinator 19:04Z, after three
    questions at 19:03Z):
    (1) The projection is over the candidate pool, not N_s: per stratum, the rate times the candidates, summed. The
    upper bound is the Wilson 95% upper bound of A_s, the lower bound that of pain yes; a fully read stratum projects
    its counts.
    (2) There is no early DROP; DROP is judged only at the stop.
    (3) The stop stays at 2026-12-14 12:00 UTC: report.py sets it from HARD_STOP.
    decide() is rewritten (rules.project, rules.wilson_lower) and READ_BUDGET_H is withdrawn.
    test_decision_branches failed first and now covers CONTINUE at 50, no DROP before the stop (also at the old
    budget end), NOT ENOUGH DATA at the stop, DROP at the stop, and NO DECISION.
22. 2026-11-26 19:20Z, a coordinator decision (main-eng-review-adc-s3-order-20261126-191500.md, 19:10Z; no rule
    change). S3 is read in the rule's seeded order over the rebuilt pool of 80,478 candidates, skipping ids already
    read. That is option (a), as "ricerche A" accepted: new candidates join the pool by a rebuild before their stratum
    is read further. Keeping the old order with the new candidates appended (b) would be a rule change after seeing
    data. The 75 S3 candidates read in chunk 2, from the old order over 50,005, stay counted. S3's first 300 are
    therefore 75 from the old pool and 225 from the new order, so old-pool candidates are slightly over-represented.
    One check was added, not a rule. REPORT shows the S3 pain-yes rate for old-pool candidates (idx < 163528) and for
    new-pool candidates (the extension's, numbered from 163528 by the rebuild; results/s3_pool_split.json). Next to
    the projection it flags when the two Wilson 95% intervals do not overlap (rules.intervals_disjoint). decide() is
    unchanged. Item 14's claim is corrected there. Chunk 9 is the next 150 S3 in the new order (plan_next). Test:
    test_s3_old_new_pool_check_flags_disjoint_intervals.
23. 2026-11-26 19:33Z, harness bookkeeping (no rule change). Chunk 8 (the first chunk with item 20's numbers) took
    48.0 min: n_429 0, rate_limit sleep 1,975.1 s, pacing 355.8 s. With no 429, that sleep is the "remaining < 50:
    sleep until reset" rule, which ghapi applies to the core quota and not to search, but the record did not name
    the quota. Each chunk record now also carries rate_limit_sleep_by: the seconds by cause and resource
    (low_remaining_core, low_remaining_search, rate_limited_core, ...). Chunk 10 is the first chunk with it.
24. 2026-11-26 22:55Z, a fix (no rule change). Run 45894243468 (chunk 12) read its 150 candidates (Chunks step
    21:31-22:38Z). Every push of its results was then refused, the 22:31Z checkpoint and all 8 tries of the final
    commit: results/texts_search_wf.jsonl, the §3.2 search records appended uncompressed, had reached 106.92 MB, and
    GitHub refuses files over 100 MB. Chunk 12's results are in artifact agent-determinism-count-results-45894243468
    (108 files, 87.6 MB, sha256 a88cb221…), not in git. Run 45899018197 started on the old head without chunk 12's
    done marker, so it was redoing chunk 12 with the same failure ahead; it was cancelled. texts_search_wf.jsonl is
    now frozen at its last committed 101,329,224 bytes. New records go to one gzip part per chunk,
    results/texts_search_wf/<chunk>.jsonl.gz. Every reader (chunk.search_records, the resume check, texts.py,
    report.py, verify.py) reads chunk.search_files(): the session file, the frozen file, then the parts in chunk
    order. commit_results.sh commits the new folder. Chunk 12 is read again by the next run, and its done marker
    comes with that run's commit. Test: test_search_records_span_the_frozen_file_and_gzip_parts.
25. 2026-11-26 23:00Z, a watchdog addition (no rule change). `watchdog.py sizes` lists the results files above 80 MB,
    leaving out the frozen texts_search_wf.jsonl and the leaf parts. It runs at every watchdog wake, so a file nears
    GitHub's 100 MB limit long before it can block a push again (item 24).

## Decision

**IN PROGRESS: 4007 read, pain yes 35 (rate 0.0087); projected over the candidate pool 1669.8 (95% 1056.7 to upper 22341.0).**

P 35<!--P--> (recording 5<!--P_recording-->, text 30<!--P_text-->); P without the repositories whose only libraries are langchain*/llama-index*/llamaindex: 31<!--P_no_retrieval--> (information; the decision uses P).

read 4007<!--read-->, members 345<!--members-->, pain yes 35<!--yes-->, unknown 192<!--unknown-->, no 118<!--no-->, uncertain 180<!--uncertain-->; bounds S1 1.0<!--B_S1-->, S2 2914873.8<!--B_S2-->, S3 undefined; hand check: not passed.

S3 by pool (a check, not a rule; coordinator 2026-11-26 19:10Z): old-pool read 1132<!--S3_old_read-->, pain yes 10<!--S3_old_yes--> (95% 0.0048 to 0.0162); new-pool (the S3 extension) read 657<!--S3_new_read-->, pain yes 2<!--S3_new_yes--> (95% 0.0008 to 0.0110). The intervals overlap.

| stratum | candidates | N_s | read | A_s | U_s | B_s | how |
|---|---|---|---|---|---|---|---|
| S1 | 12<!--cand_S1--> | 12<!--N_S1--> | 6<!--read_S1--> | 1<!--A_S1--> | 0.56351 | 1.0<!--B_S1--> | count |
| S2 | 113511<!--cand_S2--> | 26212230<!--N_S2--> | 2212<!--read_S2--> | 217<!--A_S2--> | 0.11120 | 2914873.8<!--B_S2--> | wilson |
| S3 | 80478<!--cand_S3--> | 10478336<!--N_S3--> | 1789<!--read_S3--> | 189<!--A_S3--> | 0.12074 | undefined | undefined |

covered: GitHub Actions, public repositories, libraries ag2, agno, autogen-agentchat, autogen-core, autogen-ext, claude-agent-sdk, crewai, crewai-tools, dspy, dspy-ai, google-adk, haystack-ai, langchain, langgraph, llama-index, openai-agents, phidata, pyautogen, pydantic-ai, pydantic-ai-slim, semantic-kernel, smolagents, strands-agents, langchain-*, langgraph-*, llama-index-* (PyPI); @anthropic-ai/claude-agent-sdk, @mastra/core, @openai/agents, ai, langchain, llamaindex, @langchain/*, @ai-sdk/*, @llamaindex/* (npm), pain visible to code, issue and commit search; not covered: private repositories, other CI systems, pain never written down, pain written in words outside the discovery queries (the frame is pain-first: a DROP bounds the frame, not the population), libraries and hosts not listed, texts in languages other than English, shapes dropped after the probe.

Not covered in detail: unfinished `committer-date:>=2024-01-01 "api costs" test agent` (2341 hits); unfinished `committer-date:>=2024-01-01 "api costs" test llm` (2213 hits); unfinished `committer-date:>=2024-01-01 "api costs" test openai` (1619 hits); unfinished `committer-date:>=2024-01-01 "expensive tests" agent` (418 hits); unfinished `committer-date:>=2024-01-01 "expensive tests" llm` (88 hits); unfinished `committer-date:>=2024-01-01 "expensive tests" openai` (46 hits); unfinished `committer-date:>=2024-01-01 "live llm" test` (19248 hits); unfinished `committer-date:>=2024-01-01 "llm tests" test` (46260 hits); unfinished `committer-date:>=2024-01-01 "mock llm" test` (38017 hits); unfinished `committer-date:>=2024-01-01 "mock the llm" test` (1686 hits); unfinished `committer-date:>=2024-01-01 "real llm" test` (42900 hits); unfinished `committer-date:>=2024-01-01 "record and replay" llm test` (411 hits); unfinished `committer-date:>=2024-01-01 "skip llm" test` (8498 hits); unfinished `committer-date:>=2024-01-01 "tests are expensive" agent` (10 hits); unfinished `committer-date:>=2024-01-01 "tests are expensive" llm` (4 hits); unfinished `committer-date:>=2024-01-01 "tests are expensive" openai` (4 hits); unfinished `committer-date:>=2024-01-01 "token cost" test agent` (27965 hits); unfinished `committer-date:>=2024-01-01 "token cost" test llm` (12642 hits); unfinished `committer-date:>=2024-01-01 "token cost" test openai` (9601 hits); unfinished `committer-date:>=2024-01-01 cassette llm test` (5448 hits); unfinished `committer-date:>=2024-01-01 rerun "ai sdk" test` (997 hits); unfinished `committer-date:>=2024-01-01 rerun "llama-index" test` (57 hits); unfinished `committer-date:>=2024-01-01 rerun "model output" test` (1456 hits); unfinished `committer-date:>=2024-01-01 rerun "pydantic-ai" test` (112 hits); unfinished `committer-date:>=2024-01-01 rerun agent test` (159520 hits); unfinished `committer-date:>=2024-01-01 rerun anthropic test` (265878 hits); unfinished `committer-date:>=2024-01-01 rerun autogen test` (290 hits); unfinished `committer-date:>=2024-01-01 rerun claude test` (314656 hits); unfinished `committer-date:>=2024-01-01 rerun crewai test` (110 hits); unfinished `committer-date:>=2024-01-01 rerun eval test` (28076 hits); unfinished `committer-date:>=2024-01-01 rerun gemini test` (10219 hits); unfinished `committer-date:>=2024-01-01 rerun gpt test` (44030 hits); unfinished `committer-date:>=2024-01-01 rerun langchain test` (1165 hits); unfinished `committer-date:>=2024-01-01 rerun langgraph test` (956 hits); unfinished `committer-date:>=2024-01-01 rerun llamaindex test` (74 hits); unfinished `committer-date:>=2024-01-01 rerun llm test` (23886 hits); unfinished `committer-date:>=2024-01-01 rerun openai test` (50414 hits); unfinished `committer-date:>=2024-01-01 rerun prompt test` (68628 hits); unfinished `committer-date:>=2024-01-01 retry "ai sdk" test` (11227 hits); unfinished `committer-date:>=2024-01-01 retry agent test` (957426 hits); unfinished `committer-date:>=2024-01-01 vcr openai test` (2743 hits); dropped `api.anthropic.com path:cassette`; dropped `api.cohere path:cassette`; dropped `api.deepseek.com path:cassette`; dropped `api.groq.com path:cassette`; dropped `api.mistral.ai path:cassette`; dropped `api.openai.com path:cassette`; dropped `bedrock-runtime path:cassette`; dropped `generativelanguage.googleapis.com path:cassette`; dropped `openai.azure.com path:cassette`; dropped `openrouter.ai path:cassette`

## Notes (not rule changes)

- S3 discovery: 89 of the 466 pre-pass queries are not covered: 88 never started and 1 started but unfinished (`committer-date:>=2024-01-01 xfail gemini test`); together 7,749,239 pre-pass hits. They enter N_S3 as truncated with their pre-pass total_count (gate note 3) and are listed under 'Not covered in detail'. Whether to leave them truncated or extend S3 to run them is a question for the founder (coordinator 2026-11-26 11:10Z); no discovery query runs until he answers.
- S2/S3 gap: run 45758051807 stopped d3 at its max_minutes (300) at 09:53Z and ended at 09:56Z. The work session had not queued the next text run, so S2/S3 sent no search request from 09:56Z to its 24 h budget end at 10:54:28Z (about 58 min). Cause: the session's queueing step was missed (fix 142684a had kept d3 pending; no run was queued to resume it).
- Reading of the work session, not a rule change: N_s counts unread hits of capped, truncated and unfinished queries (mostly issues and commits), not repositories, so N_S2 = 26,212,230 and N_S3 = 10,304,746 against 113,511 and 50,005 candidates. The equal-split reads for a DROP by bounds (S2 6,041,811; S3 2,375,199) exceed every candidate and any reading budget, and B_S3 is undefined while S3 has incomplete leaves (6). A DROP by bounds below 50 is therefore out of reach; the reachable outcomes are CONTINUE (>= 50 members with pain yes) or DROP (memo line) at budget end or hard stop.
- Reading gap 2026-11-26T12:34:56Z-2026-11-26T14:56:23Z: text run 45820191350 (chunk 3, r003) lost its runner about 90 s after loading the candidates file; it held two full copies of the 163,528 candidate records (about 0.9 GB uncompressed each), most likely running out of memory. Nothing was read or committed. The work session noticed at 14:58Z; fix f20d2111a (requests load only the candidate records they read, CHANGES.md item 16) and run 45844017940 restarted r003 and r003c. A 20-minute watchdog has run since about 15:05Z (CHANGES.md item 17).
- Reading gap 2026-11-26T15:32:21Z-2026-11-26T15:45:21Z: run 45844017940 ended at 15:32Z with chunks 3 and 3c done and no request left; the next chunk was not queued until the 15:44Z watchdog check found the idle workflow (r004 and r004c pushed; run 45852220950 started 15:45:21Z). Cause: no chunk was queued ahead of the running one.
- Reading gap 2026-11-26T16:40:02Z-2026-11-26T16:46:46Z: run 45852220950 read chunks 4 and 5 together (r005 was pushed while it was starting) and ended at 16:39Z; run 45852260571 then found no request and ended at 16:40Z. The watchdog treated a completed run with nothing pending as healthy; the 16:46Z check caught it and the check now counts an idle workflow as a gap. Chunks 6 and 7 queued; run 45861883004 started 16:46:46Z.
- S3 extension: first request 11:20:43Z, hard stop 17:20:43Z (6 h, the founder's), stopped 17:21:18Z. Of the 89 targeted queries 48 finished, 1 started but unfinished, 40 never started; those 41 enter N_S3 as truncated. Overrun: the session client had no deadline, so a 60 s rate-limit sleep ran past the hard stop and one leaf ('committer-date:>=2024-01-01 retry "ai sdk" test', 2025-12-30..2026-01-31, 594 hits, about 6 search requests 17:20:56-17:21:18Z) was read 13-35 s after it. That leaf is dropped (coordinator 17:23Z) and enters N_S3 as truncated with its total of 594; the client deadline is now the budget end or hard stop (CHANGES.md item 19).
- Reading gap 2026-11-26T22:38:33Z-2026-11-26T22:51:13Z: run 45894243468 read chunk 12 (21:31-22:38Z) but could not push it: results/texts_search_wf.jsonl had reached 106.92 MB, over GitHub's 100 MB file limit, so the 22:31Z checkpoint and all 8 tries of the final commit were refused. The results are in artifact agent-determinism-count-results-45894243468, not in git. Run 45899018197 then began redoing chunk 12 on the same code and was cancelled at 22:51Z; run 45907000824 (fix a3b2dd4d4: search records in per-chunk gzip parts, CHANGES.md item 24) reads chunk 12 again. Lost: chunk 12's 67 minutes of reading, now repeated.
- Pause 2026-11-27T05:38Z until RESUME (coordinator, founder decision on credits; planned resume 2026-12-01 09:00Z): chunk 17 (run 45929444538) finished and chunk 18 (run 45935380926, started 05:34Z) runs to its end; no further chunk is queued and the chunk 17-18 hand reads wait for RESUME. HARD_STOP 2026-12-14 12:00Z and the decision line are unchanged.
- Reading gap 2026-11-27T06:41Z-2026-11-27T21:42Z: pause ordered by the coordinator at 05:38Z (founder decision on credits), lifted by RESUME; chunk 18 ran to its end, nothing was queued

## Timing and probes

- coordinator's "search budget free" message received: 2026-11-25T10:46:56Z
- first search request: 2026-11-25T10:54:25+00:00 (later than the message)
- LAUNCH (UTC date of the first discovery request): 2026-11-25
- probe decisions: {"blocked": false, "code_pending": false, "code_reprobe": [], "code_route": "session", "code_route_switch": {"at": "2026-11-26T09:56:06Z", "from": "workflow", "session_probe": "results/probe_session_code.json", "to": "session", "why": "coordinator 09:30Z: \u00a70.2a re-probe tie (a1 2=2, a2 1394=1394), session route faster; CHANGES.md item 8", "workflow_run_stopped": 45776621427}, "code_totals": {"session": 1394, "workflow": 1394}, "commits_or_ok": true, "commits_route": "workflow", "dropped": ["api.anthropic.com path:cassette", "api.cohere path:cassette", "api.deepseek.com path:cassette", "api.groq.com path:cassette", "api.mistral.ai path:cassette", "api.openai.com path:cassette", "bedrock-runtime path:cassette", "generativelanguage.googleapis.com path:cassette", "openai.azure.com path:cassette", "openrouter.ai path:cassette"], "excluded_repos": ["beyhangl/evalcraft", "cendorhq/cendor-libs", "dmallya93/llmreplay", "mikiships/pytest-agentcontract"], "fixes": ["code shape path:cassette: status 200 total 0 -> dropped"], "issues_or_ok": true, "issues_route": "workflow", "issues_type_split": false, "nested_path_ok": false, "recording_packages": ["cendor-cassette", "coding-agent-vcr", "evalcraft", "pytest-agentcontract"], "repo_text_shapes_ok": true, "text_route": "workflow"}

## Pre-pass

queries 508<!--pp_queries-->; code family 45<!--pp_code_req--> requests, 0.08 h at 9/min; issues+commits family 14654<!--pp_text_req--> requests, 9.77 h at 25/min; projected discovery 9.77 h (stop above 20 h: no); queries above QUERY_CAP 135<!--pp_capped-->.

Pre-pass N_s (Σ total_count, hits, an upper bound): S1 65<!--ppN_S1-->, S2 26645845<!--ppN_S2-->, S3 10563977<!--ppN_S3-->; planned reads (equal split) S1 300<!--ppn_S1-->, S2 6141757<!--ppn_S2-->, S3 2434951<!--ppn_S3-->; zero-count bound 34.2.

| query | stratum | status | total_count | projected requests |
|---|---|---|---|---|
| `api.anthropic.com path:cassettes` | S1 | 200 | 2 | 3 |
| `api.anthropic.com path:recordings` | S1 | 200 | 2 | 3 |
| `api.anthropic.com path:vcr` | S1 | 200 | 3 | 3 |
| `api.cohere path:cassettes` | S1 | 200 | 0 | 0 |
| `api.cohere path:recordings` | S1 | 200 | 0 | 0 |
| `api.cohere path:vcr` | S1 | 200 | 0 | 0 |
| `api.deepseek.com path:cassettes` | S1 | 200 | 0 | 0 |
| `api.deepseek.com path:recordings` | S1 | 200 | 0 | 0 |
| `api.deepseek.com path:vcr` | S1 | 200 | 0 | 0 |
| `api.groq.com path:cassettes` | S1 | 200 | 0 | 0 |
| `api.groq.com path:recordings` | S1 | 200 | 0 | 0 |
| `api.groq.com path:vcr` | S1 | 200 | 0 | 0 |
| `api.mistral.ai path:cassettes` | S1 | 200 | 0 | 0 |
| `api.mistral.ai path:recordings` | S1 | 200 | 0 | 0 |
| `api.mistral.ai path:vcr` | S1 | 200 | 0 | 0 |
| `api.openai.com path:cassettes` | S1 | 200 | 2 | 3 |
| `api.openai.com path:recordings` | S1 | 200 | 1 | 3 |
| `api.openai.com path:vcr` | S1 | 200 | 7 | 3 |
| `bedrock-runtime path:cassettes` | S1 | 200 | 0 | 0 |
| `bedrock-runtime path:recordings` | S1 | 200 | 0 | 0 |
| `bedrock-runtime path:vcr` | S1 | 200 | 3 | 3 |
| `cendor-cassette filename:package.json` | S1 | 200 | 0 | 0 |
| `cendor-cassette filename:pyproject.toml` | S1 | 200 | 5 | 3 |
| `cendor-cassette filename:requirements.txt` | S1 | 200 | 0 | 0 |
| `coding-agent-vcr filename:package.json` | S1 | 200 | 0 | 0 |
| `coding-agent-vcr filename:pyproject.toml` | S1 | 200 | 1 | 3 |
| `coding-agent-vcr filename:requirements.txt` | S1 | 200 | 0 | 0 |
| `evalcraft filename:package.json` | S1 | 200 | 1 | 3 |
| `evalcraft filename:pyproject.toml` | S1 | 200 | 1 | 3 |
| `evalcraft filename:requirements.txt` | S1 | 200 | 5 | 3 |
| `generativelanguage.googleapis.com path:cassettes` | S1 | 200 | 28 | 3 |
| `generativelanguage.googleapis.com path:recordings` | S1 | 200 | 1 | 3 |
| `generativelanguage.googleapis.com path:vcr` | S1 | 429 | None | 0 |
| `openai.azure.com path:cassettes` | S1 | 429 | None | 0 |
| `openai.azure.com path:recordings` | S1 | 200 | 0 | 0 |
| `openai.azure.com path:vcr` | S1 | 200 | 0 | 0 |
| `openrouter.ai path:cassettes` | S1 | 200 | 0 | 0 |
| `openrouter.ai path:recordings` | S1 | 200 | 3 | 3 |
| `openrouter.ai path:vcr` | S1 | 200 | 0 | 0 |
| `pytest-agentcontract filename:package.json` | S1 | 200 | 0 | 0 |
| `pytest-agentcontract filename:pyproject.toml` | S1 | 200 | 0 | 0 |
| `pytest-agentcontract filename:requirements.txt` | S1 | 200 | 0 | 0 |
| `is:public created:>=2024-01-01 "api costs" test (llm OR openai OR agent)` | S2 | 200 | 112945 | 10 |
| `is:public created:>=2024-01-01 "expensive tests" (llm OR openai OR agent)` | S2 | 200 | 28546 | 10 |
| `is:public created:>=2024-01-01 "fails randomly" "ai sdk" test` | S2 | 200 | 41 | 3 |
| `is:public created:>=2024-01-01 "fails randomly" "llama-index" test` | S2 | 200 | 12 | 3 |
| `is:public created:>=2024-01-01 "fails randomly" "model output" test` | S2 | 200 | 89 | 3 |
| `is:public created:>=2024-01-01 "fails randomly" "pydantic-ai" test` | S2 | 200 | 11 | 3 |
| `is:public created:>=2024-01-01 "fails randomly" agent test` | S2 | 200 | 922 | 12 |
| `is:public created:>=2024-01-01 "fails randomly" anthropic test` | S2 | 200 | 106 | 4 |
| `is:public created:>=2024-01-01 "fails randomly" autogen test` | S2 | 200 | 6 | 3 |
| `is:public created:>=2024-01-01 "fails randomly" claude test` | S2 | 200 | 740 | 10 |
| `is:public created:>=2024-01-01 "fails randomly" crewai test` | S2 | 200 | 4 | 3 |
| `is:public created:>=2024-01-01 "fails randomly" eval test` | S2 | 200 | 181 | 4 |
| `is:public created:>=2024-01-01 "fails randomly" gemini test` | S2 | 200 | 92 | 3 |
| `is:public created:>=2024-01-01 "fails randomly" gpt test` | S2 | 200 | 109 | 4 |
| `is:public created:>=2024-01-01 "fails randomly" langchain test` | S2 | 200 | 6 | 3 |
| `is:public created:>=2024-01-01 "fails randomly" langgraph test` | S2 | 200 | 6 | 3 |
| `is:public created:>=2024-01-01 "fails randomly" llamaindex test` | S2 | 200 | 4 | 3 |
| `is:public created:>=2024-01-01 "fails randomly" llm test` | S2 | 200 | 196 | 4 |
| `is:public created:>=2024-01-01 "fails randomly" openai test` | S2 | 200 | 186 | 4 |
| `is:public created:>=2024-01-01 "fails randomly" prompt test` | S2 | 200 | 538 | 8 |
| `is:public created:>=2024-01-01 "live llm" (llm OR openai OR agent)` | S2 | 200 | 133394 | 10 |
| `is:public created:>=2024-01-01 "llm tests" (llm OR openai OR agent)` | S2 | 200 | 403141 | 10 |
| `is:public created:>=2024-01-01 "mock llm" (llm OR openai OR agent)` | S2 | 200 | 88202 | 10 |
| `is:public created:>=2024-01-01 "mock the llm" (llm OR openai OR agent)` | S2 | 200 | 32680 | 10 |
| `is:public created:>=2024-01-01 "non deterministic" "ai sdk" test` | S2 | 200 | 4713 | 58 |
| `is:public created:>=2024-01-01 "non deterministic" "llama-index" test` | S2 | 200 | 393 | 6 |
| `is:public created:>=2024-01-01 "non deterministic" "model output" test` | S2 | 200 | 19910 | 240 |
| `is:public created:>=2024-01-01 "non deterministic" "pydantic-ai" test` | S2 | 200 | 961 | 12 |
| `is:public created:>=2024-01-01 "non deterministic" agent test` | S2 | 200 | 163655 | 10 |
| `is:public created:>=2024-01-01 "non deterministic" anthropic test` | S2 | 200 | 15640 | 189 |
| `is:public created:>=2024-01-01 "non deterministic" autogen test` | S2 | 200 | 383 | 6 |
| `is:public created:>=2024-01-01 "non deterministic" claude test` | S2 | 200 | 105789 | 10 |
| `is:public created:>=2024-01-01 "non deterministic" crewai test` | S2 | 200 | 411 | 7 |
| `is:public created:>=2024-01-01 "non deterministic" eval test` | S2 | 200 | 24342 | 10 |
| `is:public created:>=2024-01-01 "non deterministic" gemini test` | S2 | 200 | 22233 | 10 |
| `is:public created:>=2024-01-01 "non deterministic" gpt test` | S2 | 200 | 15719 | 190 |
| `is:public created:>=2024-01-01 "non deterministic" langchain test` | S2 | 200 | 2910 | 36 |
| `is:public created:>=2024-01-01 "non deterministic" langgraph test` | S2 | 200 | 1984 | 24 |
| `is:public created:>=2024-01-01 "non deterministic" llamaindex test` | S2 | 200 | 246 | 5 |
| `is:public created:>=2024-01-01 "non deterministic" llm test` | S2 | 200 | 40158 | 10 |
| `is:public created:>=2024-01-01 "non deterministic" openai test` | S2 | 200 | 23826 | 10 |
| `is:public created:>=2024-01-01 "non deterministic" prompt test` | S2 | 200 | 113025 | 10 |
| `is:public created:>=2024-01-01 "non-deterministic" "ai sdk" test` | S2 | 200 | 4713 | 58 |
| `is:public created:>=2024-01-01 "non-deterministic" "llama-index" test` | S2 | 200 | 393 | 6 |
| `is:public created:>=2024-01-01 "non-deterministic" "model output" test` | S2 | 200 | 19910 | 240 |
| `is:public created:>=2024-01-01 "non-deterministic" "pydantic-ai" test` | S2 | 200 | 961 | 12 |
| `is:public created:>=2024-01-01 "non-deterministic" agent test` | S2 | 200 | 163654 | 10 |
| `is:public created:>=2024-01-01 "non-deterministic" anthropic test` | S2 | 200 | 15640 | 189 |
| `is:public created:>=2024-01-01 "non-deterministic" autogen test` | S2 | 200 | 383 | 6 |
| `is:public created:>=2024-01-01 "non-deterministic" claude test` | S2 | 200 | 105789 | 10 |
| `is:public created:>=2024-01-01 "non-deterministic" crewai test` | S2 | 200 | 411 | 7 |
| `is:public created:>=2024-01-01 "non-deterministic" eval test` | S2 | 200 | 24342 | 10 |
| `is:public created:>=2024-01-01 "non-deterministic" gemini test` | S2 | 200 | 22233 | 10 |
| `is:public created:>=2024-01-01 "non-deterministic" gpt test` | S2 | 200 | 15719 | 190 |
| `is:public created:>=2024-01-01 "non-deterministic" langchain test` | S2 | 200 | 2910 | 36 |
| `is:public created:>=2024-01-01 "non-deterministic" langgraph test` | S2 | 200 | 1984 | 24 |
| `is:public created:>=2024-01-01 "non-deterministic" llamaindex test` | S2 | 200 | 246 | 5 |
| `is:public created:>=2024-01-01 "non-deterministic" llm test` | S2 | 200 | 40158 | 10 |
| `is:public created:>=2024-01-01 "non-deterministic" openai test` | S2 | 200 | 23826 | 10 |
| `is:public created:>=2024-01-01 "non-deterministic" prompt test` | S2 | 200 | 113025 | 10 |
| `is:public created:>=2024-01-01 "randomly fails" "ai sdk" test` | S2 | 200 | 41 | 3 |
| `is:public created:>=2024-01-01 "randomly fails" "llama-index" test` | S2 | 200 | 12 | 3 |
| `is:public created:>=2024-01-01 "randomly fails" "model output" test` | S2 | 200 | 93 | 3 |
| `is:public created:>=2024-01-01 "randomly fails" "pydantic-ai" test` | S2 | 200 | 12 | 3 |
| `is:public created:>=2024-01-01 "randomly fails" agent test` | S2 | 200 | 933 | 12 |
| `is:public created:>=2024-01-01 "randomly fails" anthropic test` | S2 | 200 | 107 | 4 |
| `is:public created:>=2024-01-01 "randomly fails" autogen test` | S2 | 200 | 6 | 3 |
| `is:public created:>=2024-01-01 "randomly fails" claude test` | S2 | 200 | 742 | 10 |
| `is:public created:>=2024-01-01 "randomly fails" crewai test` | S2 | 200 | 6 | 3 |
| `is:public created:>=2024-01-01 "randomly fails" eval test` | S2 | 200 | 176 | 4 |
| `is:public created:>=2024-01-01 "randomly fails" gemini test` | S2 | 200 | 93 | 3 |
| `is:public created:>=2024-01-01 "randomly fails" gpt test` | S2 | 200 | 108 | 4 |
| `is:public created:>=2024-01-01 "randomly fails" langchain test` | S2 | 200 | 6 | 3 |
| `is:public created:>=2024-01-01 "randomly fails" langgraph test` | S2 | 200 | 6 | 3 |
| `is:public created:>=2024-01-01 "randomly fails" llamaindex test` | S2 | 200 | 3 | 3 |
| `is:public created:>=2024-01-01 "randomly fails" llm test` | S2 | 200 | 195 | 4 |
| `is:public created:>=2024-01-01 "randomly fails" openai test` | S2 | 200 | 182 | 4 |
| `is:public created:>=2024-01-01 "randomly fails" prompt test` | S2 | 200 | 543 | 8 |
| `is:public created:>=2024-01-01 "real llm" test (llm OR openai OR agent)` | S2 | 200 | 161235 | 10 |
| `is:public created:>=2024-01-01 "record and replay" llm (llm OR openai OR agent)` | S2 | 200 | 15537 | 188 |
| `is:public created:>=2024-01-01 "skip llm" (llm OR openai OR agent)` | S2 | 200 | 107469 | 10 |
| `is:public created:>=2024-01-01 "tests are expensive" (llm OR openai OR agent)` | S2 | 200 | 3185 | 40 |
| `is:public created:>=2024-01-01 "token cost" test (llm OR openai OR agent)` | S2 | 200 | 442234 | 10 |
| `is:public created:>=2024-01-01 cassette llm (llm OR openai OR agent)` | S2 | 200 | 9176 | 112 |
| `is:public created:>=2024-01-01 flakiness "ai sdk" test` | S2 | 200 | 3795 | 46 |
| `is:public created:>=2024-01-01 flakiness "llama-index" test` | S2 | 200 | 175 | 4 |
| `is:public created:>=2024-01-01 flakiness "model output" test` | S2 | 200 | 8827 | 107 |
| `is:public created:>=2024-01-01 flakiness "pydantic-ai" test` | S2 | 200 | 515 | 8 |
| `is:public created:>=2024-01-01 flakiness agent test` | S2 | 200 | 145206 | 10 |
| `is:public created:>=2024-01-01 flakiness anthropic test` | S2 | 200 | 11465 | 139 |
| `is:public created:>=2024-01-01 flakiness autogen test` | S2 | 200 | 329 | 6 |
| `is:public created:>=2024-01-01 flakiness claude test` | S2 | 200 | 103973 | 10 |
| `is:public created:>=2024-01-01 flakiness crewai test` | S2 | 200 | 203 | 5 |
| `is:public created:>=2024-01-01 flakiness eval test` | S2 | 200 | 32099 | 10 |
| `is:public created:>=2024-01-01 flakiness gemini test` | S2 | 200 | 18138 | 220 |
| `is:public created:>=2024-01-01 flakiness gpt test` | S2 | 200 | 10074 | 123 |
| `is:public created:>=2024-01-01 flakiness langchain test` | S2 | 200 | 2239 | 29 |
| `is:public created:>=2024-01-01 flakiness langgraph test` | S2 | 200 | 994 | 12 |
| `is:public created:>=2024-01-01 flakiness llamaindex test` | S2 | 200 | 113 | 4 |
| `is:public created:>=2024-01-01 flakiness llm test` | S2 | 200 | 20340 | 10 |
| `is:public created:>=2024-01-01 flakiness openai test` | S2 | 200 | 16448 | 199 |
| `is:public created:>=2024-01-01 flakiness prompt test` | S2 | 200 | 92967 | 10 |
| `is:public created:>=2024-01-01 flaky "ai sdk" test` | S2 | 200 | 34125 | 10 |
| `is:public created:>=2024-01-01 flaky "llama-index" test` | S2 | 200 | 1571 | 20 |
| `is:public created:>=2024-01-01 flaky "model output" test` | S2 | 200 | 52828 | 10 |
| `is:public created:>=2024-01-01 flaky "pydantic-ai" test` | S2 | 200 | 6761 | 82 |
| `is:public created:>=2024-01-01 flaky agent test` | S2 | 200 | 1159483 | 10 |
| `is:public created:>=2024-01-01 flaky anthropic test` | S2 | 200 | 87151 | 10 |
| `is:public created:>=2024-01-01 flaky autogen test` | S2 | 200 | 3015 | 39 |
| `is:public created:>=2024-01-01 flaky claude test` | S2 | 200 | 949648 | 10 |
| `is:public created:>=2024-01-01 flaky crewai test` | S2 | 200 | 1795 | 22 |
| `is:public created:>=2024-01-01 flaky eval test` | S2 | 200 | 155370 | 10 |
| `is:public created:>=2024-01-01 flaky gemini test` | S2 | 200 | 112518 | 10 |
| `is:public created:>=2024-01-01 flaky gpt test` | S2 | 200 | 90035 | 10 |
| `is:public created:>=2024-01-01 flaky langchain test` | S2 | 200 | 21427 | 10 |
| `is:public created:>=2024-01-01 flaky langgraph test` | S2 | 200 | 12113 | 148 |
| `is:public created:>=2024-01-01 flaky llamaindex test` | S2 | 200 | 813 | 11 |
| `is:public created:>=2024-01-01 flaky llm test` | S2 | 200 | 145954 | 10 |
| `is:public created:>=2024-01-01 flaky openai test` | S2 | 200 | 121412 | 10 |
| `is:public created:>=2024-01-01 flaky prompt test` | S2 | 200 | 643170 | 10 |
| `is:public created:>=2024-01-01 intermittent "ai sdk" test` | S2 | 200 | 5014 | 63 |
| `is:public created:>=2024-01-01 intermittent "llama-index" test` | S2 | 200 | 226 | 5 |
| `is:public created:>=2024-01-01 intermittent "model output" test` | S2 | 200 | 13885 | 167 |
| `is:public created:>=2024-01-01 intermittent "pydantic-ai" test` | S2 | 200 | 514 | 8 |
| `is:public created:>=2024-01-01 intermittent agent test` | S2 | 200 | 233677 | 10 |
| `is:public created:>=2024-01-01 intermittent anthropic test` | S2 | 200 | 20803 | 10 |
| `is:public created:>=2024-01-01 intermittent autogen test` | S2 | 200 | 369 | 6 |
| `is:public created:>=2024-01-01 intermittent claude test` | S2 | 200 | 210179 | 10 |
| `is:public created:>=2024-01-01 intermittent crewai test` | S2 | 200 | 283 | 5 |
| `is:public created:>=2024-01-01 intermittent eval test` | S2 | 200 | 22089 | 10 |
| `is:public created:>=2024-01-01 intermittent gemini test` | S2 | 200 | 18270 | 221 |
| `is:public created:>=2024-01-01 intermittent gpt test` | S2 | 200 | 24523 | 10 |
| `is:public created:>=2024-01-01 intermittent langchain test` | S2 | 200 | 1845 | 23 |
| `is:public created:>=2024-01-01 intermittent langgraph test` | S2 | 200 | 1130 | 16 |
| `is:public created:>=2024-01-01 intermittent llamaindex test` | S2 | 200 | 153 | 4 |
| `is:public created:>=2024-01-01 intermittent llm test` | S2 | 200 | 27096 | 10 |
| `is:public created:>=2024-01-01 intermittent openai test` | S2 | 200 | 31140 | 10 |
| `is:public created:>=2024-01-01 intermittent prompt test` | S2 | 200 | 122229 | 10 |
| `is:public created:>=2024-01-01 nondeterministic "ai sdk" test` | S2 | 200 | 1316 | 18 |
| `is:public created:>=2024-01-01 nondeterministic "llama-index" test` | S2 | 200 | 76 | 3 |
| `is:public created:>=2024-01-01 nondeterministic "model output" test` | S2 | 200 | 7100 | 87 |
| `is:public created:>=2024-01-01 nondeterministic "pydantic-ai" test` | S2 | 200 | 298 | 5 |
| `is:public created:>=2024-01-01 nondeterministic agent test` | S2 | 200 | 59038 | 10 |
| `is:public created:>=2024-01-01 nondeterministic anthropic test` | S2 | 200 | 4341 | 54 |
| `is:public created:>=2024-01-01 nondeterministic autogen test` | S2 | 200 | 134 | 4 |
| `is:public created:>=2024-01-01 nondeterministic claude test` | S2 | 200 | 40010 | 10 |
| `is:public created:>=2024-01-01 nondeterministic crewai test` | S2 | 200 | 98 | 3 |
| `is:public created:>=2024-01-01 nondeterministic eval test` | S2 | 200 | 10173 | 124 |
| `is:public created:>=2024-01-01 nondeterministic gemini test` | S2 | 200 | 5224 | 65 |
| `is:public created:>=2024-01-01 nondeterministic gpt test` | S2 | 200 | 6870 | 83 |
| `is:public created:>=2024-01-01 nondeterministic langchain test` | S2 | 200 | 568 | 8 |
| `is:public created:>=2024-01-01 nondeterministic langgraph test` | S2 | 200 | 439 | 7 |
| `is:public created:>=2024-01-01 nondeterministic llamaindex test` | S2 | 200 | 59 | 3 |
| `is:public created:>=2024-01-01 nondeterministic llm test` | S2 | 200 | 10795 | 130 |
| `is:public created:>=2024-01-01 nondeterministic openai test` | S2 | 200 | 8122 | 100 |
| `is:public created:>=2024-01-01 nondeterministic prompt test` | S2 | 200 | 42353 | 10 |
| `is:public created:>=2024-01-01 rerun "ai sdk" test` | S2 | 200 | 20586 | 10 |
| `is:public created:>=2024-01-01 rerun "llama-index" test` | S2 | 200 | 2107 | 28 |
| `is:public created:>=2024-01-01 rerun "model output" test` | S2 | 200 | 107373 | 10 |
| `is:public created:>=2024-01-01 rerun "pydantic-ai" test` | S2 | 200 | 3172 | 40 |
| `is:public created:>=2024-01-01 rerun agent test` | S2 | 200 | 1349796 | 10 |
| `is:public created:>=2024-01-01 rerun anthropic test` | S2 | 200 | 114381 | 10 |
| `is:public created:>=2024-01-01 rerun autogen test` | S2 | 200 | 1771 | 22 |
| `is:public created:>=2024-01-01 rerun claude test` | S2 | 200 | 1184924 | 10 |
| `is:public created:>=2024-01-01 rerun crewai test` | S2 | 200 | 1268 | 17 |
| `is:public created:>=2024-01-01 rerun eval test` | S2 | 200 | 144791 | 10 |
| `is:public created:>=2024-01-01 rerun gemini test` | S2 | 200 | 111657 | 10 |
| `is:public created:>=2024-01-01 rerun gpt test` | S2 | 200 | 274215 | 10 |
| `is:public created:>=2024-01-01 rerun langchain test` | S2 | 200 | 11136 | 136 |
| `is:public created:>=2024-01-01 rerun langgraph test` | S2 | 200 | 7408 | 91 |
| `is:public created:>=2024-01-01 rerun llamaindex test` | S2 | 200 | 826 | 11 |
| `is:public created:>=2024-01-01 rerun llm test` | S2 | 200 | 172959 | 10 |
| `is:public created:>=2024-01-01 rerun openai test` | S2 | 200 | 201398 | 10 |
| `is:public created:>=2024-01-01 rerun prompt test` | S2 | 200 | 723319 | 10 |
| `is:public created:>=2024-01-01 retry "ai sdk" test` | S2 | 200 | 131754 | 10 |
| `is:public created:>=2024-01-01 retry "llama-index" test` | S2 | 200 | 4369 | 54 |
| `is:public created:>=2024-01-01 retry "model output" test` | S2 | 200 | 283268 | 10 |
| `is:public created:>=2024-01-01 retry "pydantic-ai" test` | S2 | 200 | 19080 | 231 |
| `is:public created:>=2024-01-01 retry agent test` | S2 | 200 | 4186392 | 10 |
| `is:public created:>=2024-01-01 retry anthropic test` | S2 | 200 | 385477 | 10 |
| `is:public created:>=2024-01-01 retry autogen test` | S2 | 200 | 9537 | 116 |
| `is:public created:>=2024-01-01 retry claude test` | S2 | 200 | 3388715 | 10 |
| `is:public created:>=2024-01-01 retry crewai test` | S2 | 200 | 6075 | 75 |
| `is:public created:>=2024-01-01 retry eval test` | S2 | 200 | 420122 | 10 |
| `is:public created:>=2024-01-01 retry gemini test` | S2 | 200 | 363681 | 10 |
| `is:public created:>=2024-01-01 retry gpt test` | S2 | 200 | 531667 | 10 |
| `is:public created:>=2024-01-01 retry langchain test` | S2 | 200 | 56762 | 10 |
| `is:public created:>=2024-01-01 retry langgraph test` | S2 | 200 | 36734 | 10 |
| `is:public created:>=2024-01-01 retry llamaindex test` | S2 | 200 | 3750 | 46 |
| `is:public created:>=2024-01-01 retry llm test` | S2 | 200 | 594448 | 10 |
| `is:public created:>=2024-01-01 retry openai test` | S2 | 200 | 613353 | 10 |
| `is:public created:>=2024-01-01 retry prompt test` | S2 | 200 | 2356065 | 10 |
| `is:public created:>=2024-01-01 unstable "ai sdk" test` | S2 | 200 | 13624 | 165 |
| `is:public created:>=2024-01-01 unstable "llama-index" test` | S2 | 200 | 1405 | 19 |
| `is:public created:>=2024-01-01 unstable "model output" test` | S2 | 200 | 17673 | 213 |
| `is:public created:>=2024-01-01 unstable "pydantic-ai" test` | S2 | 200 | 1314 | 18 |
| `is:public created:>=2024-01-01 unstable agent test` | S2 | 200 | 271813 | 10 |
| `is:public created:>=2024-01-01 unstable anthropic test` | S2 | 200 | 27903 | 10 |
| `is:public created:>=2024-01-01 unstable autogen test` | S2 | 200 | 1617 | 21 |
| `is:public created:>=2024-01-01 unstable claude test` | S2 | 200 | 171271 | 10 |
| `is:public created:>=2024-01-01 unstable crewai test` | S2 | 200 | 608 | 9 |
| `is:public created:>=2024-01-01 unstable eval test` | S2 | 200 | 110537 | 10 |
| `is:public created:>=2024-01-01 unstable gemini test` | S2 | 200 | 26445 | 10 |
| `is:public created:>=2024-01-01 unstable gpt test` | S2 | 200 | 28358 | 10 |
| `is:public created:>=2024-01-01 unstable langchain test` | S2 | 200 | 7379 | 90 |
| `is:public created:>=2024-01-01 unstable langgraph test` | S2 | 200 | 5396 | 66 |
| `is:public created:>=2024-01-01 unstable llamaindex test` | S2 | 200 | 244 | 5 |
| `is:public created:>=2024-01-01 unstable llm test` | S2 | 200 | 46013 | 10 |
| `is:public created:>=2024-01-01 unstable openai test` | S2 | 200 | 39015 | 10 |
| `is:public created:>=2024-01-01 unstable prompt test` | S2 | 200 | 152834 | 10 |
| `is:public created:>=2024-01-01 vcr openai (llm OR openai OR agent)` | S2 | 200 | 6635 | 81 |
| `is:public created:>=2024-01-01 xfail "ai sdk" test` | S2 | 200 | 1359 | 18 |
| `is:public created:>=2024-01-01 xfail "llama-index" test` | S2 | 200 | 184 | 4 |
| `is:public created:>=2024-01-01 xfail "model output" test` | S2 | 200 | 5284 | 65 |
| `is:public created:>=2024-01-01 xfail "pydantic-ai" test` | S2 | 200 | 1469 | 19 |
| `is:public created:>=2024-01-01 xfail agent test` | S2 | 200 | 50306 | 10 |
| `is:public created:>=2024-01-01 xfail anthropic test` | S2 | 200 | 7000 | 84 |
| `is:public created:>=2024-01-01 xfail autogen test` | S2 | 200 | 266 | 5 |
| `is:public created:>=2024-01-01 xfail claude test` | S2 | 200 | 70514 | 10 |
| `is:public created:>=2024-01-01 xfail crewai test` | S2 | 200 | 186 | 4 |
| `is:public created:>=2024-01-01 xfail eval test` | S2 | 200 | 12136 | 148 |
| `is:public created:>=2024-01-01 xfail gemini test` | S2 | 200 | 4293 | 53 |
| `is:public created:>=2024-01-01 xfail gpt test` | S2 | 200 | 7217 | 89 |
| `is:public created:>=2024-01-01 xfail langchain test` | S2 | 200 | 3681 | 45 |
| `is:public created:>=2024-01-01 xfail langgraph test` | S2 | 200 | 1679 | 21 |
| `is:public created:>=2024-01-01 xfail llamaindex test` | S2 | 200 | 99 | 3 |
| `is:public created:>=2024-01-01 xfail llm test` | S2 | 200 | 12446 | 151 |
| `is:public created:>=2024-01-01 xfail openai test` | S2 | 200 | 9523 | 116 |
| `is:public created:>=2024-01-01 xfail prompt test` | S2 | 200 | 49403 | 10 |
| `committer-date:>=2024-01-01 "api costs" test agent` | S3 | 200 | 2341 | 30 |
| `committer-date:>=2024-01-01 "api costs" test llm` | S3 | 200 | 2213 | 29 |
| `committer-date:>=2024-01-01 "api costs" test openai` | S3 | 200 | 1619 | 21 |
| `committer-date:>=2024-01-01 "expensive tests" agent` | S3 | 200 | 418 | 7 |
| `committer-date:>=2024-01-01 "expensive tests" llm` | S3 | 200 | 88 | 3 |
| `committer-date:>=2024-01-01 "expensive tests" openai` | S3 | 200 | 46 | 3 |
| `committer-date:>=2024-01-01 "fails randomly" "ai sdk" test` | S3 | 200 | 1 | 3 |
| `committer-date:>=2024-01-01 "fails randomly" "llama-index" test` | S3 | 200 | 0 | 0 |
| `committer-date:>=2024-01-01 "fails randomly" "model output" test` | S3 | 200 | 0 | 0 |
| `committer-date:>=2024-01-01 "fails randomly" "pydantic-ai" test` | S3 | 200 | 0 | 0 |
| `committer-date:>=2024-01-01 "fails randomly" agent test` | S3 | 200 | 188 | 4 |
| `committer-date:>=2024-01-01 "fails randomly" anthropic test` | S3 | 200 | 574 | 8 |
| `committer-date:>=2024-01-01 "fails randomly" autogen test` | S3 | 200 | 19 | 3 |
| `committer-date:>=2024-01-01 "fails randomly" claude test` | S3 | 200 | 613 | 9 |
| `committer-date:>=2024-01-01 "fails randomly" crewai test` | S3 | 200 | 0 | 0 |
| `committer-date:>=2024-01-01 "fails randomly" eval test` | S3 | 200 | 72 | 3 |
| `committer-date:>=2024-01-01 "fails randomly" gemini test` | S3 | 200 | 8 | 3 |
| `committer-date:>=2024-01-01 "fails randomly" gpt test` | S3 | 200 | 17 | 3 |
| `committer-date:>=2024-01-01 "fails randomly" langchain test` | S3 | 200 | 0 | 0 |
| `committer-date:>=2024-01-01 "fails randomly" langgraph test` | S3 | 200 | 1 | 3 |
| `committer-date:>=2024-01-01 "fails randomly" llamaindex test` | S3 | 200 | 0 | 0 |
| `committer-date:>=2024-01-01 "fails randomly" llm test` | S3 | 200 | 28 | 3 |
| `committer-date:>=2024-01-01 "fails randomly" openai test` | S3 | 200 | 6 | 3 |
| `committer-date:>=2024-01-01 "fails randomly" prompt test` | S3 | 200 | 55 | 3 |
| `committer-date:>=2024-01-01 "live llm" test` | S3 | 200 | 19248 | 233 |
| `committer-date:>=2024-01-01 "llm tests" test` | S3 | 200 | 46260 | 10 |
| `committer-date:>=2024-01-01 "mock llm" test` | S3 | 200 | 38017 | 10 |
| `committer-date:>=2024-01-01 "mock the llm" test` | S3 | 200 | 1686 | 21 |
| `committer-date:>=2024-01-01 "non deterministic" "ai sdk" test` | S3 | 200 | 225 | 5 |
| `committer-date:>=2024-01-01 "non deterministic" "llama-index" test` | S3 | 200 | 8 | 3 |
| `committer-date:>=2024-01-01 "non deterministic" "model output" test` | S3 | 200 | 918 | 12 |
| `committer-date:>=2024-01-01 "non deterministic" "pydantic-ai" test` | S3 | 200 | 37 | 3 |
| `committer-date:>=2024-01-01 "non deterministic" agent test` | S3 | 200 | 14695 | 177 |
| `committer-date:>=2024-01-01 "non deterministic" anthropic test` | S3 | 200 | 33996 | 10 |
| `committer-date:>=2024-01-01 "non deterministic" autogen test` | S3 | 200 | 35 | 3 |
| `committer-date:>=2024-01-01 "non deterministic" claude test` | S3 | 200 | 44006 | 10 |
| `committer-date:>=2024-01-01 "non deterministic" crewai test` | S3 | 200 | 52 | 3 |
| `committer-date:>=2024-01-01 "non deterministic" eval test` | S3 | 200 | 5728 | 70 |
| `committer-date:>=2024-01-01 "non deterministic" gemini test` | S3 | 200 | 2620 | 33 |
| `committer-date:>=2024-01-01 "non deterministic" gpt test` | S3 | 200 | 1375 | 18 |
| `committer-date:>=2024-01-01 "non deterministic" langchain test` | S3 | 200 | 190 | 4 |
| `committer-date:>=2024-01-01 "non deterministic" langgraph test` | S3 | 200 | 199 | 4 |
| `committer-date:>=2024-01-01 "non deterministic" llamaindex test` | S3 | 200 | 33 | 3 |
| `committer-date:>=2024-01-01 "non deterministic" llm test` | S3 | 200 | 7934 | 96 |
| `committer-date:>=2024-01-01 "non deterministic" openai test` | S3 | 200 | 3779 | 46 |
| `committer-date:>=2024-01-01 "non deterministic" prompt test` | S3 | 200 | 10080 | 123 |
| `committer-date:>=2024-01-01 "non-deterministic" "ai sdk" test` | S3 | 200 | 225 | 5 |
| `committer-date:>=2024-01-01 "non-deterministic" "llama-index" test` | S3 | 200 | 8 | 3 |
| `committer-date:>=2024-01-01 "non-deterministic" "model output" test` | S3 | 200 | 920 | 12 |
| `committer-date:>=2024-01-01 "non-deterministic" "pydantic-ai" test` | S3 | 200 | 37 | 3 |
| `committer-date:>=2024-01-01 "non-deterministic" agent test` | S3 | 200 | 14695 | 177 |
| `committer-date:>=2024-01-01 "non-deterministic" anthropic test` | S3 | 200 | 34038 | 10 |
| `committer-date:>=2024-01-01 "non-deterministic" autogen test` | S3 | 200 | 35 | 3 |
| `committer-date:>=2024-01-01 "non-deterministic" claude test` | S3 | 200 | 44155 | 10 |
| `committer-date:>=2024-01-01 "non-deterministic" crewai test` | S3 | 200 | 52 | 3 |
| `committer-date:>=2024-01-01 "non-deterministic" eval test` | S3 | 200 | 5728 | 70 |
| `committer-date:>=2024-01-01 "non-deterministic" gemini test` | S3 | 200 | 2620 | 33 |
| `committer-date:>=2024-01-01 "non-deterministic" gpt test` | S3 | 200 | 1375 | 18 |
| `committer-date:>=2024-01-01 "non-deterministic" langchain test` | S3 | 200 | 190 | 4 |
| `committer-date:>=2024-01-01 "non-deterministic" langgraph test` | S3 | 200 | 199 | 4 |
| `committer-date:>=2024-01-01 "non-deterministic" llamaindex test` | S3 | 200 | 33 | 3 |
| `committer-date:>=2024-01-01 "non-deterministic" llm test` | S3 | 200 | 7949 | 96 |
| `committer-date:>=2024-01-01 "non-deterministic" openai test` | S3 | 200 | 3801 | 47 |
| `committer-date:>=2024-01-01 "non-deterministic" prompt test` | S3 | 200 | 10087 | 123 |
| `committer-date:>=2024-01-01 "randomly fails" "ai sdk" test` | S3 | 200 | 2 | 3 |
| `committer-date:>=2024-01-01 "randomly fails" "llama-index" test` | S3 | 200 | 0 | 0 |
| `committer-date:>=2024-01-01 "randomly fails" "model output" test` | S3 | 200 | 4 | 3 |
| `committer-date:>=2024-01-01 "randomly fails" "pydantic-ai" test` | S3 | 200 | 0 | 0 |
| `committer-date:>=2024-01-01 "randomly fails" agent test` | S3 | 200 | 240 | 5 |
| `committer-date:>=2024-01-01 "randomly fails" anthropic test` | S3 | 200 | 513 | 8 |
| `committer-date:>=2024-01-01 "randomly fails" autogen test` | S3 | 200 | 0 | 0 |
| `committer-date:>=2024-01-01 "randomly fails" claude test` | S3 | 200 | 631 | 9 |
| `committer-date:>=2024-01-01 "randomly fails" crewai test` | S3 | 200 | 7 | 3 |
| `committer-date:>=2024-01-01 "randomly fails" eval test` | S3 | 200 | 52 | 3 |
| `committer-date:>=2024-01-01 "randomly fails" gemini test` | S3 | 200 | 5 | 3 |
| `committer-date:>=2024-01-01 "randomly fails" gpt test` | S3 | 200 | 9 | 3 |
| `committer-date:>=2024-01-01 "randomly fails" langchain test` | S3 | 200 | 0 | 0 |
| `committer-date:>=2024-01-01 "randomly fails" langgraph test` | S3 | 200 | 0 | 0 |
| `committer-date:>=2024-01-01 "randomly fails" llamaindex test` | S3 | 200 | 0 | 0 |
| `committer-date:>=2024-01-01 "randomly fails" llm test` | S3 | 200 | 57 | 3 |
| `committer-date:>=2024-01-01 "randomly fails" openai test` | S3 | 200 | 7 | 3 |
| `committer-date:>=2024-01-01 "randomly fails" prompt test` | S3 | 200 | 70 | 3 |
| `committer-date:>=2024-01-01 "real llm" test` | S3 | 200 | 42900 | 10 |
| `committer-date:>=2024-01-01 "record and replay" llm test` | S3 | 200 | 411 | 7 |
| `committer-date:>=2024-01-01 "skip llm" test` | S3 | 200 | 8498 | 103 |
| `committer-date:>=2024-01-01 "tests are expensive" agent` | S3 | 200 | 10 | 3 |
| `committer-date:>=2024-01-01 "tests are expensive" llm` | S3 | 200 | 4 | 3 |
| `committer-date:>=2024-01-01 "tests are expensive" openai` | S3 | 200 | 4 | 3 |
| `committer-date:>=2024-01-01 "token cost" test agent` | S3 | 200 | 27965 | 10 |
| `committer-date:>=2024-01-01 "token cost" test llm` | S3 | 200 | 12642 | 153 |
| `committer-date:>=2024-01-01 "token cost" test openai` | S3 | 200 | 9601 | 117 |
| `committer-date:>=2024-01-01 cassette llm test` | S3 | 200 | 5448 | 67 |
| `committer-date:>=2024-01-01 flakiness "ai sdk" test` | S3 | 200 | 1438 | 19 |
| `committer-date:>=2024-01-01 flakiness "llama-index" test` | S3 | 200 | 57 | 3 |
| `committer-date:>=2024-01-01 flakiness "model output" test` | S3 | 200 | 1036 | 15 |
| `committer-date:>=2024-01-01 flakiness "pydantic-ai" test` | S3 | 200 | 313 | 6 |
| `committer-date:>=2024-01-01 flakiness agent test` | S3 | 200 | 130552 | 10 |
| `committer-date:>=2024-01-01 flakiness anthropic test` | S3 | 200 | 312833 | 10 |
| `committer-date:>=2024-01-01 flakiness autogen test` | S3 | 200 | 279 | 5 |
| `committer-date:>=2024-01-01 flakiness claude test` | S3 | 200 | 350093 | 10 |
| `committer-date:>=2024-01-01 flakiness crewai test` | S3 | 200 | 331 | 6 |
| `committer-date:>=2024-01-01 flakiness eval test` | S3 | 200 | 23386 | 10 |
| `committer-date:>=2024-01-01 flakiness gemini test` | S3 | 200 | 18551 | 224 |
| `committer-date:>=2024-01-01 flakiness gpt test` | S3 | 200 | 13489 | 163 |
| `committer-date:>=2024-01-01 flakiness langchain test` | S3 | 200 | 3398 | 42 |
| `committer-date:>=2024-01-01 flakiness langgraph test` | S3 | 200 | 1814 | 23 |
| `committer-date:>=2024-01-01 flakiness llamaindex test` | S3 | 200 | 112 | 4 |
| `committer-date:>=2024-01-01 flakiness llm test` | S3 | 200 | 31727 | 10 |
| `committer-date:>=2024-01-01 flakiness openai test` | S3 | 200 | 33655 | 10 |
| `committer-date:>=2024-01-01 flakiness prompt test` | S3 | 200 | 62078 | 10 |
| `committer-date:>=2024-01-01 flaky "ai sdk" test` | S3 | 200 | 1439 | 19 |
| `committer-date:>=2024-01-01 flaky "llama-index" test` | S3 | 200 | 57 | 3 |
| `committer-date:>=2024-01-01 flaky "model output" test` | S3 | 200 | 1038 | 15 |
| `committer-date:>=2024-01-01 flaky "pydantic-ai" test` | S3 | 200 | 313 | 6 |
| `committer-date:>=2024-01-01 flaky agent test` | S3 | 200 | 130585 | 10 |
| `committer-date:>=2024-01-01 flaky anthropic test` | S3 | 200 | 311794 | 10 |
| `committer-date:>=2024-01-01 flaky autogen test` | S3 | 200 | 279 | 5 |
| `committer-date:>=2024-01-01 flaky claude test` | S3 | 200 | 349908 | 10 |
| `committer-date:>=2024-01-01 flaky crewai test` | S3 | 200 | 331 | 6 |
| `committer-date:>=2024-01-01 flaky eval test` | S3 | 200 | 23367 | 10 |
| `committer-date:>=2024-01-01 flaky gemini test` | S3 | 200 | 18548 | 224 |
| `committer-date:>=2024-01-01 flaky gpt test` | S3 | 200 | 13486 | 163 |
| `committer-date:>=2024-01-01 flaky langchain test` | S3 | 200 | 3398 | 42 |
| `committer-date:>=2024-01-01 flaky langgraph test` | S3 | 200 | 1813 | 23 |
| `committer-date:>=2024-01-01 flaky llamaindex test` | S3 | 200 | 112 | 4 |
| `committer-date:>=2024-01-01 flaky llm test` | S3 | 200 | 31678 | 10 |
| `committer-date:>=2024-01-01 flaky openai test` | S3 | 200 | 33655 | 10 |
| `committer-date:>=2024-01-01 flaky prompt test` | S3 | 200 | 62054 | 10 |
| `committer-date:>=2024-01-01 intermittent "ai sdk" test` | S3 | 200 | 405 | 7 |
| `committer-date:>=2024-01-01 intermittent "llama-index" test` | S3 | 200 | 23 | 3 |
| `committer-date:>=2024-01-01 intermittent "model output" test` | S3 | 200 | 781 | 10 |
| `committer-date:>=2024-01-01 intermittent "pydantic-ai" test` | S3 | 200 | 72 | 3 |
| `committer-date:>=2024-01-01 intermittent agent test` | S3 | 200 | 41307 | 10 |
| `committer-date:>=2024-01-01 intermittent anthropic test` | S3 | 200 | 126549 | 10 |
| `committer-date:>=2024-01-01 intermittent autogen test` | S3 | 200 | 78 | 3 |
| `committer-date:>=2024-01-01 intermittent claude test` | S3 | 200 | 141567 | 10 |
| `committer-date:>=2024-01-01 intermittent crewai test` | S3 | 200 | 94 | 3 |
| `committer-date:>=2024-01-01 intermittent eval test` | S3 | 200 | 6465 | 79 |
| `committer-date:>=2024-01-01 intermittent gemini test` | S3 | 200 | 6775 | 82 |
| `committer-date:>=2024-01-01 intermittent gpt test` | S3 | 200 | 7854 | 95 |
| `committer-date:>=2024-01-01 intermittent langchain test` | S3 | 200 | 284 | 5 |
| `committer-date:>=2024-01-01 intermittent langgraph test` | S3 | 200 | 267 | 5 |
| `committer-date:>=2024-01-01 intermittent llamaindex test` | S3 | 200 | 30 | 3 |
| `committer-date:>=2024-01-01 intermittent llm test` | S3 | 200 | 10715 | 130 |
| `committer-date:>=2024-01-01 intermittent openai test` | S3 | 200 | 14943 | 180 |
| `committer-date:>=2024-01-01 intermittent prompt test` | S3 | 200 | 23885 | 10 |
| `committer-date:>=2024-01-01 nondeterministic "ai sdk" test` | S3 | 200 | 39 | 3 |
| `committer-date:>=2024-01-01 nondeterministic "llama-index" test` | S3 | 200 | 3 | 3 |
| `committer-date:>=2024-01-01 nondeterministic "model output" test` | S3 | 200 | 255 | 5 |
| `committer-date:>=2024-01-01 nondeterministic "pydantic-ai" test` | S3 | 200 | 31 | 3 |
| `committer-date:>=2024-01-01 nondeterministic agent test` | S3 | 200 | 6729 | 82 |
| `committer-date:>=2024-01-01 nondeterministic anthropic test` | S3 | 200 | 15091 | 183 |
| `committer-date:>=2024-01-01 nondeterministic autogen test` | S3 | 200 | 5 | 3 |
| `committer-date:>=2024-01-01 nondeterministic claude test` | S3 | 200 | 19826 | 239 |
| `committer-date:>=2024-01-01 nondeterministic crewai test` | S3 | 200 | 8 | 3 |
| `committer-date:>=2024-01-01 nondeterministic eval test` | S3 | 200 | 1885 | 23 |
| `committer-date:>=2024-01-01 nondeterministic gemini test` | S3 | 200 | 422 | 7 |
| `committer-date:>=2024-01-01 nondeterministic gpt test` | S3 | 200 | 1935 | 24 |
| `committer-date:>=2024-01-01 nondeterministic langchain test` | S3 | 200 | 81 | 3 |
| `committer-date:>=2024-01-01 nondeterministic langgraph test` | S3 | 200 | 39 | 3 |
| `committer-date:>=2024-01-01 nondeterministic llamaindex test` | S3 | 200 | 7 | 3 |
| `committer-date:>=2024-01-01 nondeterministic llm test` | S3 | 200 | 2410 | 31 |
| `committer-date:>=2024-01-01 nondeterministic openai test` | S3 | 200 | 2556 | 32 |
| `committer-date:>=2024-01-01 nondeterministic prompt test` | S3 | 200 | 4018 | 51 |
| `committer-date:>=2024-01-01 rerun "ai sdk" test` | S3 | 200 | 997 | 12 |
| `committer-date:>=2024-01-01 rerun "llama-index" test` | S3 | 200 | 57 | 3 |
| `committer-date:>=2024-01-01 rerun "model output" test` | S3 | 200 | 1456 | 19 |
| `committer-date:>=2024-01-01 rerun "pydantic-ai" test` | S3 | 200 | 112 | 4 |
| `committer-date:>=2024-01-01 rerun agent test` | S3 | 200 | 159520 | 10 |
| `committer-date:>=2024-01-01 rerun anthropic test` | S3 | 200 | 265878 | 10 |
| `committer-date:>=2024-01-01 rerun autogen test` | S3 | 200 | 290 | 5 |
| `committer-date:>=2024-01-01 rerun claude test` | S3 | 200 | 314656 | 10 |
| `committer-date:>=2024-01-01 rerun crewai test` | S3 | 200 | 110 | 4 |
| `committer-date:>=2024-01-01 rerun eval test` | S3 | 200 | 28076 | 10 |
| `committer-date:>=2024-01-01 rerun gemini test` | S3 | 200 | 10219 | 125 |
| `committer-date:>=2024-01-01 rerun gpt test` | S3 | 200 | 44030 | 10 |
| `committer-date:>=2024-01-01 rerun langchain test` | S3 | 200 | 1165 | 16 |
| `committer-date:>=2024-01-01 rerun langgraph test` | S3 | 200 | 956 | 12 |
| `committer-date:>=2024-01-01 rerun llamaindex test` | S3 | 200 | 74 | 3 |
| `committer-date:>=2024-01-01 rerun llm test` | S3 | 200 | 23886 | 10 |
| `committer-date:>=2024-01-01 rerun openai test` | S3 | 200 | 50414 | 10 |
| `committer-date:>=2024-01-01 rerun prompt test` | S3 | 200 | 68628 | 10 |
| `committer-date:>=2024-01-01 retry "ai sdk" test` | S3 | 200 | 12623 | 153 |
| `committer-date:>=2024-01-01 retry "llama-index" test` | S3 | 200 | 788 | 10 |
| `committer-date:>=2024-01-01 retry "model output" test` | S3 | 200 | 12714 | 154 |
| `committer-date:>=2024-01-01 retry "pydantic-ai" test` | S3 | 200 | 2448 | 31 |
| `committer-date:>=2024-01-01 retry agent test` | S3 | 200 | 957426 | 10 |
| `committer-date:>=2024-01-01 retry anthropic test` | S3 | 200 | 1909092 | 10 |
| `committer-date:>=2024-01-01 retry autogen test` | S3 | 200 | 1201 | 17 |
| `committer-date:>=2024-01-01 retry claude test` | S3 | 200 | 1964242 | 10 |
| `committer-date:>=2024-01-01 retry crewai test` | S3 | 200 | 1958 | 24 |
| `committer-date:>=2024-01-01 retry eval test` | S3 | 200 | 111255 | 10 |
| `committer-date:>=2024-01-01 retry gemini test` | S3 | 200 | 139964 | 10 |
| `committer-date:>=2024-01-01 retry gpt test` | S3 | 200 | 141636 | 10 |
| `committer-date:>=2024-01-01 retry langchain test` | S3 | 200 | 11493 | 139 |
| `committer-date:>=2024-01-01 retry langgraph test` | S3 | 200 | 11664 | 141 |
| `committer-date:>=2024-01-01 retry llamaindex test` | S3 | 200 | 783 | 10 |
| `committer-date:>=2024-01-01 retry llm test` | S3 | 200 | 273065 | 10 |
| `committer-date:>=2024-01-01 retry openai test` | S3 | 200 | 254811 | 10 |
| `committer-date:>=2024-01-01 retry prompt test` | S3 | 200 | 536156 | 10 |
| `committer-date:>=2024-01-01 unstable "ai sdk" test` | S3 | 200 | 843 | 11 |
| `committer-date:>=2024-01-01 unstable "llama-index" test` | S3 | 200 | 44 | 3 |
| `committer-date:>=2024-01-01 unstable "model output" test` | S3 | 200 | 316 | 6 |
| `committer-date:>=2024-01-01 unstable "pydantic-ai" test` | S3 | 200 | 49 | 3 |
| `committer-date:>=2024-01-01 unstable agent test` | S3 | 200 | 21879 | 10 |
| `committer-date:>=2024-01-01 unstable anthropic test` | S3 | 200 | 52961 | 10 |
| `committer-date:>=2024-01-01 unstable autogen test` | S3 | 200 | 116 | 4 |
| `committer-date:>=2024-01-01 unstable claude test` | S3 | 200 | 60520 | 10 |
| `committer-date:>=2024-01-01 unstable crewai test` | S3 | 200 | 31 | 3 |
| `committer-date:>=2024-01-01 unstable eval test` | S3 | 200 | 8069 | 99 |
| `committer-date:>=2024-01-01 unstable gemini test` | S3 | 200 | 4725 | 58 |
| `committer-date:>=2024-01-01 unstable gpt test` | S3 | 200 | 3064 | 39 |
| `committer-date:>=2024-01-01 unstable langchain test` | S3 | 200 | 432 | 7 |
| `committer-date:>=2024-01-01 unstable langgraph test` | S3 | 200 | 271 | 5 |
| `committer-date:>=2024-01-01 unstable llamaindex test` | S3 | 200 | 15 | 3 |
| `committer-date:>=2024-01-01 unstable llm test` | S3 | 200 | 4934 | 60 |
| `committer-date:>=2024-01-01 unstable openai test` | S3 | 200 | 5833 | 71 |
| `committer-date:>=2024-01-01 unstable prompt test` | S3 | 200 | 13177 | 160 |
| `committer-date:>=2024-01-01 vcr openai test` | S3 | 200 | 2743 | 34 |
| `committer-date:>=2024-01-01 xfail "ai sdk" test` | S3 | 200 | 15 | 3 |
| `committer-date:>=2024-01-01 xfail "llama-index" test` | S3 | 200 | 27 | 3 |
| `committer-date:>=2024-01-01 xfail "model output" test` | S3 | 200 | 253 | 5 |
| `committer-date:>=2024-01-01 xfail "pydantic-ai" test` | S3 | 200 | 112 | 4 |
| `committer-date:>=2024-01-01 xfail agent test` | S3 | 200 | 15527 | 188 |
| `committer-date:>=2024-01-01 xfail anthropic test` | S3 | 200 | 69888 | 10 |
| `committer-date:>=2024-01-01 xfail autogen test` | S3 | 200 | 134 | 4 |
| `committer-date:>=2024-01-01 xfail claude test` | S3 | 200 | 75030 | 10 |
| `committer-date:>=2024-01-01 xfail crewai test` | S3 | 200 | 68 | 3 |
| `committer-date:>=2024-01-01 xfail eval test` | S3 | 200 | 5161 | 64 |
| `committer-date:>=2024-01-01 xfail gemini test` | S3 | 200 | 1913 | 24 |
| `committer-date:>=2024-01-01 xfail gpt test` | S3 | 200 | 1580 | 20 |
| `committer-date:>=2024-01-01 xfail langchain test` | S3 | 200 | 822 | 11 |
| `committer-date:>=2024-01-01 xfail langgraph test` | S3 | 200 | 343 | 6 |
| `committer-date:>=2024-01-01 xfail llamaindex test` | S3 | 200 | 25 | 3 |
| `committer-date:>=2024-01-01 xfail llm test` | S3 | 200 | 5352 | 66 |
| `committer-date:>=2024-01-01 xfail openai test` | S3 | 200 | 2801 | 35 |
| `committer-date:>=2024-01-01 xfail prompt test` | S3 | 200 | 9975 | 120 |

## Discovery and funnel

Zero-count bound for the planned reads (assumes no uncertain or unknown rows): 33.5; reads needed per stratum (equal split): S1 300<!--need_S1-->, S2 6041811<!--need_S2-->, S3 2415211<!--need_S3-->.

| stratum | candidates | truncated leaves | incomplete leaves | unread hits | excluded | read | member | no-agent-lib | no-ci-tests | uncertain | yes (recording / text) | unknown | no |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1 | 12 | 0 | 0 | 0 | 6<!--excl_S1--> | 6 | 2<!--member_S1--> | 3<!--nolib_S1--> | 1<!--noci_S1--> | 0<!--unc_S1--> | 1<!--yes_S1--> (1 / 0) | 0<!--unk_S1--> | 1<!--no_S1--> |
| S2 | 113511 | 365 | 0 | 26098719 | 336<!--excl_S2--> | 2212 | 222<!--member_S2--> | 1822<!--nolib_S2--> | 108<!--noci_S2--> | 60<!--unc_S2--> | 22<!--yes_S2--> (4 / 18) | 135<!--unk_S2--> | 65<!--no_S2--> |
| S3 | 80478 | 96 | 12 | 10397858 | 91<!--excl_S3--> | 1789 | 121<!--member_S3--> | 1355<!--nolib_S3--> | 193<!--noci_S3--> | 120<!--unc_S3--> | 12<!--yes_S3--> (0 / 12) | 57<!--unk_S3--> | 52<!--no_S3--> |

capped-query (first 1,000 read, rest added to N_s): `committer-date:>=2024-01-01 "non deterministic" anthropic test`; `committer-date:>=2024-01-01 "non deterministic" claude test`; `committer-date:>=2024-01-01 "non-deterministic" anthropic test`; `committer-date:>=2024-01-01 "non-deterministic" claude test`; `committer-date:>=2024-01-01 flakiness agent test`; `committer-date:>=2024-01-01 flakiness anthropic test`; `committer-date:>=2024-01-01 flakiness claude test`; `committer-date:>=2024-01-01 flakiness eval test`; `committer-date:>=2024-01-01 flakiness llm test`; `committer-date:>=2024-01-01 flakiness openai test`; `committer-date:>=2024-01-01 flakiness prompt test`; `committer-date:>=2024-01-01 flaky agent test`; `committer-date:>=2024-01-01 flaky anthropic test`; `committer-date:>=2024-01-01 flaky claude test`; `committer-date:>=2024-01-01 flaky eval test`; `committer-date:>=2024-01-01 flaky llm test`; `committer-date:>=2024-01-01 flaky openai test`; `committer-date:>=2024-01-01 flaky prompt test`; `committer-date:>=2024-01-01 intermittent agent test`; `committer-date:>=2024-01-01 intermittent anthropic test`; `committer-date:>=2024-01-01 intermittent claude test`; `committer-date:>=2024-01-01 intermittent prompt test`; `committer-date:>=2024-01-01 retry anthropic test`; `committer-date:>=2024-01-01 retry claude test`; `committer-date:>=2024-01-01 retry eval test`; `committer-date:>=2024-01-01 retry gemini test`; `committer-date:>=2024-01-01 retry gpt test`; `committer-date:>=2024-01-01 retry llm test`; `committer-date:>=2024-01-01 retry openai test`; `committer-date:>=2024-01-01 retry prompt test`; `committer-date:>=2024-01-01 unstable agent test`; `committer-date:>=2024-01-01 unstable anthropic test`; `committer-date:>=2024-01-01 unstable claude test`; `committer-date:>=2024-01-01 xfail anthropic test`; `committer-date:>=2024-01-01 xfail claude test`; `is:public created:>=2024-01-01 "api costs" test (llm OR openai OR agent)`; `is:public created:>=2024-01-01 "expensive tests" (llm OR openai OR agent)`; `is:public created:>=2024-01-01 "live llm" (llm OR openai OR agent)`; `is:public created:>=2024-01-01 "llm tests" (llm OR openai OR agent)`; `is:public created:>=2024-01-01 "mock llm" (llm OR openai OR agent)`; `is:public created:>=2024-01-01 "mock the llm" (llm OR openai OR agent)`; `is:public created:>=2024-01-01 "non deterministic" agent test`; `is:public created:>=2024-01-01 "non deterministic" claude test`; `is:public created:>=2024-01-01 "non deterministic" eval test`; `is:public created:>=2024-01-01 "non deterministic" gemini test`; `is:public created:>=2024-01-01 "non deterministic" llm test`; `is:public created:>=2024-01-01 "non deterministic" openai test`; `is:public created:>=2024-01-01 "non deterministic" prompt test`; `is:public created:>=2024-01-01 "non-deterministic" agent test`; `is:public created:>=2024-01-01 "non-deterministic" claude test`; `is:public created:>=2024-01-01 "non-deterministic" eval test`; `is:public created:>=2024-01-01 "non-deterministic" gemini test`; `is:public created:>=2024-01-01 "non-deterministic" llm test`; `is:public created:>=2024-01-01 "non-deterministic" openai test`; `is:public created:>=2024-01-01 "non-deterministic" prompt test`; `is:public created:>=2024-01-01 "real llm" test (llm OR openai OR agent)`; `is:public created:>=2024-01-01 "skip llm" (llm OR openai OR agent)`; `is:public created:>=2024-01-01 "token cost" test (llm OR openai OR agent)`; `is:public created:>=2024-01-01 flakiness agent test`; `is:public created:>=2024-01-01 flakiness claude test`; `is:public created:>=2024-01-01 flakiness eval test`; `is:public created:>=2024-01-01 flakiness llm test`; `is:public created:>=2024-01-01 flakiness prompt test`; `is:public created:>=2024-01-01 flaky "ai sdk" test`; `is:public created:>=2024-01-01 flaky "model output" test`; `is:public created:>=2024-01-01 flaky agent test`; `is:public created:>=2024-01-01 flaky anthropic test`; `is:public created:>=2024-01-01 flaky claude test`; `is:public created:>=2024-01-01 flaky eval test`; `is:public created:>=2024-01-01 flaky gemini test`; `is:public created:>=2024-01-01 flaky gpt test`; `is:public created:>=2024-01-01 flaky langchain test`; `is:public created:>=2024-01-01 flaky llm test`; `is:public created:>=2024-01-01 flaky openai test`; `is:public created:>=2024-01-01 flaky prompt test`; `is:public created:>=2024-01-01 intermittent agent test`; `is:public created:>=2024-01-01 intermittent anthropic test`; `is:public created:>=2024-01-01 intermittent claude test`; `is:public created:>=2024-01-01 intermittent eval test`; `is:public created:>=2024-01-01 intermittent gpt test`; `is:public created:>=2024-01-01 intermittent llm test`; `is:public created:>=2024-01-01 intermittent openai test`; `is:public created:>=2024-01-01 intermittent prompt test`; `is:public created:>=2024-01-01 nondeterministic agent test`; `is:public created:>=2024-01-01 nondeterministic claude test`; `is:public created:>=2024-01-01 nondeterministic prompt test`; `is:public created:>=2024-01-01 rerun "ai sdk" test`; `is:public created:>=2024-01-01 rerun "model output" test`; `is:public created:>=2024-01-01 rerun agent test`; `is:public created:>=2024-01-01 rerun anthropic test`; `is:public created:>=2024-01-01 rerun claude test`; `is:public created:>=2024-01-01 rerun eval test`; `is:public created:>=2024-01-01 rerun gemini test`; `is:public created:>=2024-01-01 rerun gpt test`; `is:public created:>=2024-01-01 rerun llm test`; `is:public created:>=2024-01-01 rerun openai test`; `is:public created:>=2024-01-01 rerun prompt test`; `is:public created:>=2024-01-01 retry "ai sdk" test`; `is:public created:>=2024-01-01 retry "model output" test`; `is:public created:>=2024-01-01 retry agent test`; `is:public created:>=2024-01-01 retry anthropic test`; `is:public created:>=2024-01-01 retry claude test`; `is:public created:>=2024-01-01 retry eval test`; `is:public created:>=2024-01-01 retry gemini test`; `is:public created:>=2024-01-01 retry gpt test`; `is:public created:>=2024-01-01 retry langchain test`; `is:public created:>=2024-01-01 retry langgraph test`; `is:public created:>=2024-01-01 retry llm test`; `is:public created:>=2024-01-01 retry openai test`; `is:public created:>=2024-01-01 retry prompt test`; `is:public created:>=2024-01-01 unstable agent test`; `is:public created:>=2024-01-01 unstable anthropic test`; `is:public created:>=2024-01-01 unstable claude test`; `is:public created:>=2024-01-01 unstable eval test`; `is:public created:>=2024-01-01 unstable gemini test`; `is:public created:>=2024-01-01 unstable gpt test`; `is:public created:>=2024-01-01 unstable llm test`; `is:public created:>=2024-01-01 unstable openai test`; `is:public created:>=2024-01-01 unstable prompt test`; `is:public created:>=2024-01-01 xfail agent test`; `is:public created:>=2024-01-01 xfail claude test`; `is:public created:>=2024-01-01 xfail prompt test`

## Reading statistics

- requests per candidate: median 4, p90 24, max 300
- text candidates per member without a recording: median 55.5, p90 296, max 1118
- texts first-read per hour: 243.9
- search requests per member observed: median 12, p90 12, max 12
- X-RateLimit-Remaining observed (last chunk): {}

Pain unknown reasons (a member can have several): comments-incomplete 3, recording-capped 8, recording-unread 1, request-cap 4, text-cap 180, text-capped 124, tree-truncated 1, unclear 15

## Per agent library

| library | members | runtime | dev/test | optional/extras | pain yes | pain unknown |
|---|---|---|---|---|---|---|
| @ai-sdk/alibaba | 3 | 3 | 0 | 0 | 1 | 1 |
| @ai-sdk/amazon-bedrock | 7 | 7 | 0 | 0 | 2 | 4 |
| @ai-sdk/anthropic | 30 | 30 | 1 | 0 | 5 | 18 |
| @ai-sdk/azure | 6 | 6 | 0 | 0 | 2 | 4 |
| @ai-sdk/cerebras | 3 | 3 | 0 | 0 | 1 | 1 |
| @ai-sdk/cohere | 4 | 4 | 0 | 0 | 2 | 1 |
| @ai-sdk/deepinfra | 3 | 3 | 0 | 0 | 1 | 1 |
| @ai-sdk/deepseek | 2 | 2 | 0 | 0 | 1 | 0 |
| @ai-sdk/devtools | 1 | 1 | 0 | 0 | 0 | 1 |
| @ai-sdk/fireworks | 2 | 2 | 0 | 0 | 0 | 1 |
| @ai-sdk/gateway | 4 | 4 | 0 | 0 | 2 | 2 |
| @ai-sdk/google | 20 | 20 | 0 | 0 | 4 | 12 |
| @ai-sdk/google-vertex | 4 | 4 | 0 | 0 | 3 | 1 |
| @ai-sdk/groq | 5 | 5 | 0 | 0 | 1 | 2 |
| @ai-sdk/huggingface | 1 | 1 | 0 | 0 | 0 | 0 |
| @ai-sdk/mcp | 5 | 5 | 1 | 0 | 1 | 3 |
| @ai-sdk/mistral | 4 | 4 | 0 | 0 | 1 | 2 |
| @ai-sdk/moonshotai | 1 | 1 | 0 | 0 | 0 | 0 |
| @ai-sdk/openai | 45 | 45 | 1 | 0 | 7 | 29 |
| @ai-sdk/openai-compatible | 21 | 19 | 3 | 0 | 4 | 15 |
| @ai-sdk/otel | 3 | 3 | 0 | 0 | 0 | 3 |
| @ai-sdk/perplexity | 4 | 4 | 0 | 0 | 2 | 1 |
| @ai-sdk/provider | 11 | 9 | 4 | 0 | 2 | 9 |
| @ai-sdk/provider-utils | 9 | 9 | 1 | 0 | 3 | 5 |
| @ai-sdk/react | 26 | 26 | 0 | 0 | 2 | 21 |
| @ai-sdk/replicate | 1 | 1 | 0 | 0 | 0 | 0 |
| @ai-sdk/togetherai | 3 | 3 | 0 | 0 | 1 | 1 |
| @ai-sdk/vercel | 4 | 4 | 0 | 0 | 2 | 1 |
| @ai-sdk/workflow | 1 | 1 | 0 | 0 | 0 | 1 |
| @ai-sdk/xai | 9 | 9 | 0 | 0 | 2 | 5 |
| @anthropic-ai/claude-agent-sdk | 34 | 31 | 5 | 0 | 3 | 29 |
| @langchain/anthropic | 8 | 7 | 1 | 1 | 0 | 6 |
| @langchain/aws | 2 | 1 | 1 | 0 | 0 | 1 |
| @langchain/baidu-qianfan | 1 | 1 | 0 | 0 | 0 | 1 |
| @langchain/classic | 2 | 2 | 0 | 0 | 0 | 1 |
| @langchain/cloudflare | 1 | 1 | 0 | 0 | 0 | 1 |
| @langchain/cohere | 1 | 1 | 0 | 0 | 0 | 1 |
| @langchain/community | 3 | 3 | 0 | 0 | 0 | 2 |
| @langchain/core | 28 | 27 | 9 | 1 | 2 | 17 |
| @langchain/deepseek | 1 | 1 | 0 | 0 | 0 | 1 |
| @langchain/exa | 1 | 1 | 0 | 0 | 0 | 1 |
| @langchain/google | 1 | 1 | 0 | 0 | 0 | 1 |
| @langchain/google-genai | 4 | 3 | 1 | 0 | 0 | 4 |
| @langchain/google-vertexai | 1 | 1 | 0 | 0 | 0 | 1 |
| @langchain/groq | 2 | 2 | 0 | 0 | 0 | 2 |
| @langchain/langgraph | 19 | 18 | 1 | 1 | 1 | 16 |
| @langchain/langgraph-checkpoint | 2 | 2 | 1 | 0 | 0 | 2 |
| @langchain/langgraph-checkpoint-postgres | 2 | 2 | 0 | 0 | 0 | 2 |
| @langchain/langgraph-checkpoint-sqlite | 1 | 1 | 0 | 0 | 0 | 1 |
| @langchain/langgraph-cli | 1 | 0 | 1 | 0 | 1 | 0 |
| @langchain/langgraph-sdk | 5 | 5 | 0 | 0 | 2 | 2 |
| @langchain/mcp-adapters | 2 | 2 | 0 | 0 | 0 | 2 |
| @langchain/mistralai | 1 | 1 | 0 | 0 | 0 | 1 |
| @langchain/mongodb | 1 | 1 | 0 | 0 | 0 | 1 |
| @langchain/ollama | 3 | 3 | 0 | 0 | 0 | 3 |
| @langchain/openai | 16 | 16 | 2 | 0 | 0 | 10 |
| @langchain/pinecone | 1 | 1 | 0 | 0 | 0 | 1 |
| @langchain/qdrant | 1 | 1 | 0 | 0 | 0 | 1 |
| @langchain/react | 1 | 1 | 0 | 0 | 0 | 0 |
| @langchain/redis | 2 | 2 | 0 | 0 | 0 | 2 |
| @langchain/tavily | 1 | 1 | 0 | 0 | 0 | 1 |
| @langchain/textsplitters | 3 | 3 | 0 | 0 | 0 | 2 |
| @langchain/typesafe | 1 | 1 | 0 | 0 | 1 | 0 |
| @langchain/weaviate | 1 | 1 | 0 | 0 | 0 | 1 |
| @langchain/xai | 1 | 1 | 0 | 0 | 0 | 1 |
| @llamaindex/core | 2 | 2 | 1 | 0 | 0 | 2 |
| @llamaindex/liteparse | 1 | 1 | 0 | 0 | 0 | 1 |
| @llamaindex/openai | 1 | 1 | 1 | 0 | 0 | 1 |
| @llamaindex/workflow | 1 | 1 | 0 | 0 | 0 | 1 |
| @mastra/core | 6 | 6 | 3 | 0 | 0 | 5 |
| @openai/agents | 5 | 5 | 1 | 0 | 0 | 5 |
| ag2 | 2 | 2 | 0 | 0 | 1 | 1 |
| agno | 6 | 4 | 0 | 2 | 1 | 4 |
| ai | 74 | 72 | 12 | 0 | 8 | 51 |
| autogen-agentchat | 3 | 1 | 1 | 2 | 1 | 2 |
| autogen-core | 2 | 2 | 0 | 0 | 1 | 1 |
| autogen-ext | 1 | 1 | 0 | 0 | 0 | 1 |
| claude-agent-sdk | 24 | 15 | 4 | 9 | 5 | 16 |
| crewai | 17 | 11 | 1 | 7 | 1 | 13 |
| crewai-tools | 5 | 3 | 0 | 2 | 0 | 5 |
| dspy | 2 | 2 | 0 | 0 | 0 | 2 |
| dspy-ai | 2 | 2 | 1 | 1 | 0 | 1 |
| google-adk | 10 | 7 | 2 | 5 | 0 | 10 |
| haystack-ai | 3 | 3 | 1 | 1 | 0 | 2 |
| langchain | 96 | 80 | 10 | 18 | 15 | 44 |
| langchain-anthropic | 35 | 29 | 1 | 5 | 9 | 15 |
| langchain-aws | 4 | 4 | 0 | 1 | 1 | 2 |
| langchain-azure-ai | 1 | 0 | 0 | 1 | 0 | 1 |
| langchain-cerebras | 1 | 1 | 0 | 0 | 0 | 0 |
| langchain-chroma | 6 | 3 | 1 | 2 | 1 | 2 |
| langchain-classic | 4 | 3 | 1 | 0 | 1 | 1 |
| langchain-cohere | 1 | 0 | 0 | 1 | 0 | 1 |
| langchain-community | 38 | 31 | 2 | 6 | 7 | 16 |
| langchain-core | 106 | 87 | 7 | 25 | 13 | 50 |
| langchain-daytona | 1 | 1 | 0 | 0 | 0 | 0 |
| langchain-deepseek | 6 | 2 | 0 | 4 | 2 | 3 |
| langchain-docling | 1 | 1 | 0 | 0 | 1 | 0 |
| langchain-exa | 1 | 1 | 0 | 0 | 0 | 1 |
| langchain-experimental | 3 | 2 | 1 | 0 | 0 | 3 |
| langchain-fireworks | 1 | 1 | 0 | 0 | 0 | 0 |
| langchain-google-genai | 20 | 15 | 3 | 3 | 3 | 11 |
| langchain-google-vertexai | 1 | 1 | 0 | 0 | 0 | 1 |
| langchain-groq | 10 | 10 | 1 | 0 | 3 | 4 |
| langchain-huggingface | 4 | 2 | 1 | 2 | 0 | 2 |
| langchain-ibm | 1 | 1 | 0 | 0 | 1 | 0 |
| langchain-ivoire | 1 | 0 | 1 | 0 | 0 | 0 |
| langchain-litellm | 1 | 1 | 0 | 0 | 1 | 0 |
| langchain-mcp-adapters | 7 | 6 | 0 | 1 | 1 | 5 |
| langchain-mistralai | 3 | 1 | 0 | 2 | 0 | 3 |
| langchain-modal | 2 | 2 | 0 | 0 | 0 | 1 |
| langchain-nimble | 1 | 1 | 0 | 0 | 0 | 1 |
| langchain-nvidia-ai-endpoints | 2 | 2 | 0 | 0 | 0 | 2 |
| langchain-ollama | 14 | 11 | 1 | 3 | 2 | 7 |
| langchain-openai | 75 | 57 | 9 | 12 | 11 | 35 |
| langchain-openviking | 1 | 1 | 0 | 0 | 1 | 0 |
| langchain-postgres | 3 | 3 | 0 | 0 | 0 | 2 |
| langchain-protocol | 8 | 8 | 1 | 0 | 1 | 2 |
| langchain-qdrant | 3 | 3 | 0 | 0 | 1 | 0 |
| langchain-runloop | 1 | 1 | 0 | 0 | 0 | 0 |
| langchain-tavily | 3 | 3 | 0 | 0 | 1 | 2 |
| langchain-tests | 4 | 0 | 3 | 1 | 0 | 1 |
| langchain-text-splitters | 31 | 26 | 1 | 5 | 7 | 13 |
| langchain-together | 1 | 1 | 0 | 0 | 0 | 1 |
| langchain-voyageai | 2 | 1 | 1 | 0 | 0 | 0 |
| langchain-xai | 1 | 0 | 0 | 1 | 0 | 1 |
| langchain-youdotcom | 1 | 1 | 0 | 0 | 0 | 1 |
| langgraph | 126 | 101 | 9 | 22 | 16 | 56 |
| langgraph-api | 2 | 2 | 0 | 0 | 1 | 1 |
| langgraph-checkpoint | 17 | 17 | 1 | 0 | 2 | 6 |
| langgraph-checkpoint-postgres | 28 | 26 | 0 | 2 | 7 | 10 |
| langgraph-checkpoint-redis | 1 | 1 | 0 | 0 | 0 | 1 |
| langgraph-checkpoint-sqlite | 17 | 15 | 0 | 2 | 3 | 8 |
| langgraph-cli | 4 | 2 | 1 | 1 | 2 | 1 |
| langgraph-prebuilt | 14 | 13 | 2 | 0 | 2 | 4 |
| langgraph-runtime-inmem | 2 | 1 | 0 | 1 | 1 | 1 |
| langgraph-sdk | 17 | 16 | 2 | 0 | 3 | 6 |
| llama-index | 9 | 6 | 2 | 3 | 1 | 3 |
| llama-index-core | 16 | 9 | 0 | 9 | 1 | 10 |
| llama-index-embeddings-azure-openai | 1 | 0 | 1 | 0 | 0 | 1 |
| llama-index-embeddings-nvidia | 1 | 0 | 0 | 1 | 0 | 1 |
| llama-index-embeddings-openai | 1 | 1 | 0 | 0 | 1 | 0 |
| llama-index-embeddings-voyageai | 1 | 1 | 0 | 0 | 0 | 0 |
| llama-index-llms-anthropic | 1 | 1 | 0 | 0 | 0 | 0 |
| llama-index-llms-azure-openai | 1 | 0 | 1 | 0 | 0 | 1 |
| llama-index-llms-openai | 3 | 3 | 0 | 0 | 0 | 1 |
| llama-index-postprocessor-cohere-rerank | 1 | 1 | 0 | 0 | 0 | 0 |
| llama-index-protocols-ag-ui | 1 | 1 | 0 | 0 | 0 | 1 |
| llama-index-readers-file | 1 | 0 | 0 | 1 | 0 | 1 |
| llama-index-readers-web | 1 | 0 | 1 | 0 | 0 | 1 |
| llama-index-readers-wikipedia | 1 | 0 | 1 | 0 | 0 | 1 |
| llama-index-storage-chat-store-redis | 1 | 1 | 0 | 0 | 0 | 1 |
| llama-index-tools-wikipedia | 1 | 0 | 1 | 0 | 0 | 1 |
| llama-index-vector-stores-chroma | 1 | 0 | 0 | 1 | 0 | 1 |
| llama-index-vector-stores-qdrant | 2 | 2 | 0 | 0 | 0 | 0 |
| llamaindex | 2 | 2 | 0 | 0 | 0 | 2 |
| openai-agents | 18 | 10 | 1 | 8 | 2 | 13 |
| pyautogen | 1 | 1 | 1 | 1 | 0 | 1 |
| pydantic-ai | 13 | 10 | 1 | 4 | 1 | 8 |
| pydantic-ai-slim | 27 | 23 | 3 | 8 | 1 | 20 |
| semantic-kernel | 3 | 1 | 0 | 2 | 0 | 2 |
| smolagents | 3 | 2 | 0 | 1 | 2 | 1 |
| strands-agents | 10 | 9 | 1 | 3 | 1 | 6 |
| (total, each repository once) | 345 | | | | 35 | 192 |

Pain yes by kind: recording 5, text 30 (cost 4, provider-errors 5, varying-output 21).

## Candidates and non-members per S2/S3 model term

| model term | candidates | read | non-members |
|---|---|---|---|
| llm | 703 | 652 | 533 |
| openai | 636 | 571 | 489 |
| anthropic | 698 | 643 | 566 |
| claude | 471 | 451 | 409 |
| gemini | 717 | 654 | 541 |
| gpt | 564 | 507 | 412 |
| "model output" | 895 | 809 | 694 |
| prompt | 668 | 620 | 501 |
| eval | 661 | 597 | 495 |
| langchain | 340 | 281 | 180 |
| langgraph | 317 | 292 | 181 |
| crewai | 76 | 65 | 42 |
| autogen | 113 | 93 | 77 |
| llamaindex | 54 | 45 | 20 |
| "llama-index" | 60 | 47 | 31 |
| "pydantic-ai" | 219 | 200 | 142 |
| "ai sdk" | 342 | 308 | 241 |
| agent | 586 | 564 | 470 |

## Pain list

| repository | libraries | kind | date | quote or file | URL |
|---|---|---|---|---|---|
| https://github.com/7daysofrain/mood-table-v2 | @langchain/core, @langchain/langgraph, @langchain/langgraph-cli, @langchain/typesafe | text (varying-output) | 2026-10-07 | Las evals se lanzan a mano; no son una puerta de la CI (cuestan tokens y no son deterministas). | https://github.com/7daysofrain/mood-table-v2/pull/19 |
| https://github.com/abhaypadmanabhan/autocoach | @ai-sdk/openai, ai, langchain, langchain-community, langchain-core, langchain-openai, langchain-text-splitters | text (varying-output) | 2026-07-20 | The observations CSV is kept — the judge calls cost money and are non-deterministic, so it is the one artifact that cannot be recreated. | https://github.com/abhaypadmanabhan/autocoach/commit/5fc699779ba39d0be4a0939c0a05707d20fb176a |
| https://github.com/admin-init/uni-dev | langchain, langchain-anthropic, langchain-openai, langgraph | text (cost) | 2026-06-20 | Validate with **real DeepSeek API calls**. Slow, expensive — run manually or on nightly schedule only. | https://github.com/admin-init/uni-dev/issues/36 |
| https://github.com/aieng-abdullah/production-rag-assistant | langchain, langchain-community, langchain-core, langchain-groq, langchain-qdrant, langchain-text-splitters | text (varying-output) | 2026-10-08 | test: retry verify-failed generations in eval | https://github.com/aieng-abdullah/production-rag-assistant/commit/a0503da99348dcb1c02331783194b8002255008d |
| https://github.com/buYoung/pi-packages | @anthropic-ai/claude-agent-sdk | text (varying-output) | 2026-07-29 | Asking a model to enumerate its tools was flaky - gemini intermittently summarises and omits custom tools. | https://github.com/buYoung/pi-packages/commit/7c18e88f5675692bcf9e5286b6b08eedc4675d7c |
| https://github.com/code0monkey1/invoice-dispute-agent | langchain, langchain-core, langchain-groq, langgraph, langgraph-checkpoint-postgres, langgraph-checkpoint-sqlite | text (provider-errors) | 2026-11-13 | When a *client-reply* case was rate-limited, `handle_client_reply` logged and swallowed the error (correct for a webhook), so the eval saw "the agent didn't call the tool". | https://github.com/code0monkey1/invoice-dispute-agent/pull/28 |
| https://github.com/context-labs/HALO | openai-agents, smolagents | text (varying-output) | 2026-07-29 | The same test passed on two branch runs of identical code minutes earlier — model nondeterminism against a budget with no slack. | https://github.com/context-labs/HALO/pull/90 |
| https://github.com/cuga-project/cuga-agent | langchain, langchain-core, langchain-docling, langchain-google-genai, langchain-groq, langchain-ibm, langchain-litellm, langchain-ollama, langchain-openai, langchain-text-splitters, langgraph, langgraph-checkpoint-postgres, langgraph-checkpoint-sqlite | text (provider-errors) | 2026-10-07 | This makes Policy (unit), Policy (e2e), SDK integration and Stability Tests fail at random on every PR. | https://github.com/cuga-project/cuga-agent/issues/907 |
| https://github.com/dre-mkr/aspire-chatbot | langchain, langchain-anthropic, langchain-chroma, langchain-core, langchain-openai, langchain-protocol, langchain-text-splitters, langgraph, langgraph-checkpoint, langgraph-checkpoint-postgres, langgraph-prebuilt, langgraph-sdk | text (varying-output) | 2026-08-14 | judging_memory 14 is recorded as unassigned and nondeterministic. One run recalled "Marisol's secondary-school uniform"; the next answered "You mentioned a laptop or a trip as savings goals" -- invent | https://github.com/dre-mkr/aspire-chatbot/commit/d33395f58d589b6f41e6ed24176d2856004fb9c9 |
| https://github.com/dyad-sh/dyad | @ai-sdk/amazon-bedrock, @ai-sdk/anthropic, @ai-sdk/azure, @ai-sdk/google, @ai-sdk/google-vertex, @ai-sdk/mcp, @ai-sdk/openai, @ai-sdk/openai-compatible, @ai-sdk/provider-utils, @ai-sdk/xai, ai | text (varying-output) | 2026-08-05 | Whether a run passes or fails depends on whether the model happens to wait for the sub-agent, hence the flakiness (failing runs finish in 1–3 minutes). | https://github.com/dyad-sh/dyad/pull/4204 |
| https://github.com/Eng-suso/BK-GPT | langchain, langchain-anthropic, langchain-community, langchain-core, langchain-openai, langchain-tavily, langchain-text-splitters, langgraph, langgraph-checkpoint-postgres | text (cost) | 2026-09-01 | gira pytest contro Postgres + Neo4j (Mem0/OpenAI restano skip, niente costi/flakiness). | https://github.com/Eng-suso/BK-GPT/commit/e82029c3bce39d2127292f23b18700e29d88a9ed |
| https://github.com/garybense/entelechy | @ai-sdk/google-vertex, @ai-sdk/openai, @ai-sdk/react, ag2, agno, ai, autogen-agentchat, autogen-core, claude-agent-sdk, crewai, langchain-core, langchain-text-splitters, langgraph, llama-index-core, openai-agents, pydantic-ai-slim, smolagents, strands-agents | text (varying-output) | 2026-04-15 | The end-to-end content-length assertion was flaky: the reflect agent can legitimately short-circuit and return text directly from a tool-call iteration | https://github.com/garybense/entelechy/commit/568e3c3028ce9967fa8c54f180a72c64af3ea33e |
| https://github.com/grixu/cc-toolkit | @anthropic-ai/claude-agent-sdk | text (varying-output) | 2026-11-13 | anti-slop's `clean-text-untouched` eval case failed CI in 3 of 6 runs. | https://github.com/grixu/cc-toolkit/pull/48 |
| https://github.com/IgorGoncharenko15/ouroboros | claude-agent-sdk | text (provider-errors) | 2026-05-11 | Add `_skip_on_provider_environmental_error()` helper that converts three known non-code provider errors to `pytest.skip()` instead of failure | https://github.com/IgorGoncharenko15/ouroboros/commit/c4f5cc427350f89cf2096c213572d487c3925036 |
| https://github.com/j7an/nexus-mcp | claude-agent-sdk | text (provider-errors) | 2026-05-30 | `test_run_returns_valid_response` relied on OpenCode's mutable stored default model (`ollama-cloud/kimi-k2.5`), which now returns 403. | https://github.com/j7an/nexus-mcp/pull/204 |
| https://github.com/jikig-ai/soleur | @anthropic-ai/claude-agent-sdk | text (varying-output) | 2026-06-02 | Downgrade the old soft-assert step to an explicitly informational agent-runtime dump (::notice::, exit 0) so the non-deterministic agent telemetry stays visible without gating CI. | https://github.com/jikig-ai/soleur/commit/fc8d518dfbd4dc2661f7e235a61075e8fe31cc34 |
| https://github.com/julianblue/geogent | @langchain/langgraph-sdk, langchain, langchain-anthropic, langchain-aws, langchain-classic, langchain-community, langchain-core, langchain-openai, langgraph, langgraph-checkpoint-postgres, langgraph-cli, langgraph-sdk | text (varying-output) | 2026-05-23 | buffer_then_save_eiffel is flaky on gemini-2.5-flash (it sometimes buffers then drops the save), so it carries an xfail reason | https://github.com/julianblue/geogent/commit/d078f8d859a9e222748ebf20418871688de9a6ec |
| https://github.com/lofeodo/agentic-jev-trader | langchain, langchain-anthropic, langchain-core, langchain-openai, langgraph | recording (path) | 2026-11-20 | `tests/recorded/cassettes/test_recorder_early_check/test_llm_call_hands_back_the_saved_answer.yaml` | https://github.com/lofeodo/agentic-jev-trader/blob/main/tests/recorded/cassettes/test_recorder_early_check/test_llm_call_hands_back_the_saved_answer.yaml |
| https://github.com/MiltonKlun/EvalHarness | langchain, langchain-anthropic, langchain-community, langchain-google-genai, langchain-text-splitters, langgraph | text (varying-output) | 2026-08-29 | 0001 judge never gates a merge (non-deterministic + paid; three-tier CI) | https://github.com/MiltonKlun/EvalHarness/commit/ad8e5adcade3aca971e43ed36b353b40699adb2a |
| https://github.com/mpaturi/genai-block5-agent | langgraph | text (varying-output) | 2026-07-18 | docs(phase1): note real LLM cost and non-determinism in CI eval runs | https://github.com/mpaturi/genai-block5-agent/commit/876f4253a9c167e35273e3055b96ca1b1607f1fb |
| https://github.com/New-user0/orbit | @ai-sdk/cohere, @ai-sdk/gateway, @ai-sdk/openai-compatible, @ai-sdk/perplexity, @ai-sdk/provider, @ai-sdk/provider-utils, @ai-sdk/vercel | recording (path) | 2026-10-04 | `packages/ai/test/fixtures/recordings/anthropic-messages-cache/keeps-a-long-tool-turn-inside-the-cache-lookback.json` | https://github.com/New-user0/orbit/blob/main/packages/ai/test/fixtures/recordings/anthropic-messages-cache/keeps-a-long-tool-turn-inside-the-cache-lookback.json |
| https://github.com/nikhilcrypto0/concierge | langchain-anthropic, langchain-core, langgraph, langgraph-checkpoint-postgres | text (cost) | 2026-10-06 | - [ ] Agent eval not re-run (costs money); the shipped KB is unaffected, which the new test asserts. | https://github.com/nikhilcrypto0/concierge/pull/9 |
| https://github.com/orime-org/breatic | @ai-sdk/anthropic, @ai-sdk/deepseek, @ai-sdk/google, @ai-sdk/openai, @ai-sdk/react, ai | text (varying-output) | 2026-11-26 | the red one (`:317`, the pet photo) passed on a rerun, the same model variance the internal backlog tracks on `main`. | https://github.com/orime-org/breatic/pull/1647 |
| https://github.com/ParampreetSingh23/litellm-vps | claude-agent-sdk, langchain, langchain-openai, langgraph, langgraph-prebuilt | text (varying-output) | 2026-10-09 | Whether gpt-5.4-mini emits a reasoning item next to a forced function call is up to the model, and it skipped it on four scheduled runs while a same-SHA rerun passed. The first turn now retries up to  | https://github.com/ParampreetSingh23/litellm-vps/commit/cddc7cde97140749e8e4d256408761d4186f21c8 |
| https://github.com/patibandlavenkatamanideep/memoryops-ai | langchain, langchain-core | recording (path) | 2026-08-10 | `services/api/tests/cassettes/test_extraction_quality_real_gemini.yaml` | https://github.com/patibandlavenkatamanideep/memoryops-ai/blob/main/services/api/tests/cassettes/test_extraction_quality_real_gemini.yaml |
| https://github.com/phronetic-ai/litellm | claude-agent-sdk | text (provider-errors) | 2024-11-02 | * test: remove e2e test - hitting gemini rate limits | https://github.com/phronetic-ai/litellm/commit/f79365df6e1796f52929a165f53085f43710e31c |
| https://github.com/pikkujs/pikku | @ai-sdk/anthropic, @ai-sdk/openai, @ai-sdk/openai-compatible, ai | text (varying-output) | 2026-07-20 | The 24 existing `@ai` scenarios drove the console UI in Playwright against real OpenAI — slow, costly, non-deterministic, and only able to assert what renders on screen. | https://github.com/pikkujs/pikku/pull/996 |
| https://github.com/PostHog/posthog | langchain, langchain-anthropic, langchain-community, langchain-core, langchain-openai, langgraph, langgraph-checkpoint | text (varying-output) | 2026-11-25 | Engineers who watch master see the LLM Gateway Tests job fail intermittently. test_streaming_request[cloudflare] sometimes gets a stream with no delta.content | https://github.com/PostHog/posthog/pull/141995 |
| https://github.com/qfunction-ai/letta-local | langchain, langchain-community, llama-index, llama-index-embeddings-openai | text (varying-output) | 2026-01-29 | fix(tests): improve prompt for multi-modal tool return tests Make prompts more direct to reduce LLM flakiness | https://github.com/qfunction-ai/letta-local/commit/2fc592e0b621d15dc8d2eed84071b0b98473b7b6 |
| https://github.com/rock-solid-sites/ASES | @ai-sdk/alibaba, @ai-sdk/amazon-bedrock, @ai-sdk/anthropic, @ai-sdk/azure, @ai-sdk/cerebras, @ai-sdk/cohere, @ai-sdk/deepinfra, @ai-sdk/gateway, @ai-sdk/google, @ai-sdk/google-vertex, @ai-sdk/groq, @ai-sdk/mistral, @ai-sdk/openai, @ai-sdk/openai-compatible, @ai-sdk/perplexity, @ai-sdk/provider, @ai-sdk/provider-utils, @ai-sdk/togetherai, @ai-sdk/vercel, @ai-sdk/xai, ai | recording (path) | 2026-08-09 | `fork/opencode-src/packages/core/test/fixtures/recordings/session-runner/openai-chat-streams-text.json` | https://github.com/rock-solid-sites/ASES/blob/main/fork/opencode-src/packages/core/test/fixtures/recordings/session-runner/openai-chat-streams-text.json |
| https://github.com/rsn491/tea | pydantic-ai | text (varying-output) | 2026-07-28 | asks the model to implement a new operation and edit three files, which a 1.5B model can't reliably do — making the sanity-check workflow flaky for reasons unrelated to CI wiring. | https://github.com/rsn491/tea/commit/172094f52a2c6148e2e6a882c24fe9f2751dd3c6 |
| https://github.com/shaohua-code/sh-deer-flow | @langchain/core, @langchain/langgraph-sdk, ai, langchain, langchain-anthropic, langchain-deepseek, langchain-google-genai, langchain-mcp-adapters, langchain-ollama, langchain-openai, langchain-openviking, langgraph, langgraph-api, langgraph-checkpoint-postgres, langgraph-checkpoint-sqlite, langgraph-cli, langgraph-runtime-inmem, langgraph-sdk | text (varying-output) | 2026-06-08 | the single intermittent failure in tests/test_client_e2e.py::test_tool_call_produces_events is pre-existing LLM flakiness (the test asserts the model decided to call a tool; reproduces 1/3 on unchange | https://github.com/shaohua-code/sh-deer-flow/commit/799bef6d9dbc3a2cb37ce8177eeeabe2a33d8971 |
| https://github.com/tarek-gritli/argus | langgraph | text (cost) | 2026-05-09 | Mock _call_claude to exercise the full pipeline without burning API quota. | https://github.com/tarek-gritli/argus/commit/3e86ea73cd587f47904e9ad3ce3925fe02cbf282 |
| https://github.com/zhaokai-mgzn/migao | langchain-core, langchain-deepseek, langchain-openai, langgraph | text (varying-output) | 2026-08-25 | Merge PR #2519: test(qa): product_update_price 加 flaky 重试（LLM 偶发整轮不调工具） | https://github.com/zhaokai-mgzn/migao/commit/c26d9291ed0451b4751d1415d16adda4aafa3b8b |
| https://github.com/ZSvedic/TamedTable | @ai-sdk/anthropic, @ai-sdk/google, @ai-sdk/openai, ai | recording (path) | 2026-09-16 | `cassettes/aggregate.json` | https://github.com/ZSvedic/TamedTable/blob/main/cassettes/aggregate.json |

## Hand reads

first reads 9470<!--first_reads--> (confirmed 32, unclear 14, rejected 9424); second reads 670; both confirmed 30; confirmed first read not confirmed by the second 2; rejected first read labelled confirmed by the second 4.

## Hand check (AC4)

required yes checks 35, missing 35, failed 0; samples (10 non-members, 10 members with pain no, every recording package hit) done: no.

## Information

- excluded candidates with discovery hits (pain not read): simonw/pytest-recording-example (stale), langchain-ai/langsmith-python (library-owner), contextco/raggle (stale), dmallya93/llmreplay (library-owner), cendorhq/cendor-libs (library-owner), beyhangl/evalcraft (library-owner), mjrestivo16/unifi-ddns (fork/archived), saarbyrne/Simpleamapp (archived), bola-adesanya/ragsystem (fork), arcticbio/n8n-Reference (stale), pmatos/forseti (archived), numba/numba-prototypes (stale), ladzaretti-testing/lockfile-maintenance (stale), tilorc-bot/sympy (fork), GameNative/mesa-turnip (archived), TogetherCrew/temporal-worker-python (stale), devops-csmake/csmake-providers (fork), PythonBiellaGroup/Esercizi (stale), jeevantelukula/meta-openembedded (stale), agentuity/templates (archived), gazon1/10x-chat (fork), kust1011/rvdbt (fork), DoozyX/orca (fork), douglasag97/FORCLE (stale), freeunitorg/freeunit (fork), KushagraSharma924/Mini-Python-Projects (stale), multiplechoice/scrapy-sqs-exporter (stale), jeffrichley/lily (archived), CSIS/agent-router (fork), GlacierEQ/e2b-cookbook__public_fork_archive (fork), Zdycomp/awesome-llm-apps (fork), HarleyCoops/dash-cookbook (fork), stevenko2002/agents-radar (fork), moetemp/sdk-rust (fork), hsuanchenlin/EchoForge (fork), vaibh27/era-v5-lab (fork), pygarap/air-by-pygarap (fork), plooolp/colab-mcp (fork), tegnike/aituber-kit-demo (stale), TobKed/beam (fork), Kahf-Browser/Android (fork), id-2/airbyte (fork/stale), AlexM1010/FollowWeb (stale), Julianoeichelberger/private-gpt (fork/stale), mindfire-lab/openclaw (fork), jprbom/agent-lightning (fork), trevorbarnesus-lab/daily-bot (fork), auldsyababua/ai-rails-tdd (stale), junyoungDihisoft/claude-vercel-wbs (fork), Sage-PhysicalAI/EmbodiedScan (stale), sublayerapp/sublayer_actions (stale), pohanhuang/kubeovn-operator (fork), riddlemeS4m/ais-spring-2025-frontend (stale), nssuwan186-dev/adk-python (fork), CharlieTLe/opentelemetry-demo (fork), odisha-muktasoft/MUKTA_IMPL (fork), cicero-im/auto-commit (fork/stale), qlik-oss/sprout (archived), sasakama-code/rimor (stale), ymqy/cua (fork), Repcoders/chat-on-steroids (fork), langchain-ai/langsmith-sdk (archived/library-owner), Western-Artificial-Intelligence/video-virality-predictor (archived), jameskierstead/private-ollama (fork/stale), BAS-More/paseo (fork), yuanboTT/tt-boltz-opt (stale), furedea/reflex-state (archived), sksingh2005/orangu (fork), nczitzk/RSSHub (fork), forgegod/gepa-ai-gepa (fork), mavenplugins/jreleaser (fork), zo4xia/agentic-browser (fork), EnidPinxit/VIBE_MotionShapeEstimator (fork), lilnouns/lilnouns-pics (archived/stale), brendangeck/kiro-learn (archived), 578438807/dsh-superagent-prototype (fork), intellistream/vllm-hust-legacy-20260831 (fork/archived), fabiobends/cribe-server (stale), YouToco/vane (archived), coder360-crypto/BA-Supply (stale), microsoft/Build-your-own-copilot-Solution-Accelerator (archived), Kazu-Universe/cmbagent (fork), erimatnor/timescaledb (fork), tanmoy-git/deriv-one-oss (fork), Sin-Estres-dev/supabase (fork), neopilotai/devlabs (fork), davidtandoh/firstmate (fork), CosmicCuddle/azerothcore-wotlk (fork), Maxaubert/Sonara (fork), cppalliance/coding-benchmark (archived), e-kotov/t3code (fork), willnode/cc-rs (fork), kamiazya/project-manager (archived/stale), this-is-me-123/OF-Management-Ai (stale), 4444J99/trendpulse (archived), rkeene/TclTLS (stale), wt-xyz/starboard (fork), Stars1233/assistant-ui (fork), sagri-tokyo/nanoclaw (fork), krzys167-crypto/OLA (fork), 0c0c0f/Metis (fork), chark1es/bettercode (fork), paulpham157/open-interpreter (fork), kalviumcommunity/student_study_assistant (stale), muhammadumair185/nodejs.wed (stale), brunodabo/fastapi (fork), FlowiseAI/Flowise (archived), jackjin1997/TentOfTrials (fork), cascarree/RL-exercises (fork), curefatih/kolo (stale), projectoperations/stable-diffusion-webui (fork/stale), chris-dare-dev/agent-kit (archived), sealnext/SolveTaskAI (archived/stale), yash-mandaviya/ai-agents-masterclass (fork), ggozad/haiku.skills (archived), victoriadrake/open-mscs (archived/stale), wyattgill9/fix (fork), smarzban/agent-sdlc (archived), TRO-Wolf/iceberg-rust (fork), elimelt/notes (archived), misty-step/landmark (archived), Ditto190/langchain (fork), HiromiShikata/npm-cli-gh-cookie (archived), Jojen6324/commerce-agent-harness (fork), RemyLoveLogicAI/clawdbot (fork/archived), akash-soni/Chest-disease-classification (stale), PewterFelt/pewterfelt-ai (archived), Sheepsta300/langchain (fork/stale), TheIllusionOfLife/promote_autonomy (stale), dknauss/Sudo (archived), heiervang-technologies/ht-llama.cpp (fork), GewoonJaap/shopify-product-tracker (stale), MaxusAI/ollama (fork), antbrogame-a11y/docente-plus-plus (stale), LokiMetaSmith/tinygrad (fork), nathanfraske/MyOwnMeshSecurityReview (fork), ipo/codex (fork), bpasero/chokidar (fork), Marcus-A-Goncalves/Vitru-Bot (stale), jessifoo/vibe-coding-template (fork), michaelheichler/vibe-better-with-claude-code-vbw (fork), matrix-org/matrix-rich-text-editor (archived/stale), c6ai/ai-engineering-hub (fork), aSeriousCoder/DivHGNN (stale), tiagocordeiro/mulhergorila-website (stale), caneff/gridfind (archived), xue-cai/adk-python (fork), PaleoLipidRR/BAYSPAR (fork), WYRE-AI/cortextos (fork), up2itnow0822/langchainjs (fork), alsyundawy/FreeAskInternet-AI (fork), Arcanea-Labs/arcanea-ai-app-retired-20261107 (archived), romforth/binutils (stale), PINKIIILQWQ/hermes-webui (archived), Memo-2023/managarten (archived), aidenzepp/qti-pie (archived), YoctoNexus/yocto-combined (stale), 12321248/IO (stale), joy-void-joy/lup-legacy (archived), ayanjit-cmyk/crewAI (stale), Jordan1022/GoodlyChat (archived), Screaming-Bird/mt6785-mainline (stale), BillWagner/docs (fork), alicoding/semantic-search-service (stale), philipjkim/pls7-cli (stale), grafana-cold-storage/alloy-configurator (archived), jhwadman/melchizedek-agents (archived), hsrts/vllm (archived), aderinsolabamidele/fastapi-custom (stale), glitch10X/test-repo1 (stale), mrbrazzi/crewAI-examples (fork), Leon-6/Linux-Kernel-Stable (stale), rwkv-rs/evalscope-rwkv (fork), atree1023/ragtag_crew (stale), KalleNiemi/linux_next (stale), akitorahayashi/cowsay-mcp (stale), sunscape-stuff/msm-5.4 (stale), OCHOLA-EDDYPHIL/elenchos-dfir (archived), hoelzl/termverify (archived), DenchHQ/DenchClaw (fork), gumgizoa/rllm (fork), sahiixx/system-prompts-and-models-of-ai-tools (fork), roman98Z/valuecell (stale), hyperlapse122/dotfiles-v1 (archived), soumyadixit/Playwright-Python-Example (fork), emilympoland/chat-langchain-lite (fork), sjmaple/cr-rocketride-server (fork), slittyjuice-source/claude-quickstarts (fork), cayoc9/wordpress_to_wix-migrator (stale), RemyLoveLogicAI/browser-use (fork), luluthehungrycat/oh-mon-vibe (fork), Fizza-Mukhtar/deepeval (fork), AmirulAndalib/awesome-llm-apps (fork), michaelasper/ds4 (fork/archived), ntfsprogs-plus/ntfsprogs-plus (fork), jauderho/ntpd-rs (fork), mjc/hipfire (fork), Grow-Love/langchain (stale), Project-PixelStar/frameworks_base (archived/stale), mocimoda/generative-ai (fork)
- general recording tools in members without a model-host recording: AseemPrasad/Legalassist-AI: vcrpy; EpicStaff/EpicStaff: pytest-vcr; ParampreetSingh23/litellm-vps: pytest-recording; ParampreetSingh23/litellm-vps: vcrpy; UtkarshAlshi/finsight-ai: vcrpy; anthonycoffey/multi-agent-orchestration-demo: pytest-recording; datahub-project/datahub: vcrpy; jezztify/Bro-Code: nock; sergiiiavt/gimme-job: vcrpy
- population (file hits, not repositories; information only): `@ai-sdk filename:package.json` 87424, `@ai-sdk filename:pyproject.toml` 1, `@ai-sdk filename:requirements.txt` 7, `@anthropic-ai/claude-agent-sdk filename:package.json` 9616, `@anthropic-ai/claude-agent-sdk filename:pyproject.toml` 2, `@anthropic-ai/claude-agent-sdk filename:requirements.txt` 3, `@langchain filename:package.json` 40896, `@langchain filename:pyproject.toml` 653, `@langchain filename:requirements.txt` 32, `@llamaindex filename:package.json` 985, `@llamaindex filename:pyproject.toml` 136, `@llamaindex filename:requirements.txt` 1, `@mastra/core filename:package.json` None, `@mastra/core filename:pyproject.toml` 0, `@mastra/core filename:requirements.txt` 0, `@openai/agents filename:package.json` 2920, `@openai/agents filename:pyproject.toml` 0, `@openai/agents filename:requirements.txt` 0, `ag2 filename:package.json` 1254, `ag2 filename:pyproject.toml` 655, `ag2 filename:requirements.txt` 2612, `agno filename:package.json` 51200, `agno filename:pyproject.toml` 17184, `agno filename:requirements.txt` 12528, `ai filename:package.json` 15237120, `ai filename:pyproject.toml` 1253376, `ai filename:requirements.txt` 1867776, `autogen-agentchat filename:package.json` 1, `autogen-agentchat filename:pyproject.toml` 1186, `autogen-agentchat filename:requirements.txt` 2106, `autogen-core filename:package.json` 0, `autogen-core filename:pyproject.toml` 483, `autogen-core filename:requirements.txt` 1216, `autogen-ext filename:package.json` 0, `autogen-ext filename:pyproject.toml` 958, `autogen-ext filename:requirements.txt` 2012, `claude-agent-sdk filename:package.json` 10128, `claude-agent-sdk filename:pyproject.toml` 4024, `claude-agent-sdk filename:requirements.txt` 1904, `crewai filename:package.json` 448, `crewai filename:pyproject.toml` None, `crewai filename:requirements.txt` 12560, `crewai-tools filename:package.json` 1, `crewai-tools filename:pyproject.toml` 1856, `crewai-tools filename:requirements.txt` 4272, `dspy filename:package.json` 206, `dspy filename:pyproject.toml` 3004, `dspy filename:requirements.txt` 2408, `dspy-ai filename:package.json` 2, `dspy-ai filename:pyproject.toml` 904, `dspy-ai filename:requirements.txt` 1032, `google-adk filename:package.json` 150, `google-adk filename:pyproject.toml` 10016, `google-adk filename:requirements.txt` 13200, `haystack-ai filename:package.json` 1, `haystack-ai filename:pyproject.toml` 960, `haystack-ai filename:requirements.txt` 1063, `langchain filename:package.json` 51840, `langchain filename:pyproject.toml` 86016, `langchain filename:requirements.txt` 314880, `langgraph filename:package.json` 17344, `langgraph filename:pyproject.toml` 55296, `langgraph filename:requirements.txt` 89344, `llama-index filename:package.json` 55, `llama-index filename:pyproject.toml` 18816, `llama-index filename:requirements.txt` 17728, `llamaindex filename:package.json` 2076, `llamaindex filename:pyproject.toml` 2164, `llamaindex filename:requirements.txt` None, `openai-agents filename:package.json` 583, `openai-agents filename:pyproject.toml` 8944, `openai-agents filename:requirements.txt` 6528, `phidata filename:package.json` 10, `phidata filename:pyproject.toml` 172, `phidata filename:requirements.txt` 1240, `pyautogen filename:package.json` 1, `pyautogen filename:pyproject.toml` 568, `pyautogen filename:requirements.txt` 3272, `pydantic-ai filename:package.json` 102, `pydantic-ai filename:pyproject.toml` 8016, `pydantic-ai filename:requirements.txt` 3264, `pydantic-ai-slim filename:package.json` 0, `pydantic-ai-slim filename:pyproject.toml` 2876, `pydantic-ai-slim filename:requirements.txt` 1568, `semantic-kernel filename:package.json` 78, `semantic-kernel filename:pyproject.toml` 1480, `semantic-kernel filename:requirements.txt` 1616, `smolagents filename:package.json` 24, `smolagents filename:pyproject.toml` 1808, `smolagents filename:requirements.txt` 1574, `strands-agents filename:package.json` 529, `strands-agents filename:pyproject.toml` 3748, `strands-agents filename:requirements.txt` 5888

## Limits

Default branches only for files; search coverage limited to the listed queries (1,000 results per leaf, best-match order on capped queries); truncated leaves are counted in N_s; texts are the first 100 results of each repository search; comments fetched for the first 40 non-candidate hits.
