#!/usr/bin/env bash
# Install the fenvix engine from its artifact (this directory, unpacked from fenvix-engine-<version>-linux-x86_64.tar.gz).
#
#   ./install.sh [PREFIX]          PREFIX default: $FENVIX_HOME or /opt/fenvix
#   PYTHON=/path/to/python ./install.sh ...   the interpreter that gets the pytest plugin (default: python3)
#
# Python: the wheel (pytest plugin, `python -m detpy` runners, `fenvix` command) goes into $PYTHON's environment;
# its one dependency, pytest>=8.1, comes from the package index unless already installed.
# Node: the shells and the native core go to PREFIX/node (no npm install: they have no runtime dependencies);
# `fenvix node <runner> ...` and `node PREFIX/node/bin/fenvix.js <runner> ...` start them.
# Exit 4, with one sentence, on an unsupported interpreter or platform (CPython 3.12-3.14, Linux x86_64, glibc 2.28+).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
prefix="${1:-${FENVIX_HOME:-/opt/fenvix}}"
py="${PYTHON:-python3}"

if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != x86_64 ]; then
  echo "fenvix: this engine artifact is for Linux x86_64; this machine is $(uname -s) $(uname -m)" >&2; exit 4
fi
rc=0
"$py" - <<'PY' || rc=$?
import sys, sysconfig
v = "%d.%d" % sys.version_info[:2]
if sys.implementation.name != "cpython" or sys.version_info[:2] < (3, 12) or sysconfig.get_config_var("Py_GIL_DISABLED"):
    sys.stderr.write("fenvix: needs CPython 3.12, 3.13 or 3.14 (default build); %s is %s %s%s\n"
                     % (sys.executable, sys.implementation.name, v, "t" if sysconfig.get_config_var("Py_GIL_DISABLED") else ""))
    sys.exit(4)
PY
[ "$rc" -eq 0 ] || exit "$rc"

"$py" -m pip install -q --disable-pip-version-check "$here"/wheels/fenvix-*.whl
# the installed engine loads, and no other distribution writes its import package `detpy/` (the unrelated PyPI
# project of that name; audit G-0170, G-0737): otherwise the installation is refused
if ! "$py" -m detpy.fenvix_cli doctor >&2; then
  echo "fenvix: the installation in $("$py" -c 'import sys; print(sys.prefix)') does not pass fenvix doctor (above)" >&2
  exit 1
fi
mkdir -p "$prefix/node" "$prefix/bin"
cp -R "$here/node/." "$prefix/node/"
install -m 755 "$here/bin/fenvix" "$prefix/bin/fenvix"
cp "$here/VERSION.json" "$prefix/VERSION.json"
if command -v node >/dev/null 2>&1; then
  if major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null)"; then
    case "$major" in 22|24|26) ;; *) echo "fenvix: Node $major found; the Node shells are tested on Node 22, 24 and 26" >&2 ;; esac
  else
    echo "fenvix: the node on PATH does not start ($(node --version 2>&1 | head -1)); the Node shells need a working Node 22, 24 or 26" >&2
  fi
fi
echo "installed fenvix $(cat "$here/VERSION") into $prefix (Python: $("$py" -c 'import sys; print(sys.executable)'))"
