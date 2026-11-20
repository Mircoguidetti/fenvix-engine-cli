"""Review R-019: cases the exact-culprit validation did not cover, run through the prototype finder unchanged.

Each test builds a small git repository, records the green and the red proof key with
``pytest --det --det-cache-keys`` (as the harness does) and runs ``finder.Finder`` as ``run_code_cases.py`` and
``nocode.py`` call it. The assertion is the right answer; every test fails today because the finder names an
innocent commit or input with no sign of doubt.

    python -m pytest -p no:cacheprovider harness/culprit/review_r019     # detpy installed in this interpreter
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import checkout, git_bisect, run_det  # noqa: E402
from finder import Finder  # noqa: E402

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
VENV = Path(sys.prefix)


def git(repo, *args, env=None):
    e = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid", **(env or {})}
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=e)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


def write(repo: Path, files: dict) -> None:
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text).lstrip())


def commit(repo: Path, msg: str, files: dict | None = None) -> str:
    if files:
        write(repo, files)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def new_repo(tmp_path: Path, files: dict) -> tuple[Path, str]:
    repo = tmp_path / "proj"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "core.fileMode", "true")
    write(repo, {"pytest.ini": "[pytest]\n", "pkg/__init__.py": "", **files})
    return repo, commit(repo, "green")


def key_at(repo: Path, sha: str, nodeid: str, path: Path, env: dict | None = None, want: str | None = None,
           tries: int = 1) -> str:
    """Record the proof key of one run (retried until the outcome is ``want``, for the flaky case)."""
    for _ in range(tries):
        checkout(repo, sha)
        r = run_det(repo, VENV, nodeid, env, keys=str(path))
        if want is None or r["outcome"] == want:
            return r["outcome"]
    raise AssertionError(f"no {want} run of {nodeid} at {sha[:8]} in {tries} tries: {r['tail']}")


def find(repo, nodeid, green: dict, red: dict) -> dict:
    res = Finder(repo, nodeid, green, red).run()
    c = res.get("culprit") or {}
    res["named"] = c.get("commit") or c.get("input")
    return res


# ------------------------------------------------------------------------------------------------ 1. interaction
def test_two_inputs_together_are_not_blamed_on_a_third(tmp_path):
    """The red needs APP_LEGACY_FORMAT=1 and APP_STRICT=1 together; LOG_LEVEL also changed and is harmless.

    The input split applies one half at a time to the green environment and keeps the other half when the first
    passes, so neither culprit alone reproduces the red and the search ends on the decoy.
    """
    repo, g = new_repo(tmp_path, {
        "pkg/fmt.py": """
            import os

            def render(amount):
                strict = os.environ.get("APP_STRICT") == "1"
                legacy = os.environ.get("APP_LEGACY_FORMAT") == "1"
                level = os.environ.get("LOG_LEVEL", "INFO")  # only decides how much is logged
                s = f"{amount:.2f}"
                if strict and legacy:  # strict mode rounds legacy amounts
                    s = str(round(amount))
                return s
            """,
        "test_fmt.py": """
            from pkg import fmt

            def test_render():
                assert fmt.render(2.5) == "2.50"
            """})
    nid = "test_fmt.py::test_render"
    green_env = {"APP_STRICT": None, "APP_LEGACY_FORMAT": None, "LOG_LEVEL": "INFO"}
    red_env = {"APP_STRICT": "1", "APP_LEGACY_FORMAT": "1", "LOG_LEVEL": "DEBUG"}
    gk, rk = tmp_path / "g.json", tmp_path / "r.json"
    assert key_at(repo, g, nid, gk, green_env) == "pass"
    assert key_at(repo, g, nid, rk, red_env) == "fail"
    # the decoy alone does not break the test
    checkout(repo, g)
    assert run_det(repo, VENV, nid, {**green_env, "LOG_LEVEL": "DEBUG"})["outcome"] == "pass"

    res = find(repo, nid, {"sha": g, "env": green_env, "venv": VENV, "key": str(gk)},
               {"sha": g, "env": red_env, "venv": VENV, "key": str(rk)})
    print("finder:", res["named"], "executions:", res["executions"], "candidates:", res["input_candidates"])
    assert res["named"] in ("env:APP_STRICT", "env:APP_LEGACY_FORMAT"), \
        f"finder blamed {res['named']} (harmless) for a red that needs APP_STRICT and APP_LEGACY_FORMAT together"


# ------------------------------------------------------------------------------- 2. input outside the proof key
def test_exec_bit_dropped_is_not_blamed_on_a_later_refactor(tmp_path):
    """A commit drops the executable bit of a script (mode 100755 -> 100644, content unchanged); a later commit
    refactors a helper the test runs, harmlessly. ``os.access``/``os.stat`` are not inputs of the key, and the
    commit pruning compares blob contents, so the mode commit is no candidate: the finder names the refactor with
    zero executions. ``git bisect run`` names the mode commit."""
    repo, g = new_repo(tmp_path, {
        "bin/deploy.sh": "#!/bin/sh\necho deploy\n",
        "pkg/tools.py": """
            import os

            def script_path(root):
                return os.path.join(root, "bin", "deploy.sh")

            def is_runnable(path):
                return os.access(path, os.X_OK)
            """,
        "test_tools.py": """
            import os
            from pkg import tools

            ROOT = os.path.dirname(os.path.abspath(__file__))

            def test_deploy_script_is_runnable():
                assert tools.is_runnable(tools.script_path(ROOT))
            """})
    git(repo, "update-index", "--chmod=+x", "bin/deploy.sh")
    git(repo, "commit", "-q", "--amend", "-m", "green")
    g = git(repo, "rev-parse", "HEAD")
    git(repo, "update-index", "--chmod=-x", "bin/deploy.sh")
    git(repo, "commit", "-q", "-m", "regenerate scripts (loses the exec bit)")
    culprit = git(repo, "rev-parse", "HEAD")
    red = commit(repo, "refactor: script_path via a constant", {"pkg/tools.py": """
            import os

            SCRIPTS = "bin"

            def script_path(root):
                return os.path.join(root, SCRIPTS, "deploy.sh")

            def is_runnable(path):
                return os.access(path, os.X_OK)
            """})
    nid = "test_tools.py::test_deploy_script_is_runnable"
    gk, rk = tmp_path / "g.json", tmp_path / "r.json"
    assert key_at(repo, g, nid, gk) == "pass"
    assert key_at(repo, red, nid, rk) == "fail"
    # truth: the mode commit turns it red, the refactor alone does not
    checkout(repo, culprit)
    assert run_det(repo, VENV, nid)["outcome"] == "fail"

    res = find(repo, nid, {"sha": g, "env": {}, "venv": VENV, "key": str(gk)},
               {"sha": red, "env": {}, "venv": VENV, "key": str(rk)})
    print("finder:", res["named"], "executions:", res["executions"], "commit candidates:", res["commit_candidates"])
    b = git_bisect(repo, VENV, g, red, ["--tb=no", nid])
    print("git bisect:", b["named"], "right" if b["named"] and culprit.startswith(b["named"]) else "wrong")
    assert res["named"] == culprit, \
        f"finder named {res['named'][:10] if res['named'] else None} (the harmless refactor) with " \
        f"{res['executions']} executions; the culprit is {culprit[:10]} (exec bit dropped)"


# ---------------------------------------------------------------------------------------------- 3. flaky test
def test_flaky_test_is_not_blamed_on_a_commit(tmp_path):
    """The test assumes two uuid4 ids sort in creation order: it fails half the time at every commit, green
    included. ``run_det`` does not pass ``--det-urandom`` (as in the study), and the key flags the entropy draw,
    but the finder ignores the flag and binary-searches three harmless commits on one run per step: it always
    names one of them."""
    impls = ["return uuid.uuid4().hex", "return str(uuid.uuid4()).replace('-', '')", "return uuid.uuid4().hex[:]",
             "value = uuid.uuid4()\n    return value.hex"]
    src = "import uuid\n\ndef new_id():\n    {}\n"
    repo, g = new_repo(tmp_path, {
        "pkg/ids.py": src.format(impls[0]),
        "test_ids.py": """
            from pkg import ids

            def test_ids_increase():
                a, b = ids.new_id(), ids.new_id()
                assert sorted([a, b]) == [a, b]
            """})
    shas = [commit(repo, f"tidy new_id ({i})", {"pkg/ids.py": src.format(x)}) for i, x in enumerate(impls[1:])]
    red = shas[-1]
    nid = "test_ids.py::test_ids_increase"
    gk, rk = tmp_path / "g.json", tmp_path / "r.json"
    key_at(repo, g, nid, gk, want="pass", tries=40)
    key_at(repo, red, nid, rk, want="fail", tries=40)
    # the green commit fails too: there is no culprit commit
    checkout(repo, g)
    outs = {run_det(repo, VENV, nid)["outcome"] for _ in range(12)}
    assert outs == {"pass", "fail"}

    res = find(repo, nid, {"sha": g, "env": {}, "venv": VENV, "key": str(gk)},
               {"sha": red, "env": {}, "venv": VENV, "key": str(rk)})
    print("finder:", res["named"], "executions:", res["executions"], "steps:",
          [(s["sha"][:8], s["outcome"]) for s in res["steps"]])
    assert res["named"] is None, \
        f"finder named commit {res['named'][:10]} for a test that is flaky at the green commit itself"


# ------------------------------------------------------------------------------------- 4. break, fix, break
def test_non_monotonic_history_names_the_newest_transition(tmp_path):
    """C1 breaks ``f``, C2 reverts it, C3 breaks ``f`` again in another way. The red at C3 comes from C3. The
    finder's first probe is the oldest candidate, it fails, and the search stops there: it names C1, whose
    breakage was already fixed. (Kind a cannot contain this: the planted commit is always the first one.)"""
    repo, g = new_repo(tmp_path, {
        "pkg/m.py": "def f(x):\n    return x + 1\n",
        "test_m.py": "from pkg import m\n\ndef test_f():\n    assert m.f(1) == 2\n"})
    c1 = commit(repo, "C1 breaks f", {"pkg/m.py": "def f(x):\n    return x + 2\n"})
    c2 = commit(repo, "C2 reverts C1", {"pkg/m.py": "def f(x):\n    return x + 1\n"})
    c3 = commit(repo, "C3 breaks f again", {"pkg/m.py": "def f(x):\n    return x * 3\n"})
    nid = "test_m.py::test_f"
    gk, rk = tmp_path / "g.json", tmp_path / "r.json"
    assert key_at(repo, g, nid, gk) == "pass"
    assert key_at(repo, c3, nid, rk) == "fail"
    checkout(repo, c2)
    assert run_det(repo, VENV, nid)["outcome"] == "pass"

    res = find(repo, nid, {"sha": g, "env": {}, "venv": VENV, "key": str(gk)},
               {"sha": c3, "env": {}, "venv": VENV, "key": str(rk)})
    b = git_bisect(repo, VENV, g, c3, ["--tb=no", nid])
    print("git bisect:", b["named"], "right" if b["named"] and c3.startswith(b["named"]) else "wrong")
    print("finder:", res["named"], "c1", c1, "c3", c3, "steps:", [(s["sha"][:8], s["outcome"]) for s in res["steps"]])
    assert res["named"] == c3, f"finder named {res['named'][:10]} (C1, already reverted by C2); the red comes from C3"


# ------------------------------------------------------------------------------------------ control (passes)
def test_control_culprit_in_the_middle_of_a_monotonic_history(tmp_path):
    """Positive control: one breaking commit in the middle of eight that all touch the function the test runs.
    The finder is right here; the cases above fail for the reasons they name, not for a harness problem."""
    repo, g = new_repo(tmp_path, {"pkg/m.py": "def f(x):\n    return x + 1  # v0\n",
                                  "test_m.py": "from pkg import m\n\ndef test_f():\n    assert m.f(1) == 2\n"})
    shas = []
    for i in range(1, 9):
        body = f"x + 1 + 0 * {i}" if i < 5 else f"x * 3 + 0 * {i}"  # every commit changes f; c5 breaks it
        shas.append(commit(repo, f"c{i}", {"pkg/m.py": f"def f(x):\n    return {body}\n"}))
    nid = "test_m.py::test_f"
    gk, rk = tmp_path / "g.json", tmp_path / "r.json"
    assert key_at(repo, g, nid, gk) == "pass"
    assert key_at(repo, shas[-1], nid, rk) == "fail"
    res = find(repo, nid, {"sha": g, "env": {}, "venv": VENV, "key": str(gk)},
               {"sha": shas[-1], "env": {}, "venv": VENV, "key": str(rk)})
    print("finder:", res["named"], "executions:", res["executions"], "candidates:", res["commit_candidates"])
    assert res["commit_candidates"] == 8 and res["named"] == shas[4]
