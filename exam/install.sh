#!/usr/bin/env bash
# Install the engine as our runner machines do (founder decision 2026-11-20: go-live runs only on our machines).
# One source: the versioned engine tarball of a release-1.yml run (CI artifact `engine-artifact`:
# fenvix-engine-<version>-<build>-linux-x86_64.tar.gz + its .sha256; VERSION.json inside), fetched with that run's head
# commit's release/engine/fetch.sh (pinned sha256, fail closed) and installed with the tarball's own install.sh: the
# runner-image install. Which run (founder decision 2026-11-20: rows are examined before their merge):
#   EXAM_RELEASE_RUN=<run id> -> that release-1.yml run, any branch (a PR run or a dispatched full run); fail closed if the
#                                run is not found, is not release-1.yml, or its engine artifact is missing or expired
#   unset                     -> the newest release-1.yml run on claude/release-1 that has the artifact (the trunk)
# The install records the artifact, the release run, its commit and branch, the sha256 of every artifact file (and of the
# tarball's VERSION.json) and the version `fenvix version` prints.
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
clean() { echo "$1" | tr '\n' ' ' | tr -d '"='; }
name="engine-artifact"   # the release CI builds one engine artifact, Linux x86_64 (platform $plat)
want="${EXAM_RELEASE_RUN:-}"
if [ -n "$want" ]; then
  # the named run: must exist and be a run of release-1.yml; its artifact must exist and not be expired
  if ! [[ "$want" =~ ^[0-9]+$ ]]; then
    write ok=false source=$src platform="$plat" artifact="$name" requested_run="$want" reason="EXAM_RELEASE_RUN is not a run id: $want"; exit 0
  fi
  rq=$(gh api "repos/$repo/actions/runs/$want" --jq '"\(.path) \(.head_sha) \(.head_branch) \(.event)"' 2>&1)
  read -r wpath sha branch event <<< "$rq"
  if [ -z "${sha:-}" ] || ! [[ "$sha" =~ ^[0-9a-f]{40}$ ]]; then
    write ok=false source=$src platform="$plat" artifact="$name" requested_run="$want" reason="release run $want not found: $(clean "$rq")"; exit 0
  fi
  if [ "${wpath%%@*}" != ".github/workflows/release-1.yml" ]; then
    write ok=false source=$src platform="$plat" artifact="$name" requested_run="$want" release_commit="$sha" head_branch="$branch" reason="run $want is not a release-1.yml run (workflow $wpath)"; exit 0
  fi
  q=$(gh api "repos/$repo/actions/runs/$want/artifacts?name=$name&per_page=100" \
       --jq '[.artifacts[] | select(.name=="'"$name"'")] | if length == 0 then "missing" elif ([.[] | select(.expired==false)] | length) == 0 then "expired" else ([.[] | select(.expired==false)] | sort_by(.created_at) | last | "\(.id)") end' 2>&1)
  if ! [[ "$q" =~ ^[0-9]+$ ]]; then
    write ok=false source=$src platform="$plat" artifact="$name" requested_run="$want" release_run="$want" release_commit="$sha" head_branch="$branch" event="$event" reason="artifact $name of release run $want: $(clean "$q")"; exit 0
  fi
  art="$q"; run="$want"; selected="requested"
else
  q=$(gh api "repos/$repo/actions/artifacts?name=$name&per_page=100" \
       --jq '[.artifacts[] | select(.expired==false and .workflow_run.head_branch=="claude/release-1")] | sort_by(.created_at) | last | if . == null then "" else "\(.id) \(.workflow_run.id) \(.workflow_run.head_sha)" end' 2>&1)
  read -r art run sha <<< "$q"
  if [ -z "${run:-}" ] || ! [[ "$run" =~ ^[0-9]+$ ]]; then
    write ok=false source=$src platform="$plat" artifact="$name" reason="no artifact $name from release-1.yml on claude/release-1: $(clean "$q")"
    exit 0
  fi
  branch=claude/release-1; event=$(gh api "repos/$repo/actions/runs/$run" --jq .event 2>/dev/null || echo unknown); selected="newest-trunk"
fi
meta=(source=$src platform="$plat" artifact="$name" artifact_id="$art" release_run="$run" release_commit="$sha" head_branch="$branch" event="$event" selected="$selected")
dist="$RUNNER_TEMP/engine-dist"; rel="$RUNNER_TEMP/release-src"; unp="$RUNNER_TEMP/engine-unpacked"
rm -rf "$dist" "$rel" "$unp"
if ! gh run download "$run" -R "$repo" -n "$name" -D "$dist"; then
  write ok=false "${meta[@]}" reason="artifact download failed"
  exit 0
fi
mkdir -p "$rel"
git fetch -q --depth 1 --filter=blob:none origin "$sha" && git archive "$sha" release | tar -x -C "$rel" || {
  write ok=false "${meta[@]}" reason="cannot check out release commit"; exit 0; }
tgz=$(ls "$dist"/fenvix-engine-*-linux-x86_64.tar.gz 2>/dev/null | head -1)
pin=$(cut -d' ' -f1 "$tgz.sha256" 2>/dev/null)
if [ -z "$tgz" ] || [ -z "$pin" ]; then
  write ok=false "${meta[@]}" reason="artifact $name has no fenvix-engine-*-linux-x86_64.tar.gz with its .sha256: $(clean "$(ls "$dist")")"; exit 0
fi
shas=$(cd "$dist" && find . -type f | sort | xargs sha256sum | python3 -c "import sys,json; print(json.dumps({l.split()[1][2:]: l.split()[0] for l in sys.stdin}))")
# fetch (pinned sha256, fail closed) and install with the tarball's own install.sh, as the runner image does
if ! edir=$(bash "$rel/release/engine/fetch.sh" "file://$tgz" "$pin" "$unp" 2> "$out/install.log"); then
  write ok=false "${meta[@]}" sha256="$shas" reason="release/engine/fetch.sh refused: $(clean "$(tail -3 "$out/install.log")")"; exit 0
fi
mkdir -p "$home"
if PYTHON=python3 bash "$edir/install.sh" "$home" >> "$out/install.log" 2>&1; then
  shas=$(python3 -c "import json,sys,hashlib,os; d=json.loads(sys.argv[1]); p=os.path.join(sys.argv[2],'VERSION.json'); \
d[os.path.basename(sys.argv[2])+'/VERSION.json']=hashlib.sha256(open(p,'rb').read()).hexdigest() if os.path.exists(p) else None; print(json.dumps(d))" "$shas" "$edir")
  whl=$(ls "$edir"/wheels/fenvix-*.whl "$edir"/wheels/detpy-*.whl 2>/dev/null | head -1)
  echo "FENVIX_HOME=$home" >> "$genv"; echo "EXAM_WHEEL=$whl" >> "$genv"
  echo "$home/bin" >> "$gpath"
  ver=$(FENVIX_HOME="$home" "$home/bin/fenvix" version 2>&1 | tr '\n' ';' | tr -d '"=')
  write ok=true "${meta[@]}" engine_dir="$edir" wheel="$whl" version="$ver" sha256="$shas"
else
  tail -20 "$out/install.log"
  write ok=false "${meta[@]}" sha256="$shas" reason="the artifact's install.sh failed: $(clean "$(tail -3 "$out/install.log")")"
fi
exit 0
