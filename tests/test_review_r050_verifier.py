"""Review R-050, re-check of PR #11 (claude/verifier-cli @ baaeba0, code ac497c0) for reviewer p1-verifier #10.

V10 (F-18): `fenvix explore` reports a clean result (exit 0, "0 flaky failing tests (0 always failing, not flaky)")
for a suite that plain pytest cannot run: one file with a syntax error next to a good file. Plain pytest stops at
collection ("Interrupted: 1 error during collection", exit 2, no test run). The reviewer's own test (only the broken
file, no other) passes on ac497c0; this variant fails there on 3.12, 3.13 and 3.14.
"""
import os
import subprocess
import sys


def test_v10_explore_does_not_report_clean_when_the_suite_cannot_be_collected(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_broken.py").write_text("def test_ok(:\n    pass\n")
    (tmp_path / "tests" / "test_fine.py").write_text("def test_fine():\n    pass\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DETPY_", "PYTEST_"))}
    plain = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], cwd=tmp_path,
                           capture_output=True, text=True, env=env, timeout=300)
    assert plain.returncode == 2 and "error during collection" in plain.stdout, plain.stdout[-1500:]  # precondition
    r = subprocess.run([sys.executable, "-m", "detpy.fenvix", "explore", "--budget", "0.3", "--max-seeds", "2",
                        "--out", str(tmp_path / "ex")], cwd=tmp_path, capture_output=True, text=True, env=env,
                       timeout=900)
    assert r.returncode != 0, f"explore exit 0 for a suite plain pytest cannot collect:\n{r.stdout}{r.stderr}"
