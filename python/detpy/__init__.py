"""detpy: deterministic execution of Python tests (Level 0).

The pytest plugin lives in :mod:`detpy.plugin` and is enabled with ``--det``;
the fingerprinting, verification, trace and cassette formats are implemented
in Rust (:mod:`detpy._core`).
"""

__version__ = "0.1.0"

from .network import NetworkBlockedError  # noqa: E402

__all__ = ["NetworkBlockedError", "__version__"]
