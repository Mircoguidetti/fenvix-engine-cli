#!/usr/bin/env python3
"""Split test files into N CI shards, balanced by file size (deterministic greedy: largest file to the lightest shard).

usage: shard.py N K ROOT GLOB [GLOB...]   -> prints the files of shard K (0-based), one per line
"""
import pathlib
import sys

n, k, root = int(sys.argv[1]), int(sys.argv[2]), pathlib.Path(sys.argv[3])
files = sorted({p for g in sys.argv[4:] for p in root.glob(g) if p.is_file()})
loads = [0] * n
owner = {}
for p in sorted(files, key=lambda p: (-p.stat().st_size, str(p))):
    i = min(range(n), key=lambda j: (loads[j], j))
    loads[i] += p.stat().st_size
    owner[p] = i
for p in files:
    if owner[p] == k:
        print(p)
