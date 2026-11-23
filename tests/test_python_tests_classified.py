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
