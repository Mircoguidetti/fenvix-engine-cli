# Reference copy (verbatim, review R-015 version of python/detpy/reexec.py, before round 2 moved its project and
# library checks to Rust: _core.pyc_stale_hashed, _core.dir_stamp). Its driver is the verbatim _pycompile.py next to
# it. Used by tests/test_precompile_rust.py only.
"""Re-launch the interpreter with a fixed PYTHONHASHSEED, deterministic bytecode
and ASLR disabled.

``PYTHONHASHSEED`` is read once at interpreter start-up, so when it does not
have the wanted value the only way to fix str/bytes hashing (and therefore set
iteration order) is to ``exec`` the same command line again with the variable
set. On Linux the same exec also disables address-space layout randomisation
(``personality(ADDR_NO_RANDOMIZE)``), which makes ``id()``-based hashes and
``repr`` addresses reproducible too. ``DETPY_REEXEC=1`` prevents loops.

Bytecode: a ``.pyc`` stores constants such as set literals (as ``frozenset``)
in the iteration order of the process that compiled them, and loading it can
yield a different set layout than compiling from source. To make every run
read the *same* bytecode, before the exec detpy precompiles the standard
library, site-packages and the project (``_pycompile.py``) *under the fixed
hash seed* into a private cache (``PYTHONPYCACHEPREFIX``), and the exec'd
interpreter runs with ``PYTHONDONTWRITEBYTECODE=1``: modules are then either
loaded from that deterministic cache or (if not precompiled, e.g. pytest's
assertion-rewritten test modules) always compiled from source.

The cached bytecode is *checked-hash* (PEP 552, ``_pycompile.py``): the import
system hashes the source before it uses a ``.pyc``, so stale bytecode never
runs, whatever the source's mtime says (a timestamp ``.pyc`` is valid for
``(int(mtime), size)``: same-size edits within one second, restored or foreign
mtimes, reinstalled library modules that keep their archive mtimes).
"""

from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
import time

ADDR_NO_RANDOMIZE = 0x0040000
MARKER = "DETPY_REEXEC"
PRECOMPILE_ENV = "DETPY_PRECOMPILE_S"
_EXCLUDE = r"[/\\](\.git|\.hg|\.tox|\.nox|node_modules|\.venv|venv|\.eggs|\.mypy_cache|\.detpy)[/\\]"

# Number of pytest sessions currently configured in this process. A nested,
# in-process session (``pytest.main()`` from a test, pytester inline runs)
# must never exec: it would replace the outer process.
SESSION_DEPTH = 0


def aslr_disabled() -> bool | None:
    """True/False on Linux, None when unknown."""
    try:
        with open("/proc/self/personality") as f:
            return bool(int(f.read().strip(), 16) & ADDR_NO_RANDOMIZE)
    except (OSError, ValueError):
        return None


def _disable_aslr_for_exec() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        current = libc.personality(0xFFFFFFFF)
        if current == -1:
            return False
        return libc.personality(current | ADDR_NO_RANDOMIZE) != -1
    except Exception:
        return False


def pyc_cache_dir(hashseed: str) -> str:
    base = os.environ.get("DETPY_PYC_CACHE") or os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "detpy", "pyc"
    )
    return os.path.join(base, f"{sys.implementation.cache_tag}-hashseed{hashseed}")


def bytecode_active(hashseed: str) -> bool:
    prefix = sys.pycache_prefix
    return bool(sys.flags.dont_write_bytecode and prefix
                and os.path.realpath(prefix) == os.path.realpath(pyc_cache_dir(hashseed)))


def plan(want_hashseed: str, want_no_aslr: bool, want_bytecode: bool = True) -> dict:
    """What a re-exec would fix: {'hashseed': bool, 'aslr': bool, 'bytecode': bool}."""
    need_hash = os.environ.get("PYTHONHASHSEED") != want_hashseed
    need_aslr = want_no_aslr and aslr_disabled() is False
    need_bytecode = want_bytecode and not bytecode_active(want_hashseed)
    return {"hashseed": need_hash, "aslr": need_aslr, "bytecode": need_bytecode}


def _argv() -> list[str] | None:
    orig = getattr(sys, "orig_argv", None)
    if orig:
        return [sys.executable] + list(orig[1:])
    # Python < 3.10: rebuild the command line (interpreter flags are lost).
    main = sys.modules.get("__main__")
    spec = getattr(main, "__spec__", None)
    if spec is not None and spec.name in ("pytest", "pytest.__main__"):
        return [sys.executable, "-m", "pytest", *sys.argv[1:]]
    if sys.argv and sys.argv[0]:
        return [sys.executable, *sys.argv]
    return None


def can_reexec() -> tuple[bool, str]:
    if os.environ.get(MARKER) == "1":
        return False, "already re-executed"
    if SESSION_DEPTH > 1:
        return False, "nested in-process pytest session"
    if os.name != "posix":
        return False, "exec is only supported on POSIX"
    if _argv() is None:
        return False, "cannot reconstruct the command line"
    return True, ""


def precompile_dirs(rootdir: str | None) -> list[str]:
    paths = sysconfig.get_paths()
    dirs = []
    for key in ("stdlib", "purelib", "platlib"):
        p = paths.get(key)
        if p and os.path.isdir(p) and os.path.realpath(p) not in map(os.path.realpath, dirs):
            dirs.append(p)
    if rootdir and os.path.isdir(rootdir):
        dirs.append(rootdir)
    return dirs


def precompile(hashseed: str, rootdir: str | None) -> float:
    """Compile every reachable module under the fixed hash seed; returns seconds.

    Incremental: a module whose cached checked-hash ``.pyc`` matches its source's hash is skipped.
    """
    prefix = pyc_cache_dir(hashseed)
    os.makedirs(prefix, exist_ok=True)
    env = dict(os.environ)
    env.update(PYTHONHASHSEED=hashseed, PYTHONPYCACHEPREFIX=prefix)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    t0 = time.perf_counter()
    dirs = precompile_dirs(rootdir)
    # The standard library and site-packages hold tens of thousands of modules (home-assistant: compileall's
    # up-to-date check alone took 7-8 s per run). They are skipped while their top-level state (entries, their
    # mtimes, each dist-info's RECORD) is the one of the last complete precompile: an installer changes it. A
    # module edited in place without that fails the import system's source-hash check and is loaded from source
    # under the same fixed seed, in every run alike.
    # The project is always checked (it changes at every commit).
    # v3: stamps written while the cache held timestamp .pyc files (v2 and earlier) do not count: every library
    # directory is checked once more, which converts its bytecode to checked-hash pycs
    stamps_path = os.path.join(prefix, "stamps-v3.json")
    try:
        import json

        with open(stamps_path) as fh:
            stamps = json.load(fh)
    except (OSError, ValueError):
        stamps = {}
    root_real = os.path.realpath(rootdir) if rootdir else None
    todo, fresh = [], {}
    for d in dirs:
        if root_real is not None and os.path.realpath(d) == root_real:
            todo.append(d)
            continue
        st = dir_stamp(d)
        fresh[d] = st
        if stamps.get(d) != st:
            todo.append(d)
    # the exclusions (VCS, tool caches, virtual environments) apply to the project's tree only: a library
    # directory is itself inside a virtual environment (venv/lib/python3.X/site-packages), and excluding it there
    # left every installed module to be compiled from source at every run
    project = [d for d in todo if root_real is not None and os.path.realpath(d) == root_real]
    libs = [d for d in todo if d not in project]
    driver = _driver_source()
    for dirs_, extra in ((libs, []), (project, ["-x", _EXCLUDE])):
        if not dirs_:
            continue
        cmd = [sys.executable, "-c", driver, *extra, *dirs_]
        p = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        if p.returncode != 0:  # interrupted: no stamps (a file that does not compile is skipped, not an error)
            return time.perf_counter() - t0
    try:
        import json

        tmp = f"{stamps_path}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            json.dump({**stamps, **fresh}, fh)
        os.replace(tmp, stamps_path)
    except OSError:
        pass
    return time.perf_counter() - t0


def _driver_source() -> str:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_pycompile.py"), encoding="utf-8") as fh:
        return fh.read()


def dir_stamp(d: str) -> str:
    """Digest of a library directory's top-level entries with their mtimes and each ``*.dist-info/RECORD``'s."""
    import hashlib

    h = hashlib.sha256()
    try:
        with os.scandir(d) as it:
            entries = sorted(it, key=lambda e: e.name)
    except OSError:
        return "missing"
    for e in entries:
        try:
            st = e.stat(follow_symlinks=False)
            h.update(f"{e.name}\0{st.st_mtime_ns}\0{st.st_ino}\n".encode("utf-8", "surrogateescape"))
            if e.name.endswith(".dist-info"):
                r = os.stat(os.path.join(e.path, "RECORD"))
                h.update(f"R{r.st_mtime_ns}\0{r.st_size}\0{r.st_ino}\n".encode())
        except OSError:
            h.update(f"{e.name}\0?\n".encode("utf-8", "surrogateescape"))
    return h.hexdigest()


BLOCKED_ENV = "DETPY_BLOCKED_PLUGINS"


def reexec(want_hashseed: str, want_no_aslr: bool, want_bytecode: bool = True, rootdir: str | None = None,
           block_plugins: list[str] | None = None) -> None:
    """Exec the current command line again. Does not return on success.

    ``block_plugins`` are passed as ``-p no:<name>``: the new process never
    loads them (unregistering an already loaded plugin leaves its fixtures).
    """
    need = plan(want_hashseed, want_no_aslr, want_bytecode)
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = want_hashseed
    env[MARKER] = "1"
    if want_bytecode:
        env[PRECOMPILE_ENV] = f"{precompile(want_hashseed, rootdir):.3f}"
        env["PYTHONPYCACHEPREFIX"] = pyc_cache_dir(want_hashseed)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
    if need["aslr"]:
        _disable_aslr_for_exec()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    argv = _argv()
    if block_plugins:
        env[BLOCKED_ENV] = ",".join(block_plugins)
        pos = argv.index("-m") + 2 if "-m" in argv else 2
        extra = [a for name in block_plugins for a in ("-p", f"no:{name}")]
        argv = argv[:pos] + extra + argv[pos:]
    os.execve(sys.executable, argv, env)
