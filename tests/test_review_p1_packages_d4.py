"""Review R-050 D4 (PY-01), copied verbatim from claude/review-p1-packages@0119874:tests/test_review_p1_packages.py
(the D4 test and its helper; D1-D3 are other sessions' findings). Fails on f84dde7.

D4 (PY-01, every version): two `pytest --det` runs of one unchanged checkout are reported divergent by
    `fenvix verify` (every test, reason "config": input `bytecode` "...rewritten from source in this run (cold rewrite
    cache: N)" vs "precompiled") whenever the tests import a library shipped by a pytest-plugin distribution
    (hypothesis): pytest rewrites that library's modules, the pre-warm (G-0168) covers only the project's own files,
    so the first run in a fresh environment is always "cold".
"""

from __future__ import annotations

import os
import subprocess
import sys


def _plugin_distribution(site):
    """A pytest-plugin distribution (like hypothesis): an entry-point plugin module plus a library the tests import;
    pytest marks every module of such a distribution for assertion rewrite."""
    (site / "fakeplug_lib").mkdir(parents=True)
    (site / "fakeplug_plugin.py").write_text("")
    (site / "fakeplug_lib" / "__init__.py").write_text("from .core import value\n")
    (site / "fakeplug_lib" / "core.py").write_text("def value():\n    return 42\n")
    di = site / "fakeplug-1.0.dist-info"
    di.mkdir()
    (di / "METADATA").write_text("Metadata-Version: 2.1\nName: fakeplug\nVersion: 1.0\n")
    (di / "entry_points.txt").write_text("[pytest11]\nfakeplug = fakeplug_plugin\n")
    (di / "RECORD").write_text("fakeplug_plugin.py,,\nfakeplug_lib/__init__.py,,\nfakeplug_lib/core.py,,\n"
                               "fakeplug-1.0.dist-info/METADATA,,\nfakeplug-1.0.dist-info/RECORD,,\n")


def test_d4_two_det_runs_of_an_unchanged_checkout_verify_identical_with_a_plugin_library(tmp_path):
    """D4: `pytest --det` twice on an unchanged checkout whose tests import a pytest-plugin distribution's library,
    then `fenvix verify`: exit 0, nothing divergent (the DET2 family of the exam)."""
    site = tmp_path / "site"
    _plugin_distribution(site)
    proj = tmp_path / "proj"
    (proj / "tests").mkdir(parents=True)
    (proj / "tests" / "test_a.py").write_text("import fakeplug_lib\n\n\ndef test_a():\n    assert fakeplug_lib.value() == 42\n")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS",)}
    env["PYTHONPATH"] = str(site)
    traces = []
    for i in (1, 2):
        t = tmp_path / f"t{i}.jsonl"
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--det", f"--det-trace={t}",
                            "tests"], cwd=proj, capture_output=True, text=True, env=env, timeout=600)
        assert r.returncode == 0 and "1 passed" in r.stdout, r.stdout[-1500:] + r.stderr[-1500:]
        traces.append(str(t))
    v = subprocess.run([sys.executable, "-m", "detpy.fenvix", "verify", *traces], capture_output=True, text=True,
                       env=env, timeout=300)
    assert v.returncode == 0, f"two --det runs of an unchanged checkout verified divergent:\n{v.stdout[-1500:]}"
