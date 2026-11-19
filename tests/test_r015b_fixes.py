"""Fixes for review R-015b: cases next to the review's own tests (tests/test_review_r015b.py)."""

import json
import os
import sys

import pytest

from test_review_r015b import WAIT, _project, _pytest, _reused, _session_with_edit

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


def test_G2_symlink_pointed_elsewhere_during_the_session_refuses_on_the_old_target(pytester):
    """The F1 stat key is taken through the link, and the file reported changed is the target it had then (the
    file whose units the test recorded), not the one it points to at the end."""
    root = pytester.path
    _project(root, {
        "pytest.ini": "[pytest]\n",
        "w.py": WAIT,
        "pkg/__init__.py": "",
        "pkg/impl_1.py": "VALUE = 1\n",
        "pkg/impl_2.py": "VALUE = 2\n",
        "test_m.py": """
            from pkg import mod
            from w import wait

            def test_a():
                wait()
                assert mod.VALUE == 1
            """,
    })
    os.symlink("impl_1.py", root / "pkg" / "mod.py")
    cache = root / ".cachedir"

    def retarget():
        os.unlink(root / "pkg" / "mod.py")
        os.symlink("impl_2.py", root / "pkg" / "mod.py")

    _session_with_edit(root, cache, retarget)
    c = json.loads((root / "o1.json").read_text())["cache"]
    assert c["not_cached_ids"]["test_m.py::test_a"] == "source changed during the session: pkg/impl_1.py"
    assert "1 failed" in _pytest(root, "--det").stdout
    assert "test_m.py::test_a" not in _reused(root, cache)
