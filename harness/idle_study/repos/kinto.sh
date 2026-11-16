# Kinto/kinto: unit + integration tests on Postgres, Redis, memcached, as in .github/workflows/test.yml (make tests-raw)
setup() {
  pg_docker postgres 5432 postgres -e POSTGRES_PASSWORD=postgres
  svc_docker memcached memcached -p 11211:11211
  redis_docker redis 6379 redis
  PGPASSWORD=postgres psql -c "CREATE DATABASE testdb ENCODING 'UTF8' TEMPLATE template0;" -U postgres -h localhost
  make install-dev
  make version-file || true
}

run_tests() {
  .venv/bin/py.test -n "$(serial_or 0 auto)" -p no:rerunfailures --junitxml="$JUNIT_DIR/pytest.xml"
}
