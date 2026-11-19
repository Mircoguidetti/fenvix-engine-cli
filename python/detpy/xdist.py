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

import pytest

from . import _core

PLAN_FORMAT = "detpy-plan"
PLAN_VERSION = 1
STICKY_TOLERANCE = 0.10
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
        if not pending:
            return None
        assert self.collection is not None
        crash = self.collection[pending.pop(0)]
        # never a rebalance: the replacement worker gets the rest of this worker's list, in order
        self.orphans.extend(pending)
        self.ctl.note_crash(node, crash, pending)
        return crash

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

    # -- hooks -----------------------------------------------------------------------------------------
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
        """Per node (in worker order), the indices into ``collection`` it runs. Reused results are reported here,
        by the controller, and not sent."""
        from . import proofcache

        self.ids = list(collection)
        self.S.order = list(collection)
        self.S.order_digest = _core.order_digest(self.S.order)
        hits: set[str] = set()
        pc = proofcache.PLUGIN
        if pc is not None:
            hits = pc.decide_controller(self.ids)
        place = [i for i, nid in enumerate(self.ids) if nid not in hits]
        n = len(nodes)
        groups = self._groups(nodes) if self.dist == "loadgroup" else {}
        mode = self.dist if _core.sched_atom_key("x", self.dist) is not None else "load"
        atoms = [_core.sched_atom_key(self.ids[i], mode, groups.get(self.ids[i])) for i in place]
        costs = self._costs([self.ids[i] for i in place], pc)
        replay = self._replay(n)
        if replay is not None:
            # exact replay: every test is its own atom, pinned to its recorded worker
            atoms = [f"r:{self.ids[i]}" for i in place]
        elif mode in ("load", "worksteal") and CHUNK_DIV:
            # locality: consecutive same-file tests travel together (module fixtures, in-process predecessors)
            atoms = _core.sched_chunk_atoms([self.ids[i] for i in place], atoms, costs, n, CHUNK_DIV)
        previous = {}
        prev = load_json(os.path.join(self.dir, "plan.json"))
        if replay is not None:
            previous = replay
        elif prev and prev.get("workers") == n and prev.get("dist") == self.dist:
            previous = {k: int(v) for k, v in (prev.get("atoms") or {}).items()}
        # replay: the recorded assignment whatever the costs; else sticky within the tolerance
        tol = float("inf") if replay is not None else STICKY_TOLERANCE
        p = json.loads(_core.sched_plan([self.ids[i] for i in place], atoms, costs, n, previous, tol))
        lists = [[place[j] for j in lst] for lst in p["lists"]]
        wids = [node.gateway.id for node in nodes]
        # every test's worker, kept for the tests not placed now (reused): the sticky plan and the controller's
        # check of tests that read PYTEST_XDIST_WORKER (proofcache) use it
        keep_prev = prev if (prev and prev.get("workers") == n) else {}
        assign = {str(k): str(v) for k, v in (keep_prev.get("assign") or {}).items()}
        atoms_all = {str(k): int(v) for k, v in (keep_prev.get("atoms") or {}).items()}
        for w, lst in zip(wids, lists):
            for i in lst:
                assign[self.ids[i]] = w
        atoms_all.update(p["atom_worker"])
        self.plan = {
            "format": PLAN_FORMAT, "version": PLAN_VERSION, "workers": n, "dist": self.dist, "mode": mode,
            "testrunuid": self.testrunuid, "digest": p["digest"], "makespan": round(p["makespan"], 6),
            "lpt_makespan": round(p["lpt_makespan"], 6), "sticky": p["sticky"], "kept": p["kept"],
            "replayed": replay is not None, "hits": len(hits), "order_digest": self.S.order_digest,
            "loads": [round(x, 6) for x in p["loads"]],
            "lists": {w: [self.ids[i] for i in lst] for w, lst in zip(wids, lists)},
            "atoms": atoms_all,
            "assign": assign,
        }
        if pc is not None:
            pc.report_hits(self.ids, hits)
        return lists

    def _groups(self, nodes) -> dict:
        for node in nodes:
            d = load_json(os.path.join(self.dir, f"xdist-groups.{node.gateway.id}.json"))
            if d is not None:
                return d.get("groups") or {}
        return {}

    def _costs(self, ids: list[str], pc) -> list:
        hist = load_json(os.path.join(self.dir, "durations.json")) or {}
        cached = pc.durations(ids) if pc is not None else [None] * len(ids)
        out = []
        for nid, c in zip(ids, cached):
            h = hist.get(nid)
            v = _core.sched_cost_of([float(x) for x in h]) if isinstance(h, list) and h else None
            out.append(v if v is not None else c)
        return out

    def _replay(self, n: int) -> dict | None:
        path = self.config.getoption("det_plan", None)
        if not path:
            return None
        d = load_json(path)
        if d is None or d.get("format") != PLAN_FORMAT:
            raise pytest.UsageError(f"--det-plan: {path} is not a detpy plan")
        lists = d.get("lists") or {}
        assign = dict(d.get("assign") or {})
        for wid, ids in lists.items():
            for nid in ids:
                assign[nid] = wid
        prev = {}
        for nid, wid in assign.items():
            try:
                k = int(str(wid)[2:])
            except ValueError:
                continue
            if k >= n:
                raise pytest.UsageError(f"--det-plan: the plan has worker {wid}, this run has {n} workers")
            prev[f"r:{nid}"] = k
        return prev

    # -- end of session ------------------------------------------------------------------------------------
    def finish(self, session, trace_path: str, meta: dict) -> None:
        from . import proofcache

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
                            "reused_by_controller": len(self.reused)}
        summary = json.loads(_core.merge_traces(self.ids, workers, json.dumps(meta, sort_keys=True),
                                                self.plan["digest"] if self.plan else None, trace_path))
        self.merge_summary = summary
        for nid, fp, _outcome, _w in summary["tests"]:
            self.S.fingerprints[nid] = fp
        if self.plan is not None:
            write_json(os.path.join(self.dir, "plan.json"), self.plan)
        self._save_durations()
        self._merge_cassettes()
        if proofcache.PLUGIN is not None:
            proofcache.PLUGIN.merge_workers(self.workeroutput, self.sent)

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
        sizes = ", ".join(f"{w}={len(ids)}" for w, ids in p["lists"].items())
        lines = [f"plan {p['digest']}: {p['workers']} workers ({sizes}), planned makespan {p['makespan']:.1f}s "
                 f"(LPT {p['lpt_makespan']:.1f}s){', sticky' if p['sticky'] else ''}"
                 f"{', replayed' if p['replayed'] else ''}; reused by the controller: {p['hits']}"]
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
        if self.loadgroup:
            # xdist appends "@group" to node ids under --dist=loadgroup; under --det the ids stay the serial ids
            # (trace, cache keys) and the groups go to the controller's plan instead
            config.option.loadgroup = False

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
