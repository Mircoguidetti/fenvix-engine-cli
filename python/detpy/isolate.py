"""``--det-isolate``: every test runs in a child process forked from the session's snapshot.

The snapshot is this process after collection (and whatever ran in it before the test: nothing of another test, since
every test runs in a child). A test therefore cannot read state an earlier test left in memory (a module dict, an
``lru_cache``, a library's registry), and the cache's carried set holds no earlier test: a test's key is its own inputs
plus the snapshot's (collection, imports, conftests), the same in a serial session, in any worker of ``-n`` and on
another machine. Files are not isolated: a test that reads a file an earlier test wrote is handled as without
isolation (the reads are inputs; a file written in the session is a refusal unless its writer is the test's own).

The child:

* does Level 0's and the cache's start of the test (``plugin.level0_begin``, ``ProofCachePlugin.iso_begin``);
* runs pytest's protocol with ``nextitem=None``: every fixture, whatever its scope, is set up and torn down in the
  child (a session-scoped fixture is set up once per test: the sound choice, its cost is measured);
* ends the test (fingerprint, cache), records it as a one-test shard (no placement) and sends the reports, the
  fingerprint, the shard path and its summary to the parent through a pipe, then leaves with ``os._exit``.

The parent logs the reports (the terminal, junitxml, xdist's worker channel see them as usual), adds the child's
summary to its session and merges the shards at the end (serial), or hands them to the controller (``-n`` worker).
A child that dies without a payload is reported as a failure of the test. Linux only (``fork``); elsewhere the
carried-set rule applies and the header says so.
"""

from __future__ import annotations

import os
import pickle
import sys
import time

from .proofcache import _now as _real_time, _perf  # the real clocks (Level 0 virtualises time)

import pytest

# overhead per test (fork + payload + wait, the parent's view, minus the child's own protocol time): measured
STATS = {"tests": 0, "overhead_s": 0.0, "child_s": 0.0, "record_s": 0.0, "failed_children": 0}


def available() -> bool:
    return hasattr(os, "fork") and sys.platform.startswith("linux")


def _det_outcome(reports) -> str:
    from .plugin import _det_outcome as o

    parts = {}
    for r in reports:
        if hasattr(r, "wasxfail"):
            parts[r.when] = "xfailed" if r.skipped else "xpassed"
        else:
            parts[r.when] = r.outcome
    return o(parts.get("setup"), parts.get("call"), parts.get("teardown"))


class Isolate:
    def __init__(self, config):
        self.config = config

    @pytest.hookimpl
    def pytest_runtest_protocol(self, item, nextitem):
        from . import proofcache

        pc = proofcache.PLUGIN
        if pc is not None and pc.sess.is_hit(item.nodeid):
            return None  # served by the cache (its own protocol hook)
        if pc is not None:
            pc.iso_prepare()
        t0 = _perf()
        r, w = os.pipe()
        sys.stdout.flush()
        sys.stderr.flush()
        import warnings

        with warnings.catch_warnings():
            # Python warns about fork() in a multi-threaded process (xdist's execnet threads): the child never
            # touches what those threads hold (no channel, no logging handler of theirs), it runs the test and leaves
            warnings.simplefilter("ignore", DeprecationWarning)
            pid = os.fork()
        if pid == 0:  # pragma: no cover - runs in the child (its coverage is the parent's tests)
            os.close(r)
            try:
                payload = self._child(item, pc)
            except BaseException as e:  # noqa: BLE001 - every failure must reach the parent
                import traceback

                payload = {"error": f"{type(e).__name__}: {e}\n{traceback.format_exc()}"}
            try:
                data = pickle.dumps(payload)
            except Exception as e:  # noqa: BLE001
                data = pickle.dumps({"error": f"payload: {type(e).__name__}: {e}"})
            with os.fdopen(w, "wb") as fh:
                fh.write(data)
            os._exit(0)
        os.close(w)
        with os.fdopen(r, "rb") as fh:
            data = fh.read()
        _, status = os.waitpid(pid, 0)
        wall = _perf() - t0
        try:
            payload = pickle.loads(data) if data else {"error": f"the child exited with status {status}"}
        except Exception as e:  # noqa: BLE001
            payload = {"error": f"unreadable payload: {type(e).__name__}: {e}"}
        self._parent(item, pc, payload)
        STATS["tests"] += 1
        STATS["child_s"] += payload.get("child_s", 0.0)
        STATS["record_s"] += payload.get("record_s", 0.0)
        STATS["overhead_s"] += max(0.0, wall - payload.get("protocol_s", 0.0))
        return True

    # -- child -------------------------------------------------------------------
    def _child(self, item, pc) -> dict:
        from _pytest.runner import runtestprotocol

        from . import plugin

        c0 = _perf()
        if pc is not None:
            pc.iso_child = True
        plugin.level0_begin(item)
        t = pc.iso_begin(item) if pc is not None else None
        p0 = _perf()
        reports = runtestprotocol(item, nextitem=None, log=False)
        protocol_s = _perf() - p0
        if pc is not None:
            for rep in reports:
                pc.sess.report(rep)
        fp = plugin.level0_end(item, _det_outcome(reports))
        shard, summary, record_s = None, None, 0.0
        if pc is not None:
            pc.iso_end(item, t)
            r0 = _perf()
            shard, summary = pc.iso_record()
            record_s = _perf() - r0
        hook = self.config.hook
        ser = [hook.pytest_report_to_serializable(config=self.config, report=rep) for rep in reports]
        return {"reports": ser, "fingerprint": fp, "shard": shard, "summary": summary,
                "facts": list(pc.iso_new_facts) if pc is not None else [],
                "protocol_s": protocol_s, "record_s": record_s, "child_s": _perf() - c0}

    # -- parent ------------------------------------------------------------------
    def _parent(self, item, pc, payload) -> None:
        from _pytest.reports import TestReport

        from . import plugin

        ihook = item.ihook
        nid = item.nodeid
        if pc is not None:
            pc.iso_add_facts(payload.get("facts"))
            pc.iso_child_done(nid, payload.get("shard"), payload.get("summary"))
        ihook.pytest_runtest_logstart(nodeid=nid, location=item.location)
        if "error" in payload:
            STATS["failed_children"] += 1
            now = _real_time()
            rep = TestReport(nid, item.location, {k: 1 for k in item.keywords}, "failed",
                             f"detpy --det-isolate: the test's child process failed: {payload['error']}", "call",
                             (), 0.0, now, now)
            if pc is not None:
                pc.sess.not_cached_add(nid, "isolate: the child process failed") \
                    if hasattr(pc.sess, "not_cached_add") else None
            ihook.pytest_runtest_logreport(report=rep)
        else:
            hook = self.config.hook
            for d in payload["reports"]:
                rep = hook.pytest_report_from_serializable(config=self.config, data=d)
                ihook.pytest_runtest_logreport(report=rep)
            fp = payload.get("fingerprint")
            if fp:
                plugin.S.fingerprints[nid] = fp
                item.user_properties.append(("detpy_fingerprint", fp))
        ihook.pytest_runtest_logfinish(nodeid=nid, location=item.location)

    def pytest_terminal_summary(self, terminalreporter):
        n = STATS["tests"]
        if not n:
            return
        terminalreporter.write_line(
            f"detpy --det-isolate: {n} tests in forked children; overhead {STATS['overhead_s']:.2f} s "
            f"({1000 * STATS['overhead_s'] / n:.1f} ms per test, of which recording {1000 * STATS['record_s'] / n:.1f} "
            f"ms); {STATS['failed_children']} children failed")
