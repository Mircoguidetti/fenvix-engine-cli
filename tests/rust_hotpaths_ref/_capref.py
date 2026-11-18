"""pytest plugin (``-p _capref``): with ``DETPY_CAPTURE_REF=1``, run detpy's cache with proof on the round-2
Python capture (``_ref_proofcache.py``: ``Capture`` with its audit hook, reads, contexts, environment reads and
events in Python) instead of the Rust one (``_core.CaptureCore``), for the equivalence tests.

Loaded by ``-p`` before pytest imports the detpy plugin (and again after detpy's re-exec, which keeps the
arguments): the reference module is installed as ``detpy.proofcache`` before the package's plugin imports it,
compiled under the real module's file name so its frames are detpy's own for every frame walk, as the original's
were. Without the variable the plugin does nothing: both paths run with the same plugins and arguments (which are
part of the cache's configuration digest).
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

def _wanted() -> bool:
    """``DETPY_CAPTURE_REF=1``, or ``DETPY_CAPTURE_REF=@<file>`` and the file holds ``1`` (the equivalence tests keep
    the environment of both paths identical: the environment is an input)."""
    v = os.environ.get("DETPY_CAPTURE_REF", "")
    if v.startswith("@"):
        try:
            with open(v[1:]) as fh:
                v = fh.read().strip()
        except OSError:
            return False
    return v == "1"


if _wanted() and "detpy.proofcache" not in sys.modules:
    import detpy

    real = os.path.join(os.path.dirname(detpy.__file__), "proofcache.py")
    mod = type(sys)("detpy.proofcache")
    mod.__file__ = real
    mod.__package__ = "detpy"
    sys.modules["detpy.proofcache"] = mod
    with open(os.path.join(HERE, "_ref_proofcache.py")) as fh:
        code = compile(fh.read(), real, "exec")
    exec(code, mod.__dict__)
    detpy.proofcache = mod
    mod.CAPTURE_REFERENCE = True
