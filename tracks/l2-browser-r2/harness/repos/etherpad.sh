# ether/etherpad-lite: Playwright frontend tests (chromium) against the Etherpad server started before the
# runner, as in .github/workflows/frontend-tests.yml (CI: retries 2). Known flaky (idle study): embed_value.spec.ts.
PW_DIR=src
PW_ARGS="--project=chromium"
PW_ENV="NODE_ENV=production"

setup() {
  corepack enable
  pnpm install --frozen-lockfile
  cp ./src/tests/settings.json settings.json
  (cd src && pnpm exec playwright install chromium --with-deps)
}

reset() {
  rm -f var/dirty.db var/*.db 2>/dev/null || true
}

server_start() {  # MODE SEED
  bg_start "$L2_OUT/server.pid" "$L2_OUT/server-$1.log" bash -c "source '$L2_H/lib.sh'; detjs_serve $1 ${2:-none} -- pnpm run prod"
  wait_http http://localhost:9001/ 240
}

server_stop() {
  bg_stop "$L2_OUT/server.pid"
}
