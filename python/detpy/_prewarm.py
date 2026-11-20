"""Audit G-0168: write pytest's assertion-rewritten test modules into detpy's rewrite cache before the process that runs
the tests starts (``python -m detpy._prewarm``, job on stdin, run by ``plugin.prewarm_rewrite_cache``).

A first run after a checkout or an edit used to compile its test modules from source in the test process: that
allocates what a later run (which loads them from the cache) does not, so id()-dependent behaviour (the order of a set
of plain objects) differed between the first run and every later one, with ASLR off. This process runs with the test
process's hash seed and bytecode prefix, parses, rewrites and compiles each file and writes it where the test process
looks, under the same keyed name (``plugin._rewrite_key``). Nothing is imported or executed: rewriting is parse and
compile only. A file whose rewrite would differ (a rewriter patched by a plugin: the key differs) is not written; what
the test process still compiles from source is a run input (``_level0.REWRITE``).
"""
from __future__ import annotations

import hashlib
import json
import marshal
import os
import sys
from importlib.util import MAGIC_NUMBER
from pathlib import Path

OWN_MAGIC = b"DETPYRW1"  # plugin._OWN_MAGIC: detpy's format for pytest < 9.2


class _Config:
    """What the rewrite reads from pytest's configuration: the ``enable_assertion_pass_hook`` ini value."""

    def __init__(self, pass_hook: bool) -> None:
        self._hook = pass_hook

    def getini(self, name):
        if name == "enable_assertion_pass_hook":
            return self._hook
        raise ValueError(name)


class _State:
    @staticmethod
    def trace(*_a, **_k) -> None:
        return None


def run(job: dict) -> int:
    from _pytest.assertion import rewrite as rw

    from . import plugin

    cfg = _Config(bool(job["pass_hook"]))
    if plugin._rewrite_key(cfg, rw) != job["key"]:  # a plugin patched the rewriter: not this one's code
        return 0
    real_rewrite, read_pyc = rw._rewrite_test, rw._read_pyc
    # the test process digests the rewriter with detpy's own cache installed (plugin._early_rewrite_cache): so does
    # this one, for the same keyed name
    from ._patch import Patcher

    plugin._cache_rewritten_tests(None, Patcher())
    key = plugin._rewrite_key(cfg, rw)
    if key is None:
        return 0
    tail = rw.PYC_TAIL[:-len(rw.PYC_EXT)] + ".det-" + key + rw.PYC_EXT
    hashed = bool(job["hashed"])
    written = 0
    for f in job["files"]:
        fn = Path(f)
        try:
            target = rw.get_cache_dir(fn) / (fn.name[:-3] + tail)
            source = fn.read_bytes()
            check = hashlib.sha256(MAGIC_NUMBER + source).digest()
            if hashed:
                if read_pyc(fn, target) is not None:
                    continue
            else:
                try:
                    with open(target, "rb") as fh:
                        head = fh.read(40)
                    if head[:8] == OWN_MAGIC and head[8:40] == check:
                        continue
                except OSError:
                    pass
            stamp, co = real_rewrite(fn, cfg)
            os.makedirs(target.parent, exist_ok=True)
            if hashed:
                rw._write_pyc(_State, co, stamp, target)
            else:
                tmp = f"{target}.{os.getpid()}"
                with open(tmp, "wb") as fh:
                    fh.write(OWN_MAGIC + check + marshal.dumps(co))
                os.replace(tmp, target)
            written += 1
        except (OSError, SyntaxError, ValueError, UnicodeDecodeError):
            continue
    return written


def main() -> int:
    print(run(json.load(sys.stdin)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
