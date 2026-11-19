"""Round 2 of the exact-culprit validation: variants of the four R-019 failure kinds that the review's own cases
do not cover. Same helpers as ``review_r019/test_wrong_culprits.py``.

    python -m pytest -p no:cacheprovider harness/culprit/round2     # detpy installed in this interpreter
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "review_r019"))
sys.path.insert(0, str(HERE.parent))
from test_wrong_culprits import VENV, checkout, commit, find, git, key_at, new_repo, run_det  # noqa: E402

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


def test_break_fixed_by_a_different_edit_then_broken_again(tmp_path):
    """C1 breaks f, C2 fixes it with a different edit (not a revert: the footprint state is new), C3..C5 are
    harmless edits of f, C6 breaks f again. The re-touch check probes the later commits that change f again."""
    repo, g = new_repo(tmp_path, {"pkg/m.py": "def f(x):\n    return x + 1\n",
                                  "test_m.py": "from pkg import m\n\ndef test_f():\n    assert m.f(1) == 2\n"})
    bodies = ["x + 2", "1 + x", "(1 + x)", "((1 + x))", "x - 1 + 2", "x * 5"]
    shas = [commit(repo, f"c{i + 1}", {"pkg/m.py": f"def f(x):\n    return {b}\n"}) for i, b in enumerate(bodies)]
    nid = "test_m.py::test_f"
    gk, rk = tmp_path / "g.json", tmp_path / "r.json"
    assert key_at(repo, g, nid, gk) == "pass"
    assert key_at(repo, shas[-1], nid, rk) == "fail"
    res = find(repo, nid, {"sha": g, "env": {}, "venv": VENV, "key": str(gk)},
               {"sha": shas[-1], "env": {}, "venv": VENV, "key": str(rk)})
    print("finder:", res["named"], res["status"], res["why"], [(s["sha"][:8], s["why"], s["outcome"]) for s in res["steps"]])
    assert res["named"] in (shas[-1], None)
    assert res["named"] == shas[-1]


def test_mode_change_after_the_harmless_commit(tmp_path):
    """Mirror of H2: the harmless refactor comes first, the exec bit is dropped by the last commit."""
    files = {"bin/deploy.sh": "#!/bin/sh\necho deploy\n",
             "pkg/tools.py": "import os\n\ndef script_path(root):\n    return os.path.join(root, 'bin', 'deploy.sh')\n\n"
                             "def is_runnable(path):\n    return os.access(path, os.X_OK)\n",
             "test_tools.py": "import os\nfrom pkg import tools\n\nROOT = os.path.dirname(os.path.abspath(__file__))\n\n"
                              "def test_runnable():\n    assert tools.is_runnable(tools.script_path(ROOT))\n"}
    repo, g = new_repo(tmp_path, files)
    git(repo, "update-index", "--chmod=+x", "bin/deploy.sh")
    git(repo, "commit", "-q", "--amend", "-m", "green")
    (repo / "bin/deploy.sh").chmod(0o755)  # the work tree follows the index (git add -A keeps the bit)
    g = git(repo, "rev-parse", "HEAD")
    commit(repo, "refactor", {"pkg/tools.py": files["pkg/tools.py"].replace("'bin', 'deploy.sh'", "'bin/deploy.sh'")})
    git(repo, "update-index", "--chmod=-x", "bin/deploy.sh")
    git(repo, "commit", "-q", "-m", "drop exec bit")
    culprit = git(repo, "rev-parse", "HEAD")
    nid = "test_tools.py::test_runnable"
    gk, rk = tmp_path / "g.json", tmp_path / "r.json"
    assert key_at(repo, g, nid, gk) == "pass"
    assert key_at(repo, culprit, nid, rk) == "fail"
    res = find(repo, nid, {"sha": g, "env": {}, "venv": VENV, "key": str(gk)},
               {"sha": culprit, "env": {}, "venv": VENV, "key": str(rk)})
    print("finder:", res["named"], res["status"], res["why"], res["executions"])
    assert res["named"] == culprit


def test_three_inputs_needed_together(tmp_path):
    """A, B and C together break the test; D and E are harmless. Answer: the set {A, B, C}."""
    repo, g = new_repo(tmp_path, {
        "pkg/cfg.py": "import os\n\ndef mode():\n    v = [os.environ.get(k) for k in ('A', 'B', 'C', 'D', 'E')]\n"
                      "    return 'odd' if v[:3] == ['1', '1', '1'] else 'ok'\n",
        "test_cfg.py": "from pkg import cfg\n\ndef test_mode():\n    assert cfg.mode() == 'ok'\n"})
    nid = "test_cfg.py::test_mode"
    green_env = {k: None for k in "ABCDE"}
    red_env = {k: "1" for k in "ABCDE"}
    gk, rk = tmp_path / "g.json", tmp_path / "r.json"
    assert key_at(repo, g, nid, gk, green_env) == "pass"
    assert key_at(repo, g, nid, rk, red_env) == "fail"
    res = find(repo, nid, {"sha": g, "env": green_env, "venv": VENV, "key": str(gk)},
               {"sha": g, "env": red_env, "venv": VENV, "key": str(rk)})
    print("finder:", res["culprit"], res["executions"])
    assert sorted(res["culprit"]["inputs"]) == ["env:A", "env:B", "env:C"]


def test_deterministic_test_red_at_green_commit_is_not_blamed(tmp_path):
    """The CI's green run passed, but the green commit fails when replayed (the green key was recorded in another
    environment: a variable the job did not declare). The finder must not name a commit."""
    repo, g = new_repo(tmp_path, {"pkg/m.py": "import os\n\ndef f():\n    return os.environ.get('HIDDEN') == '1'\n",
                                  "test_m.py": "from pkg import m\n\ndef test_f():\n    assert m.f()\n"})
    shas = [commit(repo, f"c{i}", {"pkg/m.py": f"import os\n\ndef f():\n    return os.environ.get('HIDDEN') == '1'  # {i}\n"})
            for i in range(3)]
    nid = "test_m.py::test_f"
    gk, rk = tmp_path / "g.json", tmp_path / "r.json"
    assert key_at(repo, g, nid, gk, {"HIDDEN": "1"}) == "pass"
    assert key_at(repo, shas[-1], nid, rk, {"HIDDEN": None}) == "fail"
    # both jobs declare no HIDDEN: the difference is invisible to the job definitions
    res = find(repo, nid, {"sha": g, "env": {}, "venv": VENV, "key": str(gk)},
               {"sha": shas[-1], "env": {}, "venv": VENV, "key": str(rk)})
    print("finder:", res["named"], res["status"], res["why"], res["executions"])
    assert res["named"] is None or not res["named"].startswith(tuple(shas))
