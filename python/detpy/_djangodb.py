"""Django's test database, reused with proof (row PY-04, founder decision 2026-11-21).

Building a test database (``migrate`` on an empty database) is often the longest single step of a Django suite.
Django's own shortcuts (``manage.py test --keepdb``, pytest-django's ``--reuse-db``) keep the *last run's* database:
whatever the last run left behind, and whatever the migrations were then. Neither is used here.

Under ``--det`` (every runner: the pytest plugin with pytest-django, and the driver's ``manage.py test`` shell),
``BaseDatabaseCreation.create_test_db`` is wrapped:

* **Fingerprint.** Before anything is created, the engine computes a fingerprint of what the built database is a
  function of: the migrations on disk (every app's migration names and the bytes of their files), the model state
  (every model's table, fields, columns and database types), the database server's version, the settings (every
  upper-case setting, the alias' ``DATABASES`` entry included), the Django, Python and engine versions. The record of
  the last build adds what the build was *observed* to use: every code file whose functions ran during the build
  (``sys.setprofile``) or that was imported by it, every project module that was loaded when it ran (test files
  excepted), every data file it opened, every environment variable it read, and, when the build read the virtual
  clock or drew from a seeded generator, the epoch and the seed.
* **Equal: a clean prepared copy.** The database is created from a template the engine built and sealed (PostgreSQL:
  a database ``fenvix_tpl_*`` marked ``IS_TEMPLATE`` and ``ALLOW_CONNECTIONS false``, so nothing can write to it;
  SQLite: a backup file under ``.detpy/django-db``). ``migrate`` is not run; ``createcachetable`` and the
  serialization Django does for ``serialized_rollback`` still are. Every process gets its own copy: Django's parallel
  workers clone it as they always do, pytest-django's xdist workers and the engine's parallel lanes create theirs
  from the template. Never the last run's database: a run that wrote to its copy leaves the template untouched.
* **Changed: rebuilt.** Anything that differs (or a record that cannot be read, a template that is missing, a build
  that wrote files or ran in an unsupported backend) means a normal build; a successful build is then sealed as the
  new template with its record. The line the engine prints names what changed.

What is NOT covered, and is therefore a rebuild rather than a reuse: a backend other than PostgreSQL and SQLite;
``--keepdb`` / ``--reuse-db`` (the user's own choice wins, and the engine says so); a build that wrote a file.

The database setup is not an event of any test: it runs with no test current (pytest-django sets it up inside the
first database test's setup), and the per-test clock and generators of that test start again after it, so a run
that built the database and a run that reused it produce the same trace. Its inputs still reach the cache with
proof: nothing of the setup itself is observed, and after it (a build or a reuse alike) the recorded input files
are read again (``_touch``): run inputs of every test, the same after a build and after a reuse.

``enable(root)`` is called by the shells when ``--det`` is on and ``--det-db`` is not ``fresh``.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import sys
import time

from . import __version__

FORMAT = "fenvix-django-db"
VERSION = 1
_ROOT: str | None = None
_ENABLED = False
_REAL = None
NOTES: list[str] = []  # one line per database set up this session (the shells print them in their summary)
_ADDR = re.compile(r" at 0x[0-9a-fA-F]+")
_TEST_FILE = re.compile(r"(^test_.*|.*_tests?|^tests|^conftest)\.py$")


def enable(root: str) -> None:
    """Wrap Django's test-database creation (idempotent). Imports nothing of Django that is not imported already."""
    global _ROOT, _ENABLED, _REAL
    _ROOT = os.path.abspath(root)
    if _ENABLED:
        return
    try:
        from django.db.backends.base.creation import BaseDatabaseCreation
    except Exception:  # pragma: no cover - Django absent or broken: nothing to do
        return
    _ENABLED = True
    _REAL = BaseDatabaseCreation.create_test_db

    def create_test_db(self, *args, **kw):
        return _create(self, args, kw)

    create_test_db.__wrapped__ = _REAL
    BaseDatabaseCreation.create_test_db = create_test_db


def disable() -> None:
    global _ENABLED
    if not _ENABLED:
        return
    from django.db.backends.base.creation import BaseDatabaseCreation

    BaseDatabaseCreation.create_test_db = _REAL
    _ENABLED = False


# -- helpers ------------------------------------------------------------------------------------------------------------

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_digest(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return _sha(f.read())
    except OSError:
        return "<missing>"


def _norm(v) -> str:
    """A stable text of a settings or field value: callables by their qualified name, addresses removed."""
    if callable(v) and not isinstance(v, type):
        mod = getattr(v, "__module__", None)
        qn = getattr(v, "__qualname__", None) or getattr(v, "__name__", None)
        if mod and qn:
            return f"<callable {mod}.{qn}>"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{_norm(k)}: {_norm(v[k])}" for k in sorted(v, key=repr)) + "}"
    if isinstance(v, (list, tuple)):
        return ("[" if isinstance(v, list) else "(") + ", ".join(_norm(x) for x in v) + ("]" if isinstance(v, list) else ")")
    try:
        r = repr(v)
    except Exception as e:  # pragma: no cover
        r = f"<unrepr {type(v).__name__}: {e}>"
    return _ADDR.sub("", r)


def _store() -> str:
    d = os.path.join(_ROOT or os.getcwd(), ".detpy", "django-db")
    os.makedirs(d, exist_ok=True)
    return d


@contextlib.contextmanager
def _lock(key: str):
    path = os.path.join(_store(), f"{key}.lock")
    with open(path, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# -- the fingerprint ----------------------------------------------------------------------------------------------------

_SETTINGS_DIGEST: str | None = None


def _settings_digest() -> str:
    """Every upper-case setting, computed once per process before any test database renamed its alias."""
    global _SETTINGS_DIGEST
    if _SETTINGS_DIGEST is None:
        from django.conf import settings

        import warnings

        parts = []
        with warnings.catch_warnings():  # reading a deprecated setting warns; the digest is not the user's read
            warnings.simplefilter("ignore")
            for name in sorted(n for n in dir(settings) if n.isupper()):
                try:
                    parts.append(f"{name}={_norm(getattr(settings, name))}")
                except Exception as e:
                    parts.append(f"{name}=<error {type(e).__name__}>")
        _SETTINGS_DIGEST = _sha("\n".join(parts).encode())
    return _SETTINGS_DIGEST


def _migrations() -> dict:
    """Every app's migrations on disk: ``app.name`` -> digest of its file."""
    from django.db.migrations.loader import MigrationLoader

    loader = MigrationLoader(None, ignore_no_migrations=True)
    out = {}
    for (app, name), mig in sorted(loader.disk_migrations.items()):
        mod = sys.modules.get(type(mig).__module__)
        f = getattr(mod, "__file__", None)
        out[f"{app}.{name}"] = _file_digest(f) if f else "<no file>"
    return out


def _models(connection) -> str:
    from django.apps import apps

    rows = []
    for m in sorted(apps.get_models(include_auto_created=True, include_swapped=True), key=lambda m: m._meta.label):
        meta = m._meta
        fields = []
        for f in meta.local_fields + list(meta.local_many_to_many):
            try:
                dt = f.db_type(connection)
            except Exception as e:
                dt = f"<error {type(e).__name__}>"
            try:
                dec = _norm(f.deconstruct()[1:])
            except Exception as e:
                dec = f"<error {type(e).__name__}>"
            fields.append(f"{f.name}|{getattr(f, 'column', '')}|{dt}|{dec}")
        rows.append(f"{meta.label}|{meta.db_table}|{meta.managed}|{meta.swapped}|" + ";".join(fields))
    return _sha("\n".join(rows).encode())


def _server_version(creation) -> str:
    conn = creation.connection
    if conn.vendor == "sqlite":
        import sqlite3

        return f"sqlite {sqlite3.sqlite_version}"
    if conn.vendor == "postgresql":
        with creation._nodb_cursor() as cur:
            cur.execute("SHOW server_version_num")
            num = cur.fetchone()[0]
            cur.execute("SELECT version()")
            return f"postgresql {num} {cur.fetchone()[0]}"
    return f"{conn.vendor} (unsupported)"


def _alias_settings(conn) -> str:
    d = {k: v for k, v in conn.settings_dict.items() if k not in ("NAME", "PASSWORD")}
    return _sha(_norm(d).encode())


def static_parts(creation) -> dict:
    import django

    conn = creation.connection
    return {
        "format": f"{FORMAT}/{VERSION}",
        "engine": __version__,
        "python": sys.version.split()[0],
        "django": django.get_version(),
        "vendor": conn.vendor,
        "server": _server_version(creation),
        "settings": _settings_digest(),
        "alias": _alias_settings(conn),
        "migrations": _migrations(),
        "models": _models(conn),
    }


def _fingerprint(static: dict) -> str:
    return _sha(json.dumps(static, sort_keys=True).encode())


# -- what a build is observed to use ------------------------------------------------------------------------------------

class _Observer:
    """Code that ran, files opened, environment variables read, clock and generator use, during one build."""

    _hook_installed = False
    current: "_Observer | None" = None

    def __init__(self):
        self.code: set[str] = set()
        self.data: set[str] = set()
        self.wrote: list[str] = []
        self.env: dict[str, str | None] = {}
        self.modules_before = set(sys.modules)

    def __enter__(self):
        from . import _core

        if not _Observer._hook_installed:
            sys.addaudithook(_audit)
            _Observer._hook_installed = True
        _Observer.current = self
        self._prev_profile = sys.getprofile()
        code = self.code

        def prof(frame, event, arg, code=code):
            if event == "call":
                code.add(frame.f_code.co_filename)

        sys.setprofile(prof)
        self._env_cls = type(os.environ)
        rec = self.env
        base = self._env_cls

        class _Watched(base):
            def __getitem__(self, key):
                try:
                    v = base.__getitem__(self, key)
                except KeyError:
                    rec.setdefault(key, None)
                    raise
                rec.setdefault(key, v)
                return v

            def __contains__(self, key):
                ok = base.__contains__(self, key)
                rec.setdefault(key, base.__getitem__(self, key) if ok else None)
                return ok

        os.environ.__class__ = _Watched
        try:
            self.clock0 = _core.clock_state().get("elapsed") if _core.clock_installed() else None
        except Exception:
            self.clock0 = None
        try:
            self.seeds0 = _core.seeds_counter()
        except Exception:
            self.seeds0 = None
        import random

        self.random0 = random.getstate()
        return self

    def __exit__(self, *exc):
        from . import _core

        sys.setprofile(self._prev_profile)
        os.environ.__class__ = self._env_cls
        _Observer.current = None
        import random

        try:
            c1 = _core.clock_state().get("elapsed") if _core.clock_installed() else None
        except Exception:
            c1 = None
        try:
            s1 = _core.seeds_counter()
        except Exception:
            s1 = None
        self.used_clock = c1 != self.clock0
        self.used_random = s1 != self.seeds0 or random.getstate() != self.random0
        self.new_modules = set(sys.modules) - self.modules_before
        return False


def _audit(event, args):
    obs = _Observer.current
    if obs is None or event != "open":
        return
    try:
        path, mode, flags = args[0], args[1], args[2]
    except Exception:
        return
    if not isinstance(path, str):
        return
    writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
        isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND))
    if writing:
        obs.wrote.append(path)
    elif path.endswith((".py", ".pyc")):
        pass  # code is taken from the modules and the profile
    else:
        obs.data.add(os.path.abspath(path))


def _module_files(names) -> set[str]:
    out = set()
    for n in names:
        m = sys.modules.get(n)
        f = getattr(m, "__file__", None)
        if isinstance(f, str) and os.path.isfile(f):
            out.add(os.path.abspath(f))
    return out


def _inputs_of(obs: _Observer) -> dict:
    files = set()
    for f in obs.code:
        if os.path.isabs(f) and os.path.isfile(f):
            files.add(f)
    files |= _module_files(obs.new_modules)
    root = _ROOT or os.getcwd()
    for f in _module_files(list(sys.modules)):
        if f.startswith(root + os.sep) and not _TEST_FILE.match(os.path.basename(f)) and "/.venv/" not in f:
            files.add(f)
    data = {p: _file_digest(p) for p in sorted(obs.data) if not p.startswith(_store())}
    return {"code": {p: _file_digest(p) for p in sorted(files)}, "data": data}


# -- the record and the template ----------------------------------------------------------------------------------------

def _key(creation, test_name: str) -> str:
    sd = creation.connection.settings_dict
    ident = f"{creation.connection.vendor}|{sd.get('HOST')}|{sd.get('PORT')}|{test_name}"
    return _sha(ident.encode())[:16]


def _record_path(key: str) -> str:
    return os.path.join(_store(), f"{key}.json")


def _load(key: str) -> dict | None:
    try:
        with open(_record_path(key)) as f:
            rec = json.load(f)
        return rec if rec.get("format") == f"{FORMAT}/{VERSION}" else None
    except (OSError, ValueError):
        return None


def _differences(rec: dict | None, static: dict, epoch: int, seed: int) -> list[str]:
    """Why the record does not prove the template (empty: it does)."""
    if rec is None:
        return ["no template yet"]
    why = []
    old = rec.get("static", {})
    for k in static:
        if old.get(k) != static[k]:
            if k == "migrations":
                a, b = old.get(k) or {}, static[k]
                ch = sorted(n for n in set(a) | set(b) if a.get(n) != b.get(n))
                why.append("migrations " + ", ".join(ch[:5]) + (f" (+{len(ch) - 5})" if len(ch) > 5 else ""))
            else:
                why.append(k)
    for kind in ("code", "data"):
        ch = [p for p, d in (rec.get("inputs", {}).get(kind) or {}).items() if _file_digest(p) != d]
        if ch:
            root = _ROOT or ""
            names = [os.path.relpath(p, root) if p.startswith(root) else p for p in ch[:3]]
            why.append(f"{kind} {', '.join(names)}" + (f" (+{len(ch) - 3})" if len(ch) > 3 else ""))
    env = [k for k, v in (rec.get("env") or {}).items() if _env_digest(os.environ.get(k)) != v]
    if env:
        why.append("environment " + ", ".join(sorted(env)[:5]))
    if rec.get("used_clock") and rec.get("epoch") != epoch:
        why.append("epoch (the build read the clock)")
    if rec.get("used_random") and rec.get("seed") != seed:
        why.append("seed (the build drew from a seeded generator)")
    return why


def _env_digest(v) -> str | None:
    return None if v is None else _sha(v.encode("utf-8", "surrogateescape"))


def _det_epoch_seed() -> tuple[int, int]:
    from . import _state

    c = _state.STATE.config
    return int(c.epoch_ns), int(c.seed)


def _tpl_name(key: str, fp: str) -> str:
    return f"fenvix_tpl_{key[:10]}_{fp[:16]}"


def _template_ok(creation, rec: dict) -> bool:
    conn = creation.connection
    if conn.vendor == "sqlite":
        p = rec.get("template")
        return bool(p) and os.path.isfile(p) and _file_digest(p) == rec.get("template_digest")
    if conn.vendor == "postgresql":
        with creation._nodb_cursor() as cur:
            cur.execute("SELECT datistemplate, datallowconn, shobj_description(oid, 'pg_database') "
                        "FROM pg_catalog.pg_database WHERE datname = %s", [rec.get("template")])
            row = cur.fetchone()
        return bool(row) and row[0] is True and row[1] is False and row[2] == f"{FORMAT} {rec.get('fingerprint')}"
    return False


def _seal(creation, key: str, fp: str, test_name: str) -> tuple[str, str | None]:
    """The freshly built test database becomes the template: (template, digest of a sqlite template file)."""
    conn = creation.connection
    if conn.vendor == "sqlite":
        import sqlite3

        conn.ensure_connection()
        path = os.path.join(_store(), f"{key}-{fp[:16]}.sqlite3")
        tmp = path + f".tmp{os.getpid()}"
        dst = sqlite3.connect(tmp)
        try:
            conn.connection.backup(dst)
        finally:
            dst.close()
        os.replace(tmp, path)
        for f in os.listdir(_store()):  # earlier templates of this database
            if f.startswith(f"{key}-") and f.endswith(".sqlite3") and os.path.join(_store(), f) != path:
                with contextlib.suppress(OSError):
                    os.remove(os.path.join(_store(), f))
        return path, _file_digest(path)
    tpl = _tpl_name(key, fp)
    qn = conn.ops.quote_name
    conn.close()
    if hasattr(conn, "close_pool"):
        conn.close_pool()
    with creation._nodb_cursor() as cur:
        cur.execute("SELECT datname FROM pg_catalog.pg_database WHERE datname LIKE %s", [f"fenvix_tpl_{key[:10]}_%"])
        for (old,) in cur.fetchall():
            cur.execute(f"ALTER DATABASE {qn(old)} IS_TEMPLATE false")
            cur.execute(f"DROP DATABASE IF EXISTS {qn(old)}")
        cur.execute(f"CREATE DATABASE {qn(tpl)} WITH TEMPLATE {qn(test_name)}")
        cur.execute(f"ALTER DATABASE {qn(tpl)} IS_TEMPLATE true ALLOW_CONNECTIONS false")
        cur.execute(f"COMMENT ON DATABASE {qn(tpl)} IS %s", [f"{FORMAT} {fp}"])
    return tpl, None


def _touch(rec: dict) -> None:
    """On a reuse: read the build's recorded inputs again, so that the capture of the cache with proof sees them as
    the build made it see them (an edited migration still changes every test's key that read it)."""
    for kind in ("code", "data"):
        for p in (rec.get("inputs", {}).get(kind) or {}):
            with contextlib.suppress(OSError):
                open(p, "rb").close()


# -- the wrapper --------------------------------------------------------------------------------------------------------

def _lane_suffix() -> str:
    return os.environ.get("DETPY_DJANGO_LANE", "")


def _create(creation, args, kw):
    from django.conf import settings

    conn = creation.connection
    keepdb = kw.get("keepdb", args[3] if len(args) > 3 else False)
    lane = _lane_suffix()
    if lane:
        # an engine parallel lane (django_runner): its own test database, created from the same template
        test = conn.settings_dict.setdefault("TEST", {})
        base = test.get("NAME") or ("test_" + (conn.settings_dict.get("NAME") or ""))
        if conn.vendor != "sqlite" or not creation.is_in_memory_db(base):
            root, ext = os.path.splitext(base)
            test["NAME"] = f"{root}_lane{lane}{ext}"
    if keepdb:
        NOTES.append(f"test database '{conn.alias}': --keepdb / --reuse-db given, the user's database is used as is "
                     f"(not proven by the engine)")
        return _REAL(creation, *args, **kw)
    if conn.vendor not in ("sqlite", "postgresql"):
        NOTES.append(f"test database '{conn.alias}': backend {conn.vendor} has no prepared copy, built as usual")
        return _REAL(creation, *args, **kw)
    from . import _state

    st = _state.STATE
    nid = st.nodeid
    st.nodeid = None  # the setup is not an event of the test that happens to need it first
    done: list = []
    try:
        # nothing of the setup itself is observed (a build reads migrations, a reuse reads the template: the run
        # would differ by how the database was made); what it depends on is observed once, below, the same way
        # after a build and after a reuse
        with _state.quiet():
            return _create_quiet(creation, args, kw, settings, done)
    finally:
        if done:
            _touch(done[0])  # outside any test: run inputs (files_read_outside_tests), read by the capture
        st.nodeid = nid
        if nid is not None:
            _restart_test(nid)


def _restart_test(nid: str) -> None:
    """pytest-django builds the database inside the first database test's setup: that test's clock and generators
    start again after it, so a build and a reuse leave the test in the same state."""
    from . import _level0, _state

    controls = _state.STATE.config.controls
    if "time" in controls:
        from . import clock

        clock.start_test()
    if "seeds" in controls:
        from . import seeds

        seeds.start_test(_level0.PATCHER, nid)


def _create_quiet(creation, args, kw, settings, done: list):
    conn = creation.connection
    test_name = creation._get_test_db_name()
    in_memory = conn.vendor == "sqlite" and creation.is_in_memory_db(test_name)
    key = _key(creation, _base_name(test_name) if not in_memory else f"memory:{conn.alias}")
    epoch, seed = _det_epoch_seed()
    t0 = time.perf_counter()
    with _lock(key):
        static = static_parts(creation)
        fp = _fingerprint(static)
        rec = _load(key)
        why = _differences(rec, static, epoch, seed)
        if not why and not _template_ok(creation, rec):
            why = ["template missing or altered"]
        built = ""
        if why:
            ok, err = _build_forked(creation, args, kw, key, fp, static, epoch, seed)
            if ok:
                rec = _load(key)
                left = _differences(rec, static, epoch, seed) or ([] if _template_ok(creation, rec) else ["template"])
                if left:
                    ok, err = False, f"the separate build's record does not prove it: {'; '.join(left)}"
            if not ok:
                return _build_here(creation, args, kw, key, fp, static, epoch, seed, why, err, done, t0)
            built = f"REBUILT ({'; '.join(why)}) in a separate process, sealed as template "
        name = _restore(creation, args, kw, rec, in_memory)
        done.append(rec)
        NOTES.append(f"test database '{conn.alias}' ({static['server']}): {built or 'REUSED a clean copy of template '}"
                     f"{os.path.basename(rec['template'])}{', clean copy taken' if built else ''} (fingerprint "
                     f"{fp[:12]}: {len(static['migrations'])} migrations, {len(rec['inputs']['code'])} code files, "
                     f"{len(rec['inputs']['data'])} data files, {len(rec['env'])} environment variables; "
                     f"{time.perf_counter() - t0:.2f}s)")
        return name


def _base_name(test_name: str) -> str:
    """The test database's name without a per-process suffix (pytest-django's ``_gw<N>``, the engine's lanes): every
    process of one run shares one template."""
    w = os.environ.get("PYTEST_XDIST_WORKER")
    root, ext = os.path.splitext(test_name)
    for suf in ([f"_{w}"] if w else []) + ([f"_lane{_lane_suffix()}"] if _lane_suffix() else []):
        if root.endswith(suf):
            root = root[: -len(suf)]
    return root + ext


def _new_record(obs, static, fp, epoch, seed, tpl, tdig, name) -> dict:
    return {"format": f"{FORMAT}/{VERSION}", "fingerprint": fp, "static": static, "inputs": _inputs_of(obs),
            "env": {k: _env_digest(v) for k, v in sorted(obs.env.items())}, "used_clock": obs.used_clock,
            "used_random": obs.used_random, "epoch": epoch, "seed": seed, "template": tpl,
            "template_digest": tdig, "test_name": name}


def _write_record(key: str, rec: dict) -> None:
    tmp = _record_path(key) + f".tmp{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(rec, f, indent=1, sort_keys=True)
    os.replace(tmp, _record_path(key))


def _detpy_runner_entry() -> int:
    """The engine's own fork, not the code under test's: the capture of the cache with proof takes a spawn from a
    frame of this name as infrastructure (``capture.rs`` ``is_runner_entry``), and ``posix.fork`` bypasses the
    controls' wrappers of ``os.fork`` that mark a test as having started a process."""
    import posix

    return posix.fork()


def _build_forked(creation, args, kw, key, fp, static, epoch, seed) -> tuple[bool, str]:
    """Build and seal in a forked child: it starts from this process's exact state (settings as the runner changed
    them, the engine's controls with their seed and epoch) and exits after sealing, so whatever the build warmed in
    memory (Django's lazily built migration models, caches the ``post_migrate`` handlers filled) dies with it. This
    process then takes a clean copy, as it does on every reuse: a run that built and a run that reused run the same
    code from here on. Returns (ok, why not)."""
    if not hasattr(os, "fork"):
        return False, "no fork() on this platform"
    import warnings

    from django.db import connections

    connections.close_all()  # no socket may be shared with the child
    r, w = os.pipe()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # "multi-threaded, fork() may deadlock": see below
        pid = _detpy_runner_entry()
    if pid == 0:  # the child: build, seal, record, drop its own test database, exit without atexit handlers
        code = 4
        try:
            os.close(r)
            conn = creation.connection
            original = conn.settings_dict["NAME"]
            with _Observer() as obs:
                name = _REAL(creation, *args, **kw)
            if obs.wrote:
                os.write(w, f"the build wrote {obs.wrote[0]}".encode())
                code = 3
            else:
                tpl, tdig = _seal(creation, key, fp, name)
                _write_record(key, _new_record(obs, static, fp, epoch, seed, tpl, tdig, name))
                with contextlib.suppress(Exception):
                    creation.destroy_test_db(original, verbosity=0)
                os.write(w, b"OK")
                code = 0
        except BaseException as e:  # noqa: BLE001 - everything goes back to the parent as text
            with contextlib.suppress(Exception):
                os.write(w, f"{type(e).__name__}: {e}"[:2000].encode())
        finally:
            os._exit(code)
    os.close(w)
    chunks = []
    while True:
        b = os.read(r, 65536)
        if not b:
            break
        chunks.append(b)
    os.close(r)
    _, status = os.waitpid(pid, 0)
    msg = b"".join(chunks).decode(errors="replace")
    ok = os.waitstatus_to_exitcode(status) == 0 and msg == "OK"
    return ok, "" if ok else (msg or f"the build process ended with status {status}")


def _build_here(creation, args, kw, key, fp, static, epoch, seed, why, err, done, t0):
    """The fallback: a normal build in this process (sealed when it can be). Never a reuse."""
    conn = creation.connection
    with _Observer() as obs:
        name = _REAL(creation, *args, **kw)
    if obs.wrote:
        NOTES.append(f"test database '{conn.alias}': REBUILT ({'; '.join(why)}); not sealed as a template: the "
                     f"build wrote {obs.wrote[0]}" + (f" (+{len(obs.wrote) - 1})" if len(obs.wrote) > 1 else ""))
        return name
    tpl, tdig = _seal(creation, key, fp, name)
    rec = _new_record(obs, static, fp, epoch, seed, tpl, tdig, name)
    _write_record(key, rec)
    done.append(rec)
    NOTES.append(f"test database '{conn.alias}' ({static['server']}): REBUILT ({'; '.join(why)}) in this process "
                 f"({err}) and sealed as template {os.path.basename(tpl)} (fingerprint {fp[:12]}; "
                 f"{time.perf_counter() - t0:.2f}s)")
    return name


def _restore(creation, args, kw, rec: dict, in_memory: bool):
    """Django's own ``create_test_db`` with the database created from the template and ``migrate`` replaced."""
    import django.core.management as mgmt

    conn = creation.connection
    real_cc = mgmt.call_command

    def call_command(name, *a, **k):
        if name == "migrate":
            if conn.vendor == "sqlite":
                import sqlite3

                conn.ensure_connection()
                src = sqlite3.connect(rec["template"])
                try:
                    src.backup(conn.connection)
                finally:
                    src.close()
            return None
        return real_cc(name, *a, **k)

    patched = []
    if conn.vendor == "postgresql":
        tpl = rec["template"]

        def suffix():
            test = conn.settings_dict["TEST"]
            return creation._get_database_create_suffix(encoding=test.get("CHARSET"), template=tpl)

        creation.sql_table_creation_suffix = suffix
        patched.append("sql_table_creation_suffix")
    mgmt.call_command = call_command
    try:
        return _REAL(creation, *args, **kw)
    finally:
        mgmt.call_command = real_cc
        for a in patched:
            with contextlib.suppress(AttributeError):
                delattr(creation, a)
