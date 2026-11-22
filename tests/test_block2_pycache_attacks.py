"""Block 2's own attacks on the rules it wrote (review R-056 W1/W2/W7/W10's fixes).

Each test changes one thing between two cached runs and checks the engine does not state something false. They
are in `tests/attacks.py` with the other attack files, so a later change cannot be made without running them.

The shape is R-056's: a cold cached run, one change, a warm cached run, and the verdict is uncached
``pytest --det`` under the same arguments -- never plain pytest, and never what the author expected.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the cache gates run on Linux")

VICTIM = "tests/b/test_b.py::test_victim"
INI = {"pytest.ini": "[pytest]\npythonpath = .\n"}
HELPER = {
    "helper.py": "STATE = {'mode': 'good'}\n\n\ndef poison(f=None):\n    STATE['mode'] = 'bad'\n    return f\n",
    "tests/a/test_a.py": "def test_a():\n    pass\n",
    "tests/b/test_b.py": "import helper\n\n\ndef test_victim():\n    assert helper.STATE['mode'] == 'good'\n",
    "tests/z/test_z.py": "def test_z():\n    pass\n",
}


def _write(root, files):
    for rel, text in files.items():
        p = root / rel
        if text is None:
            p.unlink(missing_ok=True)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def _run(root, *args):
    e = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "DETPY_CACHE_IN_PROCESS")}
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", "-p", "no:randomly",
                        *args, "tests"], cwd=root, capture_output=True, text=True, env=e, timeout=600)
    out = {}
    for line in p.stdout.splitlines():
        if line.startswith(("PASSED ", "FAILED ", "ERROR ")):
            out[line.split()[1]] = line.split()[0].lower()
    return p, out


def _reused(stdout: str) -> int:
    for line in stdout.splitlines():
        if line.startswith("reused ") and "result(s) with proof" in line:
            return int(line.split()[1])
    return -1


def test_a_later_file_that_binds_the_name_pytest_to_something_else_is_not_waved_through(tmp_path):
    """The one exception in `_applied_is_benign` says a `pytest.*` decorator defines and does not act. A module
    that binds that name to something else must not inherit the exception: `import helper as pytest` and then
    `@pytest.poison` runs the poison at import, in every worker, before the victim."""
    cache = f"--det-cache={tmp_path / '.c'}"
    _write(tmp_path, {**INI, **HELPER})
    _, o1 = _run(tmp_path, "--det", cache, "-n", "2")
    assert o1.get(VICTIM) == "passed", o1
    _write(tmp_path, {"tests/z/test_z.py": "import helper as pytest\n\n\n@pytest.poison\ndef test_z():\n    pass\n"})
    det, do = _run(tmp_path, "--det", "-n", "2")
    assert det.returncode == 1 and do.get(VICTIM) == "failed", det.stdout[-1500:]
    p, o = _run(tmp_path, "--det", cache, "-n", "2")
    assert p.returncode == 1 and o.get(VICTIM) == "failed", (
        f"--det-cache reports {o} (exit {p.returncode}); uncached --det fails {VICTIM}:\n{p.stdout[-2000:]}")


def test_editing_one_test_body_makes_only_that_file_stale_by_code(tmp_path):
    """The reuse side of the same rule, so a later change cannot buy safety by digesting everything again.

    A `def`'s BODY is not import-time code, so editing one test's body must leave every other file's code
    prefix valid: exactly ONE test is refused for `code:`. The others are still refused today, for `placement:`
    -- the needs rule reruns a process's earlier tests while `Entry::needs` is unknown (P-061,
    `FINDING-precise-reuse.md`). That is a different rule, in a different block, and this test says so instead
    of asserting a reuse the engine does not give yet: it asserts what THIS block fixed, and it will keep
    holding when P-061 lands.
    """
    import json as _json

    cache = f"--det-cache={tmp_path / '.c'}"
    files = {**INI}
    for i in range(1, 6):
        files[f"tests/test_{i}.py"] = f"import json\n\n\ndef test_{i}():\n    assert json.dumps({{'a': {i}}})\n"
    _write(tmp_path, files)
    _run(tmp_path, "--det", cache)
    p, _ = _run(tmp_path, "--det", cache)
    assert _reused(p.stdout) == 5, p.stdout[-1500:]
    _write(tmp_path, {"tests/test_3.py": "import json\n\n\ndef test_3():\n    assert json.dumps({'a': 33})\n"})
    p, o = _run(tmp_path, "--det", cache)
    assert all(v == "passed" for v in o.values()), o
    whys = {}
    with open(tmp_path / ".c" / "receipts.jsonl") as fh:
        for line in fh:
            r = _json.loads(line)
            if r.get("why"):
                whys[r["nodeid"]] = r["why"]
    by_code = sorted(n for n, w in whys.items() if w.startswith("code"))
    # The code prefix is cumulative in collection order, so the files AT OR AFTER the edited one are refused:
    # an edit to test_3 changes what ran before test_4 and test_5. The files BEFORE it keep their code prefix,
    # and that is what this test locks in: while closing W2 this block briefly digested every collected file's
    # whole content, which was sound and made ALL of them stale on any edit (MEASURED: "code 6" where the base
    # says "code 1" when the last file is edited). That version was removed before it shipped, and this test is
    # what stops it coming back by accident.
    assert "tests/test_1.py::test_1" not in by_code and "tests/test_2.py::test_2" not in by_code, (
        f"test_3's body changed and a file BEFORE it was refused for its code: {by_code}\n{whys}")
    assert "tests/test_3.py::test_3" in by_code, (f"the edited file must be refused: {by_code}")
