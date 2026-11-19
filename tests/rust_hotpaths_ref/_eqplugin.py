"""pytest plugin (``-p _eqplugin``) for equivalence tests: every ``--det-cache`` session records its tests twice,
with the reference Python path (into a copy of the cache directory as it was at session start, ``<dir>-ref``) and
with the current path, then writes both decisions to ``$DETPY_EQ_OUT`` (one JSON line per session)."""

import json
import os
import shutil

from detpy import proofcache as pc

_orig_configure = pc.ProofCachePlugin.configure
_orig_record = pc.ProofCachePlugin._record_captured


def _configure(self, config):
    ref_dir = self.dir + "-ref"
    # this copy is not an input of any test; nor are configure's own reads, which this wrapper's frames (outside
    # pytest) would otherwise make look like user code
    was, self.cap.active = self.cap.active, False
    try:
        shutil.rmtree(ref_dir, ignore_errors=True)
        if os.path.isdir(self.dir):
            shutil.copytree(self.dir, ref_dir)
        _orig_configure(self, config)
    finally:
        self.cap.active = was


def _ref_view(self, store):
    """The plugin as the round-1 reference loop reads it: the round-2 Python plugin (``_ref_proofcache.py``) without
    its ``__init__``, holding the Rust session's bookkeeping (``CacheSession.state``) and ``store``."""
    from _ref_pc_helpers import _m as ref

    v = ref.ProofCachePlugin.__new__(ref.ProofCachePlugin)
    for name in ("cap", "items", "root", "dir", "run_id", "epoch", "config_digest", "runtime_digest"):
        setattr(v, name, getattr(self, name))
    for name, value in self.sess.state().items():
        setattr(v, name, value)
    v.store, v.not_cached, v.not_cached_where, v.stale_hits, v.recorded = store, {}, {}, {}, 0
    return v


def _record_captured(self):
    from _ref_record import record_reference

    ref_dir = self.dir + "-ref"
    ref_store = pc._core.ProofCache(ref_dir, self.root)
    view = _ref_view(self, ref_store)
    record_reference(view, ref_store)
    ref = {"not_cached": view.not_cached, "where": view.not_cached_where, "stale": view.stale_hits,
           "recorded": view.recorded}
    _orig_record(self)
    d = self.sess.outcomes_data(self.cap)
    new = {"not_cached": d["not_cached_ids"], "where": d["not_cached_where"], "stale": d["stale_reuses"],
           "recorded": d["recorded"]}
    with open(os.environ["DETPY_EQ_OUT"], "a") as fh:
        fh.write(json.dumps({"ref": ref, "new": new, "dir": self.dir, "ref_dir": ref_dir}) + "\n")


pc.ProofCachePlugin.configure = _configure
pc.ProofCachePlugin._record_captured = _record_captured
