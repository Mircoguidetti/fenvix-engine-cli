# litestar-org/litestar-fullstack: pytest; pytest-databases starts Postgres and Redis containers from inside the suite (.github/workflows/ci.yaml)
setup() {
  uv sync --all-groups
  make build-emails
  # (run 1 includes pulling the images the suite starts; the median over runs does not)
}

run_tests() {
  uv run pytest src/py/tests -n "$(serial_or 0 auto)" -p no:rerunfailures --junitxml="$JUNIT_DIR/pytest.xml"
}
