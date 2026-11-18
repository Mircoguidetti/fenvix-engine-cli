# `runs-on: fenvix`: runner prototype

A GitHub Actions job declared with `runs-on: [self-hosted, fenvix]` is picked up by **our** machine, runs the
project's pytest suite inside the fenvix engine (`pytest --det --det-cache=<dir on the machine>`), keeps the cache
with proof on the machine between jobs, and writes a summary on the run: tests run, tests skipped with proof (with
receipts), test time saved, failures, flaky tests with their replay command.

Prototype scope: one machine, registered as a GitHub **self-hosted runner** (free on GitHub), serving this repository.

## Files

| file | what it does |
|---|---|
| `runner/bootstrap.sh` | turns a Linux x64 machine into the runner: tools (git, strace, uv, Rust), Python, the engine wheel (built from this checkout), the official Actions runner (pinned version, SHA-256 checked), registration with labels `self-hosted,fenvix`, the job environment (`.env`: where the engine and the cache are) |
| `runner/fenvix-run` | the job wrapper (stdlib Python). `fenvix-run` runs the suite in the engine and writes `$GITHUB_STEP_SUMMARY` + `summary.json` + `receipts.jsonl`; `fenvix-run verify` runs the suite again without the cache and checks every reused outcome (wrong must be 0) |
| `runner/local-demo.sh` | the two demo jobs on this machine without GitHub (same steps, same work paths as a runner): to check a machine before it serves jobs |
| `.github/workflows/fenvix-demo-jobs.yml` | reusable body: job 1 at commit N (cold cache), job 2 at commit N+1 (warm cache) + verify |
| `.github/workflows/fenvix-demo.yml` | the real thing: `runs-on: [self-hosted, fenvix]` |
| `.github/workflows/fenvix-demo-hosted.yml` | rehearsal on a GitHub-hosted machine (free on a public repository); the cache directory is carried from job 1 to job 2 as an artifact, because two hosted jobs never share a machine |
| `tests/test_runner_wrapper.py` | wrapper tests: reuse with proof in job 2 and verify = 0 wrong; an order-dependent failure is reported flaky with its replay |
| `tests/test_runner_node.py` + `tests/fixtures/runner-node/` | Node path: a Vitest (npm) and a Jest (yarn 1) project with order-dependent tests, a mixed Python + Vitest (pnpm) repository; the replay commands are run and must fail again; `--det-cache` is a no-op until detjs has it |
| `.github/workflows/fenvix-demo-node-hosted.yml` | Node rehearsal on hosted machines: engines built by `bootstrap.sh engines`, `unjs/ufo` (public Vitest project), the mixed repository as one job per language, the fixtures and the wrapper tests |

Demo target: `pygments/pygments`, commit N = `9c436b34` ("Go lexer improvements"), N+1 = `b6aaaca7` ("Groff formatter:
don't duplicate a character when word-wrapping": `pygments/formatters/groff.py` changed, one test file grew). Any
other public pytest project works through the `workflow_dispatch` inputs (`target`, `commit_n`, `commit_n1`, `extra_pip`).

Engine: `BASE` 1573079 + cache-proof patches 0001-0008 (`tracks/cache-proof/patches-step1/` on
`claude/loving-maxwell-58mv2w`). The latest commit of `claude/cache-proof-step1` was not used: its suite fails
`tests/test_proofcache.py::test_module_level_change_reruns_every_test_that_had_the_module_loaded` in the full run
(2 of 2 runs; it passes alone): the test after the edit runs the *old* module (stale bytecode), see the session report.

## Node (Vitest, Jest)

The same wrapper, the same `summary.json` keys (schema `fenvix-summary/2`) and the same step summary as Python. In
the customer's workflow, one job per language:

```yaml
jobs:
  python:
    runs-on: [self-hosted, fenvix]
    steps: [checkout, venv + project + detpy, run: fenvix-run --lang python --python .venv/bin/python]
  node:
    runs-on: [self-hosted, fenvix]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4          # optional: without it the machine's Node LTS is used
        with: {node-version: 22}
      - run: fenvix-run --lang node          # Vitest or Jest, found in package.json
```

What `fenvix-run --lang node` does:

1. **Dependencies** as the project's CI installs them, from the lockfile, when `node_modules` is missing:
   `npm ci`, `pnpm install --frozen-lockfile`, `yarn install --frozen-lockfile` (yarn 1) or `--immutable` (berry),
   `bun install --frozen-lockfile`; a lockfile at the workspace root is found from a package directory; a pinned
   `packageManager` goes through corepack. `--install always|never`, `--install-cmd '...'` override it.
2. **Tests**: `detjs vitest run --det` or `detjs jest --det` (detjs runs the project's own Vitest 1.4–5 / Jest), with
   the runner flags of the project's `test` script (`vitest run --typecheck` -> `--typecheck`; watch/coverage/in-band
   flags dropped), the detjs trace (outcome and fingerprint per test) and the runner's JSON report (timings).
3. **Failures** run again alone (file + exact name). A test that passes alone is **flaky**; the wrapper then looks for
   the shortest replay that fails again (the test's file; then each earlier test of that file together with it) and
   runs it: the summary's `replay` was seen to fail again in the job (`replay_reproduces: true`), `minimise` names
   the test that leaves the state behind, `explanation` says it in words.
4. **Cache with proof**: not for Node yet. `--det-cache` is wired: it passes `--det-cache=<machine cache dir>`
   (and `--det-cache-receipts` if listed) once `detjs --det-help` lists the flag (claude/node-cache-proof); until
   then it is a no-op, said in `cache_status` and in the step summary. The cache directory is per project and Node
   major (`<key>-node<major>`), never shared with the Python cache (`<key>-py<ver>`).

`runner/bootstrap.sh` installs Node 26.13.1 (the Active LTS on 2026-11-18, SHA-256 checked) in `$FENVIX_HOME/node`
with corepack shims, builds detjs from `claude/node-l0` at a pinned commit (`FENVIX_DETJS_REF`) into
`$FENVIX_HOME/detjs`, and adds `FENVIX_DETJS` and `$FENVIX_HOME/bin/detjs` (which runs with the job's own `node`) to
the job environment. `bootstrap.sh engines` does only tools + engines (what a machine image bakes in).

## How a job flows

```
GitHub  --job (runs-on: self-hosted, fenvix)-->  our runner (actions/runner, labels self-hosted,Linux,X64,fenvix)
                                                   |  checkout engine + target commit; venv; detpy wheel from $FENVIX_WHEEL_DIR
                                                   |  fenvix-run: pytest --det --det-cache=$FENVIX_CACHE_ROOT/<project>-<python>
                                                   |     reused tests: result + receipt, 0 s; changed tests: run, recorded
                                                   |  failures: re-run alone -> failure or flaky (replay command)
                                                   '--> $GITHUB_STEP_SUMMARY, artifact fenvix-receipts-<job>
```

The cache lives in `$FENVIX_HOME/cache` (outside the runner's `_work` directory, which the runner cleans), one
directory per project and Python version. The demo uses one cache namespace per workflow run (key
`<target>@demo-<run id>`) so every demo starts cold at N; a real project job uses the project key alone and keeps
one warm cache for all its runs. Every job must use the same work paths (the runner does: `_work/...`,
`_work/_temp/venv`): the engine's runtime identity includes the installed distributions, and an editable install
records its path, so a venv at a different path is a different runtime and nothing is reused (MEASURED: 2,558 of
2,558 entries missed on `runtime` when job 2 used another directory).

## Run it (founder: about 10 minutes, $0)

Needs one Linux x64 machine you own that can stay on during the demo (a Linux PC, a VM, or WSL2 on Windows), with
outbound HTTPS to `github.com`, `api.github.com`, `*.actions.githubusercontent.com`. No AWS (spending needs the
founder's yes); no secret in git, no token in a chat.

1. **Protect the public repository first.** GitHub → `fenvix-engine-cli` → **Settings → Actions → General** →
   "Fork pull request workflows from outside collaborators" → **Require approval for all external contributors** →
   Save. (See Security below.)
2. **Get a registration token.** **Settings → Actions → Runners → New self-hosted runner** → Linux, x64. The page
   shows a `./config.sh --url ... --token XXXXX` line. Copy only the token (valid one hour). Ignore the rest: the
   bootstrap does the download and configuration.
3. **On the machine**, put the token in a private file (it never enters git or a chat):
   ```bash
   git clone -b claude/runner-prototype-ee21he https://github.com/Mircoguidetti/fenvix-engine-cli && cd fenvix-engine-cli
   mkdir -p ~/.fenvix && (umask 077; cat > ~/.fenvix/registration-token)   # paste the token, Enter, Ctrl-D
   runner/bootstrap.sh install         # ~5 min: tools, engine wheel, runner; ends with a network check
   runner/local-demo.sh                # optional: the two demo jobs locally (~2 min), wrong must be 0
   runner/bootstrap.sh register        # the runner appears under Settings -> Actions -> Runners, labels self-hosted, fenvix
   rm ~/.fenvix/registration-token     # used once
   runner/bootstrap.sh run             # leave it running ("Listening for Jobs")
   ```
4. **Open the gate**: **Settings → Secrets and variables → Actions → Variables → New repository variable**:
   name `FENVIX_RUNNER_READY`, value `true`.
5. **Start the demo**: a push to `claude/runner-prototype-ee21he` that touches `runner/**` or a `fenvix-demo*.yml`
   (any work session can do it), or, once the file is on the default branch, **Actions → fenvix-demo → Run workflow**.
   Two jobs appear on the run page; both run on your machine (the job page shows the runner name `fenvix-<host>`);
   the second job's summary shows the skip with proof and "wrong: 0".
6. **Close**: Ctrl-C the runner; delete it under **Settings → Actions → Runners** (or `runner/bootstrap.sh remove`
   with a fresh token); set `FENVIX_RUNNER_READY` to `false`.

Ephemeral mode (`FENVIX_EPHEMERAL=1`: one job, then the runner deregisters) needs a fresh token per job, so it needs a
credential that can mint tokens (a GitHub App, below). A just-in-time config (`POST
/repos/{owner}/{repo}/actions/runners/generate-jitconfig`, admin) can be put in `~/.fenvix/jitconfig` instead of a
token: `bootstrap.sh run` then serves exactly one job.

## Security (the repository is public)

GitHub's own guidance is to avoid self-hosted runners on public repositories, because a pull request from a fork can
contain a workflow that targets them and runs arbitrary code on the machine. What this prototype does about it:

* `fenvix-demo.yml` and `fenvix-demo-hosted.yml` trigger only on `push` to `claude/runner-prototype-ee21he` and on
  `workflow_dispatch`; never on `pull_request` or `pull_request_target`. Only people with write access can push or
  dispatch. No other workflow on this branch targets `self-hosted` (checked: all use `ubuntu-latest`); workflows on other branches run only on pushes by people with write access.
* A fork pull request can still *add* a workflow with `on: pull_request` + `runs-on: self-hosted` in its own diff.
  Step 1 above (require approval for external contributors) makes such a run wait for an owner's click; never
  approve a fork run while the runner is online. The runner is registered to this one repository only.
* The jobs get `permissions: contents: read`; the target project is checked out with `persist-credentials: false`.
  No secret is used by the demo. The registration token lives in a mode-600 file outside the clone and is deleted
  after registration.
* Run the runner as an unprivileged user on a machine with nothing else of value; stop it after the demo.

For production the answer is structural, not a setting: one throwaway VM per job (just-in-time runners), created by
our GitHub App, so no job ever sees another job's machine or our credentials.

## What is missing for production

| piece | prototype | production |
|---|---|---|
| machines | one machine, one runner, jobs in sequence | a fleet (AWS, founder's yes for spending): a pool of warm VMs, one fresh VM per job (JIT runner), autoscaled on the queue (`workflow_job` webhooks) |
| registration | founder copies a one-hour token by hand | a **GitHub App** installed by the customer (scopes: `administration` for self-hosted runners, `actions:read`, `checks:write`, `pull_requests:write`); our control plane mints JIT configs per job |
| cache | a directory on the one machine | a **shared cache service**: entries keyed by project + runtime + config, served to every VM; content-addressed, per-customer isolation and encryption; the engine already merges stores under a lock and keeps per-entry receipts |
| reporting | `$GITHUB_STEP_SUMMARY` + receipts artifact | the same plus a **PR comment** / check run per PR ("N tests skipped with proof, M minutes saved, flaky: ... replay: ..."), and a dashboard |
| trust | verify step re-runs the whole suite (doubles the time; demo only) | sampled verification (`--det-cache-verify=FRACTION`) on a share of jobs, plus the nightly full run |
| other languages | Python (pytest), Node (Vitest/Jest, no cache yet) | Node cache with proof (detjs `--det-cache`), Go |
| billing / pricing | none | per CI run (DECISIONS 2026-11-17); not before the founder decides |

## Known limits seen in this prototype

* Reuse is coarse on some projects: a change to a module that every test imports re-runs every test (click
  `e38188e` → `08b803c`: 0 of 2,653 reused, MEASURED locally). The demo pair was chosen from the cache-proof walk
  (`tracks/cache-proof/results/r5/pygments`) as a realistic source change with a high reuse.
* **The cache does not cross machines yet.** In the hosted rehearsal (run 44187521000) job 2 ran on another GitHub
  machine with job 1's cache: 0 of 5,314 reused, all on `runtime` (digest `816b626a` in job 1, `35556ebb` in job 2),
  while on one machine 5,287 were reused (MEASURED). `fenvix-run` now records the runtime parts per job and names
  the ones that changed (`runtime_changed_since_previous_job`, also in the step summary). A shared cache service needs
  a runtime identity that is equal on identical machine images; on our own fleet we control the image.
* The engine re-checks inputs per test: ~0.4 s of check on 5,314 tests (MEASURED locally).
* The runner (2.329.0) aborts at startup on some `no_proxy` entries (`::`, CIDR, `*.domain`); the bootstrap writes a
  cleaned `no_proxy` into the job environment.
