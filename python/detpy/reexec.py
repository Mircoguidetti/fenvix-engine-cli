"""Re-launch the interpreter with a fixed PYTHONHASHSEED (and ASLR disabled).

``PYTHONHASHSEED`` is read once at interpreter start-up, so when it does not
have the wanted value the only way to fix str/bytes hashing (and therefore set
iteration order) is to ``exec`` the same command line again with the variable
set. On Linux the same exec also disables address-space layout randomisation
(``personality(ADDR_NO_RANDOMIZE)``), which makes ``id()``-based hashes and
``repr`` addresses reproducible too. ``DETPY_REEXEC=1`` prevents loops.
"""

from __future__ import annotations

import os
import sys

ADDR_NO_RANDOMIZE = 0x0040000
MARKER = "DETPY_REEXEC"

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


def fresh_bytecode_active() -> bool:
    return bool(sys.flags.dont_write_bytecode and sys.pycache_prefix and "detpy-nopyc" in sys.pycache_prefix)


def plan(want_hashseed: str, want_no_aslr: bool, want_fresh_bytecode: bool = False) -> dict:
    """What a re-exec would fix: {'hashseed': bool, 'aslr': bool, 'bytecode': bool}."""
    need_hash = os.environ.get("PYTHONHASHSEED") != want_hashseed
    need_aslr = want_no_aslr and aslr_disabled() is False
    need_bytecode = want_fresh_bytecode and not fresh_bytecode_active()
    return {"hashseed": need_hash, "aslr": need_aslr, "bytecode": need_bytecode}


def can_reexec() -> tuple[bool, str]:
    if os.environ.get(MARKER) == "1":
        return False, "already re-executed"
    if SESSION_DEPTH > 1:
        return False, "nested in-process pytest session"
    if os.name != "posix":
        return False, "exec is only supported on POSIX"
    if not getattr(sys, "orig_argv", None):
        return False, "sys.orig_argv unavailable (Python < 3.10)"
    return True, ""


def reexec(want_hashseed: str, want_no_aslr: bool, want_fresh_bytecode: bool = False) -> None:
    """Exec the current command line again. Does not return on success."""
    need = plan(want_hashseed, want_no_aslr, want_fresh_bytecode)
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = want_hashseed
    env[MARKER] = "1"
    if want_fresh_bytecode:
        # Never read nor write .pyc files: constants such as set literals are
        # then always built from source (a .pyc stores a frozenset in the
        # iteration order of the process that compiled it).
        import tempfile

        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPYCACHEPREFIX"] = os.path.join(tempfile.gettempdir(), "detpy-nopyc-empty")
    if need["aslr"]:
        _disable_aslr_for_exec()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    os.execve(sys.executable, list(sys.orig_argv), env)
