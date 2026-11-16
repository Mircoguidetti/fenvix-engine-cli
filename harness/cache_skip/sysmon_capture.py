"""Per-context line capture with ``sys.monitoring`` (Python 3.12+), a cheaper
replacement for ``coverage run`` + dynamic contexts in the cache-skip study.

It records the same thing as coverage.py in statement mode: for every context
(``t|nodeid``, ``f|...``, ``c|file``, ``s|session``, ``""`` before the first
switch), the set of lines executed in each file below the root. It is cheaper
because every (code location, context) pair costs one callback instead of one
callback per execution:

* No event is enabled globally. ``LINE`` is enabled locally on every code
  object whose file is below the root: module code objects are seen through
  the ``exec`` audit event (raised by every import, ``exec``, ``eval`` and
  ``runpy`` before the code runs), and the functions and classes they define
  are the code objects nested in their constants. Code that exists before the
  start is found with ``gc``. The test runner's own code is never
  instrumented, so a restart costs nothing there.
* The ``LINE`` callback adds the line to the current context's set and returns
  ``DISABLE``: a loop body costs one callback, not one per iteration.
* A context switch calls ``sys.monitoring.restart_events()``, which re-arms
  every disabled location, so each line is seen again (once) in the new
  context. A switch with nothing recorded since the previous one skips the
  restart.

Data is kept as ``{context: {co_filename: set(lines)}}`` and written once, at
interpreter exit, in the compact form ``run_repo.extract_coverage`` produces
from a coverage.py data file: ``{"files", "blobs", "ctx"}``.
"""

from __future__ import annotations

import atexit
import gzip
import os
import pickle
import sys
from types import CodeType, FunctionType

_mon = getattr(sys, "monitoring", None)
AVAILABLE = _mon is not None
_DBG = os.environ.get("SYSMON_DBG", "")
_DBG_NORESTART = "norestart" in _DBG


class SysmonCapture:
    def __init__(self, root: str, out: str):
        self.root = os.path.realpath(root)
        self.root_sep = self.root + os.sep
        self.out = out
        self.data: dict[str, dict[str, set]] = {}
        self.ctx = ""
        self.cur: dict[str, set] = self.data.setdefault("", {})
        self.dirty = False
        self.tool = None
        self._wanted: dict[str, bool] = {}
        self._armed: set[int] = set()
        self._keep: list = []  # armed code objects stay alive: their id() is never reused
        self._saved = False

    # -- filtering -------------------------------------------------------------
    def _want(self, filename: str) -> bool:
        w = self._wanted.get(filename)
        if w is None:
            w = False
            # coverage.py never traces "<string>", "<doctest ...>", ... (not a real original file name)
            if filename and not filename.startswith("<"):
                try:
                    p = os.path.realpath(os.path.abspath(filename))
                except (OSError, ValueError):
                    p = ""
                w = p.startswith(self.root_sep)
            self._wanted[filename] = w
        return w

    # -- arming --------------------------------------------------------------
    def arm(self, code) -> None:
        """Enable LINE locally on ``code`` and on every code object nested in it, if its file is below the root."""
        stack = [code]
        set_local, tool, LINE = _mon.set_local_events, self.tool, _mon.events.LINE
        while stack:
            c = stack.pop()
            if id(c) in self._armed:
                continue
            fn = c.co_filename
            w = self._wanted.get(fn)
            if w is None:
                w = self._want(fn)
            if not w:
                continue
            self._armed.add(id(c))
            self._keep.append(c)
            set_local(tool, c, LINE)
            stack.extend(k for k in c.co_consts if isinstance(k, CodeType))

    def _audit(self, event, args):
        # every module body (import, runpy, exec, eval) passes here with its code object before it runs; the
        # functions and classes it defines are nested code objects, armed with it
        if event == "exec" and self.tool is not None:
            code = args[0]
            if isinstance(code, CodeType) and id(code) not in self._armed:
                self.arm(code)

    def _arm_existing(self) -> None:
        """Code objects created before ``start`` (functions of modules imported earlier, frames on the stack)."""
        import gc

        for o in gc.get_objects():
            if type(o) is FunctionType:
                self.arm(o.__code__)
        f = sys._getframe()
        while f is not None:
            self.arm(f.f_code)
            f = f.f_back

    def _make_line_callback(self):
        DISABLE = _mon.DISABLE
        me = self

        def line(code, lineno):
            cur = me.cur
            fn = code.co_filename
            s = cur.get(fn)
            if s is None:
                cur[fn] = {lineno}
            else:
                s.add(lineno)
            me.dirty = True
            return DISABLE

        return line

    # -- control ---------------------------------------------------------------
    def start(self) -> None:
        if "off" in _DBG:
            return
        for tid in (_mon.COVERAGE_ID, 4, 3, 2, 5):
            if _mon.get_tool(tid) is None:
                self.tool = tid
                break
        else:
            raise RuntimeError("sys.monitoring: no free tool id")
        _mon.use_tool_id(self.tool, "cache_skip_capture")
        _mon.register_callback(self.tool, _mon.events.LINE, self._make_line_callback())
        # no global event: only code objects below the root are instrumented, so a restart_events() costs
        # nothing for the test runner's own code
        sys.addaudithook(self._audit)
        self._arm_existing()
        atexit.register(self.save)

    def switch_context(self, ctx: str) -> None:
        if ctx == self.ctx:
            return
        self.ctx = ctx
        self.cur = self.data.setdefault(ctx, {})
        if self.dirty:
            self.dirty = False
            if not _DBG_NORESTART:
                _mon.restart_events()

    def stop(self) -> None:
        if self.tool is not None:
            _mon.set_events(self.tool, 0)
            for code in self._keep:
                try:
                    _mon.set_local_events(self.tool, code, 0)
                except ValueError:
                    pass
            _mon.register_callback(self.tool, _mon.events.LINE, None)
            _mon.free_tool_id(self.tool)
            self.tool = None

    def compact(self) -> dict:
        """Same layout as ``run_repo.extract_coverage``: {"files", "blobs", "ctx"}; paths relative to the root."""
        rel_of: dict[str, str] = {}
        for per in self.data.values():
            for fn in per:
                if fn not in rel_of:
                    p = os.path.realpath(os.path.abspath(fn))
                    rel_of[fn] = p[len(self.root_sep):] if p.startswith(self.root_sep) else p
        # one file may appear under several co_filename spellings: merge per (ctx, rel path)
        merged: dict[str, dict[str, set]] = {}
        for c, per in self.data.items():
            for fn, lines in per.items():
                if lines:
                    merged.setdefault(rel_of[fn], {}).setdefault(c, set()).update(lines)
        files, blobs, ctx = [], [], {}
        blob_ix: dict = {}
        for rel in sorted(merged):
            fi = len(files)
            files.append(rel)
            for c, lines in merged[rel].items():
                key = (fi, tuple(sorted(lines)))
                b = blob_ix.get(key)
                if b is None:
                    b = blob_ix[key] = len(blobs)
                    blobs.append(key)
                ctx.setdefault(c, []).append(b)
        return {"files": files, "blobs": blobs, "ctx": ctx}

    def save(self) -> None:
        if self._saved:
            return
        self._saved = True
        self.stop()
        with gzip.open(self.out, "wb", compresslevel=3) as fh:
            pickle.dump(self.compact(), fh, protocol=pickle.HIGHEST_PROTOCOL)
