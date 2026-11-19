"""pytest-xdist under ``--det``: a fixed plan instead of xdist's dynamic scheduling (docs/PARALLEL-PROOF-DESIGN.md 2).

xdist stays the process manager (workers, execnet, report forwarding); detpy replaces its *scheduling* and owns the
*merge*:

* **Plan** (``DetScheduling``): once every worker has collected, the controller computes a fixed plan in Rust
  (``_core.sched_plan``: atoms from the customer's ``--dist`` mode, LPT on recorded durations, sticky across
  runs) and sends every worker its whole, ordered list at once; no refill, no stealing. A worker's list is a
  subsequence of the serial order. The plan is written to ``.detpy/plan.json`` and into the merged trace header.
* **Traces**: every worker writes ``<trace>.gwK.jsonl``; the controller merges them into ``<trace>`` at the end
  (``_core.merge_traces``).
* **testrun_uid** is derived from the seed and the command line instead of ``uuid4()``.
* **Cache with proof**: the reuse decision is made once, in the controller, before planning; hits are reported by
  the controller and never sent to a worker; workers record shards that the controller merges with the
  cross-worker write rule (``proofcache.py``).
* ``--det-plan=FILE`` replays a plan: under ``-n`` the same assignment; with ``--det-plan-worker=gwK`` (no
  ``-n``) worker K's list, serially, in one process, with the worker's xdist variables and fixtures.

This module is pytest/xdist glue; the decisions are Rust.
"""

from __future__ import annotations

import json
import os
import time as _time

import pytest

from . import _core

PLAN_FORMAT = "detpy-plan"
PLAN_VERSION = 1
STICKY_TOLERANCE = 0.10
# variables a worker process can inherit with another value than its controller's os.environ shows: the C-level
# environment of the controller (readline sets COLUMNS/LINES with setenv when it is imported) is what a popen worker
# starts with. Under --det the controller passes its own values (DETPY_XDIST_ENV) and the worker restores them first.
WORKER_ENV = ("COLUMNS", "LINES")
CONTROLLER_ENV = "DETPY_XDIST_ENV"


def export_controller_env(barrier: str | None = None) -> None:
    d = {k: os.environ.get(k) for k in WORKER_ENV}
    if barrier:
        d["_barrier"] = barrier  # not a variable: the directory of this run's cross-worker waits (Barrier)
    d["_controller_pid"] = os.getpid()  # not a variable: listeners of the controller are session infrastructure
    os.environ[CONTROLLER_ENV] = json.dumps(d)


_BARRIER_DIR: str | None = None
# real clocks, bound before Level 0 virtualises the time module
_sleep = _time.sleep
_mono = _time.monotonic
_time_ns = _time.time_ns


def restore_controller_env() -> None:
    """In a worker, before anything reads the environment: the controller's values of ``WORKER_ENV``."""
    raw = os.environ.pop(CONTROLLER_ENV, None)
    if raw is None or not os.environ.get("PYTEST_XDIST_WORKER"):
        return
    try:
        want = json.loads(raw)
    except ValueError:
        return
    global _BARRIER_DIR
    _BARRIER_DIR = want.pop("_barrier", None)
    pid = want.pop("_controller_pid", None)
    if isinstance(pid, int) and pid > 0:
        _core.set_xdist_controller_pid(pid)
    for k, v in want.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
# one-test atoms are merged into same-file chunks of at most total / (workers * CHUNK_DIV) (0: off)
CHUNK_DIV = int(os.environ.get("DETPY_PLAN_CHUNK_DIV", "8"))
_UNSUPPORTED = {"each"}


def is_worker(config) -> bool:
    return hasattr(config, "workerinput")


def worker_id(config) -> str | None:
    wi = getattr(config, "workerinput", None)
    return wi.get("workerid") if isinstance(wi, dict) else None


def is_controller(config) -> bool:
    """True in the controller of a distributed (``-n``) session."""
    if is_worker(config):
        return False
    try:
        if config.getoption("collectonly"):
            return False
        return config.getoption("dist", "no") != "no" and bool(config.getoption("tx", None))
    except ValueError:  # xdist not installed
        return False


def worker_path(path: str, wid: str) -> str:
    root, ext = os.path.splitext(path)
    return f"{root}.{wid}{ext}"


def state_dir(config) -> str:
    return os.path.join(str(config.rootpath), ".detpy")


def derived_testrunuid(config, seed: int) -> str:
    """``testrun_uid`` under ``--det``: a function of the seed, the selected paths, ``--dist`` and the number of
    workers (xdist draws ``uuid4()``; tests see it through the ``testrun_uid`` fixture and
    ``PYTEST_XDIST_TESTRUNUID``). Output options (trace, receipts, junit paths) do not change it."""
    args = [str(a) for a in (getattr(config, "args", None) or ())]
    n = len(config.getoption("tx", None) or ())
    return _core.digest(json.dumps(["detpy-testrun", seed, args, config.getoption("dist", "load"), n]).encode())[:32]


def _gw_number(node) -> tuple:
    gid = getattr(getattr(node, "gateway", None), "id", "") or ""
    try:
        return (0, int(gid[2:]), gid)
    except ValueError:
        return (1, 0, gid)


def load_json(path: str) -> dict | None:
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(data, f, sort_keys=True)
    os.replace(tmp, path)


def xdist_groups(items) -> dict:
    """``{nodeid: group}`` of the tests marked ``xdist_group`` (several names joined as xdist joins them)."""
    out = {}
    for item in items:
        names = set()
        for mark in item.iter_markers("xdist_group"):
            name = mark.args[0] if mark.args else mark.kwargs.get("name", "default")
            names.add(str(name))
        if names:
            out[item.nodeid] = "_".join(sorted(names))
    return out


# ---------------------------------------------------------------------------------------------------------------
class DetScheduling:
    """xdist scheduler of ``--det``: one fixed plan, sent whole to every worker (xdist's ``Scheduling`` protocol)."""

    def __init__(self, config, log, ctl: Controller):
        from xdist.workermanage import parse_tx_spec_config

        self.config = config
        self.log = log.detsched if log is not None else (lambda *a: None)
        self.ctl = ctl
        self.numnodes = len(parse_tx_spec_config(config))
        self.node2collection: dict = {}
        self.node2pending: dict = {}
        self.collection: list | None = None
        self.sent: set = set()
        self.orphans: list[int] = []  # the rest of a crashed worker's list, for its replacement

    # -- the Scheduling protocol ----------------------------------------------------------------------
    @property
    def nodes(self) -> list:
        return list(self.node2pending.keys())

    @property
    def collection_is_completed(self) -> bool:
        return len(self.node2collection) >= self.numnodes

    @property
    def tests_finished(self) -> bool:
        if not self.collection_is_completed or self.collection is None or self.orphans:
            return False
        return all(len(p) < 2 for p in self.node2pending.values())

    @property
    def has_pending(self) -> bool:
        return bool(self.orphans) or any(self.node2pending.values())

    def add_node(self, node) -> None:
        assert node not in self.node2pending
        self.node2pending[node] = []

    def add_node_collection(self, node, collection) -> None:
        assert node in self.node2pending
        if self.collection is not None and list(collection) != self.collection:
            from xdist.report import report_collection_diff

            other = next(iter(self.node2collection))
            self.log(report_collection_diff(self.collection, collection, other.gateway.id, node.gateway.id))
            return
        self.node2collection[node] = list(collection)

    def mark_test_complete(self, node, item_index: int, duration: float = 0) -> None:
        self.node2pending[node].remove(item_index)

    def mark_test_pending(self, item: str) -> None:
        # a plugin asks for a test to run again (rerun plugins): on the worker that ran it first in the plan
        assert self.collection is not None
        idx = self.collection.index(item)
        node = self.ctl.node_of_index(idx) or (self.nodes[0] if self.nodes else None)
        if node is None or node.shutting_down:
            self.orphans.append(idx)
            return
        self.node2pending[node].append(idx)
        node.send_runtest_some([idx])

    def remove_pending_tests_from_node(self, node, indices) -> None:
        raise NotImplementedError("--det: work stealing is not used (fixed plan)")

    def remove_node(self, node):
        pending = self.node2pending.pop(node)
        assert self.collection is not None or not pending
        crash, rest = _core.sched_crash_split(list(pending))
        if crash is not None:
            # never a rebalance: the replacement worker gets the rest of this worker's list, in order
            self.orphans.extend(rest)
            self.ctl.note_crash(node, self.collection[crash], rest)
            return self.collection[crash]
        if not self.node2pending and not self.orphans and self.collection is not None:
            # every worker finished its list: the controller settles its reused results (and may run some again)
            rerun = self.ctl.all_finished(node)
            if rerun:
                self.orphans.extend(rerun)
        return None

    def schedule(self) -> None:
        assert self.collection_is_completed
        if self.collection is not None:
            # a replacement for a crashed worker: it runs the rest of the dead worker's list
            for node in sorted(self.nodes, key=_gw_number):
                if node in self.sent or node.shutting_down:
                    continue
                todo, self.orphans = self.orphans, []
                self._send(node, todo)
            return
        if not self._same_collections():
            self.log("**Different tests collected, aborting run**")
            return
        self.collection = list(next(iter(self.node2collection.values())))
        nodes = sorted(self.nodes, key=_gw_number)
        lists = self.ctl.make_plan(self.collection, nodes)
        for node, indices in zip(nodes, lists):
            self._send(node, indices)

    # -- helpers --------------------------------------------------------------------------------------
    def _send(self, node, indices: list[int]) -> None:
        self.sent.add(node)
        self.ctl.note_sent(node, indices)
        if indices:
            self.node2pending[node].extend(indices)
            node.send_runtest_some(list(indices))
        node.shutdown()

    def _same_collections(self) -> bool:
        from xdist.report import report_collection_diff

        items = list(self.node2collection.items())
        first, col = items[0]
        same = True
        for node, other in items[1:]:
            msg = report_collection_diff(col, other, first.gateway.id, node.gateway.id)
            if msg:
                same = False
                self.log(msg)
                self.config.hook.pytest_collectreport(
                    report=pytest.CollectReport(nodeid=node.gateway.id, outcome="failed", longrepr=msg, result=[]))
        return same


# ---------------------------------------------------------------------------------------------------------------
class Controller:
    """The controller's side of a ``--det -n N`` session: plan, hits, worker bookkeeping, merges."""

    def __init__(self, config, session_state):
        self.config = config
        self.S = session_state
        self.dist = config.getoption("dist", "load") or "load"
        self.dir = state_dir(config)
        self.plan: dict | None = None
        self.ids: list[str] = []
        self.sent: dict[str, list[str]] = {}  # worker id -> ids sent, in order
        self.sent_index: dict[int, object] = {}
        self.crashed: list[tuple[str, str]] = []  # (worker, test)
        self.durations: dict[str, float] = {}
        self.reused: set[str] = set()
        self.workeroutput: dict[str, dict] = {}
        self.merge_summary: dict | None = None
        self.testrunuid = None
        self.spawn_env: dict | None = None  # the environment the workers start with (pytest_xdist_setupnodes)
        self.pending_hits: list[str] = []  # reused results not reported yet (until every worker finished)
        self.settled = False
        self.rerun: list[str] = []  # withdrawn reuses run again by an extra worker
        self.barrier = os.path.join(self.dir, "barrier", f"{os.getpid()}-{_time_ns()}")
        self.waits: dict = {}
        # F2 first discovery (parallel-proof round 3): under --det-cache the workers' reports are held until the end
        # of the run loop; a test that read what a test on another worker wrote, with no wait between them in this
        # plan, is run again after its earlier writers in a fresh worker, and that run's reports replace its own
        self.held: list | None = None
        self._forward = None
        self.racy: dict = {}  # reader -> (path, writers before it)
        self.racy_edges: list = []  # (writer, reader) pairs found here: data edges for the next plans
        self.unsettled: dict = {}  # reader -> path (a cross-worker writer after it: no serial view to rerun into)
        self.rerun_nodes: list = []
        self.rerun_racy: list[str] = []

    # -- hooks -----------------------------------------------------------------------------------------
    def pytest_xdist_setupnodes(self, config, specs):
        """The environment the workers start with (review R-023, cacheability): the controller's ``os.environ`` now,
        after its conftests ran at import time (litellm sets variables there). A worker records against this
        environment, so the controller decides with it too, not with its own start environment."""
        from . import proofcache

        env = dict(os.environ)
        # review R-023b N4: --tx popen//env:NAME=VALUE starts the workers with more variables than the controller
        # has. The same items on every spec are the workers' values; a variable the specs set differently gets a
        # value no recorded digest equals (a test that read it runs)
        per_spec = [dict(getattr(s, "env", None) or {}) for s in (specs or ())]
        names = {k for d in per_spec for k in d}
        for k in names:
            vals = {d.get(k) for d in per_spec}
            env[k] = vals.pop() if len(vals) == 1 and None not in vals else "\x00detpy:differs-per-worker"
        self.spawn_env = _core.safe_env(env.items(), proofcache._DETPY_OWN_ENV)

    @pytest.hookimpl(tryfirst=True)
    def pytest_xdist_make_scheduler(self, config, log):
        if self.dist in _UNSUPPORTED:
            return None  # xdist's own scheduler; noted in the report header
        return DetScheduling(config, log, self)

    def pytest_testnodedown(self, node, error):
        out = getattr(node, "workeroutput", None)
        if isinstance(out, dict):
            self.workeroutput[node.gateway.id] = {k: v for k, v in out.items() if k.startswith("detpy_")}

    def pytest_runtest_logreport(self, report):
        if any(k == "detpy_cache" and v == "reused" for k, v in getattr(report, "user_properties", ()) or ()):
            self.reused.add(report.nodeid)
            return
        self.durations[report.nodeid] = self.durations.get(report.nodeid, 0.0) + float(report.duration or 0.0)

    # -- scheduler callbacks -----------------------------------------------------------------------------
    def node_of_index(self, idx: int):
        return self.sent_index.get(idx)

    def note_sent(self, node, indices) -> None:
        wid = node.gateway.id
        self.sent.setdefault(wid, []).extend(self.ids[i] for i in indices)
        for i in indices:
            self.sent_index[i] = node

    def note_crash(self, node, crash: str, rest) -> None:
        self.crashed.append((node.gateway.id, crash))

    def make_plan(self, collection: list[str], nodes: list) -> list[list[int]]:
        """Per node (in worker order), the indices into ``collection`` it runs. The plan (``_core.sched_controller_plan``)
        covers every collected test: reused tests get a worker too (cost 0) and are not sent; their reports come
        from the controller once every worker finished (``all_finished``)."""
        from . import proofcache

        self.ids = list(collection)
        self.S.order = list(collection)
        self.S.order_digest = _core.order_digest(self.S.order)
        pc = proofcache.PLUGIN
        hits = pc.decide_controller(self.ids) if pc is not None else set()
        wids = [node.gateway.id for node in nodes]
        replay_path = self.config.getoption("det_plan", None)
        replay = None
        if replay_path:
            replay = load_json(replay_path)
            if replay is None:
                raise pytest.UsageError(f"--det-plan: {replay_path} is not a detpy plan")
        hist = load_json(os.path.join(self.dir, "durations.json")) or {}
        inp = {
            "ids": self.ids, "hits": [n for n in self.ids if n in hits], "dist": self.dist,
            "groups": self._groups(nodes) if self.dist == "loadgroup" else {}, "workers": wids,
            "chunk_div": CHUNK_DIV, "tolerance": STICKY_TOLERANCE, "slack": 1.0,
            "history": {k: v for k, v in hist.items() if isinstance(v, list)},
            "cached": pc.durations(self.ids) if pc is not None else {},
            "previous": load_json(os.path.join(self.dir, "plan.json")), "replay": replay,
            "edges": [list(e) for e in pc.store.edges()] if pc is not None else [],
        }
        try:
            p = json.loads(_core.sched_controller_plan(json.dumps(inp)))
        except ValueError as e:
            if replay is not None:
                raise pytest.UsageError(f"--det-plan: {replay_path}: {e}") from None
            raise
        withdrawn = pc.check_workers(self.ids, p["assign"]) if pc is not None else []
        index = {nid: i for i, nid in enumerate(self.ids)}
        # sent: the plan's list of each worker without the results reused in the end
        lists = [[index[nid] for nid in p["lists"].get(w, []) if pc is None or not pc.sess.is_hit(nid)]
                 for w in wids]
        self.pending_hits = [n for n in self.ids if pc is not None and pc.sess.is_hit(n)]
        if pc is not None and self.held is None:
            self._hold_reports()
        self.waits = p["waits"]
        if self.waits:
            write_json(os.path.join(self.barrier, "waits.json"), {"waits": self.waits})
        self.plan = {
            "format": PLAN_FORMAT, "version": PLAN_VERSION, "workers": len(wids), "dist": self.dist,
            "mode": p["mode"], "testrunuid": self.testrunuid, "digest": p["digest"],
            "makespan": round(p["makespan"], 6), "lpt_makespan": round(p["lpt_makespan"], 6), "sticky": p["sticky"],
            "kept": p["kept"], "replayed": p["replayed"], "previous_ignored": p["previous_ignored"],
            "hits": len(self.pending_hits), "withdrawn_worker": len(withdrawn), "order_digest": self.S.order_digest,
            "loads": [round(x, 6) for x in p["loads"]], "lists": p["lists"], "atoms": p["atoms"],
            "assign": p["assign"], "waits": p["waits"],
        }
        return lists

    def all_finished(self, last_node) -> list[int]:
        """Every worker finished its list. Reused results whose input a test that comes before them wrote in this
        session are withdrawn (review R-023 F2): a fresh worker runs them; the other reused results are reported now.
        Returns the indices to run again."""
        from . import proofcache

        if self.settled:
            return []
        self.settled = True
        pc = proofcache.PLUGIN
        if pc is None:
            return []
        shards = [o.get("detpy_cache_shard") for o in self.workeroutput.values() if o.get("detpy_cache_shard")]
        withdrawn = pc.written_hits(shards, self.ids)
        pc.report_hits(self.pending_hits)
        self.pending_hits = []
        racy = pc.store.racy_readers(shards, self.ids, dict(self.plan["assign"]) if self.plan else {},
                                     dict(self.waits)) if self.held is not None else []
        if not withdrawn and not racy:
            return []
        dsession = self.config.pluginmanager.getplugin("dsession")
        if dsession is None or not hasattr(dsession, "_clone_node"):
            pc.report_unrun(withdrawn)
            return []
        # xdist's own way to add a worker (as for a crashed one): it collects, then DetScheduling.schedule sends it
        # the orphans
        self.rerun = [nid for nid, _ in withdrawn]
        index = {nid: i for i, nid in enumerate(self.ids)}
        todo = set(self.rerun)
        for reader, path, before, later in racy:
            self.racy_edges.extend((w, reader) for w in (*before, *later))
            if later:
                # a writer on another worker comes after the reader: the file already holds its write, no rerun
                # gives the serial view. Reported as unsettled; the pair is a data edge, and from the next plan on
                # the writer waits for the reader.
                self.unsettled[reader] = path
                continue
            self.racy[reader] = (path, before)
            todo.add(reader)
            todo.update(before)  # its earlier writers first, so it reads what the serial order gives it
        self.rerun_racy = sorted(self.racy)
        if not todo:
            return []
        dsession.shuttingdown = False
        self.rerun_nodes.append(dsession._clone_node(last_node))
        return sorted(index[nid] for nid in todo if nid in index)

    # -- held reports (F2 first discovery) ----------------------------------------------------------------------
    def _hold_reports(self) -> None:
        dsession = self.config.pluginmanager.getplugin("dsession")
        if dsession is None or not hasattr(dsession, "worker_testreport"):
            return
        self.held = []
        self._forward = dsession.worker_testreport

        def hold(node, rep):
            self.held.append((node, rep))

        dsession.worker_testreport = hold  # xdist dispatches worker events by attribute name

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtestloop(self, session):
        yield
        held, self.held = self.held, None
        if held is None or self._forward is None:
            return
        racy = set(self.racy)
        rerun_hits = set(self.rerun)
        for node, rep in held:
            nid = rep.nodeid
            if node in self.rerun_nodes:
                # the rerun worker: its reports of the racy readers and withdrawn hits are their verdicts; its runs of
                # the earlier writers only set the files up (their own verdicts were reported from their workers)
                if nid in racy or nid in rerun_hits:
                    self._forward(node, rep)
            elif nid not in racy:
                self._forward(node, rep)

    def _groups(self, nodes) -> dict:
        for node in nodes:
            d = load_json(os.path.join(self.dir, f"xdist-groups.{node.gateway.id}.json"))
            if d is not None:
                return d.get("groups") or {}
        return {}

    # -- end of session ------------------------------------------------------------------------------------
    def finish(self, session, trace_path: str, meta: dict) -> None:
        from . import proofcache

        if self.pending_hits and proofcache.PLUGIN is not None:
            # the session stopped before every worker finished (-x, --maxfail, an interrupt): nothing was settled
            proofcache.PLUGIN.report_hits(self.pending_hits)
            self.pending_hits = []
        os.makedirs(self.dir, exist_ok=True)
        workers = []
        for wid in sorted(set(self.sent) | set(self.workeroutput), key=lambda w: _gw_number(_N(w))):
            out = self.workeroutput.get(wid, {})
            path = out.get("detpy_trace") or worker_path(trace_path, wid)
            workers.append((wid, path, self.sent.get(wid, [])))
        meta = dict(meta)
        if self.plan is not None:
            meta["plan"] = {k: v for k, v in self.plan.items() if k not in ("atoms", "assign")}
        meta["parallel"] = {"workers": len(self.sent), "crashed": [list(c) for c in self.crashed],
                            "reused_by_controller": len(self.reused), "rerun_written": list(self.rerun),
                            "rerun_racy": sorted(self.racy), "unsettled": sorted(self.unsettled)}
        summary = json.loads(_core.merge_traces(self.ids, workers, json.dumps(meta, sort_keys=True),
                                                self.plan["digest"] if self.plan else None, trace_path))
        self.merge_summary = summary
        for nid, fp, _outcome, _w in summary["tests"]:
            self.S.fingerprints[nid] = fp
        if self.plan is not None:
            write_json(os.path.join(self.dir, "plan.json"), self.plan)
        import shutil

        shutil.rmtree(self.barrier, ignore_errors=True)
        self._save_durations()
        self._merge_cassettes()
        if proofcache.PLUGIN is not None:
            proofcache.PLUGIN.merge_workers(self.workeroutput, self.sent, self.racy_edges)

    def _save_durations(self) -> None:
        if not self.durations:
            return
        path = os.path.join(self.dir, "durations.json")
        hist = load_json(path) or {}
        for nid, d in self.durations.items():
            h = hist.get(nid) if isinstance(hist.get(nid), list) else []
            hist[nid] = (h + [round(d, 6)])[-3:]
        write_json(path, hist)

    def _merge_cassettes(self) -> None:
        from . import _state

        cfg = _state.STATE.config
        if not getattr(cfg, "record_net", False):
            return
        target_path = cfg.cassette_path
        parts = [o.get("detpy_cassette") for o in self.workeroutput.values() if o.get("detpy_cassette")]
        if not parts:
            return
        target = _core.Cassette.load(target_path) if os.path.exists(target_path) else _core.Cassette()
        n = 0
        for p in sorted(parts):
            if os.path.exists(p):
                c = _core.Cassette.load(p)
                n += len(c.tests())
                target.merge(c)
        target.save(target_path)
        self.S.saved_cassette = n

    def header_lines(self) -> list[str]:
        if self.dist in _UNSUPPORTED:
            return [f"detpy: pytest-xdist --dist={self.dist} is not planned by detpy (xdist's own scheduling)"]
        return [f"detpy: pytest-xdist under a fixed plan (--dist={self.dist}); testrun_uid {self.testrunuid}"]

    def summary_lines(self) -> list[str]:
        p = self.plan
        if p is None:
            return []
        sizes = ", ".join(f"{w}={len(self.sent.get(w, []))}/{len(ids)}" for w, ids in p["lists"].items())
        lines = [f"plan {p['digest']}: {p['workers']} workers (ran/planned {sizes}), planned makespan "
                 f"{p['makespan']:.1f}s (LPT {p['lpt_makespan']:.1f}s){', sticky' if p['sticky'] else ''}"
                 f"{', replayed' if p['replayed'] else ''}; reused by the controller: {len(self.reused)}"
                 + (f"; {p['withdrawn_worker']} reuse(s) withdrawn: the plan moved a worker-id reader"
                    if p.get("withdrawn_worker") else "")]
        if self.waits:
            lines.append(f"{len(self.waits)} test(s) waited for a writer on another worker (data edges of earlier "
                         f"sessions)")
        if self.rerun:
            lines.append(f"{len(self.rerun)} reuse(s) withdrawn after the run (an earlier test of this session wrote "
                         f"their input): run again in an extra worker")
        if self.unsettled:
            lines.append(f"UNSETTLED: {len(self.unsettled)} test(s) read a file that a later test (in the serial order) "
                         f"on another worker wrote, with no data edge yet: their verdict may not be the serial one "
                         f"({', '.join(sorted(self.unsettled)[:5])}); from the next run on the writer waits for them")
        if self.racy:
            lines.append(f"{len(self.racy)} test(s) read a file a test on another worker wrote, with no data edge yet: "
                         f"run again after their earlier writers in an extra worker; that run is their verdict "
                         f"(the pairs are data edges from now on)")
        s = self.merge_summary
        if s is not None:
            lines.append(f"merged trace: {s['n_tests']} tests from {len(self.sent)} worker traces"
                         + (f"; MISSING {len(s['missing'])}" if s["missing"] else "")
                         + (f"; unreadable worker traces: {', '.join(s['unreadable'])}" if s["unreadable"] else ""))
        for w, t in self.crashed:
            lines.append(f"worker {w} crashed in {t}; its remaining tests went to its replacement")
        return lines


class _N:  # a stand-in node for sorting worker ids
    def __init__(self, gid):
        self.gateway = type("G", (), {"id": gid})


# ---------------------------------------------------------------------------------------------------------------
class Worker:
    """A worker's side: its trace path, its xdist groups (for the controller's atoms), its outputs."""

    def __init__(self, config, wid: str):
        self.config = config
        self.wid = wid
        self.loadgroup = bool(getattr(config.option, "loadgroup", False))
        self.barrier = Barrier(_BARRIER_DIR) if _BARRIER_DIR else None
        if self.loadgroup:
            # xdist appends "@group" to node ids under --dist=loadgroup; under --det the ids stay the serial ids
            # (trace, cache keys) and the groups go to the controller's plan instead
            config.option.loadgroup = False

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item, nextitem):
        b = self.barrier
        if b is not None:
            b.wait_for(item.nodeid)
        try:
            yield
        finally:
            if b is not None:
                b.done(item.nodeid)

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, session, config, items):
        if self.loadgroup:
            write_json(os.path.join(state_dir(config), f"xdist-groups.{self.wid}.json"),
                       {"groups": xdist_groups(items)})

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session):
        # after detpy's own session finish (trace closed, cache shard written); xdist sends workeroutput after it
        out = getattr(self.config, "workeroutput", None)
        if out is None:
            return
        from . import plugin, proofcache

        out["detpy_trace"] = plugin.S.trace_path
        if plugin.S.saved_cassette and plugin.S.cassette_out:
            out["detpy_cassette"] = plugin.S.cassette_out
        if proofcache.PLUGIN is not None:
            out.update(proofcache.PLUGIN.worker_output())


# ---------------------------------------------------------------------------------------------------------------
class Barrier:
    """Cross-worker waits of one run (review R-023 F2). The controller's plan (Rust) lists, for a test that read a file
    another test wrote in an earlier session, the writers that run this time on another worker and come before it in
    the serial order (``waits.json``). The test starts only once they finished (``done/<digest>``), so it reads what
    a serial session gives it instead of the result of a race between two processes. Files under ``.detpy/`` are
    not inputs of the cache's capture. Waiting is real time; a writer whose worker died is not waited for longer
    than ``timeout`` seconds."""

    def __init__(self, path: str, timeout: float = 600.0):
        self.path = path
        self.timeout = timeout
        self._waits: dict | None = None
        self._writers: set = set()

    def _load(self) -> dict:
        if self._waits is None:
            d = load_json(os.path.join(self.path, "waits.json")) or {}
            self._waits = {str(k): [str(x) for x in v] for k, v in (d.get("waits") or {}).items()}
            self._writers = {w for v in self._waits.values() for w in v}
        return self._waits

    def _marker(self, nid: str) -> str:
        return os.path.join(self.path, "done", _core.digest(nid.encode())[:32])

    def wait_for(self, nid: str) -> list[str]:
        """Wait until every writer ``nid`` waits for is done; returns the ones still missing at the timeout."""
        need = self._load().get(nid)
        if not need:
            return []
        t0 = _mono()
        while True:
            missing = [w for w in need if not os.path.exists(self._marker(w))]
            if not missing or _mono() - t0 > self.timeout:
                return missing
            _sleep(0.005)

    def done(self, nid: str) -> None:
        self._load()
        if nid in self._writers:
            os.makedirs(os.path.join(self.path, "done"), exist_ok=True)
            with open(self._marker(nid), "w"):
                pass


# ---------------------------------------------------------------------------------------------------------------
class PlanWorkerReplay:
    """``--det-plan=FILE --det-plan-worker=gwK`` without ``-n``: the worker's xdist identity in one process."""

    def __init__(self, wid: str, count: int, testrunuid: str):
        self.wid, self.count, self.testrunuid = wid, count, testrunuid

    @pytest.fixture(scope="session")
    def worker_id(self):
        return self.wid

    @pytest.fixture(scope="session")
    def testrun_uid(self):
        return self.testrunuid


def replay_worker(path: str, wid: str) -> tuple[list[str], int, str]:
    """(ids, number of workers, testrun uid) of worker ``wid`` in plan ``path``."""
    d = load_json(path)
    if d is None or d.get("format") != PLAN_FORMAT:
        raise pytest.UsageError(f"--det-plan: {path} is not a detpy plan")
    lists = d.get("lists") or {}
    if wid not in lists:
        raise pytest.UsageError(f"--det-plan-worker: {wid} not in {path} (workers: {', '.join(sorted(lists))})")
    return list(lists[wid]), int(d.get("workers") or len(lists)), str(d.get("testrunuid") or "")
