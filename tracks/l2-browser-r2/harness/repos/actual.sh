# actualbudget/actual: Playwright e2e against the built web client (static server in the config's webServer;
# the app's logic runs in the browser and a web worker), as in .github/workflows/e2e-test.yml (CI: retries 1,
# 4 workers; shard 1 of 3).
export E2E_USE_BUILD=1 E2E_PORT=3001 E2E_WORKERS=4
PW_DIR=packages/desktop-client
PW_ARGS="--browser=chromium --shard=1/3"

setup() {
  npm install -g yarn
  corepack enable || true
  yarn install
  REACT_APP_NETLIFY=true yarn build:browser --skip-translations
  (cd packages/desktop-client && npx playwright install --with-deps chromium)
}
