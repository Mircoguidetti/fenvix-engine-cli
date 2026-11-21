"""The machine's real CPU count, captured when detpy is imported, before ``--det`` pins what tests see
(``_level0.pin_cpu_count``): the engine sizes its own work (precompile and code-fact workers, the runtime
identity) on the real machine, outside the tests' view."""

from __future__ import annotations

import os

_cpu_count = os.cpu_count
_process_cpu_count = getattr(os, "process_cpu_count", None)
_sched_getaffinity = getattr(os, "sched_getaffinity", None)


def cpu_count() -> int | None:
    return _cpu_count()


def process_cpu_count() -> int | None:
    return _process_cpu_count() if _process_cpu_count is not None else None


def affinity() -> int | None:
    if _sched_getaffinity is None:
        return None
    try:
        return len(_sched_getaffinity(0))
    except OSError:
        return None
