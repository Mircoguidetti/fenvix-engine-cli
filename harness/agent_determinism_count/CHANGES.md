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
