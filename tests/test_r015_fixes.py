"""Fixes for review R-015 beyond its own tests (tests/test_review_r015.py): a code file changed during the session
refuses only the tests whose code includes it. (A non-test module's import-time lines are inputs of every test, so
an edit of one refuses every test that ran after its import; a test module serves its own tests only.)"""

import json
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


def test_code_changed_during_the_session_refuses_only_the_tests_that_ran_it(pytester):
    files = {
        "pytest.ini": "[pytest]\n",
        "pkg/__init__.py": "",
        "pkg/a.py": "def value():\n    return 1\n",
        "test_1a.py": "from pkg import a\n\ndef test_a():\n    assert a.value() == 1\n",
        "test_2b.py": "def test_b():\n    assert 1 == 1\n",
        # runs last: the developer's edit of test_2b.py while the suite runs (only while EDIT exists: removing a
        # module from the root would change what every import's search of the root finds)
        "EDIT": "",
        "test_3edit.py": """
            from pathlib import Path

            def test_edit():
                if (Path(__file__).parent / "EDIT").exists():
                    p = Path(__file__).parent / "test_2b.py"
                    p.write_text(p.read_text().replace("1 == 1", "1 == 2"))
            """,
    }
    for name, text in files.items():
        p = pytester.path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))
    cache, out = pytester.path / ".cachedir", pytester.path / "o.json"
    r = pytester.runpytest_subprocess("--det", f"--det-cache={cache}", f"--det-outcomes={out}", "-p",
                                      "no:cacheprovider")
    r.assert_outcomes(passed=3)
    c = json.loads(out.read_text())["cache"]
    # test_b ran the old code; test_edit, which ran after it in the same process, carries test_b's code (review R-020
    # prefix rule): both are refused, test_a (before the edit) is recorded
    assert c["not_cached_detail"] == {"source changed during the session: test_2b.py": 2}, c
    assert c["recorded"] == 1
    # next run: test_a reused, test_b runs the new code (fails)
    (pytester.path / "EDIT").unlink()
    r = pytester.runpytest_subprocess("--det", f"--det-cache={cache}", f"--det-outcomes={out}", "-p",
                                      "no:cacheprovider")
    r.assert_outcomes(passed=2, failed=1)
    assert json.loads(out.read_text())["cache"]["reused_ids"] == ["test_1a.py::test_a"]
