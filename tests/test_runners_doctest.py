"""``python -m detpy doctest FILE...``: controls and adversarial cases (the shared table as docstring examples, plus
doctest's own: a text file, the docstring itself, ``-o`` options)."""

from __future__ import annotations

import sys
import textwrap

import pytest

from runners_cases import CASES, PRELUDE, check_case, run_case
from runners_util import run, write

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


def dt(root, *files, **kw):
    return run("doctest", root, *files, **kw)


MODULE = '''
import random, time

def clock():
    """
    >>> t0 = time.time(); time.time() > t0
    True
    """

def rand():
    """
    >>> 0 <= random.random() < 1
    True
    """

def order():
    """
    >>> len({"a", "b", "c"})
    3
    """
'''


def test_two_det_runs_give_identical_fingerprints(tmp_path):
    root = tmp_path / "p"
    write(root, {"m.py": MODULE, "README.txt": "Text\n\n>>> 1 + 1\n2\n"})
    a = dt(root, "m.py", "README.txt", cache=False)
    b = dt(root, "m.py", "README.txt", cache=False)
    assert set(a.outcomes) == {"m.py::m.clock", "m.py::m.rand", "m.py::m.order", "README.txt::README.txt"}, a
    assert set(a.outcomes.values()) == {"passed"} and a.fingerprints == b.fingerprints


def test_seeded_shuffle_is_reproducible(tmp_path):
    root = tmp_path / "p"
    write(root, {f"m{i}.py": "".join(f'def f{j}():\n    """\n    >>> {j}\n    {j}\n    """\n\n' for j in range(6))
                 for i in range(3)})
    files = [f"m{i}.py" for i in range(3)]
    s5 = dt(root, *files, cache=False, det_args=["--det-seed=5"])
    s5b = dt(root, *files, cache=False, det_args=["--det-seed=5"])
    s6 = dt(root, *files, cache=False, det_args=["--det-seed=6"])
    assert len(s5.order) == 18 and s5.order == s5b.order and s5.order != s6.order


def test_controls_are_active_inside_doctests(tmp_path):
    root = tmp_path / "p"
    write(root, {"c.py": '''
def f():
    """
    >>> import time, os
    >>> int(time.time())
    1893456000
    >>> os.environ.get("PYTHONHASHSEED")
    '0'
    """
'''})
    r = dt(root, "c.py", cache=False, det_args=["--det-epoch=2030-01-01T00:00:00"])
    assert r.outcomes == {"c.py::c.f": "passed"}, r


def _module(c) -> str:
    body = textwrap.indent(PRELUDE + c["prelude"] + c["body"], " " * 4)
    return ('def control():\n    """\n    >>> 1 + 1\n    2\n    """\n\n\n'
            'def x():\n    """\n    >>> _case()\n    """\n\n\ndef _case():\n' + body + "\n")


@pytest.mark.parametrize("c", CASES, ids=[c["name"] for c in CASES])
def test_wrong_reuse(tmp_path, c):
    root = tmp_path / "p"
    (root / "dt").mkdir(parents=True)
    # dt/ on sys.path while the examples run (doctest's own import puts it there only for the import)
    first, second = run_case(c, lambda r, env: dt(r, "dt/case_mod.py", env={**env, "PYTHONPATH": str(r / "dt")},
                                                  safe_path=True), root,
                             lambda r, c: (r / "dt" / "case_mod.py").write_text(_module(c)), root / "dt")
    check_case(c, first, second, "dt/case_mod.py::case_mod.x", "dt/case_mod.py::case_mod.control")


def test_text_file_change_reruns_it(tmp_path):
    root = tmp_path / "p"
    write(root, {"README.txt": "Text\n\n>>> 1 + 1\n2\n", "m.py": MODULE})
    dt(root, "README.txt", "m.py")
    write(root, {"README.txt": "Text\n\n>>> 1 + 1\n3\n"})
    r = dt(root, "README.txt", "m.py")
    assert r.outcomes["README.txt::README.txt"] == "failed" and "README.txt::README.txt" not in r.reused, r
    assert r.reused == {"m.py::m.clock", "m.py::m.rand", "m.py::m.order"}, r


def test_docstring_change_reruns_the_module_doctests(tmp_path):
    root = tmp_path / "p"
    write(root, {"m.py": MODULE})
    dt(root, "m.py")
    write(root, {"m.py": MODULE.replace("    3\n", "    4\n")})
    r = dt(root, "m.py")
    assert r.outcomes["m.py::m.order"] == "failed" and r.reused == set(), r


def test_option_change_is_configuration(tmp_path):
    root = tmp_path / "p"
    write(root, {"e.py": 'def f():\n    """\n    >>> print("a   b")\n    a b\n    """\n'})
    a = dt(root, "-o", "NORMALIZE_WHITESPACE", "e.py")
    assert a.outcomes == {"e.py::e.f": "passed"}, a
    r = dt(root, "e.py")
    assert r.reused == set() and r.outcomes["e.py::e.f"] == "failed", r
