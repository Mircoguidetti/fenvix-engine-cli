# CTFd/CTFd: pytest -n auto on Postgres + Redis, as in .github/workflows/postgres.yml
export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
export TESTING_DATABASE_URL=postgres://postgres:password@localhost:5432/ctfd
export UV_PYTHON=3.11

setup() {
  pg_docker postgres 5432 postgres -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=ctfd -e POSTGRES_PASSWORD=password
  redis_docker redis 6379 redis
  sudo yarn install --non-interactive
  sudo rm -f /etc/boto.cfg
  uv sync
}

run_tests() {
  PYTEST_ADDOPTS="--junitxml=$JUNIT_DIR/pytest.xml -p no:rerunfailures" uv run make test
}
