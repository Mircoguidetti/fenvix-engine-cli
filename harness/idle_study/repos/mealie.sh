# mealie-recipes/mealie: backend pytest -n auto --dist loadfile on Postgres + LDAP, as in .github/workflows/test-backend.yml (Database=postgres)
export PRODUCTION=False UV_FROZEN=1 DB_ENGINE=postgres POSTGRES_SERVER=localhost
export LDAP_AUTH_ENABLED=True LDAP_SERVER_URL=ldap://localhost:10389 LDAP_TLS_INSECURE=True LDAP_ENABLE_STARTTLS=False
export LDAP_BASE_DN='ou=people,dc=planetexpress,dc=com' LDAP_QUERY_BIND='cn=admin,dc=planetexpress,dc=com' LDAP_QUERY_PASSWORD=GoodNewsEveryone
export LDAP_USER_FILTER='(&(|({id_attribute}={input})({mail_attribute}={input}))(|(memberOf=cn=ship_crew,ou=people,dc=planetexpress,dc=com)(memberOf=cn=admin_staff,ou=people,dc=planetexpress,dc=com)))'
export LDAP_ADMIN_FILTER='memberOf=cn=admin_staff,ou=people,dc=planetexpress,dc=com'
export LDAP_ID_ATTRIBUTE=uid LDAP_NAME_ATTRIBUTE=cn LDAP_MAIL_ATTRIBUTE=mail

setup() {
  pg_docker postgres 5432 postgres -e POSTGRES_USER=mealie -e POSTGRES_PASSWORD=mealie -e POSTGRES_DB=mealie
  svc_docker ldap rroemhild/test-openldap -p 10389:10389 -p 10636:10636
  sudo apt-get update -qq
  sudo apt-get install -y libsasl2-dev libldap2-dev libssl-dev
  uv sync --group dev --extra pgsql
  sleep 10
}

run_tests() {
  uv run pytest -n auto --dist loadfile -p no:rerunfailures --junitxml="$JUNIT_DIR/pytest.xml"
}
