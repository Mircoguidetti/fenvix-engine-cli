"""Review R-023 (speed): for pytest < 9.2 (timestamp rewritten pycs, review R-015), ``--det`` keeps the rewritten
test modules in detpy's own format, validated by a SHA-256 of (interpreter magic, source). Without it every ``--det``
session, and every worker of ``--det -n``, rewrote every test module (litellm, pydantic-ai, prefect: pytest 9.0-9.1).
``DETPY_REWRITE_OWN=1`` selects that format on any pytest, so these tests run here."""

import os
import subprocess
import sys
import textwrap

TEST = """
    def test_value():
        assert 1 + 1 == {VALUE}
    """


def _run(root, env, *extra):
    return subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--det", "-q", *extra],
                          cwd=root, env=env, capture_output=True, text=True, timeout=300)


def _own(prefix):
    out = []
    for r, _d, fs in os.walk(prefix):
        for f in fs:
            p = os.path.join(r, f)
            with open(p, "rb") as fh:
                if fh.read(8) == b"DETPYRW1":
                    out.append(p)
    return sorted(out)


def _env(tmp_path, **kw):
    env = {**os.environ, "DETPY_PYC_CACHE": str(tmp_path / "pyc"), "DETPY_REWRITE_OWN": "1", **kw}
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID"):
        env.pop(k, None)
    return env


def test_own_format_is_written_loaded_and_checked_by_content(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pytest.ini").write_text("[pytest]\n")
    src = root / "test_a.py"
    src.write_text(textwrap.dedent(TEST).replace("{VALUE}", "2"))
    env = _env(tmp_path)
    assert _run(root, env).returncode == 0
    files = [p for p in _own(tmp_path / "pyc") if os.path.basename(p).startswith("test_a.")]
    assert len(files) == 1, _own(tmp_path / "pyc")
    written = os.stat(files[0]).st_mtime_ns
    st = os.stat(src)
    assert _run(root, env).returncode == 0
    assert os.stat(files[0]).st_mtime_ns == written  # loaded, not rewritten
    # same size, same mtime, other content: the hash check rejects the cached code and the new code runs
    src.write_text(textwrap.dedent(TEST).replace("{VALUE}", "3"))
    os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns))
    r = _run(root, env)
    assert r.returncode == 1 and "assert (1 + 1) == 3" in r.stdout, r.stdout


def test_own_format_is_keyed_on_the_rewrite_configuration(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pytest.ini").write_text("[pytest]\n")
    (root / "conftest.py").write_text(
        "def pytest_assertion_pass(item, lineno, orig, expl):\n    print('PASSHOOK', item.nodeid)\n")
    (root / "test_a.py").write_text("def test_x():\n    assert 1 == 1\n")
    env = _env(tmp_path)
    on = ("-s", "-o", "enable_assertion_pass_hook=true")
    calls = lambda r: r.stdout.count("PASSHOOK")  # noqa: E731
    assert calls(_run(root, env, *on)) == 1
    assert calls(_run(root, env, "-s")) == 0
    assert calls(_run(root, env, *on)) == 1
    names = {os.path.basename(p) for p in _own(tmp_path / "pyc") if os.path.basename(p).startswith("test_a.")}
    assert len(names) == 2 and all(".det-" in n for n in names), names


def test_a_corrupt_own_pyc_is_rewritten(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pytest.ini").write_text("[pytest]\n")
    (root / "test_a.py").write_text(textwrap.dedent(TEST).replace("{VALUE}", "2"))
    env = _env(tmp_path)
    assert _run(root, env).returncode == 0
    f = [p for p in _own(tmp_path / "pyc") if os.path.basename(p).startswith("test_a.")][0]
    with open(f, "r+b") as fh:
        fh.seek(40)
        fh.write(b"\x00garbage")
    assert _run(root, env).returncode == 0  # unreadable code: rewritten again, the test runs
