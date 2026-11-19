"""Level 0 controls shared by every runner shell: the pytest plugin (``plugin.py``) and the runner-neutral driver
(``runners/``) call the same functions, in the same order.

What is here: the option table (``OPTIONS``: the same ``--det*`` options for pytest and for ``python -m detpy
<runner>``), the controls (``controls_of``), the epoch (``epoch_for``: the HEAD commit time, kept by the cache), the
hash seed, the installation of the clock, seeds, file-system order and bytecode controls (``install_controls``), the
network control and the recorder (``open_session``), the per-test bracket (``begin_test`` / ``end_test``), the trace
header (``trace_meta``) and the teardown (``uninstall``). What stays in each shell: how its own plugins are blocked
or kept, its own bytecode (pytest's assertion rewrite), its hooks.
"""

from __future__ import annotations

import datetime as _dt
import os
import platform
import sys

from . import __version__, _core, _sites, _state, clock, fsorder, network, reexec, seeds
from ._patch import Patcher

CONTROLS = ("order", "seeds", "hashseed", "bytecode", "time", "fs", "net")
PATCHER = Patcher()
INFRA_PREFIXES = ("_pytest", "pytest", "pluggy", "detpy", "_hypothesis_pytestplugin", "xdist", "execnet")
# top-level packages of the running shell's plugins (pytest plugins): test infrastructure, never rebound to the
# virtual clock (set by the shell)
INFRA_PACKAGES: set = set()
FALLBACK_EPOCH = "2025-01-01T00:00:00+00:00"
EPOCH_SOURCE = {"source": "default"}


class UsageError(Exception):
    """A wrong ``--det*`` option (the pytest shell raises it as ``pytest.UsageError``)."""


# The --det* options: (flags, keyword arguments of argparse's add_argument / pytest's addoption).
OPTIONS: list[tuple[tuple[str, ...], dict]] = [
    (("--det",), dict(action="store_true", default=False, help="enable deterministic execution (Level 0)")),
    (("--det-seed",), dict(type=int, default=None, metavar="N",
                           help="reproducible shuffle of the test order and seed of every generator (default: fixed "
                                "order, seed 0)")),
    (("--det-order",), dict(default=None, metavar="FILE",
                            help="run exactly the test ids listed in FILE (one per line), in that order; other tests "
                                 "are deselected. With --det-seed the seed still drives every generator, not the "
                                 "order (replay bundles written by `detpy repro`)")),
    (("--det-trace",), dict(default=None, metavar="PATH",
                            help="where to write the execution trace (default: <rootdir>/.detpy/trace.jsonl)")),
    (("--det-compare",), dict(default=None, metavar="TRACE",
                              help="compare fingerprints with a previous trace and report tests not covered by "
                                   "Level 0")),
    (("--det-record",), dict(action="store_true", default=False,
                             help="allow external network access and record responses into the cassette")),
    (("--det-cassette",), dict(default=None, metavar="PATH",
                               help="network cassette (default: <rootdir>/.detpy/cassette.json); replayed when "
                                    "present")),
    (("--det-allow-host",), dict(action="append", default=[], metavar="HOST",
                                 help="external host that may be reached (repeatable)")),
    (("--det-epoch",), dict(default="auto", metavar="ISO",
                            help="wall-clock value at the start of every test (default auto: the commit time of the "
                                 f"checked-out git HEAD, else {FALLBACK_EPOCH})")),
    (("--det-tick",), dict(type=int, default=1000, metavar="NS",
                           help="nanoseconds the virtual clock advances on every read (default 1000)")),
    (("--det-tick-adapt",), dict(type=int, default=8, metavar="N",
                                 help="double the tick after N consecutive clock reads with no other event (0 = "
                                      "fixed tick)")),
    (("--det-sleep",), dict(choices=("virtual", "real"), default="virtual",
                            help="virtual: time.sleep only advances the clock; real: it also waits")),
    (("--det-disable",), dict(default="", metavar="LIST",
                              help=f"comma separated controls to turn off: {','.join(CONTROLS)}")),
    (("--det-urandom",), dict(action="store_true", default=False,
                              help="also make os.urandom/uuid4/secrets deterministic (beyond Level 0; NOT for crypto "
                                   "tests)")),
    (("--det-keep-aslr",), dict(action="store_true", default=False,
                                help="do not disable address space randomisation when re-executing")),
    (("--det-no-reexec",), dict(action="store_true", default=False,
                                help="never re-exec the interpreter to fix PYTHONHASHSEED")),
    (("--det-max-events",), dict(type=int, default=10_000, metavar="N",
                                 help="events stored verbatim per test (the fingerprint always covers all of them)")),
    (("--det-outcomes",), dict(default=None, metavar="PATH",
                               help="write {nodeid: outcome} as JSON (works without --det; used by the harness)")),
    (("--det-cache",), dict(default=None, metavar="DIR",
                            help="cache with proof (needs --det, Python 3.12+): reuse a test's previous result from "
                                 "DIR only when every input it depended on (code executed, files read, environment "
                                 "variables read, runtime, configuration) is unchanged; failures are never reused; "
                                 "prints a receipt")),
    (("--det-cache-verify",), dict(type=float, default=0.0, metavar="FRACTION",
                                   help="run this random fraction of the reusable tests anyway and compare with the "
                                        "cached result")),
    (("--det-cache-no-follow",), dict(action="store_true", default=False,
                                      help="with --det-cache: never cache a test that starts a process (default: the "
                                           "processes run under strace and their files, program and environment "
                                           "become inputs of the test)")),
    (("--det-cache-max-age",), dict(type=float, default=30.0, metavar="DAYS",
                                    help="with --det-cache: never reuse a result recorded more than DAYS ago on the "
                                         "real clock (default 30; 0 = no limit). Bounds real-clock reads detpy "
                                         "cannot see (C code such as TLS validity)")),
    (("--det-cache-epoch-window",), dict(type=float, default=30.0, metavar="DAYS",
                                         help="with --det-cache and --det-epoch=auto: keep the cache's epoch while the "
                                              "HEAD commit time is at most DAYS later (default 30), so tests that read "
                                              "the clock are reusable across commits")),
    (("--det-cache-receipts",), dict(default=None, metavar="PATH",
                                     help="where to write the per-test receipts (JSON lines; default "
                                          "DIR/receipts.jsonl)")),
]


def controls_of(disable: str) -> frozenset:
    """The active controls: every control but the ``--det-disable`` ones."""
    off = {c.strip() for c in (disable or "").split(",") if c.strip()}
    unknown = off - set(CONTROLS)
    if unknown:
        raise UsageError(f"--det-disable: unknown control(s) {sorted(unknown)}; known: {CONTROLS}")
    return frozenset(CONTROLS) - off


def skip_module(name: str, mod) -> bool:
    """Modules whose references to real clock objects must not be rebound.

    Besides the standard library and detpy itself, the running shell's plugins (``INFRA_PACKAGES``: pytest plugins
    such as pytest-benchmark, pytest-timeout) are test infrastructure: they keep real timers, otherwise
    time-calibrated loops would spin on virtual time.
    """
    top = name.split(".", 1)[0]
    if top in INFRA_PREFIXES or top.startswith("pytest_") or top in INFRA_PACKAGES:
        return True
    f = getattr(mod, "__file__", None)
    if not f:
        return True  # builtins / namespace packages
    kind, _ = _sites._classify(f)
    return kind != _sites._USER


def head_commit_time(root: str) -> int | None:
    """Commit time (seconds) of the git HEAD containing ``root``, or None."""
    import subprocess

    try:
        p = subprocess.run(["git", "log", "-1", "--format=%ct"], cwd=root, capture_output=True, text=True,
                           timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    out = p.stdout.strip()
    return int(out) if p.returncode == 0 and out.isdigit() else None


def epoch_ns(text: str, root: str) -> int:
    """--det-epoch: an ISO time, or "auto" = the HEAD commit time (T2).

    A test written at a commit may take dates before the commit as past; a fixed
    epoch older than the commit made such tests fail only under --det. The commit
    time is a pure function of the checkout and never later than the real time.
    """
    if text == "auto":
        ct = head_commit_time(root)
        if ct is not None:
            EPOCH_SOURCE.update(source="git HEAD commit time", value=ct)
            return ct * 1_000_000_000
        EPOCH_SOURCE.update(source="fixed default (no git HEAD)", value=FALLBACK_EPOCH)
        text = FALLBACK_EPOCH
    else:
        EPOCH_SOURCE.update(source="--det-epoch", value=text)
    return parse_epoch(text)


def epoch_for(ns, root: str) -> int:
    """The session's epoch. Under ``--det-cache`` with ``--det-epoch=auto`` it is the cache's epoch: the HEAD commit
    time when the cache took it, kept while HEAD is at most ``--det-cache-epoch-window`` days later. The epoch is a
    configuration input of every test that reads the clock; one that moved at every commit made those tests (and,
    through a clock read at import time, every test) unreusable from one commit to the next."""
    ns_epoch = epoch_ns(ns.det_epoch, root)
    cache = getattr(ns, "det_cache", None)
    if cache and ns.det_epoch == "auto" and EPOCH_SOURCE.get("source") == "git HEAD commit time":
        window = getattr(ns, "det_cache_epoch_window", 30.0)
        kept = _core.cache_epoch(cache, ns_epoch, int(window * 86400 * 1_000_000_000))  # Rust: identity.rs
        if kept != ns_epoch:
            EPOCH_SOURCE.update(source="cache epoch (HEAD commit time when the cache took it)",
                                value=kept // 1_000_000_000, head=ns_epoch // 1_000_000_000)
        return kept
    return ns_epoch


def parse_epoch(text: str) -> int:
    try:
        d = _dt.datetime.fromisoformat(text)
    except ValueError as e:
        raise UsageError(f"--det-epoch: {e}")
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    delta = d - _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


def hashseed(seed: int | None) -> str:
    return str((seed or 0) % 4294967296)


def hashseed_value() -> str:
    return str(_state.STATE.config.seed % 4294967296)


def reexec_status(ns, controls, root: str, block: list[str], before_exec=None) -> str:
    """The hash-seed re-exec (``reexec``): exec the same command line again under the fixed hash seed (and ASLR off,
    deterministic bytecode) when needed and possible; does not return then. Returns the status line otherwise.
    ``before_exec`` runs just before the exec (pytest restores its captured file descriptors)."""
    if "hashseed" not in controls:
        return "not-needed"
    want_bytecode = "bytecode" in controls
    need = reexec.plan(hashseed(ns.det_seed), not ns.det_keep_aslr, want_bytecode)
    if not any(need.values()):
        return "ok"
    ok, why = reexec.can_reexec()
    if ok and not ns.det_no_reexec:
        if before_exec is not None:
            before_exec()
        reexec.reexec(hashseed(ns.det_seed), not ns.det_keep_aslr, want_bytecode, root, block)  # no return
    reason = "--det-no-reexec" if ns.det_no_reexec else why
    if need["hashseed"]:
        return f"PYTHONHASHSEED not fixed ({reason})"
    missing = [k for k in ("aslr", "bytecode") if need[k]]
    return f"hash seed fixed; not applied: {','.join(missing)} ({reason})"


def make_config(ns, root: str, controls) -> _state.Config:
    """The Level 0 configuration of the session (``_state.STATE.config``)."""
    cfg = _state.Config(
        seed=ns.det_seed or 0,
        shuffle=ns.det_seed is not None and not getattr(ns, "det_order", None),
        epoch_ns=epoch_for(ns, root),
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
    return cfg


def install_controls(cfg: _state.Config, root: str | None) -> list:
    """Install the seeds, clock and file-system order controls (in this order). Returns the clock's rebound
    references."""
    _sites.refresh(root)
    controls = cfg.controls
    if "seeds" in controls:
        seeds.install(PATCHER, cfg.control_urandom)
    rebound: list = []
    if "time" in controls:
        rebound = clock.install(PATCHER, cfg.epoch_ns, cfg.tick_ns, skip_module, cfg.tick_adapt)
    if "fs" in controls:
        fsorder.install(PATCHER)
    return rebound


def hash_checked_imports(root: str) -> bool:
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

    PATCHER.set(SourceFileLoader, "get_code", get_code)
    return True


def open_session(root: str, cassette: str | None, record: bool, allow_hosts, max_events: int) -> str | None:
    """The network control (with its cassette) and the recorder. Returns the network mode."""
    cfg = _state.STATE.config
    cfg.cassette_path = cassette or os.path.join(root, ".detpy", "cassette.json")
    mode = None
    if "net" in cfg.controls:
        mode = network.install(PATCHER, record, cfg.cassette_path, allow_hosts)
    _state.STATE.recorder = _core.Recorder(max_events=max_events)
    return mode


def begin_test(nodeid: str, index: int) -> None:
    """A test starts (it runs, it is not reused): the recorder's bracket and every per-test control."""
    st = _state.STATE
    controls = st.config.controls
    st.recorder.begin_test(nodeid, index)
    _state.reset_threads()
    if "time" in controls:
        clock.start_test()
    st.nodeid = nodeid
    if "seeds" in controls:
        seeds.start_test(PATCHER, nodeid)
    if "net" in controls:
        network.start_test()


def end_test(outcome: str):
    """The test that ran ends with ``outcome``: returns its fingerprint (or None)."""
    st = _state.STATE
    controls = st.config.controls
    if "seeds" in controls:
        seeds.end_test()
    if "net" in controls:
        network.end_test()
    st.nodeid = None
    return st.recorder.end_test(outcome)


def trace_meta(status: str, net_mode, rebound: int, order_digest: str, runner: str, runner_version: str | None,
               disabled_plugins=(), adjustments=()) -> dict:
    """The trace header: the same fields for every runner (``runner`` names it; the pytest shell also writes
    ``pytest`` with its version)."""
    cfg = _state.STATE.config
    meta = {
        "detpy": __version__,
        "seed": cfg.seed,
        "shuffle": cfg.shuffle,
        "controls": sorted(cfg.controls),
        "hashseed": os.environ.get("PYTHONHASHSEED"),
        "reexec": status,
        "aslr_disabled": reexec.aslr_disabled(),
        "bytecode": ("precompiled" if reexec.bytecode_active(hashseed_value()) else "default"),
        "precompile_s": (float(os.environ[reexec.PRECOMPILE_ENV]) if reexec.PRECOMPILE_ENV in os.environ else None),
        "tick_adapt": cfg.tick_adapt,
        "epoch_ns": cfg.epoch_ns,
        "epoch_source": EPOCH_SOURCE.get("source"),
        "tick_ns": cfg.tick_ns,
        "sleep": cfg.sleep,
        "network": net_mode,
        "urandom_controlled": cfg.control_urandom,
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": sys.platform,
        "runner": runner,
    }
    if runner_version is not None:
        meta[runner] = runner_version
    meta.update({"disabled_plugins": list(disabled_plugins), "adjustments": list(adjustments),
                 "rebound_references": rebound, "order_digest": order_digest})
    return meta


def uninstall() -> None:
    PATCHER.undo_all()
    clock.uninstall()
    seeds.uninstall()
    network.uninstall()
    _state.STATE.recorder = None
    _state.STATE.nodeid = None
    _sites.set_basetemp_provider(None)
