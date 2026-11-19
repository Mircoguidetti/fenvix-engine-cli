"""Review R-017 of claude/rust-hotpaths-2 (round 2: everything that is not interface moved to Rust).

Failing tests, one per finding (sessions/2026-11-19-review-rust-r2/REPORT.md).

H1  pytest's rewritten test modules are now kept in the deterministic bytecode cache (264b183). pytest validates
    such a pyc by the source hash and pytest's version only, but the rewrite also depends on the
    ``enable_assertion_pass_hook`` ini option. Before round 2, ``--det`` never wrote these pycs, so every run
    rewrote with its own configuration; now a run behaves according to the configuration of whichever earlier run
    wrote the pyc. ``--det`` output depends on history, and a ``--det-cache`` session whose configuration changed
    re-runs every test (the configuration digest changed) and records results produced by the other
    configuration's code.
H2  REPORT-R2 finding 2 says the deterministic temporary names "run out" only locally: "Fresh CI runners never
    see it". The final CI profile p8 (the source of the headline table) shows it on pygments: from the second or
    third round on, every ``--det`` engine fails 2 tests (outcome failures) while plain pytest passes, and the
    pygments medians of the table include those runs.
H3  (pre-existing, inherited from the Python reference) an environment variable whose name is not valid UTF-8 is
    dropped from a test's inputs: its result is reused after the value changes.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

PASS_HOOK_CONFTEST = """
import os

def pytest_assertion_pass(item, lineno, orig, expl):
    with open(os.path.join(os.path.dirname(__file__), "passhook.log"), "a") as fh:
        fh.write(item.nodeid + "\\n")
"""


def _hook_calls(pytester) -> int:
    log = pytester.path / "passhook.log"
    n = len(log.read_text().splitlines()) if log.exists() else 0
    if log.exists():
        log.unlink()
    return n


@pytest.mark.skipif(sys.version_info < (3, 12), reason="--det bytecode controls")
def test_h1_rewritten_pyc_ignores_assertion_pass_hook_option(pytester):
    """The same command (same sources, same options) must behave the same whatever ran before it. A first --det
    run without ``enable_assertion_pass_hook`` leaves a rewritten pyc without the pass-hook calls; the next --det
    run with the option loads it (its source hash matches) and the hook is never called. With an empty
    bytecode cache, or with DETPY_REWRITE_CACHE=0 (the round-2 start), the hook is called once."""
    pytester.makeconftest(PASS_HOOK_CONFTEST)
    pytester.makepyfile(test_a="def test_x():\n    assert 1 == 1\n")
    on = ("-o", "enable_assertion_pass_hook=true")

    # (the reference, the option's own behaviour on an empty bytecode cache, is one call: see the report)
    pytester.runpytest_subprocess("--det", "-p", "no:cacheprovider").assert_outcomes(passed=1)
    _hook_calls(pytester)
    r = pytester.runpytest_subprocess("--det", "-p", "no:cacheprovider", *on)
    r.assert_outcomes(passed=1)
    assert _hook_calls(pytester) == 1, (
        "--det -o enable_assertion_pass_hook=true ran rewritten code written by an earlier run without the option")


@pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
def test_h1_cache_records_result_of_other_configuration(pytester):
    """With --det-cache: the configuration change makes every result a miss (the configuration digest is part
    of the key), the test is re-run and its new result is recorded under the new configuration, yet it was
    produced by the code rewritten for the previous one (the hook-dependent test below fails, and that failure is
    what this configuration's run reports)."""
    pytester.makeconftest(PASS_HOOK_CONFTEST)
    pytester.makepyfile(test_a="""
        import os

        def test_1_assert():
            assert 1 == 1

        def test_2_hook_saw_it():
            log = os.path.join(os.path.dirname(__file__), "passhook.log")
            on = os.environ.get("R017_HOOK") == "1"
            assert os.path.exists(log) == on
        """)
    cache = pytester.path.parent / f"{pytester.path.name}-cache"
    pytester.runpytest_subprocess("--det", "-p", "no:cacheprovider", f"--det-cache={cache}").assert_outcomes(passed=2)
    os.environ["R017_HOOK"] = "1"
    try:
        r = pytester.runpytest_subprocess("--det", "-p", "no:cacheprovider", f"--det-cache={cache}",
                                          "-o", "enable_assertion_pass_hook=true")
    finally:
        del os.environ["R017_HOOK"]
        _hook_calls(pytester)
    r.assert_outcomes(passed=2)


# ---------------------------------------------------------------------------------------------------------------
P8 = ROOT / "tracks" / "rust-hotpaths" / "results" / "p8" / "pygments-0of1.json"
REPORT = ROOT / "sessions" / "2026-11-18-rust-hotpaths" / "REPORT-R2.md"


def test_h2_report_says_ci_never_sees_tmp_name_exhaustion_but_p8_does():
    d = json.loads(P8.read_text())
    plain_ok = all(x["exit"] == 0 for x in d["cache"]["P0"])
    failing = {k: [i for i, x in enumerate(v) if x["exit"] != 0 and (x.get("cache") or {}).get("not_cached", {})
                   .get("outcome")] for k, v in d["cache"].items() if k != "P0"}
    failing = {k: v for k, v in failing.items() if v}
    assert plain_ok and failing, "precondition: p8 pygments --det runs fail tests where plain pytest passes"
    # the cold-run medians of the headline table include runs with 2 failing tests
    w = d["walls"]
    assert round(statistics.median(w["C:r2"]) / statistics.median(w["P0"]), 2) == 1.27
    text = REPORT.read_text()
    assert "Fresh CI runners never see it" not in text, (
        f"REPORT-R2 finding 2 says CI never sees the temporary-name exhaustion; p8 shows failing --det runs "
        f"(engine: rounds) {failing}")
    assert re.search(r"p8.{0,200}(fail|exit 1)", text, re.S), "the p8 pygments rows do not say runs failed"


# ---------------------------------------------------------------------------------------------------------------
@pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
def test_h3_env_var_with_undecodable_name_is_an_input(pytester):
    """H3 (pre-existing: the Python reference's ``_plan`` drops the same names, ``_encodable``; carried into
    ``CaptureCore.fill_plan``, which filters them out of ``plan.env``). A test that reads an environment variable
    whose name is not valid UTF-8 is recorded without that input: after the value changes, its old result is
    reused (passed) although the test now fails. Refusing the test (as for a non-UTF-8 path, "badpath") or keying
    the name's bytes would both be safe."""
    import subprocess

    pytester.makepyfile(test_e='import os\n\ndef test_e():\n    assert os.environb.get(b"R17\\xff") == b"1"\n')
    cache = pytester.path.parent / f"{pytester.path.name}-cache"
    out = pytester.path.parent / f"{pytester.path.name}-o.json"
    res = []
    for v in (b"1", b"2"):
        env = {os.fsencode(k): os.fsencode(x) for k, x in os.environ.items()}
        env[b"R17\xff"] = v
        subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--det",
                        f"--det-cache={cache}", f"--det-outcomes={out}"], cwd=pytester.path, env=env,
                       capture_output=True)
        res.append(json.loads(out.read_text())["outcomes"]["test_e.py::test_e"])
    assert res == ["passed", "failed"], res
