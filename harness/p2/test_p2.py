"""P2 harness unit tests (spec, Testing plan: Unit (Python), +6). Run: python3 -m pytest -q harness/p2/test_p2.py

Each test states protects= / fails_when= / no_claim=.
"""
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import correctness  # noqa: E402
import fixed_run  # noqa: E402


def _verify(d, i, n, tests):
    os.makedirs(d, exist_ok=True)
    rep = {"tests": [{"nodeid": k, "status": s.split(":")[0],
                      "divergence": {"reason": s.split(":")[1]} if ":" in s else None} for k, s in tests.items()]}
    with open(os.path.join(d, f"verify{i}w{n}.json"), "w") as f:
        json.dump(rep, f)


def _ext(d, label, tests):
    os.makedirs(d, exist_ok=True)
    with gzip.open(os.path.join(d, f"tests-{label}.jsonl.gz"), "wt") as g:
        for k, (outcome, fp, events) in tests.items():
            g.write(json.dumps({"nodeid": k, "outcome": outcome, "fingerprint": fp, "events": events}) + "\n")


def test_variable_class_excluded(tmp_path):
    """protects= a test whose baseline class varies over rounds is excluded from rule 1;
    fails_when= such a test is reported as a change or a defect; no_claim= nothing about stable tests."""
    b, f = str(tmp_path / "b"), str(tmp_path / "f")
    _verify(b, 1, 2, {"t1": "stable", "t2": "stable"})
    _verify(b, 2, 2, {"t1": "not-proven:io", "t2": "stable"})
    _verify(b, 3, 2, {"t1": "stable", "t2": "stable"})
    for i in (1, 2, 3):
        _verify(f, i, 2, {"t1": "diverged", "t2": "stable"})
    r = correctness.rule1(b, f, 2)
    assert r["variable_class"] == ["t1"]
    assert r["changes"] == [] and r["defects"] == []


def test_unexplained_move_to_identical_flagged(tmp_path):
    """protects= a class change towards identical needs the fix's one-line explanation; fails_when= an unexplained
    move to identical passes; no_claim= whether the explanation is true (the reviewer reads it)."""
    b, f = str(tmp_path / "b"), str(tmp_path / "f")
    for i in (1, 2, 3):
        _verify(b, i, 4, {"t1": "not-proven:io", "t2": "stable"})
        _verify(f, i, 4, {"t1": "stable", "t2": "stable"})
    r = correctness.rule1(b, f, 4)
    assert len(r["changes"]) == 1 and r["changes"][0]["towards_identical"]
    assert [d["nodeid"] for d in r["defects"]] == ["t1"]
    r2 = correctness.rule1(b, f, 4, explain={"t1": "the hold no longer fires on this file, so io.release is gone"})
    assert r2["defects"] == [] and len(r2["changes"]) == 1


E1 = [{"o": "fs.read", "v": "a"}, {"o": "io.release", "v": "fs.read#1"}, {"o": "io.complete", "v": "x"}]


def _three_base(b, tests):
    for lab in ("base1", "base2", "base3"):
        _ext(b, f"F-{lab}", tests)


def test_changed_fixed_fingerprint_flagged(tmp_path):
    """protects= a fixed-epoch fingerprint that changes at the fix head (also on the repeat) with an undeclared event
    difference is a defect; fails_when= it passes; no_claim= tests unstable across the baseline fixed runs."""
    b, f = str(tmp_path / "b"), str(tmp_path / "f")
    _three_base(b, {"t": ("passed", "aa", E1)})
    changed = [E1[0], E1[1], {"o": "io.complete", "v": "y"}]
    _ext(f, "F-fix1", {"t": ("passed", "bb", changed)})
    first = correctness.rule2(b, ["base1", "base2", "base3"], f, "fix1")
    assert first["need_repeat"] == ["t"]
    _ext(f, "F-fix1r", {"t": ("passed", "bb", changed)})
    r = correctness.rule2(b, ["base1", "base2", "base3"], f, "fix1", "fix1r", declared=["io.release"])
    assert [d["nodeid"] for d in r["defects"]] == ["t"] and r["passed"] == 0


def test_declared_kinds_only_allowed(tmp_path):
    """protects= a difference made only of declared event kinds, with the same outcome, is allowed; fails_when= it is
    flagged; no_claim= the declared kinds are right (the coordinator approves them, gate note 1)."""
    b, f = str(tmp_path / "b"), str(tmp_path / "f")
    _three_base(b, {"t": ("passed", "aa", E1), "u": ("passed", "cc", [])})
    no_release = [E1[0], E1[2]]
    for lab in ("F-fix1", "F-fix1r"):
        _ext(f, lab, {"t": ("passed", "bb", no_release), "u": ("passed", "cc", [])})
    r = correctness.rule2(b, ["base1", "base2", "base3"], f, "fix1", "fix1r", declared=["io.release"])
    assert r["defects"] == [] and [a["nodeid"] for a in r["allowed_declared_only"]] == ["t"] and r["passed"] == 1


def test_declared_kinds_plus_other_flagged(tmp_path):
    """protects= a declared-kind difference plus one other event difference is a defect (a fix that drops or flattens
    recorded events in S and P alike is caught); fails_when= it is allowed; no_claim= which event is the cause."""
    b, f = str(tmp_path / "b"), str(tmp_path / "f")
    _three_base(b, {"t": ("passed", "aa", E1)})
    dropped = [E1[0]]  # io.release (declared) and io.complete (not declared) both gone
    for lab in ("F-fix1", "F-fix1r"):
        _ext(f, lab, {"t": ("passed", "bb", dropped)})
    r = correctness.rule2(b, ["base1", "base2", "base3"], f, "fix1", "fix1r", declared=["io.release"])
    assert [d["nodeid"] for d in r["defects"]] == ["t"] and r["allowed_declared_only"] == []


def test_fixed_run_command_uses_checkout_under_test(tmp_path):
    """protects= the fixed-epoch run uses the detjs.js of the checkout under test, --det-epoch=fixed and an F- trace
    path, never a timed trace name; fails_when= it runs the harness checkout's engine or writes S<i>/P<i>w<n>.jsonl;
    no_claim= the run itself succeeds."""
    spec = {"runner": "vitest", "args": ["--config", "x.ts"]}
    eng = str(tmp_path / "eng")
    tr = fixed_run.trace_path(str(tmp_path / "out"), "base1")
    cmd = fixed_run.build_cmd(spec, eng, tr)
    assert cmd[:3] == ["node", os.path.join(eng, "node", "bin", "detjs.js"), "vitest"]
    assert "--det-epoch=fixed" in cmd and "--det-workers=1" in cmd and f"--det-trace={tr}" in cmd
    assert os.path.basename(tr) == "F-base1.jsonl"
    for bad in ("S1.jsonl", "P2w4.jsonl", "../x.jsonl"):
        try:
            fixed_run.trace_path(str(tmp_path), "x", bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad} accepted")
    env, added = fixed_run.build_env({"env": {"NODE_ENV": "test"}}, "repo", ["DETJS_PHASES=1"], base={"CI": "1", "HOME": "/h"})
    assert "CI" not in env and env["NODE_ENV"] == "test" and env["TMPDIR"] == "/tmp/pm-repo" and added == {"DETJS_PHASES": "1"}
