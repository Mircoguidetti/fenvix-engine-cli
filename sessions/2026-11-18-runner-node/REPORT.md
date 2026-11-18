PARTIAL

# runner-node: Node (Vitest, Jest) on `runs-on: fenvix`

Session of 2026-11-18. Branch `claude/runner-node` (from `claude/runner-prototype-ee21he` @ `4391eb0`). Nothing pushed
anywhere else; fenvix-app untouched (item 5 is a patch file here).

## Result per item

| # | item | status | evidence |
|---|---|---|---|
| 1 | bootstrap.sh installs Node LTS and builds detjs next to the detpy wheel | done | run end to end in this container (below) and on a hosted machine (item 6) |
| 2 | fenvix-run: detect, install as CI does, run under detjs `--det`, same summary.json and step summary; `--det-cache` wired behind a flag, no-op test | done | `tests/test_runner_node.py` (9 tests), ufo locally (491 tests) |
| 3 | mixed repository: one job per language | done | fixture `mixed` (pytest + Vitest/pnpm), test + 2 hosted jobs |
| 4 | Vitest and Jest fixtures with an order-dependent flaky test; summary correct; the replay reproduces | done | the tests run each replay command and require the test to fail again |
| 5 | AWS image: exact recipe change as a patch file | done, with a limit | `image.patch` (a new Image Builder component, every phase run here); fenvix-app could not be read (see Limits) |
| 6 | one hosted Actions run with a public Vitest project | half run | [run 44346012832](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44346012832): `engines` passed on a hosted machine (bootstrap in 48 s); the ufo, mixed and fixtures jobs were still queued for a machine when this report was written (see below) |

## What changed

* `runner/fenvix-run` (stdlib Python, one file):
  * **Language**: `--lang auto|python|node`. Auto: `--python` given -> Python (unchanged behaviour of existing
    workflows); else detected (Python markers; `package.json` with Vitest or Jest). A repository with both stops
    with "run one job per language with --lang python and --lang node".
  * **Install as CI does**, from the lockfile, when `node_modules` is missing: `npm ci`, `pnpm install
    --frozen-lockfile`, `yarn install --frozen-lockfile` (yarn 1) / `--immutable` (berry), `bun install
    --frozen-lockfile`; lockfile of a workspace root found from a package; `packageManager` pins go through
    corepack. `--install always|never`, `--install-cmd`. Recorded in `summary.install`.
  * **Run**: `detjs vitest run --det` / `detjs jest --det` + the runner flags of the project's `test` script
    (ufo: `vitest run --typecheck` -> `--typecheck`; watch/coverage/in-band dropped; `--no-script-args`), with
    `--det-trace` (outcome + fingerprint per test) and the runner's JSON report (timings; Vitest's json reporter,
    Jest `--json`). detjs ids: `file::describe::name`, duplicates ` #2` (the report is mapped to the same ids).
  * **Failures** re-run alone (`<file> -t '^<full name>$'`, Jest `--runTestsByPath`; Vitest separator `" "`, then
    `" > "` if nothing was selected). Passes alone -> **flaky**. The wrapper then searches the shortest replay
    that fails again and **runs it**: the file alone, then each earlier test of the file (nearest first, up to
    `--max-minimise` 8) together with the victim; if the file alone does not reproduce it, the whole suite
    (cross-file state) is run. `flaky[]` = `nodeid, replay, replay_reproduces, replay_checked, minimise,
    explanation` (explanation names the polluting test when found).
  * **Same format**: schema `fenvix-summary/2`, one builder (`new_summary`) for both languages; the Node and Python
    summaries have exactly the same keys (tested). New keys for both: `schema, language, runner, cache_status,
    trace_file, fingerprints, timings, runner_args, install`; Python now also writes `--det-trace` (fingerprints)
    and maps JUnit times to node ids (timings); `pytest_args` kept for Python readers (null for Node). Python
    flaky entries carry an `explanation` too (`replay_reproduces: null`: the Python path does not re-run its
    whole-suite replay; the suite run itself is the evidence, as before). Step summary: same table; for Node a
    language/runner line, the runner in the wall-time row, a "Cache with proof: ..." line, the trace instead of
    receipts when the cache is off, and per flaky test "(run by this job: fails again)" + "why".
  * **`--det-cache` (Node)**: opt-in flag. Passed as `--det-cache=<machine cache dir>` (+ `--det-cache-receipts`
    when listed) only when `detjs --det-help` lists it; otherwise a no-op stated in `cache_status` ("requested,
    but this detjs has no --det-cache yet: no-op, every test ran") and in the step summary. Receipts, reuse counts,
    saved time and `verify` already read the same receipt format as Python, so nothing else changes when
    `claude/node-cache-proof` lands. Cache directory per project and Node major (`<key>-node26`), never the
    Python one (`<key>-py313`).
  * `fenvix-run verify` reads Node summaries too (fresh detjs run, outcomes compared).
* `runner/bootstrap.sh`: `install_node` (Node **26.13.1**, the Active LTS on 2026-11-18 per nodejs.org/dist
  index; SHA-256 pinned for x64 and arm64; corepack 0.36.0 installed, since Node >= 25 no longer ships it, with
  pnpm/yarn shims), `build_detjs` (fetches `claude/node-l0` at pinned `8e9209b` from this repository, builds the
  napi core with `node/scripts/build.js`, installs `bin/ src/ package.json detjs.linux-<arch>.node COMMIT` in
  `$FENVIX_HOME/detjs`, a `$FENVIX_HOME/bin/detjs` command that runs with the job's own `node`, checks
  `--det-help`); job `.env` gets `FENVIX_DETJS` and `$FENVIX_HOME/node/bin` on PATH; `FENVIX_LANGS` (default
  `python node`), `FENVIX_DETJS_REF/REPO/SRC`; new `bootstrap.sh engines` (tools + engines only, for images).
* Tests: `tests/test_runner_node.py`, fixtures in `tests/fixtures/runner-node/` (real lockfiles: npm, yarn 1,
  pnpm 10); `tests/conftest.py` keeps the fixtures out of the engine suite's collection (they were collected and
  broke it before the fix).
* `.github/workflows/fenvix-demo-node-hosted.yml` (item 6), `docs/RUNNER-PROTOTYPE.md` (Node section),
  `sessions/2026-11-18-runner-node/image.patch` (item 5).

## Measurements (MEASURED in this container unless said otherwise)

* `tests/test_runner_node.py`: **9 passed** with detjs from the bootstrapped `$FENVIX_HOME` on Node 26.13.1 (jobs'
  view: `PATH=$FENVIX_HOME/bin:$FENVIX_HOME/node/bin`), also 7/7 on Node 22.23.5 before the last two were added;
  `tests/test_runner_wrapper.py` (Python path) 2 passed; whole engine suite `pytest tests`: **120 passed,
  6 skipped** (4m54s).
* Vitest fixture (npm): 8 tests (passed 5, failed 1, skipped 1, todo 1); `failed: []`, flaky
  `test/registry.test.js::registry::starts empty`, `replay = detjs vitest run --det test/registry.test.js`
  (fails again), `minimise = ... -t '^(registry registers a plugin|registry starts empty)$'` (fails again), alone it
  passes; two jobs give identical outcomes and fingerprints. Same with Vitest 4.1.5.
* Jest fixture (yarn 1): 6 tests; `failed = [a real failure (fails alone too)]`, flaky
  `__tests__/cache.test.js::cache::starts empty`, replay `detjs jest --det --runTestsByPath
  __tests__/cache.test.js` (fails again), minimal pair with `stores a value`.
* Mixed fixture: Python job (`--lang python`) 2 tests, Node job (`--lang node`, `corepack pnpm install
  --frozen-lockfile`) 2 tests; identical key sets; separate caches; auto-detection refuses the mixed root.
* `--det-cache` with the current detjs: not passed, outcomes and fingerprints identical to a run without it; with
  a stub detjs that lists `--det-cache` in `--det-help`: `--det-cache=<cache dir>` passed, `cache_status: on`.
* unjs/ufo @ `f06c800d` (Vitest 4.1.5, pnpm 10.33.2 via corepack), Node 26.13.1: **491 tests passed** (489 + 2
  type-check tasks from `--typecheck`), 4.8 s wall (2.7 s without `--typecheck`).
* Bootstrap (`FENVIX_LANGS=node bootstrap.sh engines`, empty `$FENVIX_HOME`): Node download + checksum OK,
  corepack 0.36.0, detjs fetched at `8e9209b` and built (Rust ~15 s warm), `detjs --det-help` OK.
* Image component: all its phases (build, validate, test) run here with parameters substituted and scratch paths
  instead of `/opt`: passed; the test phase reports the fixture's flaky test with `replay_reproduces: true`.

## Item 6: hosted run

Workflow `fenvix-demo-node-hosted` (same pattern as `fenvix-demo-hosted`: one job builds the engines with
`runner/bootstrap.sh engines`, the test jobs take them as an artifact): `ufo` (unjs/ufo @ `f06c800d`, public
Vitest project, setup-node `lts/*`, pnpm via corepack, `fenvix-run --lang node`, summary checked), `mixed-python` and
`mixed-node` (the mixed fixture, one job per language), `fixtures` (Vitest and Jest fixtures; every replay command
of the summaries is run and must fail the flaky test again; then `tests/test_runner_node.py` and
`tests/test_runner_wrapper.py`).

Pushed at 16:20Z: [run 44346012832](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44346012832).
It has been **queued** since then: every run of the repository created after ~16:20Z is queued (go-tests,
go-harness, jvm-tests, node-cache-proof), while the l2-browser-r3 runs started at 14:47Z hold the account's hosted
machines (their `experiment` jobs run for hours). The run got a machine at 17:04Z: the **`engines` job passed** (job 134948472904: `runner/bootstrap.sh engines` with
`FENVIX_LANGS="python node"` on ubuntu-latest in 48 s: Node 26.13.1 checksum, corepack, detjs fetched at `8e9209b`
and built, detpy wheel; artifact `fenvix-engines` kept 3 days). The four test jobs (`ufo`, `mixed-python`,
`mixed-node`, `fixtures`) were created at 17:04:58Z and were still **queued** at 17:45Z for the same reason. They run
when machines free (the artifact outlives the wait); nothing needs to be re-pushed. Their results are on the run page. Until it has run, item 6 is not shown on GitHub; what it runs was run in this
container (Measurements: bootstrap, ufo 491 passed, mixed, fixtures, wrapper tests).

## Limits and open points

* **fenvix-app not read.** Fetching `Mircoguidetti/fenvix-app` (git clone, api.github.com) was refused in this
  session (the proxy returned 403, then the action was blocked). `image.patch` therefore adds a new, self-contained
  Image Builder component (`infra/imagebuilder/components/fenvix-node.yml`) and does **not** contain the hunk that
  references it from the recipe: its header gives that entry for CloudFormation, Terraform and CDK, and lists the
  three defaults to check (component directory, `FenvixHome=/opt/fenvix`, `RunnerEnvFile=/opt/actions-runner/.env`;
  base image with apt-get and python3). The session editing `claude/github-app` should apply it there.
* **No Node cache with proof yet**: every Node test runs in every job (`reused_with_proof: 0`); the wiring is in
  place and tested as a no-op, the first real use comes with `claude/node-cache-proof`.
* detjs pinned at `claude/node-l0` `8e9209b` (bootstrap `FENVIX_DETJS_REF`, image `EngineCommit` pins this
  branch's `5fffd75`, which carries that ref). detjs was built and measured on Node 22 by the Node L0 work; here it
  ran on Node 26.13.1 for the fixtures and ufo without a difference, a wider Node 26 check (the harness projects) is
  not done.
* Replay commands use `detjs` on PATH (our machines: `$FENVIX_HOME/bin/detjs`); a developer elsewhere needs detjs
  installed, as the Python replay needs detpy.
* The `test` script parsing is deliberately narrow (a plain runner call in an `&&` chain); scripts with env
  assignments or wrappers (`cross-env`, `turbo`) give no flags, `--` extra args then do it.
* Bun and Yarn PnP projects: install commands are there, not tested. Vitest workspaces / Jest multi-project: ids
  from detjs as is (detjs limit J9: a file in two projects shares ids).
* The flaky search costs at most 1 + 1 + 8 short runs per flaky test (file-scoped), plus one whole-suite run only
  when the state comes from another file; bounded by `--max-reruns` (20 failures).
