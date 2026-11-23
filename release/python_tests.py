"""Labels of the Python test files (release/python-tests.txt): `shared` (Node relies on the code they exercise) or
`python-product` (the Python product only). Used by release/shard.py --only, by the shard-0 extra steps of
.github/workflows/release-1.yml (`select`) and by tests/test_python_tests_classified.py.

usage: python_tests.py select LABEL LIST-FILE TARGET...   -> prints, space-separated, the TARGETs (a path, or
       path::test) whose file is labelled LABEL in LIST-FILE; nothing when none is.
"""
import sys

LABELS = ("shared", "python-product")


def parse(list_file):
    """[(line number, label, path)] of the non-comment lines, in file order; ValueError on a malformed line."""
    entries = []
    with open(list_file, encoding="utf-8") as f:
        for no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(f"{list_file}:{no}: expected '<label> <path>', got {line!r}")
            entries.append((no, parts[0], parts[1]))
    return entries


def labels(list_file):
    """{path: label}; ValueError on an unknown label or a path listed twice."""
    out = {}
    for no, label, path in parse(list_file):
        if label not in LABELS:
            raise ValueError(f"{list_file}:{no}: unknown label {label!r} (expected one of {', '.join(LABELS)})")
        if path in out:
            raise ValueError(f"{list_file}:{no}: {path} listed twice")
        out[path] = label
    return out


def main(argv):
    if len(argv) < 3 or argv[0] != "select":
        sys.exit(__doc__)
    label, known = argv[1], labels(argv[2])
    for t in argv[3:]:
        if t.split("::")[0] not in known:
            sys.exit(f"python_tests.py: {t} is not classified in {argv[2]}")
    print(" ".join(t for t in argv[3:] if known[t.split("::")[0]] == label))


if __name__ == "__main__":
    main(sys.argv[1:])
