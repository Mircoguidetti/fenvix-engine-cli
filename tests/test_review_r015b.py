"""Review R-015b (claude/rust-hotpaths after the R-015 fixes): failing tests for the findings in
sessions/2026-11-18-review-rust-hotpaths/REPORT-2.md.

Each test records a result under code that did not produce it, then shows that a fresh ``--det`` run of the code on
disk fails while the ``--det-cache`` run hands back the recorded "passed".

G1: code run by a followed child process (a repository script, or a module the child imports with its own
    environment) is digested when the session ends, not when the child read it: the F1 refusal does not cover it.
G2: a repository module that is a symlink is keyed on its target at the time of the session; pointing the link at
    another file (a branch switch) reuses the result of the old target's code.
G3: a doctest text file is read at collection, but its F1 stat key is taken only when its first example runs: an
    edit in between is recorded under the new content.
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


def _project(root, files: dict) -> None:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))


def _pytest(cwd, *args):
    # stdin: one byte for tests that wait for the edit (none here: they return at once)
    return subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-s", *args], cwd=cwd,
                          input="x", capture_output=True, text=True, timeout=300)


def _session_with_edit(root, cache, edit) -> None:
    """A ``--det --det-cache`` session whose test prints READY and waits on stdin; ``edit`` runs at READY (the
    developer saves a file, or switches branch, while the suite runs)."""
    p = subprocess.Popen([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-s", "--det",
                          f"--det-cache={cache}", f"--det-outcomes={root / 'o1.json'}"], cwd=root,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        for line in p.stdout:
            if "READY" in line:
                edit()
                p.stdin.write("x")
                p.stdin.flush()
        assert p.wait(timeout=300) == 0  # this session ran the old code: passed
    finally:
        p.kill()


def _reused(root, cache) -> list:
    out = root / "o2.json"
    _pytest(root, "--det", f"--det-cache={cache}", f"--det-outcomes={out}")
    return json.loads(out.read_text())["cache"].get("reused_ids", [])


WAIT = """
    import os

    def wait():
        print("READY", flush=True)
        os.read(0, 1)  # wait for the edit (stdin: no audit event, not an input)
    """


# ---------------------------------------------------------------------------
# G1: a child process's reads are turned into inputs at the end of the session (collect_children), so their digest
# is the content at the end, not the content the child ran
@pytest.mark.parametrize("how", ["script", "module"])
def test_G1_code_run_by_a_child_and_edited_during_the_session_is_not_reused(pytester, how):
    root = pytester.path
    if how == "script":
        # a CLI script of the repository, run as a program (its source is read by the interpreter, no bytecode)
        call = 'subprocess.run([sys.executable, "tool.py"], capture_output=True, text=True)'
    else:
        # a module imported by a child that gets its own environment (no detpy bytecode cache)
        call = ('subprocess.run([sys.executable, "-c", "import tool"], capture_output=True, text=True, '
                'env={"PATH": os.environ["PATH"], "PYTHONPATH": os.getcwd()})')
    _project(root, {
        "pytest.ini": "[pytest]\n",
        "w.py": WAIT,
        "tool.py": 'print("A")\n',
        "test_t.py": f"""
            import os, subprocess, sys
            from w import wait

            def test_tool():
                r = {call}
                wait()
                assert r.stdout == "A\\n"
            """,
    })
    cache = root / ".cachedir"
    # the size changes: the child's own timestamp pyc (module case) cannot stay valid
    _session_with_edit(root, cache, lambda: (root / "tool.py").write_text('print("BB")\n'))
    assert "1 failed" in _pytest(root, "--det").stdout  # the code on disk fails
    assert "test_t.py::test_tool" not in _reused(root, cache)


# ---------------------------------------------------------------------------
# G2: Capture._want keys code by os.path.realpath at the first sight of a filename: a module that is a symlink is
# recorded under its target, and the link itself is no input. git stores symlinks; a checkout that changes the
# target leaves the old target's units unchanged
def test_G2_symlinked_module_pointed_at_another_file_is_not_reused(pytester):
    root = pytester.path
    _project(root, {
        "pytest.ini": "[pytest]\n",
        "pkg/__init__.py": "",
        "pkg/impl_1.py": "VALUE = 1\n",
        "pkg/impl_2.py": "VALUE = 2\n",
        "test_m.py": """
            from pkg import mod

            def test_a():
                assert mod.VALUE == 1
            """,
    })
    os.symlink("impl_1.py", root / "pkg" / "mod.py")
    cache = root / ".cachedir"
    r = _pytest(root, "--det", f"--det-cache={cache}")
    assert "1 passed" in r.stdout, r.stdout
    # git checkout of a branch where pkg/mod.py -> impl_2.py
    os.unlink(root / "pkg" / "mod.py")
    os.symlink("impl_2.py", root / "pkg" / "mod.py")
    assert "1 failed" in _pytest(root, "--det").stdout
    assert "test_m.py::test_a" not in _reused(root, cache)


# ---------------------------------------------------------------------------
# G3: the F1 stat key is taken at the first open of a ``.py`` file or at the first module body run; a doctest text
# file is opened (parsed) at collection and its first example runs when its turn comes, possibly much later
def test_G3_doctest_text_file_edited_between_collection_and_its_run_is_not_reused(pytester):
    root = pytester.path
    _project(root, {
        "pytest.ini": "[pytest]\naddopts = --doctest-glob=*.txt\n",
        "w.py": WAIT,
        "test_wait.py": """
            from w import wait

            def test_wait():
                wait()
            """,
        "z_doc.txt": ">>> 1 + 1\n2\n",  # collected after test_wait.py, runs after it
    })
    cache = root / ".cachedir"
    _session_with_edit(root, cache, lambda: (root / "z_doc.txt").write_text(">>> 1 + 1\n3\n"))
    assert "1 failed" in _pytest(root, "--det").stdout
    assert "z_doc.txt::z_doc.txt" not in _reused(root, cache)
