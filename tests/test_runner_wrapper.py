"""runner/fenvix-run: two jobs on one machine, the second reuses with proof, the step summary says so, verify finds
no wrong reuse; a flaky (order-dependent) test is reported with its replay command."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[1] / "runner" / "fenvix-run"

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


def write(root: Path, files: dict) -> None:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def job(tmp_path: Path, project: Path, name: str, *extra: str) -> tuple[int, dict, str]:
    out = tmp_path / name
    summary_md = tmp_path / f"{name}.md"
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "GITHUB_STEP_SUMMARY": str(summary_md),
           "FENVIX_CACHE_ROOT": str(tmp_path / "machine-cache"), "TMPDIR": str(tmp_path),
           "FENVIX_AUDIT_SHARE": "0"}  # no cache audit: it would run a random 5% of the reusable tests fresh
    r = subprocess.run([sys.executable, str(WRAPPER), *extra, "--project", str(project), "--python", sys.executable,
                        "--out", str(out), *([] if extra[:1] == ("verify",) else ["--key", "demo/project"])],
                       env=env, capture_output=True, text=True, timeout=600)
    data = json.loads((out / ("verify.json" if extra[:1] == ("verify",) else "summary.json")).read_text())
    return r.returncode, data, summary_md.read_text() if summary_md.exists() else ""


def test_second_job_reuses_with_proof_and_verify_finds_no_wrong_reuse(tmp_path):
    proj = tmp_path / "proj"
    write(proj, {
        "pkg/__init__.py": "",
        "pkg/a.py": "def double(x):\n    return 2 * x\n",
        "pkg/b.py": "def inc(x):\n    return x + 1\n",
        "test_a.py": "from pkg.a import double\n\ndef test_double():\n    assert double(2) == 4\n",
        "test_b.py": "from pkg.b import inc\n\ndef test_inc():\n    assert inc(1) == 2\n",
        "pytest.ini": "[pytest]\n",
    })
    code, s1, md1 = job(tmp_path, proj, "job1")
    assert code == 0 and s1["tests"] == 2 and s1["reused_with_proof"] == 0 and not s1["cache_was_warm"]
    assert "cold" in md1 and "| Tests | **2** |" in md1

    # commit N+1: pkg/b.py changes, so test_inc runs again and test_double is reused
    (proj / "pkg/b.py").write_text("def inc(x):\n    return 1 + x\n")
    code, s2, md2 = job(tmp_path, proj, "job2")
    assert code == 0 and s2["cache_was_warm"]
    assert s2["reused_outcomes"] == {"test_a.py::test_double": "passed"}
    assert s2["ran"] == 1
    assert "Skipped with proof (result reused, receipt kept) | **1** |" in md2
    receipts = [json.loads(x) for x in Path(s2["receipts"]).read_text().splitlines()]
    assert {r["nodeid"] for r in receipts if r["reused"]} == {"test_a.py::test_double"}

    code, v, mdv = job(tmp_path, proj, "job2", "verify", "--summary", str(tmp_path / "job2" / "summary.json"))
    assert code == 0 and v["checked"] == 1 and v["same"] == 1 and v["wrong"] == []
    assert "wrong: 0" in mdv


def test_order_dependent_failure_is_reported_flaky_with_replay(tmp_path):
    proj = tmp_path / "proj"
    write(proj, {
        "state.py": "SEEN = []\n",
        "test_m.py": (
            "import state\n\n"
            "def test_1_pollutes():\n    state.SEEN.append(1)\n\n"
            "def test_2_victim():\n    assert state.SEEN == []\n"),
        "pytest.ini": "[pytest]\n",
    })
    code, s, md = job(tmp_path, proj, "job")
    assert code != 0
    assert s["failed"] == []
    assert [f["nodeid"] for f in s["flaky"]] == ["test_m.py::test_2_victim"]
    assert "detpy repro" in s["flaky"][0]["minimise"]
    assert "Flaky tests" in md and "replay" in md
