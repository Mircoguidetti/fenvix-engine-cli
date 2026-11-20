#!/usr/bin/env bash
# The shared-cache demo on this machine, without GitHub: a cache service, then
#   one machine : job 1 (commit N) and job 2 (commit N+1) share the machine's cache directory;
#   two machines: job 1 on "machine A" pushes to the service, job 2 on "machine B" (empty disk, own HOME, fresh
#                 virtualenv) pulls from it;
# every job 2 is followed by a full run without the cache (verify: wrong must be 0). Jobs run one at a time in the
# same work directory, emptied between jobs, as a runner does. Results in $OUT.
#
#   FENVIX_HOME=~/fenvix [EXTRA_PIP=...] runner/local-shared-demo.sh <target-url> <commit-N> <commit-N+1>
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FENVIX_HOME="${FENVIX_HOME:-$HOME/fenvix}"
TARGET_URL="$1"; N="$2"; N1="$3"
EXTRA_PIP="${EXTRA_PIP-}"
PY_VERSION="${FENVIX_PYTHON:-3.13}"
NAME="$(basename "$TARGET_URL")"
OUT="${OUT:-$FENVIX_HOME/local-shared-demo/$NAME-$(date -u +%Y%m%dT%H%M%SZ)}"
WHEEL="$(ls "$FENVIX_HOME"/wheels/detpy-*.whl | head -1)"
PORT="${PORT:-18900}"
mkdir -p "$OUT"
SRC="$OUT/src"
git clone -q --filter=blob:none "$TARGET_URL" "$SRC"
WORK="$OUT/work"

# the service, with its own data directory (what a deployment keeps)
SVC_PY="$(command -v python3)"
svc_venv="$OUT/service-venv"
uv venv -q --python "$PY_VERSION" "$svc_venv" && uv pip install -q --python "$svc_venv/bin/python" "$WHEEL"
"$svc_venv/bin/python" -m detpy.cache_service serve --data "$OUT/service-data" --port "$PORT" --quiet &
SVC_PID=$!
trap 'kill $SVC_PID 2>/dev/null || true' EXIT
for _ in $(seq 50); do curl -sf "http://127.0.0.1:$PORT/v1/health" >/dev/null && break; sleep 0.2; done
FENVIX_CACHE_TOKEN="$("$svc_venv/bin/python" -m detpy.cache_service token --data "$OUT/service-data" --org demo)"
export FENVIX_CACHE_TOKEN

job() {  # job <label> <machine> <commit> <cache: dir|url> [verify]
  local label="$1" machine="$2" sha="$3" cache="$4" dir="$OUT/$1"
  mkdir -p "$dir"
  git -C "$SRC" worktree remove --force "$WORK/target" 2>/dev/null || true
  rm -rf "$WORK" && mkdir -p "$WORK/_temp"
  export RUNNER_TEMP="$WORK/_temp" GITHUB_STEP_SUMMARY="$dir/step-summary.md"
  export HOME="$OUT/$machine/home" FENVIX_CACHE_ROOT="$OUT/$machine/cache"
  mkdir -p "$HOME"
  : >"$GITHUB_STEP_SUMMARY"
  git -C "$SRC" worktree add -q --detach "$WORK/target" "$sha"
  uv venv -q --python "$PY_VERSION" "$RUNNER_TEMP/venv"
  local py="$RUNNER_TEMP/venv/bin/python" grp=""
  grep -q '^tests = ' "$WORK/target/pyproject.toml" 2>/dev/null && grp="--group tests"
  (cd "$WORK/target" && uv pip install -q --python "$py" -e . $grp pytest $EXTRA_PIP && uv pip install -q --python "$py" "$WHEEL")
  local t0=$SECONDS rc=0 args=()
  if [ "$cache" = url ]; then args=(--cache "http://127.0.0.1:$PORT/demo"); fi
  "$py" "$HERE/fenvix-run" --project "$WORK/target" --python "$py" --key "$NAME@$(basename "$OUT")" \
      --out "$dir/fenvix" "${args[@]}" --title "fenvix · $NAME @ $label" || rc=$?
  echo "$label ($machine): fenvix-run exit $rc, $((SECONDS - t0)) s" | tee -a "$OUT/jobs.log"
  if [ "${5:-}" = verify ]; then
    "$py" "$HERE/fenvix-run" verify --project "$WORK/target" --python "$py" --summary "$dir/fenvix/summary.json" || rc=$?
    echo "$label verify: exit $rc" | tee -a "$OUT/jobs.log"
  fi
}

job one-machine-job-1 machine-0 "$N" dir
job one-machine-job-2 machine-0 "$N1" dir verify
job two-machines-job-1 machine-a "$N" url
job two-machines-job-2 machine-b "$N1" url verify
"$SVC_PY" "$HERE/shared-cache-compare" "$OUT" | tee "$OUT/compare.md"
