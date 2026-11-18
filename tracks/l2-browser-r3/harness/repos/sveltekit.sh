# sveltejs/kit: the `basics` test app, Playwright against the Vite dev server, as its CI leg
# `{ app: basics, script: pw:dev, project: js, shard: 1/2 }` (.github/workflows/ci.yml: 4 workers, chromium, retries 2
# on CI; the repository ships test/github-flaky-warning-reporter.js, which reports tests that passed only on a retry).
PW_DIR=packages/kit/test/apps/basics
PW_ARGS="test/playwright"
PW_ENV="DEV=true KIT_E2E_BROWSER=chromium KIT_E2E_WORKERS=4 KIT_E2E_SHARD=1/2 KIT_E2E_PROJECT=js"

setup() {
  corepack enable
  pnpm install --frozen-lockfile
  pnpm run sync-all
  (cd packages/kit && pnpm exec playwright install --with-deps chromium)
}

reset() {  # the app's own pre-run step (pw:dev runs it before every Playwright run)
  (cd packages/kit/test/apps/basics && node test/playwright/setup.js)
}
