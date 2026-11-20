# LAND: notes for the landing page audit

Audited: `/home/user/fenvix-landing` (main, commit f4d16e3), every served page (`/`, `/product/flaky-tests/`,
`/product/skip-with-proof/`, `/product/integrations/`, `/use-cases/`, `/developers/`, `/pricing/`, `/security/`,
`/estimate/`, `404.html`), `content/*.md` (feeds `/llms.txt`, `/llms-full.txt`), `pages/`, `scripts/`, `explore/`,
`screenshots/`, `img/`, `assets/`, `README.md`, `docs-notes.md`, `package.json`, `vercel.json`.
Compared with: engine `claude/release-1` (`/home/user/audit/engine`), service `fenvix-app` main, docs `fenvix-docs`
main, brain `fenvix-brain-cli` main. Gaps: `LAND.gaps.jsonl`, 126 entries (19 BLOCKS-USE, 56 DEGRADES, 51 MINOR;
95 BUILD-MVP, 25 BUILD-LATER, 6 DECIDE; 27 RAN, 94 READ, 5 DOC). Scratch: `/home/user/audit/work/LAND/`.

## (a) Could not check

| What | Why |
|---|---|
| The live sites: `www.fenvix.dev`, `docs.fenvix.dev`, `console.fenvix.dev`, `github.fenvix.dev/healthz`, any `/privacy`, `/terms`, `status.` host | The session proxy answers `403 Forbidden (agent proxy: no rule or network setting allows this host)` for every fenvix.dev host. Link targets were judged from the repositories (`fenvix-docs` content, `fenvix-app` routes) and from the brain's log. LAND-010 and LAND-011 are therefore `DOC`. If the deployed docs site differs from `fenvix-docs` main, LAND-001 to LAND-009 change. |
| Whether the deployed landing equals this repository's main | Same reason. The repository is a shallow clone with one commit. |
| Whether `detpy`, `detjs` or `fenvix` exist on PyPI / npm (or are taken by someone else) | Not queried: it would send the project's codenames to an outside registry, and the landing gives no install command to verify anyway (LAND-032). Worth a check by the founder before any `pip install detpy` is printed: a third-party package of that name would be installed instead. |
| Vercel behaviour: the 404 page, `trailingSlash`, the redirects in `vercel.json` | Served locally with `python3 -m http.server`, which does not read `vercel.json`. `/does-not-exist/` gave the server's own 404, not `404.html`. The redirect table was read, not exercised. |
| "Machines follow your runs" (autoscaling), LAND-047 | No fleet is running; judged from LOG.md (`customer-mode-pnap NOT merged`). |
| Whether the dashboard sign-in (GitHub, Google, email link) works in production | Code exists (`src/pages/SignIn.tsx`, `src/session/supabase.ts`); the console is not deployed. |
| GitHub's current list price | Not fetched. LAND-063 relies on the price recorded on 2026-11-18 in `sessions/2026-11-18-pricing-v2/REPORT.md:28` (DECLARED, docs.github.com) and COMPETITORS.md. |
| Fonts: whether Google Fonts requests succeed in production | The requests are made (seen in the browser run); what Google logs is outside reach. |
| Accessibility beyond tap-target size (contrast, screen reader order, keyboard traps in the animated mocks) | Not run: no axe in the scratch setup and no `playwright install` allowed. The home page has 6 `<a>` elements without `href` inside the dashboard mock (crawl output). |

## (b) Evidence appendix (commands and trimmed real outputs, by gap id)

### Build and serve (LAND-016 to LAND-018, LAND-101 to LAND-111, LAND-115, LAND-119, LAND-121 to LAND-123)

```
$ cp -r /home/user/fenvix-landing work/LAND/site; cd work/LAND/site; npm ci; npm run build
> node scripts/build.mjs
Built 7 docs pages into dist/                      # exit 0
$ find dist -type f | sort                        # 24 files
dist/404.html  dist/_redirects  dist/apple-touch-icon.png  dist/developers/index.html  dist/estimate/index.html
dist/favicon-32.png  dist/favicon.ico  dist/favicon.svg  dist/img/why-1.webp ... why-4.webp  dist/index.html
dist/llms-full.txt  dist/llms.txt  dist/pricing/index.html  dist/product/{flaky-tests,integrations,skip-with-proof}/index.html
dist/security/index.html  dist/site/{lenis.js,site.css,site.js}  dist/use-cases/index.html
# no docs/, no search-index.json, no robots.txt, no sitemap.xml, no security.txt, no privacy/terms/contact/status page
$ cat dist/_redirects
/docs https://docs.fenvix.dev/ 301 ... /estimate/ /pricing/#estimate 302 ...
$ SITE_URL=https://fenvix.example node scripts/build.mjs; head dist/llms.txt
- [Introduction](https://fenvix.examplehttps://docs.fenvix.dev/): What FENVIX is ...          # LAND-017
$ grep -n '/docs/' dist/llms-full.txt
32: ... see the [FAQ](https://fenvix.example/docs/faq/#how-much-does-skip-with-proof-save).   # LAND-018
$ npm audit
markdown-it  <=14.3.2  Severity: high ... 1 high severity vulnerability                      # LAND-122
$ python3 scripts/build_pages.py (on a second copy); diff -rq site site2   => "built 9 pages", no differences   # LAND-123
```

### Browser crawl (Playwright, Chromium, 1440x900 and 390x844; `work/LAND/crawl.cjs`, results `work/LAND/crawl/report.json`)

| page | status | description | og/twitter | canonical | console errors | page errors | sideways scroll (390 px) | forms |
|---|---|---|---|---|---|---|---|---|
| `/` | 200 | yes | none | none | 0 | 0 | no | none |
| `/product/flaky-tests/` | 200 | yes | none | none | 0 | 0 | no | none |
| `/product/skip-with-proof/` | 200 | yes | none | none | 0 | 0 | no | none |
| `/product/integrations/` | 200 | yes | none | none | 0 | 0 | no | none |
| `/use-cases/` | 200 | yes | none | none | 0 | 0 | no | none |
| `/developers/` | 200 | yes | none | none | 0 | 0 | no | none |
| `/pricing/` | 200 | yes | none | none | 0 | 0 | no | `#es-form` (no action, `onsubmit="return false"`), `#es-go` (no action) |
| `/security/` | 200 | yes | none | none | 0 | 0 | no | none |
| `/estimate/` | 200, meta refresh to `/pricing/#estimate` | - | none | `/pricing/#estimate` | 0 | 0 | no | (pricing) |
| `/404.html` | 200 | no (noindex) | none | none | 0 | 0 | no | none |

No failed sub-resource, no 4xx/5xx resource, no broken internal link and no broken same-page anchor on any page
(`#contact` exists on the home page: LAND-012 is about what it contains). All `lang="en"`, one `h1` each.
Screenshots: `work/LAND/crawl/*.png`.

```
$ node shot.cjs      # 390x844, reduced motion                                             LAND-104, 112, 113, 114
home external requests: [ 'https://fonts.googleapis.com/css2?family=Schibsted+Grotesk...', 'https://fonts.gstatic.com/s/schibstedgrotesk/v7/...woff2', 'https://fonts.gstatic.com/s/jetbrainsmono/v24/...woff2' ]
 small tap targets(<24px high): 10
dev  ... small tap targets(<24px high): 8
sec  clipped: [ 'LI.: test_dates.py::test_parse [188>152]', 'LI.: test_api.py::test_rate_limit [208>152]', ... 15 items ]
     small tap targets(<24px high): 8
```

### LAND-012, LAND-014, LAND-064, LAND-065 (`work/LAND/form.cjs`)

```
default: es-o1=Team | es-o2=75% | es-o3=18,000 | es-o4=$144 | es-pl=Team · 2,000 runs, 5 projects | es-gh=$144 / month
selects: [ 'es-wh:GitHub-hosted runners/Self-hosted runners/Another runner provider/Another CI system', 'es-fw:pytest/Vitest/Jest/Something else' ]
after choosing the last option of both selects: es-o1=Team | es-o2=75% | es-o3=18,000 | es-o4=$144 | ... | es-gh=$144 / month
170-minute job: es-o1=Team | es-o2=75% | es-o3=255,000 | es-o4=$2,040 | es-pl=Team · 2,000 runs, 5 projects | es-gh=$2,040 / month
message after submit: Sending is not switched on yet. Your numbers stay on this page. | non-GET requests: []
#contact section text: Stop rerunning flaky tests. / Change one line in your test job, runs-on: fenvix, and every flaky test becomes a defect you can replay. / Read the docs / Get started
mailto/tel links on home: 0
```

Estimate formula (`pricing/index.html:692-711`): `GH = 0.008`; `PLANS = [['Starter',500,1],['Team',2000,5],['Scale',10000,25]]`;
plan = first with `runs <= r && projects <= n`, else Enterprise; `minutes = runs * minutes_per_job`; `cost = minutes * GH`.
The two selects and the agent-share slider do not enter any result (the slider only splits a bar). No constant is
measured: `GH` is a DECLARED GitHub price that is out of date ($0.006 on 2026-11-18), the plan limits are the superseded
ones.

### LAND-001 to LAND-009 (docs targets)

```
$ head -8 /home/user/fenvix-docs/content/index.md
FENVIX is a database service where every customer, agent or test gets its own database. A database is a set of files on object storage. ...
$ grep -n '^## ' content/concepts.md content/commands.md
concepts.md: Databases that sleep / Wake / Sleep / Durability / One owner per database / Protocols
commands.md: Fork / Restore one customer / Export and erase / Usage per customer / Keep awake
$ grep -o 'href="[^"]*"' <8 served pages> | sort | uniq -c      (external targets)
 50 https://console.fenvix.dev   30 https://docs.fenvix.dev/   11 https://www.fenvix.dev/#contact
  5 .../quickstart/  4 .../security/  3 .../commands/  2 .../concepts/  2 .../compatibility/  1 .../faq/
  15 anchored docs links (#fingerprint x2, #deterministic-run, #seed-and-order, #polluter-and-state-setter, #defect,
     #skip-receipt, #flags, #replay, #api-keys, #read-runs-and-defects x2, #pull-a-bundle, #api-for-coding-agents, #measured-results)
  2 https://www.fenvix.dev/llms-full.txt  1 https://www.fenvix.dev/llms.txt
```

### LAND-019 to LAND-023, LAND-030 (hosted runner)

```
$ sed -n 1,18p runner/fenvix-run            (engine@claude/release-1)
"""fenvix-run: run a project's pytest suite inside the fenvix engine ... fenvix-run --project . --python .venv/bin/python
$ sed -n 303,312p runner/fenvix-run         # each failed test rerun once alone; passes => "flaky"
$ sed -n 338,339p runner/fenvix-run
"failed": real, "flaky": [{"nodeid": n, "replay": f"{replay_full}  # whole suite, same order: fails again",
                           "minimise": f"detpy repro {shlex.quote(n)} --seed fixed"} for n in flaky],
$ cat infra/github-app/lib/runner/files/fenvix-job-started     (fenvix-app@main)
mkdir -p "$HOME/.fenvix" 2>/dev/null && touch "$HOME/.fenvix/job-started" 2>/dev/null ; exit 0
$ grep -n 'v1/runner' infra/github-app/lib/runner/files/*
fenvix-summary-poster:2: ... (POST /v1/runner/summaries)   fenvix-warmup-done / -prepare / -report: POST /v1/runner/warmups
# nothing posts /v1/runner/results, /progress, /explorations
$ for b in $(git branch -r); do git grep -c "runner/results\|runner/summaries" $b -- runner/fenvix-run; done   => no branch
$ sed -n 105,107p sessions/2026-11-18-github-app/REPORT.md     (brain)
* **How the engine gets into a customer's unchanged test step** on a fenvix machine (the onboarding PR changes only
  `runs-on`, as asked; the customer's step still says `pytest`): the runner machine must inject `--det --det-cache`
  (e.g. `PYTEST_ADDOPTS` from a runner job-started hook). Runner fleet work, Block 4 part 2.
$ grep -rn PYTEST_ADDOPTS engine/runner engine/release fenvix-app/infra fenvix-app/github-app/src   => nothing
```

### LAND-027 to LAND-032 (API, bundle download, MCP, install)

```
$ sed -n 5,15p src/pages/ApiKeys.tsx
 * API keys for scripts and coding agents. The public API they would call does not exist yet, so the page only says ...
 <p className="muted">API keys arrive with the public fenvix API. Until then, everything is here in the dashboard ...
$ grep -rliw mcp python node/src node/bin crates/*/src release runner (engine); src github-app/src infra openapi (app)   => no file
$ release/fenvix --help   (docstring, lines 6-14): python, python-runner, node, go, jvm run, jvm decide, verify, detect, version   # no "defects"
$ grep -n private node/package.json   => "private": true
```

### LAND-035 to LAND-037 (GitHub App)

```
docs/GITHUB-APP.md:83-89  Actions Read-only | Administration Read and write | Checks Read and write | Contents Read and write |
                          Metadata Read-only | Pull requests Read and write | Workflows Read and write
github-app/src/onboarding/onboard.ts:130  POST  .../git/refs   {ref: refs/heads/<branch>}
                                     133  PATCH .../git/refs/heads/<branch>  {sha, force: true}
                                     135  PUT   .../contents/<workflow file>  {branch}
docs/GITHUB-APP.md:187,189  WARMUP_ENABLED true ; WARMUP_DAILY_CAP 6
```

### LAND-052, LAND-055, LAND-057 (skip study, fenvix-engine-cli `origin/claude/loving-maxwell-58mv2w:harness/skip_study2/REPORT.md`)

```
30:  | 1. home-assistant (pytest, 50 commits, 12% sample) | closure | 98% / 85% | 0 (2573) | 97% / 82% | 0 (2488) | MEASURED |
43:  * **The v2 "0 wrong" was a sample result, not a proof.** The reviewer found: 1 real wrong hit outside the sample ...
48:  Under v3, setting 1 has 0 wrong and 0 flaky in 4 464 verified `closure` skips (829 + 2488 + 314 + 442 + 391, MEASURED).
201: * At every commit a random sample of the `closure` skips runs anyway. The sample is Bernoulli 8-15% per spec ...
222: Skip shares are MEASURED on the stated sample. Time to green is ESTIMATED.
228: | home-assistant | pytest | 50 | 776 (12%) | closure | 98% / 85% | ... | 417s -> 35s (16s) / 417s -> 142s (67s) | ...
```

### Absence checks on the rendered text of the 8 served pages (LAND-041 to LAND-043, 067, 078, 087, 090, 098)

```
overhead|slower|slowdown => 0     trial|shadow => 0     parallel|xdist => 0     playwright|browser|cypress|e2e => 0
culprit => 0     security page: region => 0, EU|europe => 0, GDPR => 0, encrypt|TLS => 0, sub-processor|AWS|supabase => 0
```

## (c) Every numeric claim on the site, and its source

Labels as in the brain: MEASURED / ESTIMATED / DECLARED. "Illustration" = invented example data inside an animated mock.

| Claim (where) | Source | Verdict |
|---|---|---|
| 358 of 388 flaky tests reproduced, 92.3% (home 765, 893; flaky tests 328, 368; integrations 360; developers 413; use cases 751; content) | NUMBERS.md "Mixed round 25+25" (MEASURED, reviewer PASS) | Supported |
| 49 open-source Python repositories, about 120,000 tests, IDoFT, November 2026 (same places) | same entry | Supported |
| "Every reproduced failure replays 10 of 10 with an identical execution fingerprint" tied to the 358 (home 893; integrations 360; developers 418) | The 358 were counted as 10/10 failures only. One-fingerprint counts: 361 and 364, 16 replay-unstable (block2 REPORT-2:57,89,102) | UNSUPPORTED as worded (LAND-059) |
| "Usually 2 tests remain" (flaky tests 288) | block2: median 2, max 4 (ROADMAP Block 2, MEASURED) | Supported |
| home-assistant 97% of test time skipped, median of 50 commits (home 788; skip 286, 371; use cases 579, 749; content) | NUMBERS.md "Skip-with-proof study 2 v3.1": 97% median / 82% mean, 12% sample of test files, study harness | Number exists; presented as the product on the suite: OUTDATED / partial (LAND-055) |
| docusaurus 98% (same places; use cases 612, 615) | same study: 98% / 81%, unit step only | Number exists; context missing (LAND-056) |
| vue-core 25% (same places) | same study: 25% / 31% | Supported (study) |
| "Django apps and small libraries: little to nothing" | same study: saleor about 0%, small libraries median 0% | Supported |
| 0 wrong skips in 4,464 (home 893; skip 311, 316, 370; use cases 750; content) | same study: 0 of 4,464 verified skips, random sample | Count supported; "we re-ran every skipped test" FALSE (LAND-052) |
| Time to green: median 417 s before, about 35 s with skip (home 694, 789; skip 264, 354-363; use cases 581), labelled ESTIMATED | skip_study2 REPORT:228 (12% sample; mean 417 s -> 142 s) | Traced, but contradicted by the MEASURED floor 0.25-0.45x (NUMBERS.md): UNSUPPORTED (LAND-057) |
| "about 59% of Python flaky tests are order-dependent (Gruber et al., ICST 2021)" (flaky tests 361; content/faq) | NUMBERS.md "59% confirmed: Gruber et al." (DECLARED) | Supported |
| "1 in 11 commits at GitHub had a red build from a flaky test (github.blog, 2020)" (flaky tests 361) | NUMBERS.md "Cost of flaky tests ... verify before publishing" (DECLARED, unverified) | UNVERIFIED (LAND-061) |
| "about half of agent pull request pushes could be skipped" (use cases 651) | NUMBERS.md "Coding-agent PR pushes (v2 capture, partial): about 50%" of test time | Unit changed, partial (LAND-062) |
| $0.008 a minute, GitHub Linux 2-core (pricing 476, 479, 515) | pricing-v2 REPORT:28 says $0.006 (DECLARED 2026-11-18) | OUTDATED (LAND-063) |
| Starter up to 500 runs / 1 project; Team 2,000 / 5; Scale 10,000 / 25; Enterprise (pricing 343-355, 513; home 893; content/faq) | DECISIONS 2026-11-18 table A: 2,500 / 10,000 / 30,000 / 100,000 run units, $129 / $479 / $1,350 / $4,200, Monorepo | CONTRADICTED (LAND-071 to LAND-077) |
| "$144" and "18,000 minutes" in the estimate (pricing 471-476) | runs x minutes x $0.008, from the form's default inputs | Formula, wrong constant |
| "10 of 10" as the definition of reproduced | `detpy repro --confirm` default 10 (python/detpy/cli.py:35) | Supported (Python) |
| "5 items, 2 done today" (security 390) | the page's own table | Self-description |
| "Seven short pages" of docs (developers 539) | landing `content/` has 7 files; the docs site has other pages | Not true of the linked site (LAND-001) |
| Home hero mock: run #4821, 57 of 1,912 tests, 97%, 35 s, 3 open defects, D-17, seed 3, "0 of 10 failed" counter | none | Illustration, NOT labelled (LAND-044) |
| Flaky tests page: 1,204 tests -> 2 tests, 14 defects in families 6/4/3/1, 4 defects found at night, D-0412, D-0419, seed 7 | none | Illustration (labelled "Illustration" at line 309 for one figure only) |
| Skip page: 24 files, 14 functions, 2 files, PR #2291 | none | Illustration (labelled) |
| Pricing mocks: 2,000 runs plan, 9 / 78 / 1,140 / 1,690 runs, "2x a usual day", 80% | none | Illustration (labelled "example numbers") |
| Use cases mocks: 4,812 tests, run r-3307, "same score, 7 of 7 runs", "seeds 1 to 100, nightly", seed 41 | none | Illustration, not labelled |
| Developers mocks: fingerprint 9c41e0, "23 runs, 3 with a failure", d-0412 "seed 3, 3 tests", d-0107 seed 5 | none | Illustration ("sample data" label only on the integrations terminal) |
| Security mock: jobs #4812 / #4813, 412 and 286 tests, "runs diverge at step 214" | none | Illustration |

Numbers the brain has MEASURED and the site does not use: Node 70.1% reproduced (239/341); 0 wrong in 738,552 verified
reuses for Vitest and Jest; 0 wrong in 455,510 (home-assistant, engine); cause named in 98.9% of reproductions; exact
culprit 92.1%; dependency verdict 36.0%; threads 0 broken on 26 suites; head-to-head 0 wrong against 375 wrong skips of a
coverage rule. Numbers the brain has MEASURED and the site hides: slowdown +16.8% to +25.0%, cold run 1.03x to 1.34x,
10 and 44 tests broken by `--det`.

## (d) For the lead

1. **The docs domain is the largest single problem.** 62 links on the served pages go to `docs.fenvix.dev`, and the docs
   repository on main still documents the earlier database product (MongoDB protocol, sleeping databases, an API for
   databases). The landing's own `content/*.md` holds seven short pages about the CI product, but `scripts/build.mjs`
   no longer publishes them (only `llms.txt` and `llms-full.txt` are generated from them). So the CI docs exist nowhere
   a visitor can open. Either the docs repository is replaced or the landing publishes `content/` again.
2. **Three generations live in the landing repository.** (a) the earlier product "olvix"/database: `explore/`, four
   generators, `screenshots/`, `img/`, `scripts/logos.json`, `package.json` name; (b) the 2026-11-17 CI product: the
   served pages (pytest full, Vitest/Jest seeded, plans by run count with projects, exploration included);
   (c) today's product: four languages on release-1, run-unit plans with prices, exploration as a paid add-on, a
   30-day shadow trial. The served site is generation (b). `README.md` mixes (a) and (b) and still tells the reader to
   run a generator that would overwrite the home page with (a) (LAND-118).
3. **Contradictions between sources, found while checking:**
   - The dashboard (`fenvix-app` main) already follows pricing table A (prices in migration 0014, "Nightly exploration
     is a paid add-on", shadow trial); the landing does not. The dashboard code comment says its sections follow "the
     landing's dashboard (founder, 2026-11-17)": the two were aligned once and drifted within three days.
   - `RULES.md:64` forbids "Pricing pages, landing pages or billing now"; all three exist (LAND-125).
   - `PRODUCT.md` "How it is delivered" still says a GitHub Action on any runner and "We do not sell runners";
     DECISIONS 2026-11-17 replaced it; the audit brief's promise says "on any CI and any runner"; the landing sells
     only `runs-on: fenvix` (LAND-093, class DECIDE).
   - The dashboard stores `$0.008` per GitHub minute "to verify" (`sessions/2026-11-17-dashboard/REPORT.md`); the
     pricing study read `$0.006` the next day. The landing and the dashboard both still carry `$0.008`.
   - The security page calls one-job-per-machine "in progress" while `fenvix-app` has just-in-time per-job machines in
     code; at the same time it states "each job gets a fresh machine" as fact. The page is both behind the code and
     ahead of what is deployed.
4. **Claims found false (not merely unsupported):** "It never pushes to a branch" (LAND-036); "We re-ran every skipped
   test to check" (LAND-052); "$0.008 ... as listed by GitHub" (LAND-063); "built from the same source as the docs"
   (LAND-016); "A long job and a short job are one run each" against the decided pricing (LAND-072); "Your code runs on
   our machines only for the test job" against warm-up runs (LAND-037).
5. **What the site gets right.** It is careful about TypeScript ("seeded runs today, order minimisation not yet":
   true, detjs has no repro, explore, replay or `--det-order`), about SOC 2 ("not yet"), about what skip saves
   ("checkout, install and build still run"), and it labels the 417 s -> 35 s figure ESTIMATED. There are no customer
   logos, no testimonials and no comparison table, so nothing invented in that category. The site builds
   (`npm ci && npm run build`, exit 0), serves with no console error, no missing resource, no broken internal link and
   no sideways scroll at 390 px. The commands printed on the pages that can be checked exist in the engine:
   `pytest --det --det-seed=N --det-order=FILE` (python/detpy/_level0.py:42), `detpy replay <bundle>`
   (python/detpy/cli.py:54), `detjs vitest run --det --det-seed=N`, `detjs jest --det` (node/bin/detjs.js:4-5).
6. **Where the forms send data:** nowhere. The site has two forms, both on `/pricing/`: the estimate inputs (computed
   in the browser) and the email form (endpoint empty, nothing is sent, LAND-014). There is no analytics script, no
   cookie and no tracker; the only third-party requests are Google Fonts.
7. **Entries that overlap other agents' areas** (listed here because the landing promises them; the owning agent has
   the deeper evidence): the engine not reaching an unchanged test step (LAND-019), the hosted flaky flow (LAND-020),
   results and bundles never posted by the runner (LAND-030), no nightly exploration launcher (LAND-023), no public
   API or API keys (LAND-027, LAND-028), no MCP server (LAND-031), no GitHub Action (LAND-093).
