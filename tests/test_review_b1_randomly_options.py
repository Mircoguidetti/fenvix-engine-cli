"""B1: next failure after the fix of item 1 (blocked plugin's options registered in the child)."""
import sys


def _install_fake_randomly(pytester):
    pytester.makepyfile(
        fake_randomly="""
        def pytest_addoption(parser):
            parser.addoption("--randomly-dont-reorganize", action="store_true", default=False)
            parser.addoption("--randomly-seed", default="default")
        """,
    )
    dist = pytester.path / "fake_randomly-1.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: fake-randomly\nVersion: 1.0\n")
    (dist / "entry_points.txt").write_text("[pytest11]\nrandomly = fake_randomly\n")


def test_user_also_passes_no_randomly(pytester, run_det):
    """addopts names a randomly option AND the user passes -p no:randomly: --det must behave like normal."""
    _install_fake_randomly(pytester)
    pytester.makeini("[pytest]\naddopts = --randomly-dont-reorganize\n")
    pytester.makepyfile(test_x="def test_x():\n    pass\n")
    normal = pytester.runpytest_subprocess("-p", "no:cacheprovider", "-p", "no:randomly")
    det, _ = run_det("-p", "no:randomly")
    print("normal ret", normal.ret, "det ret", det.ret)
    assert normal.ret == det.ret


def test_addopts_with_both_randomly_options_and_no_randomly(pytester, run_det):
    """addopts = -p no:randomly --randomly-seed=1 (project blocks it itself)."""
    _install_fake_randomly(pytester)
    pytester.makeini("[pytest]\naddopts = -p no:randomly --randomly-seed=1\n")
    pytester.makepyfile(test_x="def test_x():\n    pass\n")
    normal = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    det, _ = run_det()
    print("normal ret", normal.ret, "det ret", det.ret)
    assert normal.ret == det.ret


def test_nested_pytest_subprocess_does_not_inherit_blocked_options(pytester, run_det):
    """A project test that starts pytest in a subprocess with -p no:randomly and a randomly option.
    Normally that child rejects the option (usage error, exit 4). Under --det the re-exec env var
    DETPY_BLOCKED_PLUGINS leaks to the grandchild and detpy registers the options there."""
    _install_fake_randomly(pytester)
    pytester.makepyfile(test_inner="def test_inner():\n    pass\n")
    pytester.makepyfile(test_outer=f"""
        import subprocess, sys
        def test_outer():
            r = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:randomly", "-p", "no:cacheprovider",
                                "--randomly-seed=1", "test_inner.py"], capture_output=True, text=True)
            assert r.returncode == 4, (r.returncode, r.stdout[-300:], r.stderr[-300:])
        """)
    normal = pytester.runpytest_subprocess("-p", "no:cacheprovider", "test_outer.py")
    normal.assert_outcomes(passed=1)
    det, _ = run_det("test_outer.py")
    det.assert_outcomes(passed=1)
