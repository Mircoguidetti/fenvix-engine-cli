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
