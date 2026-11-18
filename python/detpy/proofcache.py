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
from types import FunctionType

import pytest

from . import __version__, _codefacts, _core, _sites, _state, follow

# bound once: a test may remove sys._getframe (attrs' test_missing_sys_getframe) while detpy's hooks run
_getframe = sys._getframe
# real clocks, bound before Level 0 virtualises the time module
_perf = time.perf_counter
_now = time.time
_mon = getattr(sys, "monitoring", None)
AVAILABLE = _mon is not None

# context names: "" startup, "s" between tests, "c|<file>" collection of a file,
# "f|<scope>|<baseid>|<name>" setup of a wider-scoped fixture, "t|<nodeid>" a test
_GLOBAL_CTX = ("", "s")

_AUDIT_EVENTS = ("exec", "open", "sqlite3.connect", "os.listdir", "os.scandir", "socket.connect", "socket.sendto", "socket.sendmsg",
                 "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "subprocess.Popen", "os.posix_spawn",
                 "os.exec", "os.system", "os.fork", "os.forkpty", "os.spawn", "os.remove", "os.rename", "os.mkdir",
                 "os.rmdir", "os.truncate", "shutil.rmtree", "shutil.copyfile", "shutil.move", "os.symlink",
                 "os.link")
_SPAWN = {"subprocess.Popen", "os.posix_spawn", "os.exec", "os.system", "os.fork", "os.forkpty", "os.spawn"}
_WRITE_EVENTS = {"os.remove": (0,), "os.rename": (0, 1), "os.mkdir": (0,), "os.rmdir": (0,),
                 "shutil.rmtree": (0,), "shutil.copyfile": (1,), "shutil.move": (0, 1), "os.symlink": (1,),
                 "os.link": (1,), "os.truncate": (0,)}
_SKIP_PARTS = (os.sep + "__pycache__" + os.sep, os.sep + ".git" + os.sep, os.sep + ".pytest_cache",
               os.sep + ".mypy_cache", os.sep + ".hypothesis" + os.sep, os.sep + ".detpy" + os.sep)
# data reads: the same, except .git/ (review R-009 F5: a test that reads HEAD and its ref in-process depends on
# them; objects are content-addressed, so a changed commit always comes with a changed ref file)
_SKIP_DATA = tuple(x for x in _SKIP_PARTS if x != os.sep + ".git" + os.sep)
_O_ACC = os.O_RDONLY | os.O_WRONLY | os.O_RDWR
_O_TMPFILE = getattr(os, "O_TMPFILE", 0)
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
    "continue_on_collection_errors", "numprocesses", "dist", "tx", "det_epoch", "det_cache_max_age",
    "det_cache_epoch_window",
}


# detpy's own bookkeeping variables (re-exec, bytecode cache): set by detpy itself, never a test input
_DETPY_OWN_ENV = frozenset({"DETPY_REEXEC", "DETPY_PRECOMPILE_S", "DETPY_PYC_CACHE", "DETPY_BLOCKED_PLUGINS"})
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


def rep_line(code) -> int | None:
    """Code-object level capture: the line that stands for every line of a plain function, its last one. A
    unit's range starts at its first body statement's ``lineno``, after the decorators of a decorated first
    statement (whose lines the function runs first), and ends at its last line: the last line of a function
    (the last statement's, or its implicit return) is inside its unit's range."""
    co = code.co_code
    r = 0
    while r < len(co) and co[r] in _PRELUDE:
        r += 2
    if r >= len(co) or co[r] != _RESUME:
        return None
    lines = [line for start, _end, line in code.co_lines() if start > r and line is not None]
    return max(lines) if lines else None


# Line capture granularity (experiment, DETPY_CACHE_LINES): "line" (default) arms every code object with LINE;
# "code" arms plain functions (not module or class bodies, not generators or coroutines) with PY_START only and
# records one location per start (rep_line), see REPORT-2.
_CODE_LEVEL = os.environ.get("DETPY_CACHE_LINES", "line") == "code"
_CO_PLAIN_EXCLUDE = 0x20 | 0x80 | 0x100 | 0x200  # CO_GENERATOR | CO_COROUTINE | CO_ITERABLE_COROUTINE | CO_ASYNC_GENERATOR
_CO_OPTIMIZED = 0x1


# ---------------------------------------------------------------------------
class Capture(_core.CaptureCore):
    """Records, per context, executed code, data reads, environment reads and events.

    The capture itself is Rust (``_core.CaptureCore``, ``crates/detpy-py/src/capture.rs``): the audit hook, reads
    and writes, contexts and switches, environment reads, Level 0 events, the arming of code objects. This class
    keeps what is interface: ``sys.monitoring`` and audit-hook registration, the ``sqlite3.connect`` patch and the
    child follower's crediting. The Python original is ``tests/rust_hotpaths_ref/_ref_proofcache.py``.
    """

    def __new__(cls, root: str, env0: dict, hot: int = 16):
        return super().__new__(cls, os.path.realpath(root), env0, hot, _DETPY_DIR, _RESUME, sorted(_PRELUDE),
                               _CODE_LEVEL, (os.O_RDONLY, os.O_WRONLY, os.O_RDWR, os.O_CREAT, os.O_EXCL, os.O_TRUNC,
                                             _O_TMPFILE))

    def __init__(self, root: str, env0: dict, hot: int = 16):
        self.hot = hot
        self.follower: follow.Follower | None = None
        self._sqlite_saved: list = []

    # -- start and stop -----------------------------------------------------------------
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
        lst = _state._event_listener  # the object the Rust event path calls (a bound method is made per access)
        _core.l0_listener_memo(lst if lst is not None and lst == self.event else None, self.rec)
        _mon.register_callback(self.tool, _mon.events.LINE, self.rec.line)
        _mon.register_callback(self.tool, _mon.events.PY_START, self.rec.start)
        _mon.register_callback(self.tool, _mon.events.PY_RETURN, self.rec.ret)
        self.active = True
        _core.set_audit_hook(self.audit, _AUDIT_EVENTS)
        self._patch_sqlite()
        # code that exists before the start: modules already loaded become whole-content inputs
        pre = False
        for m in list(sys.modules.values()):
            f = getattr(m, "__file__", None)
            if f and self.note_preloaded(f):
                pre = True
        if pre:
            import gc

            for o in gc.get_objects():
                if type(o) is FunctionType:
                    self.arm(o.__code__)
        f = _getframe()
        while f is not None:
            self.arm(f.f_code)
            f = f.f_back

    def stop(self) -> None:
        if not self.active:
            return
        self.active = False
        _core.l0_listener_memo(None)
        _core.set_audit_hook(None, ())
        for obj, name, v in getattr(self, "_sqlite_saved", ()):
            setattr(obj, name, v)
        self._sqlite_saved = []
        if self.tool is not None:
            for ev in (_mon.events.LINE, _mon.events.PY_START, _mon.events.PY_RETURN):
                _mon.register_callback(self.tool, ev, None)
            _mon.set_events(self.tool, 0)
            _mon.free_tool_id(self.tool)
            self.tool = None

    # -- sqlite ----------------------------------------------------------------------------
    def _patch_sqlite(self) -> None:
        """review R-009 F4: sqlite evaluates 'now' (date('now'), CURRENT_TIMESTAMP, date() without a time value) on
        the real clock in C. Every connection made through sqlite3.connect traces its statements; one that may read
        the real clock makes its context uncacheable. (A trace callback the test sets itself replaces this one.)"""
        try:
            import sqlite3
            import sqlite3.dbapi2 as dbapi2
        except ImportError:
            return
        real = sqlite3.connect
        cap = self

        def connect(*args, **kwargs):
            conn = real(*args, **kwargs)
            try:
                conn.set_trace_callback(cap._sql_trace)
            except Exception:
                pass
            return conn

        connect.__wrapped__ = real
        self._sqlite_saved = [(sqlite3, "connect", real), (dbapi2, "connect", dbapi2.connect)]
        sqlite3.connect = connect
        dbapi2.connect = connect

    def _sql_trace(self, statement) -> None:
        if self.active and isinstance(statement, str) and _SQL_REAL_CLOCK.search(statement):
            self.flag(self._cur(), "rclock", f"sqlite: {statement.strip()[:80]} at {_first_user_site()}")

    def child_ignored(self, p: str) -> bool:
        """Paths a followed child touches that are not inputs: bytecode caches (their source is probed), pytest's
        temporary directory, this interpreter's standard library and installed distributions (runtime identity)."""
        if os.sep + "__pycache__" + os.sep in p:
            return True
        if self.basetemp and (p == self.basetemp or p.startswith(self.basetemp + os.sep)):
            return True
        if self.follower is not None and p.startswith(self.follower.logdir):
            return True
        for d in self.site_dirs:
            if p.startswith(d):
                return not any(p.startswith(x) for x in self.dist_info_ok)
        return any(p.startswith(d) for d in self.stdlib_dirs) or p == os.devnull

    def child_read(self, ctx: int, p: str, kind: str = "f") -> None:
        if not self.child_ignored(p):
            self.read(ctx, p, kind)

    def collect_children(self) -> None:
        """Turn the strace logs of the followed children into inputs (or refusals) of the contexts that started them."""
        fo = self.follower
        if fo is None:
            return
        _mono = follow._mono

        # a log is complete once the detached tracer wrote its process's exit, normally within milliseconds of the
        # exit; a process still running (a daemon, multiprocessing's resource tracker) never completes: wait for it
        # once, briefly, then not at all
        budget_end = _mono() + 3.0
        wait = 1.0
        # a log is written only by its tracer: one whose tracer is gone is final now, so waiting for it cannot
        # change it. It is not waited for, but the wait is charged to the budget as if it had been (the decisions
        # about the other children stay those of waiting). None: unknown, every log is waited for.
        try:
            alive = _core.tracer_prefixes(fo.logdir + os.sep)
        except Exception:
            alive = None
        alive = None if alive is None else set(alive)
        for sp in fo.spawns:
            self.children += 1
            timeout = max(0.0, min(wait, budget_end - _mono()))
            if alive is None or sp.prefix in alive:
                logs = follow._wait_logs(sp.prefix, timeout)
            else:
                logs = follow._wait_logs(sp.prefix, 0.0)
                if not (logs and all(follow._complete(f) for f in logs)):
                    budget_end -= timeout
            if logs and not all(follow._complete(f) for f in logs):
                wait = 0.05
            ctx = sp.ctx
            if not logs:
                self.flag(ctx, "spawn", f"{sp.detail} [not followed: no trace log]")
                continue
            res = follow.parse(logs, sp.cwd)
            for f in logs:
                try:
                    os.unlink(f)
                except OSError:
                    pass
            # review R-009 F1: a process kept alive across contexts (a persistent shell, a language server, a pool
            # held in a module global) works for whichever test talks to it; that test raises no event. Every test,
            # fixture or collection context that ran during the tree's lifetime (strace -ttt, real clock) gets the
            # tree's inputs and refusals, as the context that started it does.
            t1 = float("inf") if res.bad and "still running" in res.bad else res.t1
            targets = [ctx] + sorted(self._contexts_during(res.t0, t1) - {ctx})
            for c in targets:
                self._credit_child(c, sp, res)
        try:
            os.rmdir(fo.logdir)
        except OSError:
            pass

    def _credit_child(self, ctx: int, sp, res) -> None:
        """The inputs, writes and refusals of one followed process tree, as inputs of context ``ctx``."""
        if res.bad:
            self.flag(ctx, "spawn", f"{sp.detail} [not followed: {res.bad}]")
        if res.net:
            self.flag(ctx, "spawn", f"{sp.detail} [network: {res.net}]")
        if res.clock and not sp.clock_exempt:
            # review R-009 F4: the clock shim turned a real-time read into a system call
            self.flag(ctx, "spawn", f"{sp.detail} [{res.clock}]")
        if res.unshimmed:
            self.flag(ctx, "spawn", f"{sp.detail} [clock not observable: {res.unshimmed} ran without the clock shim]")
        self.child_entropy += res.entropy
        self.child_read(ctx, sp.exe)
        own = set()
        for op, p in res.ops:
            sk = follow.special(p, res.pids)
            if sk == "skip":
                continue
            if sk == "entropy":
                self.child_entropy += 1
                continue
            if sk == "proc":
                if op == "d" or (op != "w" and not os.path.exists(p)):
                    self.read(ctx, p, "d" if op == "d" else "f")  # a listing or a missing path: an input
                else:
                    self.flag(ctx, "spawn", f"{sp.detail} [reads {p}]")
                continue
            if op == "w":
                own.add(p)
                if not self.child_ignored(p):
                    self.wrote(ctx, p)
                continue
            if p in own:
                continue  # the tree wrote it first: internal
            if op == "x":
                interp = follow.shebang(p)
                if interp:
                    self.child_read(ctx, interp)
            self.child_read(ctx, p, "d" if op == "d" else "f")



# ---------------------------------------------------------------------------
# environment reads: the recorded os.environ calls _note_env (Rust: CaptureCore.note_env of the capture set by
# _core.cap_set_env_capture)
_ENV_PATCHED = False
_note_env = _core.cap_note_env


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
def _stat_key(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino]


def _dist_infos(root: str, memo_path: str | None = None):
    """(runtime digest part for installed distributions, dist-info dirs of editable installs of the project).

    Reading every distribution's metadata and RECORD takes seconds where thousands are installed: each one's
    result is memoised in ``memo_path`` under the size, mtime, ctime and inode of its metadata files (an installer
    rewrites them, which changes the ctime), so an unchanged environment is not read again.
    """
    from importlib import metadata

    memo: dict = {}
    if memo_path:
        try:
            with open(memo_path) as fh:
                memo = json.load(fh)
        except (OSError, ValueError):
            memo = {}
    fresh: dict = {}
    parts, editable = [], []
    root_sep = os.path.realpath(root) + os.sep
    for d in metadata.distributions():
        path = getattr(d, "_path", None)
        key = None
        if path is not None:
            base = os.path.realpath(str(path))
            key = json.dumps([base, root_sep] + [_stat_key(os.path.join(base, f)) for f in (
                "METADATA", "PKG-INFO", "RECORD", "direct_url.json")])
        hit = memo.get(key) if key is not None else None
        if hit is None:
            # name, version and RECORD digest read in Rust where the plain reading is certain to match
            # importlib.metadata's (simple header block); else importlib.metadata itself
            fast = _core.dist_identity(path) if type(d) is metadata.PathDistribution and path is not None else None
            if fast is not None:
                name = fast[0]
            else:
                name = (d.metadata.get("Name") or "?") if d.metadata is not None else "?"
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
                hit = ["project", os.path.realpath(str(path)) + os.sep if path is not None else None]
            elif fast is not None:
                hit = ["dist", f"{name.lower()}=={fast[1]}:{fast[2]}"]
            else:
                try:
                    rec = d.read_text("RECORD") or ""
                except Exception:
                    rec = ""
                hit = ["dist", f"{name.lower()}=={d.version}:{_core.digest(rec.encode())}"]
        if key is not None:
            fresh[key] = hit
        if hit[0] == "project":
            if hit[1] is not None:
                editable.append(hit[1])
        else:
            parts.append(hit[1])
    if memo_path and fresh != memo:
        try:
            tmp = f"{memo_path}.{os.getpid()}.tmp"
            with open(tmp, "w") as fh:
                json.dump(fresh, fh)
            os.replace(tmp, memo_path)
        except OSError:
            pass
    return sorted(parts), editable


def runtime_identity(root: str, memo_path: str | None = None) -> tuple[str, dict, list]:
    import sysconfig

    exe = os.path.realpath(sys.executable)
    lib = None
    libdir, ldlib = sysconfig.get_config_var("LIBDIR"), sysconfig.get_config_var("LDLIBRARY")
    if libdir and ldlib and os.path.exists(os.path.join(libdir, ldlib)):
        lib = os.path.join(libdir, ldlib)
    dists, editable = _dist_infos(root, memo_path)
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


_LOCALE_VARS = ("TZ", "TZDIR", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_NUMERIC", "LC_TIME", "LC_COLLATE",
                "LC_MONETARY", "LC_MESSAGES", "LC_PAPER", "LC_NAME", "LC_ADDRESS", "LC_TELEPHONE",
                "LC_MEASUREMENT", "LC_IDENTIFICATION")


def tz_locale_identity() -> dict:
    """Time zone and locale as C sees them: the variables, /etc/localtime's content and the zone file TZ names."""
    env = dict(os.environ._data) if hasattr(os.environ, "_data") else dict(os.environ)  # noqa: SLF001 (no event)
    dec = {os.fsdecode(k) if isinstance(k, bytes) else k: os.fsdecode(v) if isinstance(v, bytes) else v
           for k, v in env.items()}
    d = {k: dec.get(k) for k in _LOCALE_VARS}
    d["/etc/localtime"] = _core.file_digest("/etc/localtime")
    tz = dec.get("TZ")
    if tz:
        name = tz[1:] if tz.startswith(":") else tz
        zdir = dec.get("TZDIR") or "/usr/share/zoneinfo"
        path = name if os.path.isabs(name) else os.path.join(zdir, name)
        d["tzfile"] = _core.file_digest(path) if os.path.isfile(path) else None
    return d


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
        # review R-009 F3: the time zone and locale are read by C (getenv, tzset, /etc/localtime), never through
        # os.environ: they are configuration of every test
        "tz_locale": tz_locale_identity(),
    }
    return _core.digest(json.dumps(d, sort_keys=True, default=str).encode()), d


# ---------------------------------------------------------------------------
class ProofCachePlugin:
    """pytest hooks of ``--det-cache``."""

    def __init__(self, cap: Capture, cache_dir: str, verify: float, receipts: str | None):
        self.cap = cap
        self.dir = os.path.abspath(cache_dir)
        self.verify = verify
        self.max_age_s: float | None = None
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
        self.not_cached_where: dict[str, str] = {}  # nodeid -> first occurrence of the cause (what, where, context)
        self.stale_hits: dict[str, str] = {}
        self.error: str | None = None
        self.phases: dict[str, float] = {}  # seconds per phase of the end-of-session recording

    # -- setup ----------------------------------------------------------------
    def configure(self, config) -> None:
        self.config = config
        self.root = os.path.realpath(str(config.rootpath))
        self.config_digest, self.config_info = config_identity(config)
        os.makedirs(self.dir, exist_ok=True)
        self.runtime_digest, self.runtime_info, editable = runtime_identity(
            self.root, os.path.join(self.dir, "distributions.json"))
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
        changed = list(store.changed_code_files())
        jobs = []
        for path, content in changed:
            mod, is_pkg = _module_of(os.path.join(self.root, path))
            jobs.append((os.path.join(self.root, path), content, mod, is_pkg))
        cap, was = self.cap, self.cap.active
        cap.active = False  # detpy's own reads and workers are not inputs of any test
        try:
            facts = _codefacts.read_many(jobs, os.path.join(self.dir, "tmp"))
        finally:
            cap.active = was
        for (path, content), f in zip(changed, facts):
            if f is not None:
                store.set_fresh(path, content, f[0], f[1], f[2], f[3])
        rng = random.Random(f"detpy-cache-verify:{self.run_id}")
        for i, item in enumerate(items):
            nid = item.nodeid
            self.items[nid] = item
            self.test_index[nid] = i
            ok, info = store.check(nid)
            if ok and self.max_age_s is not None:
                # review R-009 F4: real-clock reads outside the virtual clock that detpy cannot see (C code such as
                # OpenSSL's certificate validity) are bounded: an entry older than --det-cache-max-age (real time)
                # is not reused
                age = _now() - _run_time(json.loads(info).get("run", ""))
                if age > self.max_age_s:
                    ok, info = False, f"expired: recorded {age / 86400:.1f} days ago (--det-cache-max-age)"
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

    def _prefetch_facts(self, rels, cache: dict) -> None:
        """Facts of every file in ``rels`` whose current version the store does not have yet, computed together."""
        jobs, meta = [], []
        for rel in rels:
            if rel in cache:
                continue
            p = os.path.join(self.root, rel)
            content = _core.file_digest(p)
            if content is None:
                cache[rel] = None
                continue
            ix = self.store.file_index(rel, content)
            if ix is not None:
                cache[rel] = ix
                continue
            mod, is_pkg = _module_of(p)
            jobs.append((p, content, mod, is_pkg))
            meta.append((rel, content))
        if not jobs:
            return
        for (rel, content), f in zip(meta, _codefacts.read_many(jobs, os.path.join(self.dir, "tmp"))):
            cache[rel] = None if f is None else self.store.add_file(rel, content, f[0], f[1], f[2], f[3])

    def _record_all(self) -> None:
        if self.cap.rec is None:
            return
        t = _perf()
        self.cap.collect_children()
        self.phases["children"] = _perf() - t
        self._record_captured()

    def _record_captured(self) -> None:
        """Record every test that ran from the capture: the per-test assembly of inputs and the reasons a test is
        not cached are computed in Rust (``detpy_core::record``) from one plan of plain data."""
        store, ph = self.store, self.phases
        t = _perf()
        plan = json.dumps(self._plan())
        ph["plan"] = _perf() - t - ph.get("facts", 0.0)
        t = _perf()
        recorded, not_cached, stale, g_ctx_all = store.record_session(plan)
        ph["assemble"] = _perf() - t
        for nid, path in stale:
            self.stale_hits[nid] = path
        for nid, why, ctxs in not_cached:
            if ctxs:
                self.not_cached_where[nid] = self._where(why, ctxs)
            self.not_cached[nid] = why
        self.recorded += recorded
        t = _perf()
        store.save()
        ph["save"] = _perf() - t

    def _plan(self) -> dict:
        """The session's capture as plain data (``detpy_core::record::Plan``)."""
        cap, store = self.cap, self.store
        fcache: dict[str, int | None] = {}
        rels = cap.fnames
        # file facts for every executed or loaded repository file (new versions parsed in parallel)
        needed = set(rels) | {r for r, _ in cap.loaded_order} | cap.preloaded
        t = _perf()
        self._prefetch_facts(sorted(needed), fcache)
        for rel in needed:
            self._facts_index(rel, fcache)
        self.phases["facts"] = _perf() - t
        per, imp = cap.rec.fold(len(cap.ctx_names), cap.segs, store.unit_ranges([fcache.get(r) for r in rels]))
        tests, test_modules = [], {}
        for nid in self.items:
            tf = _ctx_file(nid)
            if tf not in test_modules:
                test_modules[tf] = _module_of(os.path.join(self.root, tf))[0]
        for nid in self.ran:
            item = self.items.get(nid)
            if item is None:
                continue
            p = self.parts.get(nid, {})
            whole = type(item).__name__ == "DoctestItem" or not hasattr(item, "obj")
            if whole:
                own = _ctx_file(nid)
                if fcache.get(own) is None:
                    self._facts_index(own, fcache)
            tests.append({"nodeid": nid, "outcome": _final(p), "report": {w: p[w] for w in ("setup", "call") if w in p},
                          "fingerprint": self.fingerprints.get(nid, ""), "duration": self.dur.get(nid, 0.0),
                          "index": self.test_index.get(nid, 0), "fixtures": self.fixture_ctx.get(nid, []),
                          "whole": whole})
        cfg = _state.STATE.config
        cassette = None
        if cfg.cassette_path:
            d = _core.file_digest(cfg.cassette_path)
            cassette = (cap._key(os.path.realpath(cfg.cassette_path)), f"f:{d}" if d else "missing")
        names = cap.ctx_names
        return {
            "ctx_names": names, "import_ctx": cap.import_ctx, "fnames": rels,
            "file_ix": {r: ix for r, ix in fcache.items() if ix is not None},
            "per": per, "imp": imp,
            "data": {c: list(d.items()) for c, d in cap.data.items()},
            "env": {c: [n for n in e if _encodable(n)] for c, e in cap.env.items()},
            "flags": {c: sorted(f) for c, f in cap.flags.items()},
            "writers": {p: sorted(w) for p, w in cap.writers.items() if _encodable(p)},
            "session_written": {cap._key(p): sorted(names[c] for c in w) for p, w in cap.writers.items()
                                if _encodable(p)},
            "loaded_order": cap.loaded_order, "preloaded": sorted(cap.preloaded), "needed": sorted(needed),
            "changed": cap.changed_code(),
            "test_modules": test_modules, "tests": tests, "hits": list(self.hits),
            "root_sep": cap.root_sep, "control_urandom": bool(cfg.control_urandom),
            "time_controlled": "time" in cfg.controls, "epoch": self.epoch, "cassette": cassette,
            "env0": dict(cap.env0), "config": self.config_digest, "runtime": self.runtime_digest, "run": self.run_id,
        }

    def _where(self, why: str, ctxs) -> str:
        """``why`` with the first occurrence of its cause: what (command, address...) and in which context."""
        flag = _FLAG_OF.get(why)
        if flag is None:
            return why
        for c in ctxs:
            d = self.cap.why.get((c, flag))
            if d is not None:
                return f"{d} ({_ctx_label(self.cap.ctx_names[c])})"
        return ""

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
        detail: dict[str, int] = {}
        for nid, why in self.not_cached.items():
            k = why.split(" ", 1)[0] if why.startswith("outcome") else why.split(":", 1)[0]
            nc[k] = nc.get(k, 0) + 1
            if not why.startswith("outcome"):
                w = self.not_cached_where.get(nid)
                full = f"{why}: {w}" if w else why
                detail[full] = detail.get(full, 0) + 1
        top = dict(sorted(detail.items(), key=lambda kv: (-kv[1], kv[0]))[:40])
        return {
            "reused": len(self.hits),
            "verified": len(self.verifying),
            "ran": len(self.ran),
            "recorded": self.recorded,
            "miss_reasons": kinds,
            "not_cached": nc,
            "not_cached_detail": top,
            "children": self.cap.children,
            "children_not_followed": (self.cap.follower.why_not if self.cap.follower is not None else None),
            "child_entropy_draws": self.cap.child_entropy,
            "reused_recorded_seconds": round(sum(self._entry_duration(n) for n in self.hits), 3),
            "check_seconds": round(self.t_check, 3),
            "record_seconds": round(self.t_record, 3),
            "phase_seconds": {k: round(v, 3) for k, v in self.phases.items()},
            "config": self.config_digest,
            "runtime": self.runtime_digest,
            "epoch_ns": self.epoch,
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


def _run_time(run: str) -> float:
    """Real time (seconds) of a run id ``YYYYmmddTHHMMSS-pid``; 0 when unreadable (then the entry has expired)."""
    import calendar

    try:
        return float(calendar.timegm(time.strptime(run.split("-", 1)[0], "%Y%m%dT%H%M%S")))
    except (ValueError, IndexError):
        return 0.0


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


_LD_SO_CACHE = "/etc/ld.so.cache"


_CTYPES_UTIL = os.sep + os.path.join("ctypes", "util.py")
_UUID_PY = os.sep + "uuid.py"


def _called_from(suffix: str) -> bool:
    """Whether a frame of the running call stack is in a standard-library file ending with ``suffix``."""
    f = _getframe(2)
    while f is not None:
        fn = f.f_code.co_filename
        if fn.endswith(suffix) and _sites._classify(fn)[0] != _sites._USER:
            return True
        f = f.f_back
    return False


def _is_find_library_ldconfig(args) -> bool:
    """``subprocess.Popen(['/sbin/ldconfig', '-p'])`` called by ``ctypes.util.find_library``."""
    try:
        argv = list(args[1]) if len(args) > 1 and not isinstance(args[1], (str, bytes)) else None
    except TypeError:
        return False
    if not argv or len(argv) != 2 or os.path.basename(os.fsdecode(argv[0])) != "ldconfig" or argv[1] != "-p":
        return False
    f = _getframe(2)
    while f is not None:
        fn = f.f_code.co_filename
        if fn.endswith(os.sep + os.path.join("ctypes", "util.py")):
            return True
        f = f.f_back
    return False


import re as _re  # noqa: E402

# sqlite reads the real clock for 'now', CURRENT_TIMESTAMP/DATE/TIME and the date functions called without a time
# value (date(), datetime(), time(), julianday(), unixepoch(), strftime(format))
_SQL_REAL_CLOCK = _re.compile(
    r"""'now'|"now"|\bcurrent_(timestamp|date|time)\b|\b(date|time|datetime|julianday|unixepoch)\s*\(\s*\)"""
    r"""|\bstrftime\s*\(\s*('[^']*'|"[^"]*")\s*\)""", _re.I)


def _numeric_host(host: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        return True
    except ValueError:
        return False


_FLAG_OF = {"real clock read outside the virtual clock": "rclock", "subprocess": "spawn", "network connection": "connect", "host name lookup": "dns",
            "network socket opened outside Python (C extension)": "csock", "reads /proc, /sys or /dev": "proc"}


def _ctx_label(name: str) -> str:
    if name == "":
        return "startup"
    if name == "s":
        return "between tests"
    if name == "i":
        return "import time"
    kind, _, rest = name.partition("|")
    if kind == "i":
        return "import of " + rest
    if kind == "c":
        return "collection of " + rest
    if kind == "f":
        return "fixture " + rest.rsplit("|", 1)[-1]
    return "test"


def _first_user_site() -> str:
    """``file:line`` of the innermost frame outside detpy and the standard library (else the innermost one)."""
    try:
        f = _getframe(1)
    except ValueError:
        return "?"
    first = None
    while f is not None:
        fn = f.f_code.co_filename
        if not fn.startswith(_DETPY_DIR):
            kind, norm = _sites._classify(fn)
            if first is None:
                first = f"{norm}:{f.f_lineno}"
            if kind == _sites._USER:
                return f"{norm}:{f.f_lineno}"
        f = f.f_back
    return first or "?"


def _spawn_detail(event: str, args) -> str:
    """The program a spawn event starts and where it was called from."""
    prog = None
    try:
        if event == "subprocess.Popen":
            prog = args[0] if args[0] is not None else (args[1] if isinstance(args[1], (str, bytes)) else list(args[1])[0])
        elif event == "os.system":
            prog = os.fsdecode(args[0]).split()[0]
        elif event.startswith("os.spawn"):
            prog = args[1]
        elif event in ("os.posix_spawn", "os.exec") or event.startswith("os.exec"):
            prog = args[0]
    except (IndexError, TypeError, ValueError):
        prog = None
    name = os.path.basename(os.fsdecode(prog)) if isinstance(prog, (str, bytes, os.PathLike)) else event
    return f"{name} ({event}) at {_first_user_site()}"


def _own_listener(args) -> bool:
    """A TCP connect to a numeric loopback address whose port a listening socket of this very process holds."""
    import ipaddress
    import socket as _socket

    try:
        sock, addr = args[0], args[1]
        if sock.family not in (_socket.AF_INET, _socket.AF_INET6) or sock.type & 0xF != _socket.SOCK_STREAM:
            return False
        host, port = addr[0], int(addr[1])
        ip = ipaddress.ip_address(str(host).split("%", 1)[0])
    except (AttributeError, IndexError, TypeError, ValueError, OSError):
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if not (ip.is_loopback or (mapped is not None and mapped.is_loopback)):
        return False
    mine = _own_socket_inodes()
    want = f"{port:04X}"
    for t in ("tcp", "tcp6"):
        try:
            with open("/proc/self/net/" + t, "rb") as fh:
                next(fh, None)
                for line in fh:
                    parts = line.split()
                    if len(parts) < 10 or parts[3] != b"0A":  # LISTEN
                        continue
                    laddr, _, lport = parts[1].decode().rpartition(":")
                    if lport != want or parts[9].decode() not in mine:
                        continue
                    if set(laddr) <= {"0"} or _loopback_hex(laddr):
                        return True
        except OSError:
            continue
    return False


def _both_ends_mine(sock) -> bool:
    """A connected TCP socket whose peer address is the local address of a socket this process holds."""
    import socket as _socket

    try:
        if sock.family not in (_socket.AF_INET, _socket.AF_INET6) or sock.type & 0xF != _socket.SOCK_STREAM:
            return False
        peer = sock.getpeername()
    except (AttributeError, OSError):
        return False
    try:
        import ipaddress

        ip = ipaddress.ip_address(str(peer[0]).split("%", 1)[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if not (ip.is_loopback or (mapped is not None and mapped.is_loopback)):
        return False
    mine = _own_socket_inodes()
    want = f"{int(peer[1]):04X}"
    for t in ("tcp", "tcp6"):
        try:
            with open("/proc/self/net/" + t, "rb") as fh:
                next(fh, None)
                for line in fh:
                    parts = line.split()
                    if len(parts) < 10:
                        continue
                    laddr, _, lport = parts[1].decode().rpartition(":")
                    if lport == want and parts[9].decode() in mine and _loopback_hex(laddr):
                        return True
        except OSError:
            continue
    return False


def _own_socket_inodes() -> set:
    mine = set()
    try:
        fds = os.listdir("/proc/self/fd")
    except OSError:
        return mine
    for fd in fds:
        try:
            link = os.readlink("/proc/self/fd/" + fd)
        except OSError:
            continue
        if link.startswith("socket:["):
            mine.add(link[8:-1])
    return mine


def _loopback_hex(laddr: str) -> bool:
    """A /proc/net/tcp{,6} local address (hex, host byte order per 32-bit word) that is loopback."""
    try:
        b = bytes.fromhex(laddr)
    except ValueError:
        return False
    if len(b) == 4:
        return b[3] == 127  # little-endian 127.x.y.z
    if len(b) == 16:
        words = [b[i:i + 4][::-1] for i in range(0, 16, 4)]
        raw = b"".join(words)
        if raw == b"\0" * 15 + b"\1":
            return True
        return raw[:12] == b"\0" * 10 + b"\xff\xff" and raw[12] == 127
    return False


def _addr(args) -> str:
    try:
        a = args[1]
        return f"{a[0]}:{a[1]}" if isinstance(a, tuple) else str(a)
    except (IndexError, TypeError):
        return "?"


def _uncacheable(flags: set, cfg) -> str | None:
    if "badpath" in flags:
        return "reads a path that is not valid UTF-8"
    if "rclock" in flags:
        return "real clock read outside the virtual clock"
    if "spawn" in flags:
        return "subprocess"
    if "connect" in flags:
        return "network connection"
    if "csock" in flags:
        return "network socket opened outside Python (C extension)"
    if "dns" in flags:
        return "host name lookup"
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
def cache_epoch(cache_dir: str, head_ns: int, window_ns: int) -> int:
    """The epoch the cache in ``cache_dir`` runs its tests at (``epoch.json``).

    The HEAD commit time when the cache took it, kept while the current HEAD commit time ``head_ns`` is at most
    ``window_ns`` later; otherwise (no epoch yet, or older than the window) the epoch moves to ``head_ns``. An older
    checkout keeps the cache's epoch (later than its commit, as for any run after the commit). The epoch is part of
    the key of every test that read the clock, so moving it reruns those tests.
    """
    path = os.path.join(os.path.abspath(cache_dir), "epoch.json")
    try:
        with open(path) as fh:
            kept = int(json.load(fh)["epoch_ns"])
    except (OSError, ValueError, KeyError, TypeError):
        kept = None
    if kept is not None and head_ns - kept <= window_ns:
        return kept
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            json.dump({"epoch_ns": head_ns, "taken_from": "git HEAD commit time"}, fh)
        os.replace(tmp, path)
    except OSError:
        pass
    return head_ns


CAPTURE: Capture | None = None
PLUGIN: ProofCachePlugin | None = None


def start(early_config, ns) -> None:
    """Start recording (from ``pytest_load_initial_conftests``, before conftests are imported)."""
    global CAPTURE
    if not AVAILABLE:
        raise pytest.UsageError("--det-cache needs Python 3.12+ (sys.monitoring)")
    if CAPTURE is not None and CAPTURE.active:
        return  # nested in-process session: the outer one records
    root = str(early_config.rootpath)
    # detpy's own variables (set by its re-exec, e.g. the precompile time) are configuration, not inputs
    env0 = {_safe(k): _safe(v) for k, v in os.environ.items() if k not in _DETPY_OWN_ENV}
    cap = Capture(root, env0)
    CAPTURE = cap
    _core.cap_set_env_capture(cap)
    _patch_environ()
    _state.set_event_listener(cap.event)
    # probed before recording starts: the probe's own strace run is not a child of any test
    cap.follower = follow.Follower(cap, os.path.join(os.path.abspath(ns.det_cache), f"follow-{os.getpid()}"),
                                   not getattr(ns, "det_cache_no_follow", False))
    cap.follower.install()
    cap.start()


def install(config) -> None:
    """Register the plugin hooks (from ``pytest_configure``)."""
    global PLUGIN
    cap = CAPTURE
    if cap is None or PLUGIN is not None:
        return
    opt = config.option
    plugin = ProofCachePlugin(cap, opt.det_cache, opt.det_cache_verify, opt.det_cache_receipts)
    age = getattr(opt, "det_cache_max_age", 30.0)
    plugin.max_age_s = age * 86400 if age and age > 0 else None
    plugin.configure(config)
    PLUGIN = plugin
    config.pluginmanager.register(plugin, "detpy-cache")
    config.pluginmanager.register(_ProtocolWrapper(plugin), "detpy-cache-wrapper")
    cap.switch("s")


def uninstall() -> None:
    global CAPTURE, PLUGIN
    if CAPTURE is not None:
        CAPTURE.stop()
        if CAPTURE.follower is not None:
            CAPTURE.follower.uninstall()
    _state.set_event_listener(None)
    CAPTURE = None
    PLUGIN = None
    _core.cap_set_env_capture(None)


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
