#!/usr/bin/env python3
"""Install a library of the first study into a virtualenv, as the first study did (harness/cache_skip/run_repo.py:
project with its test extras / dependency groups / requirement files, falling back step by step), plus pytest.

    python3 libinstall.py --py /w/venv/bin/python --src /w/src [--extra trio ...]
"""

import argparse
import subprocess
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HARNESS))
from detpy_harness import detect_install  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--py", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--extra", action="append", default=[])
    a = ap.parse_args()
    src = Path(a.src)
    args, groups, reqs = detect_install(src)
    base = ["uv", "pip", "install", "--quiet", "--python", a.py]
    tools = ["pytest"]
    out = ""
    for attempt in (args + groups + reqs + a.extra, args + groups + a.extra, args + reqs + a.extra, args + a.extra,
                    ["-e", "."] + a.extra):
        p = subprocess.run(base + attempt + tools, cwd=src, capture_output=True, text=True, timeout=1500)
        out = p.stdout + p.stderr
        if p.returncode == 0:
            print("installed:", " ".join(attempt))
            return 0
    print(out[-2000:])
    return 1


if __name__ == "__main__":
    sys.exit(main())
