# Listed PREREG changes (each before any result it affects)

## Change 1 — class-rule clarification after the cp300 double read failed (2026-11-25)

Justification: at checkpoint cp300 the independent double read gave kappa 0.76 but confirmed only 19 of 24
first-reader `ours` rows (79.2% < 80%), so PREREG §2.6 requires a clarification of the class rules, a re-read of
every included row and a repeated double read. The disputes showed three ambiguous points; the clarifications below
are added to PREREG §2.2-§2.3 (and to READER_RULES.md given to readers). Thresholds, decision line, seeds, lists and
regexes are unchanged.

- **C1 (principal).** I1-I3 concern principals of the application (users, tenants, sessions, API clients). A local
  operating-system user or process acting outside the application, and a parameter value (locale, route parameter,
  cache variant) that the material does not say identifies a user, tenant or session, are not principals; such
  advisories are `excluded: no-I1-I3` unless another I1-I3 effect is stated.
- **C2 (O1 scope).** `O1-shared-state` covers in-memory or caching layers whose content depends on earlier requests
  (cache, memo, output/HTTP cache, singleton, global or module-level variable, pooled object, in-memory store). A
  persistent store (database table, file) that is queried or keyed without the user or tenant is a missing filter:
  `read-the-code`.
- **C3 (O4 scope).** A precondition the attacker creates with its own sequential requests (registering an account,
  creating or deleting its own object) does not make `O4`; if a check is missing in every order once that
  precondition exists, the row is `read-the-code`. `O4-order` needs stale state left by an earlier step of another
  principal or of the system (initialisation order, deletion and recreation by others) on which the exploit depends;
  a missing invalidation on an event (logout, password change, user disabled, object deleted) stays `read-the-code`
  as already stated under O5.
- **C4 (tie-break reminder, no rule change).** When the fix only adds a check absent in every path (for example
  "skip caching when the request carries credentials"), `read-the-code` wins over an `ours` subclass.

Procedure (gate note 3): every included row of the cp300 scope is re-read under C1-C4 (`reread/cp300b.jsonl`, all
300 rows with old and new label); changed labels are appended to `labels.jsonl` with reader `session-reread`;
reading then resumes in the same shuffled order until a new 300th included row (checkpoint `cp300b`), where the
double read is repeated with fresh subagents on the new sample.
