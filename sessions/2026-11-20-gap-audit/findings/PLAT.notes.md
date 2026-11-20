# PLAT notes: platforms, CI systems, GitHub Action, distribution, MCP, runner wrapper

Agent PLAT, audit P-036. Audited: engine `claude/release-1` at 529c160 (worktree /home/user/audit/engine), fenvix-app
`main` at ce69a6b, fenvix-landing and fenvix-docs `main`, brain `main`. Stopped early on the coordinator's budget
message: sections 1-5 and 7-8 of the task are covered to the depth below, section 6 partly. See "Not covered".

Gaps: `/home/user/audit/findings/PLAT.gaps.jsonl` (174 entries: 7 WRONG-RESULT, 76 BLOCKS-USE, 79 DEGRADES, 12 MINOR;
118 BUILD-MVP, 51 BUILD-LATER, 5 DECIDE; 98 RAN, 71 READ, 5 DOC). Raw outputs: `/home/user/audit/findings/PLAT.evidence/`.
Sources of the entries (regenerate with `gen.py`): `/home/user/audit/work/PLAT/gaps/part0*.py`.

**Caveat on line numbers.** In PLAT-001..088 the `file:line` references were checked with `grep -n`. In PLAT-089..174
(Distribution, CLI, Naming, Licensing, Supply chain, State between jobs, Runner wrapper, MCP, Engine CI) the file is
right and the quoted text is real, but line numbers for `runner/fenvix-run`, `runner/bootstrap.sh`, `release/fenvix`,
`python/detpy/cli.py`, `release-1.yml`, `fenvix-demo*.yml`, fenvix-app `install.sh`, `cache.ts`, `launcher.ts`,
`data-contract.md` were written from a reading without line numbers and can be off by up to about 15 lines. Search the
quoted text.

## 1. Platform × component

`ok` = ran here or in the release gate; `fails` = ran and failed (RAN); `none` = no artifact/never built (READ);
`refused` = the code exits with an error; `unknown` = never executed anywhere. Gap ids in brackets.

| platform | detpy wheel | detjs addon | fenvix-go | agent jar (JNI lib) | fenvix-skip | `fenvix` + install-image.sh | runner/ |
|---|---|---|---|---|---|---|---|
| Linux x86_64, glibc >= 2.39 (Ubuntu 24.04, Debian 13) | ok (gate; but head run failed 1 test, PLAT-165) | ok | ok (head run: 1 Go test fails on Go 1.26) | ok | ok | ok (needs python3, checkout, npm) | pytest only [PLAT-144] |
| Linux x86_64, glibc 2.34-2.38 (Ubuntu 22.04, Debian 12, RHEL 9, Amazon Linux 2023) | loads (needs 2.34) | loads | **fails** GLIBC_2.39 [PLAT-048] | loads | ok | not tested | not tested |
| Linux x86_64, glibc < 2.34 (Ubuntu 20.04, Debian 11, RHEL 8, Amazon Linux 2, CentOS 7) | **fails** [PLAT-046] | **fails** [PLAT-047] | **fails** | **fails** [PLAT-049] | **fails** [PLAT-050] | - | - |
| Linux x86_64 musl (Alpine) | installs, **import fails** [PLAT-054] | **fails** [PLAT-055] | **fails** [PLAT-056] | fails (glibc lib) [PLAT-057] | **fails** | fails without python3 | - |
| Linux arm64 (ubuntu-24.04-arm, Graviton, Apple-silicon Docker) | builds in a non-gate job, 4 test files, no artifact [PLAT-058] | none [PLAT-059] | none [PLAT-060] | none: x86-64 `.so` only [PLAT-061] | tests pass, no artifact [PLAT-062] | copies x64 addon by name | linux-x64 runner only [PLAT-154] |
| macOS arm64 | unknown: job never got a runner [PLAT-064]; degraded by code [PLAT-067..074] | unknown; cache keys no native libs [PLAT-072] | refused [PLAT-065] | none: `.so` name fixed [PLAT-066] | unknown | bash + python: unknown | Linux only |
| macOS Intel | unknown, no job [PLAT-075] | unknown | refused | none | unknown | unknown | - |
| Windows x86_64 / arm64 | cannot compile [PLAT-076, 080] | cannot compile | refused [PLAT-078] | none | cannot compile | bash scripts [PLAT-079] | - |
| WSL2 | unknown (doc claims it works as a runner host) [PLAT-081] | unknown | unknown | unknown | unknown | unknown | unknown |

Containers (RAN on a local Docker daemon, kernel 6.18):

| condition | `strace -f` | ASLR switch (`personality(ADDR_NO_RANDOMIZE)`) |
|---|---|---|
| docker run, default seccomp, root | works | **refused** (EPERM) [PLAT-082] |
| `--cap-drop ALL` | works | refused |
| `--user 1000:1000` | works | refused |
| `--security-opt no-new-privileges` | works | refused |
| `--security-opt seccomp=unconfined` | works | allowed |

Other container findings: service container by hostname blocked under `--det` [PLAT-083]; `--det-allow-host=<name>`
does not allow it [PLAT-084]; no C compiler in slim images, so tests that start a process are never cached [PLAT-051].

Linux/Unix-only code paths and what happens elsewhere:

| feature | where | elsewhere |
|---|---|---|
| ASLR off | `crates/detpy-py/src/reexec.rs:58-78` | returns false, run continues, header says "ASLR on" (no warning) |
| child following (strace + LD_PRELOAD shim built with cc) | `python/detpy/follow.py:157-215` | tests that start a process: "not cacheable: subprocess" |
| `--det-isolate` (fork) | `python/detpy/isolate.py:39-40`, `plugin.py:664-673` | silently off, one "adjustments" line |
| dlopen tracking (`/proc/self/maps`) | `python/detpy/distid.py:406-414` | empty text: not an input |
| runtime identity native closure (ELF) | `python/detpy/runtime_id.py:129-135,715` | "the OS release stands for the system libraries" |
| sockets / live children (`/proc/self/fd`, `/proc/self/net/*`, `/proc/self/task`) | `crates/detpy-py/src/sysmon.rs:344-372`, `sockcap.rs`, `clock.rs:206-216` | nothing found |
| Node runtime identity (`/proc/cpuinfo`, `/proc/self/maps`) | `node/src/cache/runtime-id.js:37-53` | `<arch>:unknown`, `[]` |
| Go | `go/cmd/fenvix-go/test.go:281-283` | error "only linux is supported" |
| Go pid virtualisation | `go/cmd/fenvix-go/test.go:390` | needs root + `unshare`; else not controlled (said at start) |
| JVM native core | `Agent.java:54,76,81`, `jvm/build.sh:13` | `libfenvix_jvm.so` hard-coded (no dylib/dll, no arch) |
| whole core crate | `crates/detpy-core/src/reexec.rs:14` | `use std::os::unix` without cfg: no Windows build of anything |

## 2. CI system × support

| CI system | recipe/template | cache persistence recipe | PR/MR comment | CI metadata in runs | status |
|---|---|---|---|---|---|
| GitHub Actions (our machines, `runs-on: fenvix`) | onboarding PR (app) | machine directory + private cache service | yes (app), pytest only | none in the engine | partial: engine not injected into the customer's step [PLAT-018], image lacks tools [PLAT-146] |
| GitHub Actions (any runner, via an Action) | **no action.yml** [PLAT-001] | none [PLAT-005] | none [PLAT-008] | none | missing [PLAT-001..017] |
| GitLab CI | none | none | none | none | missing [PLAT-019] |
| CircleCI | none | none | none | none | missing [PLAT-020] |
| Buildkite | none | none | none | none | missing [PLAT-021] |
| Jenkins | none | none | none | none | missing [PLAT-022] |
| Azure Pipelines | none | none | none | none | missing [PLAT-023] |
| Bitbucket Pipelines | none | none | none | none | missing [PLAT-024] |
| Travis CI | none | none | none | none | missing [PLAT-025] |
| TeamCity | none | none | none | none | missing [PLAT-026] |
| Drone / Woodpecker | none | none | none | none | missing [PLAT-027] |
| AWS CodeBuild | none | none | none | none | missing [PLAT-028] |
| Google Cloud Build | none | none | none | none | missing [PLAT-029] |
| Harness CI | none | none | none | none | missing [PLAT-030] |
| Semaphore | none | none | none | none | missing [PLAT-031] |

Runner vendors: every engine workflow runs on `ubuntu-latest` (89 jobs), plus one non-gate `macos-14` /
`ubuntu-24.04-arm` job and the self-hosted demo. Blacksmith, BuildPulse, Depot, Namespace, Ubicloud, WarpBuild, RunsOn,
Actuated: never run. Block 4 exit numbers ("zero-config install under 5 minutes on 10 forks", "same result on three
runner vendors"): **never measured** [PLAT-037, PLAT-038]. Hard-coded GitHub: only in `runner/` (`GITHUB_STEP_SUMMARY`,
`GITHUB_ENV`, `RUNNER_TEMP`, run link); the four language shells read no CI variable of any vendor [PLAT-033].

## 3. First use as a stranger, per language (RAN in clean containers)

| language | documented steps (README / docs) | result |
|---|---|---|
| Python | `pip install maturin` + `maturin develop --release` from a clone (README.md:18-23) | python:3.12-slim: "rustc, the rust compiler, is not installed". The natural `pip install detpy` installs an **unrelated PyPI project** (DetPy 2.0.0); `pytest --det` then says "unrecognized arguments" [PLAT-089..091] |
| Node/TS | `cd node && npm run build` (README.md) | node:22-slim: `npm install detjs` E404; build fails (no cargo); package is `"private": true` [PLAT-092] |
| Go | `cargo build -p fenvix-go --release; cd go && go build ./cmd/fenvix-go` (docs/GO.md:8-9) | golang:1.24: "cargo: not found"; go build: "cannot find .../libfenvix_go.a"; `go install ...@latest`: "no matching versions" [PLAT-094] |
| JVM | `jvm/build.sh` (docs/JVM.md:10) | eclipse-temurin:21: "cargo: command not found"; `fenvix jvm run` fails: "env: 'python3': No such file or directory" [PLAT-095, 096] |
| any, prebuilt | `release/install-image.sh DIST` with CI artifact `engine-linux-x64` | needs a GitHub login for the artifact, an engine checkout, python3, pip, npm, network; x86_64 + glibc >= 2.34 (2.39 for Go) only [PLAT-098, 101] |

Registries (RAN, 2026-11-20): PyPI `detpy` = someone else's; PyPI `fenvix`, `pytest-fenvix`, `pytest-det` 404; npm
`detjs`, `fenvix`, `@fenvix/detjs`, `@fenvix/cli`, `fenvix-cli` 404; crates.io `detpy-core`, `fenvix`, `fenvix-skip`,
`fenvix-go` do not exist; git tags: none; default branch `claude/gracious-rubin-eyswxd` (2026-11-17).

Cold start MEASURED (noisy, shared 4-CPU machine, python:3.12-slim + pytest + xdist): first `pytest --det` 15.7 s
(13.1 s bytecode precompile), second 2.5 s, plain pytest 1.3 s [PLAT-132].

glibc floor MEASURED (`objdump -T`): wheel 2.34, addon 2.34, JNI lib 2.34, fenvix-skip 2.34, **fenvix-go 2.39**.

## 4. Not covered (for another session)

Numbering follows the task brief.

- **1 (GitHub Action):** covered. Not done: a design check of GitHub OIDC against the service's auth code
  (`github-app/src/auth.ts` was read only to the first 60 lines).
- **2 (other CI, vendors):** covered by repository search; no run on any other CI or vendor (none possible here).
  Not done: `github-app/src/results/detect.ts` (the app's own language/test-runner detection) was not read.
- **3 (platforms):** covered for Linux x86_64/musl/old glibc/containers (RAN) and macOS/Windows/arm64 (READ). Not done:
  rootless Docker/Podman, Kubernetes pod with RuntimeDefault (reasoned from the Docker result only), Docker-in-Docker
  and testcontainers under `--det-cache` (not run), cross-compile checks (`rustup target list --installed` =
  x86_64-unknown-linux-gnu only), Python/Node version matrix (left to the language agents), `noexec /tmp` for the
  agent's `/tmp/fenvix-jvm` extraction, JVM agent on a musl JDK (inferred from `ldd`, not run).
- **4 (distribution, first use):** covered. Not done: `cargo audit` (the install was stopped at the budget message;
  the OSV API is blocked by the proxy), `fenvix detect` on a real mixed public repository (synthetic trees only),
  exit-code table of every CLI, offline use (not run), PEP 668 behaviour of `install-image.sh` on a system Python,
  licences of the Node dev dependencies and Maven dependencies, fenvix-docs content (the docs site was not read; only
  fenvix-landing `content/` and two pages).
- **5 (state between jobs):** covered from code and docs plus one measurement. Not done: reading
  `infra/github-app/lib/cache/fenvix_cache_auth.py` (per-job token auth), the warm-cache install code
  (`github-app/src/warmup/`), multi-tenant isolation tests of the cache service, compatibility run of a release-1
  client against the vendored a20b93d service.
- **6 (runner wrapper, `runs-on: fenvix`):** partly. Read fully: `runner/fenvix-run`, `bootstrap.sh`,
  `ci-project-env.sh`, `docs/RUNNER-PROTOTYPE.md`, the demo workflows, app `install.sh`, `launcher.ts` (top),
  `cache.ts`. **Not read:** `runner/local-demo.sh`, `local-shared-demo.sh`, `shared-cache-compare`,
  `tests/test_runner_wrapper.py`, app `lib/runner/files/*` other than `install.sh`, `fenvix-job-started`,
  `fenvix-job-completed`; `docs/DEPLOY-AWS.md` beyond greps. **No entries yet for:** secrets handling on our machines,
  job logs, artifacts and caching actions (`actions/cache`, `setup-*` tool cache) on the fenvix image, job time
  limits, isolation between consecutive jobs in demo mode (one shared machine), multi-language detection in the
  wrapper vs the app.
- **7 (MCP / agents):** covered. Not done: fenvix-docs grep for agent claims; the app branches `public-api`,
  `public-api-usage`, `ui-api-keys` (not on main) were not read, so an API-key design may exist there.
- **8 (engine CI):** covered. Not done: reading each of the 27 other workflows to list which of their checks have no
  equivalent in `release-1.yml`; fenvix-app's own `test.yml` / `deploy.yml`.
- **Matrix file:** the task did not assign matrix cells to PLAT; none written.

## 5. Could not check

- macOS, Windows, real arm64: no such machine; all from code and CI config. The lead's Actions probe should settle
  whether the wheel builds on macOS.
- Whether a release-1 run ever becomes green: observed at 2026-11-20 about 08:45 UTC; later reruns may differ.
- ptrace in hardened sandboxes (gVisor, Bitbucket Pipelines, CircleCI Docker executor, Kubernetes with custom
  profiles): only default Docker on kernel 6.18 was tried.
- `apt-get` inside containers failed through the proxy, so strace was copied into the containers from the host rather
  than installed; the "no strace on the image" case is the unmodified `python:3.12-slim`.
- In my container test a test that starts a subprocess stayed "not cacheable: subprocess" even with strace present;
  on the host it was cached. The difference found is the missing C compiler [PLAT-051]; other causes were not excluded.
- Third-party advisories for the 109 crates in Cargo.lock: `cargo audit` not installed, OSV API refused by the proxy
  (403).
- `detpy repro <passing test> --seed fixed` did not return within 60 s on a 3-test project (killed by timeout); not
  investigated (Python agent's area).
- PLAT-070, 071, 072, 073 (macOS wrong-reuse risks) are READ: the input is provably not captured off Linux; a wrong
  reuse was not demonstrated.

## 6. Contradictions and claims found false

1. docs/RELEASE-1.md names the wheel `...manylinux_*_x86_64.whl`; the build produces `linux_x86_64` (not uploadable
   to PyPI, glibc 2.34 floor).
2. docs/RELEASE-1.md "Gates: a release candidate is the commit whose release-1 run has every Linux x86_64 job green":
   no such run exists (11 runs, all cancelled; head has 3 failed gate jobs). The release report's result table holds
   `RESULT_*` placeholders.
3. docs/GO.md "Linux only by design" and docs/RELEASE-1.md repeat it; no DECISIONS entry records that exclusion.
4. PRODUCT.md / ROADMAP Block 4 promise a GitHub Action on any runner and an MCP server; neither exists in any branch.
   Landing and quickstart present only the GitHub App + `runs-on: fenvix`.
5. Landing quickstart: "FENVIX opens a pull request that changes one line ... Results come back as GitHub checks".
   fenvix-app's own report: a job that runs plain `pytest` on our machine is not run in the engine and gets "No fenvix
   summary" (docs/REPORT-aws-deploy.md:464).
6. Landing commands page documents an "API for coding agents" with API keys and bundle download; the API on main has
   neither. It also shows bundles at `.fenvix/defects/<id>/order.txt`; the engine writes `.detpy/repro`.
7. The service's runner image and cache service are pinned to engine commit a20b93d (2026-11-18), which is not an
   ancestor of release-1: what is deployed is not what was audited.
8. Manifests declare MIT while DECISIONS say the engine must not be copyable and the repository goes private.
9. `fenvix --help` and docs/RELEASE-1.md name runners (`zope`, `bun`, `deno`) the CLIs do not accept
   (`zope-testrunner`, `bun-test`, `deno-test`).
10. The nightly real-clock workflow's `schedule` can never fire (not on the default branch); DECISIONS 2026-11-19 relies
    on that nightly run for Python, Node and Go, and only Go has the option.

## 7. Evidence appendix (commands and trimmed outputs)

Files in `/home/user/audit/findings/PLAT.evidence/`: `ev-docker-aslr.txt` (PLAT-082), `ev-docker-cache.txt`
(PLAT-051, PLAT-131), `ev-service-container.txt` (PLAT-083, 084), `ev-precompile.txt` (PLAT-132),
`ev-firstuse-{python,node,go,jvm}.txt` (PLAT-089..096), `ev-release1-head-failed.log` (PLAT-165).

```
# PLAT-001
find engine fenvix-app fenvix-docs fenvix-landing -name action.yml -o -name action.yaml      => (nothing)
for b in <62 origin branches>: git ls-tree -r --name-only $b | grep -E '(^|/)action\.ya?ml$' => (nothing)
git tag => (nothing);  git ls-remote --tags origin => (nothing)
git ls-remote --symref origin HEAD => ref: refs/heads/claude/gracious-rubin-eyswxd

# PLAT-046..050 (glibc floor)
objdump -T <file> | grep -o 'GLIBC_[0-9.]*' | sort -V | tail -1
  _core.abi3.so GLIBC_2.34 | detjs.linux-x64.node GLIBC_2.34 | fenvix-go GLIBC_2.39 | fenvix-skip GLIBC_2.34 | libfenvix_jvm.so GLIBC_2.34
docker run ubuntu:22.04 (glibc 2.35):  fenvix-go: version `GLIBC_2.39' not found
docker run amazonlinux:2023 (2.34):    fenvix-go: version `GLIBC_2.39' not found
docker run debian:11-slim (2.31), ubuntu:20.04 (2.31), amazonlinux:2 (2.26): every binary: version `GLIBC_2.3x' not found

# PLAT-054..057 (Alpine)
python:3.12-alpine: pip install detpy-0.1.0-cp39-abi3-linux_x86_64.whl => Successfully installed detpy-0.1.0
  python -c "import detpy" => ImportError: Error loading shared library libgcc_s.so.1 ... (needed by .../detpy/_core.abi3.so)
node:22-alpine: Error: Error loading shared library ld-linux-x86-64.so.2 ... (needed by /opt/fenvix/node/detjs.linux-x64.node)
alpine:3: /opt/fenvix/bin/fenvix-go: not found | fenvix-skip: not found | fenvix: env: can't execute 'python3'

# PLAT-082 (default Docker profile)
setarch x86_64 -R true => setarch: failed to set personality to x86_64: Operation not permitted
pytest --det => detpy: PYTHONHASHSEED=0 (hash seed fixed; not applied: aslr (already re-executed)); ASLR on; network=block; sleep=virtual
trace meta: {'aslr_disabled': False, 'platform': 'linux', ...}

# PLAT-083/084
pytest            => 1 passed
pytest --det      => socket.gaierror: [Errno -2] detpy: DNS lookup of 'db' blocked (Level 0 closes the network)
pytest --det --det-allow-host=db => detpy.network.NetworkBlockedError: detpy: network access to 172.18.0.2:8000 blocked ...

# PLAT-089
curl pypi.org/pypi/detpy/json => 2.0.0 | DetPy (Differential Evolution Tools) ... | github.com/Blazej-Zielinski/detpy
clean venv: pip install detpy pytest; python -m pytest --det => error: unrecognized arguments: --det

# PLAT-108..113 (fenvix CLI)
fenvix --version => fenvix: unknown command '--version' (fenvix --help)   rc=2
fenvix python-runner zope --det => detpy: error: argument cmd: invalid choice: 'zope' ...   rc=2
fenvix detect mono (api/pyproject.toml, web/package.json, svc/go/go.mod) => (empty) rc=0
fenvix detect <dir with requirements.txt Pipfile deno.json go.work build.sbt ...> => (empty) rc=0
fenvix detect mono/nope => FileNotFoundError ... rc=1
fenvix version => fenvix release-1 / detpy 0.1.0 / detjs 0.1.0 / fenvix-go present / fenvix-skip present / fenvix-agent.jar present

# PLAT-145 (deployed engine is not release-1)
fenvix-app infra/github-app/cdk.json:58  "engineCliCommit": "a20b93d7f840b23f71c73c03efdaee3d6a233252"
git branch -r --contains a20b93d => all-runners, audit-reruns, node-cache-proof, review-r008d, ..., shared-cache (not release-1)
git merge-base --is-ancestor a20b93d origin/claude/release-1 => NOT ancestor

# PLAT-165 (release gate)
gh run list --workflow release-1.yml => 11 runs, all conclusion "cancelled"
gh run view 44700422692 (head 529c160): build success | node success | jvm 8/11/17/21 success | smoke x4 success |
  other-os ubuntu-24.04-arm success | other-os macos-14 cancelled | python 3.12 failure | python 3.13 failure | go failure
  python: FAILED tests/test_proofcache_follow.py::test_child_own_temporary_files_are_not_inputs (1 failed, 951 passed, 74 skipped)
  go: --- FAIL: TestR025b_D3_UncontrolledEntropy
```

Environment variables per component (for PLAT-120): Python `DETPY_BLOCKED_PLUGINS, DETPY_CACHE_DISTS,
DETPY_CACHE_LINES, DETPY_CACHE_SHARED, DETPY_PLAN_CHUNK_DIV, DETPY_PRECOMPILE_S, DETPY_PYC_CACHE, DETPY_REEXEC,
DETPY_REWRITE_CACHE, DETPY_REWRITE_OWN, DETPY_VERBOSE, DETPY_XDIST_ENV, FENVIX_CACHE_{ALLOW_HTTP,LOCAL,REPORT,TOKEN,
TOKEN_FD,TOKEN_FILE}, FENVIX_RUNTIME_{ISA,MEMO}`; Node `DETJS_*` (60+ names: DETJS_SEED, DETJS_EPOCH, DETJS_CACHE,
DETJS_NATIVE, DETJS_DISABLE, ...); Go `FENVIX_GO_{CACHE,DET,FDS,SESSION,CLOCK_*}`; JVM `FENVIX_SKIP_BIN`; runner
`FENVIX_{HOME,CACHE_ROOT,WHEEL_DIR,PYTHON,PY,REPO_URL,RUNNER_NAME,RUNNER_TOKEN,RUNNER_TOKEN_FILE,JITCONFIG,EPHEMERAL}`.

## 8. Housekeeping

A private Docker daemon was started for the container tests (socket and data under
`/home/user/audit/work/PLAT/dockerd/`) and stopped at the end; pulled images remain in that data directory (about
4 GB) and can be deleted with the folder. A background `cargo install cargo-audit` into the scratch folder was killed
unfinished. Nothing was written to any audited repository, nothing was pushed or posted.
