DONE — P-051 items 1–6 done and proven; coordinator add-ons H1 and H2 done here; H3 applied by the coordinator session in f5a9a4d (not by this session).

# P-051: examining a PR's own artifact (X-01)

Branch: `claude/exam` (PR #7 into `claude/release-1` stays open; nothing merged).
Commits: `19152ad` (release_run source + attribution), `f871d80` (H1 + H2), merge `bbda702`.

## Proof runs

| | exam run | release_run input | resolved release run | commit | branch | install |
|---|---|---|---|---|---|---|
| 1 | **44814691202** | 44804076830 | 44804076830 (`selected: requested`, event workflow_dispatch) | 7e36c395b319 | claude/packages | ok, artifact `engine-artifact` id 14661813649, tarball `fenvix-engine-0.1.0-r91.7e36c39-linux-x86_64.tar.gz` |
| 2 | **44816009535** | unset | 44811997318 (`selected: newest-trunk`, event push) | f84dde74f3a4 | claude/release-1 | ok, artifact `engine-artifact` id 14668186289, tarball `fenvix-engine-0.1.0-r94.f84dde7-linux-x86_64.tar.gz` |

Both runs: rows=F-18, one leg (F-18 linux-x64 py3.13 node22). F-18 result is the same on both artifacts:
FAIL 3/5 (`F-18.help`: `python`, `node` missing from `fenvix --help`; `F-18.one-verify`: `fenvix verify` rc=1 on
Python and Node traces). Those are engine findings, not plumbing. Results committed by the runs as `50c84f2` and
`d93f84b` (`exam/results.json`; it now holds run 44816009535).

Superseded/cancelled (not proofs): 44814365673 (first dispatch, pre-H1/H2 code, cancelled by me), 44814664211 (full
exam started by the merge commit `bbda702`, which lacked `[skip ci]`; cancelled). Both cancelled runs' aggregates still
committed a results.json (`7ce0565`, `b3ae05c`), since replaced.

## Diff summary (only install source and attribution; checks, thresholds, legs unchanged)

`git diff 36397ec HEAD` on rows_*.py, lib.py, fam.py, probes.py, projects.py, legs.json, gap_map.json, run.py, PLAN.md: empty.

- `.github/workflows/exam.yml` (+10/−2): workflow_dispatch input `release_run` (optional); legs get
  `EXAM_RELEASE_RUN: ${{ github.event.inputs.release_run }}` (empty on push = trunk); aggregate gets `--release-run`.
- `exam/install.sh` (rewritten install source, same outputs):
  - `EXAM_RELEASE_RUN` set: `GET runs/<id>` must exist (else `ok=false "release run <id> not found"`), its `path`
    must be `.github/workflows/release-1.yml` (else `"run <id> is not a release-1.yml run"`), and it must have a
    non-expired `engine-artifact` (else `"... missing"` / `"... expired"`); non-numeric id refused too. Any branch.
  - unset: newest non-expired `engine-artifact` on `claude/release-1` (same selection rule as before).
  - H2: installs the versioned tarball (`engine-artifact`: `fenvix-engine-*-linux-x86_64.tar.gz` + `.sha256`) with
    the run head commit's `release/engine/fetch.sh` (pinned sha256 from the artifact's `.sha256`, fail closed; a
    mismatch writes `ok=false "release/engine/fetch.sh refused: checksum mismatch ..."`) and the tarball's own
    `install.sh` (`PYTHON=python3`, prefix `$FENVIX_HOME`). Replaces `engine-linux-x64` + `release/install-image.sh`.
  - H1: `EXAM_WHEEL` = `<tarball>/wheels/fenvix-*.whl` (falls back to `detpy-*.whl`). Proof 1/2 record
    `wheel: .../wheels/fenvix-0.1.0-cp312-abi3-manylinux_2_28_x86_64.whl`.
  - install.json now also records `head_branch`, `event`, `selected` (requested | newest-trunk), `requested_run`,
    `engine_dir`, `wheel`; `sha256` covers every artifact file plus the tarball's `VERSION.json`.
- `exam/aggregate.py` (+16/−1): every leg in `rows[*].legs[*]` carries `artifact` {ok, release_run, release_commit,
  head_branch, event, selected, artifact, artifact_id, requested_run, reason}; top level adds
  `release_run_requested` and `artifacts_tested` [{release_run, release_commit, head_branch, event, selected,
  install_ok, legs}], also printed in the job log. A row PASS can be tied to the PR head sha through these.

Local checks before pushing (stubbed `gh`): run not found, wrong workflow, artifact missing, artifact expired,
non-numeric id, no trunk artifact, checksum mismatch → each `ok=false` with its reason; requested and trunk paths
install with the real `fetch.sh` of f84dde7.

## H3

Applied by the coordinator session (session_01YAF6DhnJz9UzmjRRPv2uqs) in `f5a9a4d`, under the founder delegation the
coordinator cited. The change is one line: the F-09.job-venv venv now installs `-e . pytest freezegun`. This session
did not make it: its permission guard blocked the edit, because the check is founder-frozen and the approval came
from a peer message. No proof run covers it, since F-18 does not run F-09. Below is this section as it stood before:

R-050 H3 (add `freezegun` to the `F-09.job-venv` venv) means editing the body of check `F-09.job-venv` in
`exam/rows_f.py`. The P-051 brief says checks are frozen at 36397ec8 by the founder and only the install source may
change; a peer message cannot lift that. Ready to apply (one line: `"-e", ".", "pytest", "freezegun"`) on a founder OK.

## Notes for the coordinator

1. `pull_request` runs of release-1.yml build from the merge ref (`refs/pull/N/merge`), but the run's `head_sha`
   is the PR head. install.sh records and checks out `head_sha` (fetch.sh comes from there); the tarball's
   `VERSION.json` will name the merge commit. If a PASS must match the PR head exactly, release-1.yml should check
   out `github.event.pull_request.head.sha` for PR builds (not an exam change).
2. Check *descriptions* of F-09.install/artifact-identity still say "engine-linux-x64 ... install-image.sh" (frozen
   text); the observed values now show the tarball.
3. A dispatched run (any `release_run`) commits its results.json to `claude/exam` like every dispatched run does, so
   the file shows the last exam run, which may be a PR artifact; `release_run_requested`/`artifacts_tested` say which.
   A row-filtered run still lists all 24 rows (missing legs = FAIL): pre-existing aggregate behavior, unchanged.
4. The concurrency group `exam-<ref>` serializes all runs on claude/exam: two PR exams cannot run at once. Not
   changed (parallel runs would race on the results.json commit).
