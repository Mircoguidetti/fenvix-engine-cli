"""Precompile driver for ``--det`` (run by ``reexec.precompile`` in a child interpreter under the fixed hash seed and
``PYTHONPYCACHEPREFIX``; not imported by detpy itself).

Every ``.pyc`` it writes is a *checked-hash* pyc (PEP 552): its header holds the hash of the source it was compiled
from, and the import system reads and hashes the source before using it. A stale ``.pyc`` therefore never runs,
whatever the source's mtime and size say (a timestamp ``.pyc`` is valid for ``(int(mtime), size)``: a same-size
edit whose mtime falls in the same second, a restored or foreign mtime, or a reinstalled library module kept it).

Up-to-date check: a source whose cached ``.pyc`` is a checked-hash pyc of the same magic and source hash is skipped;
any other is compiled again (``compileall`` would recompile every hash-based pyc at every run).

    python -c <this file's text> [-x REGEX] DIR...      (``-x``: skip files whose path matches, like compileall)
    python -c <this file's text> --stdin                 (the files to check: NUL-separated paths on stdin)

``reexec.precompile`` walks and checks the directories in Rust (``_core.pyc_stale_hashed``, the same walk and test)
and hands only the stale files to ``--stdin``; the directory form is its fallback.
"""

import sys

if sys.path and sys.path[0] in ("", "."):
    del sys.path[0]  # never import from the working directory (a project module named like the stdlib)

import importlib.util  # noqa: E402
import os  # noqa: E402
import py_compile  # noqa: E402
import re  # noqa: E402

_MAGIC = importlib.util.MAGIC_NUMBER
_FLAGS = (3).to_bytes(4, "little")  # hash-based, check_source
_MODE = py_compile.PycInvalidationMode.CHECKED_HASH


def sources(dirs, exclude):
    """``.py`` files under ``dirs`` as ``compileall`` lists them: ``__pycache__`` and symlinked directories are
    not entered; ``exclude`` is searched in each file's full path."""
    for d in dirs:
        for root, subdirs, files in os.walk(d):
            subdirs[:] = sorted(s for s in subdirs if s != "__pycache__"
                                and not (exclude is not None and exclude.search(os.path.join(root, s) + os.sep)))
            for f in sorted(files):
                if f.endswith(".py"):
                    p = os.path.join(root, f)
                    if exclude is None or not exclude.search(p):
                        yield p


def check(path: str) -> int:
    """Compile ``path`` unless its cached pyc is a checked-hash pyc of its current content; 1 if compiled."""
    try:
        with open(path, "rb") as fh:
            src = fh.read()
        cfile = importlib.util.cache_from_source(path)
    except (OSError, ValueError, NotImplementedError):
        return 0
    want = _MAGIC + _FLAGS + importlib.util.source_hash(src)
    try:
        with open(cfile, "rb") as fh:
            if fh.read(16) == want:
                return 0
    except OSError:
        pass
    # py_compile reads the source again and stores the hash of what it compiled: the pyc always matches its code
    py_compile.compile(path, cfile=cfile, doraise=False, quiet=2, invalidation_mode=_MODE)
    return 1


def _chunk(paths):
    return sum(check(p) for p in paths)


def main(argv) -> int:
    exclude = None
    if argv[:1] == ["--stdin"]:
        files = [os.fsdecode(p) for p in sys.stdin.buffer.read().split(b"\0") if p]
    else:
        if len(argv) >= 2 and argv[0] == "-x":
            exclude, argv = re.compile(argv[1]), argv[2:]
        files = list(sources(argv, exclude))
    n = os.cpu_count() or 1
    if n > 1 and len(files) > 256 and hasattr(os, "fork"):
        import multiprocessing

        size = max(64, len(files) // (n * 8))
        parts = [files[i:i + size] for i in range(0, len(files), size)]
        # fork: workers are copies of this process (no import of this script by name, no __main__ pickling)
        with multiprocessing.get_context("fork").Pool(n) as pool:
            pool.map(_chunk, parts, chunksize=1)
    else:
        _chunk(files)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
