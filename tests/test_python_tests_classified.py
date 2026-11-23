"""release/python-tests.txt classifies every Python test file the CI gate selects (release-1.yml LIGHT runs only the
`shared` ones until 2026-12-22): each selected file exactly once, every listed path exists, labels are `shared` or
`python-product`. The selected files come from release/shard.py itself (all 4 shards, no --only), never a copy of
its globs."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIST = ROOT / "release" / "python-tests.txt"
WORKFLOW = ROOT / ".github" / "workflows" / "release-1.yml"
LABELS = {"shared", "python-product"}


def selected():
    """The files the gate's main Python step selects: the shard.py command of release-1.yml, every shard."""
    cmd = re.search(r"release/shard\.py 4 \$\{\{ matrix\.shard \}\} (tests(?: '[^']+')+)", WORKFLOW.read_text())
    assert cmd, "the shard.py command of the python job was not found in release-1.yml"
    root, *globs = [a.strip("'") for a in cmd.group(1).split()]
    files = []
    for k in range(4):
        out = subprocess.run([sys.executable, str(ROOT / "release" / "shard.py"), "4", str(k), root, *globs],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout
        files += out.split()
    assert files, "shard.py selected no file"
    return files


def entries():
    out = []
    for no, line in enumerate(LIST.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if line and not line.startswith("#"):
            out.append((no, line.split()))
    return out


def test_every_line_is_a_known_label_and_a_path():
    bad = [(no, parts) for no, parts in entries() if len(parts) != 2 or parts[0] not in LABELS]
    assert not bad, f"lines that are not '<shared|python-product> <path>': {bad}"


def test_no_path_listed_twice():
    seen, twice = set(), []
    for _, parts in entries():
        if parts[-1] in seen:
            twice.append(parts[-1])
        seen.add(parts[-1])
    assert not twice, f"listed more than once: {twice}"


def test_every_listed_path_exists():
    gone = [parts[-1] for _, parts in entries() if not (ROOT / parts[-1]).is_file()]
    assert not gone, f"listed but not in the tree: {gone}"


def test_every_selected_file_is_classified():
    listed = {parts[-1] for _, parts in entries()}
    missing = sorted(set(selected()) - listed)
    assert not missing, f"selected by release/shard.py but not in release/python-tests.txt: {missing}"


def test_the_list_parses_with_the_parser_ci_uses_and_lists_only_selected_files():
    sys.path.insert(0, str(ROOT / "release"))
    try:
        from python_tests import labels
    finally:
        sys.path.pop(0)
    listed = labels(LIST)  # raises on an unknown label or a duplicate, as shard.py --only does in CI
    stale = sorted(set(listed) - set(selected()))
    assert not stale, f"listed but not selected by release/shard.py (never run): {stale}"


def test_light_and_full_are_the_matrix_expression():
    """env.FULL of the python job is the expression that picks several Python versions (FULL) or one (LIGHT)."""
    text = WORKFLOW.read_text()
    full = re.search(r"\n      FULL: \$\{\{ (.+) \}\}\n", text)
    matrix = re.search(r"python: \$\{\{ fromJSON\(\((.+)\) && '\[\"3\.12\"", text)
    assert full and matrix and full.group(1) == matrix.group(1), (full and full.group(1), matrix and matrix.group(1))


def _run(tmp_path, *args):
    return subprocess.run([sys.executable, *args], cwd=tmp_path, capture_output=True, text=True)


def test_shard_only_keeps_the_label_and_refuses_bad_input(tmp_path):
    shard = str(ROOT / "release" / "shard.py")
    (tmp_path / "t").mkdir()
    for name, size in (("test_a.py", 30), ("test_b.py", 20), ("test_c.py", 10)):
        (tmp_path / "t" / name).write_text("#" * size)
    lst = tmp_path / "l.txt"
    lst.write_text("# comment\nshared t/test_a.py\npython-product t/test_b.py\nshared t/test_c.py\n")
    picked = [_run(tmp_path, shard, "2", str(k), "t", "test_*.py", "--only", "shared", str(lst)).stdout.split()
              for k in (0, 1)]
    assert sorted(picked[0] + picked[1]) == ["t/test_a.py", "t/test_c.py"]
    assert _run(tmp_path, shard, "1", "0", "t", "test_*.py").stdout.split() == ["t/test_a.py", "t/test_b.py", "t/test_c.py"]
    for bad_args, bad_list in ((("sharedd",), None), (("shared",), "shared t/test_a.py\n"),
                               (("shared",), "python-product t/test_a.py\npython-product t/test_b.py\n"
                                             "python-product t/test_c.py\n"), ((), None)):
        if bad_list is not None:
            lst.write_text(bad_list)
        r = _run(tmp_path, shard, "1", "0", "t", "test_*.py", "--only", *bad_args, *((str(lst),) if bad_args else ()))
        assert r.returncode != 0 and not r.stdout, (bad_args, bad_list, r)


def test_select_keeps_targets_whose_file_has_the_label(tmp_path):
    tool = str(ROOT / "release" / "python_tests.py")
    lst = tmp_path / "l.txt"
    lst.write_text("shared t/test_a.py\npython-product t/test_b.py\n")
    r = _run(tmp_path, tool, "select", "shared", str(lst), "t/test_a.py::test_x", "t/test_b.py")
    assert r.returncode == 0 and r.stdout.split() == ["t/test_a.py::test_x"]
    r = _run(tmp_path, tool, "select", "shared", str(lst), "t/test_b.py")
    assert r.returncode == 0 and r.stdout.strip() == ""  # the workflow skips the step
    assert _run(tmp_path, tool, "select", "shared", str(lst), "t/test_z.py").returncode != 0
    assert _run(tmp_path, tool, "select", "sharedd", str(lst), "t/test_a.py").returncode != 0
