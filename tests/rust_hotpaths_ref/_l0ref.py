"""pytest plugin (``-p _l0ref``): run detpy with a Python reference path instead of the Rust one, for the
equivalence tests. ``DETPY_L0_REF`` selects it:

* ``1``: the Python Level 0 path of round 1: ``_ref_l0_sites.py``, ``_ref_l0_state.py``, ``_ref_l0_clock.py``
  (``_sites.resolve`` and ``norm_path``, ``_state.record`` and ``digest_names``, the virtual clock and its ``time.*``
  stand-ins) and ``_ref_l0_seeds.py``, ``_ref_l0_fsorder.py`` (the random / entropy stand-ins, the sorted filesystem
  enumeration);
* ``clock2``: only ``detpy.clock`` from ``_ref_l0_clock_r2.py``, the clock module as it was before its round-2 port
  (the clock and the six ``time.*`` reads in Rust, everything else Python: ``sleep``, the wall-derived functions,
  ``clock_gettime``, ``datetime.now``, the wait timeouts...), on the current Rust ``_sites`` / ``_state``.

Loaded by ``-p`` before pytest imports the detpy plugin (and again after detpy's re-exec, which keeps the
arguments): the reference modules are installed as ``detpy.<name>`` before the package itself runs. Their code is
compiled under the real modules' file names, so their frames are detpy's own (infrastructure) for every frame walk,
as the originals' were. With any other value (or none) the plugin does nothing: both paths then run with the same
plugins and arguments (which are part of the cache's configuration digest).
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

REFERENCES = {
    "1": (("_sites", "_ref_l0_sites.py"), ("_state", "_ref_l0_state.py"), ("clock", "_ref_l0_clock.py"),
          ("seeds", "_ref_l0_seeds.py"), ("fsorder", "_ref_l0_fsorder.py")),
    "clock2": (("clock", "_ref_l0_clock_r2.py"),),
}

_mode = os.environ.get("DETPY_L0_REF")

if _mode in REFERENCES and "detpy" not in sys.modules:
    spec = importlib.util.find_spec("detpy")
    pkg = importlib.util.module_from_spec(spec)
    sys.modules["detpy"] = pkg
    real_dir = os.path.dirname(spec.origin)
    for name, ref in REFERENCES[_mode]:
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
    pkg.LEVEL0_REFERENCE = True if _mode == "1" else _mode
