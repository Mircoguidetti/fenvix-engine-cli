# APP3 notes: dashboard front-end (fenvix-app, React/Vite)

Agent APP3, 2026-11-20. Stopped early on the coordinator's budget message: sections D ("Not covered") and A ("Could
not check") say exactly what is left. Gaps: `APP3.gaps.jsonl` (102 entries). Scratch: `/home/user/audit/work/APP3/`.

**Audited revision.** `fenvix-app` `main` was `ce69a6b` when the audit started and was fast-forwarded to `c59d913`
(merge of `claude/dashboard-vercel`, PR #19) while it ran. `git diff ce69a6b c59d913 --stat` touches no file under
`src/`: every `src/` finding holds for both. `vercel.json`, `package.json`, `tests/unit/vercel.test.ts`,
`docs/DEPLOY-VERCEL.md` and `deploy.yml` were read at `c59d913`. The scratch copy that was built and run is `ce69a6b`.

## Route table

Data source: every screen reads through `src/data/client.ts`. In a normal build that is the real API
(`src/data/api.ts`, openapi-fetch on `VITE_API_URL`); only a build with `VITE_DATA_BACKEND=mock` serves the sample data
(`src/data/mock.ts`, `orgs-mock.ts`). So "real" below means: real API in production, mock only under that flag. No
screen mixes hard-coded numbers into API data, except the constants named in the notes column.

Empty state: RAN = seen with stubbed empty API answers (scenarios `empty`, `projempty`, `noorg`, `unnamed`).
Error state: RAN = seen with the API refused / 401 / 403 / 500 / offline (section B-3).

| Route | Data source | Empty state (zero runs / new org) | Error state | Notes |
|---|---|---|---|---|
| (signed out, any route) | Supabase Auth only | sign-in page on every route (RAN `signedout`) | config error line when VITE_ vars are missing (RAN `noenv`) | deep link lost after sign-in (APP3-078); legal links to fenvix.com (APP3-058); hero shows fixed sample test names (decoration) |
| (gate) Name your organization | real: GET /me, PUT /organization | n/a | inline error on save | RAN `unnamed`: shown on every route for an owner with `nameConfirmed: false` |
| (gate) No organization yet | real: GET /me | this IS the empty state: dead end, only Sign out (RAN `noorg`, APP3-054) | /me failure falls through to the dashboard as "Workspace" (APP3-076) | |
| (gate) Join an organization (`/invite#token=`) | real: POST /invitations/accept | n/a | inline error | not run; no organization name shown (APP3-050); bad token silently ignored (APP3-051, RAN) |
| `/` | real: GET /projects | redirects to `/overview` (RAN) | redirects to `/overview` (RAN) | opens the last project of this browser |
| `/overview` | real: /overview, /activity, /settings | "Connect your first project" (RAN) | red line, no retry (RAN); activity card stuck on "Loading" (APP3-066, READ) | "On GitHub-hosted" is an estimate (APP3-021) |
| `/projects` | real: /projects | "No projects yet" + Connect button (RAN) | red line (RAN) | |
| `/projects/connect` | real: /github, /github/repositories, install-link, setup-pull-request | "No installation yet: install the app first" (RAN) | two red lines (RAN) | setup diff `before` is a constant (APP3-040); GitHub only (APP3-038, -039) |
| `/projects/:id` (Runs) | real: /projects/:id, /runs (paged + 30-day `since`), /defects, /activity | "No runs yet…", "Not enough green commits yet", "Nothing yet", "No runs match" (RAN `projempty`) | project fails: red line only, no heading (RAN). Data fails: "Loading the latest run", "Loading the chart", "Loading" for ever (RAN `projok`, APP3-063..065) | pagination 25/page; no PR view (APP3-024) |
| `/projects/:id/defects` | real: /defect-families, /projects | "No open defects" + explanation (RAN) | red line (RAN) | no pagination (APP3-007) |
| `/projects/:id/skip-with-proof` | real: /runs (`since`), /skip-share, /audit | zeros and "No runs in the last 30 days", "No re-runs to explain yet", "No runs yet" (RAN) | audit: red line; chart and "Why tests ran" stuck loading, KPIs show 0 (RAN, APP3-067, -068) | |
| `/projects/:id/nightly` | real: /explorations, /defects, /plans | "No nights yet" + reason (RAN) | red line (RAN) | counts only, no test names (APP3-013); no schedule/budget (APP3-011) |
| `/projects/:id/time-to-green` | real: /runs (`since`) | "Not enough green commits yet", "No green commits yet" (RAN) | NO error shown, chart stuck loading, KPIs "–"/0 (RAN, APP3-069) | |
| `/projects/:id/settings` | real: /projects/:id, PUT settings, /setup-change | n/a (form) | setup-change: red line (RAN); save: inline error | snippet invented from the language (APP3-041) |
| `/projects/:pid/runs/:rid` | real: /runs/:id (+ ETag polling), /tests, /files, /receipts/:id | "Run not found" on 404 (RAN); "No tests recorded", "No test matches" (READ) | red line only (RAN); files failure stuck on "Loading the suite" (APP3-070, READ) | tests paged 50/page; receipt deep link `?receipt=`; flash of "Run not found" (APP3-071) |
| `/defects` | real: /defect-families, /projects | "No open defects" (RAN) | red line (RAN) | |
| `/defects/:id` | real: /defects/:id | "Defect not found" on 404 (RAN) | red line only (RAN) | replay command cannot run (APP3-001); no bundle download (APP3-002) |
| `/usage` | real: /usage/months, /usage/:month, CSV | "No runs this month", zero totals (RAN) | stuck on "Loading usage" for ever, no error (RAN, APP3-062) | |
| `/billing` | real: /billing, /plans | "No plan yet", "No add-ons yet" (RAN) | red line (RAN); plans failure: empty card (APP3-047) | "Choose" is a toast only (APP3-044); Payment card is fixed text (APP3-045) |
| `/api-keys` | none: static "Coming soon" | n/a | n/a | APP3-043 |
| `/settings` | real: /settings, PUT /organization, PUT /settings | n/a | red line inside the card (RAN) | email notices stored only (APP3-048); no delete account (APP3-052) |
| `/settings/members` | real: /organization/members, /invitations | "No pending invitations." (RAN) | red lines (RAN `data*`); wrong "not set up (VITE_API_URL)" text when /me failed (RAN, APP3-075) | h1 is "Settings" (APP3-087) |
| `/styleguide` | none (static) | n/a | n/a | only in dev or with `VITE_STYLEGUIDE=1`; otherwise 404 page (RAN) |
| `/invite` (signed in, no token) | none | n/a | n/a | redirects to `/overview` (RAN) |
| `*` | none | n/a | n/a | "Page not found" + link to /projects (RAN); HTTP 200 on the host (APP3-081) |

Across all screens: loading state is a grey line "Loading …" (no skeleton); document title is always "FENVIX"
(APP3-080); no retry button anywhere (APP3-072); dates are UTC / en-US (APP3-083).

## Promise screens: exists / partial / missing

| Item | State | Gap ids |
|---|---|---|
| Defect list, grouped by cause | exists | APP3-006, -007 |
| Defect detail: seed, minimal order, cause, fingerprint, 10/10 replays | exists | |
| Diverging event | partial (index + sentence) | APP3-003, -004 |
| Replay command + copy button | partial: button works, command cannot run | APP3-001, -008, -009 |
| Dedup across PRs (occurrences) | partial (a counter) | APP3-005 |
| Replay bundle download / share | missing | APP3-002 |
| Nightly exploration results | partial | APP3-013..016 |
| Nightly schedule, budget, run now | missing | APP3-011, -012 |
| Skip-with-proof report, receipts, audit reruns | exists | APP3-017, -018, -019 |
| Shared cache statistics | missing (one line of warm/cold) | APP3-020 |
| Savings | exists, measured from runner reports; GitHub cost is an estimate | APP3-021..023 |
| Per-run view | exists | APP3-025..027 |
| Per-PR view | missing | APP3-024 |
| Multi-language | python / node / go only; pytest, vitest, jest, go test only | APP3-033..037 |
| GitHub App connect, choose repositories | exists (repositories are chosen on GitHub) | APP3-038..042 |
| Organization settings, members, invitations | exists | APP3-048..054 |
| API keys | missing ("Coming soon") | APP3-043 |
| Billing / plan / usage | usage exists; plan change and payment missing | APP3-044..047 |
| Account: sign out | exists | APP3-056 |
| Account: delete | missing | APP3-052 |
| Onboarding of a brand-new user | exists (name the organization → "Connect your first project") | APP3-060 |
| Docs / help links | point to another product's docs | APP3-057, -059 |
| Legal links | point to pages that do not exist in the landing | APP3-058 |

## Sign-in (task item 3)

- Providers: GitHub, Google (Supabase OAuth, PKCE) and a one-time email link (`signInWithOtp`, creates the user).
- Session: supabase-js, `persistSession: true`, `autoRefreshToken: true` → tokens in localStorage (APP3-088). The API
  client asks supabase-js for the session before every call and sends `Authorization: Bearer` plus
  `X-Fenvix-Workspace`. A 401 only prints a sentence (APP3-074).
- Protected routes: there is no route guard per route; `Routed` renders the sign-in page for every path while there
  is no user (RAN `signedout`: h1 "Sign in" on all 21 routes).
- Redirect after login: always the site root (APP3-078).
- Build variables (all `VITE_*` read in `src/`):
  - `VITE_API_URL`: API base; missing → config error on the sign-in page (RAN `noenv`).
  - `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`: sign-in only; missing → same config error.
  - `VITE_DATA_BACKEND=mock`: sample data AND fake sign-in (bypasses auth, but reaches no real data) (APP3-090).
  - `VITE_STYLEGUIDE=1` (or dev server): adds the `/styleguide` route.
  - Mock-only hooks: `window.__fenvixMock`, `window.__fenvixPollMs`, sessionStorage `fenvix-mock-trial`.
- localStorage keys: `fenvix-org`, `fenvix-theme`, `fenvix-last-project`, `fenvix-rail-open`, supabase's
  `sb-<ref>-auth-token`; sessionStorage `fenvix-invite`.

## DECISIONS 2026-11-18 "the dashboard talks only to our API" (task item 4)

Kept. `grep -rn "supabase\.from\|\.from(\|\.rpc(\|getSupabase()" src` → only `getSupabase().auth.*` calls
(`src/session/supabase.ts`, `src/session/redirect.ts`, `src/data/api-browser.ts:14` for the token). No `.from(` and no
`.rpc(` on a Supabase client anywhere in `src/`. Not a gap.

## dashboard-vercel (task item 6)

- Merged into `main` during the audit (`c59d913`). Changes: `vercel.json` (framework, install/build commands, SPA
  rewrite, five security headers, immutable cache for `/assets/`), `package.json` `engines.node 22.x`, a unit test for
  vercel.json, `docs/DEPLOY-VERCEL.md` (Italian, APP3-102), the AWS dashboard stack behind one switch
  (`FENVIX_DASHBOARD_ON_AWS`, off), `deploy.yml` steps 6 and 10 conditional, a CORS unit test in github-app.
- Still on AWS: the API (API Gateway + Lambda at `github.fenvix.dev`), the GitHub App service, the runners, SSM. Also
  needed: Supabase (Auth + database), Cloudflare DNS (`console` CNAME to Vercel, by hand).
- Variables in Vercel: `VITE_API_URL=https://github.fenvix.dev/v1`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`;
  `VITE_DATA_BACKEND=mock` for Preview only; never `VITE_STYLEGUIDE`.
- CORS: `github-app/src/api/config.ts:69-76` allows the origin of `DASHBOARD_URL` (`cdk.json`:
  `https://console.fenvix.dev`) plus `API_CORS_ORIGINS` (empty). So the Vercel custom domain is allowed (READ, not
  run); `*.vercel.app` addresses are not (APP3-101). Allowed request headers include `authorization`,
  `x-fenvix-workspace`, `if-none-match`; exposed: `etag`, `content-disposition`, `retry-after`.
- Gaps: APP3-089 (no CSP), APP3-099 (deploy not gated by tests), APP3-100 (Hobby plan), APP3-081, APP3-090.

## Tests (task item 7)

- Unit (`npm run test:unit`, in CI): 66 tests, all pass (RAN). Files: api, avatar, ci, listbox, no-underline, orgs,
  status-colors, warm (+ vercel at `c59d913`). No page or component test (APP3-095).
- `npm run check` (not in CI, APP3-092): builds the mock, then checks.mjs, orgs-checks.mjs, status-colors-checks.mjs,
  screenshots.mjs with axe, desktop 1440 and phone 390. RAN locally: 62 ok lines, 0 FAIL, exit 0.
- `scripts/e2e-real-api.mjs` (not in CI, APP3-093): needs Docker (local Supabase), `github-app` installed, the built
  dashboard. Not run here: the Docker daemon is not running on this machine.
- No test with a failing API (APP3-094).

## A. Could not check

- The deployed dashboard and API (`console.fenvix.dev`, `github.fenvix.dev`, `docs.fenvix.dev`, `fenvix.com/terms`):
  every request from this machine ended with HTTP code 000 (proxy). Whether fenvix.com resolves at all is unknown; the
  legal and docs findings rest on the landing and docs repositories.
- Real sign-in (GitHub, Google, email link), token refresh and sign-out against a real Supabase project.
- `scripts/e2e-real-api.mjs` and everything that needs the real API: `docker info` → "failed to connect to the docker
  API at unix:///var/run/docker.sock". So the empty and error states were produced by stubbing API answers in the
  browser with shapes written from `openapi/fenvix-api.yaml`, not by the real API.
- Whether the "Run not found" seen for two existing runs in the mock build (APP3-071) can persist or is only a flash:
  the snapshot was taken 1.8 s after load on a machine with load average 28; the re-run with a settle wait was not
  done.
- Whole-API 403, 404 and offline scenarios of `pw/visit.cjs` (`403`, `404`, `offline`) were not run; `data403` and
  `dataoffline` (organizations load, data calls fail) were.
- Vercel behaviour itself (rewrite, headers, preview environments): read from `vercel.json` and the guide only.
- CORS for the Vercel origin: read, not exercised (`github-app/tests/unit/cors-console.test.ts` not run).
- An empty skip-share series makes the area chart emit invalid SVG paths (console errors in `projempty`), but the
  real API always sends one point per day (`github-app/src/api/data.ts:152-170`), so it is not listed as a gap.

## B. Evidence appendix

### B-1 (APP3-001, -009) replay command as copied

Mock build (`VITE_DATA_BACKEND=mock`), defect page, after clicking "Copy replay command" (`results/mockwalk.json`):

```
clipboard: fenvix defects pull dfx_9a20
           pytest --det --det-seed=7 --det-order=.fenvix/defects/dfx_9a20/order.txt
Node defect page text: fenvix defects pull dfx_3b05 / detjs vitest run --det --det-seed=32 /
  "The Node engine replays the seed; it does not take an order of tests yet, so the order below is not replayed."
$ python3 /home/user/audit/engine/release/fenvix defects pull abc
fenvix: unknown command 'defects' (fenvix --help)
$ for b in $(git -C /home/user/fenvix-engine-cli branch -r); do git grep -q "defects pull" $b && echo FOUND $b; done
(no output)
```

### B-2 (APP3-044) billing

Mock build, `/billing`, click on the first enabled plan button: `{"button":"Choose Starter","statuses":["We will be in
touch about the Starter plan"]}`. `src/pages/Billing.tsx:101`: `onClick={() => toast(...)}`.

### B-3 (APP3-051, -054, -060, -062..076, -080, -087) API conditions, every route

Method: `npx vite build` with `VITE_API_URL=http://127.0.0.1:8799/v1`, `VITE_SUPABASE_URL=http://127.0.0.1:54321`, a
session written to localStorage (`sb-127-auth-token`), Playwright Chromium 1440x900, API answers stubbed with
`page.route` (`work/APP3/pw/visit.cjs`). 21 routes per scenario; results `work/APP3/results/<scenario>.json`,
screenshots `work/APP3/shots/<scenario>/`. Each page waited 2.5 s, then up to 20 s more for "Loading" lines to go.

| Scenario | Meaning | Result |
|---|---|---|
| `noenv` | build without any VITE_ variable | sign-in page with "This deployment is missing VITE_API_URL, VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY…" |
| `signedout` | no session | h1 "Sign in" on all 21 routes, 0 console errors |
| `refused` | nothing listens on the API port | red line "Could not reach fenvix…" on data screens; `/usage` loading ["Loading usage"]; `/settings/members` VITE_API_URL text |
| `401`, `data401` | every call / every data call 401 | "Your session has ended. Sign in again." on each screen, URL unchanged; `/usage` stuck |
| `500`, `data500` | 500 | "Something went wrong on fenvix's side…"; `/usage` stuck |
| `data403` | data calls 403 | "You do not have permission to do this in this organization."; `/usage` stuck |
| `dataoffline` | data calls aborted | "Could not reach fenvix…"; `/usage` stuck |
| `empty` | new organization, nothing connected | empty states as in the route table, 0 console errors on existing routes |
| `noorg` | /me with zero organizations | h1 "No organization yet" on every route |
| `unnamed` | owner, `nameConfirmed: false` | h1 "Name your organization" on every route |
| `projok` | project loads, every other call 500 | `/projects/p_demo`: loading ["Loading the latest run","Loading the chart","Loading"]; skip-with-proof: ["Loading the chart","Loading"]; time-to-green: alerts [], ["Loading the chart"] |
| `projempty` | project with zero runs | empty states as in the route table |

Titles: `"t":"FENVIX"` on every line of every scenario (APP3-080).

### B-4 build, tests (APP3-091, -092, -095, -096, -097)

```
npm ci                => added 120 packages, found 0 vulnerabilities
npm run build         => api check ok, tsc ok, vite: index-*.js 449.12 kB (gzip 133.86), supabaseClient-*.js 225.05 kB
                         (gzip 59.25), index-*.css 107.80 kB, mock-*.js 43.92 kB, orgs-mock-*.js 7.37 kB; dist 1.1 MB
npm run test:unit     => tests 66, pass 66, fail 0
npm run typecheck     => passes
ls .eslintrc* eslint.config.*  => none
npm run check         => 62 ok, 0 FAIL, "screenshots: all checks passed, 140 pictures", EXIT 0
```

### B-5 mock walk (partial)

`pw/mockwalk.cjs`, mock build, 23 routes, desktop 1440 light and phone 390 dark, axe (wcag2a, wcag2aa): horizontal
overflow 0 px on every route in both; 0 console errors; 0 images without alt; axe: 0 violations except one contrast
finding on `/styleguide`. Caveat: taken under load, 10 of 23 desktop pages and 12 of 23 phone pages were still on
their "Loading" line at the snapshot, so axe and overflow were measured on the loading state there (see D). External
links found: `https://docs.fenvix.dev/` and GitHub pull request URLs of the sample data. First Tab stop: "Skip to
content".

## C. For the lead

- `main` of fenvix-app moved during the audit (see top). The brief's "dashboard-vercel is 2 commits ahead" is no
  longer true: it is merged.
- The dashboard's product model is "`runs-on: fenvix` on GitHub Actions". Nothing in it speaks of the GitHub Action on
  any runner, the free CLI, or the MCP server; API keys are "Coming soon". This is the largest distance from the
  promise in this area (APP3-038, -039, -043).
- The page text of API keys says "the replay command of each defect works from your terminal". It does not
  (APP3-001).
- Comments that are stale: `src/session/redirect.ts:15` ("replaced with /overview"), `src/main.tsx:18` ("the hash
  router"); `src/data/ci.ts:2` and `ci-rows.ts` speak of Supabase rows inside the front-end tree (they are shared with
  the API through `github-app/src/api/shared.js`).
- Left-overs of the older database product in `src/components/charts.tsx` (AwakeAreaChart, WakeTimeline, "Requests per
  day split by tag") and `src/styles.css` (`textarea.editor`, `.doc-head`).

## D. Not covered (for the session that finishes this)

Read only in part (skimmed or truncated output, not line by line):
- `src/styles.css` (1,789 lines: only the media-query and theme lines were grepped), `src/data/mock.ts` (first 60
  lines and the outline), `src/data/orgs-mock.ts`, `src/api/schema.d.ts` (generated; the YAML was read in parts).
- Components `Select`, `ConfirmDialog`, `Segmented`, `Switch`, `Toast`, `SearchInput`, `Logo`, `marks`, `PairHero`,
  `HeroVisual`, `charts` (outline and labels only), and `src/pages/Styleguide.tsx` (first 60 lines).
- `scripts/screenshots.mjs`, `ui-shots.mjs`, `status-colors-checks.mjs`, `orgs-checks.mjs`, `api-check.mjs`,
  `lib.mjs` (first 60 lines), `checks.mjs` (grepped only); `tests/unit/*` (run, not read, except vercel.test.ts).
- `docs/data-contract.md`, `docs/status-colors.md`, `docs/screenshots-real-api/RESULTS.md`: not read.
- `.github/workflows/deploy.yml`: only its diff for the Vercel change.

Not done from task item 1:
- Mobile / responsive and dark theme by eye, screen by screen: only the automated numbers in B-5; the screenshots in
  `shots/mock-desktop-light` and `shots/mock-phone-dark` were not reviewed, and many show the loading state. Re-run
  `node pw/mockwalk.cjs` (it now waits for loading to end) with the preview of `dist-mock` on port 4303.
- Accessibility beyond axe and the first Tab stop: keyboard walk through the selects, dialogs, drawer, account menu,
  receipt dialog; focus return; contrast in dark; screen-reader names of the charts (one wrong label found, APP3-085).
- Pagination and large data, run (only read): runs table, tests list of a run with thousands of tests, defects.
- Back button and refresh on each deep link, run in a browser (read only: APP3-082). SPA fallback on Vercel and on
  CloudFront (the CloudFront function in `infra/github-app/lib/dashboard.ts` was not read).
- Run page in API mode with data: live polling (ETag/304), shadow run, failed run, receipt dialog: not exercised with
  stubs (only "Run not found" and error lines were).
- Connect page returns from GitHub (`?github=confirm#completion=`, `connected`, `requested`, `error&reason=`): read,
  not run.
- Member (read-only) role screens and the invitation accept flow: read, not run.

Not done from task item 2:
- Savings numbers traced end to end to the runner's reports (who measures `testTimeMs.skipped`, `minutesSaved`,
  `otherStepMinutes`): only the front-end arithmetic (`src/data/ci.ts`) was read.
- Shadow trial screens and the 35% gate: read, not judged against the promise.
- Region (US / EU) setting: whether EU machines exist was not checked.

Not done from task item 5:
- Visiting every route in the mock build with a settled page (see above), reviewing its screenshots, and the
  `403` / `404` / `offline` whole-API scenarios.
- Broken internal links (every `Link` target against the route table): not checked systematically.

Not done from task item 6: running the CORS unit test; reading `deploy/cli.mjs` and the CDK switch.
