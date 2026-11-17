#!/usr/bin/env bash
# Run the fenvix-demo jobs on this machine without GitHub: the same steps as .github/workflows/fenvix-demo-jobs.yml
# (job 1 at commit N, job 2 at commit N+1 with the cache kept on the machine, then the check of every reuse), each
# job in its own fresh temp directory and virtualenv, as a runner would do it. Step summaries go to
# $OUT/job-*/step-summary.md. Use it to check a machine before it serves real jobs.
#
#   FENVIX_HOME=~/fenvix runner/local-demo.sh [target-url] [commit-N] [commit-N+1]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FENVIX_HOME="${FENVIX_HOME:-$HOME/fenvix}"
TARGET_URL="${1:-https://github.com/pallets/click}"
N="${2:-e38188e9e205005d5af5f9e59df51904c984586a}"
N1="${3:-08b803cf32ceb2ae6a772c62d5da42757a897d44}"
PY_VERSION="${FENVIX_PYTHON:-3.13}"
OUT="${OUT:-$FENVIX_HOME/local-demo/$(date -u +%Y%m%dT%H%M%SZ)}"
export FENVIX_CACHE_ROOT="${FENVIX_CACHE_ROOT:-$FENVIX_HOME/cache}"
KEY="$(basename "$TARGET_URL")@local-demo-$(basename "$OUT")"
WHEEL="$(ls "$FENVIX_HOME"/wheels/detpy-*.whl | head -1)"
mkdir -p "$OUT"
SRC="$OUT/src"
git clone -q --filter=blob:none "$TARGET_URL" "$SRC"

job() {  # job <name> <commit> [verify]
  local name="$1" sha="$2" dir="$OUT/$1"
  mkdir -p "$dir"
  export RUNNER_TEMP="$dir" GITHUB_STEP_SUMMARY="$dir/step-summary.md"
  : >"$GITHUB_STEP_SUMMARY"
  rm -rf "$dir/target" && git -C "$SRC" worktree add -q --detach "$dir/target" "$sha"
  uv venv -q --python "$PY_VERSION" "$dir/venv"
  local py="$dir/venv/bin/python" grp=""
  grep -q '^tests = ' "$dir/target/pyproject.toml" 2>/dev/null && grp="--group tests"
  (cd "$dir/target" && uv pip install -q --python "$py" -e . $grp pytest && uv pip install -q --python "$py" "$WHEEL")
  local t0=$SECONDS rc=0
  "$py" "$HERE/fenvix-run" --project "$dir/target" --python "$py" --key "$KEY" --out "$dir/fenvix" \
      --title "fenvix · $(basename "$TARGET_URL") @ $name" || rc=$?
  echo "$name: fenvix-run exit $rc, $((SECONDS - t0)) s" | tee -a "$OUT/jobs.log"
  if [ "${3:-}" = verify ]; then
    "$py" "$HERE/fenvix-run" verify --project "$dir/target" --python "$py" --summary "$dir/fenvix/summary.json" || rc=$?
    echo "$name verify: exit $rc" | tee -a "$OUT/jobs.log"
  fi
}

job job-1-commit-N "$N"
job job-2-commit-N1 "$N1" verify
echo "results in $OUT (cache namespace $KEY under $FENVIX_CACHE_ROOT)"
