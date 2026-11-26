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
