#!/usr/bin/env python3
"""Install requirement files with uv, dropping requirements that fail to build (missing system libraries
on the runner). The tests of a dropped package fail at import at every commit and are reported as such.

    pyinstall.py --python VENV/bin/python -r requirements_all.txt -r requirements_test.txt
"""

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", required=True)
    ap.add_argument("-r", action="append", default=[])
    ap.add_argument("--max-drop", type=int, default=40)
    a = ap.parse_args()
    drop = set()
    for attempt in range(a.max_drop + 1):
        files = []
        for r in a.r:
            p = Path(r)
            lines = []
            for line in p.read_text().splitlines():
                name = re.split(r"[=<>!~\[; ]", line.strip(), 1)[0].lower().replace("_", "-")
                if name and name in drop:
                    continue
                if line.strip().startswith(("-c ", "-r ")):  # make relative includes absolute
                    flag, rest = line.strip().split(None, 1)
                    line = f"{flag} {(p.parent / rest).resolve()}"
                lines.append(line)
            t = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, dir=p.parent)
            t.write("\n".join(lines) + "\n")
            t.close()
            files.append(t.name)
        cmd = ["uv", "pip", "install", "--quiet", "--python", a.python]
        for f in files:
            cmd += ["-r", f]
        p = subprocess.run(cmd, capture_output=True, text=True)
        for f in files:
            Path(f).unlink(missing_ok=True)
        if p.returncode == 0:
            print(f"installed; dropped {sorted(drop)}")
            return 0
        err = p.stderr + p.stdout
        bad = set(re.findall(r"(?:Failed to build|Failed to download and build|Failed to download|"
                             r"Failed to prepare distributions|Failed to resolve)\s+`([A-Za-z0-9_.\-]+)", err))
        bad = {b.lower().replace("_", "-") for b in bad} - drop
        if not bad:
            print(err[-4000:], file=sys.stderr)
            return 1
        print(f"dropping {sorted(bad)}", flush=True)
        drop |= bad
    return 1


if __name__ == "__main__":
    sys.exit(main())
