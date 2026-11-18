#!/usr/bin/env bash
# Prepare a target project at a commit the way a fresh job on a runner does: the checkout in ./target (cleaned of
# anything a previous job left), a new virtualenv at the runner's fixed path $RUNNER_TEMP/venv with the project in
# editable mode, its test requirements, pytest and the fenvix engine wheel from $RUNNER_TEMP/wheels.
#
#   runner/ci-project-env.sh <owner/repo> <commit> "<extra pip requirements>"
set -euo pipefail
REPO="$1"; SHA="$2"; EXTRA="${3:-}"
PY_VERSION="${PY:-3.13}"
if [ ! -d target/.git ]; then
  git init -q target
  git -C target remote add origin "https://github.com/$REPO"
fi
git -C target fetch -q --depth 1 origin "$SHA"
git -C target checkout -q -f FETCH_HEAD
git -C target clean -q -ffdx
rm -rf "$RUNNER_TEMP/venv"
uv venv -q --python "$PY_VERSION" "$RUNNER_TEMP/venv"
py="$RUNNER_TEMP/venv/bin/python"
grp=""
grep -q '^tests = ' target/pyproject.toml 2>/dev/null && grp="--group tests"
(cd target && uv pip install -q --python "$py" -e . $grp pytest $EXTRA)
uv pip install -q --python "$py" "$(ls "$RUNNER_TEMP"/wheels/detpy-*.whl | head -1)"
"$py" -c "import detpy, sys; print('detpy', detpy.__version__, 'python', sys.version.split()[0])"
echo "FENVIX_PY=$py" >>"$GITHUB_ENV"
grep -q '^FENVIX_CACHE_ROOT=' "$GITHUB_ENV" 2>/dev/null || echo "FENVIX_CACHE_ROOT=$RUNNER_TEMP/fenvix-cache" >>"$GITHUB_ENV"
echo "target $REPO @ $(git -C target rev-parse HEAD)"
