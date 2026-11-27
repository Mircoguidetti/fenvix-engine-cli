#!/usr/bin/env python3
"""Workflow entry point: run one request file by its "kind" (probe | collect | oracle | screen_r2 | collect_r2 |
oracle_r2)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main(argv: list[str]) -> int:
    req = json.loads(Path(argv[1]).read_text())
    kind = req.get("kind")
    if kind == "probe":
        import probe
        return probe.main(argv)
    if kind in ("screen_r2", "collect_r2", "oracle_r2"):
        import r2
        return r2.main(argv)
    if kind in ("collect", "oracle"):
        import collect
        return collect.main(argv)
    print(f"unknown request kind: {kind!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
