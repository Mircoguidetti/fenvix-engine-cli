"""Review R-023c (claude/parallel-proof-3 at 72b2c654, engine 21b57571, REPORT-3): adversarial tests of the rules
loosened in round 3 (temporary roots, the mtime caller exclusions, the F3 cdll scope), of F1's runtime-write
connectivity and the carried-set rule, of P4's shared store and of P5's parallel placement.

Each test asserts the contract: a test is skipped only when its reused result equals what a fresh run gives. A failing
test is a finding; a passing test is an attack that did not get through. Some tests change host paths (/var/tmp) and
restore them; they need root and skip otherwise."""

import contextlib
import json
import os
import pathlib
import shutil
import sys
import textwrap

import pytest

pytest.importorskip("xdist")
needs_cache = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
needs_root = pytest.mark.skipif(os.geteuid() != 0, reason="changes host files")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NS = [pytest.param(0, id="serial"), pytest.param(2, id="n2")]


def write(pytester, **files):
    for name, text in files.items():
        p = pytester.path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))


def cache_run(pytester, n, label, *args, store=".c"):
    out = pytester.path / f"out-{label}.json"
    extra = ["-n", str(n)] if n else []
    r = pytester.runpytest_subprocess(
        "--det", f"--det-cache={pytester.path / store}", f"--det-outcomes={out}",
        "-p", "no:cacheprovider", "-p", "no:randomly", *extra, *args)
    data = json.loads(out.read_text()) if out.exists() else {}
    return r, data.get("cache", {})


def fresh_run(pytester, n, *args):
    extra = ["-n", str(n)] if n else []
    return pytester.runpytest_subprocess("--det", "-p", "no:cacheprovider", "-p", "no:randomly", *extra, *args)


def reused(c):
    return set(c.get("reused_ids", ()))


def three_sessions(pytester, n, change, nid, *args, truth_outcomes, record_outcomes):
    """Record (two sessions), apply ``change``, then a fresh run (the truth) and a cache run. The cache run must give
    the truth's outcomes and must not reuse ``nid``."""
    for label in ("s1", "s2"):
        r, _ = cache_run(pytester, n, label, *args)
        r.assert_outcomes(**record_outcomes)
    change()
    fresh_run(pytester, n, *args).assert_outcomes(**truth_outcomes)
    r, c = cache_run(pytester, n, "s3", *args)
    assert nid not in reused(c), f"{nid} reused after its input changed"
    r.assert_outcomes(**truth_outcomes)


# =====================================================================================================================
# 1. Rules loosened this round
# =====================================================================================================================
@contextlib.contextmanager
def var_tmp_moved_on_change():
    """Yields a ``change`` that moves /var/tmp away; restores it."""
    bak = "/var/tmp.r023c-bak"
    moved = []

    def change():
        os.rename("/var/tmp", bak)
        moved.append(1)

    try:
        yield change
    finally:
        if moved:
            os.rename(bak, "/var/tmp")


@needs_cache
@needs_root
@pytest.mark.parametrize("n", NS)
def test_1a_kind_check_of_a_temporary_root_is_an_input(pytester, n):
    """capture.rs is_temp_root: a kind check of /tmp, /var/tmp or $TMPDIR records nothing. A test whose verdict is
    that kind (a tool that needs /var/tmp, a fallback when it is missing) is reused after the directory is gone."""
    if not os.path.isdir("/var/tmp"):
        pytest.skip("no /var/tmp here")
    write(pytester, **{"tests/test_vt.py": """
        import os
        def test_var_tmp_is_a_directory():
            assert os.path.isdir("/var/tmp")
        def test_other():
            pass
        """})
    with var_tmp_moved_on_change() as change:
        three_sessions(pytester, n, change, "tests/test_vt.py::test_var_tmp_is_a_directory", "tests",
                       truth_outcomes={"passed": 1, "failed": 1}, record_outcomes={"passed": 2})


MTIME_FILES = {
    "tests/data.txt": "same content\n",
    "tests/conftest.py": "",
}


def mtime_case(pytester, n, body):
    write(pytester, **MTIME_FILES)
    data = pytester.path / "tests" / "data.txt"
    os.utime(data, (1_000_000_000, 1_000_000_000))
    write(pytester, **{"tests/test_mt.py": body})

    def change():  # same bytes, same size: only the time moves (`touch -d`)
        os.utime(data, (1_500_000_000, 1_500_000_000))

    three_sessions(pytester, n, change, "tests/test_mt.py::test_reads_a_time", "tests",
                   truth_outcomes={"passed": 1, "failed": 1}, record_outcomes={"passed": 2})


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_1b_time_read_behind_a_standard_library_frame(pytester, n):
    """_user_stat_caller: an os.stat whose immediate caller is the standard library is never timed (tarfile,
    zipfile, filecmp, logging.handlers read st_mtime for their caller). The time reaches the test as a value."""
    mtime_case(pytester, n, """
        import io, os, tarfile
        HERE = os.path.dirname(__file__)
        def test_reads_a_time():
            tf = tarfile.open(fileobj=io.BytesIO(), mode="w")
            assert tf.gettarinfo(os.path.join(HERE, "data.txt")).mtime == 1_000_000_000
        def test_other():
            pass
        """)


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_1b_time_read_behind_an_infrastructure_frame(pytester, n):
    """The infrastructure exclusion: an os.stat whose first non-stdlib frame is pytest's is not timed. pytest's
    LocalPath (the legacy ``tmpdir``/``py.path`` type) gives user code the file's mtime."""
    mtime_case(pytester, n, """
        import os
        from _pytest._py.path import LocalPath
        HERE = os.path.dirname(__file__)
        def test_reads_a_time():
            assert LocalPath(os.path.join(HERE, "data.txt")).mtime() == 1_000_000_000
        def test_other():
            pass
        """)


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_1b_time_read_through_os_fstat(pytester, n):
    """os.fstat (and os.stat of a descriptor) are not wrapped: their st_mtime is an unflagged time read."""
    mtime_case(pytester, n, """
        import os
        HERE = os.path.dirname(__file__)
        def test_reads_a_time():
            with open(os.path.join(HERE, "data.txt"), "rb") as f:
                assert os.fstat(f.fileno()).st_mtime == 1_000_000_000
        def test_other():
            pass
        """)


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_1b_time_read_through_os_stat_of_a_descriptor(pytester, n):
    mtime_case(pytester, n, """
        import os
        HERE = os.path.dirname(__file__)
        def test_reads_a_time():
            with open(os.path.join(HERE, "data.txt"), "rb") as f:
                assert os.stat(f.fileno()).st_mtime == 1_000_000_000
        def test_other():
            pass
        """)


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_1c_libc_through_ctypes_pythonapi(pytester, n):
    """F3: CDLL(None) from repository code is flagged ``cdll``, but ``ctypes.pythonapi`` is the same handle
    (dlopen(NULL), the program's symbols, libc among them), loaded by the standard library at ``import ctypes``: never
    flagged. libc's access() then answers an existence check the capture does not see."""
    write(pytester, **{"tests/flag.txt": "x\n", "tests/test_c.py": """
        import ctypes, os
        access = ctypes.pythonapi.access
        access.argtypes = [ctypes.c_char_p, ctypes.c_int]
        access.restype = ctypes.c_int
        FLAG = os.path.join(os.path.dirname(__file__), "flag.txt").encode()
        def test_flag_present():
            assert access(FLAG, 0) == 0
        def test_other():
            pass
        """})
    three_sessions(pytester, n, lambda: (pytester.path / "tests" / "flag.txt").unlink(),
                   "tests/test_c.py::test_flag_present", "tests",
                   truth_outcomes={"passed": 1, "failed": 1}, record_outcomes={"passed": 2})


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_1d_permission_bits_are_an_input(pytester, n):
    """os.access / st_mode: an existence check is keyed by the kind, a stat by the size; the mode is in neither. A
    test that a script is executable is reused after ``chmod -x``."""
    write(pytester, **{"tests/run.sh": "#!/bin/sh\nexit 0\n", "tests/test_x.py": """
        import os
        P = os.path.join(os.path.dirname(__file__), "run.sh")
        def test_script_is_executable():
            assert os.access(P, os.X_OK)
        def test_other():
            pass
        """})
    os.chmod(pytester.path / "tests" / "run.sh", 0o755)
    three_sessions(pytester, n, lambda: os.chmod(pytester.path / "tests" / "run.sh", 0o644),
                   "tests/test_x.py::test_script_is_executable", "tests",
                   truth_outcomes={"passed": 1, "failed": 1}, record_outcomes={"passed": 2})
