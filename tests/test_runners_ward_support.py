"""``python -m detpy ward`` where ward itself cannot run: one sentence and exit 4, never ward's traceback.

ward 0.68.0b0 (its newest release) uses ``textwrap._leading_whitespace_re``, which CPython 3.14 removed; plain
``ward`` then stops with an AttributeError before any test. On such a Python this runs for real; elsewhere the
child process removes the name first, so every interpreter of the gate proves the refusal."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="detpy needs CPython 3.12+")

CHILD = """
import runpy, sys, textwrap
sys.path[:0] = {path!r}
if {remove} and hasattr(textwrap, "_leading_whitespace_re"):
    del textwrap._leading_whitespace_re
sys.argv = ["detpy", "ward", "--det", "--det-cache", "c", "test", "--path", "tests"]
runpy.run_module("detpy", run_name="__main__")
"""


@pytest.mark.parametrize("remove", [False, True], ids=["this-python", "name-removed"])
def test_ward_refused_with_one_sentence_where_ward_cannot_run(tmp_path, remove):
    real = not hasattr(textwrap, "_leading_whitespace_re")
    if not remove and not real:
        # this Python still has the name: the refusal is proved by the "name-removed" case, and ward runs here
        # (tests/test_runners_ward.py)
        from detpy.runners.ward_runner import ward_cannot_run

        assert ward_cannot_run() is None
        return
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("from ward import test\n\n@test('a')\ndef _():\n    assert 1\n")
    # the runner entry first checks that ward is installed (fenvix ward: "not installed" otherwise); where it is not
    # (the main suite's environment), an empty stand-in package satisfies that check: the refusal comes before
    # anything of ward is imported
    path = []
    if importlib.util.find_spec("ward") is None:
        (tmp_path / "standin" / "ward").mkdir(parents=True)
        (tmp_path / "standin" / "ward" / "__init__.py").write_text("")
        path = [str(tmp_path / "standin")]
    r = subprocess.run([sys.executable, "-c", CHILD.format(remove=remove, path=path)], cwd=tmp_path,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 4, (r.stdout, r.stderr)
    assert "Traceback" not in r.stderr, r.stderr
    line = r.stderr.strip()
    assert line.startswith("detpy ward: error: ward ") and "textwrap._leading_whitespace_re" in line, line
    assert "CPython 3.12 or 3.13" in line
    assert not (tmp_path / "c").exists() and not (tmp_path / ".detpy").exists()
