"""P0 harness (harness/parallel_proof): the 20-test synthetic project, the variants runner and the fingerprint
comparison, on this engine's ``--det -n``."""

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
pytest.importorskip("xdist")

from harness.parallel_proof import fpcompare, synth  # noqa: E402


def run(cwd, *args):
    env = {k: v for k, v in os.environ.items() if k not in ("DETPY_REEXEC", "PYTHONHASHSEED")}
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", *args],
                          cwd=cwd, capture_output=True, text=True, env=env, timeout=600)


def test_synthetic_project_and_comparison(tmp_path):
    proj = tmp_path / "proj"
    shared = synth.write(str(proj), str(tmp_path / "outside" / "shared.txt"), port=47000 + os.getpid() % 2000)
    os.makedirs(os.path.dirname(shared), exist_ok=True)
    traces = {}
    for label, extra in (("ser-a", []), ("ser-b", []), ("par-a", ["-n", "2", "--dist", "loadfile"]),
                         ("par-b", ["-n", "2", "--dist", "loadfile"])):
        if os.path.exists(shared):
            os.remove(shared)
        p = run(proj, "--det", f"--det-trace={tmp_path / (label + '.jsonl')}", *extra, "tests")
        assert p.returncode == 0, p.stdout + p.stderr
        assert "20 passed" in p.stdout
        traces[label] = fpcompare.load(str(tmp_path / (label + ".jsonl")))
    (sa, _), (sb, _), (pa, ma), (pb, mb) = (traces[k] for k in ("ser-a", "ser-b", "par-a", "par-b"))
    out = fpcompare.compare(sa, sb, pa, pb)
    assert out["tests_in_all"] == 20
    assert out["serial_noise"] == 0
    # review P1 finding 4: the reader reads the file the writer (on the other worker under loadfile) may or may not
    # have written yet: a real cross-worker race, now an event (fs.read). It is the only parallel noise allowed, and
    # its first difference must be that read
    reader = "tests/test_reader.py::test_reader"
    par_noise = {n for n in pa if n in pb and pa[n]["fingerprint"] != pb[n]["fingerprint"]}
    assert par_noise <= {reader}, par_noise
    for n in par_noise:
        diff = next((ea, eb) for ea, eb in zip(pa[n]["events"], pb[n]["events"]) if ea != eb)
        # the read of the shared file, or (R-055 V6) the existence check of that same file just before it
        assert any(e.get("o") in ("fs.read", "fs.read.outside", "fs.stat") and "shared.txt" in e.get("v", "")
                   for e in diff), diff
    assert fpcompare.plans_equal(ma, mb) is True
    # the only test whose events depend on placement is the victim (when the plan separates it from its polluter)
    victim_apart = pa["tests/test_victim.py::test_victim"]["worker"] != pa["tests/test_pollute.py::test_polluter"]["worker"]
    placed = set(out["placement_examples"])
    expected = {"tests/test_victim.py::test_victim"} if victim_apart else set()
    assert expected <= placed, out
    # review P1 finding 4: the reader's read of the file the writer leaves outside the project is an event (fs.read
    # with the content's digest, or <absent>); when the split runs the writer before it on the other worker, the
    # reader's events truthfully depend on placement, and that read is the first difference
    assert placed - expected <= {"tests/test_reader.py::test_reader"}, out
    for n in placed - expected:
        diff = next((ea, eb) for ea, eb in zip(sa[n]["events"], (pa if pa[n]["fingerprint"] != sa[n]["fingerprint"]
                                                                  else pb)[n]["events"]) if ea != eb)
        # the read of the shared file, or (R-055 V6) the existence check of that same file just before it
        assert any(e.get("o") in ("fs.read", "fs.read.outside", "fs.stat") and "shared.txt" in e.get("v", "")
                   for e in diff), diff
    assert out["outcome_differences"] == 0 and out["new_failures_caused_by_split"] == []
    # detpy verify classifies the victim's divergence as placement and names the polluter it lost
    from detpy import _core

    rep = json.loads(_core.verify([str(tmp_path / "ser-a.jsonl"), str(tmp_path / "par-a.jsonl")]))
    assert rep["summary"]["order_identical"]
    if victim_apart:
        v = next(t for t in rep["tests"] if t["nodeid"] == "tests/test_victim.py::test_victim")
        assert v["divergence"]["reason"] == "placement"
        assert "tests/test_pollute.py::test_polluter" in v["divergence"]["lost_predecessors"]


@pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
def test_synthetic_reader_of_a_file_written_by_another_test_is_never_cached(tmp_path):
    proj = tmp_path / "proj"
    shared = synth.write(str(proj), str(tmp_path / "outside" / "shared.txt"), port=49000 + os.getpid() % 2000)
    os.makedirs(os.path.dirname(shared), exist_ok=True)
    reused = []
    for i in range(2):
        out = tmp_path / f"o{i}.json"
        p = run(proj, "--det", f"--det-cache={tmp_path / 'c'}", f"--det-outcomes={out}", "-n", "2", "--dist",
                "loadfile", "tests")
        assert p.returncode == 0, p.stdout + p.stderr
        reused.append(set(json.loads(out.read_text())["cache"]["reused_ids"]))
    assert "tests/test_reader.py::test_reader" not in reused[1]
    assert "tests/test_writer.py::test_w2" in reused[1]
