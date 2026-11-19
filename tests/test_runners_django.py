"""``python -m detpy django site/manage.py test app``: controls and adversarial cases (the shared table as Django
``SimpleTestCase`` tests, plus Django's own: JSON fixtures, templates through the cached loader, the settings
module, migrations, ``--parallel``, the group order under a shuffle)."""

from __future__ import annotations

import sys
import textwrap

import pytest

from runners_cases import CASES, PRELUDE, check_case, run_case
from runners_util import run, write

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
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
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": os.path.join(BASE, "db.sqlite3")}}
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True}]
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
"""
MODELS = """
from django.db import models

class Item(models.Model):
    name = models.CharField(max_length=20)
"""
MIGRATION = """
from django.db import migrations, models

class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [migrations.CreateModel(name="Item", fields=[
        ("id", models.AutoField(primary_key=True)), ("name", models.CharField(max_length=20, default="{default}"))])]
"""


def project(root, tests: str, **extra) -> None:
    files = {"site/manage.py": MANAGE, "site/proj/__init__.py": "", "site/proj/settings.py": SETTINGS,
             "site/app/__init__.py": "", "site/app/models.py": MODELS, "site/app/migrations/__init__.py": "",
             "site/app/migrations/0001_initial.py": MIGRATION.replace("{default}", "d"),
             "site/app/tests.py": tests}
    files.update(extra)
    write(root, files)


def dj(root, *args, **kw):
    kw.setdefault("safe_path", True)
    return run("django", root, "site/manage.py", "test", "app", *args, **kw)


# -- controls -------------------------------------------------------------------------------------------------------
CONTROL_TESTS = """
import random, time
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.utils import timezone
from app.models import Item

class Plain(SimpleTestCase):
    def test_clock(self):
        self.assertEqual(int(timezone.now().timestamp()), 1893456000)

    def test_random(self):
        print(random.random())

class Db(TestCase):
    def test_a(self):
        Item.objects.create(name="a")
        self.assertEqual(Item.objects.count(), 1)

    def test_b(self):
        self.assertEqual(Item.objects.count(), 0)

class Tx(TransactionTestCase):
    def test_t1(self):
        Item.objects.create(name="t")

    def test_t2(self):
        pass
"""


def test_two_det_runs_give_identical_fingerprints(tmp_path):
    root = tmp_path / "p"
    project(root, CONTROL_TESTS)
    a = dj(root, cache=False, det_args=["--det-epoch=2030-01-01T00:00:00"])
    b = dj(root, cache=False, det_args=["--det-epoch=2030-01-01T00:00:00"])
    assert len(a.outcomes) == 6 and set(a.outcomes.values()) == {"passed"}, a
    assert a.fingerprints == b.fingerprints


def test_seeded_shuffle_keeps_django_groups(tmp_path):
    root = tmp_path / "p"
    project(root, CONTROL_TESTS)
    orders = [dj(root, cache=False, det_args=[f"--det-seed={s}", "--det-epoch=2030-01-01T00:00:00"]).order
              for s in (1, 1, 2, 3)]
    assert orders[0] == orders[1]
    assert len(set(map(tuple, orders))) >= 2
    for o in orders:
        groups = ["Db" if "::Db::" in i else "other" for i in o]
        # Django's reorder_by: TestCase first
        assert groups[:2] == ["Db", "Db"], o


def test_parallel_is_forced_to_one(tmp_path):
    root = tmp_path / "p"
    project(root, CONTROL_TESTS)
    r = dj(root, "--parallel", "2", cache=False, det_args=["--det-epoch=2030-01-01T00:00:00"])
    assert "Django --parallel 2 -> 1 under --det" in r.out, r
    assert len(r.fingerprints) == 6 and set(r.outcomes.values()) == {"passed"}, r


# -- shared adversarial cases ----------------------------------------------------------------------------------------
def _tests(c) -> str:
    body = textwrap.indent(c["body"], " " * 8)
    return (PRELUDE + c["prelude"] + "from django.test import SimpleTestCase\n\n\nclass C(SimpleTestCase):\n"
            "    def test_control(self):\n        self.assertEqual(1 + 1, 2)\n\n\nclass T(SimpleTestCase):\n"
            "    def test_x(self):\n" + body + "\n")


@pytest.mark.parametrize("c", CASES, ids=[c["name"] for c in CASES])
def test_wrong_reuse(tmp_path, c):
    if c["name"] == "timezone_read_by_c":
        pytest.skip("Django sets TZ from settings.TIME_ZONE (time.tzset) at start-up: the settings test covers it")
    if c["name"].startswith("env_"):
        # Django's test client imports wsgiref.handlers, which reads the whole environment at import time: every
        # Django test depends on every variable (the same under pytest-django); the unrelated control re-runs too
        c = dict(c, control=False)
    root = tmp_path / "p"
    project(root, "")
    first, second = run_case(c, lambda r, env: dj(r, env=env), root,
                             lambda r, c: (r / "site" / "app" / "tests.py").write_text(_tests(c)), root / "site")
    check_case(c, first, second, "site/app/tests.py::T::test_x", "site/app/tests.py::C::test_control")


# -- Django's own ----------------------------------------------------------------------------------------------------
def test_json_fixture_change_reruns_its_testcase(tmp_path):
    root = tmp_path / "p"
    tests = """
        from django.test import TestCase, SimpleTestCase
        from app.models import Item

        class Fix(TestCase):
            fixtures = ["items.json"]

            def test_fixture(self):
                self.assertEqual(Item.objects.get(pk=1).name, "one")

        class Other(SimpleTestCase):
            def test_other(self):
                pass
        """
    fixture = '[{"model": "app.item", "pk": 1, "fields": {"name": "%s"}}]'
    project(root, tests, **{"site/app/fixtures/items.json": fixture % "one"})
    dj(root)
    write(root, {"site/app/fixtures/items.json": fixture % "two"})
    r = dj(root)
    assert r.outcomes["site/app/tests.py::Fix::test_fixture"] == "failed" and r.reused == {
        "site/app/tests.py::Other::test_other"}, r


def test_template_from_the_cached_loader_is_an_input_of_every_renderer(tmp_path):
    # the second render comes from the cached loader's memory: without detpy's re-read, the template is an input
    # of test_render_a only, and test_render_b keeps its old pass after the template changes
    root = tmp_path / "p"
    tests = """
        from django.test import SimpleTestCase
        from django.template.loader import render_to_string

        class TplA(SimpleTestCase):
            def test_render_a(self):
                self.assertEqual(render_to_string("app/hello.html", {"name": "a"}).strip(), "Hello a")

        class TplB(SimpleTestCase):
            def test_render_b(self):
                self.assertEqual(render_to_string("app/hello.html", {"name": "b"}).strip(), "Hello b")

            def test_missing(self):
                from django.template import TemplateDoesNotExist
                with self.assertRaises(TemplateDoesNotExist):
                    render_to_string("app/missing.html")
        """
    project(root, tests, **{"site/app/templates/app/hello.html": "Hello {{ name }}\n"})
    dj(root)
    assert dj(root).reused == {"site/app/tests.py::TplA::test_render_a", "site/app/tests.py::TplB::test_render_b",
                               "site/app/tests.py::TplB::test_missing"}
    write(root, {"site/app/templates/app/hello.html": "Hi {{ name }}\n"})
    r = dj(root)
    assert r.outcomes["site/app/tests.py::TplB::test_render_b"] == "failed", r
    write(root, {"site/app/templates/app/hello.html": "Hello {{ name }}\n", "site/app/templates/app/missing.html": "m"})
    r = dj(root)
    assert r.outcomes["site/app/tests.py::TplB::test_missing"] == "failed", r


def test_settings_module_change_is_configuration(tmp_path):
    root = tmp_path / "p"
    tests = """
        from django.conf import settings
        from django.test import SimpleTestCase

        class S(SimpleTestCase):
            def test_flag(self):
                self.assertFalse(getattr(settings, "DETPY_FLAG", False))
        """
    project(root, tests, **{"site/proj/settings_b.py": "from proj.settings import *\nDETPY_FLAG = True\n"})
    dj(root)
    assert dj(root).reused == {"site/app/tests.py::S::test_flag"}
    r = dj(root, "--settings", "proj.settings_b")
    assert r.reused == set() and r.outcomes["site/app/tests.py::S::test_flag"] == "failed", r
    r = dj(root, env={"DJANGO_SETTINGS_MODULE": "proj.settings_b"})
    assert r.reused == set() and r.outcomes["site/app/tests.py::S::test_flag"] == "failed", r


DATA_MIGRATION = """
from django.db import migrations

def seed(apps, schema_editor):
    apps.get_model("app", "Item").objects.create(name="{name}")

class Migration(migrations.Migration):
    dependencies = [("app", "0001_initial")]
    operations = [migrations.RunPython(seed)]
"""


def test_migration_change_reruns_database_tests(tmp_path):
    root = tmp_path / "p"
    tests = """
        from django.test import TestCase
        from app.models import Item

        class M(TestCase):
            def test_seeded(self):
                self.assertEqual(Item.objects.get().name, "seed")
        """
    project(root, tests, **{"site/app/migrations/0002_seed.py": DATA_MIGRATION.replace("{name}", "seed")})
    a = dj(root)
    assert a.outcomes == {"site/app/tests.py::M::test_seeded": "passed"}, a
    write(root, {"site/app/migrations/0002_seed.py": DATA_MIGRATION.replace("{name}", "other")})
    r = dj(root)
    assert r.reused == set() and r.outcomes["site/app/tests.py::M::test_seeded"] == "failed", r
