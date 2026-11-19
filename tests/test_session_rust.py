"""Round 2 of rust-hotpaths: the pure parts of the cache session (``_core.CacheSession``) and of the plugin's
outcome recorder (``_core.det_outcome``) against the Python they replace. Whole sessions are compared in
``test_capture_rust.py``."""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "rust_hotpaths_ref"))

from _ref_pc_helpers import _m as ref  # noqa: E402  (the round-2 Python proofcache module)
from _ref_plugin_helpers import _final_outcome  # noqa: E402

from detpy import _core  # noqa: E402

PHASES = [None, "passed", "failed", "skipped", "xfailed", "xpassed", "error", ""]


def test_det_outcome_matches_python():
    for s, c, t in itertools.product(PHASES, repeat=3):
        parts = {k: v for k, v in (("setup", s), ("call", c), ("teardown", t)) if v is not None}
        assert _core.det_outcome(s, c, t) == _final_outcome(parts), (s, c, t)


def test_final_of_matches_python():
    infos = [None, {"outcome": "passed"}, {"outcome": "failed"}, {"outcome": "skipped"},
             {"outcome": "skipped", "wasxfail": ""}, {"outcome": "passed", "wasxfail": "r"}, {"outcome": "failed", "wasxfail": "r"}]
    n = 0
    for s, c, t in itertools.product(infos, repeat=3):
        parts = {k: v for k, v in (("setup", s), ("call", c), ("teardown", t)) if v is not None}
        assert _core.CacheSession.final_of(parts) == ref._final(parts), parts
        n += 1
    assert n == 343


def test_ctx_label_matches_python():
    names = ["", "s", "i", "i|pkg/mod.py", "c|tests/test_x.py", "f|session|tests|db", "f|module||fx",
             "t|tests/test_x.py::test_a", "x", "f|", "c|", "i|", "t", "|", "f|a|b|c|d", "c|t\udcff.py", "i|é"]
    for n in names:
        assert _core.CacheSession.ctx_label_of(n) == ref._ctx_label(n), n
