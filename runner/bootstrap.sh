#!/usr/bin/env bash
# fenvix runner bootstrap: turn one Linux x64 machine into a `runs-on: [self-hosted, fenvix]` GitHub Actions runner.
#
#   runner/bootstrap.sh install     # tools + engine wheel + Actions runner download (no GitHub credentials needed)
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
#                           $FENVIX_HOME/cache            the persistent cache with proof (survives between jobs)
#                           $FENVIX_HOME/bin/fenvix-run   the job wrapper
#   FENVIX_RUNNER_NAME    runner name                     (default fenvix-<hostname>)
#   FENVIX_EPHEMERAL      1 = the runner takes one job, then deregisters (needs one token per job; default 0)
#   FENVIX_PYTHON         Python version for jobs         (default 3.13)
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

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_SRC="$(cd "$HERE/.." && pwd)"
RUNNER_DIR="$FENVIX_HOME/actions-runner"

log() { printf '[fenvix-bootstrap] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1; }

install_tools() {
  log "tools: git, curl, strace (child processes of tests are followed with strace), uv, Rust"
  local missing=()
  for c in git curl tar strace; do need_cmd "$c" || missing+=("$c"); done
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
  uv python install "$FENVIX_PYTHON" >/dev/null
}

build_engine() {
  log "engine: building the detpy wheel from $ENGINE_SRC"
  mkdir -p "$FENVIX_HOME/wheels" "$FENVIX_HOME/bin" "$FENVIX_HOME/cache"
  local venv="$FENVIX_HOME/build-venv"
  [ -x "$venv/bin/python" ] || uv venv -q --python "$FENVIX_PYTHON" "$venv"
  uv pip install -q --python "$venv/bin/python" "maturin>=1.5,<2"
  rm -f "$FENVIX_HOME"/wheels/detpy-*.whl
  (cd "$ENGINE_SRC" && "$venv/bin/maturin" build --release --compatibility linux -o "$FENVIX_HOME/wheels" >&2)
  ls "$FENVIX_HOME"/wheels/detpy-*.whl >/dev/null || die "wheel not built"
  install -m 755 "$HERE/fenvix-run" "$FENVIX_HOME/bin/fenvix-run"
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
$( [ -n "${HTTPS_PROXY:-${https_proxy:-}}" ] && printf 'no_proxy=%s\nNO_PROXY=%s\n' "$(sane_no_proxy)" "$(sane_no_proxy)" )
PATH=$FENVIX_HOME/bin:$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
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
  register) register ;;
  run) run_runner ;;
  all) install_tools; build_engine; download_runner; write_job_env; register; run_runner ;;
  remove) remove ;;
  check-network) check_network ;;
  *) sed -n '2,30p' "$0"; exit 2 ;;
esac
