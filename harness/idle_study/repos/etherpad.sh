# ether/etherpad-lite: Playwright frontend tests (chromium) against the server, as in .github/workflows/frontend-tests.yml
setup() {
  corepack enable
  pnpm install --frozen-lockfile
  cp ./src/tests/settings.json settings.json
  (cd src && pnpm exec playwright install chromium --with-deps)
  svc_bg "$IDLE_OUT/etherpad-server.log" pnpm run prod
  wait_http http://localhost:9001/ 240 2>/dev/null || { tail -60 "$IDLE_OUT/etherpad-server.log"; return 1; }
}

run_tests() {
  cd src && pnpm run test-ui --project=chromium --retries=0 --reporter=line,junit
}
