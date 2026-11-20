"""detpy: deterministic execution of Python tests (Level 0).

The pytest plugin lives in :mod:`detpy.plugin` and is enabled with ``--det``;
the fingerprinting, verification, trace and cassette formats are implemented
in Rust (:mod:`detpy._core`).
"""

import sys as _sys

from . import _support

from ._version import __version__

if _support.PROBLEM is None:
    from .network import NetworkBlockedError  # noqa: E402

    __all__ = ["NetworkBlockedError", "__version__"]
else:
    # Unsupported interpreter: nothing below may import the native core. `import detpy.plugin` (the pytest11 entry
    # point) gets the inactive plugin instead of the real one (detpy/_unsupported_plugin.py).
    from . import _unsupported_plugin as _up

    _sys.modules[__name__ + ".plugin"] = _up
    __all__ = ["__version__"]
