"""pytest plugin (``-p _l0ref``): with ``DETPY_L0_REF=1``, run detpy with the round-1 Python Level 0 path (``_ref_l0_sites.py``,
``_ref_l0_state.py``, ``_ref_l0_clock.py``: ``_sites.resolve``, ``_state.record``, the virtual clock and its
``time.*`` stand-ins in Python) instead of the Rust one, for the equivalence tests.

Loaded by ``-p`` before pytest imports the detpy plugin (and again after detpy's re-exec, which keeps the
arguments): the reference modules are installed as ``detpy._sites``, ``detpy._state`` and ``detpy.clock`` before
the package itself runs. Their code is compiled under the real modules' file names, so their frames are detpy's
own (infrastructure) for every frame walk, as the originals' were. Without the variable the plugin does nothing:
both paths then run with the same plugins and arguments (which are part of the cache's configuration digest).
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

if os.environ.get("DETPY_L0_REF") == "1" and "detpy" not in sys.modules:
    spec = importlib.util.find_spec("detpy")
    pkg = importlib.util.module_from_spec(spec)
    sys.modules["detpy"] = pkg
    real_dir = os.path.dirname(spec.origin)
    for name, ref in (("_sites", "_ref_l0_sites.py"), ("_state", "_ref_l0_state.py"), ("clock", "_ref_l0_clock.py")):
        real = os.path.join(real_dir, name + ".py")
        mod = type(sys)(f"detpy.{name}")
        mod.__file__ = real
        mod.__package__ = "detpy"
        sys.modules[f"detpy.{name}"] = mod
        with open(os.path.join(HERE, ref)) as fh:
            code = compile(fh.read(), real, "exec")
        exec(code, mod.__dict__)
        setattr(pkg, name, mod)
    spec.loader.exec_module(pkg)
    pkg.LEVEL0_REFERENCE = True
