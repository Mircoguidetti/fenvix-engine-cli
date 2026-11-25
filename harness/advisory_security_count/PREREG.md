# Pre-registration: public count of security advisories whose root cause is order, timing or shared state

Committed before any data request (no listing, probe or material is in this commit). Spec: LAUNCHED rev 3 (gate 7/10,
gate rev 3 notes applied). Every later change to a rule, list, regex, seed or budget is listed in REPORT.md under
"PREREG changes", each on its own line with its justification, before any result.

## Decision line (founder, fixed; not reopened)

By 15 Dec 2026: if fewer than 15% of the classified (included) advisories, or fewer than 30 advisories in absolute
number, are `ours` (`unclear` counted as not ours), the deterministic-security idea is dropped. If it holds, the next
step (running the engine on 5-10 public multi-customer applications) is decided with the founder through a gstack skill.

Written with integers: **CONTINUE** when `100*ours >= 15*included` and `ours >= 30`; **DROP** when
`100*ours < 15*included`; otherwise (share >= 15%, ours < 30) keep reading to the next checkpoint, and **DROP** if
every candidate is read. **NO DECISION** when the 48 h budget (from the first data request) ends before a decision.

## §0 Probe

From the session: `gh api -X GET /advisories -f type=reviewed -f ecosystem=npm -f published=2024-01-01..2024-01-31
-f per_page=5` and `gh api /repos/expressjs/express/commits?per_page=1`. A call that does not answer HTTP 200 is
repeated from a GitHub Actions workflow in this repository (created only then, copied from
`3aee9ba:.github/workflows/agent-pr-count2.yml`, branch pushed before the first request file). Session route for what
answers 200 there; workflow route for the rest. Neither route answers `/advisories` → REPORT first line `BLOCKED`.
Raw JSON of the probe is committed under `probe/`. Field or parameter names that differ from the spec are a listed
PREREG change.

## §1 Frame

1. **List:** for each ecosystem in {npm, pip, rubygems, maven, composer, go, nuget}:
   `GET /advisories?type=reviewed&is_withdrawn=false&ecosystem=<e>&published=2024-01-01..<LIST_DATE>&per_page=100`,
   all pages (cursor pagination via the `Link` header). Rows with `withdrawn_at` set are dropped as well.
   `LIST_DATE` is the UTC date the listing starts, recorded with its timestamp in `data/listing_meta.json`.
   Deduplicated by `ghsa_id`; an advisory listed under several ecosystems is one row with all its ecosystems (the
   union of the listing ecosystem(s) and `vulnerabilities[].package.ecosystem`, restricted to the seven).
   **Interpretation:** rust, erlang, pub and swift are left out because they rarely ship web or multi-user server code;
   `LIST_DATE` (about 26 Nov) ends a few days before the memo's 30 Nov; both are printed as limits.
2. **Candidate** = an advisory that
   - (a) has at least one CWE in the CWE list, or
   - (b) whose `summary + "\n" + description` matches the narrow regex (whatever its CWEs), or
   - (c) has no CWE (`cwes` null or empty) or only CWEs among `NVD-CWE-Other`, `NVD-CWE-noinfo`, `CWE-Other`, and
     whose `summary + "\n" + description` matches the broad regex.
   A candidate's *route* is the first of (a), (b), (c) that holds; REPORT also prints every membership. REPORT prints
   the (b)-only candidates split by CWE-79 and CWE-352 (expected noise: stored-XSS "other users", CSRF "double
   submit"; excluded at reading, the reading budget plans for them).
   - **CWE list** (numbers; matched against `cwes[].cwe_id` of the form `CWE-<n>`):
     authorization and access: 284, 285, 639, 862, 863, 266, 269, 732;
     authentication bypass: 287, 288, 290, 294, 306;
     data to the wrong party: 200, 201, 359, 488, 524, 668, 226;
     session and expiry: 298, 324, 384, 613, 672;
     concurrency, shared state and order: 362, 364, 366, 367, 543, 567, 662, 667, 820, 821, 1223, 1265;
     single-use and workflow: 837, 841, 799.
   - **Narrow regex** (Python `re`, flags `re.IGNORECASE`), the spec's regex with the gate rev 3 note 8 additions
     (`tocttou`, `in parallel`, `at the same time`, `non-?atomic\w*`, `other organi[sz]ations?`; noise from the
     missing trailing `\b`, e.g. "other usernames", is accepted):
     ```
     \b(race[- ]?conditions?|data races?|concurren\w*|simultaneous\w*|parallel requests?|toctou|tocttou|time[- ]of[- ]check|cache[- ]?key\w*|thread[- ]?locals?|async\w*local\w*|multi[- ]?tenan\w*|cross[- ](tenant|user|account)s?|another (user|tenant|customer|organi[sz]ation|account)s?|other (users?|tenants?|customers?|accounts?|organi[sz]ations?)|wrong (users?|sessions?|tenants?)|session (fixation|mix\w*|leak\w*|confusion)|double[- ]?(spend|us|redeem|submi)\w*|replay\w*|in parallel|at the same time|non-?atomic\w*)
     ```
   - **Broad regex** (`re.IGNORECASE`), only for (c): the narrow regex, or
     ```
     \b(cache[ds]?|caching|shared (state|instances?|memory)|singletons?|global (state|variables?)|async\w*|background (jobs?|tasks?|workers?)|twice|re-?us\w*|expir\w*)\b
     ```
3. **Order:** candidates sorted by `ghsa_id`, then `random.Random(5).shuffle(list)` once; read in that order.
4. **Frame bias (printed in REPORT):** the CWE list and regexes can miss `ours` advisories tagged with other CWEs and
   wording (bias toward DROP) and bring in authorization advisories that are almost always `read-the-code` (bias
   toward DROP); keyword-only candidates may lean toward `ours` (bias toward CONTINUE). REPORT prints the share with
   and without the (b)/(c)-route candidates.

## §2 Per-advisory reading

1. **Material:** `summary`, `description`, CWEs, references; for each reference URL that is a commit
   (`https://github.com/<o>/<r>/commit/<sha>`), a pull request (`.../pull/<n>`) or a compare
   (`.../compare/<a>...<b>`) in the advisory's `source_code_location` repository (owner/name compared
   case-insensitively), the first 3 in reference order: `GET /repos/<o>/<r>/commits/<sha>`, or
   `GET /repos/<o>/<r>/pulls/<n>` plus its merge commit (`merge_commit_sha`, when merged), or
   `GET /repos/<o>/<r>/compare/<a>...<b>`. Caps: at most 20 files per commit/compare, first 400 patch lines per
   file, skipping lockfiles (`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `composer.lock`, `Gemfile.lock`,
   `poetry.lock`, `Pipfile.lock`, `go.sum`, `Cargo.lock`, `packages.lock.json`) and vendored paths (`vendor/`,
   `node_modules/`, `third_party/`, `dist/`, `build/`, `*.min.js`). Material is stored in the row before
   classification. REPORT prints the share of included rows with fix material (at least one fetched commit, PR or
   compare).
2. **Inclusion**, in order:
   - (I0) the affected package is a web or multi-user server application, a web framework, or a library used to serve
     web requests for several users (authentication, session, authorization, cache, ORM, job queue, API gateway);
     otherwise `excluded: not-web` (container runtimes, CLIs, desktop tools, file-system libraries, compilers and
     cluster-internal Kubernetes components are not-web; multi-user web applications that run on Kubernetes, such as
     Argo CD, Rancher or Harbor, are web; an HTTP client library leaking a header to another origin may be excluded as
     `not-web` or `one-principal`, either is accepted);
   - then `included` when, independently of any excluded mechanism, the main effect is one of: (I1) a user, tenant,
     customer or session can see, receive or change the data of another principal (user, tenant or session) of the
     same application; (I2) an authorization or authentication check can be bypassed (acting as another user, or
     reaching what one's role does not allow); (I3) something can be used more times than allowed (coupon, token,
     invitation, vote, payment, one-time code, rate limit). A credential or header leaked to another origin by an
     HTTP client is not I1 (one principal only).
   - Excluded, whatever the CWE: injection (SQL, command, template, XSS), path traversal, SSRF, memory corruption,
     denial of service, cryptographic weakness, supply chain, open redirect, CSRF, information disclosure that is not
     another principal's data, unless I1-I3 holds through another mechanism. Closed reason list: `not-web`,
     `one-principal`, `injection`, `xss`, `csrf`, `path-traversal`, `ssrf`, `memory`, `dos`, `crypto`,
     `supply-chain`, `open-redirect`, `no-principal-disclosure` (server configuration, versions, stack traces, one's
     own data; renamed from `own-data-disclosure` per gate note 9), `no-I1-I3`.
3. **Cause classes for included advisories** (one class; a verbatim quote from the stored material is required):
   - `ours`, with subclass:
     - `O1-shared-state`: data or a decision kept in a cache, memo, singleton, global, module-level variable, pooled
       connection or object reused across users, requests or tenants, keyed or scoped without the user or tenant;
     - `O2-context-loss`: request, user or tenant context lost or swapped across async boundaries, background jobs,
       threads, workers or callbacks (thread-local or async-local leaks, a job running without the tenant);
     - `O3-concurrency`: a race between concurrent requests or processes, time-of-check to time-of-use, a non-atomic
       check-and-write; double use counts as `O3` only when it needs parallel or interleaved requests (if sequential
       repetition also works, it is `read-the-code`);
     - `O4-order`: the bug needs a specific earlier request, step or initialisation order to happen (state left by a
       previous request or step); a check missing in every order is `read-the-code`;
     - `O5-time`: the outcome depends on the clock value or on time arithmetic (time zone, daylight saving, units,
       leeway, clock comparison, a lifetime computed wrongly); a missing invalidation on an event (logout, password
       change, user disabled) or an expiry check absent altogether is `read-the-code`.
   - `read-the-code`: a missing, wrong or incomplete check, filter or comparison that is wrong in every order and at
     every moment (missing tenant filter, missing permission check, wrong role comparison, ID not verified against the
     owner, default-allow).
   - `unclear`: the material does not show the mechanism; a row without a verbatim quote supporting its class is
     `unclear`.
   **Tie-break:** when `read-the-code` and an `ours` subclass both fit, `read-the-code` wins if the fix only adds a
   check that was absent in every path; otherwise `ours`. Between subclasses: O3 > O1 > O2 > O4 > O5.
   **Interpretation:** the exploit decides the class: needs parallel or interleaved requests → `O3`; needs a specific
   earlier step → `O4`; works by sequential repetition or in every order → `read-the-code`. The fix type is used as
   evidence only when the advisory does not say how the bug is triggered: then a fix that adds a missing user or
   tenant to a cache key → `O1`; a lock, transaction or atomic update → `O3`; a check absent in every path →
   `read-the-code`; a unique constraint or idempotency key added when the advisory does not say how the bug is
   triggered → `unclear` (gate note 5; this replaces the spec's "unique constraint for a bug that sequential
   repetition also triggers → read-the-code", which only applies when the advisory says so).
   **Interpretation (quote check):** "verbatim substring" is checked after collapsing every run of whitespace to one
   space in both the quote and the material text (summary, description, CWE ids and names, reference URLs, commit
   messages, file names and patches, PR titles and bodies). Code rules: missing quote → `unclear`; quote not found →
   `unclear` and flagged in REPORT.
4. **Gold calibration set** (expected labels here; readers receive `gold/input.jsonl` without labels):
   | id | case | expected |
   |---|---|---|
   | G1 | container-runtime TOCTOU | `excluded: not-web` |
   | G2 | "Proxy-Authorization header sent to another origin on redirect" (HTTP client) | `excluded: not-web` or `excluded: one-principal` |
   | G3 | "session remains valid after password change" | `included`, `read-the-code` |
   | G4 | "token expiry compared in local time instead of UTC" | `included`, `ours` `O5-time` |
   | G5 | "coupon redeemable twice with parallel requests" | `included`, `ours` `O3-concurrency` |
   | G6 | "coupon redeemable twice by resubmitting the form" | `included`, `read-the-code` |
   The first reader (this session, not blind) classifies the set before reading real rows; an independent reader (a
   fresh subagent given only `gold/input.jsonl` and this file's §2 rules without the table above) classifies it
   before any real row is read, and the first subagent of the first double-read batch classifies it again before
   its rows. Only independent readers are scored. Results are printed in REPORT; any miss becomes a listed PREREG
   clarification before reading starts (or, for the double-read subagent, before that checkpoint's decision).
5. **Classification in batches** of 20 rows in the shuffled order; `labels.jsonl` written after each batch with
   fields `ghsa_id`, `inclusion` (`included`/`excluded`), `reason` (exclusion reason or null), `class`
   (`ours`/`read-the-code`/`unclear` or null), `subclass` (O1-O5 or null), `quote`, `reader`, `batch`.
6. **Independent double read** at each decision checkpoint: every `ours` row plus
   `random.Random(6).sample(sorted(not-ours included ghsa_ids), 40)` (all if fewer than 40). The session writes
   `doubleread/<checkpoint>/input.jsonl` with material only (no labels), rows shuffled with `random.Random(7)`, and
   starts one fresh subagent per slice of about 20 rows, told to read only its slice and the PREREG rules, never
   `labels.jsonl`; outputs in `doubleread/<checkpoint>/labels-2.jsonl`. Reported: Cohen's kappa on `ours` vs
   not-`ours` and the share of first-reader `ours` rows the second reader confirms. Required before a decision:
   kappa >= 0.6 and confirmed >= 80%; otherwise the class rules are clarified as a listed PREREG change, every
   included row is re-read, and the check repeats; reading resumes in the same shuffled order until a new 300th
   included row, and the decision is taken there (gate note 3). A dispute is only `ours` vs not-`ours` (a different
   O-subclass is not a dispute; the second reader's `excluded` counts as not-`ours`). A disputed `ours` row becomes
   `unclear` for the decision count.

## §3 Stop rule and budget

- Share = `ours` / included (`unclear` and `read-the-code` in the denominator), Wilson 95% interval (z = 1.96);
  `ours` count = observed `ours` rows after the double read (a lower bound for the frame).
- Decision checkpoints: at exactly the 300th included row in the shuffled order (even in the middle of a batch: rows
  after it in the same batch are not counted for that checkpoint), and when every candidate is read. Decisions only
  at checkpoints, with the integer rule above.
- Budget: 48 h from the first data request (the §0 probe's first call); its timestamp is recorded in
  `data/budget.json`.
- After the listing, REPORT prints frame size per ecosystem and candidates via (a), (b), (c); after the first 100
  read, the observed included share, the expected reads to reach 300 included and the projected time.

## Seeds

Reading order `random.Random(5)`; double-read sample `random.Random(6)`; double-read input order `random.Random(7)`.

## Report

`REPORT.md`, first line `DONE` (decision CONTINUE or DROP), `NOT DONE` (budget ended with NO DECISION, or the run
stopped for another reason, stated) or `BLOCKED` (§0). Printed by `report.py` from committed rows; every number
written `<n><!--key-->` and re-derived by `verify.py` (exit 1 on any mismatch). Decision block, exactly one line:
`CONTINUE: <x>% ours (<k> of <n> included).`, `DROP: <x>% ours (<k> of <n> included).` or
`NO DECISION: budget reached; <x>% ours (<k> of <n>).`

## Access rules

Every request is GET, User-Agent `fenvix-research`, sleep until reset when `X-RateLimit-Remaining` < 500; no search
endpoint; nothing written except branch `claude/advisory-security-count`; no contact with anyone.
