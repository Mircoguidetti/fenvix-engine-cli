"""The pure helpers of the round-2 Python proofcache module (``_ref_proofcache.py``) that the round-1 reference
loop (``_ref_record.py``) imports: some left ``detpy.proofcache`` when its capture moved to Rust."""

import importlib.util
import os
import sys

_name = "detpy._ref_proofcache_helpers"
if _name in sys.modules:
    _m = sys.modules[_name]
else:
    _spec = importlib.util.spec_from_file_location(_name, os.path.join(os.path.dirname(__file__), "_ref_proofcache.py"))
    _m = importlib.util.module_from_spec(_spec)
    sys.modules[_name] = _m
    _spec.loader.exec_module(_m)

_GLOBAL_CTX, _ctx_file, _encodable, _final, _module_of, _uncacheable = (
    _m._GLOBAL_CTX, _m._ctx_file, _m._encodable, _m._final, _m._module_of, _m._uncacheable)
