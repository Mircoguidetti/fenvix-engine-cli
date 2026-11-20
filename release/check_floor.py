#!/usr/bin/env python3
"""The platform floor of built native files: no symbol newer than glibc 2.28 (manylinux_2_28) on Linux, no
deployment target newer than macOS 11 on macOS (audit G-0479, G-0481, G-0488, G-0489, G-0446 family).

    python3 release/check_floor.py FILE...      (.whl: its native modules; .node / .so / .dylib: the file itself)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import zipfile

GLIBC_MAX = (2, 28)
MACOS_MAX = (11, 0)


def natives(path: str, tmp: str) -> list[str]:
    if path.endswith(".whl"):
        out = []
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.endswith((".so", ".dylib")):
                    out.append(z.extract(n, tmp))
        return out
    return [path]


def check(f: str) -> tuple[bool, str]:
    head = open(f, "rb").read(4)
    if head == b"\x7fELF":
        syms = subprocess.run(["objdump", "-T", f], capture_output=True, text=True, check=True).stdout
        vers = sorted({tuple(map(int, v.split("."))) for v in re.findall(r"GLIBC_(\d+(?:\.\d+)+)", syms)})
        top = vers[-1] if vers else (0,)
        return top <= GLIBC_MAX, f"GLIBC_{'.'.join(map(str, top))} (max {'.'.join(map(str, GLIBC_MAX))})"
    out = subprocess.run(["otool", "-l", f], capture_output=True, text=True, check=True).stdout
    m = re.search(r"minos (\d+)\.(\d+)", out) or re.search(r"LC_VERSION_MIN_MACOSX.*?version (\d+)\.(\d+)", out, re.S)
    if not m:
        return False, "no deployment target found"
    v = (int(m.group(1)), int(m.group(2)))
    return v <= MACOS_MAX, f"macOS minos {v[0]}.{v[1]} (max {MACOS_MAX[0]}.{MACOS_MAX[1]})"


def main(argv) -> int:
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        for p in argv:
            for f in natives(p, tmp):
                ok, why = check(f)
                print(f"{'ok ' if ok else 'BAD'} {os.path.basename(p)}:{os.path.basename(f)} {why}")
                bad += not ok
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
