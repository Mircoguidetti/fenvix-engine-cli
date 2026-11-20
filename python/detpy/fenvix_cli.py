"""``fenvix``: the single command of the engine (console script of the wheel; ``bin/fenvix`` of the engine artifact).

Interface only: it finds the language shell and hands it the arguments unchanged. Every decision (controls,
fingerprints, traces, keys, reuse) is the engine's.

    fenvix --version                       the version of this package (one line: ``fenvix X.Y.Z``)
    fenvix version                         versions of every component found, and the checks of ``fenvix doctor``
    fenvix doctor                          checks the installation (interpreter, native core, foreign ``detpy``)
    fenvix python [pytest args]            pytest with the detpy plugin  (e.g. --det, --det-cache=DIR)
    fenvix python-runner RUNNER [args]     python -m detpy RUNNER ...    (unittest, django, nose2, ward, zope, doctest)
    fenvix node RUNNER [args]              the Node shell: RUNNER = vitest, jest, mocha, node-test, ava, tap, ...
    fenvix verify TRACE_A TRACE_B          python -m detpy verify (every shell writes the same trace format)
    fenvix detect [DIR]                    the languages of DIR by their build files (one per line)
    fenvix go test [args]                  fenvix-go test ...  (runner image only: $FENVIX_HOME/bin)
    fenvix jvm ...                         the JVM agent       (runner image only: $FENVIX_HOME/jvm)

Node: the shells are installed by the engine artifact into $FENVIX_HOME/node (release/engine/install.sh);
``fenvix node`` uses them, else a checkout's node_modules/.bin/fenvix.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

from . import _support
from ._version import __version__

HOME = os.environ.get("FENVIX_HOME", "/opt/fenvix")


def _path(*p):
    return os.path.join(HOME, *p)


def _exec(argv):
    try:
        os.execvp(argv[0], argv)
    except FileNotFoundError:
        sys.stderr.write(f"fenvix: {argv[0]} not found (FENVIX_HOME={HOME})\n")
        sys.exit(127)


def _first(*cands):
    for c in cands:
        if c and (os.path.exists(c) or shutil.which(c)):
            return c
    return cands[-1]


def detect(d):
    files = set(os.listdir(d))
    out = []
    if files & {"pyproject.toml", "setup.py", "setup.cfg", "pytest.ini", "tox.ini"}:
        out.append("python")
    if "package.json" in files:
        out.append("node")
    if "go.mod" in files:
        out.append("go")
    if files & {"pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"}:
        out.append("jvm")
    return out


def foreign_detpy_owners() -> list[str]:
    """Installed distributions other than ``fenvix`` that also write the import package ``detpy/``.

    The PyPI project ``detpy`` (an unrelated toolbox) installs a top-level ``detpy/`` too; installing it after
    fenvix replaces the engine's files (audit G-0170, G-0737). pip cannot declare the conflict, so it is checked
    here and by ``fenvix doctor``."""
    from importlib import metadata

    out = []
    for dist in metadata.distributions():
        name = (dist.metadata.get("Name") or "").lower()
        if name == "fenvix":
            continue
        top = (dist.read_text("top_level.txt") or "").split()
        files = dist.files or ()
        if "detpy" in top or any(str(f).startswith("detpy/") for f in files):
            out.append(f"{dist.metadata.get('Name')} {dist.version}")
    return sorted(set(out))


def doctor() -> list[tuple[str, bool, str]]:
    """(check, ok, detail) of this installation."""
    rows = []
    prob = _support.PROBLEM
    rows.append(("interpreter", prob is None, prob or f"CPython {sys.version.split()[0]} ({sys.executable})"))
    if prob is None:
        try:
            from . import _core

            rows.append(("native core", True, os.path.basename(_core.__file__)))
        except Exception as e:  # reported, not hidden
            rows.append(("native core", False, f"{type(e).__name__}: {e}"))
    foreign = foreign_detpy_owners()
    rows.append(("import package detpy", not foreign,
                 "owned by fenvix only" if not foreign else
                 "also written by " + ", ".join(foreign) + " (an unrelated project with the same import name: "
                 "uninstall it and reinstall fenvix)"))
    return rows


def version(full: bool = True) -> int:
    def run(cmd):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip().splitlines()
            return out[0] if out else "absent"
        except Exception as e:  # reported, not hidden
            return f"unavailable ({type(e).__name__})"

    print(f"fenvix {__version__}")
    if not full:
        return 0
    print(f"python {sys.version.split()[0]} {sys.platform} {os.uname().machine}")
    node = _node_cmd()
    print("node shell", run(node + ["--version"]) if node else "absent")
    print("fenvix-go", "present" if os.path.exists(_path("bin", "fenvix-go")) else "absent")
    print("fenvix-skip", "present" if os.path.exists(_path("bin", "fenvix-skip")) else "absent")
    print("fenvix-agent.jar", "present" if os.path.exists(_path("jvm", "fenvix-agent.jar")) else "absent")
    bad = 0
    for name, ok, detail in doctor():
        print(f"check {name}: {'ok' if ok else 'PROBLEM'} ({detail})")
        bad += not ok
    return 1 if bad else 0


def _node_cmd() -> list[str] | None:
    image = _path("node", "bin", "fenvix.js")
    if os.path.exists(image) and shutil.which("node"):
        return ["node", image]
    d = os.getcwd()
    while True:
        b = os.path.join(d, "node_modules", ".bin", "fenvix")
        if os.path.exists(b):
            return [b]
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd in ("--version", "-V"):
        return version(full=False)
    if cmd == "version":
        return version()
    if cmd == "doctor":
        rows = doctor()
        for name, ok, detail in rows:
            print(f"{name}: {'ok' if ok else 'PROBLEM'} ({detail})")
        return 0 if all(ok for _, ok, _ in rows) else 1
    if cmd == "detect":
        print("\n".join(detect(rest[0] if rest else ".")))
        return 0
    if cmd in ("python", "python-runner", "verify") and _support.PROBLEM is not None:
        _support.refuse()
    if cmd == "python":
        _exec([sys.executable, "-m", "pytest"] + rest)
    if cmd == "python-runner":
        _exec([sys.executable, "-m", "detpy"] + rest)
    if cmd == "verify":
        _exec([sys.executable, "-m", "detpy", "verify"] + rest)
    if cmd == "node":
        node = _node_cmd()
        if node is None:
            sys.stderr.write(f"fenvix: the Node shells are not installed (no {_path('node', 'bin', 'fenvix.js')}): "
                             "install the engine artifact, or set FENVIX_HOME\n")
            return 127
        _exec(node + rest)
    if cmd == "go":
        _exec([_first(_path("bin", "fenvix-go"), "fenvix-go")] + rest)
    if cmd == "jvm":
        if rest and rest[0] == "decide":
            _exec([_first(_path("bin", "fenvix-skip"), "fenvix-skip")] + rest)
        _exec(["java", "-jar", _path("jvm", "fenvix-agent.jar")] + rest)
    sys.stderr.write(f"fenvix: unknown command {cmd!r} (fenvix --help)\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
