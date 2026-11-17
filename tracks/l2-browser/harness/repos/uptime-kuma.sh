# louislam/uptime-kuma: Playwright e2e against the app server (webServer in the config; socket.io), as in
# .github/workflows/auto-test.yml job e2e-test (CI: retries 2, workers 1).
PW_DIR=.
PW_ARGS="--max-failures=0"

setup() {
  npm clean-install --no-fund
  npx playwright@~1.64.1 install --with-deps chromium
  npm run build
}

reset() {
  rm -rf data/playwright-test private/e2e-auth.json 2>/dev/null || true
}
