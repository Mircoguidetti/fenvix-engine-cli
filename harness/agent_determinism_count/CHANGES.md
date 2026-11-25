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
