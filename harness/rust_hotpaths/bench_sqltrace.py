#!/usr/bin/env python3
"""Per-statement cost of the cache's sqlite trace (rust-hotpaths round 2): the Python ``Capture`` of
``tests/rust_hotpaths_ref/_ref_proofcache.py`` against the Rust ``_core.SqlTrace`` of ``detpy.proofcache``.

For each case, ``N`` ``execute(statement)`` on one connection made through the patched ``sqlite3.connect`` (best of 3
rounds, after 1000 warm-up statements), with no trace (``none``), with a C builtin as trace callback (``any
callback``: what sqlite's own tracing costs), with the reference trace (``ref``) and with the Rust one (``new``).
The trace overhead is the time over ``none``.

    python3 harness/rust_hotpaths/bench_sqltrace.py /tmp/sqlbench [N]
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> None:
    work = os.path.abspath(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 100_000
    os.makedirs(work, exist_ok=True)
    os.chdir(work)
    from detpy import proofcache

    spec = importlib.util.spec_from_file_location("detpy._ref_proofcache_bench",
                                                  os.path.join(REPO, "tests/rust_hotpaths_ref/_ref_proofcache.py"))
    ref = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ref)
    for name in ("main.sqlite", "att.sqlite"):
        c = sqlite3.connect(name)
        c.execute("create table if not exists t (x)")
        c.commit()
        c.close()

    def run(kind: str, db: str, attach: bool, stmt: str) -> float:
        cap = None
        if kind in ("ref", "new"):
            cap = (ref if kind == "ref" else proofcache).Capture(work, {})
            cap.active = True
            cap._patch_sqlite()
        try:
            c = sqlite3.connect(db)
            if kind == "floor":
                c.set_trace_callback(len)
            if attach:
                c.execute("attach database 'att.sqlite' as a")
            ex = c.execute
            for _ in range(1000):
                ex(stmt)
            best = float("inf")
            for _ in range(3):
                t0 = time.perf_counter()
                for _ in range(n):
                    ex(stmt)
                best = min(best, time.perf_counter() - t0)
            c.close()
            return best / n * 1e9
        finally:
            for obj, name, v in getattr(cap, "_sqlite_saved", ()):
                setattr(obj, name, v)

    for db, att, stmt in [(":memory:", False, "select 1"), ("main.sqlite", True, "select 1"),
                          ("main.sqlite", True, "select date('now')")]:
        r = {k: run(k, db, att, stmt) for k in ("none", "floor", "ref", "new")}
        over = {k: r[k] - r["none"] for k in ("floor", "ref", "new")}
        print(f"{db:12} attach={att!s:5} {stmt!r:22} ns/execute: none {r['none']:6.0f}  ref {r['ref']:6.0f}  "
              f"new {r['new']:6.0f} | overhead: any callback {over['floor']:5.0f}  ref {over['ref']:6.0f}  "
              f"new {over['new']:6.0f}  ({over['ref'] / max(over['new'], 1):.1f}x)")


if __name__ == "__main__":
    main()
