"""Review R-019b (last round): new adversarial cases for the round-2 finder (`harness/culprit/finder.py`).

Same helpers and the same calling convention as `review_r019/test_wrong_culprits.py`. Each test asserts the right
answer (the culprit, or no confident answer). A failing test is a confident wrong culprit.

    python -m pytest -p no:cacheprovider harness/culprit/review_r019b     # detpy installed in this interpreter
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "review_r019"))
sys.path.insert(0, str(HERE.parent))
from test_wrong_culprits import VENV, checkout, commit, find, git, key_at, new_repo, run_det  # noqa: E402
from common import git_bisect  # noqa: E402

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


def _steps(res):
    return [(s["sha"][:8], s["why"], s["outcome"]) for s in res["steps"]]


def _truth_walk(repo, shas, nid):
    """Plain truth: walk back from the red head to the first passing commit (as round 2's placed.py does)."""
    for i in range(len(shas) - 1, -1, -1):
        checkout(repo, shas[i])
        if run_det(repo, VENV, nid)["outcome"] == "pass":
            return shas[i + 1]
    return shas[0]


# --------------------------------------------------------------- 1. break fixed in another unit, broken again
def test_break_worked_around_in_the_caller_then_broken_elsewhere(tmp_path):
    """C1 breaks ``f``. Two harmless commits touch ``k``. C2 works around C1 in the caller ``g`` (not a revert,
    ``f`` is never touched again). C3 breaks ``k``. Red at C3 comes from C3 (C2 passes).

    The re-touch check only probes later commits that change C1's own inputs (``f``) or undo C1's lines; C2 does
    neither, so C1 is confirmed (parent passes, C1 fails) and stated."""
    src = ("def f(x):\n    return {f}\n\n\ndef g(x):\n    return {g}\n\n\ndef k():\n    return {k}\n\n\n"
           "def api(x):\n    return g(x) + k()\n")
    state = {"f": "x + 1", "g": "f(x)", "k": "0"}
    repo, g0 = new_repo(tmp_path, {"pkg/m.py": src.format(**state),
                                   "test_m.py": "from pkg import m\n\ndef test_api():\n    assert m.api(1) == 2\n"})
    shas = []
    for msg, ch in [("C1 breaks f", {"f": "x + 2"}), ("x1 tidy k", {"k": "0 * 1"}), ("x2 tidy k", {"k": "0 * 2"}),
                    ("C2 caller works around f", {"g": "f(x) - 1"}), ("C3 breaks k", {"k": "1"})]:
        state.update(ch)
        shas.append(commit(repo, msg, {"pkg/m.py": src.format(**state)}))
    nid = "test_m.py::test_api"
    gk, rk = tmp_path / "g.json", tmp_path / "r.json"
    assert key_at(repo, g0, nid, gk) == "pass"
    assert key_at(repo, shas[-1], nid, rk) == "fail"
    truth = _truth_walk(repo, shas, nid)
    assert truth == shas[-1]
    res = find(repo, nid, {"sha": g0, "env": {}, "venv": VENV, "key": str(gk)},
               {"sha": shas[-1], "env": {}, "venv": VENV, "key": str(rk)})
    b = git_bisect(repo, VENV, g0, shas[-1], ["--tb=no", nid])
    print("finder:", res["named"], res["status"], res["why"], _steps(res))
    print("git bisect:", b["named"], "right" if b["named"] and truth.startswith(b["named"]) else "wrong")
    assert res["named"] in (truth, None), \
        f"finder confirmed C1 {res['named'][:10]} (worked around by C2); the red comes from C3 {truth[:10]}"


# ------------------------------------------------- 2. fallback search after a failed confirmation (all commits)
def test_fallback_search_does_not_name_a_breakage_that_was_already_reverted(tmp_path):
    """C1 breaks ``g`` (on the test's path), C2 tidies ``f``, C3 reverts C1, C4 breaks ``f``. ``g`` is equal at
    green and red, so it is not in the key diff and C1/C3 are not candidates. The candidate search probes C2 (red,
    because C1 is still in), names C2, the confirmation finds C2's parent red, and ``_bisect_all`` searches
    (green, C1] with no re-touch check: it confirms C1, whose breakage C3 had already reverted."""
    src = "def f(x):\n    return {f}\n\n\ndef g(x):\n    return {g}\n\n\ndef api(x):\n    return g(f(x))\n"
    state = {"f": "x + 1", "g": "x"}
    repo, g0 = new_repo(tmp_path, {"pkg/m.py": src.format(**state),
                                   "test_m.py": "from pkg import m\n\ndef test_api():\n    assert m.api(1) == 2\n"})
    shas = []
    for msg, ch in [("C1 breaks g", {"g": "x * 10"}), ("C2 tidies f", {"f": "1 + x"}),
                    ("C3 reverts C1", {"g": "x"}), ("C4 breaks f", {"f": "x + 5"})]:
        state.update(ch)
        shas.append(commit(repo, msg, {"pkg/m.py": src.format(**state)}))
    nid = "test_m.py::test_api"
    gk, rk = tmp_path / "g.json", tmp_path / "r.json"
    assert key_at(repo, g0, nid, gk) == "pass"
    assert key_at(repo, shas[-1], nid, rk) == "fail"
    truth = _truth_walk(repo, shas, nid)
    assert truth == shas[-1]
    res = find(repo, nid, {"sha": g0, "env": {}, "venv": VENV, "key": str(gk)},
               {"sha": shas[-1], "env": {}, "venv": VENV, "key": str(rk)})
    b = git_bisect(repo, VENV, g0, shas[-1], ["--tb=no", nid])
    print("finder:", res["named"], res["status"], res["why"], _steps(res))
    print("git bisect:", b["named"], "right" if b["named"] and truth.startswith(b["named"]) else "wrong")
    assert res["named"] in (truth, None), \
        f"finder confirmed {res['named'][:10]} (C1, reverted by C3) via the fallback search; truth C4 {truth[:10]}"


# ------------------------------------------------ 3. no differing input: plain search, earlier break reverted
def test_red_outside_the_key_after_a_reverted_breakage(tmp_path):
    """C1 breaks ``g``, C2 reverts it, C3 changes a data file that only a child process reads (``cat``), which
    breaks the test. Nothing differs in the key, so the finder runs ``_bisect_all`` over every commit; its first
    probe is C1 (red), and C1 is confirmed. Truth: C3."""
    src = ("import subprocess\n\n\ndef g(x):\n    return {g}\n\n\n"
           "def api(x):\n    v = subprocess.run(['cat', 'data/n.txt'], capture_output=True, text=True).stdout\n"
           "    return g(x) + int(v)\n")
    repo, g0 = new_repo(tmp_path, {"pkg/m.py": src.format(g="x"), "data/n.txt": "1\n",
                                   "test_m.py": "from pkg import m\n\ndef test_api():\n    assert m.api(1) == 2\n"})
    shas = [commit(repo, "C1 breaks g", {"pkg/m.py": src.format(g="x * 10")}),
            commit(repo, "C2 reverts C1", {"pkg/m.py": src.format(g="x")}),
            commit(repo, "C3 data read by a child", {"data/n.txt": "7\n"})]
    nid = "test_m.py::test_api"
    gk, rk = tmp_path / "g.json", tmp_path / "r.json"
    assert key_at(repo, g0, nid, gk) == "pass"
    assert key_at(repo, shas[-1], nid, rk) == "fail"
    truth = _truth_walk(repo, shas, nid)
    assert truth == shas[-1]
    res = find(repo, nid, {"sha": g0, "env": {}, "venv": VENV, "key": str(gk)},
               {"sha": shas[-1], "env": {}, "venv": VENV, "key": str(rk)})
    print("finder:", res["named"], res["status"], res["why"], res.get("changed_inputs"), _steps(res))
    assert res["named"] in (truth, None), \
        f"finder confirmed {res['named'][:10]} (C1, reverted by C2); the red comes from C3 {truth[:10]}"


# -------------------------------------------------------------- 4. flaky through a child process ("spawn")
def test_flaky_child_process_is_not_blamed_on_a_commit(tmp_path):
    """The test's randomness is in a child process (``python -c ... os.urandom``). The key flags it ``spawn``,
    which is not in ``NONDET_FLAGS``, so the finder replays once per step and confirms with two single replays.
    Over 8 finder runs on a test that fails half the time at every commit, it must never state a commit."""
    child = "import os,sys; sys.exit(os.urandom(1)[0] % 2)"
    src = "import subprocess, sys\n\n\ndef ok():\n    {}\n"
    impls = [f"return subprocess.run([sys.executable, '-c', {child!r}]).returncode == 0",
             f"rc = subprocess.run([sys.executable, '-c', {child!r}]).returncode\n    return rc == 0",
             f"p = subprocess.run([sys.executable, '-c', {child!r}])\n    return p.returncode == 0",
             f"p = subprocess.run([sys.executable, '-c', {child!r}])\n    return not p.returncode"]
    repo, g0 = new_repo(tmp_path, {"pkg/m.py": src.format(impls[0]),
                                   "test_m.py": "from pkg import m\n\ndef test_ok():\n    assert m.ok()\n"})
    shas = [commit(repo, f"tidy ok ({i})", {"pkg/m.py": src.format(x)}) for i, x in enumerate(impls[1:])]
    nid = "test_m.py::test_ok"
    gk, rk = tmp_path / "g.json", tmp_path / "r.json"
    key_at(repo, g0, nid, gk, want="pass", tries=40)
    key_at(repo, shas[-1], nid, rk, want="fail", tries=40)
    checkout(repo, g0)
    assert {run_det(repo, VENV, nid)["outcome"] for _ in range(12)} == {"pass", "fail"}
    named = []
    for _ in range(8):
        res = find(repo, nid, {"sha": g0, "env": {}, "venv": VENV, "key": str(gk)},
                   {"sha": shas[-1], "env": {}, "venv": VENV, "key": str(rk)})
        print("finder:", res["named"], res["status"], res.get("uncontrolled"), res["why"][:120])
        named.append(res["named"])
    wrong = [n for n in named if n]
    assert not wrong, f"finder stated a commit for a flaky test in {len(wrong)} of 8 runs"


# ------------------------------------------------------- 5. an input masked by another one, the red from a third
def test_masked_input_is_not_blamed_when_the_red_comes_from_another(tmp_path):
    """The job turns on APP_STRICT=1 together with its shim APP_COMPAT=1 (harmless together; strict alone breaks
    the test) and also sets OUTPUT=json, which breaks the test. Removing OUTPUT=json from the red job makes it
    green; removing APP_STRICT does not. The split applies APP_STRICT alone to green (red), the confirmation
    replays the same subset (red) and the finder names APP_STRICT. No replay checks the red side (red minus the
    named input)."""
    repo, g = new_repo(tmp_path, {
        "pkg/out.py": """
            import os

            def render(v):
                strict = os.environ.get("APP_STRICT") == "1"
                compat = os.environ.get("APP_COMPAT") == "1"
                if strict and not compat:
                    return "<%s>" % v
                if os.environ.get("OUTPUT") == "json":
                    return '{"v": %s}' % v
                return str(v)
            """,
        "test_out.py": """
            from pkg import out

            def test_render():
                assert out.render(3) == "3" or out.render(3) == 3
            """})
    nid = "test_out.py::test_render"
    green_env = {"APP_STRICT": None, "APP_COMPAT": None, "OUTPUT": None}
    red_env = {"APP_STRICT": "1", "APP_COMPAT": "1", "OUTPUT": "json"}
    gk, rk = tmp_path / "g.json", tmp_path / "r.json"
    assert key_at(repo, g, nid, gk, green_env) == "pass"
    assert key_at(repo, g, nid, rk, red_env) == "fail"
    checkout(repo, g)
    # truth: the red job without OUTPUT passes; without APP_STRICT it still fails
    assert run_det(repo, VENV, nid, {**red_env, "OUTPUT": None})["outcome"] == "pass"
    assert run_det(repo, VENV, nid, {**red_env, "APP_STRICT": None})["outcome"] == "fail"
    res = find(repo, nid, {"sha": g, "env": green_env, "venv": VENV, "key": str(gk)},
               {"sha": g, "env": red_env, "venv": VENV, "key": str(rk)})
    print("finder:", res["named"], res["status"], res["why"], res["input_candidates"], _steps(res))
    assert res["named"] in ("env:OUTPUT", None), \
        f"finder named {res['named']}; the red job is green again without OUTPUT=json, and still red without it"


# ---------------------------------------------- 6. stale bytecode in the engine (checkout without fresh stamps)
def test_det_replay_runs_the_checked_out_source_not_stale_bytecode(tmp_path):
    """REPORT-2 lists the engine's shared bytecode cache as an open question (product impact UNKNOWN). This is the
    product situation: a reused CI workspace, plain ``git checkout`` (no harness stamps), two same-size versions
    of a module checked out within one second. The ``--det`` replay must run the checked-out source."""
    import os
    import time
    repo, g0 = new_repo(tmp_path, {"pkg/m.py": "def f(x):\n    return x + 1 + 0 * 4\n",
                                   "test_m.py": "from pkg import m\n\ndef test_f():\n    assert m.f(1) == 2\n"})
    bad = commit(repo, "same-size break", {"pkg/m.py": "def f(x):\n    return x * 3 + 0 * 8\n"})
    nid = "test_m.py::test_f"
    outs = []
    for _ in range(5):
        git(repo, "checkout", "-q", g0)
        stamp = int(time.time())
        os.utime(repo / "pkg/m.py", (stamp, stamp))  # what a checkout in the same second as the next one leaves
        o_green = run_det(repo, VENV, nid)["outcome"]
        git(repo, "checkout", "-q", bad)
        os.utime(repo / "pkg/m.py", (stamp, stamp))
        o_bad = run_det(repo, VENV, nid)["outcome"]
        outs.append((o_green, o_bad))
    print("outcomes (green, bad):", outs)
    assert all(o == ("pass", "fail") for o in outs), f"--det ran the other version's bytecode: {outs}"
