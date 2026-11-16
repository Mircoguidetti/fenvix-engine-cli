# actualbudget/actual: Playwright e2e against the built web client, as in .github/workflows/e2e-test.yml job functional
# (runs on the runner instead of the Playwright container; shard 1 of 3; 4 workers as in CI)
export E2E_USE_BUILD=1 E2E_PORT=3001

setup() {
  npm install -g yarn
  corepack enable || true
  yarn install
  REACT_APP_NETLIFY=true yarn build:browser --skip-translations
  (cd packages/desktop-client && npx playwright install --with-deps chromium)
}

run_tests() {
  CI=1 E2E_WORKERS="$(serial_or 1 4)" yarn e2e --shard=1/3 --retries=0 --reporter=line,junit
}
