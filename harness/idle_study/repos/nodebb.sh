# NodeBB/NodeBB: mocha suite on Redis, as in .github/workflows/test.yaml (database=redis)
export TEST_ENV=production

setup() {
  redis_docker redis 6379 redis:8.10.1
  cp install/package.json package.json
  npm install --no-package-lock
  SETUP='{"url":"http://127.0.0.1:4567/forum","secret":"abcdef","admin:username":"admin","admin:email":"test@example.org","admin:password":"hAN3Eg8W","admin:password:confirm":"hAN3Eg8W","database":"redis","redis:host":"127.0.0.1","redis:port":6379,"redis:password":"","redis:database":0}'
  CI_CFG='{"host":"127.0.0.1","database":1,"port":6379}'
  node app --setup="$SETUP" --ci="$CI_CFG"
}

run_tests() {
  npx nyc --reporter=text-summary mocha --reporter xunit --reporter-option output="$JUNIT_DIR/mocha.xml"
}
