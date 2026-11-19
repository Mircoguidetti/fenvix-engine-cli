"""Holes found while building the other runners' shells that the pytest path had too (``--det-cache`` under pytest):

* Django's cached template loader (pytest-django): a template the loader returns from memory was an input of the
  first test that rendered it only (``detpy/_django.py``);
* a ``unittest.TestCase`` class run by pytest: its methods share class state, so the class is the unit of reuse
  (``proofcache._unittest_units``), as under ``python -m detpy unittest``.

Each test fails on the commit before the fix (the second renderer / the second method was reused as passed while a
fresh run fails)."""

from __future__ import annotations

import sys

import pytest

from test_proofcache import project, run_cache  # noqa: F401 (fixture)

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")

SETTINGS = """
import os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET_KEY = "x"
INSTALLED_APPS = ["django.contrib.contenttypes", "django.contrib.auth", "app"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True}]
USE_TZ = True
"""

TESTS = """
from django.template.loader import render_to_string

def test_render_a():
    assert render_to_string("app/hello.html", {"name": "a"}).strip() == "Hello a"

def test_render_b():
    assert render_to_string("app/hello.html", {"name": "b"}).strip() == "Hello b"
"""


def test_template_from_the_cached_loader_is_an_input_of_every_renderer_under_pytest_django(pytester, run_cache):
    pytest.importorskip("pytest_django")
    project(pytester, **{"proj/__init__.py": "", "proj/settings.py": SETTINGS, "app/__init__.py": "",
                         "app/templates/app/hello.html": "Hello {{ name }}\n", "test_t.py": TESTS})
    pytester.makeini("[pytest]\nDJANGO_SETTINGS_MODULE = proj.settings\n")
    r, reused, _ = run_cache()
    r.assert_outcomes(passed=2)
    _, reused, _ = run_cache()
    assert reused == {"test_t.py::test_render_a", "test_t.py::test_render_b"}
    (pytester.path / "app/templates/app/hello.html").write_text("Hi {{ name }}\n")
    r, reused, _ = run_cache()
    assert reused == set()
    r.assert_outcomes(failed=2)


def test_unittest_class_is_the_unit_of_reuse_under_pytest(pytester, run_cache):
    src = """
        import unittest

        class S(unittest.TestCase):
            seen = []

            def test_a(self):
                self.seen.append(1)

            def test_b(self):
                self.assertEqual(len(self.seen), 1)

        class Other(unittest.TestCase):
            def test_c(self):
                pass
        """
    project(pytester, **{"test_s.py": src})
    run_cache()
    import textwrap

    changed = textwrap.dedent(src).replace("self.seen.append(1)", "self.seen.extend([1, 2])")
    (pytester.path / "test_s.py").write_text(changed)
    r, reused, data = run_cache()
    assert reused == {"test_s.py::Other::test_c"}
    assert data["cache"]["miss_ids"]["test_s.py::S::test_b"] == "unit: test_s.py::S::test_a runs"
    r.assert_outcomes(passed=2, failed=1)
