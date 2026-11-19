"""The runner-neutral driver (``DetRun``): the lifecycle of a ``--det`` session for every Python runner other than
pytest, with the same calls into the same objects as the pytest plugin (``plugin.py`` + ``proofcache.py``):

1. options (``--det*``, the same table as pytest's: ``_level0.OPTIONS``), the hash-seed re-exec, the Level 0
   controls (``_level0``), the capture of inputs (``_proof.start_capture``) - ``start``;
2. the runner's configuration digest, the runtime identity, the proof store and the recorder - ``configure``;
3. ``collecting(rel)``: code the runner runs to load a test file (``load_tests``) is attributed to ``c|<file>``;
4. ``fixture(name)``: class / module / layer set-up recorded as an ``f|<scope>|<owner>|<name>`` context;
5. ``decide(ids, items, units)``: the trace is opened with the order, the reused tests are decided (receipts);
6. ``begin(id, fixtures)`` / ``report(id, when, outcome, ...)`` / ``end(id)``: the recorder's bracket, the per-test
   controls, ``CacheSession.start_test`` / ``report`` / ``end_test``, the capture's context;
7. ``finish(exit)``: record, receipts, trace, ``--det-outcomes``, the summary.

Test ids are ``<file relative to the root>::<Class>::<method>`` (``<file>::<name>`` for function and doctest
tests), as pytest's node ids, so traces and receipts look the same for every runner.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time

from .. import __version__, _core, _level0, _proof, _sites, _state, network, reexec

_perf = time.perf_counter
_det_outcome = _core.det_outcome


class UsageError(_level0.UsageError):
    pass


def parser(prog: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, add_help=False, allow_abbrev=False)
    for flags, kw in _level0.OPTIONS:
        p.add_argument(*flags, **kw)
    return p


def parse(argv: list[str], prog: str = "detpy") -> tuple[argparse.Namespace, list[str]]:
    """The ``--det*`` options anywhere in ``argv`` (``--det-seed 3`` and ``--det-seed=3``); the rest, in order, is the
    runner's command line."""
    det, rest = [], []
    takes_value = {f for flags, kw in _level0.OPTIONS for f in flags
                   if kw.get("action") not in ("store_true", "store_false")}
    i = 0
    while i < len(argv):
        a = argv[i]
        name = a.split("=", 1)[0]
        if a == "--":
            rest.extend(argv[i:])
            break
        if name.startswith("--det") and any(name == f for flags, _ in _level0.OPTIONS for f in flags):
            det.append(a)
            if name in takes_value and "=" not in a and i + 1 < len(argv):
                det.append(argv[i + 1])
                i += 1
        else:
            rest.append(a)
        i += 1
    ns = parser(prog).parse_args(det)
    return ns, rest


class _Report:
    """The phase report ``CacheSession.report`` reads (the attributes of a pytest ``TestReport`` it uses)."""

    def __init__(self, nodeid: str, when: str, outcome: str, longrepr=None, wasxfail: str | None = None):
        self.nodeid = nodeid
        self.when = when
        self.outcome = outcome
        self.skipped = outcome == "skipped"
        self.longrepr = longrepr
        self.user_properties: list = []
        if wasxfail is not None:
            self.wasxfail = wasxfail


class TestItem:
    """A test as the record sees it (``items``): ``obj`` marks a test whose own file is code (units, not its whole
    content)."""

    __slots__ = ("nodeid", "obj")

    def __init__(self, nodeid: str, obj=None):
        self.nodeid = nodeid
        self.obj = obj


class DoctestItem:
    """A doctest: the whole content of its file is its input (``CacheSession``'s ``is_whole``)."""

    __slots__ = ("nodeid",)

    def __init__(self, nodeid: str):
        self.nodeid = nodeid


class DetRun:
    """One session of a runner under ``--det`` (and ``--det-cache``)."""

    def __init__(self, runner: str, ns: argparse.Namespace, root: str | None = None):
        self.runner = runner
        self.ns = ns
        self.root = os.path.realpath(root or os.getcwd())
        self.det = bool(ns.det)
        self.status = "not-needed"
        self.cfg = None
        self.rebound: list = []
        self.cap = None
        self.proof: _proof.ProofSession | None = None
        self.net_mode = None
        self.trace_path = None
        self.order: list[str] = []
        self.order_digest = None
        self.order_missing: list[str] = []
        self.adjustments: list[str] = []
        self.fingerprints: dict[str, str] = {}
        self.parts: dict[str, dict] = {}
        self.outcomes: dict[str, str] = {}
        self.exceptions: dict[str, list] = {}
        self.times: dict[str, float] = {}
        self.hits: set[str] = set()
        self.index = 0
        self.current: str | None = None
        self._t0 = 0.0
        self.finished = False
        self.version = None
        self.compare_report = None
        self.saved_cassette = 0

    # -- start -----------------------------------------------------------------------------
    def start(self) -> None:
        """Before anything of the project is imported: re-exec, controls, capture."""
        ns = self.ns
        if ns.det_cache and not ns.det:
            raise UsageError("--det-cache needs --det (the cache relies on Level 0 controls)")
        if not self.det:
            return
        if ns.det_cache and not _proof.AVAILABLE:
            raise UsageError("--det-cache needs Python 3.12+ (sys.monitoring)")
        controls = _level0.controls_of(ns.det_disable)
        reexec.SESSION_DEPTH += 1
        self.status = _level0.reexec_status(ns, controls, self.root, [])
        self.cfg = _level0.make_config(ns, self.root, controls)
        self.rebound = _level0.install_controls(self.cfg, self.root)
        if not ("bytecode" in controls and reexec.bytecode_active(_level0.hashseed_value())):
            _level0.hash_checked_imports(self.root)
        if ns.det_cache:
            self.cap = _proof.start_capture(self.root, ns.det_cache, not ns.det_cache_no_follow)

    def configure(self, version: str | None, config: dict, infra_files=()) -> None:
        """The runner is known: its configuration (``config``: what of its command line and configuration can change
        a result), the network control, the recorder, the proof store. ``infra_files``: the runner's own modules
        (its discovery and its loop), whose own reads are not inputs (as pytest's are not)."""
        self.version = version
        if not self.det:
            return
        _sites.add_infra(infra_files)
        _sites.refresh(self.root)
        ns = self.ns
        self.net_mode = _level0.open_session(self.root, ns.det_cassette, ns.det_record, ns.det_allow_host,
                                             ns.det_max_events)
        self.trace_path = ns.det_trace or os.path.join(self.root, ".detpy", "trace.jsonl")
        if self.cap is not None:
            info = {"runner": self.runner, "runner_version": version, **_proof.level0_identity(),
                    "config": config}
            proof = _proof.ProofSession(self.cap, ns.det_cache, ns.det_cache_verify, ns.det_cache_receipts)
            age = ns.det_cache_max_age
            proof.max_age_s = age * 86400 if age and age > 0 else None
            proof.open(self.root, _proof.digest_identity(info), info)
            self.proof = proof
            self.cap.switch("s")

    def adjust(self, note: str) -> None:
        if note not in self.adjustments:
            self.adjustments.append(note)

    # -- contexts --------------------------------------------------------------------------
    def rel(self, path: str | None) -> str | None:
        if not path:
            return None
        try:
            return os.path.relpath(os.path.realpath(path), self.root).replace(os.sep, "/")
        except ValueError:
            return os.path.realpath(path)

    @contextlib.contextmanager
    def context(self, name: str):
        """Code inside runs in capture context ``name`` (``c|<file>``, ``f|<scope>|<owner>|<name>``)."""
        cap = self.cap
        if cap is None or not cap.active:
            yield
            return
        prev = cap.ctx
        cap.switch(name)
        try:
            yield
        finally:
            cap.switch(prev)

    def collecting(self, rel: str):
        return self.context("c|" + rel)

    @contextlib.contextmanager
    def own_work(self):
        """The runner's own machinery (not the project's code: ward building its test objects, which draws uuid4
        entropy): nothing inside is an input."""
        cap = self.cap
        if cap is None or not cap.active:
            yield
            return
        cap.active = False
        try:
            yield
        finally:
            cap.active = True

    # -- order and decisions ---------------------------------------------------------------------
    @property
    def ordered(self) -> bool:
        return self.det and "order" in self.cfg.controls

    def shuffle(self, names: list[str]) -> list[int]:
        """A permutation of ``names`` from the session's seed (the reproducible shuffle of ``--det-seed``)."""
        return list(_core.shuffle_order(list(names), self.cfg.seed))

    def explicit_order(self, ids: list[str]) -> list[str] | None:
        """``--det-order FILE``: the listed ids in the listed order (None: no such option)."""
        path = self.ns.det_order
        if not path:
            return None
        with open(path) as f:
            wanted = [line.rstrip("\n") for line in f if line.strip() and not line.startswith("#")]
        have = set(ids)
        self.order_missing = [n for n in wanted if n not in have]
        if self.order_missing:
            self.adjust(f"--det-order: {len(self.order_missing)} listed test ids not collected")
        return [n for n in wanted if n in have]

    def decide(self, ids: list[str], items: dict, units: list | None = None, opaque: set | None = None) -> set:
        """Every test is known, in run order: open the trace, decide reuse. ``units``: groups of ids reused together
        or not at all; ``opaque``: ids that always run (not decided). Returns the reused ids."""
        self.order = list(ids)
        if not self.det:
            return set()
        self.order_digest = _core.order_digest(self.order)
        meta = _level0.trace_meta(self.status, self.net_mode, len(self.rebound), self.order_digest, self.runner,
                                  self.version, (), self.adjustments)
        _state.STATE.recorder.open(self.trace_path, json.dumps(meta), self.order)
        if self.proof is None:
            return set()
        opaque = opaque or set()
        decided = [i for i in ids if i not in opaque]
        self.proof.check(decided, {i: items[i] for i in decided},
                         [[i for i in u if i not in opaque] for u in units or ()])
        self.hits = set(self.proof.sess.hit_ids)
        return set(self.hits)

    def reused_info(self, nid: str) -> tuple[dict, str]:
        """The recorded phase reports and fingerprint of a reused test; its outcome joins this session's."""
        rep, fp = self.proof.store.reuse_info(nid)
        if fp:
            self.fingerprints[nid] = fp
        for when in ("setup", "call"):
            p = rep.get(when)
            if p is not None:
                o = p["outcome"]
                if "wasxfail" in p:
                    o = "xfailed" if o == "skipped" else "xpassed"
                self.parts.setdefault(nid, {})[when] = o
        self.outcomes[nid] = _det_outcome(*(self.parts.get(nid, {}).get(w) for w in ("setup", "call", "teardown")))
        return rep, fp

    # -- tests -------------------------------------------------------------------------------------
    def begin(self, nid: str, fixtures=()) -> None:
        self.current = nid
        self._t0 = _perf()
        if not self.det:
            return
        if self.proof is not None:
            self.proof.start(nid, sorted(set(fixtures)))
        _level0.begin_test(nid, self.index)
        self.index += 1

    def report(self, nid: str, when: str, outcome: str, longrepr=None, wasxfail: str | None = None,
               exception: list | None = None) -> None:
        """A phase report of a test that ran (``outcome``: passed, failed, skipped; ``wasxfail`` marks an expected
        failure: skipped = xfailed, passed = xpassed)."""
        o = outcome if wasxfail is None else ("xfailed" if outcome == "skipped" else "xpassed")
        self.parts.setdefault(nid, {})[when] = o
        self.outcomes[nid] = _det_outcome(*(self.parts[nid].get(w) for w in ("setup", "call", "teardown")))
        if outcome == "failed" and nid not in self.exceptions and exception is not None:
            self.exceptions[nid] = exception
        if self.proof is not None and nid not in self.hits:
            self.proof.sess.report(_Report(nid, when, outcome, longrepr, wasxfail))

    def end(self, nid: str) -> None:
        dur = _perf() - self._t0
        self.times[nid] = dur
        self.current = None
        if not self.det:
            return
        fp = _level0.end_test(self.outcomes.get(nid, "unknown"))
        if fp is not None:
            self.fingerprints[nid] = fp
        if self.proof is not None:
            self.proof.stop(nid, dur)

    # -- end of session --------------------------------------------------------------------------
    def finish(self, exitstatus) -> None:
        if self.finished:
            return
        self.finished = True
        st = _state.STATE
        if self.det:
            if self.proof is not None:
                self.proof.finish({k: v for k, v in self.fingerprints.items() if k not in self.hits})
            if st.recorder is not None:
                if not self.order_digest:
                    st.recorder.open(self.trace_path, json.dumps({"detpy": __version__, "collection": "failed",
                                                                 "runner": self.runner}), [])
                st.recorder.close()
            if self.net_mode == "record":
                self.saved_cassette = network.save_recordings(st.config.cassette_path)
            if self.ns.det_compare:
                try:
                    self.compare_report = json.loads(_core.verify([self.ns.det_compare, self.trace_path]))
                except Exception as e:  # report, do not stop
                    self.compare_report = {"error": str(e)}
        self.write_outcomes(exitstatus)
        if self.det:
            self.print_summary()
            _proof.stop_capture(self.cap)
            _level0.uninstall()
            reexec.SESSION_DEPTH = max(0, reexec.SESSION_DEPTH - 1)

    def write_outcomes(self, exitstatus) -> None:
        path = self.ns.det_outcomes
        if not path:
            return
        data = {"runner": self.runner, "outcomes": self.outcomes, "exceptions": self.exceptions,
                "exitstatus": _exit_int(exitstatus), "order": self.order, "times": self.times}
        if self.det:
            cfg = _state.STATE.config
            data.update({"fingerprints": dict(self.fingerprints), "seed": cfg.seed, "shuffle": cfg.shuffle,
                         "controls": sorted(cfg.controls), "trace": self.trace_path,
                         "order_missing": self.order_missing, "adjustments": self.adjustments})
            if self.proof is not None:
                data["cache"] = self.proof.outcomes_data()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)

    def print_summary(self, out=None) -> None:
        out = out or sys.stderr
        cfg = _state.STATE.config
        w = lambda s: print(s, file=out)  # noqa: E731
        w(f"{'=' * 20} detpy (Level 0) {'=' * 20}")
        w(f"detpy {__version__}: runner {self.runner} {self.version or ''}; controls={','.join(sorted(cfg.controls))};"
          f" order {'shuffled with seed %d' % cfg.seed if cfg.shuffle else 'fixed (runner order)'}")
        w(f"detpy: PYTHONHASHSEED={os.environ.get('PYTHONHASHSEED')} ({self.status}); "
          f"ASLR {'off' if reexec.aslr_disabled() else 'on'}; network={self.net_mode}; sleep={cfg.sleep}")
        if self.adjustments:
            w(f"detpy: adjusted: {'; '.join(self.adjustments)}")
        w(f"trace: {self.trace_path}  order digest: {self.order_digest}  seed: {cfg.seed}"
          f"{' (shuffled)' if cfg.shuffle else ''}")
        if self.saved_cassette:
            w(f"network: recorded {self.saved_cassette} test(s) into {cfg.cassette_path}")
        if self.proof is not None:
            w(f"{'=' * 20} detpy cache with proof {'=' * 20}")
            for text, _markup in self.proof.summary_lines(1 if os.environ.get("DETPY_VERBOSE") else 0):
                w(text)
        rep = self.compare_report
        if rep is not None:
            if "error" in rep:
                w(f"compare: failed: {rep['error']}")
            else:
                s = rep["summary"]
                w(f"compare with {rep['labels'][0]}: covered={s['stable']} not-covered={s['diverged']} "
                  f"missing={s['missing']} outcome-unstable={s['outcome_unstable']}"
                  f"{'' if s['order_identical'] else ' (ORDER DIFFERS)'}")


def _exit_int(code) -> int:
    if code is None or code is False:
        return 0
    if code is True:
        return 1
    if isinstance(code, int):
        return code
    return 1


def exception_of(exc_info, when: str = "call") -> list:
    """[exception type, phase, first line of the message, path:line] of a failure (the pytest shell's
    ``--det-outcomes`` exceptions)."""
    etype, value, tb = exc_info
    first = (str(value).strip().splitlines() or [""])[0]
    where = ""
    while tb is not None:
        where = f"{tb.tb_frame.f_code.co_filename}:{tb.tb_lineno}"
        tb = tb.tb_next
    return [getattr(etype, "__name__", "unknown"), when, first[:200], where]
