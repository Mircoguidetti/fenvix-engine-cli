"""Django's test database reused with proof (row PY-04, founder decision 2026-11-21; ``detpy/_djangodb.py``).

Every case runs Django's own runner (``python -m detpy django manage.py test``) or pytest-django under ``--det`` and
checks three things: what the engine said (REUSED / REBUILT and why), that a reuse did not run ``migrate`` (a data
migration prints a marker), and that every outcome equals what a fresh build gives. The PostgreSQL cases start a
throw-away cluster when ``initdb`` is installed (skipped otherwise; the runner suites of release-1.yml install it).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from runners_util import run, write

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det needs sys.monitoring")
pytest.importorskip("django")

MANAGE = """
import os, sys
if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "proj.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
"""
SETTINGS = """
import os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET_KEY = "x"
INSTALLED_APPS = ["django.contrib.contenttypes", "django.contrib.auth", "app"]
DATABASES = {DATABASES}
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
"""
SQLITE = '{"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": os.path.join(BASE, "db.sqlite3")}}'
MODELS = """
from django.db import models

class Item(models.Model):
    name = models.CharField(max_length=20)
"""
M0001 = """
from django.db import migrations, models

class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [migrations.CreateModel(name="Item", fields=[
        ("id", models.AutoField(primary_key=True)), ("name", models.CharField(max_length=20))])]
"""
M0002 = """
import os
from django.db import migrations

def seed(apps, schema_editor):
    from app import helpers
    print("MIGRATION-RAN")
    apps.get_model("app", "Item").objects.create(name=helpers.name() + os.environ.get("SEED_SUFFIX", ""))

class Migration(migrations.Migration):
    dependencies = [("app", "0001_initial")]
    operations = [migrations.RunPython(seed)]
"""
HELPERS = """
def name():
    return "seed"
"""
TESTS = """
from django.test import TestCase, TransactionTestCase
from app.models import Item

class Seeded(TestCase):
    def test_seed(self):
        self.assertEqual([i.name for i in Item.objects.all()], ["seed"])

    def test_write(self):
        Item.objects.create(name="added")
        self.assertEqual(Item.objects.count(), 2)

class Committed(TransactionTestCase):
    serialized_rollback = True

    def test_commit(self):
        Item.objects.create(name="committed")
        self.assertEqual(Item.objects.count(), 2)
"""
IDS = {"site/app/tests.py::Seeded::test_seed", "site/app/tests.py::Seeded::test_write",
       "site/app/tests.py::Committed::test_commit"}
EPOCH = "--det-epoch=2030-01-01T00:00:00"


def project(root: Path, databases: str = SQLITE) -> None:
    write(root, {"site/manage.py": MANAGE, "site/proj/__init__.py": "",
                 "site/proj/settings.py": SETTINGS.replace("{DATABASES}", databases),
                 "site/app/__init__.py": "", "site/app/models.py": MODELS, "site/app/helpers.py": HELPERS,
                 "site/app/migrations/__init__.py": "", "site/app/migrations/0001_initial.py": M0001,
                 "site/app/migrations/0002_seed.py": M0002, "site/app/tests.py": TESTS})


def dj(root: Path, *args, env=None, cache=False, det=True, det_args=()):
    return run("django", root, "site/manage.py", "test", "app", "--noinput", *args, cache=cache, det=det,
               det_args=[EPOCH, *det_args], safe_path=True, env=env)


def notes(r) -> list[str]:
    return [line for line in r.out.splitlines() if "test database 'default'" in line]


def reused(r) -> bool:
    return any("REUSED" in n for n in notes(r))


def ran_migrate(r) -> bool:
    return "MIGRATION-RAN" in r.out


def assert_all_pass(r):
    assert set(r.outcomes) == IDS and set(r.outcomes.values()) == {"passed"}, r


# -- SQLite (Django's in-memory test database) -------------------------------------------------------------------------

def test_second_run_reuses_the_template_and_skips_migrate(tmp_path):
    root = tmp_path / "p"
    project(root)
    a = dj(root)
    assert_all_pass(a)
    assert ran_migrate(a) and not reused(a) and any("REBUILT (no template yet)" in n for n in notes(a)), a
    b = dj(root)
    assert_all_pass(b)
    assert reused(b) and not ran_migrate(b), b
    # the setup is not an event of any test: a build and a reuse give the same fingerprints
    assert a.fingerprints == b.fingerprints and len(a.fingerprints) == 3, (a.fingerprints, b.fingerprints)
    # what the first run's tests wrote never reaches the template: the third run starts clean again
    c = dj(root)
    assert_all_pass(c)
    assert reused(c), c


def test_two_reusing_runs_verify_identical(tmp_path):
    root = tmp_path / "p"
    project(root)
    dj(root)
    t = [tmp_path / "v1.jsonl", tmp_path / "v2.jsonl"]
    for p in t:
        r = dj(root, det_args=[f"--det-trace={p}"])
        assert reused(r), r
    v = subprocess.run([sys.executable, "-m", "detpy", "verify", "--json", str(t[0]), str(t[1])],
                       capture_output=True, text=True, cwd=root)
    rep = json.loads(v.stdout)
    assert rep["summary"]["diverged"] == 0 and rep["summary"]["missing"] == 0, v.stdout[:2000]


@pytest.mark.parametrize("edit, why", [
    ("migration", "migrations app.0002_seed"),
    ("helper", "code site/app/helpers.py"),
    ("env", "environment SEED_SUFFIX"),
    ("settings", "settings"),
    ("new-migration", "migrations app.0003_more"),
])
def test_a_change_rebuilds_and_outcomes_follow_it(tmp_path, edit, why):
    root = tmp_path / "p"
    project(root)
    assert_all_pass(dj(root))
    env = None
    if edit == "migration":
        write(root, {"site/app/migrations/0002_seed.py": M0002.replace('helpers.name()', '"other"')})
    elif edit == "helper":
        write(root, {"site/app/helpers.py": HELPERS.replace('"seed"', '"other"')})
    elif edit == "env":
        env = {"SEED_SUFFIX": "-x"}
    elif edit == "settings":
        write(root, {"site/proj/settings.py": SETTINGS.replace("{DATABASES}", SQLITE) + "\nLANGUAGE_CODE = 'de'\n"})
    elif edit == "new-migration":
        write(root, {"site/app/migrations/0003_more.py": M0002.replace('"0001_initial"', '"0002_seed"')})
    r = dj(root, env=env)
    fresh = dj(root, env=env, det_args=["--det-db=fresh"])
    assert not reused(r) and ran_migrate(r), r
    assert any(why in n for n in notes(r)), notes(r)
    assert r.outcomes == fresh.outcomes, (r, fresh)
    if edit != "settings":
        assert r.outcomes["site/app/tests.py::Seeded::test_seed"] == "failed", r
    # and the new state is itself reused next time
    again = dj(root, env=env)
    assert reused(again) and again.outcomes == r.outcomes, again


def test_an_altered_template_is_never_used(tmp_path):
    root = tmp_path / "p"
    project(root)
    dj(root)
    tpl = next((root / ".detpy" / "django-db").glob("*.sqlite3"))
    import sqlite3

    c = sqlite3.connect(tpl)
    c.execute("UPDATE app_item SET name = 'tampered'")
    c.commit()
    c.close()
    r = dj(root)
    assert not reused(r) and ran_migrate(r) and any("template missing or altered" in n for n in notes(r)), r
    assert_all_pass(r)


def test_fresh_and_keepdb_are_not_reuses(tmp_path):
    root = tmp_path / "p"
    project(root)
    dj(root)
    f = dj(root, det_args=["--det-db=fresh"])
    assert ran_migrate(f) and not notes(f), f
    k = dj(root, "--keepdb")
    assert any("--keepdb / --reuse-db given" in n for n in notes(k)), k


def test_with_the_cache_a_migration_change_reruns_and_fails(tmp_path):
    root = tmp_path / "p"
    project(root)
    a = dj(root, cache=True)
    assert_all_pass(a)
    b = dj(root, cache=True)
    assert reused(b) and b.outcomes == a.outcomes, b
    write(root, {"site/app/migrations/0002_seed.py": M0002.replace('helpers.name()', '"other"')})
    c = dj(root, cache=True)
    assert c.outcomes["site/app/tests.py::Seeded::test_seed"] == "failed", c
    assert "site/app/tests.py::Seeded::test_seed" not in c.reused, c


# -- pytest-django ------------------------------------------------------------------------------------------------------

def _pytest(root: Path, *extra, trace=None):
    out = root.parent / f"po-{time.monotonic_ns()}.json"
    cmd = [sys.executable, "-P", "-m", "pytest", "-p", "no:cacheprovider", "-q", "-s", "--det", EPOCH,
           f"--det-outcomes={out}", "--ds=proj.settings", "--rootdir", str(root), *extra, "site/app/tests.py"]
    if trace:
        cmd.append(f"--det-trace={trace}")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(root / "site"), os.environ.get("PYTHONPATH")])))
    p = subprocess.run(cmd, cwd=root, capture_output=True, text=True, env=env, timeout=600)
    data = json.loads(out.read_text()) if out.exists() else {}
    return p.returncode, p.stdout + p.stderr, data


def test_pytest_django_reuses_and_the_first_db_test_is_unchanged(tmp_path):
    pytest.importorskip("pytest_django")
    root = tmp_path / "p"
    project(root)
    _pytest(root)  # warm the engine's own first-run caches (bytecode), then forget the database
    shutil.rmtree(root / ".detpy" / "django-db")
    rc1, out1, d1 = _pytest(root)
    rc2, out2, d2 = _pytest(root)
    assert rc1 == 0 and rc2 == 0, out1 + out2
    assert "MIGRATION-RAN" in out1 and "REBUILT" in out1, out1
    assert "MIGRATION-RAN" not in out2 and "REUSED" in out2, out2
    assert d1["outcomes"] == d2["outcomes"] and len(d1["outcomes"]) == 3, (d1, d2)
    # the database is set up inside the first database test's setup: its clock and generators restart after it
    assert d1["fingerprints"] == d2["fingerprints"], (d1["fingerprints"], d2["fingerprints"])


# -- PostgreSQL ---------------------------------------------------------------------------------------------------------

def _pg_bin() -> Path | None:
    for d in sorted(Path("/usr/lib/postgresql").glob("*/bin"), reverse=True):
        if (d / "initdb").exists():
            return d
    w = shutil.which("initdb")
    return Path(w).parent if w else None


@pytest.fixture(scope="module")
def pg(tmp_path_factory):
    pytest.importorskip("psycopg")
    b = _pg_bin()
    if b is None:
        pytest.skip("no initdb (PostgreSQL server binaries) on this machine")
    pre = []
    if os.geteuid() == 0:  # initdb refuses root: run the cluster as the postgres user, in a directory it can reach
        if not shutil.which("runuser"):
            pytest.skip("running as root without runuser")
        import tempfile

        pre = ["runuser", "-u", "postgres", "--"]
        d = Path(tempfile.mkdtemp(prefix="fenvix-pg-", dir="/tmp"))
        os.chmod(d, 0o755)
        subprocess.run(["chown", "postgres", str(d)], check=True)
    else:
        d = tmp_path_factory.mktemp("pg")
    data, sock = d / "data", d / "sock"
    subprocess.run(pre + ["mkdir", str(sock)], check=True)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    subprocess.run(pre + [str(b / "initdb"), "-D", str(data), "-U", "postgres", "--auth=trust", "-E", "UTF8"],
                   check=True, capture_output=True)
    subprocess.run(pre + [str(b / "pg_ctl"), "-D", str(data), "-o", f"-p {port} -k {sock} -h 127.0.0.1", "-w",
                          "-l", str(d / "log"), "start"], check=True, capture_output=True)
    yield port
    subprocess.run(pre + [str(b / "pg_ctl"), "-D", str(data), "-m", "immediate", "stop"], capture_output=True)


def _pg_dbs(port: int) -> dict:
    import psycopg

    with psycopg.connect(f"host=127.0.0.1 port={port} user=postgres dbname=postgres", autocommit=True) as c:
        return {r[0]: (r[1], r[2]) for r in c.execute(
            "SELECT datname, datistemplate, datallowconn FROM pg_database WHERE datname LIKE 'fenvix_tpl_%'")}


def test_postgres_template_sealed_reused_and_rebuilt(tmp_path, pg):
    root = tmp_path / "p"
    project(root, '{"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "app%s", "USER": "postgres",'
                  ' "HOST": "127.0.0.1", "PORT": "%d"}}' % (tmp_path.name[-8:].lower().replace("-", "_"), pg))
    a = dj(root)
    assert_all_pass(a)
    assert ran_migrate(a) and "REBUILT" in "".join(notes(a)), a
    tpls = _pg_dbs(pg)
    assert len(tpls) >= 1 and all(v == (True, False) for v in tpls.values()), tpls  # sealed: no connections
    b = dj(root)
    assert_all_pass(b)
    assert reused(b) and not ran_migrate(b), b
    assert a.fingerprints == b.fingerprints
    write(root, {"site/app/helpers.py": HELPERS.replace('"seed"', '"other"')})
    c = dj(root)
    assert not reused(c) and any("code site/app/helpers.py" in n for n in notes(c)), c
    assert c.outcomes["site/app/tests.py::Seeded::test_seed"] == "failed", c
    # the old template was replaced, not kept beside the new one
    assert len(_pg_dbs(pg)) == len(tpls), _pg_dbs(pg)


def test_postgres_parallel_workers_get_their_own_copy(tmp_path, pg):
    root = tmp_path / "p"
    project(root, '{"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "par%s", "USER": "postgres",'
                  ' "HOST": "127.0.0.1", "PORT": "%d"}}' % (tmp_path.name[-8:].lower().replace("-", "_"), pg))
    dj(root)
    r = dj(root, "--parallel", "2")
    assert_all_pass(r)
    assert reused(r), r
