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

# context names: "" startup, "s" between tests, "c|<file>" collection of a file, "f|<scope>|<baseid>|<name>" setup
# of a wider-scoped fixture, "t|<nodeid>" a test, "i" / "i|<file>" import time. The capture's rules (skipped
# paths, write events, spawn events, ...) are in crates/detpy-py/src/capture.rs.
_AUDIT_EVENTS = ("exec", "open", "sqlite3.connect", "os.listdir", "os.scandir", "socket.connect", "socket.sendto", "socket.sendmsg",
                 "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "subprocess.Popen", "os.posix_spawn",
                 "os.exec", "os.system", "os.fork", "os.forkpty", "os.spawn", "os.remove", "os.rename", "os.mkdir",
                 "os.rmdir", "os.truncate", "shutil.rmtree", "shutil.copyfile", "shutil.move", "os.symlink",
                 "os.link")
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


# Line capture granularity (experiment, DETPY_CACHE_LINES): "line" (default) arms every code object with LINE;
# "code" arms plain functions (not module or class bodies, not generators or coroutines) with PY_START only and
# records one location per start (the function's last line), see REPORT-2. The entry line and that line are read
# from the bytecode in Rust (CaptureCore.arm): the opcodes it needs are passed in.
_CODE_LEVEL = os.environ.get("DETPY_CACHE_LINES", "line") == "code"
import opcode as _opcode  # noqa: E402

_RESUME = _opcode.opmap.get("RESUME", -1)
_PRELUDE = {_opcode.opmap[n] for n in ("MAKE_CELL", "COPY_FREE_VARS", "RETURN_GENERATOR", "POP_TOP")
            if n in _opcode.opmap}


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
        the real clock makes its context uncacheable. (A trace callback the test sets itself replaces this one.)

        review R-009b R1: the schema evaluates such expressions too (a column default, a trigger, a view), while the
        statement says nothing about time. A statement that may evaluate the schema (anything but transaction
        control, PRAGMA, ATTACH/DETACH, DROP...) on a connection whose databases' schema may read the clock is
        refused in the same way."""
        try:
            import sqlite3
            import sqlite3.dbapi2 as dbapi2
        except ImportError:
            return
        real = sqlite3.connect
        cap = self
        self._sql_real_connect = real
        self._sql_schema: dict[str, tuple] = {}  # database file -> (signature, what reads the clock or None)

        def connect(*args, **kwargs):
            conn = real(*args, **kwargs)
            db = args[0] if args else kwargs.get("database")
            uri = kwargs.get("uri", args[7] if len(args) > 7 else False)
            # the state holds no reference to the connection (a cycle would delay closing it; no weak references)
            st = _SqlConn(_sqlite_file(db, bool(uri)))
            try:
                conn.set_trace_callback(lambda statement: cap._sql_trace(statement, st))
            except Exception:
                pass
            return conn

        connect.__wrapped__ = real
        self._sqlite_saved = [(sqlite3, "connect", real), (dbapi2, "connect", dbapi2.connect)]
        sqlite3.connect = connect
        dbapi2.connect = connect

    def _sql_trace(self, statement, st=None) -> None:
        if not self.active or not isinstance(statement, str):
            return
        if _SQL_REAL_CLOCK.search(statement):
            self.flag(self._cur(), "rclock", f"sqlite: {statement.strip()[:80]} at {_first_user_site()}")
            if st is not None and _SQL_DDL.match(statement):
                st.own = st.own or "this connection's schema"  # a temporary or uncommitted definition included
        if st is None:
            return
        m = _SQL_ATTACH.match(statement)
        if m:
            f = _sqlite_file(m.group(1)[1:-1].replace("''", "'"), True)
            if f is not None:
                st.dbs.append(f)
            return
        if _SQL_NO_SCHEMA.match(statement):
            return
        why = st.own
        if why is None:
            for f in st.dbs:
                why = self._sql_schema_clock(f)
                if why is not None:
                    break
        if why is not None:
            self.flag(self._cur(), "rclock",
                      f"sqlite: {why} may read the real clock ({statement.strip()[:60]}) at {_first_user_site()}")

    def _sql_schema_clock(self, path: str) -> str | None:
        """What in the schema of database file ``path`` may read the real clock (None: nothing), memoised on the
        file's and its write-ahead log's identity."""
        sig = []
        for f in (path, path + "-wal"):
            try:
                st = os.stat(f)
                sig.append((st.st_ino, st.st_size, st.st_mtime_ns))
            except OSError:
                sig.append(None)
        if sig[0] is None:
            return None  # not created yet: no schema
        sig = tuple(sig)
        memo = self._sql_schema.get(path)
        if memo is not None and memo[0] == sig:
            return memo[1]
        from urllib.parse import quote
        why = None
        try:
            # a "file:" URI: the audit hook does not take this connection as the test's read of the file
            con = self._sql_real_connect(f"file:{quote(path)}?mode=ro", uri=True, timeout=0)
            try:
                for name, sql in con.execute("select name, sql from sqlite_master where sql is not null"):
                    if isinstance(sql, str) and _SQL_REAL_CLOCK.search(sql):
                        why = f"the schema of {self._key(path)} ({name})"
                        break
            finally:
                con.close()
        except Exception as e:
            why = f"the schema of {self._key(path)} (unreadable: {e})"
        self._sql_schema[path] = (sig, why)
        return why

    # child_ignored, child_read, collect_children, _credit_child: Rust (CaptureCore)


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
    """pytest hooks of ``--det-cache``. The session's bookkeeping (decisions, reports, the record plan, the reasons
    and the summary) is Rust (``_core.CacheSession``, ``crates/detpy-py/src/session.rs``); this class hands it
    pytest's objects."""

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
        self.items: dict[str, object] = {}
        self.run_id = f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime(_now()))}-{os.getpid()}"
        self.sess = _core.CacheSession(self.run_id, self.receipts_path)

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
        self.sess.configure(self.config_digest, self.runtime_digest, self.epoch)

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
            self.sess.t_check = _perf() - t0

    def _decide(self, items) -> None:
        store, cap = self.store, self.cap
        changed = list(store.changed_code_files())
        for (path, content), f in zip(changed, self._read_facts([os.path.join(self.root, p) for p, _ in changed],
                                                                 [c for _, c in changed])):
            if f is not None:
                store.set_fresh(path, content, *f)
        self.sess.seed_exclusive(store, cap)  # review R-009b R2
        nids = [item.nodeid for item in items]
        self.items = dict(zip(nids, items))
        # the checks, the expiry (review R-009 F4: an entry older than --det-cache-max-age is not reused), the
        # receipts and the verification draw (Python's Mersenne Twister, seeded per run) are Rust
        rng = random.Random(f"detpy-cache-verify:{self.run_id}")
        self.sess.decide(store, nids, self.max_age_s, _now(), _run_time, self.verify, rng.random)

    def _read_facts(self, paths, contents) -> list:
        """Facts of code files (``_codefacts``: CPython's parser), detpy's own reads not being inputs."""
        if not paths:
            return []
        cap, was = self.cap, self.cap.active
        cap.active = False
        try:
            return _codefacts.read_many([(p, c, *_module_of(p)) for p, c in zip(paths, contents)],
                                        os.path.join(self.dir, "tmp"))
        finally:
            cap.active = was

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
        receipt = self.sess.hit(item.nodeid)
        if receipt is None:
            return None
        self._reuse(item, nextitem, receipt)
        return True

    def _wrap_protocol(self, item, nextitem):  # generator driven by _ProtocolWrapper
        nid = item.nodeid
        if self.sess.is_hit(nid):
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
        self.sess.start_test(nid, fx)
        self.cap.switch("t|" + nid)
        t = _perf()
        try:
            yield
        finally:
            dur = _perf() - t
            self.cap.switch("s")
            self.cap.scan_modules(self.sess.end_test(nid, dur), self._conftests())

    def pytest_runtest_logreport(self, report):
        self.sess.report(report)

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

        rep, fingerprint = self.store.reuse_info(item.nodeid)
        ihook = item.ihook
        ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
        now = _now()
        kw = {k: 1 for k in item.keywords}
        props = [("detpy_cache", "reused"), ("detpy_cache_key", receipt["key"]),
                 ("detpy_fingerprint", fingerprint)]
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

        sess, cap = self.sess, self.cap
        sess.add_fingerprints(_plugin.S.fingerprints)
        cap.switch("s")
        cap.stop()
        t0 = _perf()
        try:
            self._record_all()
        except Exception as e:  # never break the test session: nothing is recorded this time
            import traceback
            import warnings

            sess.error = f"{type(e).__name__}: {e}"
            warnings.warn(f"detpy --det-cache: results not recorded: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        finally:
            sess.t_record = _perf() - t0
        sess.compare_verified()
        sess.write_receipts(self.store)

    def _facts(self, rels, cache: dict) -> None:
        """Store index of the facts of the current version of every file in ``rels`` not in ``cache`` (new versions
        parsed together)."""
        jobs = []
        for rel in rels:
            if rel in cache:
                continue
            content = _core.file_digest(os.path.join(self.root, rel))
            ix = None if content is None else self.store.file_index(rel, content)
            cache[rel] = ix
            if content is not None and ix is None:
                jobs.append((rel, content))
        facts = _codefacts.read_many([(p, c, *_module_of(p)) for p, c in
                                      ((os.path.join(self.root, r), c) for r, c in jobs)],
                                     os.path.join(self.dir, "tmp")) if jobs else ()
        for (rel, content), f in zip(jobs, facts):
            cache[rel] = None if f is None else self.store.add_file(rel, content, *f)

    def _record_all(self) -> None:
        if self.cap.rec is None:
            return
        t = _perf()
        self.cap.collect_children()
        self.sess.set_phase("children", _perf() - t)
        self._record_captured()

    def _record_captured(self) -> None:
        """Record every test that ran: the record plan is built and recorded in Rust (``CacheSession.record``,
        ``detpy_core::record``) from the session, the capture and the facts of the files it needs (CPython's
        parser, ``_codefacts``)."""
        cap, store, sess = self.cap, self.store, self.sess
        t = _perf()
        fcache: dict[str, int | None] = {}
        needed, whole = sess.files_needed(cap, self.items)
        self._facts(needed, fcache)
        self._facts(whole, fcache)
        sess.set_phase("facts", _perf() - t)
        t = _perf()
        per, imp = cap.rec.fold(len(cap.ctx_names), cap.segs, store.unit_ranges([fcache.get(r) for r in cap.fnames]))
        cfg = _state.STATE.config
        assemble = sess.record(store, cap, self.items, fcache, needed, per, imp, _module_of,
                               bool(cfg.control_urandom), "time" in cfg.controls, cfg.cassette_path)
        sess.set_phase("plan", _perf() - t - assemble)
        sess.set_phase("assemble", assemble)
        t = _perf()
        store.save()
        sess.set_phase("save", _perf() - t)

    # -- reporting (Rust: CacheSession) --------------------------------------------------
    def summary_data(self) -> dict:
        return self.sess.summary_data(self.cap)

    def outcomes_data(self) -> dict:
        return self.sess.outcomes_data(self.cap)

    def terminal_summary(self, tr) -> None:
        tr.section("detpy cache with proof")
        for text, markup in self.sess.summary_lines(self.cap, tr.config.option.verbose):
            tr.write_line(text, **({markup: True} if markup else {}))


def _run_time(run: str) -> float:
    """Real time (seconds) of a run id ``YYYYmmddTHHMMSS-pid``; 0 when unreadable (then the entry has expired).
    (``time.strptime``'s rules, which depend on the Python version: called by ``ProofCache.check_all`` once per
    distinct run id.)"""
    import calendar

    try:
        return float(calendar.timegm(time.strptime(run.split("-", 1)[0], "%Y%m%dT%H%M%S")))
    except (ValueError, IndexError):
        return 0.0


def _safe(s: str) -> str:
    """``s`` as valid UTF-8 text (undecodable bytes of environment strings escaped)."""
    return s if _encodable(s) else s.encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")


def _encodable(s: str) -> bool:
    try:
        s.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False






import re as _re  # noqa: E402

# sqlite reads the real clock for 'now', CURRENT_TIMESTAMP/DATE/TIME and the date functions called without a time
# value (date(), datetime(), time(), julianday(), unixepoch(), strftime(format))
_SQL_REAL_CLOCK = _re.compile(
    r"""'now'|"now"|\bcurrent_(timestamp|date|time)\b|\b(date|time|datetime|julianday|unixepoch)\s*\(\s*\)"""
    r"""|\bstrftime\s*\(\s*('[^']*'|"[^"]*")\s*\)""", _re.I)


# statements that evaluate no column default, trigger or view
_SQL_NO_SCHEMA = _re.compile(
    r"\s*(begin|commit|end|rollback|savepoint|release|pragma|attach|detach|drop|vacuum|analyze|reindex)\b", _re.I)
_SQL_DDL = _re.compile(r"\s*(create|alter)\b", _re.I)
_SQL_ATTACH = _re.compile(r"\s*attach\s+(?:database\s+)?('(?:[^']|'')*')", _re.I)


class _SqlConn:
    """What detpy knows of one sqlite connection: its database files (main, attached) and whether a definition it
    ran reads the real clock."""

    __slots__ = ("dbs", "own")

    def __init__(self, main: str | None):
        self.dbs = [main] if main is not None else []
        self.own: str | None = None


def _sqlite_file(db, uri: bool) -> str | None:
    """The absolute path of the database file sqlite opens for ``db`` (None: in memory or not a file name)."""
    if not isinstance(db, (str, bytes, os.PathLike)):
        return None
    try:
        s = os.fsdecode(db)
    except (TypeError, ValueError):
        return None
    if uri and s.startswith("file:"):
        from urllib.parse import unquote
        s, _, query = s[5:].partition("?")
        if "mode=memory" in query.split("#")[0].split("&"):
            return None
        if s.startswith("//"):
            host, _, rest = s[2:].partition("/")
            s = "/" + rest if host in ("", "localhost") else ""
        s = unquote(s.split("#")[0])
    if s in ("", ":memory:"):
        return None
    try:
        return os.path.abspath(s)
    except (OSError, ValueError):
        return None


def _numeric_host(host: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        return True
    except ValueError:
        return False


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
