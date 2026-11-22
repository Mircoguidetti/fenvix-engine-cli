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
import sys

import pytest

from . import _core, _state, follow  # noqa: F401 (kept importable from here: test plugins reach them as proofcache.*)

# the runner-neutral part (capture, identities, session): _proof.py; these names stay importable from here
from ._proof import (  # noqa: F401
    _AUDIT_EVENTS,
    _DETPY_DIR,
    _ScandirEntry,
    _TimedStat,
    _time_helper_caller,
    _reaches_user,
    _user_stat_caller,
    _kind_check_caller,
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
    "det_cache_verify", "det_cache_receipts", "det_cache_shared", "det_cache_keys", "det_trace", "det_outcomes", "det_compare", "det_max_events",
    "showcapture", "fulltrace", "collectonly", "markers", "fixtures", "show_fixtures_per_test", "help", "version",
    "debug", "traceconfig", "showlocals", "log_file", "log_cli_level", "pastebin", "usepdb", "usepdb_cls",
    "trace", "xmlpath", "htmlpath", "lf", "failedfirst", "last_failed_no_failures", "newfirst", "cacheclear",
    "cacheshow", "stepwise", "stepwise_skip", "maxfail", "exitfirst", "no_header", "no_summary", "override_ini",
    "inifilename", "rootdir", "confcutdir", "keyword", "markexpr", "deselect", "ignore", "ignore_glob",
    "continue_on_collection_errors", "numprocesses", "dist", "tx", "det_epoch", "det_cache_max_age",
    "det_cache_epoch_window",
    # pytest-xdist's options (set differently in its controller, its workers and a serial session) and detpy's
    # plan replay: under --det the plan is not an input of a test's result (docs/PARALLEL-PROOF-DESIGN.md 2.5)
    "loadgroup", "looponfail", "distload", "maxprocesses", "maxworkerrestart", "loadscopereorder", "px",
    "testrunuid", "rsyncdir", "rsyncignore", "maxschedchunk", "det_plan", "det_plan_worker",
}


def config_identity(config, as_if: dict | None = None) -> tuple[str, dict]:
    """The configuration digest and its parts; ``as_if``: option values to use instead of the session's (the serial
    session's configuration of an isolated one)."""
    plugins = sorted({f"{dist.project_name}=={dist.version}"
                      for _, dist in config.pluginmanager.list_plugin_distinfo()})
    ini = getattr(config, "_inicfg", None)
    if ini is None:
        ini = {}
    ini_items = sorted((str(k), repr(getattr(v, "value", v))) for k, v in dict(ini).items())
    opts = []
    # options of a plugin detpy blocks under --det (pytest-randomly: plugin.py keeps its options valid and inert):
    # they change nothing, and only some processes of a session define them (the xdist controller does, its workers
    # do not), so a result recorded by a worker had another configuration than the controller's (MEASURED: never
    # reused under -n with pytest-randomly installed)
    pm = config.pluginmanager
    inert = tuple(prefix for name, prefix in (("randomly", "randomly_"), ("random_order", "random_order"))
                  if pm.is_blocked(name))
    for k, v in sorted(vars(config.option).items()):
        if k in _VOLATILE_OPTIONS or (inert and k.startswith(inert)):
            continue
        if as_if and k in as_if:
            v = as_if[k]
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
    """pytest hooks of ``--det-cache``: the runner-neutral session (``_proof.ProofSession``) fed by pytest's objects,
    and pytest-xdist's controller and worker roles under ``--det``."""

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
        # audit G-0169: the configuration of the same session without --det-isolate, under which the serial results
        # of these tests are stored (_expect_serial compares an isolated outcome with them)
        # (the in-process session: --det-cache-in-process, without isolation; --det-isolate-scope at its default)
        self.serial_config_digest = (config_identity(config, as_if={"det_isolate": False, "det_isolate_scope": "file",
                                                                    "det_cache_in_process": True})[0]
                                     if config.getoption("det_isolate", False) else None)
        # audit G-0159: the nightly real-clock check compares with the results recorded on the virtual day
        self.real_clock = bool(config.getoption("det_cache_real_clock", False))
        if self.real_clock:
            cfg = _state.STATE.config
            saved = cfg.controls
            try:
                cfg.controls = frozenset(saved | {"time"})
                self.serial_config_digest = config_identity(config, as_if={"det_cache_real_clock": False})[0]
            finally:
                cfg.controls = saved


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
        self.collected()
        if self.role == "worker":
            # the controller decided; this worker runs (and records) every test the plan sends it
            self.items = {item.nodeid: item for item in session.items}
            self.sess.set_test_index(list(self.items))
            return
        nids = [item.nodeid for item in session.items]
        self.check(nids, dict(zip(nids, session.items)), _unittest_units(nids, session.items))
        if (self.isolate and not self.iso_child) or self.real_clock:
            self._expect_serial(nids)
            self.demote_for_running([nids])  # a result _expect_serial withdrew runs after its file's earlier tests
        if self.real_clock:
            for nid in nids:  # every test runs on the real clock
                self.sess.demote(nid, "real-clock check: every test runs")

    # -- pytest-xdist under --det: the controller --------------------------------------------------------------
    def decide_controller(self, nids: list) -> set:
        """The reuse decision of every collected test, once, in the controller (before the plan). The environment
        a worker of this run sees, the deferred check of ``PYTEST_XDIST_WORKER`` (compared with this run's plan in
        ``check_workers``) and the verification draw (seeded by ``derive_seed`` over the seed, the order and the
        configuration: two runs on the same inputs verify the same tests) are Rust. Returns the reused ids."""
        from . import plugin as _plugin

        t0 = _perf()
        try:
            ctl = _plugin.S.controller
            env0 = ctl.spawn_env if ctl is not None and ctl.spawn_env is not None else self.cap.env0
            self.store.begin_controller(self.config_digest, self.runtime_digest, self.epoch, dict(env0),
                                        len(self.config.getoption("tx") or ()),
                                        ctl.testrunuid if ctl is not None else None)
            store = self.store
            self._shared_fetch(list(nids))
            changed = list(store.changed_code_files())
            for (path, content), f in zip(changed, self._read_facts([os.path.join(self.root, p) for p, _ in changed],
                                                                     [c for _, c in changed])):
                if f is not None:
                    store.set_fresh(path, content, *f)
            self._shared_adopt()
            self.sess.seed_exclusive(store, self.cap)
            seed = _core.CacheSession.controller_verify_seed(_state.STATE.config.seed, list(nids), self.config_digest)
            self.sess.decide(store, list(nids), self.max_age_s, _now(), _run_time, self.verify, seed)
            self._demote_writers_of_running_readers(list(nids))
            self.prefix_check(list(nids))
            self._expect_serial(list(nids))
            if self.real_clock:
                for nid in nids:
                    self.sess.demote(nid, "real-clock check: every test runs")
            return set(self.sess.hit_ids)
        finally:
            self.sess.t_check = _perf() - t0

    # -- PY-05 / audit G-0175, G-0169: -n and --det-isolate never change an outcome silently ----------------------
    def _expect_serial(self, nids) -> None:
        """The outcome a serial session gives each test that runs here, where the store proves it: a serial entry (or
        a parallel one proven equal to the serial result) whose inputs are unchanged. ``placement_findings`` compares
        it with the outcome this session got."""
        exp = self.serial_expect = {}
        store = self.store
        # set for --det-isolate (per test or per file, the default under the cache: the -n controller too, which
        # isolates nothing itself) and for the real-clock check
        view = None
        if getattr(self, "serial_config_digest", None):
            if self.store.entries_with_config(self.serial_config_digest):
                # a read-only view of the same store under the serial session's configuration
                cap, was = self.cap, self.cap.active
                cap.active = False
                try:
                    view = _core.ProofCache(self.dir, self.root)
                    view.begin(self.serial_config_digest, self.runtime_digest, self.epoch, dict(cap.env0))
                finally:
                    cap.active = was
            # no result of the in-process session in the store: nothing to compare with but pending findings (the
            # store itself holds this mode's results, not the in-process ones)
            store = view
        pending = self._pending_findings() if (getattr(self, "serial_config_digest", None) or self.role == "controller") \
            and not getattr(self, "real_clock", False) else {}
        for nid in list(nids):
            hit = self.sess.is_hit(nid)
            p = pending.get(nid)
            if p is not None:
                # a placement finding of an earlier session that no session has resolved: never reused here, compared
                # again (it is reported until this mode gives the in-process outcome or the in-process session gives
                # this mode's)
                if hit:
                    self.sess.demote(nid, f"placement: a pending finding: {p.get('here')} under {p.get('how')}, "
                                          f"{p.get('in_process')} in the in-process session")
                exp.setdefault(nid, p.get("in_process"))
                continue
            if store is None or (hit and store is self.store):
                continue
            try:
                ok, _ = store.check(nid)
                if not ok:
                    continue
                e = json.loads(store.entry(nid))
            except Exception:
                continue
            if not (e.get("placement", "") in ("", "parallel-proven") and e.get("outcome")):
                continue
            if hit:
                # coordinator condition 2: a result of this mode (one child per file or per test) whose outcome is not
                # the in-process session's with the same inputs is not reused: it runs, and is a finding again
                try:
                    mine = json.loads(self.store.entry(nid)).get("outcome")
                except Exception:
                    mine = None
                if mine != e["outcome"] and self.sess.demote(
                        nid, f"placement: {mine} here, {e['outcome']} in the in-process session with the same inputs"):
                    exp[nid] = e["outcome"]
                continue
            exp[nid] = e["outcome"]

    def _note_outcome(self, report) -> None:
        got = self.__dict__.setdefault("got_outcome", {})
        nid = report.nodeid
        if report.failed:
            got[nid] = "failed"
        elif got.get(nid) == "failed":
            return
        elif report.when == "call" or (report.when == "setup" and report.skipped):
            out = report.outcome
            if hasattr(report, "wasxfail"):
                out = "xfailed" if report.skipped else "xpassed"
            got[nid] = out

    def placement_findings(self) -> list:
        """(nodeid, serial outcome, this session's outcome) of every test whose outcome under -n / --det-isolate
        differs from the outcome a serial session gives it with the same inputs (the store's proof)."""
        exp = getattr(self, "serial_expect", None) or {}
        got = getattr(self, "got_outcome", None) or {}
        return [(n, exp[n], got[n]) for n in exp if n in got and got[n] != exp[n]]

    FINDINGS = "placement-findings.json"

    def _pending_findings(self) -> dict:
        d = self.engine_json_load(os.path.join(self.dir, self.FINDINGS))
        return d if isinstance(d, dict) else {}

    def _save_findings(self) -> None:
        """Placement findings persist until resolved (coordinator condition 2: never silent; the store keeps one entry
        per test, so the in-process result they were found against may be gone). A session of this mode resolves one
        when it gives the in-process outcome; an in-process session resolves one when it gives this mode's."""
        pending = self._pending_findings()
        got = getattr(self, "got_outcome", None) or {}
        before = dict(pending)
        if (getattr(self, "serial_config_digest", None) or self.role == "controller") \
                and not getattr(self, "real_clock", False):
            how = "-n" if self.role == "controller" and getattr(self, "iso_scope", "test") != "file" else (
                "one child per test file" if getattr(self, "iso_scope", "test") == "file" else "one child per test")
            exp = getattr(self, "serial_expect", None) or {}
            for nid, want in exp.items():
                if nid not in got:
                    continue
                if got[nid] == want:
                    pending.pop(nid, None)
                else:
                    pending[nid] = {"in_process": want, "here": got[nid], "how": how, "run": self.run_id}
        elif self.role != "worker" and not getattr(self, "isolate", False):
            for nid in list(pending):  # the in-process session
                if nid in got and got[nid] == pending[nid].get("here"):
                    pending.pop(nid)
        if pending != before:
            self.engine_json_save(os.path.join(self.dir, self.FINDINGS), pending, sort_keys=True)

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session):
        try:
            self._save_findings()
        except Exception:  # never break the session
            pass
        if self.placement_findings() and session.exitstatus == 0:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
        if self.role != "worker" and not self.iso_child \
                and session.config.pluginmanager.getplugin("terminalreporter") is None:
            # no terminal reporter (-p no:terminal): no summary hook will run; the summary file still holds it (G-0412)
            try:
                self.terminal_summary(_NoTerminal(session.config))
            except Exception:  # noqa: BLE001 - never break the session's end
                pass

    def check_workers(self, nids: list, assign: dict) -> list:
        """After the plan: reused results that read ``PYTEST_XDIST_WORKER`` and that this run's plan places on
        another worker are withdrawn (they run). Returns the withdrawn ids (review R-023 F3)."""
        out = []
        for nid, why in self.store.worker_check([n for n in nids if self.sess.is_hit(n)], dict(assign)):
            if self.sess.demote(nid, why):
                out.append(nid)
        return out

    def written_hits(self, shard_paths: list, order: list) -> list:
        """After every worker finished: the reused results whose input a test that comes before them in the serial
        order wrote in this session (``ProofCache.hits_written``). They are withdrawn; the controller runs them again.
        Returns ``[(nodeid, reason)]`` (review R-023 F2)."""
        out = []
        hits = [n for n in order if self.sess.is_hit(n)]
        for nid, key, writer in self.store.hits_written(list(shard_paths), hits, list(order)):
            why = f"written: {key} was written by {writer}, which comes before the test, in this session"
            if self.sess.demote(nid, why):
                out.append((nid, why))
        return out

    def report_hits(self, nids: list) -> None:
        """Reports of the reused results among ``nids``, from the controller (they are never sent to a worker):
        logstart, the recorded setup/call reports, a passed teardown, logfinish."""
        from _pytest.reports import TestReport

        hook = self.config.hook
        now = _now()
        for nid in nids:
            if not self.sess.is_hit(nid):
                continue
            receipt = self.sess.hit(nid)
            rep, fingerprint = self.store.reuse_info(nid)
            location = _location_of(nid)
            hook.pytest_runtest_logstart(nodeid=nid, location=location)
            props = [("detpy_cache", "reused"), ("detpy_cache_key", receipt["key"]), ("detpy_fingerprint", fingerprint)]
            for when in ("setup", "call"):
                p = rep.get(when)
                if p is None:
                    continue
                lr = p.get("longrepr")
                r = TestReport(nid, location, {}, p["outcome"], tuple(lr) if lr else None, when, (), 0.0, now, now,
                               list(props))
                if "wasxfail" in p:
                    r.wasxfail = p["wasxfail"]
                hook.pytest_runtest_logreport(report=r)
            hook.pytest_runtest_logreport(report=TestReport(nid, location, {}, "passed", None, "teardown", (), 0.0,
                                                            now, now, list(props)))
            hook.pytest_runtest_logfinish(nodeid=nid, location=location)
            if fingerprint:
                from . import plugin as _plugin

                _plugin.S.fingerprints[nid] = fingerprint

    def report_unrun(self, nids_reasons: list) -> None:
        """Withdrawn reuses the controller could not run again (no worker to run them): reported as errors, never
        as their recorded result."""
        from _pytest.reports import TestReport

        hook = self.config.hook
        now = _now()
        for nid, why in nids_reasons:
            location = _location_of(nid)
            hook.pytest_runtest_logstart(nodeid=nid, location=location)
            hook.pytest_runtest_logreport(report=TestReport(
                nid, location, {}, "failed", f"detpy --det-cache: the reused result was withdrawn ({why}) and no "
                f"worker was left to run the test again", "setup", (), 0.0, now, now, []))
            hook.pytest_runtest_logfinish(nodeid=nid, location=location)

    def durations(self, nids: list) -> dict:
        """``{nodeid: recorded duration}`` of the tests that have an entry: the plan's cache costs."""
        return {n: d for n, d in zip(nids, self.store.durations(list(nids))) if d is not None}

    def merge_workers(self, workeroutput: dict, sent: dict, edges: list = (), lists: dict | None = None) -> None:
        """The controller's end of session: the workers' summaries, then the cross-worker write rule and one merge of
        their shards into the store (``ProofCache.merge_shards``)."""
        t0 = _perf()
        paths = list(self.iso_shards) if self.isolate else []
        for wid in sorted(workeroutput):
            out = workeroutput[wid]
            summ = out.get("detpy_cache_summary")
            if summ:
                ran, recorded, not_cached = summ[:3]
                where = [tuple(x) for x in summ[3]] if len(summ) > 3 else None
                self.sess.merge_worker(list(ran), int(recorded), [tuple(x) for x in not_cached], where)
            if out.get("detpy_cache_error"):
                self.sess.error = out["detpy_cache_error"]
            if out.get("detpy_cache_shard"):
                paths.append(out["detpy_cache_shard"])
            paths.extend(out.get("detpy_cache_shards") or ())  # --det-isolate: the worker's children
            if out.get("detpy_isolate"):
                from . import isolate as _isolate

                for k, v in out["detpy_isolate"].items():
                    _isolate.STATS[k] = _isolate.STATS.get(k, 0) + v
        self.merge_shards(paths, edges, lists, t0)

    # -- pytest-xdist under --det: a worker ----------------------------------------------------------------------
    def worker_output(self) -> dict:
        self.iso_merge_summaries()
        if self.isolate:
            self.iso_flush()
        out = {"detpy_cache_summary": list(self.sess.worker_summary())}
        if self.shard_path:
            out["detpy_cache_shard"] = self.shard_path
        if self.iso_shards:
            out["detpy_cache_shards"] = list(self.iso_shards)
        if self.isolate:
            from . import isolate as _isolate

            out["detpy_isolate"] = dict(_isolate.STATS)
        err = self.sess.summary_data(self.cap).get("error")
        if err:
            out["detpy_cache_error"] = err
        return out

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
        self.recheck(nid)
        if self.sess.is_hit(nid) or (self.isolate and not self.iso_child):
            # a reused result; or --det-isolate's parent: the child does iso_begin / iso_end
            yield
            return
        t = self.iso_begin(item)
        try:
            yield
        finally:
            self.iso_end(item, t)

    def iso_begin(self, item) -> float:
        """The cache's start of a test that runs (the protocol wrapper's, or a --det-isolate child's)."""
        nid = item.nodeid
        fx = []
        info = getattr(item, "_fixtureinfo", None)
        if info is not None:
            for name in item.fixturenames:
                defs = info.name2fixturedefs.get(name)
                if defs and defs[-1].scope != "function":
                    d = defs[-1]
                    fx.append(f"f|{d.scope}|{d.baseid}|{d.argname}")
        self.start(nid, fx)
        # review R-023b N9: xdist's worker_id and testrun_uid fixtures read config.workerinput, not the environment;
        # they carry the same values as PYTEST_XDIST_WORKER / _TESTRUNUID, which are inputs (the worker one is
        # checked against this run's plan, Checker::worker_check)
        names = getattr(item, "fixturenames", ())
        if "worker_id" in names:
            self.cap.env_read("PYTEST_XDIST_WORKER")
        if "testrun_uid" in names:
            self.cap.env_read("PYTEST_XDIST_TESTRUNUID")
        return _perf()

    def iso_end(self, item, t: float) -> None:
        self.stop(item.nodeid, _perf() - t)

    def iso_record(self, fingerprints: dict | None = None) -> tuple:  # noqa: D102 (isolate.py calls it bare)
        from . import plugin as _plugin

        return super().iso_record(_plugin.S.fingerprints if fingerprints is None else fingerprints)

    def pytest_runtest_logreport(self, report):
        if self.role != "worker" and not self.iso_child:
            for k, v in getattr(report, "user_properties", None) or ():
                if k == "detpy_placement":  # a failure only the per-file isolation caused (isolate.FileIsolate)
                    self.__dict__.setdefault("replay_findings", {})[report.nodeid] = v
            self._note_outcome(report)  # findings (and their resolution by an in-process session)
        if self.isolate and not self.iso_child and report.nodeid in self.iso_forked:
            return  # the child reported it to its own session
        self.sess.report(report)

    def _conftests(self):
        pm = self.config.pluginmanager
        n = len(getattr(pm, "_conftest_plugins", ()))
        if n == getattr(self, "_n_conftests", -1):
            return ()
        self._n_conftests = n
        return list(getattr(pm, "_conftest_plugins", ()))

    def loaded_conftest_files(self) -> list:
        """Every conftest module pytest has imported, as a path relative to the root (review R-056 W1)."""
        import os

        out = []
        for mod in getattr(self.config.pluginmanager, "_conftest_plugins", ()):
            f = getattr(mod, "__file__", None)
            if f:
                try:
                    out.append(os.path.relpath(f, self.root))
                except ValueError:  # another drive: keep the absolute path, it is still a stable key
                    out.append(f)
        return out

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

    def _after_session(self) -> None:
        self._write_quarantine()

    # refusals that are not a test's own non-file inputs (those of an earlier test, a file another test wrote, a code
    # change during the session). A test that did not pass is quarantined too: its flags are not evaluated (it is
    # not recorded) but carried into the tests after it
    _NOT_QUARANTINED = ("after an earlier test", "reads a file another test", "source changed")

    def _write_quarantine(self) -> None:
        """The tests this session refused for inputs of their own that are not files (a network connection, a
        process-state read, ...): the next ``-n`` plan runs their atoms on a worker of their own, so that no other
        test of a worker carries their refusal (the carried-set rule; ``schedule::ControllerInput::quarantine``)."""
        try:
            nc = self.sess.outcomes_data(self.cap).get("not_cached_ids") or {}
            # cumulative while refused: a quarantined test refused for a carried input (it runs after another
            # quarantined one) stays, else it would leave the quarantine worker and carry the refusal back out; one
            # that is recorded (or not run) leaves it
            prev = set(self.quarantine())
            ids = sorted(n for n, why in nc.items() if n in prev or not str(why).startswith(self._NOT_QUARANTINED))
            os.makedirs(self.dir, exist_ok=True)
            tmp = os.path.join(self.dir, f"quarantine.json.{os.getpid()}")
            with open(tmp, "w") as fh:
                json.dump({"run": self.run_id, "tests": ids}, fh)
            os.replace(tmp, os.path.join(self.dir, "quarantine.json"))
        except Exception:
            pass

    def quarantine(self) -> list:
        try:
            with open(os.path.join(self.dir, "quarantine.json")) as fh:
                return list(json.load(fh).get("tests") or ())
        except (OSError, ValueError, AttributeError):
            return []

    SUMMARY_FILE = "summary.txt"

    def terminal_summary(self, tr) -> None:
        """The cache's summary, printed and written to ``<cache>/summary.txt`` (audit G-0412: a project that replaces
        pytest's terminal reporter can swallow every line a plugin prints; the file keeps the summary, a 0-entry store's
        reasons included, reachable)."""
        rec = _SummaryRecorder(tr)
        try:
            self._terminal_summary(rec)
        finally:
            self.summary_saved = True
            text = "\n".join(rec.lines) + "\n"

            def save(path=os.path.join(self.dir, self.SUMMARY_FILE)):
                try:
                    with open(path + f".tmp{os.getpid()}", "w") as fh:
                        fh.write(text)
                    os.replace(path + f".tmp{os.getpid()}", path)
                except OSError:
                    pass

            _core.detpy_probe_call(save)

    def _terminal_summary(self, tr) -> None:
        found = self.placement_findings()
        if found:
            if getattr(self, "real_clock", False):
                tr.section("detpy REAL-CLOCK FINDINGS: outcomes on the real clock differ from the virtual day", red=True)
                for nid, want, got in found:
                    tr.write_line(f"real clock: {nid}: {got} on the real clock, {want} on the virtual day with the "
                                  f"same inputs (it depends on the real date or time)", red=True)
            else:
                how = "-n" if self.role == "controller" else "--det-isolate"
                tr.section(f"detpy PLACEMENT FINDINGS: outcomes under {how} differ from the serial run", red=True)
                for nid, want, got in found:
                    tr.write_line(f"placement: {nid}: {got} here, {want} in a serial session with the same inputs "
                                  f"(it depends on another test's in-process state or on its worker)", red=True)
        rf = getattr(self, "replay_findings", None) or {}
        if rf:
            tr.section("detpy PLACEMENT FINDINGS: tests that fail only when their file runs in its own process",
                       yellow=True)
            for nid in sorted(rf):
                tr.write_line(f"placement: {rf[nid]}", yellow=True)
        tr.section("detpy cache with proof")
        for text, markup in self.summary_lines(getattr(tr.config.option, "verbose", 0)):
            tr.write_line(text, **({markup: True} if markup else {}))
        fo = getattr(self.cap, "follower", None)
        why = getattr(fo, "why_not", None) if fo is not None else None
        if why and why != "--det-cache-no-follow":
            # audit G-1544: processes started at import, collection or start-up are followed with strace; without
            # it, the tests after them are refused for "subprocess" and nothing said why
            tr.write_line(f"processes started outside a test are not followed ({why}): install strace so that the "
                          f"tests after them can be reused", yellow=True)
        m = self.merge_result
        if m is not None:
            tr.write_line(f"parallel: decided once in the controller; {m['merged']} entries merged from the workers' "
                          f"shards, {len(m['dropped'])} dropped by the cross-worker write rule, {len(m['stale'])} "
                          f"reused results dropped (inputs written by this session), {m.get('edges', 0)} together "
                          f"edge(s) noted for the next plans"
                          + (f"; UNREADABLE shards: {len(m['unreadable'])}" if m["unreadable"] else ""))
            if "proven" in m:
                tr.write_line(f"parallel vs serial (P5): {m['proven']} entr(ies) proven equal to the serial result "
                              f"(reusable by serial sessions), {len(m['diverged'])} diverged (not stored: the serial "
                              f"entry stays), {m['unproven']} unproven (no stable serial fingerprint under their key)")


class _NoTerminal:
    def __init__(self, config):
        self.config = config

    def section(self, *a, **kw):
        pass

    def write_line(self, *a, **kw):
        pass


class _SummaryRecorder:
    """The terminal reporter as the cache's summary sees it: every section and line also kept in ``lines``."""

    def __init__(self, tr):
        self._tr = tr
        self.lines: list = []
        self.config = tr.config

    def section(self, title, *a, **kw):
        self.lines.append(f"== {title} ==")
        return self._tr.section(title, *a, **kw)

    def write_line(self, text, **kw):
        self.lines.append(str(text))
        return self._tr.write_line(text, **kw)

    def __getattr__(self, name):
        return getattr(self._tr, name)


def _location_of(nodeid: str) -> tuple:
    """A report location for a test reported by the xdist controller (which has no items): the file, no line, the
    rest of the node id as the domain."""
    path, _, rest = nodeid.partition("::")
    return (path, None, rest.replace("::", ".") or path)



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
    CAPTURE = start_capture(str(early_config.rootpath), ns.det_cache, not getattr(ns, "det_cache_no_follow", False),
                            bool(getattr(ns, "det_cache_dists", False)))


def install(config) -> None:
    """Register the plugin hooks (from ``pytest_configure``)."""
    global PLUGIN
    cap = CAPTURE
    if cap is None or PLUGIN is not None:
        return
    opt = config.option
    plugin = ProofCachePlugin(cap, opt.det_cache, opt.det_cache_verify, opt.det_cache_receipts)
    plugin.shared = getattr(opt, "det_cache_shared", None) or os.environ.get("DETPY_CACHE_SHARED") or None
    plugin.keys_path = getattr(opt, "det_cache_keys", None)
    age = getattr(opt, "det_cache_max_age", 30.0)
    plugin.max_age_s = age * 86400 if age and age > 0 else None
    from . import xdist as _xdist

    if _xdist.worker_id(config) is not None:
        plugin.role, plugin.worker = "worker", _xdist.worker_id(config)
    elif _xdist.is_controller(config):
        plugin.role = "controller"
    plugin.configure(config)
    if getattr(opt, "det_plan_worker", None):
        plugin.store.set_parallel()  # one worker's list of a parallel plan: its results are parallel results
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
