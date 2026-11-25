# Reader rules (verbatim extract of PREREG.md §2.2-§2.3)

For each advisory, output one JSON line with fields `ghsa_id`, `inclusion` (`included` or `excluded`), `reason` (exclusion reason from the closed list, or null), `class` (`ours`, `read-the-code` or `unclear`, null when excluded), `subclass` (O1-shared-state .. O5-time when `ours`, else null), `quote` (a verbatim substring of the advisory material that supports the inclusion decision and class; required for included rows), `reader`, `batch`.

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
