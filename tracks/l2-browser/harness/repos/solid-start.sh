# solidjs/solid-start: Playwright tests against the Vite dev server (webServer), the Node harness's
# pw-solid-start (47 tests, no flaky test in 10 baseline runs there).
PW_ARGS="--project=chromium"

setup() {
  corepack enable
  pnpm install --frozen-lockfile
  local cfg d
  cfg=$(find . -name 'playwright.config.*' -not -path '*/node_modules/*' | awk '{ print gsub("/","/"), $0 }' | sort -n | head -1 | cut -d' ' -f2)
  d=$(dirname "$cfg")
  persist PW_DIR "$d"
  (cd "$d" && npx -y playwright@latest install-deps chromium && pnpm exec playwright install chromium)
}
