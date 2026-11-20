"""Which interpreters the engine supports, decided before anything imports the native core.

The wheel is ``cp312-abi3`` and the package says ``Requires-Python >=3.12``, so pip refuses older interpreters at
install time. This module is the second line: an install forced past that check (``--ignore-requires-python``, a
copied ``site-packages``, ``PYTHONPATH`` into a checkout) or an interpreter the wheel's ABI does not cover
(free-threaded builds, other implementations) gets one clear message and a usage-error exit, never a traceback
from the native module or from code that needs 3.12 (audit G-0547, G-0556, G-0548..G-0551, G-0553..G-0557).

Pure Python, standard library only, and valid syntax back to Python 3.6, so that the message itself can be shown.
"""

import sys
import sysconfig

MIN = (3, 12)
SUPPORTED = ("3.12", "3.13", "3.14")
EXIT_USAGE = 4  # pytest's usage-error exit code; the runners use the same


def problem():
    """None when this interpreter is supported, else the reason (one sentence)."""
    impl = sys.implementation.name
    ver = "%d.%d" % sys.version_info[:2]
    if impl != "cpython":
        return "fenvix supports CPython only; this is %s %s" % (impl, ver)
    if tuple(sys.version_info[:2]) < MIN:
        return "fenvix needs CPython 3.12 or newer; this is Python %s (%s)" % (ver, sys.executable)
    if sysconfig.get_config_var("Py_GIL_DISABLED"):
        return ("fenvix does not support the free-threaded build of CPython (%st); use the default build of %s"
                % (ver, ver))
    return None


PROBLEM = problem()


def message():
    return ("fenvix: %s. Supported: CPython %s on Linux x86_64 (glibc 2.28+)."
            % (PROBLEM, ", ".join(SUPPORTED)))


def refuse():
    """Print the message and exit with the usage-error code (for command-line entries)."""
    sys.stderr.write(message() + "\n")
    raise SystemExit(EXIT_USAGE)
