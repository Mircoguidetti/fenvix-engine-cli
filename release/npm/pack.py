#!/usr/bin/env python3
"""Assemble the npm packages from a checkout and the built addons.

    python3 release/npm/pack.py --addons DIR --out DIR [--pack]

DIR (--addons) holds `fenvix.<triple>.node` files, one per platform built by CI (.github/workflows/packages.yml).
Writes OUT/fenvix (the main package: shells, `fenvix` and `detjs` bins, an optionalDependency per platform) and
OUT/@fenvix/<triple> (one per addon found), each with its package.json; with --pack, also `npm pack` tarballs in
OUT/tarballs. Every package carries the version of Cargo.toml (release/version.py checks they agree).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "release"))
import version as _version  # noqa: E402

# triple -> (os, cpu, libc)
PLATFORMS = {
    "linux-x64-gnu": ("linux", "x64", "glibc"),
    "linux-arm64-gnu": ("linux", "arm64", "glibc"),
    "darwin-arm64": ("darwin", "arm64", None),
}
REPO = {"type": "git", "url": "git+https://github.com/Mircoguidetti/fenvix-engine-cli.git"}


def main_package(out: str, ver: str) -> str:
    src = os.path.join(ROOT, "node")
    dst = os.path.join(out, "fenvix")
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    for d in ("bin", "src"):
        shutil.copytree(os.path.join(src, d), os.path.join(dst, d))
    shutil.copy(os.path.join(src, "README.md"), dst)
    shutil.copy(os.path.join(ROOT, "LICENSE"), dst)
    dev = json.load(open(os.path.join(src, "package.json")))
    pkg = {
        "name": "fenvix",
        "version": ver,
        "description": "Deterministic CI test runs for Node: reproducible flaky tests, skip with proof (Vitest, Jest, Mocha, node:test, ...)",
        "license": dev.get("license", "MIT"),
        "repository": REPO,
        "homepage": "https://fenvix.dev",
        "keywords": ["test", "flaky", "deterministic", "vitest", "jest", "mocha", "ci", "cache"],
        "main": "src/index.js",
        "bin": {"fenvix": "bin/fenvix.js", "detjs": "bin/detjs.js"},
        "files": ["bin/", "src/", "README.md", "LICENSE"],
        "engines": {"node": ">=22"},
        "os": sorted({p[0] for p in PLATFORMS.values()}),
        "cpu": sorted({p[1] for p in PLATFORMS.values()}),
        "optionalDependencies": {f"@fenvix/{t}": ver for t in PLATFORMS},
    }
    json.dump(pkg, open(os.path.join(dst, "package.json"), "w"), indent=2)
    return dst


def platform_package(out: str, ver: str, triple: str, addon: str) -> str:
    osn, cpu, libc = PLATFORMS[triple]
    dst = os.path.join(out, "@fenvix", triple)
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    node = f"fenvix.{triple}.node"
    shutil.copy(addon, os.path.join(dst, node))
    shutil.copy(os.path.join(ROOT, "LICENSE"), dst)
    with open(os.path.join(dst, "README.md"), "w") as fh:
        fh.write(f"# @fenvix/{triple}\n\nThe native core of the npm package `fenvix` for {triple}. "
                 "Installed automatically as an optional dependency of `fenvix`; do not depend on it directly.\n")
    pkg = {
        "name": f"@fenvix/{triple}",
        "version": ver,
        "description": f"fenvix native core for {triple}",
        "license": "MIT",
        "repository": REPO,
        "main": node,
        "files": [node, "README.md", "LICENSE"],
        "os": [osn],
        "cpu": [cpu],
        "engines": {"node": ">=22"},
        "publishConfig": {"access": "public"},
    }
    if libc:
        pkg["libc"] = [libc]
    json.dump(pkg, open(os.path.join(dst, "package.json"), "w"), indent=2)
    return dst


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--addons", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pack", action="store_true")
    ap.add_argument("--require-all", action="store_true", help="fail unless every platform's addon is present")
    a = ap.parse_args(argv)
    ver = _version.read()["cargo"]
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    dirs = [main_package(out, ver)]
    missing = []
    for t in PLATFORMS:
        f = os.path.join(a.addons, f"fenvix.{t}.node")
        if os.path.exists(f):
            dirs.append(platform_package(out, ver, t, f))
        else:
            missing.append(t)
    if missing:
        print(f"pack: no addon for {', '.join(missing)}", file=sys.stderr)
        if a.require_all:
            return 1
    if a.pack:
        tb = os.path.join(out, "tarballs")
        os.makedirs(tb, exist_ok=True)
        for d in dirs:
            subprocess.run(["npm", "pack", "--pack-destination", tb], cwd=d, check=True, stdout=subprocess.DEVNULL)
        print("\n".join(sorted(os.listdir(tb))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
