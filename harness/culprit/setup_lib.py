#!/usr/bin/env python3
"""Create one virtualenv per library at its current checkout (fixed environment for the planted-regression cases).

    setup_lib.py REPO_DIR VENV_DIR WHEEL
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from detpy_harness import detect_install  # noqa: E402


def main():
    src, venv, wheel = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    py = venv / "bin" / "python"
    if not py.exists():
        subprocess.run(["uv", "venv", "-q", "--python", "3.13", str(venv)], check=True)
    args, groups, reqs = detect_install(src)
    cmd = ["uv", "pip", "install", "-q", "--python", str(py), *args, *groups, *reqs, "pytest", wheel]
    p = subprocess.run(cmd, cwd=src, capture_output=True, text=True)
    print(" ".join(cmd[5:]), "->", p.returncode, p.stderr[-800:])
    return p.returncode


if __name__ == "__main__":
    sys.exit(main())
