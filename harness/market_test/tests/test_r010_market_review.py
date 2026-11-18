"""R-010 reviewer tests for the market test (fenvix-engine-cli claude/market-test, commit e2107683).

Each test asserts what the proof rule or the verifier promises and FAILS on e2107683.

    python3 -m pytest -q harness/market_test/tests/test_r010_market_review.py

Needs git, strace and uv (as test_r002_capture.py).
"""
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
import aggregate  # noqa: E402
import walk  # noqa: E402
from test_r002_capture import g  # noqa: E402

PY_INSTALL = ["test -x {py} || uv venv -q --python 3.13 {venv}", "uv pip install -q --python {py} pytest"]
PY_CMD = ["{py}", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "s2_report", "{unit}"]

# The prefect shape (tests/utilities/test_dockerutils.py at 5e8ca118): the test file asks git for the commit and
# puts it in the parametrized IDs. Here the same file also asserts on the commit subject, so the outcome depends on
# .git too: a release-check or a version assertion is the pass/fail form of the same input.
TEST_GIT = '''import subprocess

import pytest

SHA = subprocess.check_output(["git", "rev-parse", "--short=7", "HEAD"], text=True).strip()
SUBJECT = subprocess.check_output(["git", "log", "-1", "--format=%s"], text=True).strip()


@pytest.mark.parametrize("image", [f"prefecthq/prefect-dev:sha-{SHA}-python3.13"])
def test_image_name(image):
    assert image.endswith("-python3.13")
    assert "BROKEN" not in SUBJECT
'''


def _repo(tmp_path, name):
    work = tmp_path / "work"
    src = work / "src"
    (src / "tests").mkdir(parents=True)
    g(src, "init", "-q", "-b", "main")
    g(src, "config", "user.email", "r@x"); g(src, "config", "user.name", "r")
    return work, src


# -- defect 1: .git is not in the key (limit N9), the prefect wrong hit --------------------------------------
def test_unit_that_reads_the_commit_from_git_reruns_when_the_commit_changes(tmp_path):
    """prefect's 3 strict wrong hits: a unit whose test IDs (and here outcome) come from git is reused at a new
    commit, because strace_deps.SKIP_PARTS drops every read under .git/. The proof rule must rerun it."""
    work, src = _repo(tmp_path, "r010-git")
    (src / "tests" / "test_git.py").write_text(TEST_GIT)
    (src / "README.md").write_text("c0\n")
    g(src, "add", "-A"); g(src, "commit", "-qm", "c0")
    c0 = g(src, "rev-parse", "HEAD")
    (src / "README.md").write_text("c1\n")          # a file the unit never reads
    g(src, "commit", "-qam", "BROKEN release")
    c1 = g(src, "rev-parse", "HEAD")
    spec = {"name": "r010-git", "lang": "pytest", "seq": {"kind": "list", "commits": [c0, c1]},
            "units": {"include": ["tests/test_*.py"]}, "workers": 1, "install": PY_INSTALL, "cmd": PY_CMD}
    w = walk.Walker(spec, work, tmp_path / "out.json.gz", 0, 1, 30, "r010")
    w.push = False
    assert w.install()[0]
    w.checkout(c0)
    rec = w.run_unit("tests/test_git.py"); rec["sha"] = c0
    assert rec["code"] == 0
    w.checkout(c1)
    fresh = w.run_unit("tests/test_git.py", traced_run=False)
    # the fresh run at c1 differs from the cached one: other test IDs (prefect) and a failure (pass/fail form)
    assert set(walk.outcome_summary(fresh["tests"])) != set(walk.outcome_summary(rec["tests"]))
    assert fresh["code"] != 0
    decision, _ = w.decide("tests/test_git.py", rec, c1, [c0, c1])
    assert decision["closure"] is not None, (
        "closure reuses a PASS at a commit where the fresh run FAILS: the unit's input (git HEAD) is not in the key")


# -- defect 2: an exit-code-only mismatch is called flaky without evidence -----------------------------------
def test_reproducible_exit_code_change_on_a_verified_skip_is_wrong_not_flaky(tmp_path, monkeypatch):
    """pydantic-ai tests/harness/pixeltable/test_video.py at i = 15 and 38: the cached run exited 0, the fresh run
    of the verified skip exited non-zero (the next commit shows "cached-failure") with the same test outcomes
    (diff []). walk.compare re-runs twice but compares only the test outcomes, never the exit code, so
    rerun_matches_cache = rerun_matches_fresh = 2 and aggregate.classify returns "flaky" whatever the reruns'
    exit codes were. Here the fresh exit code reproduces on every run: the verdict must be "wrong"."""
    work, src = _repo(tmp_path, "r010-code")
    (src / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n")
    g(src, "add", "-A"); g(src, "commit", "-qm", "c0")
    c0 = g(src, "rev-parse", "HEAD")
    (src / "README.md").write_text("c1\n")
    g(src, "add", "-A"); g(src, "commit", "-qm", "c1")
    c1 = g(src, "rev-parse", "HEAD")
    spec = {"name": "r010-code", "lang": "pytest", "seq": {"kind": "list", "commits": [c0, c1]},
            "units": {"include": ["tests/test_*.py"]}, "workers": 1, "verify": 1.0, "plain_baseline": False,
            "install": PY_INSTALL, "cmd": PY_CMD}
    w = walk.Walker(spec, work, tmp_path / "out.json", 0, 1, 30, "r010")
    w.push = False
    head = {"sha": c0}

    real_checkout = w.checkout

    def checkout(sha):
        head["sha"] = sha
        return real_checkout(sha)

    def run_unit(unit, traced_run=True, tag="run"):
        # same test outcomes at both commits; at c1 the file exits 1 on every run (e.g. a session-finish hook or a
        # crash at interpreter exit after the report is written): a reproducible file-level pass -> fail
        code = 0 if head["sha"] == c0 else 1
        return {"code": code, "tests": {f"{unit}::test_a": ["passed"]}, "test_time": 0.1, "wall": 0.2,
                "deps": {"reads": {}, "net_ext": 0}, "tail": ""}

    def decide(unit, rec, sha, shas):
        r = "new" if rec is None else None    # nothing the unit read changed: closure skips it
        return {k: r for k in w.rules()}, {}

    monkeypatch.setattr(w, "checkout", checkout)
    monkeypatch.setattr(w, "run_unit", run_unit)
    monkeypatch.setattr(w, "decide", decide)
    w.walk()
    t = w.result["transitions"][0]
    assert [v["unit"] for v in t["verify"]] == ["tests/test_a.py"]
    v = t["verify"][0]
    assert v["same"] is False                         # the verifier saw the pass -> fail
    assert aggregate.classify(v, t) == "wrong", (
        f"a reproducible exit-code change is classified {aggregate.classify(v, t)!r}: {v}")
