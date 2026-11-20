"""``python -m detpy nose2``: controls and adversarial cases (the shared table as nose2 function tests, plus nose2's
own: configuration file, plugins, generator and parameterised ids, the multiprocess plugin refused)."""

from __future__ import annotations

import sys
import textwrap

import pytest

from runners_cases import CASES, PRELUDE, check_case, run_case
from runners_util import run, write

pytestmark = [pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring"),
              pytest.mark.skipif(pytest.importorskip("nose2") is None, reason="nose2")]


def n2(root, *args, **kw):
    return run("nose2", root, "-s", "tests", "-t", "tests", *args, **kw)


MODULE = """
import random, time, unittest
from nose2.tools import params

def test_clock():
    t0 = time.time()
    time.sleep(3)
    assert time.time() - t0 >= 3

def test_random():
    print(random.random())

def test_gen():
    for i in range(3):
        yield check, i

def check(i):
    assert i < 3

@params(1, 2)
def test_params(v):
    assert v > 0

class C(unittest.TestCase):
    def test_a(self):
        pass

    def test_b(self):
        pass
"""


def test_two_det_runs_give_identical_fingerprints_and_stable_ids(tmp_path):
    root = tmp_path / "p"
    write(root, {"tests/test_n.py": MODULE})
    a = n2(root, cache=False)
    b = n2(root, cache=False)
    assert set(a.outcomes.values()) == {"passed"} and len(a.outcomes) == 9, a
    assert a.fingerprints == b.fingerprints and len(a.fingerprints) == 9
    assert {"tests/test_n.py::test_gen:1", "tests/test_n.py::test_params:2", "tests/test_n.py::C::test_b"} <= set(
        a.outcomes)


def test_seeded_shuffle_is_reproducible(tmp_path):
    root = tmp_path / "p"
    write(root, {f"tests/test_m{m}.py": "".join(f"def test_{t}():\n    pass\n\n" for t in "abcdefg") for m in range(3)})
    s5 = n2(root, cache=False, det_args=["--det-seed=5"])
    s5b = n2(root, cache=False, det_args=["--det-seed=5"])
    s6 = n2(root, cache=False, det_args=["--det-seed=6"])
    assert len(s5.order) == 21 and s5.order == s5b.order and s5.order != s6.order


def test_controls_are_active_inside_nose2_tests(tmp_path):
    root = tmp_path / "p"
    write(root, {"tests/test_c.py": """
        import os, socket, time
        import detpy

        def test_clock():
            assert int(time.time()) == 1893456000

        def test_network():
            try:
                socket.create_connection(("192.0.2.1", 80), timeout=1)
            except detpy.NetworkBlockedError:
                return
            raise AssertionError("connected")

        def test_hash_seed():
            assert os.environ.get("PYTHONHASHSEED") == "0"
        """})
    r = n2(root, cache=False, det_args=["--det-epoch=2030-01-01T00:00:00"])
    assert r.outcomes and set(r.outcomes.values()) == {"passed"}, r


def _module(c) -> str:
    body = textwrap.indent(c["body"], " " * 4)
    return PRELUDE + c["prelude"] + "\n\ndef test_control():\n    assert 1 + 1 == 2\n\n\ndef test_x():\n" + body + "\n"


@pytest.mark.parametrize("c", CASES, ids=[c["name"] for c in CASES])
def test_wrong_reuse(tmp_path, c):
    root = tmp_path / "p"
    (root / "tests").mkdir(parents=True)
    first, second = run_case(c, lambda r, env: n2(r, env=env, safe_path=True), root,
                             lambda r, c: (r / "tests" / "test_case.py").write_text(_module(c)), root / "tests")
    check_case(c, first, second, "tests/test_case.py::test_x", "tests/test_case.py::test_control")


def test_configuration_file_is_an_input(tmp_path):
    # unittest.cfg can turn on a plugin that changes results (here: the test file pattern selects another module
    # whose import sets a variable the test reads)
    root = tmp_path / "p"
    write(root, {"unittest.cfg": "[unittest]\ntest-file-pattern = test_*.py\n",
                 "tests/test_cfg.py": "import os\n\ndef test_cfg():\n    assert os.environ.get('N2_EXTRA') is None\n",
                 "tests/check_extra.py": "import os\nos.environ['N2_EXTRA'] = '1'\n\ndef test_extra():\n    pass\n"})
    n2(root)
    again = n2(root)
    assert again.reused == {"tests/test_cfg.py::test_cfg"}, again
    write(root, {"unittest.cfg": "[unittest]\ntest-file-pattern = *.py\n"})
    r = n2(root)
    assert "tests/test_cfg.py::test_cfg" not in r.reused, r


def test_plugin_module_change_reruns(tmp_path):
    root = tmp_path / "p"
    plugin = """
        from nose2.events import Plugin

        class Tag(Plugin):
            configSection = "tag"
            alwaysOn = True

            def startTest(self, event):
                import os
                os.N2_TAG = "{tag}"
        """
    write(root, {"unittest.cfg": "[unittest]\nplugins = n2tag\n", "n2tag.py": plugin.format(tag="a"),
                 "tests/test_tag.py": "import os\n\ndef test_tag():\n    assert getattr(os, 'N2_TAG', None) == 'a'\n"})
    env = {"PYTHONPATH": str(root)}
    a = n2(root, env=env)
    assert a.outcomes == {"tests/test_tag.py::test_tag": "passed"}, a
    assert n2(root, env=env).reused == {"tests/test_tag.py::test_tag"}
    write(root, {"n2tag.py": plugin.format(tag="b")})
    r = n2(root, env=env)
    assert r.reused == set() and r.outcomes["tests/test_tag.py::test_tag"] == "failed", r


def test_multiprocess_plugin_is_refused(tmp_path):
    root = tmp_path / "p"
    write(root, {"tests/test_x.py": "def test_x():\n    pass\n"})
    r = n2(root, "-N", "2")
    assert r.code == 4 and "not supported under --det" in r.out
