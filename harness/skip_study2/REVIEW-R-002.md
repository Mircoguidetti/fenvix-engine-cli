FIX 3

# R-002 review: skip study 2, REPORT.md version 2 (fenvix-engine-cli `claude/loving-maxwell-58mv2w` @ 6be49f6)

I am the reviewer. I worked in a read-only worktree (`<scratch>/rv-skip2`) and pushed nothing. Reviewer scripts and tests are in `<scratch>/review-R-002/`. `<scratch>` is `/tmp/claude-0/-home-user/50f6213c-868e-5784-89fb-56a198be63cf/scratchpad`.

Labels:
- **MEASURED**: by me.
- **DECLARED**: from the delivery's files.

## What I checked

| # | check | result |
|---|---|---|
| 1a | How a skip is "verified" | **OK.** `walk.py` L607 draws a Bernoulli(`verify`) sample over *all* closure-skippable units at every transition. `verify` is 0.08-0.15 per spec. Go draws a random sample of go-cache hits plus every hit whose runtime read changed. The draw does not depend on the unit, so it is unbiased. The fresh run is traced (strace). A mismatch gets 2 plain reruns. |
| 1b | My own fresh reruns of skipped units, compared with the reused outcome | **771 of 772 match; 1 differs** (MEASURED). See the reruns table below. |
| 2 | The two mismatch verdicts | **Plausible, but the evidence is hand-written.** The two `results/s1/recheck/*-local.json` files hold counts and per-run summaries, not raw logs. The GitHub Actions re-check is still queued (DECLARED). I did not re-run Home Assistant (too heavy). The rule "a cached failure is never reused" is stated. The skip shares do **not** apply it, but the effect is negligible (MEASURED: at most 1 failing record per commit in setting 1). |
| 3 | Dependency capture soundness | **3 holes proven**: errors 1-3 below. Two method claims are false: the capture records no environment variables, and it records no interpreter, stdlib or shared libraries. |
| 4 | The numbers | **Recomputation matches; one caveat.** Shares are per commit and then median/mean over commits. Commits that invalidate everything are included. `aggregate.py --md` on the committed data reproduces every setting-1 and setting-2 number in the report (MEASURED). The HA sample is a hash-random draw of files, so it is unbiased in expectation. But on agent PRs it mostly leaves out the PR's own integration tests. |
| 5 | Customer-facing claims | Several need fixing (notes below). The main one: the Go "with proof" numbers are not a proof. |

**My fresh reruns of skipped units** (MEASURED). These are units skipped and not verified by the walk. I re-ran them at the same commit and compared with the cached outcome. Every cached outcome was a pass.

| walk | commit | units re-run | match |
|---|---|---:|---|
| vue-core | last (i=50, cbd95955) | 153 | 153 |
| vue-core | random (i=8, a14aa0bd) | 82 | 82 |
| docusaurus | random (i=6, b3c49fe9) | 181 | 181 |
| docusaurus | random (i=8, e02ab433) | 180 | 180 |
| prometheus | last (b2a60249) | 69 packages | 69 |
| terraform | last (b3fb138b) | 107 packages | 106 |

- **Random commits:** chosen with seed "R-002" by `review-R-002/scripts/pick.py`. At each chosen commit I re-ran every unverified skipped unit.
- **Docusaurus (i=6), 3 failures under HOME=/root.** 3 of the 181 failed while HOME was /root (env var dependency, see error 2). All 3 pass with a neutral HOME, which is how 181 match.
- **Terraform:** the 1 package that differs is `internal/cloud`, which fails because it needs network access (error 3).

## Proven errors

### 1. A file opened read-write is dropped from the dependencies, which gives a wrong hit

**Cause.** `strace_deps.parse` treats any open with `O_RDWR`, `O_CREAT`, `O_APPEND` or `O_TRUNC` as a write. It then removes that path from `reads`, `exists` and `missing`. sqlite opens a database `O_RDWR` even for a SELECT, and so do `open(...,"r+")` and numpy memmap. A checked-in fixture read this way is therefore not a dependency.

**Reproduction.** I ran their own `walk.py` on a 2-commit demo repo (`review-R-002/demo/`):
- commit c1 changes `tests/fixture.db`;
- `closure` and every other rule skip `tests/test_db.py`;
- the walker's own verification then records `same: False, rerun_matches_fresh: 2, rerun_matches_cache: 0`, which is a wrong hit by the report's definition (MEASURED);
- the unit that does not read the fixture was re-run (`exists:data`).

**Failing test:** `review-R-002/test_r002_capture.py::test_sqlite_fixture_change_is_a_dependency`. Run it with `WT=<worktree> python -m pytest test_r002_capture.py`.

### 2. Environment variables are not captured, although REPORT §1 says "every environment variable it read"

**Cause.** Nothing records environment variables: strace cannot see `getenv`, and neither `pyhooks` nor `decide()` reads the environment.

**Failing test:** `test_r002_capture.py::test_environment_variable_is_a_dependency`. The test reads `R002_FLAG`; the test is run with it set to 1; `decide()` still returns a skip, and the fresh run fails.

**Real-repo instance (MEASURED).** Three docusaurus files skipped at b3c49fe9 depend on `$HOME`: `docusaurus-glob/.../globUtils.test.ts`, `plugin-content-docs/.../index.test.ts` and `docs.test.ts`. Their snapshots render a fixture path `/root/_docs` as `<HOME_DIR>` when HOME=/root.
- They pass with HOME=/home/runner-like paths and fail with HOME=/root, for example in a root container.
- A shared cache between those two environments reuses a wrong PASS.
- The study ran in one environment, so its own numbers are not affected. The product claim ("nothing it depends on changed") is.

**Related mislabel.** `kind_of()` labels any path outside the repo or under node_modules as `env`. The docusaurus "invalidate all … read:env 1" (i=50, 4c4ec4aa, a `package.json` bump followed by a reinstall) is a changed node_modules file, not "an environment variable every test reads" as REPORT §2 says.

### 3. The Go rules have no network guard: a PASS is reused for a test that needs an external service

**Cause.**
- `walk_go` records `net` per package but never uses it, in neither `go-cache` nor Go `closure`.
- The pytest/vitest `decide()` does refuse to skip units that connect to non-loopback addresses.
- Terraform `internal/cloud` was a go-cache skip (cached PASS, recorded at i=41) at b3fb138b.

**What happens on a fresh run.** It fails deterministically (2 of 2 reruns, MEASURED). `TestRunEventWarningsAll` panics because `tfe.NewClient` (`backend_run_warning_test.go:91`) calls `getRawAPIMetadata()` (go-tfe v1.112.0, `tfe.go:443`) against app.terraform.io. The error is discarded, so `client` is nil, and the test dereferences it at line 80.

**Reproduction:** `review-R-002/go_network_repro.sh <terraform checkout>`. Run it where app.terraform.io is unreachable; here the proxy answers 403.

**Scale.** 14 of 125 terraform packages and 30 of 90 prometheus packages make `connect()` calls. They account for 540 and 1,310 go-cache skip events (MEASURED from `unit_info.net`). The connections include loopback, and the data cannot separate the two.

## Notes

These are not counted in the FIX total, but should be fixed before any customer-facing use.

### Go labelled as proof
The headline "time skipped **with proof**" for Go uses `go-cache`: terraform 72%/61%, prometheus 56%/52%, and setting 2 at 78%/56% (DECLARED).
- By the report's own definition the proof rule is Go `closure`: terraform 35%/31% (DECLARED, reproduced).
- The terraform walk itself found 222 go-cache hits whose runtime reads had changed (DECLARED), which means the go-cache key missed real inputs.
- Its "0 wrong" is empirical, not proof. Error 3 is a case where it is wrong.
- Relabel these numbers "go test cache (no proof)".

### Method claims that are false
"strace: … interpreter, shared libraries" is not true:
- the roots are `src` plus `venv` (plus spec roots, and no spec sets any);
- in my run, a pytest record held 122 reads: 1 in src, 121 in the venv, and 0 from the interpreter, stdlib or libs (MEASURED, `scripts/roots_check.py`);
- the uv venv's python resolves outside the venv, so the stdlib is outside the roots too;
- the Node binary is not in the vitest roots either.

So a Python, Node, tzdata or openssl change on the runner image is invisible to the rule.

Also excluded:
- `.git/` reads (`SKIP_PARTS`);
- wall-clock time, which is not a dependency at all: tests that start failing on a date are reused as passes.

### Verification only covers `closure` skips
The `func+guard`, `func` and `~cfg` rows print the same "2573 (0, 0)". But the skips those rules add beyond `closure` were never compared, even though they were run fresh as closure-must units and their outcomes were not kept.
- The `func` row ("coverage-only, NOT a proof") shows "0 wrong", which is unsupported.
- Show "n/a" for those rows, or compare them.

### The Home Assistant 12% sample on agent PRs
On most HA agent pushes the PR's own integration tests are outside the sample. Examples (MEASURED from `r6/agent`):
- 172680 (lg_tv_rs232): pushes 2-3 changed files, 0 units re-run;
- 190901 (telldus): push 2 changed 23 files, 0 units re-run;
- 191160 (omada): push 3, 0 units re-run.

Effects:
- **Median.** "Copilot on HA 100% median" is partly a sampling artifact. In the full suite those integration tests would re-run. The share effect is probably small (ESTIMATED under about 2 points), but a 100% median cannot hold.
- **Setting 1 representativeness.** For setting 1 the per-file hash sample is unbiased in expectation. Per-commit closure shares (MEASURED): max 98.3%, none at 100%, 6 of 50 under 50%. So the 98% median looks representative.

### Cached failures were reused without verification
In PR 163164, `tests/components/hydrawise/test_init.py` (cached code 1) was reused at all 5 pushes and never verified (MEASURED). The new "never reuse a failure" rule fixes this. The shares were not recomputed under it; the effect is tiny.

### The aggregator override is too permissive
`aggregate.py` turns a wrong hit into "flaky" for **any** re-check verdict string that does not start with `code-change`. A verdict written as "missed dependency" would be counted as flaky. Today both verdicts are legitimate ("capture-induced…", "flaky…"), so no number changes. Make the accepted verdicts an explicit allow-list.

### knx and switchbot verdicts
- **switchbot:** the per-run summaries (2/20 at the base, 2/30 at the push, same `KeyError: 'path'`) support "flaky" (DECLARED).
- **knx:** "plain 0/20, traced 6/8 at both commits" is a count with no logs (DECLARED, not reproduced). It is consistent with the walk data (MEASURED):
  - knx was counted failing at pushes 0-3;
  - it passed in the traced verification run at push 4, which a 75% failure rate allows.

### Statistical power
0 wrong in 5,887 verified skips (DECLARED) bounds the per-skip error rate at about 0.05% (95% upper bound, ESTIMATED 3/5887). That is for these repositories and this environment. It says nothing about the holes above, which only fire when a read-write fixture, an environment variable, the runtime or the network changes.

## Files
- `review-R-002/test_r002_capture.py`: the 2 failing tests (errors 1 and 2).
- `review-R-002/demo/`: the full `walk.py` run that shows the wrong hit for error 1.
- `review-R-002/go_network_repro.sh`: the command for error 3.
- `review-R-002/scripts/`: `skips.py`, `pick.py` and `roots_check.py`, which pick the skipped units, choose the commits and check the recorded paths.
- `review-R-002/*-units.txt` and `*.json`: the fresh-rerun inputs and outputs.
- `review-R-002/notes.md`: my working notes.
