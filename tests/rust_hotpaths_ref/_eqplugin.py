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


def _record_captured(self):
    from _ref_record import record_reference

    ref_dir = self.dir + "-ref"
    saved = (self.store, self.not_cached, self.not_cached_where, self.stale_hits, self.recorded)
    ref_store = pc._core.ProofCache(ref_dir, self.root)
    self.store, self.not_cached, self.not_cached_where, self.stale_hits, self.recorded = ref_store, {}, {}, {}, 0
    try:
        record_reference(self, ref_store)
        ref = {"not_cached": self.not_cached, "where": self.not_cached_where, "stale": self.stale_hits,
               "recorded": self.recorded}
    finally:
        self.store, self.not_cached, self.not_cached_where, self.stale_hits, self.recorded = saved
    _orig_record(self)
    new = {"not_cached": self.not_cached, "where": self.not_cached_where, "stale": self.stale_hits,
           "recorded": self.recorded}
    with open(os.environ["DETPY_EQ_OUT"], "a") as fh:
        fh.write(json.dumps({"ref": ref, "new": new, "dir": self.dir, "ref_dir": ref_dir}) + "\n")


pc.ProofCachePlugin.configure = _configure
pc.ProofCachePlugin._record_captured = _record_captured
