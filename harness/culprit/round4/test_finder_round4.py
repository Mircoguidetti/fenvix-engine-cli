"""Exact culprit, round 4: adversarial tests for the red-side check with key-validity inference and parallel probes.

Round 4 decides later commits without replaying them when an earlier replay's key recorded inputs that all have
the same value there, and replays the rest several at a time (each in its own copy of the repository mounted at
the repository's path). Each test below is built so that a careless inference would state a confident wrong
culprit: a later commit fixes the test through something the failing run's key does not record (a new conftest,
the pytest configuration, a new module shadowing an import, a file mode), or through an input the old footprint
vector ignored (a unit equal at green and red). The truth is the newest transition (walk back to the newest
passing commit), as in review R-019b.

    python -m pytest -p no:cacheprovider harness/culprit/round4     # detpy installed in this interpreter
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "review_r019"))
sys.path.insert(0, str(HERE.parent))
from test_wrong_culprits import VENV, checkout, commit, git, key_at, new_repo, run_det  # noqa: E402
import finder as F  # noqa: E402

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
NID = "test_m.py::test_api"
TEST = "from pkg import m\n\ndef test_api():\n    assert m.api(1) == 2\n"


def _truth(repo, shas, nid=NID):
    for i in range(len(shas) - 1, -1, -1):
        checkout(repo, shas[i])
        if run_det(repo, VENV, nid)["outcome"] == "pass":
            return shas[i + 1]
    return shas[0]


def _find(repo, g0, red, tmp_path, nid=NID, **kw):
    gk, rk = tmp_path / "g.json", tmp_path / "r.json"
    assert key_at(repo, g0, nid, gk) == "pass"
    assert key_at(repo, red, nid, rk) == "fail"
    f = F.Finder(repo, nid, {"sha": g0, "env": {}, "venv": VENV, "key": str(gk)},
                 {"sha": red, "env": {}, "venv": VENV, "key": str(rk)})
    for k, v in kw.items():
        setattr(f, k, v)
    res = f.run()
    res["named"] = (res.get("culprit") or {}).get("commit")
    print("finder:", res["named"], res["status"], res["why"],
          [(s["sha"][:8], s["why"], s["outcome"], s.get("batch")) for s in res["steps"]])
    return res


def _history(tmp_path, src, state, steps, extra=None):
    repo, g0 = new_repo(tmp_path, {"pkg/m.py": src.format(**state), "test_m.py": TEST, **(extra or {})})
    shas = []
    for msg, ch, files in steps:
        state.update(ch)
        shas.append(commit(repo, msg, {"pkg/m.py": src.format(**state), **(files or {})}))
    return repo, g0, shas


# ------------------------------------------------------------- 1. a unit equal at green and red (old vector)
def test_caller_fix_reverted_later_unit_equal_at_both_ends(tmp_path):
    """C breaks ``f``; F works around it in the caller ``g`` (passes); R reverts F (fails again). ``g`` is equal
    at green and red, so it is not in the key diff: the round-3 footprint vector (differing inputs only) gives F
    the state of C and infers it failing, and C is stated. The red key records ``g``, so key validity cannot infer
    F, F is replayed, passes, and the search restarts above it. Truth: R."""
    src = "def f(x):\n    return {f}\n\n\ndef g(x):\n    return {g}\n\n\ndef api(x):\n    return g(x)\n"
    repo, g0, shas = _history(tmp_path, src, {"f": "x + 1", "g": "f(x)"}, [
        ("C breaks f", {"f": "x + 2"}, None), ("x tidy", {}, {"README": "a\n"}),
        ("F caller works around f", {"g": "f(x) - 1"}, None), ("y tidy", {}, {"README": "b\n"}),
        ("R reverts F", {"g": "f(x)"}, None), ("z tidy", {}, {"README": "c\n"})])
    truth = _truth(repo, shas)
    assert truth == shas[4]
    res = _find(repo, g0, shas[-1], tmp_path)
    assert res["named"] in (truth, None), f"named {res['named'][:10]}, truth R {truth[:10]}"
    assert res["named"] == truth


# ------------------------------------------------------------- 2. a conftest added later (not in the red key)
def test_conftest_added_later_fixes_the_test(tmp_path):
    """C breaks ``f``; L adds a conftest.py whose autouse fixture works around it (passes); B deletes the
    conftest (fails again). The red run never saw a conftest, so its key does not mention one: inferring L from
    the red key would state C. Truth: B."""
    src = "OFFSET = 0\n\n\ndef f(x):\n    return {f}\n\n\ndef api(x):\n    return f(x) + OFFSET\n"
    conf = "import pytest\nfrom pkg import m\n\n\n@pytest.fixture(autouse=True)\ndef _fix(monkeypatch):\n" \
           "    monkeypatch.setattr(m, 'OFFSET', -1)\n"
    repo, g0, shas = _history(tmp_path, src, {"f": "x + 1"}, [
        ("C breaks f", {"f": "x + 2"}, None), ("L conftest works around", {}, {"conftest.py": conf}),
        ("x tidy", {}, {"README": "a\n"})])
    git(repo, "rm", "-q", "conftest.py")
    shas.append(commit(repo, "B drops the conftest"))
    truth = _truth(repo, shas)
    assert truth == shas[-1]
    res = _find(repo, g0, shas[-1], tmp_path)
    assert res["named"] in (truth, None), f"named {res['named'][:10]}, truth B {truth[:10]}"


# ------------------------------------------------------------- 3. pytest configuration changed later
def test_ini_option_changed_later_fixes_the_test(tmp_path):
    """The test reads an ini option (``request.config.getini``) declared by a conftest. C breaks ``f``; L sets the
    option in pytest.ini so the test passes; B restores pytest.ini (fails again). The ini file is not a per-test
    input of the key (the configuration digest is session-wide). Truth: B."""
    src = "def f(x):\n    return {f}\n\n\ndef api(x, off=0):\n    return f(x) + off\n"
    conf = "def pytest_addoption(parser):\n    parser.addini('offset', 'offset', default='0')\n"
    test = "from pkg import m\n\ndef test_api(request):\n    assert m.api(1, int(request.config.getini('offset'))) == 2\n"
    repo, g0 = new_repo(tmp_path, {"pkg/m.py": src.format(f="x + 1"), "conftest.py": conf, "test_m.py": test})
    shas = [commit(repo, "C breaks f", {"pkg/m.py": src.format(f="x + 2")}),
            commit(repo, "L sets offset", {"pytest.ini": "[pytest]\noffset = -1\n"}),
            commit(repo, "x tidy", {"README": "a\n"}),
            commit(repo, "B restores pytest.ini", {"pytest.ini": "[pytest]\n"})]
    truth = _truth(repo, shas)
    assert truth == shas[-1]
    res = _find(repo, g0, shas[-1], tmp_path)
    assert res["named"] in (truth, None), f"named {res['named'][:10]}, truth B {truth[:10]}"


# ------------------------------------------------------------- 4. a new package shadows the imported module
def test_package_added_later_shadows_the_module(tmp_path):
    """C breaks ``pkg/m.py``; L adds a package ``pkg/m/`` (which the import system prefers to ``pkg/m.py``) with a
    working ``api``; B removes it. The red key records ``pkg/m.py`` only: ``pkg/m/__init__.py`` did not exist and
    the import system's directory reads are not recorded. Truth: B."""
    src = "def f(x):\n    return {f}\n\n\ndef api(x):\n    return f(x)\n"
    repo, g0, shas = _history(tmp_path, src, {"f": "x + 1"}, [
        ("C breaks f", {"f": "x + 2"}, None),
        ("L adds package pkg.m", {}, {"pkg/m/__init__.py": "def api(x):\n    return x + 1\n"}),
        ("x tidy", {}, {"README": "a\n"})])
    git(repo, "rm", "-q", "-r", "pkg/m")
    shas.append(commit(repo, "B removes the package"))
    truth = _truth(repo, shas)
    assert truth == shas[-1]
    res = _find(repo, g0, shas[-1], tmp_path)
    assert res["named"] in (truth, None), f"named {res['named'][:10]}, truth B {truth[:10]}"


# ------------------------------------------------------------- 5. a file mode changed later
def test_mode_change_later_fixes_the_test(tmp_path):
    """``api`` subtracts 1 when ``tool.sh`` is executable (``os.access``: modes are not inputs of the key). C
    breaks ``f``; L makes tool.sh executable (passes); B makes it plain again. Truth: B."""
    src = ("import os\n\n\ndef f(x):\n    return {f}\n\n\n"
           "def api(x):\n    return f(x) - (1 if os.access('tool.sh', os.X_OK) else 0)\n")
    repo, g0, shas = _history(tmp_path, src, {"f": "x + 1"}, [("C breaks f", {"f": "x + 2"}, None)],
                              extra={"tool.sh": "#!/bin/sh\n"})
    (repo / "tool.sh").chmod(0o755)
    shas.append(commit(repo, "L tool.sh executable"))
    shas.append(commit(repo, "x tidy", {"README": "a\n"}))
    (repo / "tool.sh").chmod(0o644)
    shas.append(commit(repo, "B tool.sh plain"))
    truth = _truth(repo, shas)
    assert truth == shas[-1]
    res = _find(repo, g0, shas[-1], tmp_path)
    assert res["named"] in (truth, None), f"named {res['named'][:10]}, truth B {truth[:10]}"


# ------------------------------------------------------------- 6. inference does what it claims
def test_later_changes_the_failing_run_never_reached_are_inferred(tmp_path):
    """After C breaks ``f``, eight commits change ``h``, which the test calls only after the failing assertion.
    The green run read ``h`` (so ``h`` is in the key diff, and each of the eight was a footprint state the round-3
    check had to replay), the red run never reached it: its key does not record ``h``. Key validity infers all
    eight from the red key: C is stated with no red-side replay."""
    src = "def f(x):\n    return {f}\n\n\ndef h():\n    return {h}\n"
    test = "from pkg import m\n\ndef test_api():\n    assert m.f(1) == 2\n    assert m.h() >= 0\n"
    repo, g0 = new_repo(tmp_path, {"pkg/m.py": src.format(f="x + 1", h="0"), "test_m.py": test})
    shas = [commit(repo, "C breaks f", {"pkg/m.py": src.format(f="x + 2", h="0")})]
    for i in range(1, 9):
        shas.append(commit(repo, f"h tidy {i}", {"pkg/m.py": src.format(f="x + 2", h=f"{i}")}))
    truth = _truth(repo, shas)
    assert truth == shas[0]
    res = _find(repo, g0, shas[-1], tmp_path)
    assert res["named"] == truth
    assert res["red_probes"] == 0, res["red_probes"]


def test_budget_runs_out_gives_unknown_with_suspect(tmp_path):
    """Ten later commits each change ``g``, which the failing run calls before failing: none can be inferred.
    With a budget of 4 the answer is withheld with the right suspect; with a budget of 12 (parallel batches
    of 4) it is stated."""
    src = "def f(x):\n    return {f}\n\n\ndef g(x):\n    return x + {g}\n\n\ndef api(x):\n    return f(g(x))\n"
    repo, g0 = new_repo(tmp_path, {"pkg/m.py": src.format(f="x + 1", g="0"), "test_m.py": TEST})
    shas = [commit(repo, "C breaks f", {"pkg/m.py": src.format(f="x + 2", g="0")})]
    for i in range(1, 11):
        shas.append(commit(repo, f"g tidy {i}", {"pkg/m.py": src.format(f="x + 2", g=f"0 * {i}")}))
    truth = _truth(repo, shas)
    assert truth == shas[0]
    small = _find(repo, g0, shas[-1], tmp_path, budget=4)
    assert small["named"] is None and f"suspect {truth}" in small["why"]
    big = _find(repo, g0, shas[-1], tmp_path, budget=12)
    assert big["named"] == truth
    assert big["batches"] >= 2 and 4 < big["red_probes"] <= 12


# ------------------------------------------------------------- 7. parallel probes see their own checkout
def test_parallel_probes_equal_sequential_replays(tmp_path):
    """Five commits alternate pass and fail through a data file and a code change. Replayed four at a time (each in
    its own copy mounted at the repository's path) and one at a time, every commit gives the same outcome and the
    same recorded inputs."""
    src = "import pathlib\n\n\ndef api(x):\n    return x + {k} + int(pathlib.Path('n.txt').read_text())\n"
    repo, g0 = new_repo(tmp_path, {"pkg/m.py": src.format(k="1"), "n.txt": "0\n", "test_m.py": TEST})
    shas = [commit(repo, "a", {"n.txt": "1\n"}), commit(repo, "b", {"pkg/m.py": src.format(k="0")}),
            commit(repo, "c", {"n.txt": "5\n"}), commit(repo, "d", {"pkg/m.py": src.format(k="-4")})]
    gk = tmp_path / "g.json"
    key_at(repo, g0, NID, gk)
    seq = []
    for x in shas:
        checkout(repo, x)
        seq.append(run_det(repo, VENV, NID)["outcome"])
    assert seq == ["fail", "pass", "fail", "pass"]
    f = F.Finder(repo, NID, {"sha": g0, "env": {}, "venv": VENV, "key": str(gk)},
                 {"sha": shas[-1], "env": {}, "venv": VENV, "key": str(gk)})
    f._green_dists = {}
    side = ({}, None, VENV, None)
    par = f._probe_many(shas, side, "parallel")
    assert par == seq
    assert all(s.get("batch") == 1 for s in f.steps)
    runs = f.runs[f._side_sid(side)]
    assert sorted(r.sha for r in runs) == sorted(shas)
    for r in runs:
        assert "n.txt" in r.items and "pkg/m.py" in r.items


def test_run_from_key_refuses_runs_that_are_no_proof():
    entry = {"code": {"unit:pkg/m.py::f": "d"}, "data": {}, "flags": [], "not_cached": "outcome failed"}
    kd = {"root": "/r", "config_info": {}}
    assert F.run_from_key("/r", "s", "fail", kd, entry, NID, "x") is not None
    assert F.run_from_key("/r", "s", "fail", kd, {**entry, "not_cached": "subprocess"}, NID, "x") is None
    assert F.run_from_key("/r", "s", "fail", kd, {**entry, "flags": ["rclock"]}, NID, "x") is None
    assert F.run_from_key("/r", "s", "missing", kd, entry, NID, "x") is None
    assert F.run_from_key("/r", "s", "fail", {**kd, "root": "/elsewhere"}, entry, NID, "x") is None
