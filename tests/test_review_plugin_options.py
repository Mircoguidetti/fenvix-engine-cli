"""R-001 review: failing tests on fenvix-engine-cli 0aef0ae (copy into tests/; uses tests/conftest.py).

Why it matters: since 1ad4e04 (-p no:randomly injected at the re-exec) a project that names a
pytest-randomly option in its configuration (addopts = --randomly-seed=..., --randomly-dont-reorganize,
--randomly-dont-reset-seed) cannot run under --det at all: usage error, zero tests run. Before
1ad4e04 the same project ran (plugin unregistered after loading). Verified with the real
pytest-randomly 4.0.1 in a scratch project: `pytest` passes, `pytest --det` exits with
"unrecognized arguments: --randomly-dont-reorganize". The harness cannot see it: its collection
check runs with -p no:randomly and falls back to -o addopts= (arrow and faker ran that way).
"""


def _install_fake_randomly(pytester):
    pytester.makepyfile(
        fake_randomly="""
        def pytest_addoption(parser):
            parser.addoption("--randomly-dont-reorganize", action="store_true", default=False)
        """,
    )
    dist = pytester.path / "fake_randomly-1.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: fake-randomly\nVersion: 1.0\n")
    (dist / "entry_points.txt").write_text("[pytest11]\nrandomly = fake_randomly\n")


def test_det_runs_a_project_that_configures_pytest_randomly(pytester, run_det):
    _install_fake_randomly(pytester)
    pytester.makeini("[pytest]\naddopts = --randomly-dont-reorganize\n")
    pytester.makepyfile(test_x="def test_x():\n    pass\n")
    normal = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    normal.assert_outcomes(passed=1)
    result, _ = run_det()
    # Fails on 0aef0ae: "error: unrecognized arguments: --randomly-dont-reorganize", no test runs.
    assert result.ret == 0, result.stderr.str()[-400:]
    result.assert_outcomes(passed=1)
