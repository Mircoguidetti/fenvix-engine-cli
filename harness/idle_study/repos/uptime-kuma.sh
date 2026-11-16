# louislam/uptime-kuma: Playwright e2e, as in .github/workflows/auto-test.yml job e2e-test
setup() {
  npm clean-install --no-fund
  npx playwright@~1.64.1 install --with-deps chromium
  npm run build
}

reset() {
  rm -rf data/playwright-test 2>/dev/null || true
}

run_tests() {
  npx playwright test --retries=0 --max-failures=0 --reporter=line,junit
}
