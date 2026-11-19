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

import os

import pytest

from . import _core, _state, follow  # noqa: F401 (kept importable from here: test plugins reach them as proofcache.*)

# the runner-neutral part (capture, identities, session): _proof.py; these names stay importable from here
from ._proof import (  # noqa: F401
    _AUDIT_EVENTS,
    _DETPY_DIR,
    _DETPY_OWN_ENV,
    AVAILABLE,
    Capture,
    ProofSession,
    _ctx_file,
    _dist_infos,
    _module_of,
    _now,
    _patch_environ,
    _perf,
    _run_time,
    cache_epoch,
    digest_identity,
    level0_identity,
    runtime_identity,
    start_capture,
    stop_capture,
    tz_locale_identity,
)

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



def config_identity(config) -> tuple[str, dict]:
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
        **level0_identity(),
        "plugins": plugins,
        "ini": ini_items,
        "inifile": os.path.relpath(str(inipath), root) if inipath else None,
        "options": opts,
    }
    return digest_identity(d), d


# ---------------------------------------------------------------------------
class ProofCachePlugin(ProofSession):
    """pytest hooks of ``--det-cache``: the runner-neutral session (``_proof.ProofSession``) fed by pytest's objects."""

    def __init__(self, cap: Capture, cache_dir: str, verify: float, receipts: str | None):
        super().__init__(cap, cache_dir, verify, receipts)
        self.config = None

    # -- setup ----------------------------------------------------------------
    def configure(self, config) -> None:
        self.config = config
        basetemp = None
        factory = getattr(config, "_tmp_path_factory", None)
        if factory is not None:
            try:
                basetemp = os.path.realpath(str(factory.getbasetemp()))
            except Exception:
                basetemp = None
            self.cap.basetemp = basetemp
        self.open(str(config.rootpath), *config_identity(config))

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
        nids = [item.nodeid for item in session.items]
        self.check(nids, dict(zip(nids, session.items)), _unittest_units(nids, session.items))

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
        self.start(nid, fx)
        t = _perf()
        try:
            yield
        finally:
            self.stop(nid, _perf() - t)

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
    def finish(self, session) -> None:  # noqa: D102 (pytest shell: the fingerprints of the plugin's recorder)
        from . import plugin as _plugin

        super().finish(_plugin.S.fingerprints)

    def terminal_summary(self, tr) -> None:
        tr.section("detpy cache with proof")
        for text, markup in self.sess.summary_lines(self.cap, tr.config.option.verbose):
            tr.write_line(text, **({markup: True} if markup else {}))


def _unittest_units(nids, items) -> list:
    """The tests of each ``unittest.TestCase`` class, reused together or not at all (as under ``python -m detpy
    unittest``, ``runners/unittest_shell.py``): the methods run in order and share the class's attributes and what
    ``setUpClass`` built, which the capture does not see; a method reused after another one of its class ran
    fresh would carry a result made with the other's old version of that state."""
    import unittest

    units: dict = {}
    for nid, item in zip(nids, items):
        cls = getattr(item, "cls", None)
        if isinstance(cls, type) and issubclass(cls, unittest.TestCase):
            units.setdefault(id(cls), []).append(nid)
    return [u for u in units.values() if len(u) > 1]


CAPTURE: Capture | None = None
PLUGIN: ProofCachePlugin | None = None


def start(early_config, ns) -> None:
    """Start recording (from ``pytest_load_initial_conftests``, before conftests are imported)."""
    global CAPTURE
    if not AVAILABLE:
        raise pytest.UsageError("--det-cache needs Python 3.12+ (sys.monitoring)")
    if CAPTURE is not None and CAPTURE.active:
        return  # nested in-process session: the outer one records
    CAPTURE = start_capture(str(early_config.rootpath), ns.det_cache, not getattr(ns, "det_cache_no_follow", False))


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
    stop_capture(CAPTURE)
    CAPTURE = None
    PLUGIN = None


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
