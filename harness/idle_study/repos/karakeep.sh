# karakeep-app/karakeep: e2e tests (vitest; global setup brings the compose stack up), as in .github/workflows/ci.yml job tests
export E2E_TEST_NO_BUILD=1

setup() {
  config=/etc/docker/daemon.json
  current=$(sudo cat "$config" 2>/dev/null || echo '{}')
  jq '.features["containerd-snapshotter"] = true' <<<"$current" | sudo tee "$config" >/dev/null
  sudo systemctl restart docker
  image=$(sed -n 's/^  IMAGE: *//p' .github/workflows/chrome.yml)
  version=$(sed -n 's/^  GOOGLE_CHROME_VERSION: *//p' .github/workflows/chrome.yml)
  revision=$(sed -n 's/^  IMAGE_REVISION: *//p' .github/workflows/chrome.yml)
  persist KARAKEEP_CHROME_IMAGE "${image}:${version}-${revision}"
  (cd packages/e2e_tests && docker compose build web web-remote sandbox)
  (cd packages/e2e_tests && docker compose pull --ignore-buildable --quiet)
  docker pull --quiet "$KARAKEEP_CHROME_IMAGE" || (cd packages/e2e_tests && docker compose build chrome)
  corepack enable
  pnpm install
  (cd packages/e2e_tests && pnpm exec playwright install --with-deps chromium)
}

run_tests() {
  cd packages/e2e_tests && pnpm exec vitest run \
    --reporter=dot --reporter=junit --outputFile.junit="$JUNIT_DIR/vitest.xml"
}
