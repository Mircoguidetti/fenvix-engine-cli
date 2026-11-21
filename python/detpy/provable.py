"""The wide sensor of the general rule, on the Python side.

The rule itself is in the shared Rust core (``crates/detpy-core/src/provable.rs``): the accounting table and the
one predicate that may conclude a test is provable. This module is only the sensor — it reports facts, it decides
nothing. What it reports, per test, is every callable the test crossed the Python/C boundary with that the core's
table could not account for. The core then answers NOT PROVEN for that test, whatever its fingerprint.

Why ``sys.monitoring`` and not ``sys.addaudithook``
---------------------------------------------------
The audit hook is the obvious candidate and it is not good enough. MEASURED in this container: 200,000
``os.stat`` calls raise **zero** audit events. The audit hook only fires for about seventeen
resource-acquisition operations (``open``, ``import``, ``exec``, ``socket.connect``, ``subprocess.Popen``,
``ctypes.dlopen``, ``os.listdir``, ...). It is blind to ``os.stat``, ``os.lstat``, ``os.access``, ``os.uname``,
``resource.getrusage``, ``os.read`` on an open descriptor, extended attributes, and every environment, clock and
random read. A general rule cannot rest on a sensor that cannot see file metadata.

``sys.monitoring``'s ``CALL`` event (PEP 669) fires for *every* callable invoked from Python bytecode, C
functions included, so it sees ``posix.stat`` like everything else. It needs Python 3.12+, which is no
restriction: 3.12 is the product's floor (3.11 is refused by the installer), so there is no supported
interpreter without it.

The audit hook is still installed, as a *second and independent* sensor: ``ctypes.dlopen`` loads a library whose
calls never appear as Python calls at all, and an audit event the engine has no rule for is itself a gap. Two
sensors that fail differently are worth more than one.

What is deliberately not done: ``DISABLE``
------------------------------------------
``sys.monitoring`` lets a callback return ``DISABLE`` to switch its event off at that one bytecode offset, which
makes the steady-state cost nil (MEASURED: 10 callbacks for 900,000 calls). It is not used here, and that is a
decision, not an oversight. ``DISABLE`` is per *call site*, not per callable, so a site that calls different
things on different iterations — ``for fn in (os.stat, os.getxattr): fn(p)`` — would be silenced after the first
callee and the second would never be seen. That is a hole in the rule, and "speed never buys an exception"
(founder, 2026-11-21). The cost of not using it is MEASURED in docs/REPORT-verifier-rule.md.

What this sensor cannot see (the declared residual)
---------------------------------------------------
A call made from C to C raises no ``CALL`` event: a native extension that opens a file or reads the clock inside
its own C code is invisible here, and to ``strace`` too in the clock's case. Two things narrow it, and the rest
is declared rather than hidden:

* ``inputs.deps`` digests the bytes of the installed packages, so a *different* extension cannot pass as
  identical;
* a test that loads a native extension which is not on the core's audited list is NOT PROVEN
  (``unaccounted.native``), which is this module's job below.
"""

from __future__ import annotations

import os
import sys

from . import _core, _sites, _state

_mon = getattr(sys, "monitoring", None)

#: Name and version of this sensor, as the trace header declares it. The core refuses a trace whose sensor it
#: does not know, so this string and the contract version travel together.
SENSOR = "py-monitoring/1"

#: Frames between a sensor callback and the frame that caused the operation, for ``_sites.resolve``.
#:
#: MEASURED, not guessed: from inside the ``sys.monitoring`` callback, ``resolve(0)`` and ``resolve(1)`` answer
#: None (the callback's own frame is the engine's) and ``resolve(2)`` answers the frame making the monitored
#: call. Getting this wrong by one silenced the sensor completely -- every gap looked like infrastructure -- which
#: is why it is a named constant with the measurement next to it.
_CALLER = 2

#: Set by the cache with proof (``_proof.Capture.start``) to be called with every gap this sensor finds, so that
#: the test is never stored and never reused. Without it the cache could reuse a result the rule refuses, and
#: "reused" would be as false a claim as "identical" (founder, 2026-11-21: whatever the cache cannot observe with
#: certainty forces a rerun). It is what sets the ``unacc`` flag that ``record.rs``'s ``uncacheable`` refuses on.
ON_GAP = None

#: Audit events the engine has a rule for. Every one of them is already covered by a channel rule (a file read is
#: an ``fs.read`` event, a child process is ``uncontrolled.child``, an import is an ``inputs.code`` / ``deps``
#: entry), so seeing them adds nothing. Anything else the audit hook reports is a gap: the hook is asked for
#: everything and whatever is not in this set becomes ``unaccounted.audit``.
_AUDIT_KNOWN = frozenset({
    # the interpreter's own bookkeeping, far too frequent to mean anything and carrying no outside state
    "builtins.id", "object.__getattr__", "object.__setattr__", "object.__delattr__", "exec", "compile",
    "marshal.loads", "marshal.dumps", "code.__new__", "function.__new__", "sys._getframe",
    "sys._getframemodulename", "sys.audit", "sys.excepthook", "sys.unraisablehook", "cpython.run_file",
    "cpython.run_module", "cpython.run_command", "cpython.run_stdin", "cpython.run_startup",
    "cpython.PyInterpreterState_New", "cpython.PyInterpreterState_Clear", "cpython._PySys_ClearAuditHooks",
    "builtins.breakpoint", "pickle.find_class", "gc.get_objects", "gc.get_referrers", "gc.get_referents",
    # this process's own frames and threads: no information from outside the process at all, and the engine's
    # own thread observer (`uncontrolled.py`) is what asks for them
    "sys._current_frames", "sys.settrace", "sys.setprofile", "sys.set_asyncgen_hooks",
    "sys.setrecursionlimit", "sys.setswitchinterval", "sys.addaudithook", "sys.set_int_max_str_digits",
    "sys.monitoring.register_callback", "sys.monitoring.set_events", "sys.monitoring.set_local_events",
    "sys.monitoring.use_tool_id", "sys.monitoring.free_tool_id", "sys.monitoring.restart_events",
    "object.__getattr__/result", "sys._getframe/result", "exec/result", "compile/result",
    # channels that already have a rule of their own
    "open", "import", "os.listdir", "os.scandir", "os.walk", "os.chdir", "os.fwalk",
    "os.putenv", "os.unsetenv", "os.getxattr", "os.setxattr", "os.listxattr", "os.removexattr",
    "os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.truncate", "os.link", "os.symlink", "os.chmod",
    "os.chown", "os.utime", "os.add_dll_directory",
    "shutil.rmtree", "shutil.copyfile", "shutil.move", "shutil.unpack_archive", "shutil.make_archive",
    "glob.glob", "pathlib.Path.glob", "tempfile.mkstemp", "tempfile.mkdtemp",
    "socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg", "socket.getaddrinfo",
    "socket.gethostbyname", "socket.gethostbyaddr", "socket.gethostname", "socket.__new__", "socket.sethostname",
    "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.fork", "os.forkpty", "os.spawn",
    "os.kill", "os.killpg", "_thread.start_new_thread", "_thread.start_joinable_thread",
    "ctypes.dlopen", "ctypes.dlsym", "ctypes.dlsym/handle", "ctypes.call_function", "ctypes.cdata",
    "ctypes.cdata/buffer", "ctypes.create_string_buffer", "ctypes.create_unicode_buffer", "ctypes.get_errno",
    "ctypes.set_errno", "ctypes.addressof", "ctypes.string_at", "ctypes.wstring_at",
    "sqlite3.connect", "sqlite3.connect/handle", "sqlite3.enable_load_extension", "sqlite3.load_extension",
    "http.client.connect", "http.client.send", "urllib.Request", "ftplib.connect", "smtplib.connect",
    "imaplib.open", "poplib.connect", "nntplib.connect", "telnetlib.Telnet.open",
    "time.sleep", "builtins.input", "builtins.input/result", "winreg.OpenKey", "msvcrt.open_osfhandle",
    "webbrowser.open", "array.__new__", "mmap.__new__", "resource.setrlimit", "syslog.syslog",
    "syslog.openlog", "syslog.closelog", "syslog.setlogmask",
})

#: `sys.monitoring` tool ids this sensor will take, in order. The cache with proof claims one of
#: `(COVERAGE_ID, 4, 3, 2, 5)` for its line recorder (``_proof.py``), so the two must not fight over the same
#: slot; whichever starts second takes what is left. With nothing free, no sensor is declared and every test of
#: the run comes out NOT PROVEN — which is the honest answer, not a reason to stop watching.
_TOOL_PREFERENCE = (5, 3, 4, 2, 1, 0)


def runtime_key() -> str:
    """The key the core matches against its audited runtimes (``cpython3.13``)."""
    impl = sys.implementation.name.lower()
    return f"{'cpython' if impl == 'cpython' else impl}{sys.version_info[0]}.{sys.version_info[1]}"


class Sensor:
    """The two sensors and the per-test ledger of what they could not place.

    One instance per process, started once per session. It records nothing by itself: every gap it finds becomes
    an ``unaccounted.<class>`` event of the running test (or an entry of ``not_proven_outside_tests`` when no
    test is running), and the Rust core decides what that means.
    """

    __slots__ = ("tool", "active", "_verdicts", "_seen", "outside", "_native_ok", "_native_seen",
                 "_reason", "_transparent_memo", "_seen_for", "_native_bad")

    def __init__(self) -> None:
        self.tool: int | None = None
        self.active = False
        # (module, qualname) -> True when the core accounted for it. One Rust call per distinct name, not per
        # call: the table is a pure function, so its answer can be remembered for the life of the process.
        self._verdicts: dict = {}
        self._transparent_memo: dict = {}   # module name -> its code is Python
        self._seen: set = set()          # gaps already reported for the test named by _seen_for
        self._seen_for: str | None = None
        self._native_bad: list = []      # unaudited extensions found, reported again for every later test
        self.outside: set = set()        # gaps found while no test was running
        self._native_ok: frozenset = frozenset()
        self._native_seen: set = set()
        self._reason: str | None = None  # why there is no sensor, when there is none

    # -- the ledger ----------------------------------------------------------------------------------
    def _report(self, kind: str, name: str, site: str = "<sensor>") -> None:
        """One gap. Inside a test it is an event of that test; outside one it goes to the header."""
        key = f"{kind}:{name}"
        st = _state.STATE
        if st.nodeid is None:
            self.outside.add(key)
            return
        # keyed by the running test, not by the process: a set that is never cleared would report a gap for the
        # first test only and leave every later test of the process looking clean
        if self._seen_for != st.nodeid:
            self._seen_for = st.nodeid
            self._seen = set()
        if key in self._seen:
            return
        self._seen.add(key)
        _state.record_at("other", f"unaccounted.{kind}", site, name)
        if ON_GAP is not None:
            try:
                ON_GAP(key)
            except Exception:
                pass   # the cache's bookkeeping must not take the test down

    def start_test(self) -> None:
        self._seen = set()
        self._seen_for = _state.STATE.nodeid
        # No sensor means nothing in this run can be shown identical, so nothing in it may be stored for reuse
        # either: a later run that reused one of these results would have no ground to call it provable.
        if not self.active and ON_GAP is not None:
            try:
                ON_GAP(f"sensor:{self._reason or 'the sensor is not running'}")
            except Exception:
                pass

    # -- sensor 1: every call crossing out of Python ---------------------------------------------------
    def _transparent(self, mod: str) -> bool:
        """True when this module's code is Python, so its callables need no entry in the table.

        This is the other half of the closed-world argument, and it is what keeps the table small enough to be
        auditable. A function written in Python cannot reach outside state on its own: its body is bytecode, and
        every call it makes into C fires ``CALL`` again and is classified then. So ``re.compile``,
        ``posixpath.join``, ``inspect.signature`` and ``pathlib.Path.stat`` need no entry — what they *do* is
        seen one level down, at ``posix.stat`` and friends.

        A builtin or extension module is the opposite: it *is* the boundary, so it must be in the table. That is
        also why an extension module nobody audited makes a test NOT PROVEN (:meth:`check_native`): its code is
        not Python, so nothing below it will be seen.
        """
        v = self._transparent_memo.get(mod)
        if v is None:
            m = sys.modules.get(mod)
            f = getattr(m, "__file__", None) if m is not None else None
            if f:
                v = f.endswith(".py") or f.endswith(".pyc") or f.endswith(".pyo")
            else:
                # a frozen module (`_frozen_importlib`, `zipimport`) is Python bytecode with no file of its own
                spec = getattr(m, "__spec__", None) if m is not None else None
                v = getattr(spec, "origin", None) == "frozen"
            self._transparent_memo[mod] = v
        return v

    def _on_call(self, code, offset, c, arg0):
        try:
            # 1. A callable implemented in Python is not a boundary crossing at all: its body is bytecode, and
            #    every call it makes into C fires CALL again and is classified then. This is the cheapest test
            #    and the commonest case, so it comes first. It also covers the engine's own patch wrappers,
            #    which are plain functions with no module of their own.
            if getattr(c, "__code__", None) is not None:
                return None
            f = getattr(c, "__func__", None)  # a bound Python method, a classmethod
            if f is not None and getattr(f, "__code__", None) is not None:
                return None
            mod = getattr(c, "__module__", None)
            qual = getattr(c, "__qualname__", None) or getattr(c, "__name__", None)
            if mod is None or qual is None:
                # a method of a C type: `list.append` carries neither (`__objclass__` is the type it belongs to),
                # a bound builtin method carries `__self__` instead
                owner = getattr(c, "__objclass__", None)
                if owner is None:
                    s = getattr(c, "__self__", None)
                    if s is not None:
                        owner = s if isinstance(s, type) else type(s)
                        if isinstance(s, type(sys)):  # a module-level builtin: `time.time`, `posix.stat`
                            mod = mod or getattr(s, "__name__", None)
                            owner = None
                if owner is not None:
                    mod = mod or getattr(owner, "__module__", None)
                    qual = qual or getattr(owner, "__qualname__", None)
                if qual is None:
                    # a callable instance: what runs is its type's `__call__`
                    t = type(c)
                    mod, qual = mod or getattr(t, "__module__", None), getattr(t, "__qualname__", "?")
            k = (mod or "", qual or "?")
            ok = self._verdicts.get(k)
            if ok is None:
                # a Python-level callable is not a boundary crossing at all; everything else must be in the table
                ok = self._transparent(k[0]) or _core.provable_account(k[0], k[1]) != "unaccounted"
                # keyed by the name, not by the object's identity: a bound builtin method is a fresh object on
                # every attribute access, so an identity cache would need a reference to each one -- and holding
                # `fh.read` would hold the open file, and `sock.recv` the socket, for the whole session.
                self._verdicts[k] = ok
            if not ok:
                # Only now, when a gap is about to be reported, is it worth asking whose call this is. A call the
                # runner makes for its own bookkeeping is not something the test observed (Rule E), and finding
                # that out means walking past the standard library: pytest's tmp_path machinery reaches
                # pwd.getpwuid through getpass.getuser(), so the immediate caller is the standard library and
                # only the frame above it says whose call it really is. `_sites.resolve` is the walk every other
                # observer in the engine uses, and it answers None for infrastructure.
                #
                # The verdict cache above still says "unaccounted", so the same callable reached from a test is
                # reported as it should be: what is suppressed here is the report, not the classification.
                site = _sites.resolve(_CALLER)
                if site is None:
                    return None
                self._report("api", f"{k[0]}.{k[1]}", site or _site(code, offset))
        except Exception:
            # a sensor that raises would take the test down with it. A sensor that cannot classify must not
            # answer "accounted": it says so, and the test is NOT PROVEN.
            try:
                self._report("api", "<the sensor could not classify a callable>")
            except Exception:
                pass
        return None  # never DISABLE: see the module docstring

    # -- sensor 2: the audit hook, for what calls do not show -----------------------------------------
    def _on_audit(self, event, args) -> None:
        # CPython raises `name/N` for the argument-list variants of one event (`glob.glob/2`, `ctypes.dlsym/handle`
        # and so on): the same operation, so the rule is the same and the suffix is dropped before the lookup.
        base = event.rsplit("/", 1)[0] if "/" in event else event
        if event in _AUDIT_KNOWN or base in _AUDIT_KNOWN:
            return
        # the same question as for a call: whose operation is this? The runner's own bookkeeping is not something
        # the test observed (Rule E), and only the frame above the standard library says so.
        if _sites.resolve(_CALLER) is None:
            return
        self._report("audit", event)

    # -- the residual: native extension modules -------------------------------------------------------
    def check_native(self) -> None:
        """Any extension module loaded that the core has not reasoned about makes the test NOT PROVEN.

        A C extension's own reads raise neither a call nor an audit event, so the only honest rule is to refuse
        a test that loaded one nobody audited. Called at the end of every test: an extension imported inside the
        test counts for that test, one imported earlier for all of them.

        What counts as audited: the interpreter's own extension modules (they are part of the interpreter, which
        the ``runtime`` run input pins), the engine's and the runner's (Rule E), and the names the core lists in
        ``CONTROLLED_NATIVE``. Anything else -- a package's compiled module, a project's own -- is a gap.
        """
        for name, m in list(sys.modules.items()):
            if name in self._native_seen:
                continue
            self._native_seen.add(name)
            f = getattr(m, "__file__", None)
            if not f or not (f.endswith(".so") or f.endswith(".pyd") or f.endswith(".dylib")):
                continue
            if name in self._native_ok:
                continue
            # The interpreter's own extension modules are part of the interpreter, which the `runtime` run input
            # pins, and the engine's and the runner's are the declared controlled set (Rule E). Deciding this by
            # PATH and not by name matters: which standard-library modules are separate shared objects depends on
            # how the interpreter was built. MEASURED on CI: `_asyncio` and thirteen others are separate .so files
            # on the hosted CPython 3.13 and built into the binary in this container, so a list of names refused
            # almost every test there and nothing here.
            kind = _sites._classify(f)[0]
            if kind in (_sites._STDLIB, _sites._INFRA):
                continue
            self._native_bad.append(name)
        # every unaudited extension loaded at any point so far, for THIS test: the module is still loaded, so its
        # C code could have run inside this test too. Scanning only what is new keeps the cost to the modules
        # imported since the last test; reporting all of them keeps the answer right for every test, which is what
        # this method's contract says ("one imported earlier for all of them").
        for name in self._native_bad:
            self._report("native", name)

    # -- start and stop --------------------------------------------------------------------------------
    def start(self) -> bool:
        """Install both sensors. False when this run cannot have one, with :attr:`reason` set."""
        # Turning the sensor off cannot buy a green: with no sensor the header carries no declaration and the
        # core answers NOT PROVEN for every test of the run. It exists to measure what the sensor costs
        # (docs/REPORT-verifier-rule.md), and it is safe by construction -- there is no setting that makes the
        # engine claim IDENTICAL on something it did not watch.
        if os.environ.get("FENVIX_NO_PROVABLE_SENSOR"):
            self._reason = "the sensor was switched off with FENVIX_NO_PROVABLE_SENSOR"
            return False
        if _mon is None:  # pragma: no cover - 3.12 is the floor, so this cannot happen on a supported build
            self._reason = f"sys.monitoring is missing (Python {sys.version_info[0]}.{sys.version_info[1]})"
            return False
        if runtime_key() not in _core.provable_runtimes():
            self._reason = (f"the engine's accounting table was not audited against {runtime_key()} "
                            f"(audited: {', '.join(_core.provable_runtimes())})")
            return False
        for tid in _TOOL_PREFERENCE:
            if _mon.get_tool(tid) is None:
                self.tool = tid
                break
        else:
            self._reason = "sys.monitoring has no free tool id for the sensor"
            return False
        self._native_ok = frozenset(_core.provable_native())
        _mon.use_tool_id(self.tool, "fenvix-provable")
        _mon.register_callback(self.tool, _mon.events.CALL, self._on_call)
        _mon.set_events(self.tool, _mon.events.CALL)
        # slot 1: the cache with proof keeps slot 0 for its own event list. () = every event reaches us,
        # because an event this sensor has no rule for is itself the gap it looks for.
        _core.set_audit_hook(self._on_audit, (), 1)
        self.active = True
        return True

    def stop(self) -> None:
        if not self.active:
            return
        self.active = False
        try:
            _mon.set_events(self.tool, 0)
            _mon.register_callback(self.tool, _mon.events.CALL, None)
            _mon.free_tool_id(self.tool)
        except Exception:
            pass
        try:
            _core.set_audit_hook(None, (), 1)
        except Exception:
            pass

    @property
    def reason(self) -> str | None:
        """Why this run has no sensor, or None when it has one."""
        return self._reason

    def header(self) -> dict | None:
        """``meta.provable`` for the trace header, or None when there is no sensor to declare.

        A header without it is what makes every test of the run NOT PROVEN in the core. That is the point: a run
        that cannot say what it watched must not be able to claim a green.
        """
        if not self.active:
            return None
        import json

        return json.loads(_core.provable_header(SENSOR, runtime_key()))


def _site(code, offset) -> str:
    try:
        return f"{code.co_filename}:{code.co_firstlineno}"
    except Exception:  # pragma: no cover - a code object always has these
        return "<sensor>"


#: The process's sensor. ``_level0.py`` starts it with the rest of the controls.
SENSOR_OBJ = Sensor()
