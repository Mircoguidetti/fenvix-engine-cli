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

The decisions are in Rust (``crates/detpy-py/src/reexec.rs``, ``crates/detpy-core/src/reexec.rs``): the personality
read and set, the cache directory, ``plan``, the command line, ``can_reexec``, the precompile's directories and its
stamps file with the todo/fresh decision. This module keeps the exec itself, ``sysconfig`` and the driver
subprocess. The Python original is kept verbatim in ``tests/rust_hotpaths_ref/_ref_reexec_r2.py``.
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
_EXCLUDE_NAMES = (".git", ".hg", ".tox", ".nox", "node_modules", ".venv", "venv", ".eggs", ".mypy_cache", ".detpy")
_EXCLUDE = r"[/\\](" + "|".join(n.replace(".", r"\.") for n in _EXCLUDE_NAMES) + r")[/\\]"

# Number of pytest sessions currently configured in this process. A nested,
# in-process session (``pytest.main()`` from a test, pytester inline runs)
# must never exec: it would replace the outer process.
SESSION_DEPTH = 0


def aslr_disabled() -> bool | None:
    """True/False on Linux, None when unknown (``/proc/self/personality``)."""
    return _core().aslr_disabled()


def _disable_aslr_for_exec() -> bool:
    """``personality(current | ADDR_NO_RANDOMIZE)``, inherited by the exec'd interpreter (Linux only)."""
    return _core().disable_aslr_for_exec()


def pyc_cache_dir(hashseed: str) -> str:
    return _core().pyc_cache_dir(hashseed)


def bytecode_active(hashseed: str) -> bool:
    return _core().bytecode_active(hashseed)


def plan(want_hashseed: str, want_no_aslr: bool, want_bytecode: bool = True) -> dict:
    """What a re-exec would fix: {'hashseed': bool, 'aslr': bool, 'bytecode': bool}."""
    return _core().reexec_plan(want_hashseed, want_no_aslr, want_bytecode)


def _argv() -> list[str] | None:
    return _core().reexec_argv()


def can_reexec() -> tuple[bool, str]:
    return _core().reexec_can(SESSION_DEPTH)


def precompile_dirs(rootdir: str | None) -> list[str]:
    paths = sysconfig.get_paths()
    return _core().reexec_precompile_dirs([paths.get(key) for key in ("stdlib", "purelib", "platlib")], rootdir)


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
    # directory is checked once more, which converts its bytecode to checked-hash pycs.
    # The stamps file's read and write and the todo/fresh decision are in Rust (_core.reexec_precompile_plan).
    # The exclusions (VCS, tool caches, virtual environments) apply to the project's tree only: a library
    # directory is itself inside a virtual environment (venv/lib/python3.X/site-packages), and excluding it there
    # left every installed module to be compiled from source at every run
    stamps_path = os.path.join(prefix, "stamps-v3.json")
    libs, project, stamps = _core().reexec_precompile_plan(dirs, rootdir, stamps_path)
    driver = _driver_source()
    for dirs_, extra in ((libs, []), (project, ["-x", _EXCLUDE])):
        if not dirs_:
            continue
        stale = _stale_sources(dirs_, prefix, bool(extra))
        if stale is None:  # no Rust check here: the driver walks and checks the directories itself
            cmd, data = [sys.executable, "-c", driver, *extra, *dirs_], None
        elif not stale:
            continue
        else:
            cmd, data = [sys.executable, "-c", driver, "--stdin"], b"\0".join(os.fsencode(f) for f in stale)
        p = subprocess.run(cmd, env=env, input=data, stdin=None if data is not None else subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if p.returncode != 0:  # interrupted: no stamps (a file that does not compile is skipped, not an error)
            return time.perf_counter() - t0
    stamps.write(stamps_path)
    return time.perf_counter() - t0


def _core():
    from . import _core as c

    return c


_SIP: list = []  # [(c_rounds, d_rounds)] of importlib.util.source_hash, [None] when the Rust hash does not match it


def _hash_variant():
    if not _SIP:
        import importlib.util

        key = int.from_bytes(importlib.util.MAGIC_NUMBER, "little")
        probe = b"detpy source_hash probe\n" * 3
        want = importlib.util.source_hash(probe)
        _SIP.append(next((v for v in ((1, 3), (2, 4)) if _core().source_hash(probe, key, *v) == want), None))
    return _SIP[0]


def _stale_sources(dirs: list, prefix: str, project: bool) -> list | None:
    """The sources the driver would compile for ``dirs`` (with the project's exclusions when ``project``), checked in
    Rust (``_core.pyc_stale_hashed``: the driver's walk and up-to-date test); None when the Rust check does not apply
    here (not POSIX, an optimization level that names ``.opt-N.pyc`` files, an unknown source hash)."""
    import importlib.util

    if os.name != "posix" or os.environ.get("PYTHONOPTIMIZE") or sys.flags.optimize:
        return None
    variant = _hash_variant()
    if variant is None or sys.implementation.cache_tag is None:
        return None
    return _core().pyc_stale_hashed(dirs, prefix, sys.implementation.cache_tag, importlib.util.MAGIC_NUMBER,
                                    os.getcwd(), list(_EXCLUDE_NAMES) if project else [],
                                    int.from_bytes(importlib.util.MAGIC_NUMBER, "little"), *variant)


def _driver_source() -> str:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_pycompile.py"), encoding="utf-8") as fh:
        return fh.read()


def dir_stamp(d: str) -> str:
    """Digest of a library directory's top-level entries with their mtimes and each ``*.dist-info/RECORD``'s (in
    Rust; the Python original is ``tests/rust_hotpaths_ref/_ref_reexec_r015.py``)."""
    return _core().dir_stamp(d)


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
