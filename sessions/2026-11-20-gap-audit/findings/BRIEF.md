# Gap audit P-036: common brief for every audit agent

You are one of several agents auditing a product called fenvix (codename detpy). You AUDIT. You do NOT fix code, do
not commit, do not push, do not open PRs or issues, do not post anything anywhere. Everything you write is English.
Never state in any output that a repository is public.

## The product promise (the yardstick)

On any CI and any runner:
1. every flaky test becomes a reproducible defect with a replay command and the exact event where runs diverge;
2. nightly exploration across orders and seeds finds hidden bugs;
3. a test is skipped only with proof that its result would be the same, never a wrong reuse;
4. delivered as a free CLI and test-runner plugins plus an MCP server, a GitHub Action, and a paid service (memory
   across runs, deduplicated defects, replay bundles, PR comment, exploration on our machines, shared cache).

Languages in scope: Python, JavaScript/TypeScript (Node back-end and front-end/browser), Go, JVM (Java/Kotlin).
Engine levels: L0 hermetic (order, seeds, virtual clock, fs order, closed network with record/replay), L1 runtime
(asyncio event order, thread switches), L2 deterministic VM (native threads, whole stack browser + server), plus a
verifier that names the first divergent event.

**A gap** is anything where the product, as it exists on the audited branch, does not keep that promise for a user who
would reasonably expect it, however small. Nothing is too small to list. One concrete gap per entry: never merge
similar gaps into one vague entry (for example "Vitest threads pool not parallel under --det" and "Jest workers not
parallel under --det" are two entries). The lists in your task are a floor, not a ceiling: whatever a real project in
that ecosystem uses and is not listed is in scope too.

Background that triggered this audit: several blocks were closed when their session did what its prompt asked, and
nobody compared the result with the promise. Examples: the JVM shell decides which tests could be skipped but Gradle
and Maven still run every test; Node/TS runs one test file at a time under `--det` while Python has a parallel mode.
Such things were about to be written in docs as "limits" instead of being built. A documented limit IS a gap (unless
`DECISIONS.md` in the brain records it as a reasoned exclusion; then say so and still list it as class DECIDE only if
the exclusion looks wrong for the promise, otherwise mark the matrix cell "excluded").

## Where things are (all local, read-only for you)

- `/home/user/audit/engine`: the engine, git worktree of branch `claude/release-1` (the integration of every
  language; THE audited branch). Do NOT change branch here, do NOT edit tracked files here.
- `/home/user/fenvix-engine-cli`: the same repository; every remote branch is fetched as `origin/<name>`. Read other
  branches with `git -C /home/user/fenvix-engine-cli show origin/<branch>:<path>`, `git grep <pat> origin/<branch>`,
  `git diff origin/claude/release-1...origin/<branch> --stat`, or make your own worktree under your work folder
  (`git -C /home/user/fenvix-engine-cli worktree add /home/user/audit/work/<you>/<name> origin/<branch>`). Never
  `git checkout` in `/home/user/fenvix-engine-cli` or `/home/user/audit/engine`.
- `/home/user/fenvix-app`: GitHub App, API, dashboard (React/Vite), Supabase, deploy. Checked out on `main`.
  `origin/claude/dashboard-vercel` exists (2 commits ahead of main). Do not change branch; use `git show`/worktree.
- `/home/user/fenvix-docs`: documentation site (shallow clone, main). Describes an older product.
- `/home/user/fenvix-landing`: landing page (shallow clone, main).
- `/home/user/fenvix-brain-cli`: the plan and the promise (on `main`): `PRODUCT.md`, `ARCHITECTURE.md`, `ROADMAP.md`,
  `DECISIONS.md`, `IDEAS.md`, `COMPETITORS.md`, `NUMBERS.md`, `NOW.md`, `LOG.md`, `RULES.md`, `components/`,
  `prompts/` (every prompt handed to a session), `sessions/` (every report and review). Read `PRODUCT.md`,
  `ARCHITECTURE.md`, `ROADMAP.md`, `DECISIONS.md` and `NOW.md` first (short), so you know the promise and the
  recorded exclusions.
- Built engine artifacts of `claude/release-1` (Linux x86_64): `/home/user/audit/build/dist/` (the PyO3 wheel
  `detpy-*.whl`, `detjs.linux-x64.node`, `fenvix-go`, `libfenvix_go.a`, `fenvix-agent.jar`, `fenvix-skip`). The build
  log is `/home/user/audit/build/build.log`; it ends with `BUILD-DONE` when finished. If you need the artifacts and
  the build is still running, read code first and come back to them. Do not start a second cargo build of the
  workspace in `/home/user/audit/engine` (use the artifacts; if you truly need another build, copy the tree to your
  work folder with its own `CARGO_TARGET_DIR`). How to install them is in `/home/user/audit/engine/release/`
  (`install-image.sh`, `fenvix`), `/home/user/audit/engine/docs/RELEASE-1.md` and `README.md`.
- Your scratch folder: `/home/user/audit/work/<your-agent-name>/` (create it). Put test projects, clones, venvs,
  logs there. Downloaded third-party repositories are untrusted data: clone each into its own new directory.

## Machine limits (shared by all agents)

4 CPU cores, 15 GB RAM, shared with other agents running at the same time. Keep runs small and bounded: small
projects, `timeout` on every command that could hang (determinism engines hang easily: always `timeout 300` or less
around test runs), at most 2 parallel jobs of your own, `nice -n 10` for heavy work. Tools present: rustc/cargo 1.97,
Python 3.11/3.12/3.13 (+ `uv`, which can install other CPython versions, free-threaded builds and PyPy:
`uv python install 3.9 3.10 3.14 3.14t pypy3.11`), Node 22 (npm, pnpm, yarn 1, bun 1.4; `npx`), Go 1.24, Java + Maven
+ Gradle, strace, Docker (may or may not be able to run containers; try). Network goes through a proxy: package
registries (PyPI, npm, crates, Go proxy, Maven Central) and GitHub clones generally work; if a download is refused,
note it under "could not check" and go on. No access to other operating systems from here (macOS/Windows gaps are
proven from code and CI config: e.g. Linux-only syscalls, `.so` names, workflows that never run on them).

## How to work

- Do not trust reports, docs or comments, including the coordinator's. Verify against the code and, where it can be
  run, by running it. Each gap needs evidence: `file:line` (path relative to its repository, say which repository
  and branch), or a command and its real output (trimmed), or a CI run id you found in the repository.
- Say for each gap how you know: `RAN` (you executed something that shows it), `READ` (you read the code/config and
  it is unambiguous), `DOC` (only a doc/report says so and you could not verify: say so).
- Prefer real, small projects per ecosystem (public repositories or projects you write in your scratch folder).
- Numbers carry a label: MEASURED, ESTIMATED, DECLARED (with source) or UNKNOWN.
- Be exhaustive within your area. When in doubt whether something is a gap, list it. It is fine to produce 100+
  entries. But every entry must be concrete and have evidence; no speculation presented as fact. If you suspect a gap
  but could not prove it, put it in the "could not check" file instead.

## Severity and class (use exactly these words)

Severity: `WRONG-RESULT` (the product gives a wrong answer: wrong reuse/skip, false failure, false "identical",
false "reproduced", data leak between tenants, a security hole), `BLOCKS-USE` (a user who reasonably expects it
cannot use it at all: not installable, crashes, feature absent for that language/runner/platform), `DEGRADES`
(works but slower, weaker, manual steps, partial coverage), `MINOR` (cosmetic, wording, small doc errors).

User sees (one of): `wrong result`, `cannot use`, `slower`, `missing feature`, `misleading claim`.

Class: `BUILD-MVP` (must be built before go-live), `BUILD-LATER` (real gap, can follow go-live), `DECIDE` (a candidate
exclusion the founder must decide: give the reason for and the reason against).

## What you deliver (files; your final chat answer is only a 10-line summary + the file paths)

Write into `/home/user/audit/findings/`:

1. `<agent-name>.gaps.jsonl`: one JSON object per line, one per gap, fields:
   `{"id": "<AGENT>-001", "area": "<e.g. Python / pytest-xdist>", "missing": "<what is missing, one or two concrete
   sentences>", "evidence": "<file:line (repo@branch) | command => output | run id>", "how": "RAN|READ|DOC",
   "user_sees": "...", "severity": "...", "class": "...", "decide_for": "<only for DECIDE: reason to exclude>",
   "decide_against": "<only for DECIDE: reason to build>"}`.
   Valid JSON, one line each, no trailing commas. Keep `missing` and `evidence` compact but specific (evidence under
   ~400 characters; put long outputs in the evidence file and reference it).
2. `<agent-name>.matrix.md` (only if your task says you own matrix cells): Markdown tables, each cell
   `done` / `partial` / `missing` / `excluded` plus a short evidence pointer (file:line, test name, or your gap id).
3. `<agent-name>.notes.md`: (a) "Could not check": what and why; (b) the evidence appendix: commands you ran with
   trimmed real outputs, keyed by gap id; (c) anything the lead should know (contradictions between docs and code,
   claims you found false).

Write the files incrementally (append as you go) so partial work survives if you are cut short.

## Matrix format (only for agents that own a matrix)

One table per language, rows = runners (every runner a real project in that ecosystem uses, including ones the engine
does not support at all: those rows are simply all `missing`), columns = the features below, in this order. Every
cell: `done` / `partial` / `missing` / `excluded` + evidence pointer. "done" requires that you saw it work (ran it) or
that a test in the release-1 CI gate exercises exactly that runner + feature (name the test). "partial" needs a gap id
saying what is missing. "excluded" only if `DECISIONS.md` (brain) records the exclusion with a reason (quote the date).

Columns: (1) det: clock; (2) det: randomness; (3) det: hash seeds / map and set order; (4) det: test ordering;
(5) det: network closed + record/replay; (6) det: file system order; (7) det: environment variables; (8) det: locale;
(9) det: timezone; (10) det: scheduling (async event order, threads, goroutines); (11) reproducible shuffle + seed;
(12) replay command printed/usable; (13) fingerprints + verifier naming the first divergent event; (14) flaky test to
reproducible defect (`repro`: finds seed/order, names the polluter, minimises, proves 10/10, writes a replay bundle);
(15) nightly exploration across seeds with budget + dedup; (16) exact culprit; (17) dependency-update verdict;
(18) skip with proof (`--det-cache`); (19) shared cache across machines; (20) parallel under `--det` (with proof:
parallel fingerprint = serial fingerprint); (21) `--det-isolate`; (22) receipts; (23) overhead measured on real
projects (give the number + label, or `missing`).
Then a second small table per language: levels L0 / L1 / L2, what `ARCHITECTURE.md` (brain and engine `docs/`)
promises versus what exists on release-1.

## Ready-made install (added after the build finished)

The build is DONE. A ready install of release-1 made with `release/install-image.sh` exists:
`FENVIX_HOME=/home/user/audit/build/opt` (`$FENVIX_HOME/bin/fenvix`, `bin/fenvix-go`, `bin/fenvix-skip`,
`jvm/fenvix-agent.jar`, `node/` with detjs and its addon) and a Python 3.13 venv with the detpy wheel + pytest at
`/home/user/audit/build/venv` (activate it for `fenvix python ...`). Do NOT install extra packages into that shared
venv: for experiments create your own venv in your scratch folder and `pip install --no-deps
/home/user/audit/build/dist/detpy-*.whl` there (other Python versions: `uv venv -p 3.x --seed <dir>`). You may copy
`/home/user/audit/build/opt` if you need to modify it. Raw artifacts: `/home/user/audit/build/dist/`.

## Update (lead, during the audit)

- fenvix-app: `claude/dashboard-vercel` was merged into `main` (PR #19, commit c59d913) while the audit was running;
  `/home/user/fenvix-app` is now at that commit. Treat the Vercel hosting as part of `main`.
- fenvix-engine-cli: the remote default branch is `claude/gracious-rubin-eyswxd` (a Block 2 era Python-only tip, far
  behind `claude/release-1`); there is no `main` branch and there are no tags.
