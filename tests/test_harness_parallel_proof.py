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
    assert out["serial_noise"] == 0 and out["parallel_noise"] == 0
    assert fpcompare.plans_equal(ma, mb) is True
    # the only test whose events depend on placement is the victim (when the plan separates it from its polluter)
    victim_apart = pa["tests/test_victim.py::test_victim"]["worker"] != pa["tests/test_pollute.py::test_polluter"]["worker"]
    assert out["placement"] == (1 if victim_apart else 0)
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
