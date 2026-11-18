"""Guards around the R-010 fixes (the two reviewer tests are in test_r010_market_review.py).

    python3 -m pytest -q harness/market_test/tests/test_r010_fixes.py
"""
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
import aggregate  # noqa: E402
import market  # noqa: E402
import walk  # noqa: E402
from test_r002_capture import g  # noqa: E402
from test_r010_market_review import PY_CMD, PY_INSTALL, _repo  # noqa: E402

T = {"sha": "0" * 40}


def _walker(tmp_path, files, subject="c1"):
    work, src = _repo(tmp_path, "r010-fix")
    for rel, text in files.items():
        (src / rel).write_text(text)
    (src / "README.md").write_text("c0\n")
    g(src, "add", "-A"); g(src, "commit", "-qm", "c0")
    c0 = g(src, "rev-parse", "HEAD")
    (src / "README.md").write_text("c1\n")
    g(src, "commit", "-qam", subject)
    c1 = g(src, "rev-parse", "HEAD")
    spec = {"name": "r010-fix", "lang": "pytest", "seq": {"kind": "list", "commits": [c0, c1]},
            "units": {"include": ["tests/test_*.py"]}, "workers": 1, "install": PY_INSTALL, "cmd": PY_CMD}
    w = walk.Walker(spec, work, tmp_path / "out.json.gz", 0, 1, 30, "r010")
    w.push = False
    assert w.install()[0]
    return w, c0, c1


def test_unit_that_never_reads_git_keeps_its_skip(tmp_path):
    """The commit enters the key only of a unit that read .git: any other unit is still reused at the next commit."""
    w, c0, c1 = _walker(tmp_path, {"tests/test_plain.py": "def test_a():\n    assert True\n"})
    w.checkout(c0)
    rec = w.run_unit("tests/test_plain.py"); rec["sha"] = c0
    assert rec["code"] == 0 and rec["deps"]["git"] is None
    assert not [p for p in rec["deps"]["reads"] if "/.git/" in p]
    w.checkout(c1)
    decision, _ = w.decide("tests/test_plain.py", rec, c1, [c0, c1])
    assert decision["closure"] is None


def test_git_reader_records_head_and_reruns_with_a_git_reason(tmp_path):
    test = ('import subprocess\n\ndef test_sha():\n'
            '    assert len(subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()) == 40\n')
    w, c0, c1 = _walker(tmp_path, {"tests/test_sha.py": test})
    w.checkout(c0)
    rec = w.run_unit("tests/test_sha.py"); rec["sha"] = c0
    assert rec["deps"]["git"]["head"] == c0
    assert not [p for p in rec["deps"]["reads"] if "/.git/objects/" in p]      # the object store stays out
    decision, _ = w.decide("tests/test_sha.py", rec, c0, [c0, c1])
    assert decision["closure"] is None                                        # same commit: reusable
    w.checkout(c1)
    decision, _ = w.decide("tests/test_sha.py", rec, c1, [c0, c1])
    assert decision["closure"] == "git:HEAD"


def test_git_status_reader_reruns_when_only_the_index_changes(tmp_path):
    """`git status` / `git diff --cached` read the index: a staged change at the same commit reruns the unit."""
    test = ('import subprocess\n\ndef test_clean():\n'
            '    assert subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True) == ""\n')
    w, c0, c1 = _walker(tmp_path, {"tests/test_idx.py": test})
    w.checkout(c0)
    rec = w.run_unit("tests/test_idx.py"); rec["sha"] = c0
    assert rec["code"] == 0
    (w.src / "staged.txt").write_text("x\n")
    g(w.src, "add", "staged.txt")
    assert g(w.src, "rev-parse", "HEAD") == c0
    decision, _ = w.decide("tests/test_idx.py", rec, c0, [c0, c1])
    assert decision["closure"] is not None


def test_classify_needs_evidence_of_a_flip():
    old_blind = {"unit": "u", "same": False, "diff": [], "rerun_matches_cache": 2, "rerun_matches_fresh": 2}
    assert aggregate.classify(old_blind, T) == "wrong"            # pre-fix item, exit code only: no evidence
    old_ids = {"unit": "u", "same": False, "diff": ["u::t"], "rerun_matches_cache": 2, "rerun_matches_fresh": 0}
    assert aggregate.classify(old_ids, T) == "flaky"              # both reruns gave the cached outcomes back
    new = {"unit": "u", "same": False, "diff": [], "cache_code": 0, "fresh_code": 1}
    assert aggregate.classify({**new, "rerun_codes": [1, 1], "rerun_matches_cache": 0, "rerun_matches_fresh": 2},
                              T) == "wrong"
    assert aggregate.classify({**new, "rerun_codes": [0, 1], "rerun_matches_cache": 1, "rerun_matches_fresh": 1},
                              T) == "flaky"
    assert aggregate.classify({**new, "rerun_codes": [0, 0], "rerun_matches_cache": 2, "rerun_matches_fresh": 0},
                              T) == "flaky"


def test_classify_accepts_a_recheck_that_shows_the_flip(monkeypatch):
    v = {"unit": "u", "same": False, "diff": [], "rerun_matches_cache": 2, "rerun_matches_fresh": 2}
    monkeypatch.setattr(aggregate, "_RECHECK", {("u", T["sha"]): "not-reproducible"})
    assert aggregate.classify(v, T) == "flaky"
    monkeypatch.setattr(aggregate, "_RECHECK", {("u", T["sha"]): "code-change"})
    assert aggregate.classify(v, T) == "wrong"


def test_rekey_git_reruns_git_units_and_takes_them_out_of_the_verified_skips():
    sh = {"transitions": [{"i": 1, "sha": "a", "tests": {"g": 1, "p": 1}, "decisions": {},
                           "verify": [{"unit": "g", "same": False}, {"unit": "p", "same": True}]}]}
    out, moved = market.rekey_git([sh], {"g"})
    t = out[0]["transitions"][0]
    assert t["decisions"]["g"]["closure"] == "git:HEAD" and "p" not in t["decisions"]
    assert [v["unit"] for v in t["verify"]] == ["p"] and [v["unit"] for v in moved] == ["g"]
    assert sh["transitions"][0]["decisions"] == {}                # the input is not modified
