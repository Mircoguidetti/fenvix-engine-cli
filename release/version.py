#!/usr/bin/env python3
"""One version for every package: Cargo.toml [workspace.package] version is the source.

    python3 release/version.py            check that every manifest carries it (exit 1 and the list otherwise)
    python3 release/version.py 0.2.0      set it everywhere (Cargo.toml, python/detpy/_version.py, node/package.json)

The PyPI wheel takes it from Cargo.toml (maturin, `dynamic = ["version"]`), the npm packages from
release/npm/pack.py, the git tag is `v<version>` (.github/workflows/release.yml refuses a tag that differs).
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARGO = os.path.join(ROOT, "Cargo.toml")
PYVER = os.path.join(ROOT, "python", "detpy", "_version.py")
NODE = os.path.join(ROOT, "node", "package.json")
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?$")


def _cargo_version(text: str) -> str:
    m = re.search(r'\[workspace\.package\][^\[]*?\nversion\s*=\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("version: no [workspace.package] version in Cargo.toml")
    return m.group(1)


def read() -> dict:
    py = re.search(r'__version__ = "([^"]+)"', open(PYVER).read())
    return {
        "cargo": _cargo_version(open(CARGO).read()),
        "python": py.group(1) if py else None,
        "node": json.load(open(NODE)).get("version"),
    }


def write(v: str) -> None:
    if not SEMVER.match(v):
        raise SystemExit(f"version: {v!r} is not MAJOR.MINOR.PATCH[-PRE]")
    t = open(CARGO).read()
    t = re.sub(r'(\[workspace\.package\][^\[]*?\nversion\s*=\s*")[^"]+(")', rf"\g<1>{v}\g<2>", t, count=1)
    open(CARGO, "w").write(t)
    open(PYVER, "w").write("# Written by release/version.py from Cargo.toml [workspace.package] version; do not edit by hand.\n"
                           f'__version__ = "{v}"\n')
    pkg = json.load(open(NODE))
    pkg["version"] = v
    open(NODE, "w").write(json.dumps(pkg, indent=2) + "\n")


def main(argv) -> int:
    if argv:
        write(argv[0])
    vs = read()
    if len(set(vs.values())) != 1:
        print("version mismatch: " + ", ".join(f"{k}={v}" for k, v in vs.items()))
        return 1
    print(vs["cargo"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
