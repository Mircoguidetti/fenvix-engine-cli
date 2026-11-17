"""Cache with proof (``pytest --det --det-cache=DIR``).

A test's previous result is reused only when every input it depended on is
unchanged; every reused result comes with a receipt (what was checked, the
digests). What counts as an input (each one recorded while the test runs):

* **code it executed**: per outermost function (``sys.monitoring`` LINE events
  attributed to the running test, its wider-scoped fixtures and the collection
  of its file); plus the module-level structure (*skeleton*) of every
  repository module it had loaded, the pytest hook surface of every conftest,
  and functions run at import time (those build module state any later reader
  depends on);
* **files it read**: content digest, read-write opens included; paths it found
  missing; directories it listed;
* **environment variables it read** (value digests; enumerating the environment
  makes the whole environment an input);
* **runtime identity**: interpreter (version and binary), platform, installed
  distributions;
* **configuration**: pytest version, options and ini, plugins, the Level 0
  controls. Under ``--det`` the clock, randomness, hash seed and network are
  controlled, so they are configuration, not hidden inputs; the clock's epoch
  is an input of the tests that read the clock.

Never reused: a failure (only passed, skipped and xfailed results are
reused); a test that opened a network connection (loopback included) or
spawned a process; a test that drew OS entropy without ``--det-urandom``;
a test that read a file another test wrote in the same session.

The Rust core (``detpy._core``) records executed lines (``LineRecorder``),
filters audit events, hashes files, stores entries, computes the keys and
decides reuse (``ProofCache``). This module wires them into pytest.
"""

from __future__ import annotations

import json
import os
import platform
import random
import sys
import time
from types import CodeType, FunctionType

import pytest

from . import __version__, _codefacts, _core, _sites, _state

# real clocks, bound before Level 0 virtualises the time module
_perf = time.perf_counter
_now = time.time
_mon = getattr(sys, "monitoring", None)
AVAILABLE = _mon is not None

# context names: "" startup, "s" between tests, "c|<file>" collection of a file,
# "f|<scope>|<baseid>|<name>" setup of a wider-scoped fixture, "t|<nodeid>" a test
_GLOBAL_CTX = ("", "s")

_AUDIT_EVENTS = ("exec", "open", "sqlite3.connect", "os.listdir", "os.scandir", "socket.connect", "subprocess.Popen", "os.posix_spawn",
                 "os.exec", "os.system", "os.fork", "os.forkpty", "os.spawn", "os.remove", "os.rename", "os.mkdir",
                 "os.rmdir", "os.truncate", "shutil.rmtree", "shutil.copyfile", "shutil.move", "os.symlink",
                 "os.link")
_SPAWN = {"subprocess.Popen", "os.posix_spawn", "os.exec", "os.system", "os.fork", "os.forkpty", "os.spawn"}
_WRITE_EVENTS = {"os.remove": (0,), "os.rename": (0, 1), "os.mkdir": (0,), "os.rmdir": (0,),
                 "shutil.rmtree": (0,), "shutil.copyfile": (1,), "shutil.move": (0, 1), "os.symlink": (1,),
                 "os.link": (1,), "os.truncate": (0,)}
_SKIP_PARTS = (os.sep + "__pycache__" + os.sep, os.sep + ".git" + os.sep, os.sep + ".pytest_cache",
               os.sep + ".mypy_cache", os.sep + ".hypothesis" + os.sep, os.sep + ".detpy" + os.sep)
_O_ACC = os.O_RDONLY | os.O_WRONLY | os.O_RDWR
# options that never change a test's result (output, reporting, selection by path, detpy's own files)
_VOLATILE_OPTIONS = {
    "file_or_dir", "verbose", "quiet", "color", "code_highlight", "reportchars", "tbstyle", "showlocals",
    "durations", "durations_min", "junitxml", "junitprefix", "resultlog", "basetemp", "det_cache",
    "det_cache_verify", "det_cache_receipts", "det_trace", "det_outcomes", "det_compare", "det_max_events",
    "showcapture", "fulltrace", "collectonly", "markers", "fixtures", "show_fixtures_per_test", "help", "version",
    "debug", "traceconfig", "showlocals", "log_file", "log_cli_level", "pastebin", "usepdb", "usepdb_cls",
    "trace", "xmlpath", "htmlpath", "lf", "failedfirst", "last_failed_no_failures", "newfirst", "cacheclear",
    "cacheshow", "stepwise", "stepwise_skip", "maxfail", "exitfirst", "no_header", "no_summary", "override_ini",
    "inifilename", "rootdir", "confcutdir", "keyword", "markexpr", "deselect", "ignore", "ignore_glob",
    "continue_on_collection_errors", "numprocesses", "dist", "tx", "det_epoch",
}


_DETPY_DIR = os.path.dirname(os.path.abspath(__file__)) + os.sep


def _ctx_file(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


# ---------------------------------------------------------------------------
# entry line (as in the cache-skip study's tracer)
import opcode as _opcode  # noqa: E402

_RESUME = _opcode.opmap.get("RESUME", -1)
_PRELUDE = {_opcode.opmap[n] for n in ("MAKE_CELL", "COPY_FREE_VARS", "RETURN_GENERATOR", "POP_TOP")
            if n in _opcode.opmap}


def entry_line(code) -> int | None:
    """The line ``LINE`` alone never reports on entry (one-line functions, lambdas, docstring-only bodies)."""
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


# ---------------------------------------------------------------------------
class Capture:
    """Records, per context, executed code, data reads, environment reads and events."""

    def __init__(self, root: str, env0: dict, hot: int = 16):
        self.root = os.path.realpath(root)
        self.root_sep = self.root + os.sep
        self.env0 = env0
        self.ctx = ""
        self.ctx_ix: dict[str, int] = {"": 0}
        self.ctx_names: list[str] = [""]
        self.segs: list[tuple[int, int]] = [(0, 0)]
        self.tool = None
        self.rec = None
        self.hot = hot
        self._wanted: dict[str, bool] = {}
        self.fid: dict[str, int] = {}
        self.fnames: list[str] = []  # fid -> path relative to root
        self._armed: set[int] = set()
        self._events: dict[int, int] = {}
        self.preloaded: set[str] = set()
        # per context: data deps {path: dep}, flags
        self.data: dict[int, dict[str, str]] = {}
        self.env: dict[int, set] = {}
        self.flags: dict[int, set] = {}  # "net", "spawn", "proc", "time", "entropy", "netrec", "foreign:<path>"
        self.writers: dict[str, set] = {}  # abs path -> context indices that wrote it
        self._hashed: dict[str, str] = {}  # abs path -> dep at first read in the session
        self.loaded_order: list[tuple[str, int]] = []  # (rel module file, index of the test after which it was seen)
        self._seen_mods: set[str] = set()
        self._nmods = 0
        self.basetemp: str | None = None
        self.site_dirs: tuple = ()
        self.stdlib_dirs: tuple = ()
        self.dist_info_ok: tuple = ()
        self.import_ctx = -1  # pseudo context for import-time data/env/flags
        self.active = False

    # -- contexts -------------------------------------------------------------
    def ctx_index(self, name: str) -> int:
        i = self.ctx_ix.get(name)
        if i is None:
            i = self.ctx_ix[name] = len(self.ctx_names)
            self.ctx_names.append(name)
        return i

    def switch(self, name: str) -> None:
        if name == self.ctx:
            return
        self.ctx = name
        i = self.ctx_index(name)
        if self.rec is None:
            return
        n = len(self.rec)
        if self.segs[-1][1] == n:
            self.segs[-1] = (i, n)
        else:
            self.segs.append((i, n))
        hot = self.rec.switch()
        if hot:
            set_local, tool, ev = _mon.set_local_events, self.tool, self._events
            for code in hot:
                set_local(tool, code, 0)
                set_local(tool, code, ev[id(code)])

    def _cur(self) -> int:
        if self.rec is not None and self.rec.import_depth:
            return self.import_ctx
        return self.ctx_ix[self.ctx]

    # -- code ---------------------------------------------------------------------
    def _want(self, filename: str) -> bool:
        w = self._wanted.get(filename)
        if w is None:
            w = False
            if filename and not filename.startswith("<"):
                try:
                    p = os.path.realpath(os.path.abspath(filename))
                except (OSError, ValueError):
                    p = ""
                w = p.startswith(self.root_sep) and not any(s in p for s in _SKIP_PARTS)
                if w:
                    self.fid[filename] = len(self.fnames)
                    self.fnames.append(p[len(self.root_sep):].replace(os.sep, "/"))
            self._wanted[filename] = w
        return w

    def arm(self, code) -> None:
        stack = [code]
        set_local, tool = _mon.set_local_events, self.tool
        LINE, START, RET = _mon.events.LINE, _mon.events.PY_START, _mon.events.PY_RETURN
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
            e = entry_line(c)
            module = c.co_name == "<module>"
            ev = LINE
            if e is not None or module:
                ev |= START
            if module:
                ev |= RET
            self._events[id(c)] = ev
            self.rec.add_code(c, self.fid[fn], -1 if e is None else e, module)
            set_local(tool, c, ev)
            stack.extend(k for k in c.co_consts if isinstance(k, CodeType))

    def start(self) -> None:
        for tid in (_mon.COVERAGE_ID, 4, 3, 2, 5):
            if _mon.get_tool(tid) is None:
                self.tool = tid
                break
        else:
            raise RuntimeError("detpy --det-cache: sys.monitoring has no free tool id")
        _mon.use_tool_id(self.tool, "detpy-cache")
        self.rec = _core.LineRecorder(_mon.DISABLE, self.hot)
        self.import_ctx = self.ctx_index("i")
        self.ctx = ""
        _mon.register_callback(self.tool, _mon.events.LINE, self.rec.line)
        _mon.register_callback(self.tool, _mon.events.PY_START, self.rec.start)
        _mon.register_callback(self.tool, _mon.events.PY_RETURN, self.rec.ret)
        self.active = True
        _core.set_audit_hook(self._audit, _AUDIT_EVENTS)
        # code that exists before the start: modules already loaded become whole-content inputs
        pre = False
        for m in list(sys.modules.values()):
            f = getattr(m, "__file__", None)
            if f and self._want(f):
                self.preloaded.add(self.fnames[self.fid[f]])
                pre = True
        if pre:
            import gc

            for o in gc.get_objects():
                if type(o) is FunctionType:
                    self.arm(o.__code__)
        f = sys._getframe()
        while f is not None:
            self.arm(f.f_code)
            f = f.f_back

    def stop(self) -> None:
        if not self.active:
            return
        self.active = False
        _core.set_audit_hook(None, ())
        if self.tool is not None:
            for ev in (_mon.events.LINE, _mon.events.PY_START, _mon.events.PY_RETURN):
                _mon.register_callback(self.tool, ev, None)
            _mon.set_events(self.tool, 0)
            _mon.free_tool_id(self.tool)
            self.tool = None

    # -- data, environment, events ------------------------------------------------------
    def _caller_kind(self) -> str:
        """'import' (the import system), 'infra' (pytest, detpy, ...) or 'user', from the calling frames."""
        try:
            f = sys._getframe(2)  # 0 this function, 1 the audit callback, 2 the code that raised the event
        except ValueError:
            return "user"
        while f is not None:
            fn = f.f_code.co_filename
            if fn.startswith("<frozen importlib") or fn.startswith("<frozen zipimport"):
                return "import"
            if fn.startswith(_DETPY_DIR):  # detpy's own wrappers (network, fsorder, ...) are transparent
                f = f.f_back
                continue
            kind, _ = _sites._classify(fn)
            if kind == _sites._USER:
                return "user"
            if kind == _sites._INFRA:
                return "infra"
            f = f.f_back
        return "user"

    def _abs(self, p) -> str | None:
        if isinstance(p, int) or p is None:
            return None
        try:
            s = os.fsdecode(os.fspath(p))
        except (TypeError, ValueError):
            return None
        if not s:
            return None
        if not os.path.isabs(s):
            try:
                s = os.path.join(os.getcwd(), s)
            except OSError:
                return None
        return os.path.normpath(s)

    def _ignored(self, p: str) -> bool:
        if any(s in p for s in _SKIP_PARTS):
            return True
        if self.basetemp and (p == self.basetemp or p.startswith(self.basetemp + os.sep)):
            return True
        for d in self.site_dirs:
            if p.startswith(d):
                return not any(p.startswith(x) for x in self.dist_info_ok)
        return any(p.startswith(d) for d in self.stdlib_dirs) or p == os.devnull

    def _key(self, p: str) -> str:
        return p[len(self.root_sep):] if p.startswith(self.root_sep) else p

    def read(self, ctx: int, p: str, kind: str) -> None:
        """A read of ``p`` (kind f = file content, d = listing) in context ``ctx``."""
        if not _encodable(p):
            self.flags.setdefault(ctx, set()).add("badpath")
            return
        if p.startswith(("/proc/", "/sys/", "/dev/")):
            self.flags.setdefault(ctx, set()).add("proc")
            return
        if p in self.writers:
            # reads what code of this session wrote: allowed only if every writer is credited to the reader
            self.flags.setdefault(ctx, set()).add("rw:" + p)
            return
        hk = kind + p
        dep = self._hashed.get(hk)
        if dep is None:
            if kind == "d":
                d = _core.listing_digest(p)
                dep = f"d:{d}" if d is not None else "missing"
            else:
                d = _core.file_digest(p)
                dep = f"f:{d}" if d is not None else ("missing" if not os.path.exists(p) else "s:" + (
                    "dir" if os.path.isdir(p) else "other"))
            self._hashed[hk] = dep
        self.data.setdefault(ctx, {})[self._key(p)] = dep

    def wrote(self, ctx: int, p: str) -> None:
        self.writers.setdefault(p, set()).add(ctx)
        for k in ("f" + p, "d" + p, "d" + os.path.dirname(p)):
            self._hashed.pop(k, None)

    def _audit(self, event, args):
        if not self.active:
            return
        if event == "exec":
            # every module body (import, runpy, exec) passes here before it runs; the functions and classes
            # it defines are nested code objects, armed with it
            code = args[0] if args else None
            if isinstance(code, CodeType) and id(code) not in self._armed and self.tool is not None:
                self.arm(code)
            return
        if event == "open":
            p = self._abs(args[0] if args else None)
            if p is None or self._ignored(p):
                return
            mode, flags = (args[1] if len(args) > 1 else None), (args[2] if len(args) > 2 else 0)
            if isinstance(mode, str):
                reads = "r" in mode or "+" in mode
                writes = any(ch in mode for ch in "wax+")
                trunc = "w" in mode
            else:
                acc = (flags or 0) & _O_ACC
                reads = acc in (os.O_RDONLY, os.O_RDWR)
                writes = acc in (os.O_WRONLY, os.O_RDWR) or bool((flags or 0) & os.O_CREAT)
                trunc = bool((flags or 0) & os.O_TRUNC)
            kind = self._caller_kind()
            if kind in ("import", "infra"):
                return
            ctx = self._cur()
            if reads and not trunc:
                self.read(ctx, p, "f")
            if writes:
                self.wrote(ctx, p)
        elif event == "sqlite3.connect":
            # sqlite opens the database read-write in C (no "open" event): its committed content is an input
            db = args[0] if args else None
            if isinstance(db, (str, bytes, os.PathLike)) and os.fsdecode(db) not in ("", ":memory:") \
                    and not os.fsdecode(db).startswith("file:"):
                p = self._abs(db)
                if p is not None and not self._ignored(p) and self._caller_kind() not in ("import", "infra"):
                    ctx = self._cur()
                    self.read(ctx, p, "f")
                    self.wrote(ctx, p)
        elif event in ("os.listdir", "os.scandir"):
            if self._caller_kind() != "user":
                return
            p = self._abs(args[0] if args and args[0] is not None else ".")
            if p is None or self._ignored(p):
                return
            self.read(self._cur(), p, "d")
        elif event == "socket.connect":
            if self._caller_kind() == "infra":
                return
            self.flags.setdefault(self._cur(), set()).add("connect")
        elif event in _SPAWN or event.startswith("os.spawn") or event.startswith("os.exec"):
            if self._caller_kind() == "infra":
                return
            self.flags.setdefault(self._cur(), set()).add("spawn")
        else:
            idx = _WRITE_EVENTS.get(event)
            if idx is None or self._caller_kind() == "infra":
                return
            ctx = self._cur()
            for i in idx:
                p = self._abs(args[i] if len(args) > i else None)
                if p is not None and not self._ignored(p):
                    self.wrote(ctx, p)

    def env_read(self, name: str) -> None:
        if self.active:
            self.env.setdefault(self._cur(), set()).add(name)

    def event(self, source: str, value: str) -> None:
        """A Level 0 event (``detpy._state.record``) by user code."""
        if not self.active:
            return
        fl = self.flags.setdefault(self._cur(), set())
        if source == "net":
            if "record#" in value:
                fl.add("net-record")
            elif "replay" in value:
                fl.add("net-replay")
        else:
            fl.add(source)

    def scan_modules(self, index: int, plugins=()) -> None:
        """Note the repository modules loaded so far (``sys.modules`` and conftest plugins, which pytest keeps
        out of ``sys.modules``) as loaded after the test at ``index`` (-1 = collection)."""
        for m in plugins:
            f = getattr(m, "__file__", None)
            if isinstance(f, str) and self._want(f):
                rel = self.fnames[self.fid[f]]
                if rel not in self._seen_mods:
                    self._seen_mods.add(rel)
                    self.loaded_order.append((rel, index))
        mods = sys.modules
        if len(mods) == self._nmods:
            return
        self._nmods = len(mods)
        for m in list(mods.values()):
            f = getattr(m, "__file__", None)
            if not f:
                continue
            if f in self._wanted and not self._wanted[f]:
                continue
            if self._want(f):
                rel = self.fnames[self.fid[f]]
                if rel not in self._seen_mods:
                    self._seen_mods.add(rel)
                    self.loaded_order.append((rel, index))


# ---------------------------------------------------------------------------
# environment reads
_ENV_CAPTURE: Capture | None = None
_ENV_PATCHED = False


def _env_caller_is_user() -> bool:
    try:
        f = sys._getframe(3)
    except ValueError:
        return True
    while f is not None:
        fn = f.f_code.co_filename
        if fn.startswith(_DETPY_DIR):
            f = f.f_back
            continue
        kind, _ = _sites._classify(fn)
        if kind == _sites._USER:
            return True
        if kind == _sites._INFRA:
            return False
        f = f.f_back
    return True


def _note_env(key) -> None:
    cap = _ENV_CAPTURE
    if cap is None or not cap.active or not _env_caller_is_user():
        return
    cap.env_read(os.fsdecode(key) if isinstance(key, (str, bytes)) else repr(key))


def _patch_environ() -> None:
    global _ENV_PATCHED
    if _ENV_PATCHED:
        return
    _ENV_PATCHED = True

    def make(base):
        class _Recorded(base):
            def __getitem__(self, key):
                _note_env(key)
                return base.__getitem__(self, key)

            def __contains__(self, key):
                _note_env(key)
                return base.__contains__(self, key)

            def __iter__(self):
                _note_env("*")
                return base.__iter__(self)

        _Recorded.__name__ = base.__name__
        _Recorded.__qualname__ = base.__qualname__
        return _Recorded

    for name in ("environ", "environb"):
        o = getattr(os, name, None)
        if o is not None:
            try:
                o.__class__ = make(type(o))
            except TypeError:
                pass


# ---------------------------------------------------------------------------
# identities
def _dist_infos(root: str):
    """(runtime digest part for installed distributions, dist-info dirs of editable installs of the project)."""
    from importlib import metadata

    parts, editable = [], []
    root_sep = os.path.realpath(root) + os.sep
    for d in metadata.distributions():
        name = (d.metadata.get("Name") or "?") if d.metadata is not None else "?"
        path = getattr(d, "_path", None)
        project = False
        try:
            du = d.read_text("direct_url.json")
            if du:
                info = json.loads(du)
                url = info.get("url", "")
                if url.startswith("file://") and (os.path.realpath(url[7:]) + os.sep).startswith(root_sep):
                    project = True
        except Exception:
            pass
        if project:
            if path is not None:
                editable.append(os.path.realpath(str(path)) + os.sep)
            continue
        try:
            rec = d.read_text("RECORD") or ""
        except Exception:
            rec = ""
        parts.append(f"{name.lower()}=={d.version}:{_core.digest(rec.encode())}")
    return sorted(parts), editable


def runtime_identity(root: str) -> tuple[str, dict, list]:
    import sysconfig

    exe = os.path.realpath(sys.executable)
    lib = None
    libdir, ldlib = sysconfig.get_config_var("LIBDIR"), sysconfig.get_config_var("LDLIBRARY")
    if libdir and ldlib and os.path.exists(os.path.join(libdir, ldlib)):
        lib = os.path.join(libdir, ldlib)
    dists, editable = _dist_infos(root)
    d = {
        "python": sys.version,
        "cache_tag": sys.implementation.cache_tag,
        "executable": _core.file_digest(exe),
        "libpython": _core.file_digest(lib) if lib else None,
        "system": platform.system(),
        "machine": platform.machine(),
        "libc": "-".join(platform.libc_ver()),
        "stdlib": _core.listing_digest(os.path.dirname(os.__file__)),
        "distributions": _core.digest("\n".join(dists).encode()),
        "n_distributions": len(dists),
    }
    return _core.digest(json.dumps(d, sort_keys=True).encode()), d, editable


def config_identity(config) -> tuple[str, dict]:
    cfg = _state.STATE.config
    plugins = sorted({f"{dist.project_name}=={dist.version}"
                      for _, dist in config.pluginmanager.list_plugin_distinfo()})
    ini = getattr(config, "_inicfg", None)
    if ini is None:
        ini = {}
    ini_items = sorted((str(k), repr(getattr(v, "value", v))) for k, v in dict(ini).items())
    opts = []
    for k, v in sorted(vars(config.option).items()):
        if k in _VOLATILE_OPTIONS:
            continue
        r = repr(v)
        if " at 0x" in r:
            r = type(v).__name__
        opts.append((k, r))
    root = str(config.rootpath)
    inipath = getattr(config, "inipath", None)
    d = {
        "pytest": pytest.__version__,
        "detpy": __version__,
        "encoding": _core.ENCODING_VERSION,
        "plugins": plugins,
        "ini": ini_items,
        "inifile": os.path.relpath(str(inipath), root) if inipath else None,
        "options": opts,
        "level0": {
            "seed": cfg.seed, "shuffle": cfg.shuffle, "controls": sorted(cfg.controls), "tick": cfg.tick_ns,
            "tick_adapt": cfg.tick_adapt, "sleep": cfg.sleep, "urandom": cfg.control_urandom,
            "record_net": cfg.record_net, "allow_hosts": list(cfg.allow_hosts),
            "hashseed": os.environ.get("PYTHONHASHSEED"),
        },
    }
    return _core.digest(json.dumps(d, sort_keys=True, default=str).encode()), d


# ---------------------------------------------------------------------------
class ProofCachePlugin:
    """pytest hooks of ``--det-cache``."""

    def __init__(self, cap: Capture, cache_dir: str, verify: float, receipts: str | None):
        self.cap = cap
        self.dir = os.path.abspath(cache_dir)
        self.verify = verify
        self.receipts_path = receipts or os.path.join(self.dir, "receipts.jsonl")
        self.store = None
        self.config = None
        self.root = cap.root
        self.config_digest = ""
        self.runtime_digest = ""
        self.runtime_info: dict = {}
        self.epoch = 0
        self.hits: dict[str, dict] = {}  # nodeid -> receipt
        self.verifying: dict[str, dict] = {}  # nodeid -> receipt of a hit re-run for verification
        self.misses: dict[str, str] = {}
        self.items: dict[str, object] = {}
        self.test_index: dict[str, int] = {}
        self.fixture_ctx: dict[str, list] = {}
        self.ran: list[str] = []
        self.parts: dict[str, dict] = {}
        self.dur: dict[str, float] = {}
        self.fingerprints: dict[str, str] = {}
        self.verify_results: list[dict] = []
        self.summary: dict = {}
        self.run_id = f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime(_now()))}-{os.getpid()}"
        self.t_check = 0.0
        self.t_record = 0.0
        self.recorded = 0
        self.not_cached: dict[str, str] = {}
        self.stale_hits: dict[str, str] = {}
        self.error: str | None = None

    # -- setup ----------------------------------------------------------------
    def configure(self, config) -> None:
        self.config = config
        self.root = os.path.realpath(str(config.rootpath))
        self.config_digest, self.config_info = config_identity(config)
        self.runtime_digest, self.runtime_info, editable = runtime_identity(self.root)
        cap = self.cap
        cap.dist_info_ok = tuple(editable)
        cap.stdlib_dirs = tuple(d + os.sep for d in _sites._stdlib_dirs)
        cap.site_dirs = tuple(d + os.sep for d in _sites._site_dirs)
        factory = getattr(config, "_tmp_path_factory", None)
        if factory is not None:
            try:
                cap.basetemp = os.path.realpath(str(factory.getbasetemp()))
            except Exception:
                cap.basetemp = None
        self.epoch = _state.STATE.config.epoch_ns
        self.store = _core.ProofCache(self.dir, self.root)
        self.store.begin(self.config_digest, self.runtime_digest, self.epoch, dict(cap.env0))

    # -- collection -------------------------------------------------------------
    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_make_collect_report(self, collector):
        if not isinstance(collector, (pytest.File, pytest.Class)):
            yield
            return
        prev = self.cap.ctx
        self.cap.switch("c|" + _ctx_file(collector.nodeid))
        try:
            yield
        finally:
            self.cap.switch(prev)

    @pytest.hookimpl(trylast=True)
    def pytest_collection_finish(self, session):
        self.cap.switch("s")
        self.cap.scan_modules(-1, self._conftests())
        t0 = _perf()
        try:
            self._decide(session.items)
        finally:
            self.t_check = _perf() - t0

    def _decide(self, items) -> None:
        store = self.store
        for path, content in store.changed_code_files():
            mod, is_pkg = _module_of(os.path.join(self.root, path))
            f = _codefacts.read_facts(os.path.join(self.root, path), content, mod, is_pkg)
            if f is not None:
                store.set_fresh(path, content, f[0], f[1], f[2], f[3])
        rng = random.Random(f"detpy-cache-verify:{self.run_id}")
        for i, item in enumerate(items):
            nid = item.nodeid
            self.items[nid] = item
            self.test_index[nid] = i
            ok, info = store.check(nid)
            if ok:
                receipt = json.loads(info)
                if self.verify and rng.random() < self.verify:
                    self.verifying[nid] = receipt
                else:
                    self.hits[nid] = receipt
            else:
                self.misses[nid] = info

    # -- fixtures and tests ------------------------------------------------------
    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_fixture_setup(self, fixturedef, request):
        if fixturedef.scope == "function":
            yield
            return
        prev = self.cap.ctx
        self.cap.switch(f"f|{fixturedef.scope}|{fixturedef.baseid}|{fixturedef.argname}")
        try:
            yield
        finally:
            self.cap.switch(prev)

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_protocol(self, item, nextitem):
        receipt = self.hits.get(item.nodeid)
        if receipt is None:
            return None
        self._reuse(item, nextitem, receipt)
        return True

    def _wrap_protocol(self, item, nextitem):  # generator driven by _ProtocolWrapper
        nid = item.nodeid
        if nid in self.hits:
            yield
            return
        fx = []
        info = getattr(item, "_fixtureinfo", None)
        if info is not None:
            for name in item.fixturenames:
                defs = info.name2fixturedefs.get(name)
                if defs and defs[-1].scope != "function":
                    d = defs[-1]
                    fx.append(f"f|{d.scope}|{d.baseid}|{d.argname}")
        self.fixture_ctx[nid] = sorted(set(fx))
        self.cap.switch("t|" + nid)
        t = _perf()
        try:
            yield
        finally:
            self.dur[nid] = _perf() - t
            self.cap.switch("s")
            self.cap.scan_modules(self.test_index.get(nid, len(self.ran)), self._conftests())
            self.ran.append(nid)

    def pytest_runtest_logreport(self, report):
        if report.nodeid in self.hits:
            return
        p = self.parts.setdefault(report.nodeid, {})
        info = {"outcome": report.outcome}
        if hasattr(report, "wasxfail"):
            info["wasxfail"] = report.wasxfail
        if report.skipped and isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
            info["longrepr"] = [str(report.longrepr[0]), report.longrepr[1], str(report.longrepr[2])]
        p[report.when] = info
        for k, v in report.user_properties:
            if k == "detpy_fingerprint":
                self.fingerprints[report.nodeid] = v

    def _conftests(self):
        pm = self.config.pluginmanager
        n = len(getattr(pm, "_conftest_plugins", ()))
        if n == getattr(self, "_n_conftests", -1):
            return ()
        self._n_conftests = n
        return list(getattr(pm, "_conftest_plugins", ()))

    def _reuse(self, item, nextitem, receipt) -> None:
        from _pytest.reports import TestReport
        from _pytest.runner import CallInfo

        e = json.loads(self.store.entry(item.nodeid))
        rep = e.get("report") or {}
        ihook = item.ihook
        ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
        now = _now()
        kw = {k: 1 for k in item.keywords}
        props = [("detpy_cache", "reused"), ("detpy_cache_key", receipt["key"]),
                 ("detpy_fingerprint", e.get("fingerprint", ""))]
        reports = []
        for when in ("setup", "call"):
            p = rep.get(when)
            if p is None:
                continue
            lr = p.get("longrepr")
            r = TestReport(item.nodeid, item.location, kw, p["outcome"], tuple(lr) if lr else None, when,
                           (), 0.0, now, now, list(props))
            if "wasxfail" in p:
                r.wasxfail = p["wasxfail"]
            reports.append(r)
        for r in reports:
            ihook.pytest_runtest_logreport(report=r)
        call = CallInfo.from_call(lambda: item.session._setupstate.teardown_exact(nextitem), when="teardown")
        if call.excinfo is None:
            td = TestReport(item.nodeid, item.location, kw, "passed", None, "teardown", (), 0.0, now, now,
                            list(props))
        else:
            td = TestReport.from_item_and_call(item, call)
        ihook.pytest_runtest_logreport(report=td)
        ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)

    # -- end of session ------------------------------------------------------------
    def finish(self, session) -> None:
        from . import plugin as _plugin  # the fingerprints of the tests that ran (Level 0 recorder)

        for nid, fp in _plugin.S.fingerprints.items():
            if nid not in self.hits:
                self.fingerprints[nid] = fp
        cap = self.cap
        cap.switch("s")
        cap.stop()
        t0 = _perf()
        try:
            self._record_all()
        except Exception as e:  # never break the test session: nothing is recorded this time
            import traceback
            import warnings

            self.error = f"{type(e).__name__}: {e}"
            warnings.warn(f"detpy --det-cache: results not recorded: {self.error}\n{traceback.format_exc()}")
        finally:
            self.t_record = _perf() - t0
        self.compare_verified({n: _final(p) for n, p in self.parts.items()})
        self._write_receipts()

    def _facts_index(self, rel: str, cache: dict) -> int | None:
        """Store index of the facts of the current version of ``rel`` (computed once per file)."""
        if rel in cache:
            return cache[rel]
        p = os.path.join(self.root, rel)
        content = _core.file_digest(p)
        ix = None
        if content is not None:
            ix = self.store.file_index(rel, content)
            if ix is None:
                mod, is_pkg = _module_of(p)
                f = _codefacts.read_facts(p, content, mod, is_pkg)
                if f is not None:
                    ix = self.store.add_file(rel, content, f[0], f[1], f[2], f[3])
        cache[rel] = ix
        return ix

    def _record_all(self) -> None:
        cap, store = self.cap, self.store
        if cap.rec is None:
            return
        fcache: dict[str, int | None] = {}
        rels = cap.fnames
        # file facts for every executed or loaded repository file
        needed = set(rels) | {r for r, _ in cap.loaded_order} | cap.preloaded
        for rel in needed:
            self._facts_index(rel, fcache)
        ranges = []
        for rel in rels:
            ix = fcache.get(rel)
            if ix is None:
                ranges.append([])
            else:
                ranges.append([(a, b) for _, a, b, _ in store.file_facts(ix)[4]])
        per, imp = cap.rec.fold(len(cap.ctx_names), cap.segs, ranges)
        names = cap.ctx_names
        ctx_of = {n: i for i, n in enumerate(names)}

        def units_of(fids_units):
            out = set()
            for v in fids_units:
                fid, u = v >> 32, v & 0xFFFFFFFF
                ix = fcache.get(rels[fid])
                if ix is not None:
                    out.add((ix, u))
            return out

        def unparsable(fids):
            out = set()
            for fid in fids:
                ix = fcache.get(rels[fid])
                if ix is None or not store.file_facts(ix)[4]:
                    if ix is not None:
                        f = store.file_facts(ix)
                        if f[2] == f[1]:  # not Python: whole content
                            out.add(ix)
            return out

        conftests = {r for r in needed if r.rsplit("/", 1)[-1] == "conftest.py"}
        test_files = {_ctx_file(n) for n in self.items}
        # import graph: test modules imported by any loaded module are shared, others only serve their own tests
        imported_names = set()
        for rel in needed:
            ix = fcache.get(rel)
            if ix is not None:
                imported_names.update(store.file_facts(ix)[5])
        shared_test_files = set()
        for tf in test_files:
            mod, _ = _module_of(os.path.join(self.root, tf))
            if mod and (mod in imported_names or mod.rsplit(".", 1)[-1] in imported_names):
                shared_test_files.add(tf)

        # global contexts: startup, between tests, import time
        g_ctx = [ctx_of[c] for c in _GLOBAL_CTX if c in ctx_of]
        g_units = units_of(imp[0])
        g_unparsable = unparsable(imp[1])
        for c in g_ctx:
            g_units |= units_of(per[c][0])
            g_unparsable |= unparsable(per[c][1])
        g_ctx_all = g_ctx + [cap.import_ctx]
        g_data, g_env, g_flags = {}, set(), set()
        for c in g_ctx_all:
            g_data.update(cap.data.get(c, {}))
            g_env |= cap.env.get(c, set())
            g_flags |= {f for f in cap.flags.get(c, set()) if f != "proc"}

        pre_ix = {fcache[r] for r in cap.preloaded if fcache.get(r) is not None}
        names_of = cap.ctx_names
        session_written = {cap._key(p): sorted(names_of[c] for c in w) for p, w in cap.writers.items()
                           if _encodable(p)}
        written = {p: set(w) for p, w in store.written().items()}
        for p, w in session_written.items():
            written.setdefault(p, set()).update(w)
        # persisted for the next sessions: paths in the repository only (temporary files have fresh names)
        store.add_written({p: w for p, w in session_written.items() if not os.path.isabs(p)})
        # results reused in this session whose input files code of this session then wrote: drop them
        for nid in self.hits:
            if not session_written:
                break
            try:
                deps = json.loads(store.entry(nid)).get("data", [])
            except KeyError:
                continue
            own = {"t|" + nid}
            for path, _dep in deps:
                if path in session_written and not set(session_written[path]) <= own:
                    self.stale_hits[nid] = path
                    store.remove(nid)
                    break
        loaded_idx = cap.loaded_order  # (rel, index)
        cfg = _state.STATE.config
        file_of_ix = {}
        for rel, ix in fcache.items():
            if ix is not None:
                file_of_ix[ix] = rel

        def in_scope(rel: str, own: str) -> bool:
            if rel in test_files:
                return rel == own or rel in shared_test_files
            if rel in conftests:
                d = rel.rsplit("/", 1)[0] if "/" in rel else ""
                return d == "" or own == d or own.startswith(d + "/")
            return True

        for nid in self.ran:
            item = self.items.get(nid)
            if item is None:
                continue
            p = self.parts.get(nid, {})
            outcome = _final(p)
            if outcome not in ("passed", "skipped", "xfailed"):
                self._not_cached(nid, f"outcome {outcome}")
                continue
            own = _ctx_file(nid)
            ctxs = [ctx_of[c] for c in ["t|" + nid, "c|" + own, *self.fixture_ctx.get(nid, [])] if c in ctx_of]
            flags = set(g_flags)
            data = dict(g_data)
            env = set(g_env)
            units = set()
            content = set(pre_ix) | g_unparsable
            for c in ctxs:
                flags |= cap.flags.get(c, set())
                data.update(cap.data.get(c, {}))
                env |= cap.env.get(c, set())
                units |= units_of(per[c][0])
                content |= unparsable(per[c][1])
            why = _uncacheable(flags, cfg)
            if why is None:
                # writers credited to the test: its own contexts and the global ones (startup, between tests,
                # import time), whose code is an input of every test
                credited = set(ctxs) | set(g_ctx_all)
                names = {names_of[c] for c in credited}
                for f in sorted(flags):
                    if f.startswith("rw:") and not cap.writers.get(f[3:], set()) <= credited:
                        why = f"reads a file another test or fixture wrote: {cap._key(f[3:])}"
                        break
                if why is None:
                    for path in data:
                        w = written.get(path)
                        if w and not w <= names:
                            why = f"reads a file another test or fixture wrote: {path}"
                            break
            if why is None and "net-replay" in flags and cfg.cassette_path:
                d = _core.file_digest(cfg.cassette_path)
                data[cap._key(os.path.realpath(cfg.cassette_path))] = f"f:{d}" if d else "missing"
            if why:
                self._not_cached(nid, why)
                continue
            idx = self.test_index.get(nid, 0)
            skeleton, hooks = set(), set()
            for rel, seen_at in loaded_idx:
                if seen_at > idx:
                    continue
                ix = fcache.get(rel)
                if ix is None:
                    continue
                if rel in conftests:
                    hooks.add(ix)
                if in_scope(rel, own):
                    skeleton.add(ix)
            for ix, u in g_units:
                rel = file_of_ix.get(ix)
                # hooks run outside tests can act on any test; test modules serve their own tests
                if rel is not None and (rel in conftests or in_scope(rel, own)):
                    units.add((ix, u))
            if type(item).__name__ == "DoctestItem" or not hasattr(item, "obj"):
                ix = fcache.get(own)
                if ix is None:
                    ix = self._facts_index(own, fcache)
                if ix is not None:
                    content.add(ix)
            epoch = self.epoch if ("time" in flags and "time" in cfg.controls) else None
            if "time" in flags and "time" not in cfg.controls:
                self._not_cached(nid, "real clock")
                continue
            env_deps = []
            for name in sorted(n for n in env if _encodable(n)):
                if name == "*":
                    env_deps.append(("*", _core.env_all_digest(dict(cap.env0))))
                else:
                    env_deps.append((name, _core.env_value_digest(cap.env0.get(name))))  # env0 is sanitised
            report = {w: p[w] for w in ("setup", "call") if w in p}
            store.record(nid, outcome, json.dumps(report), self.fingerprints.get(nid, ""), self.dur.get(nid, 0.0),
                         self.run_id, self.config_digest, self.runtime_digest, epoch, env_deps,
                         sorted(data.items()), sorted(content), sorted(skeleton), sorted(hooks), sorted(units))
            self.recorded += 1
        store.save()

    def _not_cached(self, nid: str, why: str) -> None:
        self.not_cached[nid] = why
        self.store.remove(nid)

    def _write_receipts(self) -> None:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.receipts_path)), exist_ok=True)
            with open(self.receipts_path, "w") as fh:
                for nid, r in self.hits.items():
                    fh.write(json.dumps({"nodeid": nid, "reused": True, **r}) + "\n")
                for nid, why in self.misses.items():
                    fh.write(json.dumps({"nodeid": nid, "reused": False, "why": why}) + "\n")
        except OSError:
            pass

    # -- reporting --------------------------------------------------------------------
    def summary_data(self) -> dict:
        kinds: dict[str, int] = {}
        for why in self.misses.values():
            k = why.split(":", 1)[0]
            kinds[k] = kinds.get(k, 0) + 1
        nc: dict[str, int] = {}
        for why in self.not_cached.values():
            k = why.split(" ", 1)[0] if why.startswith("outcome") else why.split(":", 1)[0]
            nc[k] = nc.get(k, 0) + 1
        return {
            "reused": len(self.hits),
            "verified": len(self.verifying),
            "ran": len(self.ran),
            "recorded": self.recorded,
            "miss_reasons": kinds,
            "not_cached": nc,
            "reused_recorded_seconds": round(sum(self._entry_duration(n) for n in self.hits), 3),
            "check_seconds": round(self.t_check, 3),
            "record_seconds": round(self.t_record, 3),
            "config": self.config_digest,
            "runtime": self.runtime_digest,
            "verify_mismatches": [v for v in self.verify_results if not v["same"]],
            "stale_reuses": self.stale_hits,
            "error": self.error,
            "receipts": self.receipts_path,
        }

    def _entry_duration(self, nid: str) -> float:
        return float(self.hits[nid].get("duration", 0.0) or 0.0)

    def compare_verified(self, outcomes: dict) -> None:
        for nid, r in self.verifying.items():
            o = outcomes.get(nid)
            fp = self.fingerprints.get(nid)
            self.verify_results.append({"nodeid": nid, "cached": r["outcome"], "fresh": o,
                                        "same": o == r["outcome"], "same_fingerprint": fp == r["fingerprint"]})

    def terminal_summary(self, tr) -> None:
        s = self.summary_data()
        tr.section("detpy cache with proof")
        tr.write_line(f"reused {s['reused']} result(s) with proof, ran {s['ran']}, recorded {s['recorded']} "
                      f"(check {s['check_seconds']}s, record {s['record_seconds']}s); config {s['config']}, "
                      f"runtime {s['runtime']}")
        if s["miss_reasons"]:
            tr.write_line("not reused: " + ", ".join(f"{k} {v}" for k, v in sorted(s["miss_reasons"].items())))
        if s["not_cached"]:
            tr.write_line("not cacheable: " + ", ".join(f"{k} {v}" for k, v in sorted(s["not_cached"].items())))
        for nid, path in self.stale_hits.items():
            tr.write_line(f"WARNING reused {nid}, but this session then wrote its input {path}: entry dropped",
                          yellow=True)
        if self.verify_results:
            bad = s["verify_mismatches"]
            tr.write_line(f"verified {len(self.verify_results)} reusable result(s) by running them: "
                          f"{len(bad)} mismatch(es)", red=bool(bad))
            for b in bad:
                tr.write_line(f"  MISMATCH {b['nodeid']}: cached {b['cached']}, fresh {b['fresh']}", red=True)
        if tr.config.option.verbose > 0:
            for nid, r in self.hits.items():
                tr.write_line(f"REUSED {nid} key={r['key']} run={r['run']} outcome={r['outcome']}: checked "
                              f"{r['n_units']} functions, {r['n_skeleton']} modules, {r['n_hooks']} conftest hook "
                              f"sets, {r['n_content']} whole files, {r['n_data']} data paths, {r['n_env']} env "
                              f"vars; runtime {r['runtime']}, config {r['config']}"
                              f"{'' if r['epoch'] is None else ', epoch ' + str(r['epoch'])}")
        tr.write_line(f"receipts: {s['receipts']}")


def _final(parts: dict) -> str:
    setup, call, teardown = parts.get("setup"), parts.get("call"), parts.get("teardown")
    so = setup and setup["outcome"]
    if so and so != "passed":
        if so == "skipped":
            return "xfailed" if "wasxfail" in setup else "skipped"
        return "error"
    if call is None:
        return "unknown"
    co = call["outcome"]
    if teardown and teardown["outcome"] == "failed":
        return "error"
    if co == "skipped" and "wasxfail" in call:
        return "xfailed"
    if co == "passed" and "wasxfail" in call:
        return "xpassed"
    return co


def _safe(s: str) -> str:
    """``s`` as valid UTF-8 text (undecodable bytes of environment strings escaped)."""
    return s if _encodable(s) else s.encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")


def _encodable(s: str) -> bool:
    try:
        s.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def _uncacheable(flags: set, cfg) -> str | None:
    if "badpath" in flags:
        return "reads a path that is not valid UTF-8"
    if "spawn" in flags:
        return "subprocess"
    if "connect" in flags:
        return "network connection"
    if "net-record" in flags:
        return "network recording (--det-record)"
    if "entropy" in flags and not cfg.control_urandom:
        return "os entropy (not controlled; use --det-urandom)"
    if "proc" in flags:
        return "reads /proc, /sys or /dev"
    return None


_MODMAP: dict = {}
_MODMAP_N = [-1]


def _module_of(path: str) -> tuple[str | None, bool]:
    """Module name of a file (from ``sys.modules``) and whether it is a package ``__init__``."""
    if _MODMAP_N[0] != len(sys.modules):
        _MODMAP.clear()
        for name, m in list(sys.modules.items()):
            f = getattr(m, "__file__", None)
            if isinstance(f, str):
                try:
                    _MODMAP.setdefault(os.path.realpath(f), name)
                except (OSError, ValueError):
                    pass
        _MODMAP_N[0] = len(sys.modules)
    p = os.path.realpath(path)
    return _MODMAP.get(p), os.path.basename(p) == "__init__.py"


# ---------------------------------------------------------------------------
CAPTURE: Capture | None = None
PLUGIN: ProofCachePlugin | None = None


def start(early_config, ns) -> None:
    """Start recording (from ``pytest_load_initial_conftests``, before conftests are imported)."""
    global CAPTURE, _ENV_CAPTURE
    if not AVAILABLE:
        raise pytest.UsageError("--det-cache needs Python 3.12+ (sys.monitoring)")
    if CAPTURE is not None and CAPTURE.active:
        return  # nested in-process session: the outer one records
    root = str(early_config.rootpath)
    # detpy's own variables (set by its re-exec, e.g. the precompile time) are configuration, not inputs
    env0 = {_safe(k): _safe(v) for k, v in os.environ.items() if not k.startswith("DETPY_")}
    cap = Capture(root, env0)
    CAPTURE = cap
    _ENV_CAPTURE = cap
    _patch_environ()
    _state.set_event_listener(cap.event)
    cap.start()


def install(config) -> None:
    """Register the plugin hooks (from ``pytest_configure``)."""
    global PLUGIN
    cap = CAPTURE
    if cap is None or PLUGIN is not None:
        return
    opt = config.option
    plugin = ProofCachePlugin(cap, opt.det_cache, opt.det_cache_verify, opt.det_cache_receipts)
    plugin.configure(config)
    PLUGIN = plugin
    config.pluginmanager.register(plugin, "detpy-cache")
    config.pluginmanager.register(_ProtocolWrapper(plugin), "detpy-cache-wrapper")
    cap.switch("s")


def uninstall() -> None:
    global CAPTURE, PLUGIN, _ENV_CAPTURE
    if CAPTURE is not None:
        CAPTURE.stop()
    _state.set_event_listener(None)
    CAPTURE = None
    PLUGIN = None
    _ENV_CAPTURE = None


class _ProtocolWrapper:
    def __init__(self, plugin):
        self.plugin = plugin

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item, nextitem):
        gen = self.plugin._wrap_protocol(item, nextitem)
        next(gen)
        try:
            yield
        finally:
            try:
                next(gen)
            except StopIteration:
                pass
