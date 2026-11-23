#!/usr/bin/env python3
"""Render pull requests for the hand check: handcheck_dump.py <selection.jsonl> <out.txt>

Each selection row needs "url". Prints the title, body excerpt, signals, the changed-file list and the diff of the
changed test/test-config files (as stored in count1_diffs.jsonl.gz).
"""
from __future__ import annotations

import sys
from pathlib import Path

from common import HERE, read_jsonl


def main() -> None:
    sel = read_jsonl(Path(sys.argv[1]))
    rows = {r["url"]: r for r in read_jsonl(HERE / "count1_rows.jsonl")}
    diffs = {r["url"]: r for r in read_jsonl(HERE / "count1_diffs.jsonl.gz")}
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 12000
    with open(sys.argv[2], "w") as out:
        for s in sel:
            r, d = rows[s["url"]], diffs[s["url"]]
            out.write("=" * 100 + "\n")
            out.write(f"{r['url']}  family={r['family']}  tier={r['tier']}  method={r['method']}\n")
            out.write(f"TITLE: {r['title']}\nBODY: {r['body_head'][:700]!r}\n")
            for sig in r["signals"]:
                out.write(f"SIGNAL {sig}\n")
            out.write("FILES: " + "; ".join(f"{e['status']} {e['path']}" for e in d["ns"][:60]) + "\n")
            p = d["patch"]
            out.write(p[:limit] + ("\n[... diff truncated ...]\n" if len(p) > limit else "\n"))


if __name__ == "__main__":
    main()
