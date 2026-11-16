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
  instrumented.
* ``PY_START`` is also enabled on the code objects with an *entry line* (see
  ``entry_line``: one-line functions, lambdas, docstring-only functions, empty
  modules), the one line ``LINE`` alone never reports and coverage.py does.
* Each callback appends one integer (file id, line) to a flat ``array`` and
  returns ``DISABLE``: a loop body costs one callback, not one per iteration,
  and nothing is allocated per event (no per-context sets for the garbage
  collector to traverse).
* A context switch notes the position in the array and calls
  ``sys.monitoring.restart_events()``, which re-arms every disabled location,
  so each line is seen again (once) in the new context. A switch with nothing
  recorded since the previous restart skips it.

At interpreter exit the raw data (file names, context boundaries, the array
as bytes) is written as one uncompressed pickle; ``fold`` turns it, outside
the test process, into the compact form ``run_repo.extract_coverage``
produces from a coverage.py data file: ``{"files", "blobs", "ctx"}`` (as
coverage.py writes its data file at exit and ``extract_coverage`` reads it
afterwards). With ``raw=False`` the process folds and writes the compact form
itself.

Measured alternatives (see the capture-overhead report): re-arming only the
code objects with disabled lines (``set_local_events`` off and on) instead of
``restart_events()`` was not cheaper; keeping LINE armed and de-duplicating in
the callback is far more expensive on loops.
"""

from __future__ import annotations

import atexit
import gzip
import opcode
import os
import pickle
import sys
from array import array
from bisect import bisect_left
from types import CodeType, FunctionType

_mon = getattr(sys, "monitoring", None)
AVAILABLE = _mon is not None
# profiling knobs: "off" (tracer not started), "restart" (DISABLE + restart_events strategy), "python" (no C recorder)
_DBG = os.environ.get("SYSMON_DBG", "")
_RESUME = opcode.opmap.get("RESUME", -1)
# opcodes that may precede the first RESUME (cells, free variables, generator and coroutine creation)
_PRELUDE = {opcode.opmap[n] for n in ("MAKE_CELL", "COPY_FREE_VARS", "RETURN_GENERATOR", "POP_TOP")
            if n in opcode.opmap}
_SHIFT = 24  # recorded value: file id << _SHIFT | line
_MASK = (1 << _SHIFT) - 1
_HOT = int(os.environ.get("SYSMON_HOT", "16"))  # repeat hits of one location in one context before it is disabled


_NATIVE_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_sysmon_rec.c")


def load_native(build: bool = True):
    """The ``_sysmon_rec`` C recorder module, built on first use, or None (then the Python callbacks are used).

    The shared object is cached per interpreter and source hash under ``$CACHE_SKIP_NATIVE_DIR`` (default
    ``~/.cache/detpy/cache_skip``). ``CACHE_SKIP_NATIVE=0`` disables it. Building needs the C compiler and headers the
    interpreter was built with (``sysconfig``); any failure falls back silently.
    """
    if os.environ.get("CACHE_SKIP_NATIVE", "1") == "0" or not AVAILABLE:
        return None
    try:
        import hashlib
        import importlib.machinery
        import importlib.util
        import sysconfig

        with open(_NATIVE_SRC, "rb") as fh:
            src = fh.read()
        tag = f"{sys.implementation.cache_tag}-{hashlib.sha256(src).hexdigest()[:12]}"
        d = os.environ.get("CACHE_SKIP_NATIVE_DIR") or os.path.join(
            os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "detpy", "cache_skip")
        so = os.path.join(d, f"_sysmon_rec-{tag}{importlib.machinery.EXTENSION_SUFFIXES[0]}")
        if not os.path.exists(so):
            if not build:
                return None
            import shlex
            import subprocess
            import tempfile

            os.makedirs(d, exist_ok=True)
            cc = shlex.split(sysconfig.get_config_var("CC") or "cc")
            cflags = shlex.split(sysconfig.get_config_var("CCSHARED") or "-fPIC")
            ldshared = shlex.split(sysconfig.get_config_var("LDSHARED") or "cc -shared")
            inc = sysconfig.get_paths()["include"]
            with tempfile.TemporaryDirectory(dir=d) as tmp:
                obj = os.path.join(tmp, "rec.o")
                out = os.path.join(tmp, "rec.so")
                subprocess.run([*cc, *cflags, "-O2", "-I", inc, "-c", _NATIVE_SRC, "-o", obj], check=True,
                               capture_output=True, timeout=120)
                subprocess.run([*ldshared, obj, "-o", out], check=True, capture_output=True, timeout=120)
                os.replace(out, so)  # atomic: concurrent builders race harmlessly
        spec = importlib.util.spec_from_file_location("_sysmon_rec", so)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def entry_line(code) -> int | None:
    """The line ``LINE`` alone never reports on entry, which ``sys.settrace`` (hence coverage.py) does.

    The first instruction after the RESUME raises a line event only when its line differs from the RESUME's;
    legacy tracing (and any tool with ``PY_START`` on the code object) reports it on every entry anyway. This is
    the only line of one-line functions, lambdas, docstring-only functions and empty modules. Returns that line
    when it is the RESUME's line, else None (the line event fires by itself).
    """
    co = code.co_code
    r = 0
    while r < len(co) and co[r] in _PRELUDE:
        r += 2
    if r + 2 >= len(co) or co[r] != _RESUME:
        return None
    lr = ln = None
    for start, end, line in code.co_lines():
        if start <= r < end:
            lr = line
        if start <= r + 2 < end:
            ln = line
            break
    return ln if ln is not None and ln == lr else None


class SysmonCapture:
    def __init__(self, root: str, out: str, raw: bool = False):
        self.root = os.path.realpath(root)
        self.root_sep = self.root + os.sep
        self.out = out
        self.raw = raw
        self.buf = array("Q")
        self.segs: list[tuple[str, int]] = [("", 0)]  # (context, start index in buf)
        self.ctx = ""
        self.mark = 0  # len(buf) at the last restart
        self.tool = None
        self._wanted: dict[str, bool] = {}
        self._fid: dict[str, int] = {}  # co_filename -> file id << _SHIFT
        self._fnames: list[str] = []
        self._armed: set[int] = set()
        self._keep: list = []  # armed code objects stay alive: their id() is never reused
        self._entry: dict[int, int] = {}  # id(code) -> entry line (see entry_line), recorded from PY_START
        self._events: dict[int, int] = {}  # id(code) -> local events armed on it
        self._seen: dict[int, int] = {}  # recorded value -> repeat hits in the current context ("count" strategy)
        self._hot: dict = {}  # id -> code objects with a location disabled in the current context
        self.restart = "restart" in _DBG
        self.rec = None  # native recorder (``_sysmon_rec.Recorder``), set by start() when it can be loaded
        self._len = self.buf.__len__
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
            if w:
                self._fid[filename] = len(self._fnames) << _SHIFT
                self._fnames.append(filename)
        return w

    # -- arming --------------------------------------------------------------
    def arm(self, code) -> None:
        """Enable LINE locally on ``code`` and on every code object nested in it, if its file is below the root."""
        stack = [code]
        set_local, tool, LINE, START = _mon.set_local_events, self.tool, _mon.events.LINE, _mon.events.PY_START
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
            e = entry_line(c)
            ev = LINE
            if e is not None:
                self._entry[id(c)] = e
                ev = LINE | START
            self._events[id(c)] = ev
            if self.rec is not None:
                self.rec.add_code(c, self._fid[fn], -1 if e is None else e)
            set_local(tool, c, ev)
            stack.extend(k for k in c.co_consts if isinstance(k, CodeType))

    def _audit(self, event, args):
        # every module body (import, runpy, exec, eval) passes here with its code object before it runs; the
        # functions and classes it defines are nested code objects, armed with it
        if event == "exec" and self.tool is not None:
            code = args[0]
            if isinstance(code, CodeType) and id(code) not in self._armed:
                self.arm(code)

    def _arm_existing(self) -> None:
        """Code objects created before ``start`` (functions of modules imported earlier, frames on the stack).

        The heap is scanned only when a module below the root is already loaded (usually none is: the plugin is
        imported before conftest files and the code under test).
        """
        if any(self._want(getattr(m, "__file__", None) or "") for m in list(sys.modules.values())):
            import gc

            for o in gc.get_objects():
                if type(o) is FunctionType:
                    self.arm(o.__code__)
        f = sys._getframe()
        while f is not None:
            self.arm(f.f_code)
            f = f.f_back

    def _make_callbacks(self):
        """(LINE callback, PY_START callback).

        Default ("count") strategy: the first hit of a location in the current context appends one integer to the
        array; the next ``_HOT`` hits only count; past that the location is a loop body and is disabled, and its code
        object is re-armed (``set_local_events`` off and on) at the next context switch. Most code objects are never
        re-armed, so no re-instrumentation is paid for them. "restart" strategy (``SYSMON_DBG=restart``): DISABLE on
        the first hit and ``restart_events()`` at every switch, which re-instruments every code object run afterwards.
        """
        DISABLE = _mon.DISABLE
        app, fid, entry = self.buf.append, self._fid, self._entry
        if self.restart:
            def line(code, lineno):
                app(fid[code.co_filename] | lineno)
                return DISABLE

            def start(code, offset):
                app(fid[code.co_filename] | entry[id(code)])
                return DISABLE

            return line, start
        seen = self._seen
        get = seen.get
        hot = self._hot
        HOT = _HOT

        def line(code, lineno):
            k = fid[code.co_filename] | lineno
            c = get(k)
            if c is None:
                seen[k] = 0
                app(k)
            elif c < HOT:
                seen[k] = c + 1
            else:
                hot[id(code)] = code
                return DISABLE

        def start(code, offset):
            k = fid[code.co_filename] | entry[id(code)]
            c = get(k)
            if c is None:
                seen[k] = 0
                app(k)
            elif c < HOT:
                seen[k] = c + 1
            else:
                hot[id(code)] = code
                return DISABLE

        return line, start

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
        native = None if self.restart or "python" in _DBG else load_native()
        if native is not None:
            self.rec = native.Recorder(_mon.DISABLE, _HOT)
            self._len = self.rec.__len__
            line, start = self.rec.line, self.rec.start
        else:
            line, start = self._make_callbacks()
        _mon.register_callback(self.tool, _mon.events.LINE, line)
        _mon.register_callback(self.tool, _mon.events.PY_START, start)
        sys.addaudithook(self._audit)
        self._arm_existing()
        atexit.register(self.save)

    def switch_context(self, ctx: str) -> None:
        if ctx == self.ctx:
            return
        self.ctx = ctx
        n = self._len()
        if self.segs[-1][1] == n:
            self.segs[-1] = (ctx, n)
        else:
            self.segs.append((ctx, n))
        if self.restart:
            if n != self.mark:
                self.mark = n
                _mon.restart_events()
            return
        if self.rec is not None:
            hot = self.rec.switch()
        else:
            self._seen.clear()
            hot = list(self._hot.values())
            self._hot.clear()
        if hot:
            set_local, tool, ev = _mon.set_local_events, self.tool, self._events
            for code in hot:
                set_local(tool, code, 0)
                set_local(tool, code, ev[id(code)])

    def stop(self) -> None:
        if self.tool is not None:
            _mon.set_events(self.tool, 0)
            for code in self._keep:
                try:
                    _mon.set_local_events(self.tool, code, 0)
                except ValueError:
                    pass
            _mon.register_callback(self.tool, _mon.events.LINE, None)
            _mon.register_callback(self.tool, _mon.events.PY_START, None)
            _mon.free_tool_id(self.tool)
            self.tool = None

    def raw_data(self) -> dict:
        rel = []
        for fn in self._fnames:
            p = os.path.realpath(os.path.abspath(fn))
            rel.append(p[len(self.root_sep):] if p.startswith(self.root_sep) else p)
        return {"format": "sysmon-raw-1", "files": rel, "segs": self.segs, "buf": self.rec.tobytes() if self.rec is not None else self.buf.tobytes()}

    def save(self) -> None:
        if self._saved:
            return
        self._saved = True
        self.stop()
        raw = self.raw_data()
        if self.raw:
            with open(self.out, "wb") as fh:
                pickle.dump(raw, fh, protocol=pickle.HIGHEST_PROTOCOL)
        else:
            with gzip.open(self.out, "wb", compresslevel=3) as fh:
                pickle.dump(fold(raw), fh, protocol=pickle.HIGHEST_PROTOCOL)


def fold(raw: dict) -> dict:
    """Raw data -> {"files", "blobs", "ctx"} (layout of ``run_repo.extract_coverage``, paths relative to the root).

    ``ctx`` maps every context with at least one line to blob ids; a blob is (file index, sorted lines).
    """
    buf = array("Q")
    buf.frombytes(raw["buf"])
    by_ctx: dict[str, set] = {}
    segs = list(raw["segs"]) + [("", len(buf))]
    for (c, a), (_, b) in zip(segs, segs[1:]):
        if b > a:
            by_ctx.setdefault(c, set()).update(buf[a:b])
    rel = raw["files"]
    files = sorted(set(rel))
    fi_of = [files.index(r) for r in rel]  # one file may appear under several co_filename spellings
    mask = _MASK.__and__
    blobs: list = []
    blob_ix: dict = {}
    ctx: dict[str, list] = {}
    for c, vals in by_ctx.items():
        v = sorted(vals)
        per: dict[int, tuple] = {}
        i, n = 0, len(v)
        while i < n:
            f = v[i] >> _SHIFT
            j = bisect_left(v, (f + 1) << _SHIFT, i)
            fi = fi_of[f]
            lines = tuple(map(mask, v[i:j]))
            per[fi] = tuple(sorted(set(per[fi] + lines))) if fi in per else lines
            i = j
        ids = ctx[c] = []
        for fi in sorted(per):
            key = (fi, per[fi])
            b = blob_ix.get(key)
            if b is None:
                b = blob_ix[key] = len(blobs)
                blobs.append(key)
            ids.append(b)
    return {"files": files, "blobs": blobs, "ctx": ctx}


def fold_file(raw_path: str, out_path: str) -> None:
    """Read a raw capture, write the compact form gzip-pickled (``<stem>.cov.pkl.gz``)."""
    with open(raw_path, "rb") as fh:
        raw = pickle.load(fh)
    with gzip.open(out_path, "wb", compresslevel=3) as fh:
        pickle.dump(fold(raw), fh, protocol=pickle.HIGHEST_PROTOCOL)


if __name__ == "__main__":  # python sysmon_capture.py <raw> <out.cov.pkl.gz>
    fold_file(sys.argv[1], sys.argv[2])
