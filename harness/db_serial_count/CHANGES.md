Each line: change, justification. All were made before any §2-§5 result (row) existed.

1. **Route (§0):** the workflow route's `search/code` with `GITHUB_TOKEN` answered HTTP 429 ("try again in 2.04s",
   `X-RateLimit-Remaining` 10) on the first attempt (run 45450935955); discovery runs on the work-session route
   (HTTP 200, total_count 4,488), which the §0 rule picks when only one route returns 200. Re-probe results are in
   `routes.md`.
2. **§4 split across routes (replaces PREREG interpretation 14):** the work session's proxy refuses REST reads of
   third-party repositories (HTTP 403 "GitHub access to this repository is not enabled for this session"), and the
   workflow token is throttled on code search. §4 code searches run in the work session
   (`perworker.py search`); the hit files are fetched and evaluated in the workflow (request
   `{"chunk": n, "perworker": true}`). Same rules, different route.
3. **Reusable workflows (replaces PREREG interpretation 11):** a `workflow_call` callee with a local caller is timed
   through each caller's runs; a callee that also has its own triggers is also timed through its own runs; a callee
   with no local caller and no other trigger is `unsupported` (the spec's "caller from another repository"), not
   `too_few_runs`. Justification: matches the spec text; the PREREG interpretation would have hidden these as
   not qualifying.
4. **Package-script arguments:** `npm test -- --runInBand` / `yarn test --runInBand` append the extra arguments to the
   last command of the resolved script (what npm/yarn do), so the runner line carries them. Justification: the flag
   regexes apply to "the line that invokes the runner, after script resolution".
5. **§4 working directory per repository:** a hit counts if it is under the working directory of any of the
   repository's pairs with median >= 10.0 minutes. Justification: §4 runs once per repository.
6. **U while §4 is pending:** a row with median >= 10.0 whose §4 check is not finished counts in U's numerator (as
   uncertain) until §4 completes. Justification: conservative for DROP.
7. **Debug run:** request 3 runs the pipeline on 8 named repositories (`results/debug/`) to check the code against
   the live API; these rows are not candidates and are never counted.
8. **Image prefixes:** `IMAGE_RE` is applied after removing a `docker.io/` (or `index.docker.io/`) registry prefix and
   the official-image prefix `library/`. Found in the debug run: saleor/saleor uses `library/postgres:15-alpine`,
   which is the official `postgres` image and the anchored regex missed.
9. **`COMPOSE_FILE`:** for a `docker compose ... up` step without `-f`, the files named in the step/job/workflow env
   `COMPOSE_FILE` (colon-separated) are read before the default names. Found in the debug run: PostHog/posthog sets
   `COMPOSE_FILE: docker-compose.dev.yml:docker-compose.profiles.yml`. Compose `extends` is not followed (limit).
10. **Limit noted, rule unchanged:** databases started by a bare `docker run ... postgres` (e.g. forem/forem) are not
    database jobs under §2.1; they are not counted (listed under limits).
