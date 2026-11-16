"""pytest-django's test groups are kept under --det (fixed order and --det-seed).

pytest-django runs TestCase tests first, then transactional tests (which flush
the database), then tests without a database. Undoing that order made TestCase
tests that read rows created by a data migration fail under --det only."""

import pytest

from test_order import executed

# Stand-in for pytest-django, registered under its plugin name "django": a stable
# sort by group, like pytest_django.plugin.pytest_collection_modifyitems.
FAKE_DJANGO = """
GROUP = {"tc": 0, "ttc": 1, "plain": 2}

def pytest_collection_modifyitems(items):
    items.sort(key=lambda i: GROUP[i.name.split("_")[1]])
"""

MODULES = {
    f"test_m{m}": "\n".join(
        [f"def test_plain_{t}(): pass" for t in range(3)]
        + [f"def test_ttc_{t}(): pass" for t in range(3)]
        + [f"def test_tc_{t}(): pass" for t in range(3)]
    )
    for m in range(3)
}


def groups(nodeids):
    return [n.split("::")[1].split("_")[1] for n in nodeids]


def first_change(seq):
    return [s for i, s in enumerate(seq) if i == 0 or seq[i - 1] != s]


@pytest.fixture
def project(pytester):
    pytester.makepyfile(fake_django=FAKE_DJANGO, **MODULES)


def _run(run_det, pytester, *args):
    pytester.syspathinsert()
    pytester.makeconftest(
        "import fake_django\n"
        "def pytest_configure(config):\n"
        "    pm = config.pluginmanager\n"
        "    real = pm.get_plugin('django')  # real pytest-django, unconfigured here\n"
        "    if real is not None:\n"
        "        pm.unregister(real, name='django')\n"
        "    pm.register(fake_django, 'django')\n"
    )
    return run_det(*args)


def test_fixed_order_keeps_django_groups(pytester, run_det, project):
    r, t = _run(run_det, pytester)
    r.assert_outcomes(passed=27)
    order = executed(t)
    assert first_change(groups(order)) == ["tc", "ttc", "plain"]
    # inside a group: collection order
    assert order[:3] == [f"test_m0.py::test_tc_{i}" for i in range(3)]
    assert any("pytest-django" in a for a in t[0]["meta"]["adjustments"])


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_seeded_order_shuffles_inside_django_groups(pytester, run_det, project, seed):
    _, fixed = _run(run_det, pytester)
    _, a = run_det(f"--det-seed={seed}")
    _, b = run_det(f"--det-seed={seed}")
    assert executed(a) == executed(b)
    assert first_change(groups(executed(a))) == ["tc", "ttc", "plain"]
    assert sorted(executed(a)) == sorted(executed(fixed))
    assert executed(a) != executed(fixed)


def test_without_pytest_django_order_is_unchanged(pytester, run_det):
    pytester.makepyfile(**MODULES)
    _, t = run_det()
    assert executed(t)[0] == "test_m0.py::test_plain_0"
    assert not any("pytest-django" in a for a in t[0]["meta"]["adjustments"])


DJANGO_PROJECT = {
    "proj/__init__.py": "",
    "proj/settings.py": (
        'SECRET_KEY = "x"\nINSTALLED_APPS = ["django.contrib.contenttypes", "shop"]\n'
        'DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": "db.sqlite3"}}\n'
        'DEFAULT_AUTO_FIELD = "django.db.models.AutoField"\n'
    ),
    "shop/__init__.py": "",
    "shop/models.py": (
        "from django.db import models\n"
        "class Item(models.Model):\n    name = models.CharField(max_length=50)\n"
    ),
    "shop/migrations/__init__.py": "",
    "shop/migrations/0001_initial.py": (
        "from django.db import migrations, models\n"
        "class Migration(migrations.Migration):\n    initial = True\n    dependencies = []\n"
        "    operations = [migrations.CreateModel('Item', [('id', models.AutoField(primary_key=True)),"
        " ('name', models.CharField(max_length=50))])]\n"
    ),
    "shop/migrations/0002_seed.py": (
        "from django.db import migrations\n"
        "def seed(apps, schema_editor):\n    apps.get_model('shop', 'Item').objects.create(name='default')\n"
        "class Migration(migrations.Migration):\n    dependencies = [('shop', '0001_initial')]\n"
        "    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]\n"
    ),
    # collected first: flushes the table, including the migration's row
    "test_a_flush.py": (
        "from django.test import TransactionTestCase\nfrom shop.models import Item\n"
        "class FlushTests(TransactionTestCase):\n"
        "    def test_flush_1(self):\n        Item.objects.create(name='tmp')\n"
        "    def test_flush_2(self):\n        assert Item.objects.count() >= 0\n"
    ),
    "test_b_seed.py": (
        "from django.test import TestCase\nfrom shop.models import Item\n"
        "class SeedTests(TestCase):\n"
        "    def test_seed_exists(self):\n        assert Item.objects.filter(name='default').exists()\n"
        "    def test_seed_count(self):\n        assert Item.objects.count() == 1\n"
    ),
}


@pytest.mark.parametrize("args", [(), ("--det-seed=2",), ("--det-seed=3",)])
def test_real_pytest_django_data_migration(pytester, run_det, args):
    """End to end with the real pytest-django (skipped when it is not installed)."""
    pytest.importorskip("pytest_django")
    pytest.importorskip("django")
    for path, text in DJANGO_PROJECT.items():
        p = pytester.path / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    pytester.makeini("[pytest]\nDJANGO_SETTINGS_MODULE = proj.settings\npythonpath = .\n")
    r, t = run_det(*args)
    r.assert_outcomes(passed=4)
    assert [n.split("::")[0] for n in executed(t)][:2] == ["test_b_seed.py"] * 2
