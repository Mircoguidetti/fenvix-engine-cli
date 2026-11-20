#!/usr/bin/env bash
# Install release 1 into a runner image from the CI artifact `engine-linux-x64` (.github/workflows/release-1.yml):
#   detpy-*.whl            -> pip install into the image's Python (pytest plugin + python -m detpy)
#   node/ + addon          -> $FENVIX_HOME/node (detjs; runtime dependencies only)
#   fenvix-go              -> $FENVIX_HOME/bin/fenvix-go (self-contained: overlay embedded, core linked statically)
#   fenvix-skip            -> $FENVIX_HOME/bin/fenvix-skip (JVM skip decider)
#   fenvix-agent.jar       -> $FENVIX_HOME/jvm/fenvix-agent.jar (agent, runtime, JNI core, Gradle init, Maven ext)
#   release/fenvix         -> $FENVIX_HOME/bin/fenvix (the single CLI entry)
# Toolchains (Python 3.12+, Node 22, Go 1.22+, JDK 8+, strace) are the image's, not installed here.
#
#   release/install-image.sh DIST_DIR [FENVIX_HOME]
set -euo pipefail
dist="$(cd "$1" && pwd)"
home="${2:-${FENVIX_HOME:-/opt/fenvix}}"
here="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$home/bin" "$home/jvm" "$home/node"
python3 -m pip install -q --no-deps "$dist"/detpy-*.whl
python3 -m pip install -q "pytest>=7"
cp -r "$here/node/bin" "$here/node/src" "$here/node/package.json" "$here/node/package-lock.json" "$home/node/"
cp "$dist/detjs.linux-x64.node" "$home/node/"
(cd "$home/node" && npm ci --omit=dev --no-audit --no-fund --silent)
# Go and the JVM are outside the go-live scope: installed only when the artifact has them
for f in fenvix-go fenvix-skip; do if [ -f "$dist/$f" ]; then install -m 755 "$dist/$f" "$home/bin/"; fi; done
if [ -f "$dist/fenvix-agent.jar" ]; then install -m 644 "$dist/fenvix-agent.jar" "$home/jvm/"; fi
install -m 755 "$here/release/fenvix" "$home/bin/fenvix"
echo "installed release 1 into $home"
FENVIX_HOME="$home" "$home/bin/fenvix" version
