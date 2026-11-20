#!/usr/bin/env bash
# Install release 1 into a runner image from a CI artifact `engine-<os>-<arch>` (.github/workflows/release-1.yml):
#   fenvix-*.whl           -> pip install into the image's Python (pytest plugin, python -m detpy, fenvix command)
#   node/ + addon          -> $FENVIX_HOME/node (detjs/fenvix shells; runtime dependencies only). The addon is the
#                             one of this machine: detjs.<platform>-<arch>.node or fenvix.<triple>.node (any OS/arch;
#                             audit G-0478, G-0496)
#   fenvix-go              -> $FENVIX_HOME/bin/fenvix-go (self-contained: overlay embedded, core linked statically)
#   fenvix-skip            -> $FENVIX_HOME/bin/fenvix-skip (JVM skip decider)
#   fenvix-agent.jar       -> $FENVIX_HOME/jvm/fenvix-agent.jar (agent, runtime, JNI core, Gradle init, Maven ext)
#   release/fenvix         -> $FENVIX_HOME/bin/fenvix (the single CLI entry; with the job's python3, and the engine
#                             from $FENVIX_HOME/python when that Python has none)
#   fenvix-*.whl (again)   -> $FENVIX_HOME/python (pip --target, no dependencies: the copy for jobs' own venvs)
# Toolchains (Python 3.12+, Node 22, Go 1.22+, JDK 8+, strace) are the image's, not installed here.
#
#   release/install-image.sh DIST_DIR [FENVIX_HOME]
set -euo pipefail
dist="$(cd "$1" && pwd)"
home="${2:-${FENVIX_HOME:-/opt/fenvix}}"
here="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$home/bin" "$home/jvm" "$home/node"
python3 -m pip install -q --no-deps "$dist"/fenvix-*.whl
# the image's copy for jobs that make their own virtual environment: $FENVIX_HOME/bin/fenvix puts it on their path
# (release/fenvix; R-050 D3, G-0413)
rm -rf "$home/python"
python3 -m pip install -q --no-deps --target "$home/python" "$dist"/fenvix-*.whl
python3 -m pip install -q "pytest>=8"
cp -r "$here/node/bin" "$here/node/src" "$here/node/package.json" "$here/node/package-lock.json" "$home/node/"
plat="$(node -p 'process.platform + "-" + process.arch')"
triple="$(node -p 'require(process.argv[1]).platformTriple().triple' "$here/node/src/platform.js")"
if [ -f "$dist/detjs.$plat.node" ]; then cp "$dist/detjs.$plat.node" "$home/node/"
elif [ -f "$dist/fenvix.$triple.node" ]; then cp "$dist/fenvix.$triple.node" "$home/node/detjs.$plat.node"
else echo "install-image: no Node addon for $plat ($triple) in $dist" >&2; exit 1; fi
(cd "$home/node" && npm ci --omit=dev --no-audit --no-fund --silent)
# Go and the JVM are outside the go-live scope: installed only when the artifact has them
for f in fenvix-go fenvix-skip; do if [ -f "$dist/$f" ]; then install -m 755 "$dist/$f" "$home/bin/"; fi; done
if [ -f "$dist/fenvix-agent.jar" ]; then install -m 644 "$dist/fenvix-agent.jar" "$home/jvm/"; fi
install -m 755 "$here/release/fenvix" "$home/bin/fenvix"
echo "installed release 1 into $home"
FENVIX_HOME="$home" "$home/bin/fenvix" version
