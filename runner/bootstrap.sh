#!/usr/bin/env bash
# fenvix runner bootstrap: turn one Linux x64 machine into a `runs-on: [self-hosted, fenvix]` GitHub Actions runner.
#
#   runner/bootstrap.sh install     # tools + engines (detpy wheel, Node LTS + detjs) + Actions runner download (no GitHub credentials)
#   runner/bootstrap.sh engines     # tools + engines only (what a machine image bakes in)
#   runner/bootstrap.sh register    # register with GitHub (needs a registration token, see below)
#   runner/bootstrap.sh run         # serve jobs in the foreground (Ctrl-C to stop)
#   runner/bootstrap.sh all         # install, register, run
#   runner/bootstrap.sh remove      # deregister (needs a fresh registration or removal token)
#
# Configuration (environment variables):
#   FENVIX_REPO_URL       repository the runner serves   (default https://github.com/Mircoguidetti/fenvix-engine-cli)
#   FENVIX_HOME           everything the machine keeps    (default ~/fenvix)
#                           $FENVIX_HOME/actions-runner   the official GitHub Actions runner
#                           $FENVIX_HOME/wheels           detpy wheel built from this checkout
#                           $FENVIX_HOME/node             Node LTS (jobs that do not set up their own Node use it)
#                           $FENVIX_HOME/detjs            detjs (Node engine: napi core + Vitest/Jest shells)
#                           $FENVIX_HOME/bin/detjs        detjs command (runs with whatever `node` the job has)
#                           $FENVIX_HOME/cache            the persistent cache with proof (survives between jobs)
#                           $FENVIX_HOME/bin/fenvix-run   the job wrapper
#   FENVIX_RUNNER_NAME    runner name                     (default fenvix-<hostname>)
#   FENVIX_EPHEMERAL      1 = the runner takes one job, then deregisters (needs one token per job; default 0)
#   FENVIX_PYTHON         Python version for jobs         (default 3.13)
#   FENVIX_NODE_VERSION   Node for jobs and the detjs build (default below, the Active LTS; checksum verified)
#   FENVIX_DETJS_REF      commit of the detjs sources     (default below: claude/node-l0)
#   FENVIX_DETJS_REPO     where to fetch them             (default: this checkout's origin)
#   FENVIX_DETJS_SRC      a local detjs checkout instead of fetching (its node/ and crates/ are used)
#   FENVIX_LANGS          engines to install              (default "python node")
#   RUNNER_VERSION        GitHub Actions runner version   (default below; checksum verified)
#
# The registration token (valid one hour, from `POST /repos/{owner}/{repo}/actions/runners/registration-token`, which
# needs admin rights on the repository, or from Settings -> Actions -> Runners -> New self-hosted runner) is read from,
# in order: $FENVIX_RUNNER_TOKEN, the file $FENVIX_RUNNER_TOKEN_FILE (default ~/.fenvix/registration-token, mode 600).
# Never commit it, never paste it in a chat. A just-in-time config (`POST .../actions/runners/generate-jitconfig`,
# base64 string) can be given instead in $FENVIX_JITCONFIG or the file ~/.fenvix/jitconfig: the runner then takes
# exactly one job without any registration step.
set -euo pipefail

FENVIX_REPO_URL="${FENVIX_REPO_URL:-https://github.com/Mircoguidetti/fenvix-engine-cli}"
FENVIX_HOME="${FENVIX_HOME:-$HOME/fenvix}"
FENVIX_RUNNER_NAME="${FENVIX_RUNNER_NAME:-fenvix-$(hostname -s)}"
FENVIX_EPHEMERAL="${FENVIX_EPHEMERAL:-0}"
FENVIX_PYTHON="${FENVIX_PYTHON:-3.13}"
FENVIX_RUNNER_TOKEN_FILE="${FENVIX_RUNNER_TOKEN_FILE:-$HOME/.fenvix/registration-token}"
FENVIX_JITCONFIG_FILE="${FENVIX_JITCONFIG_FILE:-$HOME/.fenvix/jitconfig}"
# Pinned runner release and its SHA-256 (from the release notes of actions/runner). Update both together.
RUNNER_VERSION="${RUNNER_VERSION:-2.329.0}"
RUNNER_SHA256="${RUNNER_SHA256:-194f1e1e4bd02f80b7e9633fc546084d8d4e19f3928a324d512ea53430102e1d}"
# Node: the Active LTS on 2026-11-18 is 26 ("Lithium"). SHA-256 from https://nodejs.org/dist/v26.13.1/SHASUMS256.txt.
FENVIX_NODE_VERSION="${FENVIX_NODE_VERSION:-26.13.1}"
NODE_SHA256_X64="${NODE_SHA256_X64:-5c063e46bab0fbc1c17cc445d7ff129cbdcd0471be6ed83b6ab864f8143bc864}"
NODE_SHA256_ARM64="${NODE_SHA256_ARM64:-89e1853138db51e8b82d3e98ba9c0d3f2956a28e5e55ea1b7e12d25aae92d5dd}"
COREPACK_VERSION="${COREPACK_VERSION:-0.36.0}"   # Node 25+ no longer ships corepack (pnpm/yarn as each project pins them)
# detjs sources: claude/node-l0 (Node L0 report, R-005b). Move with the commit the Node work declares ready.
FENVIX_DETJS_REF="${FENVIX_DETJS_REF:-8e9209bb1351d4996f5fba39e9ad4b9b8b2e46e8}"
FENVIX_LANGS="${FENVIX_LANGS:-python node}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_SRC="$(cd "$HERE/.." && pwd)"
RUNNER_DIR="$FENVIX_HOME/actions-runner"
FENVIX_DETJS_REPO="${FENVIX_DETJS_REPO:-$(git -C "$ENGINE_SRC" remote get-url origin 2>/dev/null || echo "$FENVIX_REPO_URL")}"

log() { printf '[fenvix-bootstrap] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1; }

install_tools() {
  log "tools: git, curl, xz, a C linker, strace (child processes of tests are followed with strace), uv, Rust"
  local missing=()
  for c in git curl tar xz strace; do need_cmd "$c" || missing+=("$c"); done
  need_cmd cc || missing+=(build-essential)
  [[ " ${missing[*]} " == *" xz "* ]] && missing=("${missing[@]/#xz/xz-utils}")
  if ((${#missing[@]})); then
    if need_cmd apt-get; then
      local sudo=""; [ "$(id -u)" = 0 ] || sudo="sudo"
      $sudo apt-get update -qq && $sudo apt-get install -y -qq "${missing[@]}" build-essential >/dev/null
    else
      die "missing: ${missing[*]} (install them, then run again)"
    fi
  fi
  if ! need_cmd uv; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
  if ! need_cmd cargo; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
    # shellcheck disable=SC1091
    . "$HOME/.cargo/env"
  fi
  if wants python; then uv python install "$FENVIX_PYTHON" >/dev/null; fi
}

wants() { [[ " $FENVIX_LANGS " == *" $1 "* ]]; }

build_engine() {
  mkdir -p "$FENVIX_HOME/bin" "$FENVIX_HOME/cache"
  install -m 755 "$HERE/fenvix-run" "$FENVIX_HOME/bin/fenvix-run"
  if wants python; then build_detpy; fi
  if wants node; then install_node; build_detjs; fi
}

install_node() {
  local arch sha
  case "$(uname -m)" in
    x86_64) arch=x64; sha="$NODE_SHA256_X64" ;;
    aarch64|arm64) arch=arm64; sha="$NODE_SHA256_ARM64" ;;
    *) die "node: unsupported machine $(uname -m)" ;;
  esac
  local dir="$FENVIX_HOME/node"
  if [ -x "$dir/bin/node" ] && [ "$("$dir/bin/node" --version)" = "v$FENVIX_NODE_VERSION" ]; then
    log "node: v$FENVIX_NODE_VERSION already in $dir"
  else
    log "node: downloading v$FENVIX_NODE_VERSION ($arch)"
    local tgz="$FENVIX_HOME/node-v$FENVIX_NODE_VERSION-linux-$arch.tar.xz"
    curl -fsSL -o "$tgz" "https://nodejs.org/dist/v$FENVIX_NODE_VERSION/node-v$FENVIX_NODE_VERSION-linux-$arch.tar.xz"
    echo "$sha  $tgz" | sha256sum -c - >&2 || die "node checksum mismatch (FENVIX_NODE_VERSION and NODE_SHA256_* go together)"
    rm -rf "$dir" && mkdir -p "$dir"
    tar -xJf "$tgz" -C "$dir" --strip-components=1
    rm -f "$tgz"
  fi
  export PATH="$dir/bin:$PATH"
  # pnpm and yarn at the version each project pins (`packageManager`), through corepack shims next to node.
  [ -x "$dir/bin/corepack" ] || npm install -g --silent --no-fund --no-audit "corepack@$COREPACK_VERSION" >&2
  "$dir/bin/corepack" enable --install-directory "$dir/bin" pnpm yarn
  log "node: $(node --version), npm $(npm --version), corepack $("$dir/bin/corepack" --version)"
}

build_detjs() {
  local src="${FENVIX_DETJS_SRC:-}"
  if [ -z "$src" ]; then
    src="$FENVIX_HOME/src/detjs"
    log "detjs: fetching $FENVIX_DETJS_REF from $FENVIX_DETJS_REPO"
    mkdir -p "$src"
    [ -d "$src/.git" ] || git -C "$src" init -q
    git -C "$src" fetch -q --depth 1 "$FENVIX_DETJS_REPO" "$FENVIX_DETJS_REF"
    git -C "$src" checkout -q --detach FETCH_HEAD
  fi
  [ -f "$src/node/scripts/build.js" ] || die "detjs: no node/scripts/build.js in $src"
  log "detjs: building the native core (crates/detpy-node) in $src"
  (cd "$src/node" && node scripts/build.js >&2)
  local dest="$FENVIX_HOME/detjs"
  rm -rf "$dest.new" && mkdir -p "$dest.new"
  cp -r "$src/node/bin" "$src/node/src" "$src/node/package.json" "$dest.new/"
  cp "$src"/node/detjs.*.node "$dest.new/"
  git -C "$src" rev-parse HEAD >"$dest.new/COMMIT" 2>/dev/null || echo "local" >"$dest.new/COMMIT"
  rm -rf "$dest" && mv "$dest.new" "$dest"
  # `detjs` for jobs and for the replay commands in the summaries: the job's own node (setup-node), else ours.
  printf '#!/bin/sh\nexec node "%s/bin/detjs.js" "$@"\n' "$dest" >"$FENVIX_HOME/bin/detjs"
  chmod 755 "$FENVIX_HOME/bin/detjs"
  "$FENVIX_HOME/bin/detjs" --det-help | grep -q -- '--det-seed' || die "detjs: --det-help failed"
  log "detjs: $dest ($(cut -c1-12 "$dest/COMMIT"), core $(basename "$(ls "$dest"/detjs.*.node)"))"
}

build_detpy() {
  log "engine: building the detpy wheel from $ENGINE_SRC"
  mkdir -p "$FENVIX_HOME/wheels" "$FENVIX_HOME/bin" "$FENVIX_HOME/cache"
  local venv="$FENVIX_HOME/build-venv"
  [ -x "$venv/bin/python" ] || uv venv -q --python "$FENVIX_PYTHON" "$venv"
  uv pip install -q --python "$venv/bin/python" "maturin>=1.5,<2"
  rm -f "$FENVIX_HOME"/wheels/detpy-*.whl
  (cd "$ENGINE_SRC" && "$venv/bin/maturin" build --release --compatibility linux -o "$FENVIX_HOME/wheels" >&2)
  ls "$FENVIX_HOME"/wheels/detpy-*.whl >/dev/null || die "wheel not built"
  log "engine: $(ls "$FENVIX_HOME"/wheels/detpy-*.whl)"
}

download_runner() {
  if [ -x "$RUNNER_DIR/config.sh" ]; then log "runner: already in $RUNNER_DIR"; return; fi
  log "runner: downloading actions/runner v$RUNNER_VERSION"
  mkdir -p "$RUNNER_DIR"
  local tgz="$FENVIX_HOME/actions-runner-linux-x64-$RUNNER_VERSION.tar.gz"
  curl -fsSL -o "$tgz" \
    "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/actions-runner-linux-x64-$RUNNER_VERSION.tar.gz"
  echo "$RUNNER_SHA256  $tgz" | sha256sum -c - >&2 || die "runner checksum mismatch (RUNNER_VERSION and RUNNER_SHA256 go together)"
  tar -xzf "$tgz" -C "$RUNNER_DIR"
  rm -f "$tgz"
  # The runner's own dependencies (libicu etc.); needs root once.
  if [ -x "$RUNNER_DIR/bin/installdependencies.sh" ] && need_cmd apt-get; then
    local sudo=""; [ "$(id -u)" = 0 ] || sudo="sudo"
    $sudo "$RUNNER_DIR/bin/installdependencies.sh" >/dev/null || log "runner: installdependencies.sh failed (continuing)"
  fi
}

sane_no_proxy() {
  # The runner (2.329.0) aborts at startup (ArgumentNullException in RunnerWebProxy) on some no_proxy entries such
  # as "::", CIDR ranges or "*.domain" (MEASURED in a proxied container). Keep plain host names and IPv4 addresses.
  local raw="${no_proxy:-${NO_PROXY:-}}" out=() e
  IFS=',' read -ra parts <<<"$raw"
  for e in "${parts[@]}"; do
    e="${e// /}"
    [[ -z "$e" || "$e" == *"/"* || "$e" == *"*"* || "$e" == *":"* ]] && continue
    out+=("$e")
  done
  (IFS=','; printf '%s' "${out[*]}")
}

write_job_env() {
  # The runner exports the variables of `.env` (in its root) to every job: jobs find the engine and the cache there.
  cat >"$RUNNER_DIR/.env" <<EOF
FENVIX_HOME=$FENVIX_HOME
FENVIX_CACHE_ROOT=$FENVIX_HOME/cache
FENVIX_WHEEL_DIR=$FENVIX_HOME/wheels
FENVIX_PYTHON=$FENVIX_PYTHON
FENVIX_DETJS=$FENVIX_HOME/detjs/bin/detjs.js
$( [ -n "${HTTPS_PROXY:-${https_proxy:-}}" ] && printf 'no_proxy=%s\nNO_PROXY=%s\n' "$(sane_no_proxy)" "$(sane_no_proxy)" )
PATH=$FENVIX_HOME/bin:$FENVIX_HOME/node/bin:$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
EOF
  log "runner: job environment in $RUNNER_DIR/.env"
}

read_token() {
  if [ -n "${FENVIX_RUNNER_TOKEN:-}" ]; then printf '%s' "$FENVIX_RUNNER_TOKEN"; return; fi
  if [ -f "$FENVIX_RUNNER_TOKEN_FILE" ]; then tr -d ' \n\r' <"$FENVIX_RUNNER_TOKEN_FILE"; return; fi
  return 1
}

register() {
  local np; np="$(sane_no_proxy)"; export no_proxy="$np" NO_PROXY="$np"
  [ -x "$RUNNER_DIR/config.sh" ] || die "run '$0 install' first"
  if [ -n "${FENVIX_JITCONFIG:-}" ] || [ -f "$FENVIX_JITCONFIG_FILE" ]; then
    log "register: just-in-time config found, nothing to register (run '$0 run')"; return
  fi
  local token
  token="$(read_token)" || die "no registration token: set FENVIX_RUNNER_TOKEN or write it to $FENVIX_RUNNER_TOKEN_FILE (chmod 600). See docs/RUNNER-PROTOTYPE.md"
  local flags=(--unattended --replace --url "$FENVIX_REPO_URL" --token "$token" --name "$FENVIX_RUNNER_NAME"
               --labels fenvix --work "$FENVIX_HOME/work")
  [ "$FENVIX_EPHEMERAL" = 1 ] && flags+=(--ephemeral)
  [ "$(id -u)" = 0 ] && export RUNNER_ALLOW_RUNASROOT=1
  (cd "$RUNNER_DIR" && ./config.sh "${flags[@]}")
  log "register: '$FENVIX_RUNNER_NAME' registered on $FENVIX_REPO_URL with labels self-hosted,Linux,X64,fenvix"
}

run_runner() {
  local np; np="$(sane_no_proxy)"; export no_proxy="$np" NO_PROXY="$np"
  [ "$(id -u)" = 0 ] && export RUNNER_ALLOW_RUNASROOT=1
  if [ -n "${FENVIX_JITCONFIG:-}" ] || [ -f "$FENVIX_JITCONFIG_FILE" ]; then
    local jit="${FENVIX_JITCONFIG:-$(tr -d ' \n\r' <"$FENVIX_JITCONFIG_FILE")}"
    (cd "$RUNNER_DIR" && exec ./run.sh --jitconfig "$jit")
  else
    (cd "$RUNNER_DIR" && exec ./run.sh)
  fi
}

remove() {
  local token
  token="$(read_token)" || die "no token: removal needs a fresh registration (or removal) token"
  (cd "$RUNNER_DIR" && ./config.sh remove --token "$token")
}

check_network() {
  # The runner long-polls these hosts. A machine that cannot reach them can be registered but never gets a job.
  local bad=0
  for h in github.com api.github.com broker.actions.githubusercontent.com pipelines.actions.githubusercontent.com \
           results-receiver.actions.githubusercontent.com; do
    if curl -s -o /dev/null -m 10 "https://$h"; then log "network: $h reachable"; else log "network: $h NOT reachable"; bad=1; fi
  done
  return $bad
}

case "${1:-}" in
  install) install_tools; build_engine; download_runner; write_job_env; check_network || log "network: see above" ;;
  engines) install_tools; build_engine ;;   # tools and engines only (machine images: no runner, no network check)
  register) register ;;
  run) run_runner ;;
  all) install_tools; build_engine; download_runner; write_job_env; register; run_runner ;;
  remove) remove ;;
  check-network) check_network ;;
  *) sed -n '2,30p' "$0"; exit 2 ;;
esac
