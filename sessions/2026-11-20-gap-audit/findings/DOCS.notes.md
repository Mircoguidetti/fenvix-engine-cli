# DOCS agent notes (gap audit P-036)

Agent `DOCS`. Area: the documentation, every claim against what exists. Audited: `fenvix-docs@main` (4cc4129, shallow),
`fenvix-landing@main` (f4d16e3; only its `content/` drafts and its links into the docs site),
`fenvix-engine-cli@claude/release-1` (worktree `/home/user/audit/engine`, 529c1609) with the built artifacts in
`/home/user/audit/build/dist`, `fenvix-app@main` (ce69a6b when the audit started; the checkout advanced to c59d913, the merge of
`claude/dashboard-vercel`, while the audit ran: every App entry was re-checked on c59d913), `fenvix-brain-cli@main` (1a955a7).

Output: `/home/user/audit/findings/DOCS.gaps.jsonl` (444 entries; severity: BLOCKS-USE 23, DEGRADES 264, MINOR 157; class: BUILD-LATER 8, BUILD-MVP 429, DECIDE 7; how: DOC 2, RAN 253, READ 189).
Scratch: `/home/user/audit/work/DOCS/` — `docs-copy/` (docs build), `docs-branches/r` (every branch of fenvix-docs),
`venv/` (wheel installed), `fenvix-home/` (install tree), `help/*.txt` (every captured help text), `pyproj/`, `utproj/`,
`odproj/` (test projects), `links-to-docs.txt`, `gen/` (the generator of the JSONL: `gen/part*.py` + `gen/build.py`).

Repository shorthand in the evidence fields: `engine@claude/release-1` = fenvix-engine-cli, branch claude/release-1.

## Index of entries by area

| area | entries | ids |
|---|---|---|
| Docs site / whole site | 3 | DOCS-001..002, DOCS-442 |
| Docs site / llms.txt | 1 | DOCS-003 |
| Docs site / header | 1 | DOCS-004 |
| Docs site / navigation | 1 | DOCS-005 |
| Docs site / index.md (Introduction) | 10 | DOCS-006..015 |
| Docs site / quickstart.md | 9 | DOCS-016..024 |
| Docs site / concepts.md | 12 | DOCS-025..036 |
| Docs site / commands.md | 14 | DOCS-037..050 |
| Docs site / faq.md | 6 | DOCS-051..056 |
| Docs site / limits.md | 19 | DOCS-057..075 |
| Docs site / security.md | 5 | DOCS-076..080 |
| Docs site / compatibility.md | 9 | DOCS-081..089 |
| Docs site / data/compatibility.json | 1 | DOCS-090 |
| Docs site / api/authentication.md | 14 | DOCS-091..104 |
| Docs site / api/errors.md | 9 | DOCS-105..113 |
| Docs site / api/databases.md | 5 | DOCS-114..118 |
| Docs site / api/database-users.md | 3 | DOCS-119..121 |
| Docs site / api/network-allowlist.md | 2 | DOCS-122..123 |
| Docs site / api/usage.md | 3 | DOCS-124..126 |
| Docs site / api/organization.md | 1 | DOCS-127 |
| Docs site / api/api-keys.md | 3 | DOCS-128..130 |
| Docs site / openapi/fenvix-public-api.json | 1 | DOCS-131 |
| Docs site / API reference | 1 | DOCS-132 |
| Docs site / README.md | 6 | DOCS-133..138 |
| Docs site / PUBLISHING.md | 4 | DOCS-139..142 |
| Docs site / MIGRATION.md | 1 | DOCS-143 |
| Docs site / REPORT.md | 2 | DOCS-144..145 |
| Docs site / LIMITS-SOURCES.md | 1 | DOCS-146 |
| Docs site / site.config.mjs | 2 | DOCS-147..148 |
| Docs site / sync.config.json + scripts | 5 | DOCS-149..153 |
| Docs site / build | 1 | DOCS-154 |
| Docs site / inbound links | 1 | DOCS-155 |
| Docs site / draft in fenvix-landing content/ | 2 | DOCS-156..157 |
| Docs site / draft in fenvix-landing content/index.md | 4 | DOCS-158..161 |
| Docs site / draft in fenvix-landing content/quickstart.md | 4 | DOCS-162..165 |
| Docs site / draft in fenvix-landing content/concepts.md | 5 | DOCS-166..170 |
| Docs site / draft in fenvix-landing content/commands.md | 6 | DOCS-171..176 |
| Docs site / draft in fenvix-landing content/compatibility.md | 7 | DOCS-177..183 |
| Docs site / draft in fenvix-landing content/faq.md | 4 | DOCS-184..187 |
| Docs site / draft in fenvix-landing content/security.md | 6 | DOCS-188..193 |
| Engine docs / README.md | 12 | DOCS-194..205 |
| Engine docs / docs/RELEASE-1.md | 6 | DOCS-206..211 |
| Engine docs / docs/SHARED-CACHE.md | 5 | DOCS-212..216 |
| Engine docs / docs/ARCHITECTURE.md | 4 | DOCS-217..220 |
| Engine docs / docs/LIMITS.md | 3 | DOCS-221..223 |
| Engine docs / docs/NODE.md | 9 | DOCS-224..232 |
| Engine docs / docs/NODE-CACHE.md | 4 | DOCS-233..236 |
| Engine docs / docs/GO.md | 10 | DOCS-237..246 |
| Engine docs / docs/JVM.md | 5 | DOCS-247..251 |
| Engine docs / docs/ALL-RUNNERS.md | 2 | DOCS-252, DOCS-435 |
| Engine docs / docs/runners/ | 2 | DOCS-253..254 |
| Engine docs / docs/ | 1 | DOCS-255 |
| Engine docs / docs/RUNNER-PROTOTYPE.md | 2 | DOCS-256..257 |
| Engine docs / node/ | 1 | DOCS-258 |
| Engine docs / go/ | 1 | DOCS-259 |
| Engine docs / jvm/ | 1 | DOCS-260 |
| Engine docs / release/ | 1 | DOCS-261 |
| Engine docs / runner/ | 1 | DOCS-262 |
| Engine docs / pytest options | 8 | DOCS-263..270 |
| Engine docs / detpy CLI | 6 | DOCS-271..276 |
| Engine docs / environment variables | 1 | DOCS-277 |
| Engine docs / exact culprit | 1 | DOCS-278 |
| Engine docs / dependency verdict | 1 | DOCS-279 |
| Engine docs / help text: pytest --help | 12 | DOCS-280..291 |
| Engine docs / help text: python -m detpy | 13 | DOCS-292..304 |
| Engine docs / help text: detjs | 6 | DOCS-305..310 |
| Engine docs / help text: fenvix-go | 5 | DOCS-311..315 |
| Engine docs / help text: fenvix-agent.jar | 5 | DOCS-316..320 |
| Engine docs / help text: fenvix-skip | 1 | DOCS-321 |
| Engine docs / help text: fenvix | 7 | DOCS-322..328 |
| Engine docs / naming | 17 | DOCS-329..345 |
| Engine docs / licensing | 1 | DOCS-346 |
| App docs / README.md | 4 | DOCS-347..350 |
| App docs / github-app/README.md | 2 | DOCS-351..352 |
| App docs / docs/ | 6 | DOCS-353..357, DOCS-363 |
| App docs / dashboard texts | 5 | DOCS-358..362 |
| Docs missing / quickstart: Python pytest (free, local) | 1 | DOCS-364 |
| Docs missing / quickstart: other Python runners | 1 | DOCS-365 |
| Docs missing / quickstart: Vitest | 1 | DOCS-366 |
| Docs missing / quickstart: Jest | 1 | DOCS-367 |
| Docs missing / quickstart: other Node runners | 1 | DOCS-368 |
| Docs missing / quickstart: browser tests (Playwright, Cypress) | 1 | DOCS-369 |
| Docs missing / quickstart: Go | 1 | DOCS-370 |
| Docs missing / quickstart: Java/Kotlin with Gradle | 1 | DOCS-371 |
| Docs missing / quickstart: Java/Kotlin with Maven | 1 | DOCS-372 |
| Docs missing / quickstart: hosted (runs-on: fenvix) | 1 | DOCS-373 |
| Docs missing / installation: Linux | 1 | DOCS-374 |
| Docs missing / installation: macOS | 1 | DOCS-375 |
| Docs missing / installation: Windows | 1 | DOCS-376 |
| Docs missing / installation: requirements | 1 | DOCS-377 |
| Docs missing / installation: containers and CI images | 1 | DOCS-378 |
| Docs missing / CLI reference: pytest plugin options | 1 | DOCS-379 |
| Docs missing / CLI reference: detpy command | 1 | DOCS-380 |
| Docs missing / CLI reference: detjs | 1 | DOCS-381 |
| Docs missing / CLI reference: fenvix-go | 1 | DOCS-382 |
| Docs missing / CLI reference: fenvix-agent.jar and fenvix-skip | 1 | DOCS-383 |
| Docs missing / CLI reference: fenvix | 1 | DOCS-384 |
| Docs missing / --det controls reference | 1 | DOCS-385 |
| Docs missing / levels (L0, L1, L2) explained | 1 | DOCS-386 |
| Docs missing / verifier and trace format | 1 | DOCS-387 |
| Docs missing / repro guide (flaky test to reproducible defect) | 1 | DOCS-388 |
| Docs missing / replay guide and bundle format | 1 | DOCS-389 |
| Docs missing / exploration guide | 1 | DOCS-390 |
| Docs missing / network record and replay (cassettes) | 1 | DOCS-391 |
| Docs missing / skip with proof guide | 1 | DOCS-392 |
| Docs missing / receipts reference | 1 | DOCS-393 |
| Docs missing / shared cache setup | 1 | DOCS-394 |
| Docs missing / parallel mode | 1 | DOCS-395 |
| Docs missing / --det-isolate | 1 | DOCS-396 |
| Docs missing / exact culprit | 1 | DOCS-397 |
| Docs missing / dependency-update verdict | 1 | DOCS-398 |
| Docs missing / framework and plugin compatibility notes | 1 | DOCS-399 |
| Docs missing / GitHub Action usage | 1 | DOCS-400 |
| Docs missing / GitHub Actions recipe with the free plugin | 1 | DOCS-401 |
| Docs missing / GitHub App install (customer) | 1 | DOCS-402 |
| Docs missing / runs-on: fenvix job guide | 1 | DOCS-403 |
| Docs missing / pull request comment and check run | 1 | DOCS-404 |
| Docs missing / CI recipe: GitLab CI | 1 | DOCS-405 |
| Docs missing / CI recipe: CircleCI | 1 | DOCS-406 |
| Docs missing / CI recipe: Buildkite | 1 | DOCS-407 |
| Docs missing / CI recipe: Jenkins | 1 | DOCS-408 |
| Docs missing / CI recipe: Azure Pipelines | 1 | DOCS-409 |
| Docs missing / CI recipe: Bitbucket Pipelines | 1 | DOCS-410 |
| Docs missing / runner vendors | 1 | DOCS-411 |
| Docs missing / MCP server for agents | 1 | DOCS-412 |
| Docs missing / API reference | 1 | DOCS-413 |
| Docs missing / API for agents and API keys | 1 | DOCS-414 |
| Docs missing / dashboard guide | 1 | DOCS-415 |
| Docs missing / billing and plans | 1 | DOCS-416 |
| Docs missing / shadow trial | 1 | DOCS-417 |
| Docs missing / audit reruns | 1 | DOCS-418 |
| Docs missing / warm cache at install | 1 | DOCS-419 |
| Docs missing / organizations, members and roles | 1 | DOCS-420 |
| Docs missing / regions and data residency | 1 | DOCS-421 |
| Docs missing / security and privacy | 1 | DOCS-422 |
| Docs missing / data retention, deletion and processing terms | 1 | DOCS-423 |
| Docs missing / limits per language | 1 | DOCS-424 |
| Docs missing / troubleshooting | 1 | DOCS-425 |
| Docs missing / FAQ | 1 | DOCS-426 |
| Docs missing / changelog | 1 | DOCS-427 |
| Docs missing / versioning and compatibility policy | 1 | DOCS-428 |
| Docs missing / upgrade guide | 1 | DOCS-429 |
| Docs missing / licensing | 1 | DOCS-430 |
| Docs missing / support and contact | 1 | DOCS-431 |
| Docs missing / glossary | 1 | DOCS-432 |
| Docs missing / multi-language and monorepo projects | 1 | DOCS-433 |
| Docs missing / docs for coding agents (llms.txt) | 1 | DOCS-434 |
| Engine docs / output text: detpy repro, replay, verify | 6 | DOCS-436..441 |
| Engine docs / fenvix-brain-cli ARCHITECTURE.md | 1 | DOCS-443 |
| Engine docs / fenvix-brain-cli PRODUCT.md | 1 | DOCS-444 |

## (c) What the lead should know

1. **The documentation site documents another product.** `fenvix-docs` (16 pages, `SITE_PUBLIC = true`, domain
   `docs.fenvix.dev` from `site.config.mjs`) is entirely about the removed "database that sleeps" (MongoDB protocol,
   fork/restore/erase, `fvx_` API keys, 17 database endpoints). `grep -rilE 'pytest|flaky|determinis|vitest|jest|runs-on|GitHub App|fingerprint|skip with proof' content/`
   finds nothing. No branch of the repository (6 branches fetched) has a page of the current product. Its newest commit
   is 2026-11-10.
2. **The generator of that site cannot run any more.** `npm ci && npm run build` works (16 pages) and `check-links`
   passes, but only because the build renders the committed Markdown. `npm run sync-spec`, `sync-compat`, `check-drift`
   and `check` all fail: they import `fenvix-app/control-plane/src/routes/public/openapi.ts` (deleted with the old
   product) and read `fenvix-engine/docs/compatibility.json` (the current engine is the repository `fenvix-engine-cli`
   and has no such file). `sync.config.json` names no branch.
3. **A newer draft exists but is not published.** `fenvix-landing/content/*.md` (7 pages, 2026-11-17) describes
   deterministic CI. The landing no longer renders it (it redirects `/docs/*` to `docs.fenvix.dev`); it only feeds the
   landing's `/llms.txt`. The draft is itself behind release-1: two languages ("Other languages come later"), three
   pytest options, superseded plans (runs per month instead of run units and prices), "nightly exploration included
   in every plan" (it is a paid add-on), API keys and an API for agents that do not exist, GitHub App permissions
   understated (the App has Administration, Contents and Workflows write).
4. **The landing links into the docs 156 times; 28 links point at anchors that do not exist** on the published pages
   (`/commands/#flags`, `#replay`, `#pull-a-bundle`, `#api-keys`, `#api-for-coding-agents`, `#read-runs-and-defects`;
   `/concepts/#deterministic-run`, `#seed-and-order`, `#fingerprint`, `#polluter-and-state-setter`, `#defect`,
   `#skip-receipt`), and 12 point at `/#measured-results`, which shows MongoDB compatibility numbers next to the
   landing's "358 of 388 flaky tests reproduced". The dashboard's Docs link goes to the same site.
5. **Docs that describe something the release-1 code does not do (found by running it):**
   - `pytest --det --det-cache=https://...` (docs/SHARED-CACHE.md, docs/RELEASE-1.md "DIR|URL", docs/ALL-RUNNERS.md):
     the URL is taken as a directory name; `./https:/host/...` is created and the run reports success. The Python
     client (`python/detpy/remote_cache.py`) is imported by nothing; its tests are skipped with
     "shared-cache Python client not yet ported onto the Rust proof cache" (10 + 4 skips). `runner/fenvix-run --cache URL`
     passes the URL straight to pytest, so the hosted shared cache for Python stores into a local directory.
     (DOCS-206, DOCS-212..213, DOCS-287, DOCS-435)
   - The dashboard prints `fenvix defects pull <id>` and a replay path `.fenvix/defects/<id>/order.txt`; the CLI has no
     `defects` command, the API has no bundle download, API keys are "Coming soon". `detpy repro` writes
     `.detpy/repro/<test>-<hash>/`.
   - `python -m detpy zope`, `detjs bun`, `detjs deno` (spellings in docs/RELEASE-1.md and in `fenvix --help`) are not
     commands (`zope-testrunner`, `bun-test`, `deno-test`).
6. **Level 1 is not in release-1.** `--det-threads` / `--det-async` exist only on `origin/claude/l1-threads-fix` and
   `origin/claude/review-r007b`; `git merge-base --is-ancestor origin/claude/l1-threads-fix origin/claude/release-1`
   is false and `pytest --help` on the built wheel has neither option. The brain records Block 3 as closed.
   docs/RELEASE-1.md does not say L1 is absent. (Listed once as a documentation entry; the feature gap belongs to the
   engine agents.)
7. **The commands of promise 1 and 2 are undocumented everywhere**: `detpy repro`, `detpy explore`, `detpy replay`
   appear in no file of the engine's README/docs and are not reachable through `fenvix`; Node, Go and JVM have no
   repro/explore/replay at all.
8. **No GitHub Action and no MCP server exist** on any of the 62 engine branches or in fenvix-app (searched every
   branch's file list), so the two pages cannot be written yet; the landing says the MCP server "is part of the free
   tools".
9. **Nothing is installable by a user**: no package is published (release-1.yml only uploads CI artifacts), detjs is a
   private npm package, the only install script targets a runner image (`/opt/fenvix`, pip into the system Python),
   every artifact is Linux x86_64.
10. **Naming**: detpy / detjs / fenvix-go / fenvix-agent.jar (usage says `fenvix-jvm`) / fenvix-skip / fenvix; state
    in `.detpy/`, `.detjs/`, `.fenvix/`, `~/.cache/fenvix/`; env prefixes `DETPY_`, `DETJS_`, `FENVIX_`, JVM
    `fenvix.*`; cache flags `--det-cache` / `--skip-cache` / `--deps`; trace format string `detpy-trace` in every
    language's files; pytest output headers `detpy (Level 0)`.
11. **Licence metadata contradicts itself**: `MIT` in pyproject.toml and node/package.json, `Proprietary` in the API's
    OpenAPI, no LICENSE file anywhere (DECIDE entry).
12. Contradictions between documents: `fenvix-docs/README.md` says the domain is not decided and SITE_PUBLIC defaults
    to false (config: `fenvix.dev`, true); `MIGRATION.md` says nothing was done (the landing redirect is in place);
    `PUBLISHING.md` says 15 pages (16); `fenvix-app/README.md` says migrations 0001 to 0014 (0017 exists) and
    `github-app/README.md` says there is no Actions workflow (test.yml and deploy.yml exist); engine
    `docs/ARCHITECTURE.md` says the cache is "not wired"; engine `README.md` says the epoch default is 2025-01-01 (it
    is the HEAD commit time); the brain's PRODUCT.md and ARCHITECTURE.md (2026-11-16) predate the decisions of
    2026-11-17..20.
13. `fenvix-docs/REPORT.md` and `fenvix-app/docs/DEPLOY-VERCEL.md` are in Italian (repository rule: English only).
14. Severity note: a URL given to the Python cache is not reported as WRONG-RESULT here, because no test outcome is
    wrong (the run silently caches into a local directory); it is filed as the shared cache service being unusable
    for Python (BLOCKS-USE) plus the documents that claim it.

## (a) Could not check

- **Whether docs.fenvix.dev, fenvix.dev, console.fenvix.dev, api.fenvix.dev, github.fenvix.dev answer and what they
  serve.** The agent proxy refuses the hosts (`curl -sS -i https://docs.fenvix.dev/` => `HTTP/1.1 403 Forbidden (agent
  proxy: no rule or network setting allows this host)`). Where the docs site is deployed is therefore known only from
  files: `vercel.json` (build settings, no domain), `site.config.mjs` (`DOMAIN = "fenvix.dev"` => `docs.fenvix.dev`),
  `PUBLISHING.md` (manual Vercel import), and the landing's permanent redirect to `https://docs.fenvix.dev/`.
- **Whether the repository `Mircoguidetti/fenvix-engine` (the sync's engine source) still exists.**
  `git ls-remote --heads https://github.com/Mircoguidetti/fenvix-engine` => `could not read Username` (not readable
  with this session's credentials; the same command lists heads for fenvix-engine-cli, fenvix-app, fenvix-docs and
  fenvix-landing).
- **How a customer's `run: pytest` step becomes an engine run on a fenvix machine** (the dashboard says "fenvix wraps
  the test command with the engine"). Not traced through `fenvix-app` infra; left to the app/runner agents.
- **The numbers quoted in the landing drafts** (358 of 388; 0 wrong in 4,464; home-assistant 97%, docusaurus 98%,
  vue-core 25%) were only matched against `fenvix-brain-cli/NUMBERS.md`, not re-measured.
- **Help texts on macOS and Windows**; `detpy explore` was not run (time budget); `fenvix-go test`, `detjs <runner>`
  and `fenvix-agent.jar run` were exercised only for their help, usage and option errors, not for the correctness of
  what their documents claim (language agents).
- **The landing's marketing pages** (index, product/*, pricing, developers) were read only for their links into the
  docs and for one MCP sentence; their claims are not audited here.
- **docs/runners/*.md, docs/HARNESS.md, docs/PARALLEL-PROOF-DESIGN.md, docs/REPORT-node-l0*.md**: checked for command
  and option spellings only (all options named there exist), not claim by claim.
- **Django, nose2, ward, zope.testrunner runners**: not installed in the scratch venv, so only their failure without
  the runner was observed.

## (b) Evidence appendix (commands and trimmed real outputs)

### E1. Docs site build and checks (Docs site / build, README.md, PUBLISHING.md, sync.config.json + scripts)

Gap ids: DOCS-002..003, DOCS-133..142, DOCS-146, DOCS-149..154

```
$ cp -r /home/user/fenvix-docs docs-copy && cd docs-copy && rm -rf .git && timeout 600 npm ci && timeout 600 npm run build
Built 16 docs pages into dist/ (SITE_PUBLIC=true).          (exit 0)
$ npm run check-links
check-links: 395 internal link(s) on 16 page(s), all good.
$ npm run check-drift
Error: Source repository "fenvix-app" is not at /home/user/audit/work/DOCS/fenvix-app.
$ FENVIX_APP_REPO=/home/user/fenvix-app npm run sync-spec
  code: 'ERR_MODULE_NOT_FOUND', url: 'file:///home/user/fenvix-app/control-plane/src/routes/public/openapi.ts'
$ FENVIX_ENGINE_REPO=/home/user/audit/engine FENVIX_APP_REPO=/home/user/fenvix-app npm run sync-compat   (same error)
$ FENVIX_ENGINE_REPO=/home/user/audit/engine FENVIX_APP_REPO=/home/user/fenvix-app npm run check          (same error)
$ ls /home/user/fenvix-app/control-plane; ls /home/user/audit/engine/docs/compatibility.json /home/user/audit/engine/compat
No such file or directory (all three)
$ head -3 dist/llms.txt
# FENVIX
> FENVIX is a database service where every customer, agent or test gets its own database. ... It speaks the MongoDB protocol ...
$ cat dist/robots.txt
User-agent: *
Allow: /
Sitemap: https://docs.fenvix.dev/sitemap.xml
```

### E2. openapi diff (Docs site / openapi/fenvix-public-api.json, API reference, api/*)

Gap ids: DOCS-069, DOCS-091..132, DOCS-140

```
docs  openapi/fenvix-public-api.json : title 'Fenvix public API', server https://api.fenvix.dev/v1/public, 12 paths, 17 operations,
      security apiKey (bearer fvx_<43 characters>) + session
app   openapi/fenvix-api.yaml        : title 'fenvix API', server https://github.fenvix.dev/v1, 42 paths, 47 operationIds,
      security session (Supabase Auth access token) + runner (per-machine credential)
common paths: {'/organization'}
docs paths: /databases, /databases/{id}, /databases/{id}/users, /databases/{id}/users/{username}, /databases/{id}/ip-allowlist,
            /usage, /databases/{id}/usage, /usage/export, /organization, /operations/{id}, /api-keys, /api-keys/{id}
app (fenvix-app) supabase/migrations/0014_dashboard_api.sql:25-37 drops public_api_keys, database_ip_allowlists, data_audit_log,
            database_tags, usage_hourly, usage_daily, wake_events, invoices, operations, idempotency_keys, audit_log, api_keys, databases
$ grep -rn 'fvx_\|fnx_' github-app/src src openapi | wc -l          => 0
$ grep -rnE 'Idempotency-Key|Idempotent-Replay' github-app/src openapi | wc -l   => 0
$ grep -rni 'x-request-id' github-app/src | wc -l                    => 0
$ grep -rn 'rateLimit\|perMinute' github-app/src/api | wc -l         => 0
```

### E3. Links from the landing and the dashboard into the docs site (Docs site / inbound links, concepts.md and commands.md anchors, index.md #measured-results)

Gap ids: DOCS-014, DOCS-031..036, DOCS-045..050, DOCS-155

`grep -rhoE "https://docs\.fenvix\.dev/[^\"' <)]*"` over fenvix-landing (html, md, mjs, js, json) and fenvix-app, counted:

```
     82 https://docs.fenvix.dev/
     12 https://docs.fenvix.dev/#measured-results
      1 https://docs.fenvix.dev/:path*
      1 https://docs.fenvix.dev/:splat
      6 https://docs.fenvix.dev/commands/
      2 https://docs.fenvix.dev/commands/#api-for-coding-agents
      2 https://docs.fenvix.dev/commands/#api-keys
      2 https://docs.fenvix.dev/commands/#flags
      2 https://docs.fenvix.dev/commands/#pull-a-bundle
      4 https://docs.fenvix.dev/commands/#read-runs-and-defects
      2 https://docs.fenvix.dev/commands/#replay
      4 https://docs.fenvix.dev/compatibility/
      4 https://docs.fenvix.dev/concepts/
      2 https://docs.fenvix.dev/concepts/#defect
      2 https://docs.fenvix.dev/concepts/#deterministic-run
      4 https://docs.fenvix.dev/concepts/#fingerprint
      2 https://docs.fenvix.dev/concepts/#polluter-and-state-setter
      2 https://docs.fenvix.dev/concepts/#seed-and-order
      2 https://docs.fenvix.dev/concepts/#skip-receipt
      2 https://docs.fenvix.dev/faq/
     10 https://docs.fenvix.dev/quickstart/
      8 https://docs.fenvix.dev/security/
```

Checked against the built `docs-copy/dist`: every page path exists; missing anchors: commands/#api-for-coding-agents,
#api-keys, #flags, #pull-a-bundle, #read-runs-and-defects, #replay; concepts/#defect, #deterministic-run, #fingerprint,
#polluter-and-state-setter, #seed-and-order, #skip-receipt (28 links). `/#measured-results` exists and is the MongoDB table.
(`/:path*` and `/:splat` are the redirect templates in vercel.json and dist/_redirects.)

### E4. Branches of the docs repository (Docs site / whole site)

Gap ids: DOCS-442

```
$ git clone --depth 1 --no-single-branch https://github.com/Mircoguidetti/fenvix-docs r
origin/docs-limits-restore  2026-10-30  pytest-mentions=0      (git grep -il 'pytest\|flaky' <branch> -- content | wc -l)
origin/docs-migration       2026-10-30  pytest-mentions=0
origin/docs-navy            2026-10-30  pytest-mentions=0
origin/docs-site            2026-10-30  pytest-mentions=0
origin/main                 2026-11-10  pytest-mentions=0
origin/site-public          2026-10-30  pytest-mentions=0
```

### E5. A URL as the Python cache (Engine docs / docs/SHARED-CACHE.md, docs/RELEASE-1.md, docs/ALL-RUNNERS.md, help text)

Gap ids: DOCS-206, DOCS-212..213, DOCS-287, DOCS-435

```
$ cd work/DOCS/pyproj   # two tests, git repository
$ pytest -q --det --det-cache=https://cache.example.invalid/acme/repo
..                                                                       [100%]
=============================== detpy (Level 0) ================================
trace: .../pyproj/.detpy/trace.jsonl  order digest: cc2c0e0edf20279b83e7fb8ddf811b7c  seed: 0
============================ detpy cache with proof ============================
reused 0 result(s) with proof, ran 2, recorded 2 (check 0.0s, record 0.011s); config d11af83b..., runtime 60bf3e94...
not reused: new 2
receipts: .../pyproj/https:/cache.example.invalid/acme/repo/receipts.jsonl
2 passed in 0.04s            (exit 0;  ls => .detpy  https:  test_a.py)
$ cd ../utproj && python -m detpy unittest --det --det-cache=https://cache.example.invalid/acme/repo test_u
receipts: .../utproj/https:/cache.example.invalid/acme/repo/receipts.jsonl
$ grep -rn "remote_cache" python/detpy --include=*.py | grep -v '^python/detpy/remote_cache.py'     => (nothing)
$ sed -n 21,22p tests/test_shared_cache.py
_CLIENT_NOT_PORTED = pytest.mark.skip(
    reason='shared-cache Python client not yet ported onto the Rust proof cache (claude/rust-hotpaths-2)')
$ grep -c _CLIENT_NOT_PORTED tests/test_shared_cache.py tests/test_review_r008.py   => 11 and 5 (one definition each)
runner/fenvix-run:248-253: if is_url(a.cache): ... cache_arg = f"{a.cache.rstrip('/')}/{ns}"; :270 f"--det-cache={cache_arg}"
```

### E6. Commands that documents or the dashboard name and the CLI refuses

Gap ids: DOCS-163, DOCS-173, DOCS-176, DOCS-207..208, DOCS-250, DOCS-310, DOCS-313, DOCS-318..319, DOCS-323..325, DOCS-338, DOCS-341, DOCS-355, DOCS-357..358, DOCS-368

```
$ fenvix defects pull d-0412        => fenvix: unknown command 'defects' (fenvix --help)      exit 2
$ fenvix repro tests/test_x.py::t   => fenvix: unknown command 'repro' (fenvix --help)        exit 2
$ fenvix explore --budget 5         => fenvix: unknown command 'explore' (fenvix --help)      exit 2
$ fenvix replay x                   => fenvix: unknown command 'replay' (fenvix --help)       exit 2
$ fenvix --version                  => fenvix: unknown command '--version' (fenvix --help)    exit 2
$ fenvix version                    => fenvix release-1 / detpy 0.1.0 / detjs 0.1.0 / fenvix-go present / fenvix-skip present / fenvix-agent.jar present
$ fenvix detect /home/user/audit/engine  => python
$ python -m detpy zope --help       => detpy: error: argument cmd: invalid choice: 'zope' (choose from 'unittest', 'django', 'nose2', 'doctest', 'zope-testrunner', 'ward', 'verify', 'backends', 'repro', 'explore', 'replay')
$ detjs bun --det ; detjs deno test --det   => usage text (commands are bun-test, deno-test), exit 2
$ detjs vitest run --det --det-order=x      => Error: detjs: unknown option --det-order
$ detjs jest --det --det-isolate            => Error: detjs: unknown option --det-isolate
$ fenvix-go test --det --det-order=x        => fenvix-go: unknown fenvix flag --det-order
$ fenvix-go test --det --det-record         => fenvix-go: unknown fenvix flag --det-record
$ java -jar fenvix-agent.jar run --det --det-trace=x.jsonl -- mvn test   => fenvix-jvm: unknown build tool --det-trace=x.jsonl (gradle, gradlew, mvn, mvnw)
$ java -jar fenvix-agent.jar run --det --det-epoch=2026-01-01T00:00:00Z -- mvn -v  => fenvix-jvm: unknown build tool --det-epoch=...
$ java -jar fenvix-agent.jar run --help     => fenvix-jvm: unknown build tool --help (gradle, gradlew, mvn, mvnw)
```

### E7. Help texts (Engine docs / help text: *). Full captures: `/home/user/audit/work/DOCS/help/*.txt`

Gap ids: DOCS-280..328

`pytest --help` (venv with the release-1 wheel, pytest 9.2.0), the plugin's group, 30 options: `pytest-help.txt` lines 214-304
(group title `deterministic execution (Level 0):`).

```
$ python -m detpy --help
usage: detpy [-h] {unittest,django,nose2,doctest,zope-testrunner,ward,verify,backends,repro,explore,replay} ...
deterministic Python test execution (Level 0)
$ python -m detpy --version        => detpy: error: the following arguments are required: cmd   (exit 2)
$ python -m detpy unittest --help  => usage: python -m unittest [-h] [-v] [-q] [--locals] ...   (unittest's own help)
$ python -m detpy doctest --help   => detpy doctest: error: the following arguments are required: file
$ python -m detpy django --help    => Traceback ... ModuleNotFoundError: No module named 'django'   (same shape: nose2, ward, zope-testrunner)
$ node bin/detjs.js --help         (exit 2)
usage: detjs vitest|jest|node-test|mocha|bun-test|deno-test|tap|ava|jasmine|uvu [--det options] [runner args]
       detjs verify TRACE TRACE [...] [--json] [--show-stable]
       detjs --det-help
$ node bin/detjs.js vitest --help  (empty directory) => Error: detjs: vitest is not installed in <cwd>  + 10 stack frames
$ fenvix-go --help                 (exit 0, to stderr; 14 flags; --det-adapt, --det-max-events, --det-keep-parallel absent)
$ fenvix-go test --help            => usage: go test [build/test flags] [packages] [build/test flags & test binary flags]
$ fenvix-go version                => fenvix-go: unknown command "version"
$ java -jar fenvix-agent.jar --help   (exit 2)
usage: fenvix-jvm run [--det] [--det-seed=N] [--deps] [--det-disable=a,b] [--det-allow-host=h] [--out=DIR] -- <build command>
       fenvix-jvm merge DIR | verify TRACE... | paths
[exit 2]
$ fenvix-skip --help               => usage: fenvix-skip decide A_DEPS_DIR B_DEPS_DIR --root-b DIR [--json OUT]   (exit 2)
```

Reviewer ids (R-0xx, J14, V15, P-0xx) were searched in user-visible string literals of python/detpy, node/src, node/bin,
go/cmd, go/internal, jvm/agent, jvm/rt: none found in messages (only in comments and docstrings). They are in the
documents (docs/RELEASE-1.md, LIMITS.md, NODE.md, GO.md, JVM.md, ALL-RUNNERS.md). The jargon that does reach users is
"Level 0", "the carried-set rule", "PROTOTYPE", "the harness", "the culprit finder", "release 1 / runner image".

### E8. `detpy repro`, `replay`, `verify` on an order-dependent test (Engine docs / output text)

Gap ids: DOCS-436..441

```
$ cd work/DOCS/odproj   # test_a_polluter sets a module global, test_b_victim asserts it is absent
$ python -m detpy repro "test_od.py::test_b_victim" --seeds 5 --confirm 3 --max-runs 40
detpy repro: test_od.py::test_b_victim: reproduced
  found with fixed order; order minimised from 2 to 2 test(s)
  polluter(s): test_od.py::test_a_polluter
  replay: 3/3 failed, identical fingerprint: True
  first diverging event vs a passing run: outcome-only: identical observed events, different outcome (passed vs failed): the cause is a source Level 0 does not observe
  replay: pytest --det --det-order=.detpy/repro/test_b_victim-71a9bb80/order.txt
  5 pytest runs, 17.45 s                      (MEASURED, shared 4-core machine, niced)
$ find .detpy -maxdepth 3
.detpy/repro/test_b_victim-71a9bb80/{fail.trace.jsonl,pass.trace.jsonl,order.txt,bundle.json}
.detpy/repro/.work/ (17 files: search-fixed.json, replay-0.jsonl, collect-fixed.json, alone-fixed.order.txt, ...)
$ python -m detpy replay .detpy/repro/test_b_victim-71a9bb80 --runs 3
{ "test": "test_od.py::test_b_victim", "runs": 3, "fails": 3, "identical_fingerprint": true, "matches_bundle": true }
$ python -m detpy verify .../pass.trace.jsonl .../fail.trace.jsonl
detpy verify: 2 runs, 2 tests
order: DIFFERS between runs
covered by Level 0: 0  not covered: 1  missing: 1  outcome-unstable: 1
reasons: missing=1 outcome-only=1
NOT-COVERED test_od.py::test_b_victim  [outcome-only] outcomes=passed,failed
```

### E9. Flag coverage ("flag coverage" in the evidence fields)

Gap ids: DOCS-219, DOCS-224..246, DOCS-263..270, DOCS-277

Options in code (python/detpy/_level0.py OPTIONS + plugin.py; node/src/session.js; go/cmd/fenvix-go/test.go;
jvm .../cli/Main.java) searched in each language's documents:

```
python (README.md, docs/LIMITS.md, ARCHITECTURE.md, SHARED-CACHE.md, ALL-RUNNERS.md, RELEASE-1.md, RUNNER-PROTOTYPE.md, HARNESS.md, runners/*python*)
  not mentioned : --det-order (only PARALLEL-PROOF-DESIGN.md), --det-cassette, --det-cache-no-follow, --det-cache-epoch-window,
                  --det-cache-receipts (only PARALLEL-PROOF-DESIGN.md)
  mentioned once: --det-compare README.md:30, --det-record README.md:32, --det-tick README.md:42, --det-cache-dists ALL-RUNNERS.md:92,
                  --det-cache-shared RELEASE-1.md:34, --det-cache-keys RELEASE-1.md:16, --det-plan / --det-plan-worker LIMITS.md:23,
                  --det-isolate RELEASE-1.md:16
node (docs/NODE.md, NODE-CACHE.md, runners/{mocha,node-test,ava,tap,uvu,jasmine,bun,deno,BUILD-node-*}.md)
  not mentioned : --det-trace, --det-compare, --det-cassette, --det-tick, --det-tick-adapt, --det-disable, --det-max-events,
                  --det-cache-receipts, --det-cache-summary
go (docs/GO.md)
  not mentioned : --det-trace, --det-max-events, --skip-capture, --skip-report, --skip-commit, --fenvix-dir
  in code, absent from `fenvix-go --help`: --det-adapt, --det-max-events, --det-keep-parallel
jvm (docs/JVM.md): all six CLI options mentioned (line 18-19); subcommands merge, paths and verify --json not mentioned
documented, not in code: --det-backend=syscall (docs/ARCHITECTURE.md:46)
```

Environment variables read by the code (`grep -rhoE` over the sources):

```
python : DETPY_BLOCKED_PLUGINS DETPY_CACHE_DISTS DETPY_CACHE_LINES DETPY_CACHE_SHARED DETPY_PLAN_CHUNK_DIV DETPY_PRECOMPILE_S
         DETPY_PYC_CACHE DETPY_REEXEC DETPY_REWRITE_CACHE DETPY_REWRITE_OWN DETPY_VERBOSE DETPY_XDIST_ENV
         FENVIX_CACHE_ALLOW_HTTP FENVIX_CACHE_LOCAL FENVIX_CACHE_REPORT FENVIX_CACHE_TOKEN FENVIX_CACHE_TOKEN_FD
         FENVIX_CACHE_TOKEN_FILE FENVIX_RUNTIME_ISA FENVIX_RUNTIME_MEMO
node   : DETJS (=1) DETJS_CACHE_DIR DETJS_CACHE_DEBUG DETJS_CACHE_SKIP_DIRS DETJS_CACHE_IDENTITY DETJS_JEST_RUNNER ... (60+ DETJS_*
         names, most of them internal hand-off between detjs processes) + the FENVIX_CACHE_* and FENVIX_RUNTIME_* names
go     : FENVIX_GO_CACHE FENVIX_GO_SESSION
jvm    : system properties fenvix.adapt fenvix.allow.hosts fenvix.cache fenvix.config fenvix.disable fenvix.epoch.ms
         fenvix.meta.jdkhooks fenvix.module fenvix.native fenvix.out fenvix.plugins fenvix.root fenvix.seed fenvix.tick.ns
         fenvix.timer.budget fenvix.tool
```

### E10. Level 1, GitHub Action, MCP server (Engine docs / docs/RELEASE-1.md; Docs missing / GitHub Action usage, MCP server)

Gap ids: DOCS-159, DOCS-210, DOCS-374, DOCS-400, DOCS-412

```
$ cd /home/user/fenvix-engine-cli
$ git grep -l -- "det-threads\|det_threads" <62 remote branches> -- 'python/detpy/*.py' | sed 's/:.*//' | sort | uniq -c
      5 origin/claude/l1-threads-fix
      5 origin/claude/review-r007b
$ git merge-base --is-ancestor origin/claude/l1-threads-fix origin/claude/release-1   => exit 1 (not merged)
$ grep -c "det-threads\|det-async" work/DOCS/help/pytest-help.txt                      => 0
$ for b in <every remote branch>; do git ls-tree -r --name-only $b | grep -iE '(^|/)action\.ya?ml$|mcp'; done
  => only harness/skip_study2/specs/github-mcp-server.json and .../github-mcp-server-copilot.json.gz (a benchmark project) on 7 branches
  (same search over every remote branch of fenvix-app: nothing)
$ grep -n 'pypi\|twine\|npm publish\|maturin publish' .github/workflows/release-1.yml   => (nothing; 7 upload-artifact steps)
```

### E11. fenvix-app facts used for the docs site entries

Gap ids: DOCS-065..071, DOCS-080, DOCS-091, DOCS-096, DOCS-098..099, DOCS-102, DOCS-106, DOCS-111, DOCS-128..130, DOCS-158..159, DOCS-162, DOCS-174, DOCS-185, DOCS-190, DOCS-330, DOCS-358, DOCS-361, DOCS-414, DOCS-416, DOCS-418, DOCS-420, DOCS-440

```
src/pages: ApiKeys Billing Connect Defects Members Overview Project ProjectSections Projects Run Settings SignIn Styleguide Usage  (no Databases)
src/pages/ApiKeys.tsx:5-6  "The public API they would call does not exist yet, so the page only says so (founder, 2026-11-18)"
github-app/src/api/orgs.ts:14-21  LIMITS = name 2..64, 50 members, 20 invitations a day, invitation 7 days, 50 organizations per user
github-app/src/api/errors.ts:29   new ApiError(503, "github_not_configured", ...)
openapi/fenvix-api.yaml:577-578   page / pageSize (max 200, default 25);  :607 Region enum [us, eu]
supabase/migrations/0014_dashboard_api.sql:155-159  starter 129, team 479, scale 1350, monorepo 4200 (USD a month), nightly-exploration = addon
docs/GITHUB-APP.md:83-89  App permissions: Actions read; Administration, Checks, Contents, Pull requests, Workflows read and write
src/data/ci.ts:368-382    bundleDir = .fenvix/defects/<id>; pullCommand = `fenvix defects pull <id>`
```
