# P-018 · Block 4: cache with proof shared across machines

```
You are a work session for fenvix (deterministic CI engine; pytest plugin detpy with --det and --det-cache = skip tests with proof). Read fenvix-brain-cli CLAUDE.md, NOW.md, DECISIONS.md, RULES.md, NUMBERS.md ("Skip with proof"), sessions/2026-11-18-runner-prototype/REPORT.md and sessions/2026-11-17-headtohead/REPORT.md. English only in code, commits and reports. Model: Opus 5.5, high effort. Work autonomously; commit and push often; do not ask questions.

Fact (MEASURED, runner prototype): the cache works on one machine (pygments 99.4% of test time reused, 0 wrong) but does not cross machines: two GitHub-hosted machines from the same image gave different runtime digests, so nothing recorded on machine 1 was reusable on machine 2 (commit 28f5dd9 on fenvix-engine-cli branch claude/runner-prototype-ee21he records which runtime parts differ). Another session (claude/cache-proof-step1) is making the engine skip on large repositories: do not change the same files; coordinate through small, separate commits and rebase on it when it lands.

Goal (Block 4, part 2):
1. Runtime identity that is equal on equivalent machines and different whenever behaviour can differ: identify exactly which parts differed (interpreter binary, libpython, libc, stdlib listing, distribution RECORDs, paths) and key on content, not on machine paths or timestamps. Prove with tests: same image → same identity; a changed Python patch version, libc, or an installed package version → different identity.
2. A cache service: a small HTTP store for results and receipts keyed by the proof key (content-addressed, append-only, per organization, auth by token), plus the client in the engine (`--det-cache=https://...`) with a local fallback. Self-hostable for tests (single binary or Python service with SQLite/files); no cloud spending.
3. Measure on GitHub Actions of the public engine repo (free minutes): the runner-prototype demo (pygments, and click and marshmallow) with job 1 and job 2 on two different hosted machines sharing the cache service (run it inside the workflow as a service container or on the first job's machine via an artifact, whichever is simplest), every reuse verified by a fresh run (wrong must be 0).
Work on your own branch `claude/shared-cache` of fenvix-engine-cli (never main, never force-push).
Exit: cross-machine reuse on hosted runners > 90% of what the same pair reuses on one machine, 0 wrong with every reuse checked, identity tests green.
Report: fenvix-brain-cli sessions/2026-11-18-shared-cache/REPORT.md (first line DONE or PARTIAL; labels MEASURED/ESTIMATED/UNKNOWN). In chat only: Report ready: <path>.
```
