"""Review R-050, re-check of PR #5 (claude/py-cache @ 2a7f0d1e): the placement replay never hides a real failure.

P2 (blocking, wrong result): an earlier test file pollutes shared state, so the user's normal run (plain `pytest`,
and `pytest --det`) fails a later file's test. Under `--det-cache` PR #5 runs each test file in its own child by
default (1b6179d), so the victim passes there. The run reports "2 passed", exit 0, with no placement finding, on a
fresh cache. The placement replay (b23026c) looks only at tests that *fail* in their child. On the trunk build
(fdf6029 code) the same command reports the failure.
P1 (guard, passes on 2a7f0d1e): a test that fails in every placement stays failed, with no finding.
"""
import os
import subprocess
import sys

import pytest

CONF = "import sys, os\nsys.path.insert(0, os.path.dirname(__file__))\n"


def _project(root, files):
    for rel, text in {"tests/conftest.py": CONF, **files}.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def _pytest(root, *args):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "DETPY_CACHE_IN_PROCESS")}
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", "-p", "no:randomly",
                        *args, "tests"], cwd=root, capture_output=True, text=True, env=env, timeout=600)
    out = {}
    for line in p.stdout.splitlines():
        if line.startswith(("PASSED ", "FAILED ", "ERROR ")):
            out[line.split()[1]] = line.split()[0].lower()
    return p, out


def test_p2_a_failure_an_earlier_file_causes_in_the_normal_run_is_not_reported_passed(tmp_path):
    _project(tmp_path, {
        "tests/helper.py": "STATE = {'mode': 'good'}\n",
        "tests/test_a_setup.py": "from helper import STATE\n\ndef test_pollutes():\n    STATE['mode'] = 'bad'\n",
        "tests/test_b_client.py": "from helper import STATE\n\ndef test_victim():\n    assert STATE['mode'] == 'good'\n"})
    victim = "tests/test_b_client.py::test_victim"
    plain, po = _pytest(tmp_path)
    assert plain.returncode == 1 and po.get(victim) == "failed", plain.stdout[-1500:]  # the user's normal run
    det, do = _pytest(tmp_path, "--det")
    assert det.returncode == 1 and do.get(victim) == "failed", det.stdout[-1500:]
    p, o = _pytest(tmp_path, "--det", f"--det-cache={tmp_path / '.c'}")
    finding = "PLACEMENT FINDINGS" in p.stdout
    assert o.get(victim) == "failed" or finding, (
        f"--det-cache reports {o} (exit {p.returncode}) with no placement finding; plain pytest and --det fail "
        f"{victim}:\n{p.stdout[-2000:]}")


def test_p1_a_real_failure_stays_failed(tmp_path):
    _project(tmp_path, {
        "tests/helper.py": "STATE = {}\n",
        "tests/test_a_setup.py": "from helper import STATE\n\ndef test_sets():\n    STATE['creds'] = 'x'\n",
        "tests/test_b_client.py": "from helper import STATE\n\ndef test_use():\n    assert STATE.get('creds') == 'y'\n"})
    for i in (1, 2):
        p, o = _pytest(tmp_path, "--det", f"--det-cache={tmp_path / '.c'}")
        assert p.returncode == 1 and o.get("tests/test_b_client.py::test_use") == "failed", p.stdout[-2000:]
        assert "PLACEMENT FINDINGS" not in p.stdout, p.stdout[-2000:]
