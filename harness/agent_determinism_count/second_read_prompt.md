# Second-read prompt (§4 item 2)

Given verbatim to a fresh general-purpose subagent (new context, no access to the first reader's labels). The session
replaces `{TEXTS}` with JSON lines `{"url": ..., "text": ...}` from `handread.py second --chunk N` and nothing else.

---

You are the second reader of public GitHub texts (commit messages, issue and pull request titles, bodies and
comments). Label each text by the rule below and nothing else. Do not open any URL, do not search, do not contact
anyone: the text given is all you read.

**Rule (§4 item 1b, verbatim).** `confirmed` only if the text meets all of: (i) it names a test, test suite, eval or
CI job of this repository; (ii) that test involves a model or agent call (names a model, provider, the agent, an LLM,
a prompt or an agent library); (iii) it says the test is flaky or non-deterministic because of that call (varying
output, provider errors, rate limits, latency), or that it was retried, skipped, disabled (including moved out of the
CI run), marked xfail or recorded because of varying output or cost, or that a test calling a live model was replaced
by a mock because of varying output or cost; (iv) dated on or after `HISTORY_START` (2024-01-01). Text that only
complains about model quality, or a flaky test whose stated cause is not the model call (database, network to
another service, timing of the test's own code) → `rejected`. Not enough text to decide (i)-(iii) → `unclear`.

Mocking counts only when the text says a test that called a live model was replaced by a mock because of varying
output or cost; mocking a model in unit tests from the start is ordinary practice and is not pain (`rejected`).
A flaky test caused by the provider's errors, rate limits or latency counts as flaky.

Every text given was found by a search dated on or after 2024-01-01; treat (iv) as met unless the text itself says
otherwise.

**Answer** with one JSON line per text, in the order given, and nothing else:
`{"url": "<url>", "label": "confirmed|rejected|unclear", "reason": "varying-output|provider-errors|cost|null", "quote": "<one line from the text that decides it, or empty>"}`

Texts:

{TEXTS}
