"""pytest plugin: deterministic execution (Level 0), enabled with ``--det``."""

from __future__ import annotations

import datetime as _dt
import json
import os
import platform
import sys
import warnings

import pytest

from . import __version__, _core, _sites, _state, aio, clock, fsorder, network, reexec, seeds, threads
from ._patch import Patcher

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
    g.addoption("--det-async", action="store_true", default=False,
                help="Level 1 prototype: deterministic asyncio scheduling driven by a seed (needs --det)")
    g.addoption("--det-async-seed", type=int, default=None, metavar="N",
                help="seed of the asyncio scheduler (default: --det-seed; 0 = calm profile, no exploration)")
    g.addoption("--det-async-grace", type=float, default=1.0, metavar="S",
                help="real seconds an idle loop waits for foreign I/O or threads before its clock jumps")
    g.addoption("--det-async-wait", type=float, default=2.0, metavar="S",
                help="real seconds the loop waits for an executor job before giving up determinism for it")
    g.addoption("--det-async-settle", type=float, default=0.01, metavar="S",
                help="real seconds to batch near-simultaneous foreign wake-ups")
    g.addoption("--det-threads", action="store_true", default=False,
                help="Level 1 prototype: deterministic thread scheduling driven by a seed (needs --det)")
    g.addoption("--det-threads-seed", type=int, default=None, metavar="N",
                help="seed of the thread scheduler (default: --det-seed; 0 = calm profile, no exploration)")
    g.addoption("--det-threads-grace", type=float, default=1.0, metavar="S",
                help="real seconds an idle scheduler waits for work outside the process before a timer fires")
    g.addoption("--det-threads-deadlock", type=float, default=5.0, metavar="S",
                help="real seconds with only I/O waiters (or unmanaged threads) left before a deadlock is declared")
    g.addoption("--det-threads-preempt", type=int, default=200, metavar="N",
                help="exploring seeds only: mean number of user-code lines between preemptions (0 = off)")
    g.addoption("--det-outcomes", default=None, metavar="PATH",
                help="write {nodeid: outcome} as JSON (works without --det; used by the harness)")


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
    ns = early_config.known_args_namespace
    if not getattr(ns, "det", False):
        if getattr(ns, "det_async", False):
            raise pytest.UsageError("--det-async needs --det")
        if getattr(ns, "det_threads", False):
            raise pytest.UsageError("--det-threads needs --det")
        return
    if S.active:
        # A pytest session nested in-process inside a --det session (pytester
        # inline runs, pytest.main() from a test) runs under the outer controls.
        warnings.warn("detpy: nested in-process pytest session: it runs under the outer --det session")
        return
    controls = _controls(ns)
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
    _install(early_config, ns, controls)


def _install(config, ns, controls) -> None:
    cfg = _state.Config(
        seed=ns.det_seed or 0,
        shuffle=ns.det_seed is not None and not getattr(ns, "det_order", None),
        epoch_ns=_epoch_ns(ns.det_epoch, str(config.rootpath) if hasattr(config, "rootpath") else os.getcwd()),
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
    if "fs" in controls:
        fsorder.install(_PATCHER)
    if ns.det_async:
        seed = ns.det_async_seed if ns.det_async_seed is not None else (ns.det_seed or 0)
        aio.install(_PATCHER, seed, ns.det_async_grace, ns.det_async_wait, ns.det_async_settle,
                    str(config.rootpath) if hasattr(config, "rootpath") else os.getcwd())
    if getattr(ns, "det_threads", False):
        seed = ns.det_threads_seed if ns.det_threads_seed is not None else (ns.det_seed or 0)
        threads.install(_PATCHER, seed, ns.det_threads_grace, ns.det_threads_deadlock, ns.det_threads_preempt)


def _owner(config) -> bool:
    return S.active and config is S.config


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    out = config.getoption("det_outcomes", None)
    if _owner(config):
        config.pluginmanager.register(_DetSession(config, out), "detpy-session")
        _configure_det(config)
    elif out:
        config.pluginmanager.register(_Outcomes(out), "detpy-outcomes")


def _configure_det(config) -> None:
    if config.pluginmanager.get_plugin("dsession") is not None or getattr(config.option, "numprocesses", None):
        warnings.warn("detpy: pytest-xdist is not supported under --det (order is only fixed per worker)")
    root = str(config.rootpath)
    _sites.refresh(root)
    if aio.CFG.enabled:
        aio.refresh_prefixes(root)  # after plugins are imported
    opt = config.option
    cassette = opt.det_cassette or os.path.join(root, ".detpy", "cassette.json")
    _state.STATE.config.cassette_path = cassette
    if "net" in _state.STATE.config.controls:
        S.net_mode = network.install(_PATCHER, opt.det_record, cassette, opt.det_allow_host)
    S.trace_path = opt.det_trace or os.path.join(root, ".detpy", "trace.jsonl")
    _state.STATE.recorder = _core.Recorder(max_events=opt.det_max_events)
    factory = getattr(config, "_tmp_path_factory", None)
    if factory is not None:
        def basetemp():
            bt = getattr(factory, "_basetemp", None)
            return str(bt) if bt is not None else None
        _sites.set_basetemp_provider(basetemp)


def pytest_unconfigure(config):
    reexec.SESSION_DEPTH = max(0, reexec.SESSION_DEPTH - 1)
    if _owner(config):
        threads.uninstall()
        _PATCHER.undo_all()
        clock.uninstall()
        aio.uninstall()
        seeds.uninstall()
        network.uninstall()
        _state.STATE.recorder = None
        _state.STATE.nodeid = None
        _sites.set_basetemp_provider(None)
        S.active = False
        S.config = None


def _final_outcome(parts: dict) -> str:
    setup, call, teardown = parts.get("setup"), parts.get("call"), parts.get("teardown")
    if setup is not None and setup != "passed":
        main = setup if setup in ("skipped", "xfailed") else "error"
    elif call is not None:
        main = call
    else:
        main = "unknown"
    if teardown not in (None, "passed", "skipped"):
        main += "+teardown-error"
    return main


def _exception_of(report) -> list:
    """[exception type, phase, first line of the message, crash path:line] of a failed report."""
    crash = getattr(getattr(report, "longrepr", None), "reprcrash", None)
    message = getattr(crash, "message", None) or str(getattr(report, "longrepr", "") or "")
    first = message.strip().splitlines()[0] if message.strip() else ""
    head = first.split(":", 1)[0].strip()
    etype = head.rsplit(".", 1)[-1] if head and " " not in head else "AssertionError" if first.startswith("assert") else "unknown"
    where = f"{getattr(crash, 'path', '')}:{getattr(crash, 'lineno', '')}" if crash is not None else ""
    return [etype, report.when, first[:200], where]


def _explicit_order(config, items: list, path: str) -> list:
    """``--det-order``: the listed ids in the listed order; the rest is deselected."""
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
        S.adjustments.append(f"--det-order: {len(missing)} listed test ids not collected")
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
        self.outcomes[report.nodeid] = _final_outcome(parts)
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
        return {"fingerprints": dict(S.fingerprints), "seed": cfg.seed, "shuffle": cfg.shuffle,
                "controls": sorted(cfg.controls), "trace": S.trace_path, "order_missing": S.order_missing}

    def pytest_report_header(self, config):
        cfg = _state.STATE.config
        order = f"shuffled with seed {cfg.seed}" if cfg.shuffle else "fixed (collection order)"
        lines = [
            f"detpy {__version__}: Level 0 active; controls={','.join(sorted(cfg.controls))}; order {order}",
            f"detpy: PYTHONHASHSEED={os.environ.get('PYTHONHASHSEED')} ({S.reexec_status}); "
            f"ASLR {'off' if reexec.aslr_disabled() else 'on'}; network={S.net_mode}; sleep={cfg.sleep}",
        ]
        if aio.CFG.enabled:
            lines.append(f"detpy: --det-async (Level 1 prototype): asyncio scheduler seed {aio.CFG.seed}"
                         f"{' (calm)' if aio.CFG.seed == 0 else ' (exploring)'}")
        if threads.CFG.enabled:
            lines.append(f"detpy: --det-threads (Level 1 prototype): thread scheduler seed {threads.CFG.seed}"
                         f"{' (calm)' if threads.CFG.seed == 0 else ' (exploring)'}")
        if S.disabled_plugins:
            lines.append(f"detpy: disabled conflicting plugins: {', '.join(S.disabled_plugins)}")
        if S.adjustments:
            lines.append(f"detpy: adjusted: {'; '.join(S.adjustments)}")
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
        items[:] = ordered

    def pytest_collection_finish(self, session):
        S.order = [i.nodeid for i in session.items]
        S.order_digest = _core.order_digest(S.order)
        cfg = _state.STATE.config
        meta = {
            "detpy": __version__,
            "runtime": "python",
            "runtime_version": platform.python_version(),
            "runner": "pytest",
            "seed": cfg.seed,
            "shuffle": cfg.shuffle,
            "controls": sorted(cfg.controls | ({"async"} if aio.CFG.enabled else set())
                               | ({"threads"} if threads.CFG.enabled else set())),
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
            "det_async": ({"seed": aio.CFG.seed, "grace": aio.CFG.grace, "wait": aio.CFG.wait,
                           "settle": aio.CFG.settle} if aio.CFG.enabled else None),
            "det_threads": ({"seed": threads.CFG.seed, "grace": threads.CFG.grace,
                             "deadlock": threads.CFG.deadlock, "preempt": threads.CFG.preempt}
                            if threads.CFG.enabled else None),
            "order_digest": S.order_digest,
        }
        _state.STATE.recorder.open(S.trace_path, json.dumps(meta), S.order)

    # Per-test control ---------------------------------------------------------
    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item, nextitem):
        st = _state.STATE
        rec = st.recorder
        if rec is None:  # pragma: no cover - defensive: never break the session
            yield
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
        if threads.CFG.enabled:
            threads.activate()
            threads.start_test()
        try:
            yield
        finally:
            if threads.CFG.enabled:
                threads.end_test()
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
        super().pytest_sessionfinish(session, exitstatus)
        st = _state.STATE
        if st.recorder is not None:
            if not S.order_digest:  # collection failed before the trace was opened
                st.recorder.open(S.trace_path, json.dumps({"detpy": __version__, "collection": "failed"}), [])
            st.recorder.close()
        if S.net_mode == "record":
            S.saved_cassette = network.save_recordings(st.config.cassette_path)
        baseline = session.config.getoption("det_compare")
        if baseline:
            try:
                S.compare_report = json.loads(_core.verify([baseline, S.trace_path]))
            except Exception as e:  # report, do not crash the session
                S.compare_report = {"error": str(e)}

    def pytest_terminal_summary(self, terminalreporter, exitstatus, config):
        tr = terminalreporter
        tr.section("detpy (Level 0)")
        cfg = _state.STATE.config
        tr.write_line(f"trace: {S.trace_path}  order digest: {S.order_digest}  seed: {cfg.seed}"
                      f"{' (shuffled)' if cfg.shuffle else ''}")
        if S.saved_cassette:
            tr.write_line(f"network: recorded {S.saved_cassette} test(s) into {cfg.cassette_path}")
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
