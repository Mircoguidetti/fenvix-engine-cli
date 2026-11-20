#!/usr/bin/env bash
# Assemble the one engine artifact for our machines (Linux x86_64, manylinux_2_28 floor) from a CI build directory.
#
#   release/engine/assemble.sh DIST OUT
#
# DIST holds the manylinux_2_28 x86_64 wheel and detjs.linux-x64.node (release-1.yml, job build). Writes
# OUT/fenvix-engine-<version>-<build>-linux-x86_64.tar.gz and its .sha256 (the runner image pins both), reproducible:
# fixed order, owner and mtimes, gzip without a name or time. <version> is release/version.py; <build> is
# $ENGINE_BUILD (CI: r<run number>.<short commit>), "local" otherwise.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
dist="$(cd "$1" && pwd)"
out="$(mkdir -p "$2" && cd "$2" && pwd)"
ver="$(python3 "$root/release/version.py")"
build="${ENGINE_BUILD:-local}"
name="fenvix-engine-${ver}-${build}-linux-x86_64"
stage="$(mktemp -d)/$name"
mkdir -p "$stage/wheels" "$stage/node" "$stage/bin"
whl="$(ls "$dist"/fenvix-*-manylinux_2_28_x86_64.whl)"
cp "$whl" "$stage/wheels/"
cp -R "$root/node/bin" "$root/node/src" "$root/node/package.json" "$stage/node/"
cp "$dist/detjs.linux-x64.node" "$stage/node/"
install -m 755 "$root/release/fenvix" "$stage/bin/fenvix"
install -m 755 "$root/release/engine/install.sh" "$stage/install.sh"
cp "$root/LICENSE" "$root/CHANGELOG.md" "$stage/"
echo "$ver-$build" > "$stage/VERSION"
python3 - "$stage" "$ver" "$build" "${GITHUB_SHA:-$(git -C "$root" rev-parse HEAD)}" <<'PY'
import hashlib, json, os, sys
stage, ver, build, commit = sys.argv[1:]
files = {}
for d, _, fs in os.walk(stage):
    for f in fs:
        p = os.path.join(d, f)
        files[os.path.relpath(p, stage)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
json.dump({"version": ver, "build": build, "commit": commit, "platform": "linux-x86_64", "glibc_min": "2.28",
           "python": ["3.12", "3.13", "3.14"], "node": ["22", "24", "26"], "files": dict(sorted(files.items()))},
          open(os.path.join(stage, "VERSION.json"), "w"), indent=2, sort_keys=True)
PY
tarball="$out/$name.tar.gz"
tar -C "$(dirname "$stage")" --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -cf - "$name" | gzip -n -9 > "$tarball"
(cd "$out" && sha256sum "$name.tar.gz" > "$name.tar.gz.sha256")
echo "$tarball"
cat "$tarball.sha256"
