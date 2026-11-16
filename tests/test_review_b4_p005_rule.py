"""B4: the new P-005 rule (fixed-dir fs writes + xdist baseline + never fails under --det -> b).

The rule's evidence says "a serial --det run never does", but `_never_under_det` is computed from the
fixed-order --det runs only. The seed exploration runs are serial --det runs too; when one of them
failed (best_attempt "seed S:k/n", k > 0), the failure happened in a single process, in an order,
so it is not a cross-process race. Run with HARNESS=<worktree>/harness.
"""
import importlib.util
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location("analyze_flaky", Path(os.environ.get("HARNESS", Path(__file__).resolve().parents[1] / "harness")) / "analyze_flaky.py")
af = importlib.util.module_from_spec(spec)
spec.loader.exec_module(af)

SRC = '''
_SEEN = []
def test_writes_build_dir():
    global _SEEN
    os.makedirs("build/cache", exist_ok=True)
    _SEEN.append(1)
    assert len(_SEEN) == 1
'''

ROW = {
    "nodeid": "tests/test_x.py::test_writes_build_dir",
    "idoft_category": "",              # popular pool, not in IDoFT
    "baseline_outcomes": "failed=3;passed=7",
    "det_outcomes": "passed=10",
    "best_attempt": "seed 4:2/10",     # failed 2/10 in a serial --det run with seed 4
    "pass_fail_reason": "random",
    "det_exception": "", "baseline_exception": "AssertionError", "det_exception_message": "",
    "_xdist": True, "_never_under_det": True,
}


def test_order_dependent_fixed_dir_test_is_not_cross_process():
    cls, why = af.classify(ROW, SRC)
    assert cls == "c", (cls, why)
