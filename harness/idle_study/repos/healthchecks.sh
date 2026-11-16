# healthchecks/healthchecks: Django test runner on Postgres, as in .github/workflows/tests.yml (db=postgres)
export DB=postgres DB_USER=runner DB_PASSWORD= SECRET_KEY=dummy-key

setup() {
  sudo systemctl start postgresql.service
  sudo -u postgres createuser -s runner
  sudo apt-get update -qq
  sudo apt-get install -y libcurl4-openssl-dev libpython3-dev libssl-dev
  python -m pip install --upgrade pip
  pip install -r requirements.txt -r requirements-dev.txt
}

run_tests() {
  python manage.py test -v 2
}
