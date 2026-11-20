"""``python -m detpy zope-testrunner``: controls and adversarial cases (the shared table as unittest cases found by
zope.testrunner, plus its own: layer set-up reading a file, a fully reused layer not set up, ``test_suite()``, ``-j``)."""

from __future__ import annotations

import sys
import textwrap

import pytest

from runners_cases import CASES, PRELUDE, check_case, run_case
from runners_util import run, write

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
pytest.importorskip("zope.testrunner")


def zt(root, *args, **kw):
    return run("zope-testrunner", root, "--path=src", *args, **kw)


def pkg(root, tests: dict) -> None:
    files = {"src/pkg/__init__.py": "", "src/pkg/tests/__init__.py": ""}
    files.update({f"src/pkg/tests/{k}": v for k, v in tests.items()})
    write(root, files)


LAYERED = """
import os, unittest

class Layer:
    @classmethod
    def setUp(cls):
        cls.value = open("layer.txt").read()
        open(os.environ.get("ZT_MARK", os.devnull), "a").write("setup\\n")

    @classmethod
    def tearDown(cls):
        pass

class LT(unittest.TestCase):
    layer = Layer

    def test_layer(self):
        self.assertEqual(Layer.value, "1\\n")

class U(unittest.TestCase):
    def test_unit(self):
        import random, time
        print(random.random(), time.time())
"""


def test_two_det_runs_give_identical_fingerprints(tmp_path):
    root = tmp_path / "p"
    pkg(root, {"test_z.py": LAYERED})
    write(root, {"layer.txt": "1\n"})
    a = zt(root, cache=False)
    b = zt(root, cache=False)
    assert set(a.outcomes.values()) == {"passed"} and len(a.outcomes) == 2, a
    assert a.fingerprints == b.fingerprints


def test_seeded_shuffle_is_reproducible(tmp_path):
    root = tmp_path / "p"
    pkg(root, {f"test_m{m}.py": "import unittest\n" + "".join(
        f"\nclass C{c}(unittest.TestCase):\n" + "".join(f"    def test_{t}(self):\n        pass\n" for t in "abc")
        for c in range(3)) for m in range(2)})
    s5 = zt(root, cache=False, det_args=["--det-seed=5"])
    s5b = zt(root, cache=False, det_args=["--det-seed=5"])
    s6 = zt(root, cache=False, det_args=["--det-seed=6"])
    assert len(s5.order) == 18 and s5.order == s5b.order and s5.order != s6.order


def test_controls_are_active_inside_zope_tests(tmp_path):
    root = tmp_path / "p"
    pkg(root, {"test_c.py": """
        import os, time, unittest

        class C(unittest.TestCase):
            def test_clock(self):
                self.assertEqual(int(time.time()), 1893456000)

            def test_hash_seed(self):
                self.assertEqual(os.environ.get("PYTHONHASHSEED"), "0")
        """})
    r = zt(root, cache=False, det_args=["--det-epoch=2030-01-01T00:00:00"])
    assert set(r.outcomes.values()) == {"passed"} and len(r.outcomes) == 2, r


def _module(c) -> str:
    body = textwrap.indent(c["body"], " " * 8)
    return (PRELUDE + c["prelude"] + "import unittest\n\n\nclass C(unittest.TestCase):\n    def test_control(self):\n"
            "        self.assertEqual(1 + 1, 2)\n\n\nclass T(unittest.TestCase):\n    def test_x(self):\n" + body + "\n")


@pytest.mark.parametrize("c", CASES, ids=[c["name"] for c in CASES])
def test_wrong_reuse(tmp_path, c):
    root = tmp_path / "p"
    pkg(root, {})
    first, second = run_case(c, lambda r, env: zt(r, env=env, safe_path=True), root,
                             lambda r, c: (r / "src/pkg/tests/test_case.py").write_text(_module(c)), root / "src")
    check_case(c, first, second, "src/pkg/tests/test_case.py::T::test_x", "src/pkg/tests/test_case.py::C::test_control")


def test_layer_setup_read_is_an_input_and_a_reused_layer_is_not_set_up(tmp_path):
    root = tmp_path / "p"
    mark = tmp_path / "mark.txt"
    pkg(root, {"test_z.py": LAYERED})
    write(root, {"layer.txt": "1\n"})
    env = {"ZT_MARK": str(mark)}
    zt(root, env=env)
    assert mark.read_text() == "setup\n"
    again = zt(root, env=env)
    assert again.reused == {"src/pkg/tests/test_z.py::LT::test_layer", "src/pkg/tests/test_z.py::U::test_unit"}, again
    assert mark.read_text() == "setup\n"  # every test of the layer reused: not set up
    write(root, {"layer.txt": "2\n"})
    r = zt(root, env=env)
    assert r.outcomes["src/pkg/tests/test_z.py::LT::test_layer"] == "failed", r
    assert r.reused == {"src/pkg/tests/test_z.py::U::test_unit"}, r


def test_test_suite_function_reads_are_inputs(tmp_path):
    root = tmp_path / "p"
    pkg(root, {"test_s.py": """
        import unittest

        class P(unittest.TestCase):
            value = None

            def test_value(self):
                self.assertEqual(self.value, "1")

        def test_suite():
            P.value = open("param.txt").read().strip()
            return unittest.defaultTestLoader.loadTestsFromTestCase(P)
        """, "test_o.py": "import unittest\n\nclass O(unittest.TestCase):\n    def test_o(self):\n        pass\n"})
    write(root, {"param.txt": "1\n"})
    zt(root)
    write(root, {"param.txt": "2\n"})
    r = zt(root)
    assert r.outcomes["src/pkg/tests/test_s.py::P::test_value"] == "failed", r
    assert r.reused == {"src/pkg/tests/test_o.py::O::test_o"}, r


def test_processes_forced_to_one(tmp_path):
    root = tmp_path / "p"
    pkg(root, {"test_z.py": LAYERED})
    write(root, {"layer.txt": "1\n"})
    r = zt(root, "-j", "2", cache=False)
    assert "zope.testrunner -j 2 -> 1 under --det" in r.out and len(r.fingerprints) == 2, r
