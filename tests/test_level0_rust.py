"""Round 2 of rust-hotpaths: the virtual clock, ``_sites.resolve`` and ``_state.record`` in Rust
(``crates/detpy-py/src/level0.rs``) against the round-1 Python originals (``tests/rust_hotpaths_ref/_ref_l0_*.py``).

* whole sessions: the same project run with the reference path (``-p _l0ref``) and with the Rust path; the
  ``--det`` traces (every event, site, value, fingerprint) must be byte-identical, and so must the
  ``--det-cache`` stores and the warm runs' receipts and outcomes;
* the clock's arithmetic against the reference ``VirtualClock`` (random operation sequences, adaptive tick);
* the seconds conversion against Python's ``int / int``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import random
import re
import sys
from pathlib import Path

import pytest

REF = Path(__file__).parent / "rust_hotpaths_ref"

PROJECT = {
    "pkg/__init__.py": "",
    "pkg/timing.py": '''
import time
from time import monotonic, perf_counter_ns   # bound before detpy installs: rebound to the stand-ins

T0 = time.time()                                # import-time read (collection context)


def stamp():
    return (time.time(), time.time_ns(), monotonic(), time.monotonic_ns(), time.perf_counter(), perf_counter_ns())


def spin(n):
    out = []
    t = time.perf_counter()
    while len(out) < n:                         # a clock-only loop: the adaptive tick doubles
        out.append(time.perf_counter() - t)
    return out
''',
    "conftest.py": '''
import time
import pytest


@pytest.fixture(scope="module")
def started():
    return time.monotonic()                     # fixture context


@pytest.fixture
def per_test():
    yield time.perf_counter()
    time.time()                                 # teardown read
''',
    "test_clock.py": '''
import asyncio
import datetime
import logging
import os
import random
import threading
import time

from pkg import timing


def test_reads(started, per_test):
    a = timing.stamp()
    b = timing.stamp()
    assert a < b
    print("VAL", a, b, started, per_test)


def test_spin_and_other_events():
    s = timing.spin(40)
    random.random()                             # another event: the tick goes back to its base
    os.listdir("pkg")
    s2 = timing.spin(5)
    print("VAL", s[-1], s2)


def test_wall_derived():
    print("VAL", datetime.datetime.now(), datetime.datetime.now(datetime.timezone.utc), time.localtime(),
          time.gmtime(), time.ctime(), time.strftime("%Y"), time.asctime())
    if hasattr(time, "clock_gettime"):
        print("VAL", time.clock_gettime(time.CLOCK_MONOTONIC), time.clock_gettime_ns(time.CLOCK_REALTIME))


def test_sleep_and_waits():
    t = time.monotonic()
    time.sleep(0.01)
    ev = threading.Event()
    ev.wait(0.01)
    lock = threading.Lock()
    lock.acquire()
    assert not lock.acquire(timeout=0.01)
    print("VAL", time.monotonic() - t)


def test_threads():
    out = []

    def work(i):
        for _ in range(3):
            out.append((i, time.monotonic()))

    ts = [threading.Thread(target=work, args=(i,)) for i in range(3)]
    for t in ts:
        t.start()
        t.join()                                # sequential: deterministic thread numbering
    timer = threading.Timer(0.0, time.monotonic)   # read from stdlib frames only
    timer.start()
    timer.join()
    print("VAL", out)


def test_asyncio():
    async def main():
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        loop.call_later(0.01, fut.set_result, time.monotonic())
        await asyncio.sleep(0.01)
        r = await fut
        return r, time.perf_counter()

    print("VAL", asyncio.run(main()))


def test_logging(caplog):
    caplog.set_level(logging.INFO)
    logging.getLogger("x").info("hello")       # LogRecord reads the clock from the stdlib
    print("VAL", [r.created for r in caplog.records])


def test_reads_in_builtin_callbacks():
    print("VAL", sorted([3, 1, 2], key=lambda x: (time.monotonic(), x)), list(map(lambda _: time.time(), [1, 2])))
''',
    "test_other.py": '''
import time
import uuid
import random


def test_mixed():
    xs = []
    for i in range(5):
        xs.append(time.perf_counter_ns())
        if i % 2:
            random.randint(0, 9)
    print("VAL", xs, uuid.uuid4())


def test_failing():
    t = time.time()
    assert t < 0
''',
}


def _write(root: Path, files: dict) -> None:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


@pytest.fixture
def ref_env(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(REF), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep))


def _run(pytester, mode: str, *args):
    os.environ["DETPY_L0_REF"] = "1" if mode == "ref" else "0"
    try:
        r = pytester.runpytest_subprocess("--det", "--det-urandom", "-p", "no:cacheprovider", "-s", "-p", "_l0ref",
                                          *args)
    finally:
        del os.environ["DETPY_L0_REF"]
    out = r.stdout.str()
    assert "Traceback" not in out.split("short test summary")[0] or "assert t < 0" in out, out[-3000:]
    return r


def _vals(r) -> list:
    return [line[line.index("VAL "):] for line in r.stdout.lines if "VAL " in line]


def test_level0_reference_plugin_is_active(pytester, ref_env):
    pytester.makepyfile(test_x="import detpy, detpy.clock as c\ndef test_x():\n    print('REF', getattr(detpy, "
                                "'LEVEL0_REFERENCE', False), type(c.monotonic).__name__)\n")
    ref = _run(pytester, "ref")
    new = _run(pytester, "new")
    assert "REF True function" in ref.stdout.str()
    assert "REF False builtin_function_or_method" in new.stdout.str()


def test_level0_traces_match_reference(pytester, ref_env):
    _write(pytester.path, PROJECT)
    traces, vals = {}, {}
    for i, mode in enumerate(("ref", "new", "ref", "new")):
        t = pytester.path / f"trace-{mode}-{i}.jsonl"
        r = _run(pytester, mode, f"--det-trace={t}")
        # the header's precompile duration is the only wall-clock value in a trace
        traces.setdefault(mode, []).append(re.sub(rb'"precompile_s":[0-9.]+,', b"", t.read_bytes()))
        vals.setdefault(mode, []).append(_vals(r))
    # each path reproduces itself, and the two paths write the same bytes
    assert traces["ref"][0] == traces["ref"][1]
    assert traces["new"][0] == traces["new"][1]
    lines_ref = traces["ref"][0].decode().splitlines()
    lines_new = traces["new"][0].decode().splitlines()
    assert len(lines_ref) == len(lines_new)
    for a, b in zip(lines_ref, lines_new):
        assert a == b
    assert traces["ref"][0] == traces["new"][0]
    assert vals["ref"][0] == vals["new"][0] and len(vals["new"][0]) >= 10
    # the trace has what the test is about
    events = [json.loads(x) for x in lines_new if '"type":"test"' in x]
    ops = {e["o"] for t in events for e in t.get("events", [])}
    assert {"time.time", "time.time_ns", "time.monotonic", "time.monotonic_ns", "time.perf_counter",
            "time.perf_counter_ns", "datetime.now", "time.sleep"} <= ops, ops
    sites = {e["at"] for t in events for e in t.get("events", [])}
    assert any(s.startswith("<stdlib>/threading.py:") for s in sites), sites   # the Timer's stdlib-only read
    assert any(s.startswith("pkg/timing.py:") for s in sites)


def test_level0_cache_matches_reference(pytester, ref_env):
    _write(pytester.path, PROJECT)
    out = {}
    for mode in ("ref", "new"):
        cache = pytester.path / f".cache-{mode}"
        cold = _run(pytester, mode, f"--det-cache={cache}", f"--det-outcomes={pytester.path / f'o-{mode}-c.json'}")
        # the run id (time and pid) and the measured durations are the only wall-clock values of a store
        store = re.sub(rb'"(run|duration)":("[^"]*"|[0-9.e-]+)', b"", (cache / "proof-cache.json").read_bytes())
        warm = _run(pytester, mode, f"--det-cache={cache}", f"--det-outcomes={pytester.path / f'o-{mode}-w.json'}")
        receipts = [re.sub(r'"(run|duration)": ("[^"]*"|[0-9.e-]+)', "", x)
                    for x in (cache / "receipts.jsonl").read_text().splitlines()]
        oc = json.loads((pytester.path / f"o-{mode}-c.json").read_text())
        ow = json.loads((pytester.path / f"o-{mode}-w.json").read_text())
        # printed values are not compared here (the trace test does): under load the cache's own startup
        # subprocesses (follow.py: strace probe, cc) poll-wait with time.sleep and move the virtual clock by
        # 0.5-1 ms before the first test, in both paths alike (a finding of REPORT-2)
        out[mode] = (store, receipts, oc.get("outcomes"), ow.get("outcomes"),
                     {k: (oc.get("cache") or {}).get(k) for k in ("reused", "ran", "recorded", "not_cached")},
                     {k: (ow.get("cache") or {}).get(k) for k in ("reused", "ran", "recorded", "not_cached")})
    ref, new = out["ref"], out["new"]
    assert ref[0] == new[0]                      # the store, byte for byte
    assert ref[1] == new[1]                      # warm receipts
    assert ref[2:] == new[2:]
    assert new[5]["reused"], new[5]              # the warm run reused results (the receipts mean something)


def _ref_clock_module():
    """The reference clock module, loaded under another name (its relative imports resolve to detpy)."""
    spec = importlib.util.spec_from_file_location("detpy._ref_l0_clock", REF / "_ref_l0_clock.py")
    m = importlib.util.module_from_spec(spec)
    m.__package__ = "detpy"
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize("seed", range(6))
def test_clock_arithmetic_matches_reference(seed):
    from detpy import _core, clock

    ref_mod = _ref_clock_module()
    rnd = random.Random(seed)
    epoch, tick, adapt = rnd.choice([(1_735_689_600 * 10**9, 1000, 8), (0, 1, 0), (10**9, 50_000, 3), (5, 0, 2)])
    ref = ref_mod.VirtualClock(epoch, tick, adapt)
    new = clock.VirtualClock(epoch, tick, adapt)
    fields = ("elapsed", "tick_ns", "streak", "test_start", "wall_offset")
    try:
        for _ in range(3000):
            op = rnd.random()
            if op < 0.6:
                assert ref.read() == new.read()
            elif op < 0.75:
                ref.other_event(), new.other_event()
            elif op < 0.88:
                ns = rnd.choice([0, -5, rnd.randrange(10**3), rnd.randrange(10**12), 10**18])
                ref.advance(ns), new.advance(ns)
            elif op < 0.95:
                ref.start_test(), new.start_test()
            else:
                e = rnd.randrange(10**15)
                assert ref.wall_ns(e) == new.wall_ns(e) and ref.mono_ns(e) == new.mono_ns(e)
            ref_mod.CLOCK = ref
            assert ref_mod._rel(ref.elapsed) == _core.clock_rel(ref.elapsed)
            assert tuple(getattr(ref, f) for f in fields) == tuple(getattr(new, f) for f in fields)
    finally:
        _core.clock_activate(False)


def test_seconds_conversion_matches_int_division():
    from detpy import _core

    rnd = random.Random(1)
    vals = [0, 1, -1, 999_999_999, 10**9, 2**53 - 1, 2**53, 2**53 + 1, -(2**53) - 3, 2**63 - 1, -(2**63),
            1_735_689_600 * 10**9, 2**100 + 12345]
    for bits in range(1, 127):
        for _ in range(60):
            v = rnd.getrandbits(bits)
            vals += [v, -v, 1_735_689_600 * 10**9 + v % 10**12]
    for v in vals:
        a, b = _core.clock_ns_to_secs(v), v / 10**9
        assert a.hex() == b.hex(), v


def test_stand_ins_without_the_clock_call_the_real_functions():
    from detpy import clock

    assert clock.CLOCK is None
    import time

    assert abs(clock.time() - time.time()) < 5 and isinstance(clock.time_ns(), int)
    assert clock.monotonic() > 0 and clock.perf_counter_ns() > 0


def test_quiet_flag_is_per_thread():
    import threading

    from detpy import _state

    seen = []
    with _state.quiet():
        assert _state.is_quiet()
        t = threading.Thread(target=lambda: seen.append(_state.is_quiet()))
        t.start()
        t.join()
        with _state.quiet():
            assert _state.is_quiet()
        assert _state.is_quiet()
    assert not _state.is_quiet() and seen == [False]


@pytest.mark.skipif(sys.version_info < (3, 12), reason="timing only")
def test_rust_read_is_faster_than_the_reference(pytester, ref_env):
    """Not an equivalence check: the per-read cost of both paths inside a test (MEASURED, printed)."""
    pytester.makepyfile(test_t='''
import time
def test_t():
    real = time.get_clock_info  # untouched
    import detpy.clock as c
    n = 20000
    t0 = c.real_perf_counter()
    for _ in range(n):
        time.monotonic()
    dt = (c.real_perf_counter() - t0) / n * 1e9
    print("NSPERREAD", round(dt))
''')
    res = {}
    for mode in ("ref", "new"):
        r = _run(pytester, mode)
        line = [x for x in r.stdout.lines if "NSPERREAD" in x]
        res[mode] = int(line[0].split("NSPERREAD")[1].split()[0])
    print("ns per time.monotonic() in a test:", res)
    assert res["new"] < res["ref"]
