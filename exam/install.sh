#!/usr/bin/env bash
# Install the engine as a customer would, from ONE switch: EXAM_INSTALL=ci-artifact (default, today) | packages.
#   ci-artifact: the artifact engine-<platform> of the newest release-1.yml run on claude/release-1 that has it,
#                installed with that commit's release/install-image.sh (the documented runner-image install).
#   packages:    pip install fenvix ; npm install -g fenvix   (nothing else).
# Writes $EXAM_OUT_DIR/install.json and exports FENVIX_HOME, EXAM_WHEEL, EXAM_INSTALL_INFO, PATH via $GITHUB_ENV/$GITHUB_PATH.
#   exam/install.sh PLATFORM   (linux-x64 | linux-arm64 | macos-arm64)
set -uo pipefail
plat="$1"
src="${EXAM_INSTALL:-ci-artifact}"
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
json.dump(kv, open(p, "w"), indent=1); print(json.dumps(kv))
PY
}
if [ "$src" = packages ]; then
  if python3 -m pip install fenvix && npm install -g fenvix; then
    write ok=true source=packages platform="$plat"
  else
    write ok=false source=packages platform="$plat" reason="pip install fenvix / npm install -g fenvix failed"
  fi
  exit 0
fi
name="engine-$plat"
q=$(gh api "repos/$repo/actions/artifacts?name=$name&per_page=100" \
     --jq '[.artifacts[] | select(.expired==false and .workflow_run.head_branch=="claude/release-1")] | sort_by(.created_at) | last | if . == null then "" else "\(.id) \(.workflow_run.id) \(.workflow_run.head_sha)" end' 2>&1)
read -r art run sha <<< "$q"
if [ -z "${run:-}" ] || ! [[ "$run" =~ ^[0-9]+$ ]]; then
  write ok=false source=ci-artifact platform="$plat" artifact="$name" reason="no artifact $name from release-1.yml on claude/release-1 (the release CI builds only engine-linux-x64): $q"
  exit 0
fi
dist="$RUNNER_TEMP/engine-dist"; rel="$RUNNER_TEMP/release-src"
rm -rf "$dist" "$rel"
if ! gh run download "$run" -R "$repo" -n "$name" -D "$dist"; then
  write ok=false source=ci-artifact platform="$plat" artifact="$name" release_run="$run" release_commit="$sha" reason="artifact download failed"
  exit 0
fi
git fetch -q --depth 1 origin "$sha" && git worktree add -q --detach "$rel" "$sha" || {
  write ok=false source=ci-artifact platform="$plat" release_run="$run" release_commit="$sha" reason="cannot check out release commit"; exit 0; }
mkdir -p "$home"
if (cd "$rel" && bash release/install-image.sh "$dist" "$home") > "$out/install.log" 2>&1; then
  echo "FENVIX_HOME=$home" >> "$genv"; echo "EXAM_WHEEL=$(ls "$dist"/detpy-*.whl | head -1)" >> "$genv"
  echo "$home/bin" >> "$gpath"
  write ok=true source=ci-artifact platform="$plat" artifact="$name" release_run="$run" release_commit="$sha"
else
  tail -20 "$out/install.log"
  write ok=false source=ci-artifact platform="$plat" artifact="$name" release_run="$run" release_commit="$sha" reason="release/install-image.sh failed: $(tail -3 "$out/install.log" | tr '\n' ' ' | tr -d '"=')"
fi
exit 0
