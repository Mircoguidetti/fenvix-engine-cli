# PROC4 notes: process gaps on the service side (paper trail against code)

Agent `PROC4`. Scope: GitHub App, dashboard, API, deploy, customer machines, pricing. Gaps: `PROC4.gaps.jsonl`
(174 entries; extra fields `prompt` and `block`; `area` starts with `Process / `). Generator scripts and scratch:
`/home/user/audit/work/PROC4/` (`gen1.py`, `gen2.py`, `gen3.py`).

Repositories and commits the evidence refers to:

- `app@main`: `/home/user/fenvix-app`, branch `main`. **It moved during the audit**: `ce69a6b` (2026-11-19) until
  08:34 UTC, then fast-forwarded to `c59d913` ("Merge pull request #19 ... dashboard-vercel"). Every cited file and
  line was re-checked on `c59d913`.
- `engine@release-1`: `/home/user/audit/engine` at `529c1609`; other engine branches through
  `git -C /home/user/fenvix-engine-cli`.
- `brain`: `/home/user/fenvix-brain-cli` main at `1a955a7`.
- `landing@main`: `/home/user/fenvix-landing` at `f4d16e3` (2026-11-17).

## (a) Could not check

1. **Anything live.** The proxy refuses the product's own hosts (`curl https://github.fenvix.dev/healthz`,
   `https://console.fenvix.dev/` => `CONNECT tunnel failed, response 403`). Whether the API still answers, whether a
   Deploy run followed the merge of PR #19, whether a runner image (AMI) exists, and whether Vercel serves
   `console.fenvix.dev` are UNKNOWN to me. Entries PROC4-046, 060, 061, 141 and 153 rest on NOW.md, LOG.md and the
   session reports (`how: DOC`), plus the local git state.
2. **GitHub Actions run results of fenvix-app** (deploy runs after `44572670343`). No access; the LOG is the source.
3. **Real GitHub behaviour of the App** (permission needed by `GET /user/memberships/orgs/{org}`, PROC4-034; the
   `?github=requested` path when an organization owner approves a member's install request and the redirect carries
   no fenvix state; an installation made from GitHub's own page and linked later). The App does not exist; only the
   fake GitHub was ever used. Suspected gap, not proven: an install approved by an owner may never be linkable
   without starting again from the dashboard.
4. **Supabase project settings**: which sign-in providers (GitHub, Google, magic link) are configured, the Site URL
   and redirect URLs, whether anonymous sign-ins are off (PROC4-032), the project's region (PROC4-087 only states
   what the code shows: one database, control plane in eu-west-1).
5. **Vercel project** `fenvix/fenvix-app`: its environment variables, domain, plan. Report P-035 itself says UNKNOWN.
6. **phoenixNAP, Firecracker, KVM**: nothing can run here (no account, no `/dev/kvm`); all customer-machine entries
   on the unmerged branch are `DOC` from the reports and reviews of that branch. I did not re-run that branch's
   suites.
7. **Compatibility of release-1's `summary.json` with the App's parser** (PROC4-172): I read both sides but did not
   build and run `runner/fenvix-run` from release-1 against `github-app/src/results/summary.ts`. A mismatch is
   suspected, not proven; what is proven is that the fixtures come from commit `03a8613` of the prototype branch.
8. **Whether a database dump was taken before migration 0014** (PROC4-029) and whether the founder compared the AWS
   price pages (R-012 request): no record either way.
9. **fenvix-app test suites**: not re-run (they need Docker, a local Supabase and Postgres; other agents audit the
   code in depth). Every `READ` entry is a direct reading of the cited lines, not a test result.

## (b) Evidence appendix (commands and trimmed real outputs, by gap id)

**PROC4-001..006, 015, 048 (nothing but the summary reaches the service; no shadow mode; no injection)**

```
$ cd /home/user/audit/engine && grep -n "v1/runner\|FENVIX_MODE\|FENVIX_REGION\|FENVIX_MACHINE\|RUNNER_TOKEN\|summary-token\|receiptsUrl\|curl\|progress\|shadow\|wouldSkip\|language\|test_runner" runner/fenvix-run
(no output)
$ sed -n 2p runner/fenvix-run
"""fenvix-run: run a project's pytest suite inside the fenvix engine on a `runs-on: fenvix` machine.
$ grep -rn "FENVIX_MODE\|would_skip\|wouldSkip" --include=*.py --include=*.rs --include=*.js --include=*.ts --include=*.go --include=*.java . | grep -v /target/
(no output)
$ cd /home/user/fenvix-app && grep -rn "v1/runner/\(progress\|results\|explorations\|summaries\|warmups\)" infra/github-app/lib
infra/github-app/lib/runner/files/fenvix-warmup-done:4:# (POST /v1/runner/warmups, "finished"), then power off. ...
infra/github-app/lib/runner/files/fenvix-summary-poster:2:"""Sends the run summaries ... (POST /v1/runner/summaries).
infra/github-app/lib/runner/files/fenvix-warmup-report:2:"""Sends a warm-up machine's reports ... (POST /v1/runner/warmups; ...
infra/github-app/lib/runner.ts:87:    FENVIX_SUMMARIES_URL: `https://${s.domainName}/v1/runner/summaries`,
$ cat infra/github-app/lib/runner/files/fenvix-job-started
#!/usr/bin/env bash
# GitHub runner job-started hook (ACTIONS_RUNNER_HOOK_JOB_STARTED), as the job user: a marker for the idle watchdog ...
mkdir -p "$HOME/.fenvix" 2>/dev/null && touch "$HOME/.fenvix/job-started" 2>/dev/null
exit 0
$ grep -rn "PYTEST\|ADDOPTS\|sitecustomize" infra/github-app/lib/runner/files/
(no output)
```

**PROC4-049 (onboarding PR body)**: `github-app/src/onboarding/onboard.ts`

```
34:    "Nothing else in the workflow changes: same steps, same triggers, same secrets. The tests run on a fenvix machine, inside the fenvix engine:",
36:    "- a test whose inputs did not change since a passing run is **skipped with proof**, and its receipt says what was checked;",
57:    "Merge it when you are ready. The first run on fenvix starts cold; from the second run on, unchanged tests are skipped with proof.",
```

**PROC4-007, 008 (defect bundle pull, API keys)**

```
$ grep -rn "defects pull" src docs/data-contract.md
src/data/ci.ts:382:export const pullCommand = (d: Pick<Defect, "id">) => `fenvix defects pull ${d.id}`;
docs/data-contract.md:219:is null), after `fenvix defects pull <id>` writes the bundle to `<bundle>`. Node: the engine has no `--det-order`,
$ git -C /home/user/fenvix-engine-cli grep -n "defects pull" origin/claude/release-1
(no output)
$ sed -n 5,6p src/pages/ApiKeys.tsx
 * API keys for scripts and coding agents. The public API they would call does not exist yet, so the page only says
 * so (founder, 2026-11-18): no key list and no form until it does. The navigation keeps the entry.
```

**PROC4-009..016 (billing, units, gate, trial)**

```
$ sed -n 101p src/pages/Billing.tsx
  <button type="button" className="btn btn-block" disabled={p.current || !org.canManage} onClick={() => toast(`We will be in touch about the ${p.name} plan`)}>
$ grep -rn -i "overage\|0\.056" src supabase/migrations
(no output)
$ sed -n 28,31p src/data/ci.ts
/** 1 run unit = 10 baseline minutes (minutes a job held a fenvix machine, by GitHub's timings). */
export const MINUTES_PER_UNIT = 10;
/** The trial's gate: fenvix would have skipped at least this share of test time. */
export const TRIAL_GATE = 0.35;
$ sed -n 325p src/data/ci.ts
    gate: { threshold: TRIAL_GATE, met: share !== null && share >= TRIAL_GATE },
$ sed -n 424,427p github-app/src/service.ts    (trimmed)
  select (select region from public.workspaces ...) as region,
         (select trial_ends_at > now() from public.ci_subscriptions ...) as trial
  return { region: r?.region === "eu" ? "eu" : "us", mode: r?.trial ? "shadow" : "enforce" };
```

Migration `0014_dashboard_api.sql:154-159` inserts the plans with prices 129, 479, 1350, 4200 and never sets
`units_included` (comment at :146: "How many units each plan includes is not set yet (null)").
DECISIONS 2026-11-18: "Starter 2,500 units $129, Team 10,000 $479, Scale 30,000 $1,350, Monorepo 100,000 $4,200 ...
overage at most $0.056 per unit ... A paid plan is sold only when shadow mode shows our machine-minutes at or under
35% of baseline."

**PROC4-019..021 (settings stored, never read)**

```
$ grep -rn "comment_on_pull_requests\|skip_with_proof\|test_command" github-app/src --include=*.ts | grep -v "openapi.gen\|api/data.ts"
github-app/src/service.ts:862: ... select comment_on_pull_requests from ci_projects where id = $1 for update ...
github-app/src/service.ts:863:          commentsOn = proj.comment_on_pull_requests;
```

Only `comment_on_pull_requests` has a reader.

**PROC4-051..055 (wrappers, image, pinned commit)**

```
$ cd /home/user/fenvix-engine-cli
$ git log -1 --format='%h %ad %s' --date=iso a20b93d
a20b93d7 2026-11-18 14:31:07 +0000 R-008c: REPORT-4 (start-up Popen fix, engine suite in both package sets, ...)
$ git merge-base --is-ancestor a20b93d origin/claude/release-1 && echo ANCESTOR || echo NOT-ancestor
NOT-ancestor
$ git log --oneline a20b93d..origin/claude/shared-cache | wc -l
2
$ git merge-base --is-ancestor origin/claude/runner-node origin/claude/release-1 && echo merged || echo NOT-merged
NOT-merged
$ git ls-tree --name-only origin/claude/release-1 runner/
runner/bootstrap.sh runner/ci-project-env.sh runner/fenvix-run runner/local-demo.sh runner/local-shared-demo.sh runner/shared-cache-compare
$ grep -n "engineCliCommit\|runnerMode\|fenvixRegion\|warmupEnabled\|runnerMaxRunning" /home/user/fenvix-app/infra/github-app/cdk.json
34:    "fenvixRegion": "us",
39:    "runnerMode": "per-job",
42:    "runnerMaxRunning": "4",
45:    "warmupEnabled": "true",
59:    "engineCliCommit": "a20b93d7f840b23f71c73c03efdaee3d6a233252",
$ grep -n "apt-get install" /home/user/fenvix-app/infra/github-app/lib/runner/files/install.sh
29:apt-get install -y -qq git curl tar strace build-essential python3 iptables ca-certificates \
$ grep -rn "summary.json\|v1/runner" /home/user/audit/engine/release
(no output)
```

The vendored cache service itself is current (not a gap): `sha256sum infra/github-app/lib/cache/cache_service.py`
equals `python/detpy/cache_service.py` of release-1 (`2b93cd9a...`).

**PROC4-063..068 (PR comment)**

```
$ grep -n -i "diverg" github-app/src/results/render.ts github-app/src/results/summary.ts
(no output)
$ sed -n 82,86p github-app/src/results/render.ts
    L.push("", "### Flaky tests, explained", "",
      "Each failed in the suite and passed when run alone: another test leaves state behind (order-dependent). ...
      L.push(`- ${code(t.nodeid)}`, `  - replay: ${code(t.replay)}`);
      if (t.minimise) L.push(`  - find the test that breaks it: ${code(t.minimise)}`);
```

**PROC4-071..074 (languages the service can hold)**

```
supabase/migrations/0011_ci_runs.sql:65:  language text not null check (language in ('python', 'node', 'go')),
supabase/migrations/0011_ci_runs.sql:66:  test_runner text not null check (test_runner in ('pytest', 'vitest', 'jest', 'go test')),
supabase/migrations/0011_ci_runs.sql:156:  language text not null check (language in ('python', 'node')),
github-app/src/onboarding/workflow.ts:40-47: rules for pytest, vitest, jest, go test, tox|nox, uv/poetry/hatch/pdm run,
  unittest | manage.py test (runner null), npm|pnpm|yarn|bun test (runner null). No gradle, mvn, playwright, cypress.
```

**PROC4-083..086 (regions)**

```
$ grep -n '"region"\|"fenvixRegion"\|"second' infra/github-app/cdk.json
    "region": "eu-west-1",
    "fenvixRegion": "us",
    "secondFenvixRegion": "",  "secondAwsRegion": "",  "secondLaunchTemplateId": "",  "secondCacheUrl": "",
$ sed -n 161,162p infra/github-app/lib/stack.ts
    const placement: Record<...> = {
      [s.fenvixRegion]: { awsRegion: this.region, launchTemplateId: fleet.launchTemplate.ref },
$ sed -n 118p supabase/migrations/0014_dashboard_api.sql
alter table public.workspaces add column if not exists region text not null default 'us';
$ sed -n 93,107p infra/github-app/permissions-boundary.json   (trimmed)
  "Sid": "RunnerMachines", "Action": ["ec2:RunInstances","ec2:CreateTags","ec2:TerminateInstances",...],
  "Resource": "*", "Condition": {"StringEquals": {"aws:RequestedRegion": "eu-west-1"}}
```

**PROC4-090..093 (R-012b)**

```
$ ls infra/github-app/test | tr '\n' ' '
bootstrap.test.ts ... review-r012.test.ts review-r024.test.ts review-r024c.test.ts ...   (no review-r012b.test.ts)
$ git show origin/claude/review-r012b --stat --format='%h %s' | head -4
195839a Review R-012b: second round of R-012 (FIX 3); 18 findings verified fixed, 3 new defects with failing tests ...
 infra/github-app/test/review-r012b.test.ts |  66 +++
$ grep -n "setpriv\|O_NOFOLLOW\|uid-owner\|--netns" infra/customer-mode/spike/*
(no output)
$ grep -n 'R-012' /home/user/fenvix-brain-cli/{LOG,NOW,DECISIONS,NUMBERS}.md
(no output)
```

**PROC4-101 (customer mode not on main)**

```
$ git log --oneline main..origin/claude/customer-mode-pnap | wc -l      => 7
$ git log --oneline origin/claude/customer-mode-pnap..main | wc -l      => 51   (at ce69a6b; more after the fast-forward)
$ git diff --stat main...origin/claude/customer-mode-pnap | tail -1      => 87 files changed, 16814 insertions(+), 39 deletions(-)
$ ls infra/customer-mode                                                => spike
```

**PROC4-129 (warm-up executor)**: `infra/github-app/lib/runner/files/fenvix-warmup`

```
exe="$HOME/engine-cli/runner/warmup.sh"
if [ ! -x "$exe" ]; then
  printf '{"outcome":"unsupported","detail":"this runner image has no warm-up executor (fenvix-engine-cli runner/warmup.sh)"}\n' >"$out/outcome.json"
```

`git -C /home/user/fenvix-engine-cli grep -l warmup origin/claude/release-1 -- runner docs` => no output.

**PROC4-133**: `grep -n "reservedConcurrent\|advisory" infra/github-app/lib/stack.ts github-app/src/warmup/warmups.ts`
=> no output.

**PROC4-141, 142 (Vercel merge)**

```
$ git -C /home/user/fenvix-app reflog -3 --date=iso
c59d913 HEAD@{2026-11-20 08:34:35 +0000}: merge origin/main: Fast-forward
ce69a6b HEAD@{2026-11-20 08:19:18 +0000}: checkout: moving from claude/compassionate-edison-2dsntf to main
$ git log --format='%h %ad %s' --date=iso ce69a6b..main
c59d913 2026-11-20 09:19:32 +0100 Merge pull request #19 from Mircoguidetti/claude/dashboard-vercel
4330622 2026-11-20 08:07:24 +0000 DEPLOY-VERCEL.md: reuse the existing Vercel project fenvix-app
32cf86f 2026-11-20 08:06:39 +0000 Host the dashboard on Vercel; AWS dashboard stack off behind one switch
```

Brain at the same time: NOW.md (06:57 UTC) "Dashboard blocked by AWS"; newest LOG entry 07:55 UTC; DECISIONS
"2026-11-20 — Dashboard on Vercel now (fallback activated) ... Work: P-035".

**PROC4-144**: `git log --format='%h %s' 4cdc4ef..ce69a6b` => `ce276a9 Fix shellcheck findings that block the deploy`,
`d651af6 Fix CloudFormation tag permissions that blocked the first deploy`, `4f94746 Grant API Gateway tag actions
that blocked the second deploy` and their three merge commits (#16, #17, #18).

**PROC4-124..126, 157..159 (landing)**: text extracted from `fenvix-landing/pricing/index.html` (tags stripped):

```
... Runs up to 2,000 Projects 5 Nightly exploration included Price at launch Team. ... Runs up to 10,000 Projects 25 ...
Enterprise agreed with you ... Fewer minutes lower our cost, not your bill. ... Nightly exploration included. At night
your suite runs in many orders and seeds ... Those runs are not counted against your plan. ... No charge per minute or
per test. A long job and a short job are one run each. ... at $0.008 a minute as listed by GitHub ...
```

`grep -n -i 'landing\|pricing page' DECISIONS.md LOG.md NOW.md CLAUDE.md` in the brain => no output.
`grep -rn -i 'fenvix-landing\|fenvix-docs' prompts sessions/*/REPORT*.md CLAUDE.md RULES.md` => only
`prompts/P-036-gap-audit.md` (this audit).

**PROC4-080**: `find /home/user/audit/engine -maxdepth 3 \( -name action.yml -o -name action.yaml \)` => no output.

**PROC4-163**: `ls /home/user/fenvix-brain-cli/components` => `README.md harness.md level0.md verifier.md`.

**PROC4-167..171**: `ls prompts | grep '^R-'` => `R-001-mixed-round.md R-010-market-test.md REVIEWER.md` (plus README).

## (c) What the lead should know

### The pattern

Every service block was closed when its session passed its own test list against **fakes** (fake GitHub, local
Supabase, stub AWS, fake phoenixNAP, a fake jailer). Three things were never demanded by any prompt:

1. **The other half.** P-026 says the runner side is "contract only, runner not edited here"; the warm-cache report
   says the executor "does not exist yet"; the P-017 report says how the engine gets into the customer's step is
   "Runner fleet work, Block 4 part 2". No "part 2" prompt exists. Result: the App, API and dashboard are a complete
   receiving side with no sending side (PROC4-001..006, 015, 048, 051..055, 129).
2. **A real run.** No block's "Done means" contains "one real job of a real repository, end to end". The single live
   `runs-on: fenvix` run (2026-11-18) was on the founder's PC with a hand-registered runner and predates the App.
3. **A comparison with the decisions.** Regions, the 35% gate, the unit definition, plan units, exploration pricing
   and customer machines each differ from DECISIONS.md, and no reviewer was asked to check decisions.

### Statements in the brain that the code contradicts

| Brain statement | What the code shows | Gap |
|---|---|---|
| NUMBERS: "Dashboard ... CLOSED: every page on real data" | seeded local data; nothing real can arrive | PROC4-043 |
| NUMBERS: "Warm cache at install CLOSED" | every warm-up machine reports "unsupported" | PROC4-129 |
| LOG: "Customer mode on phoenixNAP closed" | not on main; never run on a host | PROC4-101, 102 |
| DECISIONS: runners in two regions, US data stays in the US | one stack in eu-west-1 labelled "us"; "eu" gets no machine | PROC4-083, 084 |
| DECISIONS: gate = our machine-minutes at or under 35% of baseline | dashboard: would-skip share of test time >= 35% | PROC4-014 |
| DECISIONS: 1 unit = 10 baseline test minutes, price per run not per minute | units from held machine minutes | PROC4-013 |
| DECISIONS: plan units 2,500 / 10,000 / 30,000 / 100,000, overage $0.056 | units null, no overage anywhere | PROC4-010, 011 |
| DECISIONS: exploration is a paid add-on | PRODUCT.md and the landing: included | PROC4-124 |
| DECISIONS: Firecracker microVM per job from the first customer | one EC2 VM per job; microVM code is a spike or unmerged | PROC4-096, 099, 101 |
| RULES: never pricing pages, landing pages or billing now | all three exist | PROC4-157 |
| RULES: merge only with an independent reviewer's approval | PR #16-#18 and #19 merged without one | PROC4-142, 144 |
| RULES: every prompt is saved before it is sent | 4 work prompts and 5 reviewer prompt series missing | PROC4-089, 100, 116, 128, 167..171 |
| Onboarding PR body: "inside the fenvix engine ... skipped with proof" | the engine is not put around the customer's step | PROC4-049 |

### Things that were fixed or decided (not listed as gaps)

- R-012 F1-F18, R-014 R1-R11 and R-014b N1 (on the unmerged branch), R-016 F1-F8, R-016b G1-G2, R-018 F1-F2,
  R-024 F1-F5, R-024b G1-G4, R-024c K1-K5: each has its reviewer test on the branch that fixed it; on main I
  confirmed the presence of `review-r012`, `review-r016`, `review-r016b`, `review-r018`, `review-r024`, `review-r024b`
  (deploy/test) and `review-r024c` test files. I did not re-run them.
- "Dashboard talks only to our API": holds in the code (`src/` uses Supabase for sign-in only; `src/data/api.ts`).
- P-016's unmet exit (no job picked up by a fenvix runner) was closed later on the founder's machine (LOG 2026-11-18).
- Blacksmith 2x test: deferred by a recorded decision (2026-11-18 and 2026-11-19).
- The vendored shared cache service equals release-1's file byte for byte.
- R-024c's note on the GitHub Free Actions minutes quota is in DEPLOY-AWS.md.

### Cautions about my own entries

- Entries on the customer-mode branch (PROC4-104..112) describe code that is not on main; they matter only when
  that branch is merged, and PROC4-101 is the entry that matters before.
- PROC4-055 (old engine pin) is a WRONG-RESULT **once a hosted job runs**: today no job can run (PROC4-046).
- PROC4-014 compares two different quantities; if the founder meant "skip share >= 35%" the decision text, not the
  code, is wrong. Either way they disagree.
- PROC4-141: main changed while I was working; I could not observe the result of the deploy that the merge
  triggers.
- The task named `DEPLOY-VERCEL.md` at the repository root of the Vercel branch; the file is `docs/DEPLOY-VERCEL.md`.
  `deploy/` has no README (PROC4-156).
- One session report in the brain (customer mode, round 1) talks about the visibility of a repository; I have not
  repeated it anywhere.
