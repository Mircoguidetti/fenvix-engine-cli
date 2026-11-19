"""pytest plugin: deterministic execution (Level 0), enabled with ``--det``."""

from __future__ import annotations

import datetime as _dt
import json
import os
import platform
import sys
import warnings

import pytest

from . import __version__, _core, _sites, _state, clock, fsorder, network, proofcache, reexec, seeds, sqlvirt
from . import xdist as _xdist
from ._patch import Patcher

# --det-outcomes: the outcome of a test from its phase outcomes (Rust; the Python original is
# tests/rust_hotpaths_ref/_ref_plugin_helpers.py)
_det_outcome = _core.det_outcome

CONTROLS = ("order", "seeds", "hashseed", "bytecode", "time", "fs", "net")
_PATCHER = Patcher()
_INFRA_PREFIXES = ("_pytest", "pytest", "pluggy", "detpy", "_hypothesis_pytestplugin", "xdist", "execnet")
_CONFLICTING_PLUGINS = ("randomly", "random_order", "pytest_randomly", "random-order")


def pytest_addoption(parser, pluginmanager):
    _accept_blocked_plugin_options(parser, pluginmanager)
    g = parser.getgroup("detpy", "deterministic execution (Level 0)")
    g.addoption("--det", action="store_true", default=False, help="enable deterministic execution (Level 0)")
    g.addoption("--det-seed", type=int, default=None, metavar="N",
                help="reproducible shuffle of the test order and seed of every generator (default: fixed order, seed 0)")
    g.addoption("--det-order", default=None, metavar="FILE",
                help="run exactly the test ids listed in FILE (one per line), in that order; other tests are "
                     "deselected. With --det-seed the seed still drives every generator, not the order "
                     "(replay bundles written by `detpy repro`)")
    g.addoption("--det-plan", default=None, metavar="FILE",
                help="with -n: run the worker assignment of an earlier parallel run (.detpy/plan.json); with "
                     "--det-plan-worker=gwK and no -n: run worker K's list of that plan serially, in one process, "
                     "with that worker's xdist identity")
    g.addoption("--det-plan-worker", default=None, metavar="GWK",
                help="with --det-plan, without -n: the worker whose list to replay")
    g.addoption("--det-trace", default=None, metavar="PATH",
                help="where to write the execution trace (default: <rootdir>/.detpy/trace.jsonl)")
    g.addoption("--det-compare", default=None, metavar="TRACE",
                help="compare fingerprints with a previous trace and report tests not covered by Level 0")
    g.addoption("--det-record", action="store_true", default=False,
                help="allow external network access and record responses into the cassette")
    g.addoption("--det-cassette", default=None, metavar="PATH",
                help="network cassette (default: <rootdir>/.detpy/cassette.json); replayed when present")
    g.addoption("--det-allow-host", action="append", default=[], metavar="HOST",
                help="external host that may be reached (repeatable)")
    g.addoption("--det-epoch", default="auto", metavar="ISO",
                help="wall-clock value at the start of every test (default auto: the commit time of the "
                     f"checked-out git HEAD, else {_FALLBACK_EPOCH})")
    g.addoption("--det-tick", type=int, default=1000, metavar="NS",
                help="nanoseconds the virtual clock advances on every read (default 1000)")
    g.addoption("--det-tick-adapt", type=int, default=8, metavar="N",
                help="double the tick after N consecutive clock reads with no other event (0 = fixed tick)")
    g.addoption("--det-sleep", choices=("virtual", "real"), default="virtual",
                help="virtual: time.sleep only advances the clock; real: it also waits")
    g.addoption("--det-disable", default="", metavar="LIST",
                help=f"comma separated controls to turn off: {','.join(CONTROLS)}")
    g.addoption("--det-urandom", action="store_true", default=False,
                help="also make os.urandom/uuid4/secrets deterministic (beyond Level 0; NOT for crypto tests)")
    g.addoption("--det-keep-aslr", action="store_true", default=False,
                help="do not disable address space randomisation when re-executing")
    g.addoption("--det-no-reexec", action="store_true", default=False,
                help="never re-exec the interpreter to fix PYTHONHASHSEED")
    g.addoption("--det-max-events", type=int, default=10_000, metavar="N",
                help="events stored verbatim per test (the fingerprint always covers all of them)")
    g.addoption("--det-outcomes", default=None, metavar="PATH",
                help="write {nodeid: outcome} as JSON (works without --det; used by the harness)")
    g.addoption("--det-cache", default=None, metavar="DIR",
                help="cache with proof (needs --det, Python 3.12+): reuse a test's previous result from DIR only "
                     "when every input it depended on (code executed, files read, environment variables read, "
                     "runtime, configuration) is unchanged; failures are never reused; prints a receipt")
    g.addoption("--det-cache-verify", type=float, default=0.0, metavar="FRACTION",
                help="run this random fraction of the reusable tests anyway and compare with the cached result")
    g.addoption("--det-cache-no-follow", action="store_true", default=False,
                help="with --det-cache: never cache a test that starts a process (default: the processes run under "
                     "strace and their files, program and environment become inputs of the test)")
    g.addoption("--det-cache-max-age", type=float, default=30.0, metavar="DAYS",
                help="with --det-cache: never reuse a result recorded more than DAYS ago on the real clock (default "
                     "30; 0 = no limit). Bounds real-clock reads detpy cannot see (C code such as TLS validity)")
    g.addoption("--det-cache-epoch-window", type=float, default=30.0, metavar="DAYS",
                help="with --det-cache and --det-epoch=auto: keep the cache's epoch while the HEAD commit time is at "
                     "most DAYS later (default 30), so tests that read the clock are reusable across commits")
    g.addoption("--det-cache-shared", default=None, metavar="DIR",
                help="with --det-cache: a store shared with other sessions and machines (a directory every job "
                     "sees; also DETPY_CACHE_SHARED). Candidates are fetched before the reuse decision and checked "
                     "like local entries; this session's entries are pushed at the end (by the controller under -n)")
    g.addoption("--det-cache-receipts", default=None, metavar="PATH",
                help="where to write the per-test receipts (JSON lines; default DIR/receipts.jsonl)")
    _early_reexec(parser, pluginmanager)


_BLOCKED_BY_REEXEC: list[str] | None = None

def _blocked_from_env() -> list[str]:
    """Plugins the re-exec blocked, read once and removed from os.environ.

    The variable is meant for this process only: left in the environment it
    reached every pytest the tests start, which then accepted the blocked
    plugin's options instead of rejecting them (review R-001 recheck, N3).
    """
    global _BLOCKED_BY_REEXEC
    if _BLOCKED_BY_REEXEC is None:
        raw = os.environ.pop(reexec.BLOCKED_ENV, "")
        _BLOCKED_BY_REEXEC = [n for n in raw.split(",") if n]
    return _BLOCKED_BY_REEXEC


def _early_reexec(parser, pluginmanager) -> None:
    """parallel-proof round 3, item 4: the re-exec as early as detpy is registered.

    The re-exec (fixed hash seed, ASLR off, bytecode cache) used to happen in ``pytest_load_initial_conftests``,
    after pytest had imported every entry-point plugin: on litellm (logfire, ddtrace, ...) the controller imported
    them twice (MEASURED 2.8 s per run, REPORT-2). pytest calls detpy's ``pytest_addoption`` while it loads the
    entry points, right after detpy's own; the remaining plugins are not imported yet. Here the command line is
    known (``invocation_params.args``, ``PYTEST_ADDOPTS`` and the ini ``addopts``, which pytest has read by then,
    in pytest's order), and the same decision as before is made from it. Anything unusual (a nested in-process
    session, an xdist worker, options that do not parse) leaves the decision to ``pytest_load_initial_conftests``,
    as before."""
    if reexec.SESSION_DEPTH > 0 or S.active or os.environ.get(_xdist.CONTROLLER_ENV) is not None:
        return
    if os.environ.get(reexec.MARKER) == "1":
        return
    config = pluginmanager.get_plugin("pytestconfig")
    if config is None:
        return
    try:
        import shlex

        args = list(config.invocation_params.args)
        env = os.environ.get("PYTEST_ADDOPTS")
        if env:
            args = [*shlex.split(env), *args]
        try:
            ini = config.getini("addopts")
        except (ValueError, KeyError):
            ini = []
        args = [*ini, *args]
        if any(a in ("-h", "--help", "--version", "-V") for a in args):
            return
        ns = parser.parse_known_args(args)
    except Exception:
        return
    if not getattr(ns, "det", False) or getattr(ns, "det_no_reexec", False):
        return
    try:
        controls = _controls(ns)
    except pytest.UsageError:
        return  # reported later, where the session can show it
    if "hashseed" not in controls:
        return
    want_bytecode = "bytecode" in controls
    need = reexec.plan(_hashseed(ns), not ns.det_keep_aslr, want_bytecode)
    if not any(need.values()):
        return
    ok, _why = reexec.can_reexec()
    if not ok:
        return
    try:
        from importlib.metadata import entry_points

        eps = entry_points()
        eps = eps.select(group="pytest11") if hasattr(eps, "select") else eps.get("pytest11", ())
        installed = {ep.name for ep in eps}
    except Exception:  # pragma: no cover - broken metadata
        installed = set()
    block = [n for n in _CONFLICTING_PLUGINS if n in installed or pluginmanager.get_plugin(n) is not None]
    rootdir = str(config.rootpath) if hasattr(config, "rootpath") else os.getcwd()
    reexec.reexec(_hashseed(ns), not ns.det_keep_aslr, want_bytecode, rootdir, block)  # no return


def _accept_blocked_plugin_options(parser, pluginmanager) -> None:
    """Keep the options of plugins blocked by the re-exec (pytest-randomly...) valid.

    The re-exec passes ``-p no:randomly`` so the plugin never loads, but a project
    may name its options in addopts (``--randomly-seed=...``,
    ``--randomly-dont-reorganize``): without the plugin pytest rejects them and no
    test runs (review R-001). Register exactly the options the blocked plugin
    defines, by calling its own ``pytest_addoption``: they parse and do nothing,
    because none of the plugin's hooks or fixtures is registered.
    """
    names = _blocked_from_env()
    if not names:
        return
    import inspect

    try:
        from importlib.metadata import entry_points

        eps = entry_points()
        eps = eps.select(group="pytest11") if hasattr(eps, "select") else eps.get("pytest11", ())
    except Exception:  # pragma: no cover - broken metadata
        return
    for ep in eps:
        if ep.name not in names or not pluginmanager.is_blocked(ep.name):
            continue
        try:
            mod = ep.load()
            hook = getattr(mod, "pytest_addoption", None)
            if hook is None:
                continue
            kwargs = {"parser": parser, "pluginmanager": pluginmanager}
            params = inspect.signature(hook).parameters
            hook(**{k: v for k, v in kwargs.items() if k in params})
        except Exception as exc:  # the options stay unknown: pytest reports them
            import warnings

            warnings.warn(f"detpy: could not register the options of blocked plugin {ep.name!r}: {exc!r}")


# ---------------------------------------------------------------------------
# Session-level state of the plugin (one pytest session per process normally).
class _Session:
    def __init__(self):
        self.active = False
        self.reexec_status = "not-needed"
        self.order: list[str] = []
        self.order_digest = None
        self.trace_path = None
        self.config = None
        self.fingerprints: dict[str, str] = {}
        self.order_missing: list[str] = []
        self.compare_report = None
        self.net_mode = None
        self.disabled_plugins: list[str] = []
        self.adjustments: list[str] = []
        self.rebound: list[str] = []
        self.saved_cassette = 0
        self.index = 0
        self.rewrite_cache = False
        # pytest-xdist under --det (xdist.py): the controller's state, or this worker's id
        self.controller = None
        self.worker = None
        self.cassette_out = None
        self.plan_ids: list[str] | None = None


S = _Session()


def _controls(ns) -> frozenset:
    off = {c.strip() for c in (getattr(ns, "det_disable", "") or "").split(",") if c.strip()}
    unknown = off - set(CONTROLS)
    if unknown:
        raise pytest.UsageError(f"--det-disable: unknown control(s) {sorted(unknown)}; known: {CONTROLS}")
    return frozenset(CONTROLS) - off


_PLUGIN_PACKAGES: set = set()


def _skip_module(name: str, mod) -> bool:
    """Modules whose references to real clock objects must not be rebound.

    Besides the standard library and pytest itself, third-party pytest plugins
    are test infrastructure (pytest-benchmark, pytest-timeout, ...): they keep
    real timers, otherwise time-calibrated loops would spin on virtual time.
    """
    top = name.split(".", 1)[0]
    if top in _INFRA_PREFIXES or top.startswith("pytest_") or top in _PLUGIN_PACKAGES:
        return True
    f = getattr(mod, "__file__", None)
    if not f:
        return True  # builtins / namespace packages
    kind, _ = _sites._classify(f)
    return kind != _sites._USER


_FALLBACK_EPOCH = "2025-01-01T00:00:00+00:00"
EPOCH_SOURCE = {"source": "default"}


def _head_commit_time(root: str) -> int | None:
    """Commit time (seconds) of the git HEAD containing ``root``, or None."""
    import subprocess

    try:
        p = subprocess.run(["git", "log", "-1", "--format=%ct"], cwd=root, capture_output=True, text=True,
                           timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    out = p.stdout.strip()
    return int(out) if p.returncode == 0 and out.isdigit() else None


def _epoch_ns(text: str, root: str) -> int:
    """--det-epoch: an ISO time, or "auto" = the HEAD commit time (T2).

    A test written at a commit may take dates before the commit as past; a fixed
    epoch older than the commit made such tests fail only under --det. The commit
    time is a pure function of the checkout and never later than the real time.
    """
    if text == "auto":
        ct = _head_commit_time(root)
        if ct is not None:
            EPOCH_SOURCE.update(source="git HEAD commit time", value=ct)
            return ct * 1_000_000_000
        EPOCH_SOURCE.update(source="fixed default (no git HEAD)", value=_FALLBACK_EPOCH)
        text = _FALLBACK_EPOCH
    else:
        EPOCH_SOURCE.update(source="--det-epoch", value=text)
    return _parse_epoch(text)


def _epoch_for(ns, root: str) -> int:
    """The session's epoch. Under ``--det-cache`` with ``--det-epoch=auto`` it is the cache's epoch: the HEAD commit
    time when the cache took it, kept while HEAD is at most ``--det-cache-epoch-window`` days later. The epoch is a
    configuration input of every test that reads the clock; one that moved at every commit made those tests (and,
    through a clock read at import time, every test) unreusable from one commit to the next."""
    ns_epoch = _epoch_ns(ns.det_epoch, root)
    cache = getattr(ns, "det_cache", None)
    if cache and ns.det_epoch == "auto" and EPOCH_SOURCE.get("source") == "git HEAD commit time":
        window = getattr(ns, "det_cache_epoch_window", 30.0)
        kept = proofcache.cache_epoch(cache, ns_epoch, int(window * 86400 * 1_000_000_000))
        if kept != ns_epoch:
            EPOCH_SOURCE.update(source="cache epoch (HEAD commit time when the cache took it)",
                                value=kept // 1_000_000_000, head=ns_epoch // 1_000_000_000)
        return kept
    return ns_epoch


def _parse_epoch(text: str) -> int:
    try:
        d = _dt.datetime.fromisoformat(text)
    except ValueError as e:
        raise pytest.UsageError(f"--det-epoch: {e}")
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    delta = d - _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


def _hashseed(ns) -> str:
    return str((ns.det_seed or 0) % 4294967296)


def _hashseed_value() -> str:
    return str(_state.STATE.config.seed % 4294967296)


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(early_config, parser, args):
    reexec.SESSION_DEPTH += 1
    if os.environ.get(_xdist.CONTROLLER_ENV) is not None:
        _xdist.restore_controller_env()  # an xdist worker of a --det controller
    ns = early_config.known_args_namespace
    if not getattr(ns, "det", False):
        return
    if S.active:
        # A pytest session nested in-process inside a --det session (pytester
        # inline runs, pytest.main() from a test) runs under the outer controls.
        warnings.warn("detpy: nested in-process pytest session: it runs under the outer --det session")
        return
    controls = _controls(ns)
    if getattr(ns, "det_cache", None) and not proofcache.AVAILABLE:
        raise pytest.UsageError("--det-cache needs Python 3.12+ (sys.monitoring)")
    want_bytecode = "bytecode" in controls
    if "hashseed" in controls:
        need = reexec.plan(_hashseed(ns), not ns.det_keep_aslr, want_bytecode)
        if any(need.values()):
            ok, why = reexec.can_reexec()
            if ok and not ns.det_no_reexec:
                # pytest already redirected fd 1/2 for early capture: restore
                # them, otherwise the new process writes into a lost temp file.
                capman = early_config.pluginmanager.getplugin("capturemanager")
                if capman is not None:
                    capman.stop_global_capturing()
                rootdir = str(early_config.rootpath) if hasattr(early_config, "rootpath") else os.getcwd()
                block = [n for n in _CONFLICTING_PLUGINS if early_config.pluginmanager.get_plugin(n) is not None]
                reexec.reexec(_hashseed(ns), not ns.det_keep_aslr, want_bytecode, rootdir, block)  # no return
            reason = "--det-no-reexec" if ns.det_no_reexec else why
            if need["hashseed"]:
                S.reexec_status = f"PYTHONHASHSEED not fixed ({reason})"
            else:
                missing = [k for k in ("aslr", "bytecode") if need[k]]
                S.reexec_status = f"hash seed fixed; not applied: {','.join(missing)} ({reason})"
        else:
            S.reexec_status = "ok"
    if "time" in controls:
        # pytest-benchmark: the adaptive tick lets calibration terminate, but the
        # number of rounds is then max_time / (virtual) duration, unrelated to
        # CPU cost. Keep benchmarks running, with the minimum number of rounds.
        pm = early_config.pluginmanager
        if pm.hasplugin("benchmark") and not any(a.startswith("--benchmark-max-time") for a in args):
            args.append("--benchmark-max-time=0.000001")
            S.adjustments.append("pytest-benchmark: --benchmark-max-time=0.000001 (min rounds)")
    if getattr(ns, "det_plan_worker", None):
        _replay_worker_identity(early_config, ns)
    _install(early_config, ns, controls)
    if getattr(ns, "det_cache", None):
        proofcache.start(early_config, ns)


def _replay_worker_identity(config, ns) -> None:
    """``--det-plan=FILE --det-plan-worker=gwK`` (no ``-n``): worker K's list, and the xdist identity its tests saw
    (``PYTEST_XDIST_*`` variables set before conftests are imported; ``worker_id`` / ``testrun_uid`` fixtures)."""
    if not ns.det_plan:
        raise pytest.UsageError("--det-plan-worker needs --det-plan")
    if getattr(ns, "numprocesses", None):
        raise pytest.UsageError("--det-plan-worker replays one worker in one process: drop -n")
    ids, count, uid = _xdist.replay_worker(ns.det_plan, ns.det_plan_worker)
    S.plan_ids = ids
    os.environ["PYTEST_XDIST_WORKER"] = ns.det_plan_worker
    os.environ["PYTEST_XDIST_WORKER_COUNT"] = str(count)
    if uid:
        os.environ["PYTEST_XDIST_TESTRUNUID"] = uid
    config.pluginmanager.register(_xdist.PlanWorkerReplay(ns.det_plan_worker, count, uid), "detpy-plan-worker")
    S.adjustments.append(f"--det-plan-worker: replaying {ns.det_plan_worker}'s {len(ids)} tests of {ns.det_plan}")


def _install(config, ns, controls) -> None:
    cfg = _state.Config(
        seed=ns.det_seed or 0,
        shuffle=ns.det_seed is not None and not getattr(ns, "det_order", None),
        epoch_ns=_epoch_for(ns, str(config.rootpath) if hasattr(config, "rootpath") else os.getcwd()),
        tick_ns=max(0, ns.det_tick),
        tick_adapt=max(0, ns.det_tick_adapt),
        sleep=ns.det_sleep,
        controls=controls,
        record_net=ns.det_record,
        allow_hosts=tuple(ns.det_allow_host),
        control_urandom=ns.det_urandom,
        max_events=ns.det_max_events,
    )
    _state.STATE.config = cfg
    _sites.refresh(str(config.rootpath) if hasattr(config, "rootpath") else None)
    S.active = True
    S.config = config
    # Plugins that reorder tests or reseed `random` with their own seed would
    # undo Level 0: switch them off.
    pm = config.pluginmanager
    # Normally blocked with -p no:<name> by the re-exec, before they load.
    S.disabled_plugins.extend(_blocked_from_env())
    for name in _CONFLICTING_PLUGINS:
        if pm.get_plugin(name) is not None:
            # Fallback without re-exec: hooks are removed, but fixtures the
            # plugin defined may stay active (documented limit).
            pm.unregister(name=name)
            S.disabled_plugins.append(name + " (unregistered after loading)")
    if "seeds" in controls:
        seeds.install(_PATCHER, cfg.control_urandom)
    for plugin in pm.get_plugins():
        modname = getattr(plugin, "__name__", None)
        if isinstance(modname, str) and modname not in ("__main__",) and hasattr(plugin, "__file__"):
            _PLUGIN_PACKAGES.add(modname.split(".", 1)[0])
    _PLUGIN_PACKAGES.discard("conftest")
    if "time" in controls:
        S.rebound = clock.install(_PATCHER, cfg.epoch_ns, cfg.tick_ns, _skip_module, cfg.tick_adapt)
        sqlvirt.install(_PATCHER)  # SQLite's 'now', CURRENT_TIMESTAMP, random(), randomblob() per connection
    if "fs" in controls:
        fsorder.install(_PATCHER)
    if "bytecode" in controls and reexec.bytecode_active(_hashseed_value()):
        S.rewrite_cache = _cache_rewritten_tests(config)
    else:
        _hash_checked_imports(config)


def _hash_checked_imports(config) -> bool:
    """Review R-019b N5: under ``--det`` without the bytecode control (``--det-no-reexec``, ``--det-disable``, or no
    re-exec possible), validate the bytecode of every imported project module by its source's hash.

    With the control, the import system reads only the precompile's checked-hash pycs (``reexec``), which it
    validates by hash itself. Without it, it uses the project's ``__pycache__``, whose timestamp pycs are valid for
    ``(int(mtime), size)``: after a same-size edit checked out within the same second, the previous version's
    bytecode runs, and the proof key (from the source) pairs the new source with the old outcome (a cached false
    pass). ``SourceFileLoader.get_code`` is patched for project sources (under the rootdir, without the precompile's
    excluded names): a pyc is used only when it is a hash-based pyc of exactly the current source; otherwise the
    source is compiled and, when bytecode may be written, cached as a checked-hash pyc (which plain Python also
    validates by hash). The decision and the hash are in Rust (``_core.HashCheckedPycs``); this is the importlib
    interface. Other modules (libraries) keep the import system's own check."""
    try:
        import importlib.util
        from importlib import _bootstrap_external as be
        from importlib.machinery import SourceFileLoader

        variant = reexec._hash_variant()
        compile_bytecode, code_to_hash_pyc = be._compile_bytecode, be._code_to_hash_pyc
        cache_from_source, magic = importlib.util.cache_from_source, importlib.util.MAGIC_NUMBER
    except (ImportError, AttributeError):
        return False
    root = str(config.rootpath) if hasattr(config, "rootpath") else os.getcwd()
    check = _core.HashCheckedPycs(os.path.abspath(root), list(reexec._EXCLUDE_NAMES), magic,
                                  int.from_bytes(magic, "little"), *(variant or (1, 3)))
    real = SourceFileLoader.get_code

    def get_code(self, fullname):
        path = self.get_filename(fullname)
        if variant is None:  # the Rust hash is not the interpreter's: never read a project pyc
            if not check.applies(path):
                return real(self, fullname)
            with open(path, "rb") as fh:
                return self.source_to_code(fh.read(), path)
        try:
            cfile = cache_from_source(path)
        except NotImplementedError:
            cfile = None
        got = check(path, cfile)
        if got is None:
            return real(self, fullname)
        source, source_hash, data = got
        if data is not None:
            try:
                return compile_bytecode(memoryview(data)[16:], name=fullname, bytecode_path=cfile, source_path=path)
            except (ImportError, EOFError):
                pass
        code = self.source_to_code(source, path)
        if cfile is not None and not sys.dont_write_bytecode:
            try:
                self._cache_bytecode(path, cfile, code_to_hash_pyc(code, source_hash, True))
            except NotImplementedError:
                pass
        return code

    _PATCHER.set(SourceFileLoader, "get_code", get_code)
    return True


def _cache_rewritten_tests(config, patcher=None) -> bool:
    """Keep pytest's assertion-rewritten test modules (and conftests) in the deterministic bytecode cache.

    Under ``--det`` the interpreter runs with ``PYTHONDONTWRITEBYTECODE=1`` and ``PYTHONPYCACHEPREFIX`` set to the
    precompile's cache: pytest looks for its rewritten pycs there but never writes them, so every test module was
    parsed, rewritten and compiled again at every run (click: ~12 % of a fully reused run, MEASURED). pytest >= 9
    keeps them as checked-hash pycs (``_read_pyc`` compares the source's hash before use), so a stale one never
    runs; detpy writes them with pytest's own writer. The module then runs from the marshalled code in the first
    run too (``marshal.loads``), as it does in every later run: a set constant has one layout in every run.

    pytest's own check covers the source, the interpreter (magic number, cache tag) and pytest's version only, but
    the rewritten code also depends on the configuration (``enable_assertion_pass_hook``), the optimisation level
    and the rewriter itself (review R-017 H1: a run with the option loaded the code an earlier run wrote without
    it). So under ``--det`` pytest reads, and detpy writes, these pycs under a name keyed on all of that
    (``_rewrite_key``): a run only ever loads code that its own configuration would have produced. A rewriter
    replaced by a plugin is not keyed: nothing is read or written then. The pytest-named pycs (written by earlier
    versions of detpy without the key) are never read under ``--det``.
    Older pytest versions write timestamp pycs (``(mtime, size)``: stale same-size edits, review R-015): for them
    detpy reads and writes its own format under the same keyed name, validated by a SHA-256 of the interpreter's
    magic number and the source (review R-023: without it every ``--det`` session and every ``-n`` worker rewrote
    every test module). ``DETPY_REWRITE_CACHE=0`` turns the cache off (no read, no write)."""
    if _EARLY_REWRITE_CACHE[0]:
        return True  # installed when detpy was imported (before the plugins' modules were rewritten)
    patcher = patcher or _PATCHER
    try:
        import marshal

        from _pytest.assertion import rewrite as rw

        # pytest >= 9.2 reads checked-hash pycs; DETPY_REWRITE_OWN=1 uses detpy's own format anyway (tests)
        hashed = (b"\x03\x00\x00\x00" in rw._read_pyc.__code__.co_consts
                  and os.environ.get("DETPY_REWRITE_OWN") != "1")
        real, read_pyc, write_pyc, cache_dir_of, tail, ext, key = (
            rw._rewrite_test, rw._read_pyc, rw._write_pyc, rw.get_cache_dir, rw.PYC_TAIL, rw.PYC_EXT,
            rw.assertstate_key)
        originals = (rw.rewrite_asserts, rw.AssertionRewriter)
    except (ImportError, AttributeError):
        return False
    enabled = os.environ.get("DETPY_REWRITE_CACHE", "1") != "0"
    memo: list = []

    def keyed_tail(config):
        """The pyc tail for this run, or None when the rewrite cannot be keyed (nothing is read or written).

        Review R-017b F1: the key holds a digest of the rewriter as loaded (``_rewriter_digest``), so a plugin or
        conftest that patches a method of ``AssertionRewriter`` (or a helper of ``rewrite.py``) gets its own pycs.
        It is re-checked at each read and write by the identity of the namespaces' values (cheap): a conftest
        loaded later that patches the rewriter changes the key from then on."""
        if not enabled or (rw.rewrite_asserts, rw.AssertionRewriter) != originals:
            return None
        snap = _rewriter_snapshot(rw)
        if not memo or memo[0] != snap or memo[2] is not config:
            memo[:] = [snap, _rewrite_key(config, rw), config]
        k = memo[1]
        return None if k is None else tail[:-len(ext)] + ".det-" + k + ext

    import hashlib
    from importlib.util import MAGIC_NUMBER

    def _own_check(source_bytes: bytes) -> bytes:
        return hashlib.sha256(MAGIC_NUMBER + source_bytes).digest()

    def _read_pyc(source, pyc, trace=lambda x: None):
        config = _REWRITE_CONFIG[0]
        if config is None:
            return None
        t = keyed_tail(config)
        name = pyc.name
        if t is None or not name.endswith(tail):
            return None
        path = pyc.with_name(name[:-len(tail)] + t)
        if hashed:
            return read_pyc(source, path, trace)
        # pytest < 9.2 writes timestamp pycs ((mtime, size): a same-size edit in the same second keeps the old code,
        # review R-015). detpy's own format instead: a header, the SHA-256 of (interpreter magic, source), the code.
        # Review R-023 (speed): without a cache every --det session, and every worker of --det -n, rewrote every
        # test module again (litellm: about a third of its collection).
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            if data[:8] != _OWN_MAGIC or data[8:40] != _own_check(source.read_bytes()):
                return None
            return marshal.loads(data[40:])
        except (OSError, ValueError, EOFError, TypeError):
            return None

    def _rewrite_test(fn, config):
        stamp, co = real(fn, config)
        t = keyed_tail(config)
        if t is None:
            return stamp, co
        cache_dir = cache_dir_of(fn)
        target = cache_dir / (fn.name[:-3] + t)
        try:
            os.makedirs(cache_dir, exist_ok=True)
            if hashed:
                write_pyc(config.stash[key], co, stamp, target)
            else:
                body = _OWN_MAGIC + _own_check(fn.read_bytes()) + marshal.dumps(co)
                tmp = f"{target}.{os.getpid()}"
                with open(tmp, "wb") as fh:
                    fh.write(body)
                os.replace(tmp, target)
        except (OSError, KeyError):
            pass
        return stamp, marshal.loads(marshal.dumps(co))

    real_exec = rw.AssertionRewritingHook.exec_module

    def exec_module(self, module):
        # the configuration this hook rewrites for: _read_pyc has no config argument
        prev, _REWRITE_CONFIG[0] = _REWRITE_CONFIG[0], getattr(self, "config", None)
        try:
            return real_exec(self, module)
        finally:
            _REWRITE_CONFIG[0] = prev

    patcher.set(rw, "_read_pyc", _read_pyc)
    patcher.set(rw, "_rewrite_test", _rewrite_test)
    patcher.set(rw.AssertionRewritingHook, "exec_module", exec_module)
    return enabled


_REWRITE_CONFIG: list = [None]
_EARLY_REWRITE_CACHE = [False]


def _early_rewrite_cache() -> None:
    """Review R-023 (speed): in a re-executed ``--det`` process (``DETPY_REEXEC=1``: the controller after its re-exec
    and every xdist worker), install the rewritten-module cache when detpy is imported, before pytest imports the
    other plugins' modules: those are rewritten too, and ``PYTHONDONTWRITEBYTECODE`` stops pytest from caching them.
    The cache is keyed on the configuration of the hook that rewrites (``_rewrite_key``) and validated by hash, so
    installing it before ``--det`` is parsed is safe; it stays installed for the process."""
    if os.environ.get("DETPY_REEXEC") != "1" or os.environ.get("DETPY_REWRITE_CACHE", "1") == "0":
        return
    from ._patch import Patcher

    try:
        _EARLY_REWRITE_CACHE[0] = _cache_rewritten_tests(None, Patcher())
    except Exception:
        _EARLY_REWRITE_CACHE[0] = False


_OWN_MAGIC = b"DETPYRW1"  # detpy's rewritten-module cache format (pytest < 9.2), see _cache_rewritten_tests


def _rewrite_key(config, rw) -> str | None:
    """A digest of everything pytest's assertion rewrite depends on besides the source and the interpreter/pytest
    version (which pytest's pyc check and name already cover): the ``enable_assertion_pass_hook`` ini option (the
    one configuration value ``AssertionRewriter`` reads), the optimisation level ``compile`` uses, and the
    rewriter's own source. None (no cache) when one of them cannot be read."""
    import hashlib

    try:
        hook = bool(config.getini("enable_assertion_pass_hook"))
        with open(rw.__file__, "rb") as fh:
            code = hashlib.sha256(fh.read()).hexdigest()
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    loaded = _rewriter_digest(rw)
    if loaded is None:
        return None
    parts = f"pass_hook={hook}\noptimize={sys.flags.optimize}\nrewriter={code}\nloaded={loaded}\n"
    return hashlib.sha256(parts.encode()).hexdigest()[:16]


def _rewriter_snapshot(rw) -> tuple:
    """The identity of what the rewrite runs (compared at each read and write): ``rewrite_asserts``,
    ``AssertionRewriter``, and the values of their module's and the class's namespaces."""
    cls = rw.AssertionRewriter
    return (rw.rewrite_asserts, cls, tuple(vars(cls).values()), tuple(vars(rw).values()))


_MODULE_METADATA = frozenset({"__builtins__", "__file__", "__cached__", "__loader__", "__spec__"})
_SIMPLE = (str, bytes, int, float, complex, bool, type(None), type(Ellipsis))


def _rewriter_digest(rw, limit: int = 5000) -> str | None:
    """Review R-017b F1: a digest of pytest's assertion rewriter *as loaded*, stable across runs.

    It covers ``rewrite_asserts`` and every value of ``rewrite.py``'s namespace and of ``AssertionRewriter``'s (by
    name). A function is its code (bytecode, constants, names, recursively; not its file name or line numbers, so
    two installs of the same pytest share pycs), its defaults, its closure cells and the globals its code names.
    Functions are followed wherever they are defined (a plugin's replacement method, and the original it wraps
    from its closure); a function's globals are followed within its own module (a plugin's helpers), other
    modules' objects are named. A class of ``rewrite.py`` (or of the referring function's module) is its name,
    bases and namespace; other classes are named. A constant is its ``repr``, a module its name, anything else its
    type. None (no cache) past ``limit`` objects."""
    import hashlib
    import types

    h = hashlib.sha256()
    seen: dict = {}
    todo: list = []
    home = rw.__name__

    def name(v) -> str:
        return f"{getattr(v, '__module__', None)}.{getattr(v, '__qualname__', '?')}"

    def ref(v, mod: str | None) -> str:
        """A token for ``v``; objects to follow are queued and named by their order. ``mod``: the module whose
        classes and functions are followed (None: functions always)."""
        if isinstance(v, _SIMPLE):
            return f"{type(v).__name__}:{v!r}"
        if isinstance(v, (tuple, list, frozenset, set)):
            items = [ref(x, mod) for x in v]
            if isinstance(v, (frozenset, set)):
                items.sort()
            return f"{type(v).__name__}({','.join(items)})"
        if isinstance(v, dict):
            return "dict(" + ",".join(sorted(f"{ref(k, mod)}={ref(x, mod)}" for k, x in v.items())) + ")"
        if isinstance(v, (staticmethod, classmethod)):
            return f"{type(v).__name__}({ref(v.__func__, None)})"
        if isinstance(v, property):
            return f"property({ref(v.fget, None)},{ref(v.fset, None)},{ref(v.fdel, None)})"
        if isinstance(v, types.ModuleType):
            return f"module:{v.__name__}"
        if isinstance(v, (types.BuiltinFunctionType, types.MethodWrapperType, types.WrapperDescriptorType)):
            return f"builtin:{name(v)}"
        m = getattr(v, "__module__", None)
        if m == __name__:  # detpy's own wrappers (_read_pyc, _rewrite_test): they do not change the code
            return f"named:{name(v)}"
        if isinstance(v, type):
            follow = m == home or m == mod
        elif isinstance(v, types.FunctionType) or hasattr(v, "__wrapped__"):
            follow = mod is None or m == mod or m == home
        else:
            return f"other:{type(v).__module__}.{type(v).__qualname__}"
        if not follow:
            return f"named:{name(v)}"
        if id(v) not in seen:
            seen[id(v)] = (len(seen), v)
            todo.append(v)
        return f"obj#{seen[id(v)][0]}"

    def code(co) -> str:
        consts = ",".join(code(c) if isinstance(c, types.CodeType) else ref(c, None) for c in co.co_consts)
        return (f"code({co.co_qualname}|{co.co_argcount},{co.co_posonlyargcount},{co.co_kwonlyargcount},"
                f"{co.co_flags}|{co.co_code.hex()}|{','.join(co.co_names)}|{','.join(co.co_varnames)}|"
                f"{','.join(co.co_freevars)}|{','.join(co.co_cellvars)}|{consts})")

    def names(co):
        yield from co.co_names
        for c in co.co_consts:
            if isinstance(c, types.CodeType):
                yield from names(c)

    h.update(f"rewrite_asserts={ref(rw.rewrite_asserts, None)}\nclass={ref(rw.AssertionRewriter, None)}\n".encode())
    for n in sorted(vars(rw)):
        if n not in _MODULE_METADATA:  # where it was loaded from: not what it does
            h.update(f"rw.{n}={ref(vars(rw)[n], None)}\n".encode())
    while todo:
        if len(seen) > limit:
            return None
        v = todo.pop(0)
        i = seen[id(v)][0]
        if isinstance(v, type):
            body = ";".join(f"{n}={ref(x, None)}" for n, x in sorted(vars(v).items(), key=lambda kv: kv[0])
                            if n not in ("__dict__", "__weakref__"))
            bases = ",".join(ref(b, v.__module__) for b in v.__bases__)
            h.update(f"#{i}=class {name(v)}({bases}){{{body}}}\n".encode())
            continue
        f = inspect_unwrap(v)
        co = getattr(f, "__code__", None)
        if co is None:
            h.update(f"#{i}=callable {type(v).__module__}.{type(v).__qualname__}\n".encode())
            continue
        cells = ",".join(ref(c.cell_contents, None) if _cell_full(c) else "empty" for c in (f.__closure__ or ()))
        g, fm = f.__globals__, f.__module__
        glob = ",".join(f"{n}={ref(g[n], fm)}" for n in sorted(set(names(co)) - _MODULE_METADATA) if n in g)
        h.update(f"#{i}=function {code(co)} defaults={ref(f.__defaults__, None)} kw={ref(f.__kwdefaults__, None)} "
                 f"cells=({cells}) globals=({glob})\n".encode())
    return h.hexdigest()[:16]


def inspect_unwrap(v):
    """``v`` itself when it has code; else what it wraps (``functools.lru_cache`` and the like)."""
    for _ in range(10):
        if hasattr(v, "__code__") or not hasattr(v, "__wrapped__"):
            return v
        v = v.__wrapped__
    return v


def _cell_full(cell) -> bool:
    try:
        cell.cell_contents
    except ValueError:
        return False
    return True


def _owner(config) -> bool:
    return S.active and config is S.config


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    out = config.getoption("det_outcomes", None)
    if config.getoption("det_cache", None) and not config.getoption("det", False):
        raise pytest.UsageError("--det-cache needs --det (the cache relies on Level 0 controls)")
    if _owner(config):
        config.pluginmanager.register(_DetSession(config, out), "detpy-session")
        _configure_det(config)
    elif out:
        config.pluginmanager.register(_Outcomes(out), "detpy-outcomes")


def _configure_det(config) -> None:
    # pytest-xdist: the controller plans and merges, each worker writes its own trace (xdist.py)
    wid = _xdist.worker_id(config)
    if wid is not None:
        S.worker = wid
        config.pluginmanager.register(_xdist.Worker(config, wid), "detpy-xdist-worker")
    elif _xdist.is_controller(config):
        ctl = _xdist.Controller(config, S)
        if getattr(config.option, "testrunuid", None) is None:
            config.option.testrunuid = _xdist.derived_testrunuid(config, _state.STATE.config.seed)
        ctl.testrunuid = config.option.testrunuid
        _xdist.export_controller_env(ctl.barrier)
        S.controller = ctl
        config.pluginmanager.register(ctl, "detpy-xdist-controller")
    root = str(config.rootpath)
    _sites.refresh(root)
    opt = config.option
    cassette = opt.det_cassette or os.path.join(root, ".detpy", "cassette.json")
    _state.STATE.config.cassette_path = cassette
    if "net" in _state.STATE.config.controls:
        S.net_mode = network.install(_PATCHER, opt.det_record, cassette, opt.det_allow_host)
    S.trace_path = opt.det_trace or os.path.join(root, ".detpy", "trace.jsonl")
    if S.worker is not None:
        S.trace_path = _xdist.worker_path(S.trace_path, S.worker)
        if opt.det_record:
            S.cassette_out = _xdist.worker_path(cassette, S.worker)
    _state.STATE.recorder = _core.Recorder(max_events=opt.det_max_events)
    if opt.det_cache:
        proofcache.install(config)
    factory = getattr(config, "_tmp_path_factory", None)
    if factory is not None:
        def basetemp():
            bt = getattr(factory, "_basetemp", None)
            return str(bt) if bt is not None else None
        _sites.set_basetemp_provider(basetemp)


def pytest_unconfigure(config):
    reexec.SESSION_DEPTH = max(0, reexec.SESSION_DEPTH - 1)
    if _owner(config):
        _PATCHER.undo_all()
        clock.uninstall()
        sqlvirt.uninstall()
        seeds.uninstall()
        network.uninstall()
        _state.STATE.recorder = None
        _state.STATE.nodeid = None
        _sites.set_basetemp_provider(None)
        proofcache.uninstall()
        S.active = False
        S.config = None
        if S.controller is not None:
            os.environ.pop(_xdist.CONTROLLER_ENV, None)
        S.controller = None
        S.worker = None


def _exception_of(report) -> list:
    """[exception type, phase, first line of the message, crash path:line] of a failed report."""
    crash = getattr(getattr(report, "longrepr", None), "reprcrash", None)
    message = getattr(crash, "message", None) or str(getattr(report, "longrepr", "") or "")
    first = message.strip().splitlines()[0] if message.strip() else ""
    head = first.split(":", 1)[0].strip()
    etype = head.rsplit(".", 1)[-1] if head and " " not in head else "AssertionError" if first.startswith("assert") else "unknown"
    where = f"{getattr(crash, 'path', '')}:{getattr(crash, 'lineno', '')}" if crash is not None else ""
    return [etype, report.when, first[:200], where]


def _explicit_order(config, items: list, path: str, wanted: list | None = None) -> list:
    """``--det-order``: the listed ids in the listed order; the rest is deselected."""
    source = "--det-order" if wanted is None else "--det-plan"
    if wanted is None:
        with open(path) as f:
            wanted = [line.rstrip("\n") for line in f if line.strip() and not line.startswith("#")]
    by_id = {i.nodeid: i for i in items}
    chosen = [by_id[n] for n in wanted if n in by_id]
    missing = [n for n in wanted if n not in by_id]
    keep = {id(i) for i in chosen}
    dropped = [i for i in items if id(i) not in keep]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    S.order_missing = missing
    if missing:
        S.adjustments.append(f"{source}: {len(missing)} listed test ids not collected")
    return chosen


class _Outcomes:
    """Per-config collector of test outcomes (``--det-outcomes``), with or without --det.

    Registered on one config's plugin manager only, so a pytest session nested
    in the same process never mixes its reports into ours.
    """

    def __init__(self, path):
        self.path = path
        self.outcomes: dict[str, str] = {}
        self.parts: dict[str, dict] = {}
        self.exceptions: dict[str, list] = {}

    def pytest_runtest_logreport(self, report):
        if hasattr(report, "wasxfail"):
            o = "xfailed" if report.skipped else "xpassed"
        else:
            o = report.outcome
        parts = self.parts.setdefault(report.nodeid, {})
        parts[report.when] = o
        self.outcomes[report.nodeid] = _det_outcome(parts.get("setup"), parts.get("call"), parts.get("teardown"))
        if report.failed and report.nodeid not in self.exceptions:
            self.exceptions[report.nodeid] = _exception_of(report)

    def pytest_sessionfinish(self, session, exitstatus):
        if not self.path or hasattr(session.config, "workerinput"):
            return  # xdist worker: the controller writes the file
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({"outcomes": self.outcomes, "exceptions": self.exceptions, "exitstatus": int(exitstatus),
                       "order": [i.nodeid for i in getattr(session, "items", [])], **self.extra()}, f)

    def extra(self) -> dict:
        return {}


def _keep_django_groups(config, ordered):
    """Re-apply pytest-django's grouping to detpy's order, in place.

    pytest-django stable-sorts the items like Django's runner: TestCase (rollback)
    tests first, then transactional tests (TransactionTestCase, transaction=True,
    which flush the database), then tests without a database. Running a flushing
    test before TestCase tests deletes the rows created by data migrations, so the
    TestCase tests fail under --det although they pass normally. The grouping is a
    stable sort, a pure function of its input: calling pytest-django's own hook on
    detpy's (fixed or seeded) order keeps the group order as a constraint, keeps
    detpy's order inside each group, and stays deterministic. Returns True when
    the grouping moved a test."""
    plugin = config.pluginmanager.get_plugin("django")
    hook = getattr(plugin, "pytest_collection_modifyitems", None)
    if hook is None:
        return False
    grouped = list(ordered)
    try:
        hook(items=grouped)
    except Exception:  # pragma: no cover - never break collection on a pytest-django change
        return False
    if sorted(map(id, grouped)) != sorted(map(id, ordered)):  # pragma: no cover - not a pure reorder
        return False
    changed = any(a is not b for a, b in zip(grouped, ordered))
    ordered[:] = grouped
    return changed


class _DetSession(_Outcomes):
    """Hooks of the --det session, bound to the config that activated Level 0."""

    def __init__(self, config, outcomes_path):
        super().__init__(outcomes_path)
        self.config = config

    def extra(self) -> dict:
        cfg = _state.STATE.config
        out = {"fingerprints": dict(S.fingerprints), "seed": cfg.seed, "shuffle": cfg.shuffle,
               "controls": sorted(cfg.controls), "trace": S.trace_path, "order_missing": S.order_missing}
        pc = proofcache.PLUGIN
        if pc is not None:
            out["cache"] = pc.outcomes_data()
        if S.controller is not None:
            out["order"] = list(S.order)
            out["plan"] = S.controller.plan
        return out

    def pytest_report_header(self, config):
        cfg = _state.STATE.config
        order = f"shuffled with seed {cfg.seed}" if cfg.shuffle else "fixed (collection order)"
        lines = [
            f"detpy {__version__}: Level 0 active; controls={','.join(sorted(cfg.controls))}; order {order}",
            f"detpy: PYTHONHASHSEED={os.environ.get('PYTHONHASHSEED')} ({S.reexec_status}); "
            f"ASLR {'off' if reexec.aslr_disabled() else 'on'}; network={S.net_mode}; sleep={cfg.sleep}",
        ]
        if S.disabled_plugins:
            lines.append(f"detpy: disabled conflicting plugins: {', '.join(S.disabled_plugins)}")
        if S.adjustments:
            lines.append(f"detpy: adjusted: {'; '.join(S.adjustments)}")
        if S.controller is not None:
            lines.extend(S.controller.header_lines())
        return lines

    # Ordering ---------------------------------------------------------------
    @pytest.hookimpl(hookwrapper=True)
    def pytest_collection_modifyitems(self, session, config, items):
        original = list(items)
        yield
        if "order" not in _state.STATE.config.controls:
            return
        # Undo reorderings done by other plugins, keep their deselection.
        remaining = {id(i) for i in items}
        ordered = [i for i in original if id(i) in remaining]
        known = {id(i) for i in ordered}
        ordered += [i for i in items if id(i) not in known]
        cfg = _state.STATE.config
        if cfg.shuffle:
            perm = _core.shuffle_order([i.nodeid for i in ordered], cfg.seed)
            ordered = [ordered[p] for p in perm]
        if _keep_django_groups(config, ordered):
            note = "pytest-django: test groups kept (TestCase, then transactional, then non-db)"
            if note not in S.adjustments:
                S.adjustments.append(note)
        # An explicit order (replay bundle) is run exactly as listed.
        order_file = config.getoption("det_order", None)
        if order_file:
            ordered = _explicit_order(config, ordered, order_file)
        elif S.plan_ids is not None:
            ordered = _explicit_order(config, ordered, config.getoption("det_plan"), S.plan_ids)
        items[:] = ordered

    def pytest_collection_finish(self, session):
        S.order = [i.nodeid for i in session.items]
        S.order_digest = _core.order_digest(S.order)
        cfg = _state.STATE.config
        meta = {
            "detpy": __version__,
            "seed": cfg.seed,
            "shuffle": cfg.shuffle,
            "controls": sorted(cfg.controls),
            "hashseed": os.environ.get("PYTHONHASHSEED"),
            "reexec": S.reexec_status,
            "aslr_disabled": reexec.aslr_disabled(),
            "bytecode": ("precompiled" if reexec.bytecode_active(_hashseed_value()) else "default"),
            "precompile_s": (float(os.environ[reexec.PRECOMPILE_ENV]) if reexec.PRECOMPILE_ENV in os.environ
                             else None),
            "tick_adapt": cfg.tick_adapt,
            "epoch_ns": cfg.epoch_ns,
            "epoch_source": EPOCH_SOURCE.get("source"),
            "tick_ns": cfg.tick_ns,
            "sleep": cfg.sleep,
            "network": S.net_mode,
            "urandom_controlled": cfg.control_urandom,
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": sys.platform,
            "pytest": pytest.__version__,
            "disabled_plugins": S.disabled_plugins,
            "adjustments": S.adjustments,
            "rebound_references": len(S.rebound),
            "order_digest": S.order_digest,
        }
        if S.worker is not None:
            meta["worker"] = S.worker
        _state.STATE.recorder.open(S.trace_path, json.dumps(meta), S.order)

    # Per-test control ---------------------------------------------------------
    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item, nextitem):
        st = _state.STATE
        rec = st.recorder
        if rec is None:  # pragma: no cover - defensive: never break the session
            yield
            return
        pc = proofcache.PLUGIN
        receipt = pc.sess.hit(item.nodeid) if pc is not None else None
        if receipt is not None:
            # reused with proof: nothing runs, the recorded fingerprint stands for the test
            yield
            fp = receipt.get("fingerprint")
            if fp:
                S.fingerprints[item.nodeid] = fp
            return
        controls = st.config.controls
        rec.begin_test(item.nodeid, S.index)
        S.index += 1
        _state.reset_threads()
        if "time" in controls:
            clock.start_test()
        st.nodeid = item.nodeid
        if "seeds" in controls:
            seeds.start_test(_PATCHER, item.nodeid)
        if "net" in controls:
            network.start_test()
        try:
            yield
        finally:
            if "seeds" in controls:
                seeds.end_test()
            if "net" in controls:
                network.end_test()
            st.nodeid = None
            fp = rec.end_test(self.outcomes.get(item.nodeid, "unknown"))
            if fp is not None:
                S.fingerprints[item.nodeid] = fp
                item.user_properties.append(("detpy_fingerprint", fp))

    def pytest_sessionfinish(self, session, exitstatus):
        st = _state.STATE
        if S.controller is not None:
            # xdist controller: no test ran here; merge the workers' traces (and cache shards, cassettes)
            S.controller.finish(session, S.trace_path, self._controller_meta())
        if proofcache.PLUGIN is not None:
            proofcache.PLUGIN.finish(session)
        super().pytest_sessionfinish(session, exitstatus)
        if st.recorder is not None and S.controller is None:
            if not S.order_digest:  # collection failed before the trace was opened
                st.recorder.open(S.trace_path, json.dumps({"detpy": __version__, "collection": "failed"}), [])
            st.recorder.close()
        if S.net_mode == "record" and S.controller is None:
            S.saved_cassette = network.save_recordings(S.cassette_out or st.config.cassette_path)
        baseline = session.config.getoption("det_compare")
        if baseline:
            try:
                S.compare_report = json.loads(_core.verify([baseline, S.trace_path]))
            except Exception as e:  # report, do not crash the session
                S.compare_report = {"error": str(e)}

    def _controller_meta(self) -> dict:
        """Header metadata of the merged trace (the controller's view; the workers' headers stay in their traces)."""
        cfg = _state.STATE.config
        return {
            "detpy": __version__, "seed": cfg.seed, "shuffle": cfg.shuffle, "controls": sorted(cfg.controls),
            "hashseed": os.environ.get("PYTHONHASHSEED"), "reexec": S.reexec_status,
            "aslr_disabled": reexec.aslr_disabled(), "epoch_ns": cfg.epoch_ns,
            "epoch_source": EPOCH_SOURCE.get("source"), "tick_ns": cfg.tick_ns, "tick_adapt": cfg.tick_adapt,
            "sleep": cfg.sleep, "network": S.net_mode, "urandom_controlled": cfg.control_urandom,
            "python": platform.python_version(), "implementation": platform.python_implementation(),
            "platform": sys.platform, "pytest": pytest.__version__, "disabled_plugins": S.disabled_plugins,
            "adjustments": S.adjustments, "order_digest": S.order_digest, "merged": True,
        }

    def pytest_terminal_summary(self, terminalreporter, exitstatus, config):
        tr = terminalreporter
        tr.section("detpy (Level 0)")
        cfg = _state.STATE.config
        tr.write_line(f"trace: {S.trace_path}  order digest: {S.order_digest}  seed: {cfg.seed}"
                      f"{' (shuffled)' if cfg.shuffle else ''}")
        if S.controller is not None:
            for line in S.controller.summary_lines():
                tr.write_line(line)
        if S.saved_cassette:
            tr.write_line(f"network: recorded {S.saved_cassette} test(s) into {cfg.cassette_path}")
        if proofcache.PLUGIN is not None:
            proofcache.PLUGIN.terminal_summary(tr)
        rep = S.compare_report
        if rep is None:
            return
        if "error" in rep:
            tr.write_line(f"compare: failed: {rep['error']}", red=True)
            return
        s = rep["summary"]
        tr.write_line(f"compare with {rep['labels'][0]}: covered={s['stable']} not-covered={s['diverged']} "
                      f"missing={s['missing']} outcome-unstable={s['outcome_unstable']}"
                      f"{'' if s['order_identical'] else ' (ORDER DIFFERS)'}")
        for t in rep["tests"]:
            d = t.get("divergence")
            if d and t["status"] == "diverged":
                tr.write_line(f"NOT COVERED by Level 0: {t['nodeid']} [{d['reason']}]", yellow=True)
                tr.write_line(f"    {d['description']}")


_early_rewrite_cache()
