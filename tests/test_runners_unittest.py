"""``python -m detpy unittest``: controls (identical fingerprints, the seeded shuffle, the controls active inside
tests) and adversarial wrong-reuse cases (the shared table ``runners_cases.CASES`` plus unittest's own: class state,
``setUpClass`` / ``setUpModule`` / ``load_tests`` reads, discovery pattern, a new module, class tear-down errors)."""

from __future__ import annotations

import sys
import textwrap

import pytest

from runners_cases import CASES, PRELUDE, check_case, run_case
from runners_util import run, write

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


def ut(root, *args, **kw):
    return run("unittest", root, *args, **kw)


# -- controls -------------------------------------------------------------------------------------------------------
DET_MODULE = """
import os, random, time, unittest

class Clock(unittest.TestCase):
    def test_time(self):
        t0 = time.time()
        time.sleep(5)
        self.assertGreaterEqual(time.time() - t0, 5)

    def test_random(self):
        self.assertIsInstance(random.random(), float)

class Order(unittest.TestCase):
    def test_set_order(self):
        print(list({"alpha", "beta", "gamma", "delta"}))

    def test_listing(self):
        print(os.listdir("."))
"""


def test_two_det_runs_give_identical_fingerprints(tmp_path):
    root = tmp_path / "p"
    write(root, {"test_det.py": DET_MODULE, "zz.txt": "", "aa.txt": ""})
    a = ut(root, cache=False)
    b = ut(root, cache=False)
    assert a.outcomes and set(a.outcomes.values()) == {"passed"}, a
    assert len(a.fingerprints) == 4 and a.fingerprints == b.fingerprints, (a, b)
    assert a.order == b.order


SHUFFLE = {f"test_m{m}.py": "import unittest\n" + "".join(
    f"\nclass C{c}(unittest.TestCase):\n" + "".join(f"    def test_{t}(self):\n        pass\n" for t in "abcd")
    for c in range(3)) for m in range(3)}


def _contiguous(order):
    groups = [i.rsplit("::", 1)[0] for i in order]
    seen, last = set(), None
    for g in groups:
        if g != last:
            assert g not in seen, f"class {g} split: {order}"
            seen.add(g)
            last = g


def test_seeded_shuffle_is_reproducible_and_keeps_classes_together(tmp_path):
    root = tmp_path / "p"
    write(root, SHUFFLE)
    fixed = ut(root, cache=False)
    s5 = ut(root, cache=False, det_args=["--det-seed=5"])
    s5b = ut(root, cache=False, det_args=["--det-seed=5"])
    s6 = ut(root, cache=False, det_args=["--det-seed=6"])
    assert len(fixed.order) == 36 and sorted(fixed.order) == sorted(s5.order) == sorted(s6.order)
    assert s5.order == s5b.order
    assert s5.order != s6.order
    assert s5.order != fixed.order
    for o in (fixed.order, s5.order, s6.order):
        _contiguous(o)
    assert set(s5.outcomes.values()) == {"passed"}


CONTROLS_MODULE = """
import os, random, socket, time, unittest
import detpy

class Controls(unittest.TestCase):
    def test_virtual_clock(self):
        self.assertEqual(int(time.time()), 1893456000)  # --det-epoch=2030-01-01T00:00:00

    def test_seeded_random(self):
        print("RANDOM", random.random())

    def test_network_closed(self):
        with self.assertRaises(detpy.NetworkBlockedError):
            socket.create_connection(("192.0.2.1", 80), timeout=1)

    def test_hash_seed(self):
        self.assertEqual(os.environ.get("PYTHONHASHSEED"), "0")
"""


def test_controls_are_active_inside_unittest_tests(tmp_path):
    root = tmp_path / "p"
    write(root, {"test_ctl.py": CONTROLS_MODULE})
    a = ut(root, "-v", cache=False, det_args=["--det-epoch=2030-01-01T00:00:00"])
    b = ut(root, "-v", cache=False, det_args=["--det-epoch=2030-01-01T00:00:00"])
    assert a.outcomes and set(a.outcomes.values()) == {"passed"}, a
    ra = [line for line in a.out.splitlines() if "RANDOM" in line]
    rb = [line for line in b.out.splitlines() if "RANDOM" in line]
    assert ra and ra == rb


HYPOTHESIS_MODULE = """
import unittest
from hypothesis import given, settings, strategies as st

class H(unittest.TestCase):
    @given(st.integers())
    def test_ints(self, x):
        self.assertIsInstance(x, int)

    def test_database_off(self):
        self.assertIsNone(settings().database)
"""


def test_hypothesis_is_seeded_per_test_and_has_no_database(tmp_path):
    pytest.importorskip("hypothesis")
    root = tmp_path / "p"
    write(root, {"test_h.py": HYPOTHESIS_MODULE})
    a = ut(root, cache=False)
    b = ut(root, cache=False)
    assert set(a.outcomes.values()) == {"passed"}, a
    assert a.fingerprints == b.fingerprints
    # the same test alone (the other one not run first): the same examples, the same fingerprint
    c = ut(root, "test_h.H.test_ints", cache=False)
    assert c.fingerprints["test_h.py::H::test_ints"] == a.fingerprints["test_h.py::H::test_ints"]


def test_reused_results_are_reported_to_the_runner(tmp_path):
    root = tmp_path / "p"
    write(root, {"test_r.py": """
        import unittest

        class R(unittest.TestCase):
            def test_ok(self):
                pass

            @unittest.skip("not here")
            def test_skip(self):
                pass

            @unittest.expectedFailure
            def test_xfail(self):
                self.assertEqual(1, 2)
        """})
    a = ut(root, "-v")
    b = ut(root, "-v")
    assert b.reused == {"test_r.py::R::test_ok", "test_r.py::R::test_skip", "test_r.py::R::test_xfail"}, b
    assert b.outcomes == a.outcomes == {"test_r.py::R::test_ok": "passed", "test_r.py::R::test_skip": "skipped",
                                        "test_r.py::R::test_xfail": "xfailed"}
    assert "skipped 'not here'" in b.out and "expected failure" in b.out and "Ran 3 tests" in b.out
    assert b.code == 0


# -- shared adversarial cases ----------------------------------------------------------------------------------------
def _module(c) -> str:
    body = textwrap.indent(c["body"], " " * 8)
    return (PRELUDE + c["prelude"] + "import unittest\n\n\nclass C(unittest.TestCase):\n    def test_control(self):\n"
            "        self.assertEqual(1 + 1, 2)\n\n\nclass T(unittest.TestCase):\n    def test_x(self):\n" + body + "\n")


@pytest.mark.parametrize("c", CASES, ids=[c["name"] for c in CASES])
def test_wrong_reuse(tmp_path, c):
    # the tests live in tests/ (the importable directory); the data files the cases change are in the working
    # directory, kept off sys.path (python -P): its listing is then not an input of every test, so the unrelated
    # control test stays reusable)
    root = tmp_path / "p"
    (root / "tests").mkdir(parents=True)
    first, second = run_case(c, lambda r, env: ut(r, "discover", "-s", "tests", "-t", "tests", env=env,
                                                  safe_path=True), root,
                             lambda r, c: (r / "tests" / "test_case.py").write_text(_module(c)), root / "tests")
    check_case(c, first, second, "tests/test_case.py::T::test_x", "tests/test_case.py::C::test_control")


# -- unittest's own ----------------------------------------------------------------------------------------------------
def test_class_state_makes_the_class_the_unit_of_reuse(tmp_path):
    # test_b depends on what test_a left in the class: when test_a re-runs (its code changed), test_b re-runs too
    # (a per-method reuse would keep test_b's old pass; in a full run it fails)
    root = tmp_path / "p"
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
    write(root, {"test_s.py": src})
    ut(root)
    write(root, {"test_s.py": src.replace("self.seen.append(1)", "self.seen.extend([1, 2])")})
    r = ut(root)
    assert "test_s.py::S::test_b" not in r.reused and r.outcomes["test_s.py::S::test_b"] == "failed", r
    assert r.reused == {"test_s.py::Other::test_c"}, r
    receipts = (root.parent / "p-cache" / "receipts.jsonl").read_text()
    assert '"why": "unit: test_s.py::S::test_a runs"' in receipts


def test_setupclass_and_setupmodule_reads_are_inputs_of_their_tests(tmp_path):
    root = tmp_path / "p"
    write(root, {"cls.txt": "1\n", "mod.txt": "1\n", "test_f.py": """
        import unittest

        def setUpModule():
            global MOD
            MOD = open("mod.txt").read()

        class A(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                cls.value = open("cls.txt").read()

            def test_class_value(self):
                self.assertEqual(self.value, "1\\n")

        class B(unittest.TestCase):
            def test_module_value(self):
                self.assertEqual(MOD, "1\\n")
        """, "test_g.py": """
        import unittest

        class G(unittest.TestCase):
            def test_g(self):
                pass
        """})
    ut(root)
    write(root, {"cls.txt": "2\n"})
    r = ut(root)
    assert r.outcomes["test_f.py::A::test_class_value"] == "failed" and "test_f.py::A::test_class_value" not in r.reused
    write(root, {"cls.txt": "1\n"})
    ut(root)
    write(root, {"mod.txt": "2\n"})
    r = ut(root)
    assert r.outcomes["test_f.py::B::test_module_value"] == "failed", r
    assert "test_g.py::G::test_g" in r.reused, r


def test_load_tests_reads_are_inputs_of_the_tests_it_returns(tmp_path):
    root = tmp_path / "p"
    write(root, {"param.txt": "1\n", "test_l.py": """
        import unittest

        class P(unittest.TestCase):
            def __init__(self, methodName="runTest", value=None):
                super().__init__(methodName)
                self.value = value

            def runTest(self):
                self.assertEqual(self.value, "1")

        def load_tests(loader, tests, pattern):
            suite = unittest.TestSuite()
            suite.addTest(P(value=open("param.txt").read().strip()))
            return suite
        """, "test_other.py": """
        import unittest

        class O(unittest.TestCase):
            def test_o(self):
                pass
        """})
    a = ut(root)
    assert a.outcomes["test_l.py::P::runTest"] == "passed", a
    write(root, {"param.txt": "2\n"})
    r = ut(root)
    assert r.outcomes["test_l.py::P::runTest"] == "failed" and "test_l.py::P::runTest" not in r.reused, r
    assert "test_other.py::O::test_o" in r.reused, r


def test_discovery_pattern_change_reruns_everything(tmp_path):
    root = tmp_path / "p"
    write(root, {"test_both_test.py": "import unittest\n\nclass B(unittest.TestCase):\n    def test_b(self):\n"
                                      "        pass\n"})
    ut(root, "discover", "-p", "test_*.py")
    same = ut(root, "discover", "-p", "test_*.py")
    assert same.reused == {"test_both_test.py::B::test_b"}, same
    other = ut(root, "discover", "-p", "*_test.py")
    assert other.reused == set() and other.outcomes == {"test_both_test.py::B::test_b": "passed"}, other


def test_buffer_option_is_configuration(tmp_path):
    root = tmp_path / "p"
    write(root, {"test_buf.py": """
        import sys, unittest

        class B(unittest.TestCase):
            def test_plain_stdout(self):
                self.assertNotIn("StringIO", type(sys.stdout).__name__)
        """})
    ut(root)
    r = ut(root, "-b")
    assert r.reused == set() and r.outcomes["test_buf.py::B::test_plain_stdout"] == "failed", r


def test_new_test_module_runs_and_the_others_are_reused(tmp_path):
    root = tmp_path / "p"
    write(root, {"test_one.py": "import unittest\n\nclass One(unittest.TestCase):\n    def test_1(self):\n"
                                "        pass\n"})
    ut(root)
    write(root, {"test_two.py": "import unittest\n\nclass Two(unittest.TestCase):\n    def test_2(self):\n"
                                "        self.fail('new')\n"})
    r = ut(root)
    assert r.outcomes["test_two.py::Two::test_2"] == "failed" and r.reused == {"test_one.py::One::test_1"}, r
    assert r.code == 1


def test_class_teardown_error_is_never_reused(tmp_path):
    root = tmp_path / "p"
    write(root, {"test_td.py": """
        import unittest

        class TD(unittest.TestCase):
            @classmethod
            def tearDownClass(cls):
                raise RuntimeError("teardown")

            def test_a(self):
                pass
        """})
    a = ut(root)
    assert a.outcomes["test_td.py::TD::test_a"].startswith("passed+teardown-error"), a
    b = ut(root)
    assert b.reused == set() and b.code == 1, b


def test_file_written_by_another_test_is_never_reused(tmp_path):
    root = tmp_path / "p"
    write(root, {"data.txt": "1\n", "test_w.py": """
        import unittest

        class A(unittest.TestCase):
            def test_write(self):
                with open("out.txt", "w") as fh:
                    fh.write(open("data.txt").read())

        class B(unittest.TestCase):
            def test_read(self):
                self.assertEqual(open("out.txt").read(), "1\\n")
        """})
    ut(root)
    write(root, {"data.txt": "2\n"})
    r = ut(root)
    assert "test_w.py::B::test_read" not in r.reused and r.outcomes["test_w.py::B::test_read"] == "failed", r


def test_verify_mode_compares_every_would_be_reuse(tmp_path):
    root = tmp_path / "p"
    write(root, {"test_v.py": "import unittest\n\nclass V(unittest.TestCase):\n    def test_v(self):\n        pass\n"})
    ut(root)
    r = ut(root, det_args=["--det-cache-verify=1"])
    assert r.reused == set() and r.cache.get("verified_ids") == ["test_v.py::V::test_v"], r
    assert r.cache.get("verify_mismatches") in ([], None), r


def test_rmtree_of_a_temporary_directory_is_not_a_write_in_the_project(tmp_path):
    # shutil.rmtree removes entries by name under its directory's descriptor (os.remove(name, dir_fd=...)): those
    # removals were taken as writes of the same names in the working directory, so a test reading the project's
    # data.txt was "reading a file another test wrote" and never reused (ward's own suite: 376 of 389 tests)
    root = tmp_path / "p"
    write(root, {"data.txt": "1\n", "test_rm.py": """
        import os, shutil, tempfile, unittest

        class A(unittest.TestCase):
            def test_tmp(self):
                d = tempfile.mkdtemp()
                open(os.path.join(d, "data.txt"), "w").write("x")
                shutil.rmtree(d)

        class B(unittest.TestCase):
            def test_read(self):
                self.assertEqual(open("data.txt").read(), "1\\n")
        """})
    ut(root)
    r = ut(root)
    assert "test_rm.py::B::test_read" in r.reused, r
