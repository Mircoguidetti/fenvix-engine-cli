#!/usr/bin/env python3
"""Split test files into N CI shards, balanced by file size (deterministic greedy: largest file to the lightest shard).

usage: shard.py N K ROOT GLOB [GLOB...] [--only LABEL LIST-FILE]   -> prints the files of shard K (0-based), one per line

--only keeps, before the split, only the selected files labelled LABEL in LIST-FILE (release/python-tests.txt, read
by release/python_tests.py); a selected file LIST-FILE does not classify is an error. Without --only the output is
unchanged.
"""
import pathlib
import sys

args = sys.argv[1:]
only = None
if "--only" in args:
    i = args.index("--only")
    if len(args) < i + 3:
        sys.exit("shard.py: --only needs LABEL LIST-FILE")
    only, args = (args[i + 1], args[i + 2]), args[:i] + args[i + 3:]
n, k, root = int(args[0]), int(args[1]), pathlib.Path(args[2])
files = sorted({p for g in args[3:] for p in root.glob(g) if p.is_file()})
if only:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from python_tests import labels

    known = labels(only[1])
    missing = [str(p) for p in files if p.as_posix() not in known]
    if missing:
        sys.exit(f"shard.py: not classified in {only[1]}: {', '.join(missing)}")
    files = [p for p in files if known[p.as_posix()] == only[0]]
loads = [0] * n
owner = {}
for p in sorted(files, key=lambda p: (-p.stat().st_size, str(p))):
    i = min(range(n), key=lambda j: (loads[j], j))
    loads[i] += p.stat().st_size
    owner[p] = i
for p in files:
    if owner[p] == k:
        print(p)
