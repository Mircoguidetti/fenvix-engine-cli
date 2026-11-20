#!/usr/bin/env bash
# Install the engine as our runner machines do (founder decision 2026-11-20: go-live runs only on our machines).
# One source: the artifact engine-linux-x64 of a release-1.yml run, installed with that run's head commit's
# release/install-image.sh (the runner-image install). Which run (founder decision 2026-11-20, rows examined before merge):
#   EXAM_RELEASE_RUN=<run id> -> that release-1.yml run, any branch (a PR run or a dispatched full run); fail closed if the
#                                run is not found, is not release-1.yml, or its engine artifact is missing or expired
#   unset                     -> the newest release-1.yml run on claude/release-1 that has the artifact (the trunk) The install records the artifact,
# the release run and commit, the sha256 of every artifact file and the version `fenvix version` prints.
# Writes $EXAM_OUT_DIR/install.json and exports FENVIX_HOME, EXAM_WHEEL, EXAM_INSTALL_INFO, PATH via $GITHUB_ENV/$GITHUB_PATH.
#   exam/install.sh linux-x64
set -uo pipefail
plat="$1"
src=ci-artifact
out="${EXAM_OUT_DIR:-$PWD/exam-out}"; mkdir -p "$out"
info="$out/install.json"
home="${FENVIX_HOME:-$HOME/fenvix}"
repo="${GITHUB_REPOSITORY:-}"
genv="${GITHUB_ENV:-/dev/null}"; gpath="${GITHUB_PATH:-/dev/null}"
echo "EXAM_INSTALL_INFO=$info" >> "$genv"
write() { python3 - "$info" "$@" <<'PY'
import json, sys
p = sys.argv[1]; kv = dict(a.split("=", 1) for a in sys.argv[2:])
kv["ok"] = kv.get("ok") == "true"
if "sha256" in kv:
    kv["sha256"] = json.loads(kv["sha256"])
json.dump(kv, open(p, "w"), indent=1); print(json.dumps(kv))
PY
}
name="engine-$plat"
want="${EXAM_RELEASE_RUN:-}"
if [ -n "$want" ]; then
  # the named run: must exist and be a run of release-1.yml; its artifact must exist and not be expired
  if ! [[ "$want" =~ ^[0-9]+$ ]]; then
    write ok=false source=ci-artifact platform="$plat" artifact="$name" requested_run="$want" reason="EXAM_RELEASE_RUN is not a run id: $want"; exit 0
  fi
  rq=$(gh api "repos/$repo/actions/runs/$want" --jq '"\(.path) \(.head_sha) \(.head_branch) \(.event)"' 2>&1)
  read -r wpath sha branch event <<< "$rq"
  if [ -z "${sha:-}" ] || ! [[ "$sha" =~ ^[0-9a-f]{40}$ ]]; then
    write ok=false source=ci-artifact platform="$plat" artifact="$name" requested_run="$want" reason="release run $want not found: $(echo "$rq" | tr '\n' ' ' | tr -d '"=')"; exit 0
  fi
  if [ "${wpath%%@*}" != ".github/workflows/release-1.yml" ]; then
    write ok=false source=ci-artifact platform="$plat" artifact="$name" requested_run="$want" release_commit="$sha" head_branch="$branch" reason="run $want is not a release-1.yml run (workflow $wpath)"; exit 0
  fi
  q=$(gh api "repos/$repo/actions/runs/$want/artifacts?name=$name&per_page=100" \
       --jq '[.artifacts[] | select(.name=="'"$name"'")] | if length == 0 then "missing" elif ([.[] | select(.expired==false)] | length) == 0 then "expired" else ([.[] | select(.expired==false)] | sort_by(.created_at) | last | "\(.id)") end' 2>&1)
  if ! [[ "$q" =~ ^[0-9]+$ ]]; then
    write ok=false source=ci-artifact platform="$plat" artifact="$name" requested_run="$want" release_run="$want" release_commit="$sha" head_branch="$branch" event="$event" reason="artifact $name of release run $want: $(echo "$q" | tr '\n' ' ' | tr -d '"=')"; exit 0
  fi
  art="$q"; run="$want"; selected="requested"
else
  q=$(gh api "repos/$repo/actions/artifacts?name=$name&per_page=100" \
       --jq '[.artifacts[] | select(.expired==false and .workflow_run.head_branch=="claude/release-1")] | sort_by(.created_at) | last | if . == null then "" else "\(.id) \(.workflow_run.id) \(.workflow_run.head_sha)" end' 2>&1)
  read -r art run sha <<< "$q"
  if [ -z "${run:-}" ] || ! [[ "$run" =~ ^[0-9]+$ ]]; then
    write ok=false source=ci-artifact platform="$plat" artifact="$name" reason="no artifact $name from release-1.yml on claude/release-1 (the release CI builds only engine-linux-x64): $q"
    exit 0
  fi
  branch=claude/release-1; event=$(gh api "repos/$repo/actions/runs/$run" --jq .event 2>/dev/null || echo unknown); selected="newest-trunk"
fi
dist="$RUNNER_TEMP/engine-dist"; rel="$RUNNER_TEMP/release-src"
rm -rf "$dist" "$rel"
if ! gh run download "$run" -R "$repo" -n "$name" -D "$dist"; then
  write ok=false source=ci-artifact platform="$plat" artifact="$name" release_run="$run" release_commit="$sha" head_branch="$branch" event="$event" selected="$selected" reason="artifact download failed"
  exit 0
fi
mkdir -p "$rel"
git fetch -q --depth 1 --filter=blob:none origin "$sha" && git archive "$sha" release node | tar -x -C "$rel" || {
  write ok=false source=ci-artifact platform="$plat" release_run="$run" release_commit="$sha" head_branch="$branch" event="$event" selected="$selected" reason="cannot check out release commit"; exit 0; }
mkdir -p "$home"
if (cd "$rel" && bash release/install-image.sh "$dist" "$home") > "$out/install.log" 2>&1; then
  echo "FENVIX_HOME=$home" >> "$genv"; echo "EXAM_WHEEL=$(ls "$dist"/detpy-*.whl | head -1)" >> "$genv"
  echo "$home/bin" >> "$gpath"
  shas=$(cd "$dist" && find . -type f | sort | xargs sha256sum | python3 -c "import sys,json; print(json.dumps({l.split()[1][2:]: l.split()[0] for l in sys.stdin}))")
  ver=$(FENVIX_HOME="$home" "$home/bin/fenvix" version 2>&1 | tr '\n' ';' | tr -d '"=')
  write ok=true source=ci-artifact platform="$plat" artifact="$name" artifact_id="$art" release_run="$run" release_commit="$sha" head_branch="$branch" event="$event" selected="$selected" version="$ver" sha256="$shas"
else
  tail -20 "$out/install.log"
  write ok=false source=ci-artifact platform="$plat" artifact="$name" release_run="$run" release_commit="$sha" head_branch="$branch" event="$event" selected="$selected" reason="release/install-image.sh failed: $(tail -3 "$out/install.log" | tr '\n' ' ' | tr -d '"=')"
fi
exit 0
