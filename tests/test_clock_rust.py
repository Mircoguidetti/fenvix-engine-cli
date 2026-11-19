"""Round 2 of the clock in Rust (``crates/detpy-py/src/clock.rs``): ``time.sleep`` and its decision to also wait
for real, the wall-derived ``time`` functions, ``clock_gettime(_ns)``, ``datetime.now`` / ``utcnow``, the timeout
rules of ``Condition.wait``, ``selectors.*.select`` and ``_TimedLock.acquire``, ``_mark_external`` and
``_time_machine_ns``, against the Python original (``tests/rust_hotpaths_ref/_ref_l0_clock_r2.py``, installed by
``-p _l0ref`` with ``DETPY_L0_REF=clock2``).

* whole sessions: a project exercising every one of them, run with the reference module and with the Rust path:
  ``--det`` traces byte-identical, printed values identical, ``--det-cache`` stores, warm receipts and outcomes
  identical;
* unit level, in this process: argument validation (exception type, message, context), the clock's state after each
  call, the recorded events and sites, warnings, the wait rules on stub waits, the time-machine travel, the
  child-process check (with its audit events), the process-start stand-ins' disguise;
* the per-call cost of both paths inside a recorded test (MEASURED, printed).
"""

from __future__ import annotations

import datetime as dt
import decimal
import fractions
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
import types
import warnings
from pathlib import Path

import pytest

REF = Path(__file__).parent / "rust_hotpaths_ref"
HAS_TIME_MACHINE = importlib.util.find_spec("time_machine") is not None

PROJECT = {
    "pkg/__init__.py": "",
    "pkg/waits.py": '''
import time
from time import sleep as bound_sleep, strftime as bound_strftime   # module-level references: rebound


def nap(x):
    bound_sleep(x)                              # a user-code site one frame down


def stamp():
    return (time.localtime(), time.gmtime(), time.ctime(), time.asctime(), bound_strftime("%Y-%m-%d %H:%M:%S"))
''',
    "conftest.py": '''
import pytest


@pytest.fixture
def external():
    """Whether the test started a process (the reference keeps a dict, the Rust path a flag)."""
    import detpy.clock as c

    def get():
        return c._EXTERNAL["started"] if hasattr(c, "_EXTERNAL") else c._core.clock_external_started()

    return get


@pytest.fixture
def napped():
    import time
    time.sleep(0.002)                            # fixture setup sleep
    yield time.monotonic()
    time.localtime()                             # teardown read
''',
    "test_sleep.py": '''
import decimal
import fractions
import pickle
import sched
import time
from unittest import mock

from pkg import waits


class NumpyLike:                                 # numpy scalars: neither int nor float, converted by float()
    def __init__(self, v):
        self.v = v

    def __float__(self):
        return self.v

    def __repr__(self):
        return f"NumpyLike({self.v!r})"


class IntSub(int):
    pass


class FloatSub(float):
    pass


GOOD = [0, 1, 0.5, 2.5e-7, 1e-12, True, False, 100, decimal.Decimal("0.25"), fractions.Fraction(1, 3),
        NumpyLike(0.125), "0.1", b"0.2", IntSub(2), FloatSub(0.75), decimal.Decimal("1e-15"), 10 ** -30]
BAD = [float("nan"), -1, -0.5, None, [], object, "x", decimal.Decimal("NaN"), decimal.Decimal("sNaN"),
       decimal.Decimal("-1"), float("inf"), float("-inf"), 1j, NumpyLike("x"), NumpyLike(float("nan")),
       fractions.Fraction(-1, 3)]


def show(e):
    return (type(e).__name__, str(e), type(e.__context__).__name__)


def test_sleep_values(napped):
    t0 = time.monotonic()
    for v in GOOD:
        time.sleep(v)
        print("VAL", repr(v), time.monotonic() - t0)
    for v in BAD:
        try:
            time.sleep(v)
            print("VAL", repr(v), "slept", time.monotonic() - t0)
        except Exception as e:
            print("VAL", repr(v) if v is not object else "object", show(e))


def test_sleep_call_forms():
    class Holder:
        sleeper = time.sleep                    # a builtin stored on a class does not bind

    Holder().sleeper(0.001)
    time.sleep(secs=0.002)
    waits.nap(0.003)
    for call in (lambda: time.sleep(), lambda: time.sleep(1, 2), lambda: time.sleep(x=1),
                 lambda: time.sleep(1, secs=2)):
        try:
            call()
        except TypeError as e:
            print("VAL", show(e))
    s = sched.scheduler(time.monotonic, time.sleep)      # sleeps from the stdlib
    s.enter(0.01, 1, time.time)
    s.run()
    print("VAL", time.monotonic(), time.sleep.__name__, time.sleep.__qualname__, time.sleep.__module__,
          repr(time.sleep), time.sleep.__doc__, pickle.loads(pickle.dumps(time.sleep)) is time.sleep)


def test_sleep_with_open_mocked():
    with mock.patch("builtins.open", mock.mock_open(read_data="123 ")):
        time.sleep(0.001)                       # "a child is alive": waits for real
    with mock.patch("builtins.open", side_effect=FileNotFoundError("gone")):
        time.sleep(0.001)
    with mock.patch("builtins.open", mock.mock_open(read_data=" \\n")):
        time.sleep(0.001)
    print("VAL", time.monotonic())


def test_sleep_inside_threads():
    import threading

    go = threading.Event()
    t = threading.Thread(target=go.wait)
    t.start()
    t0 = time.monotonic()
    time.sleep(0.01)                            # another thread is alive: waits for real
    go.set()
    t.join()
    go.clear()
    d = threading.Thread(target=go.wait, name="detpy-helper")   # detpy's own threads do not count
    d.start()
    time.sleep(0.01)
    go.set()
    d.join()
    print("VAL", time.monotonic() - t0)
''',
    "test_wall.py": '''
import datetime as dt
import email.utils
import inspect
import os
import time
import warnings

from pkg import waits


def test_wall_derived():
    print("VAL", waits.stamp())
    print("VAL", time.localtime(0), time.localtime(None), time.localtime(secs=86400), time.gmtime(10 ** 9),
          time.ctime(0), time.ctime(None), time.asctime(time.gmtime(0)), time.asctime(None),
          time.strftime("%Y", time.gmtime(0)), time.strftime(fmt="%H:%M", t=time.gmtime(3600)), time.strftime("%j"),
          time.strftime("%Y", None))
    for call in (lambda: time.localtime("x"), lambda: time.localtime(1, 2), lambda: time.strftime(),
                 lambda: time.strftime(1), lambda: time.asctime(5), lambda: time.ctime(t=1),
                 lambda: time.gmtime(float("nan")), lambda: time.asctime(1, 2), lambda: time.strftime("%Y", 1, 2)):
        try:
            call()
        except Exception as e:
            print("VAL", type(e).__name__, e)
    print("VAL", email.utils.formatdate(localtime=True), email.utils.localtime())   # stdlib callers
    print("VAL", [str(inspect.signature(f)) for f in (time.localtime, time.gmtime, time.ctime, time.asctime,
                                                       time.strftime, time.clock_gettime, time.clock_gettime_ns)],
          [(f.__name__, f.__module__, repr(f), f.__doc__) for f in (time.localtime, time.strftime, time.clock_gettime)])


def test_clock_gettime():
    virtual = ("CLOCK_REALTIME", "CLOCK_TAI", "CLOCK_MONOTONIC", "CLOCK_MONOTONIC_RAW", "CLOCK_BOOTTIME",
               "CLOCK_UPTIME", "CLOCK_HIGHRES")
    for n in sorted(x for x in dir(time) if x.startswith("CLOCK_")):
        i = getattr(time, n)
        try:
            a, b = time.clock_gettime(i), time.clock_gettime_ns(i)
        except OSError as e:
            print("VAL", n, "OSError", e)
            continue
        print("VAL", n, repr(a), b) if n in virtual else print("VAL", n, type(a).__name__, type(b).__name__)
    for bad in (0.0, 1.0, True, "x", [], None, 12345, -7):
        for f in (time.clock_gettime, time.clock_gettime_ns):
            try:
                v = f(bad)
                print("VAL", repr(bad), type(v).__name__, v if isinstance(bad, (float, bool)) else "")
            except Exception as e:
                print("VAL", repr(bad), type(e).__name__, e)
    for call in (lambda: time.clock_gettime(), lambda: time.clock_gettime_ns(0, 1),
                 lambda: time.clock_gettime(clk_id=time.CLOCK_REALTIME), lambda: time.clock_gettime(clk=0)):
        try:
            print("VAL", call())
        except TypeError as e:
            print("VAL", type(e).__name__, e)


class Sub(dt.datetime):
    pass


class Over(dt.datetime):
    @classmethod
    def fromtimestamp(cls, t, tz=None):         # a Python override: runs under a detpy frame, as it did
        time.time()
        return super().fromtimestamp(t, tz)


def test_datetime_now():
    print("VAL", dt.datetime.now(), dt.datetime.now(dt.timezone.utc),
          dt.datetime.now(tz=dt.timezone(dt.timedelta(hours=5))), Sub.now(), type(Sub.now()).__name__, Over.now(),
          type(Over.now(dt.timezone.utc)).__name__, dt.datetime(2020, 1, 1).now(), dt.date.today(),
          dt.datetime.today(), str(inspect.signature(dt.datetime.now)), dt.datetime.now.__name__)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        u = dt.datetime.utcnow()
        u2 = Over.utcnow()
        u3 = Sub.utcnow()
    print("VAL", u, u2, type(u2).__name__, u3, type(u3).__name__,
          [(x.category.__name__, str(x.message), os.path.basename(x.filename), x.lineno) for x in w])
    for call in (lambda: dt.datetime.now("bad"), lambda: dt.datetime.now(1, 2), lambda: dt.datetime.now(foo=1),
                 lambda: dt.datetime.utcnow(1), lambda: Over.now(1, 2), lambda: dt.datetime.now(dt.timezone.utc, tz=1)):
        try:
            call()
        except Exception as e:
            print("VAL", type(e).__name__, e)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        try:
            dt.datetime.utcnow()
            print("VAL no warning")
        except DeprecationWarning as e:
            print("VAL raised", e)
    print("VAL", dt.datetime.now())
''',
    "test_waits.py": '''
import decimal
import queue
import selectors
import socket
import sys
import threading
import time


def test_condition_event_queue():
    t0 = time.monotonic()
    ev = threading.Event()
    print("VAL", ev.wait(0.01), ev.wait(timeout=0.005), time.monotonic() - t0)
    c = threading.Condition()
    with c:
        print("VAL", c.wait(0.003), c.wait_for(lambda: True, timeout=0.004), c.wait(0), c.wait(-0.5),
              time.monotonic() - t0)
        for bad in (decimal.Decimal("0.002"), "x"):
            try:
                c.wait(bad)
            except TypeError as e:
                print("VAL", type(e).__name__, e)
    ev.set()
    print("VAL", ev.wait(0.5), ev.wait(), time.monotonic() - t0)
    q = queue.Queue()
    q.put(1)
    print("VAL", q.get(timeout=1), q.empty(), time.monotonic() - t0)
    b = threading.Barrier(1)
    print("VAL", b.wait(timeout=0.5), time.monotonic() - t0)


def test_locks():
    t0 = time.monotonic()
    for factory in (threading.Lock, threading.RLock):
        lock, held, release = factory(), threading.Event(), threading.Event()

        def owner():
            with lock:
                held.set()
                release.wait()

        t = threading.Thread(target=owner)
        t.start()
        held.wait()
        r = [lock.acquire(timeout=0.01), lock.acquire(False), lock.acquire(True, 0.002), lock.acquire(True, 0),
             lock.acquire(blocking=True, timeout=0.0015)]
        try:
            lock.acquire(False, 0.1)
        except ValueError as e:
            r.append(str(e))
        print("VAL", factory.__name__, r, time.monotonic() - t0)
        release.set()
        t.join()
        with lock:
            pass
        print("VAL", lock.acquire(timeout=0.5))
        lock.release()
    if sys.version_info >= (3, 13):
        print("VAL", isinstance(threading.Lock(), threading.Lock), isinstance(threading.RLock(), threading.Lock),
              issubclass(type(threading.Lock()._lock), threading.Lock), repr(threading.Lock))


def test_selectors():
    a, b = socket.socketpair()
    try:
        for name in ("SelectSelector", "PollSelector", "EpollSelector"):
            cls = getattr(selectors, name, None)
            if cls is None:
                continue
            s = cls()
            s.register(a, selectors.EVENT_READ)
            t0 = time.monotonic()
            r1, r2 = s.select(0.0015), s.select(timeout=0)
            r3 = s.select(0.0000002)
            b.send(b"x")
            r4 = len(s.select(1))
            a.recv(1)
            print("VAL", name, r1, r2, r3, r4, time.monotonic() - t0)
            s.close()
    finally:
        a.close()
        b.close()
''',
    "test_processes.py": '''
import os
import subprocess
import sys
import time


def test_subprocess_makes_sleeps_real(external):
    import detpy.clock as c

    t0 = time.monotonic()
    print("VAL", external(), c._children_alive())
    time.sleep(0.001)
    subprocess.run([sys.executable, "-c", "pass"], check=True)
    print("VAL", external())
    time.sleep(0.002)
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
    try:
        print("VAL children", c._children_alive(), c._other_threads_alive(), c._in_event_loop())
        time.sleep(0.001)
    finally:
        p.kill()
        p.wait()
    print("VAL", c._children_alive(), time.monotonic() - t0)


def test_flag_is_per_test(external):
    print("VAL", external(), os.system("true"), external(), os.system.__name__, os.system.__module__,
          repr(os.system), type(subprocess.Popen.__init__).__name__ in ("function", "external_method_stand_in"),
          subprocess.Popen.__init__.__name__, subprocess.Popen.__init__.__qualname__)
    time.sleep(0.001)
''',
    # Last, with no recorded clock read after their waits: queue.Queue.get(timeout=...) waits for "deadline - now" on
    # queue's own (real) clock, so the virtual clock advances by a real-time-dependent amount, in both paths
    # (Condition.wait_for alike); asyncio's waits likewise (below).
    "test_zlast.py": '''
import asyncio
import queue
import time


def test_queue_timeout():
    q = queue.Queue()
    try:
        q.get(timeout=0.006)
    except queue.Empty:
        print("VAL empty")


def test_asyncio():
    # The loop's select timeouts are "deadline - now" on the loop's real clock, rounded up to the millisecond: a
    # loop iteration slower than that (a loaded machine) moves the virtual clock by one more millisecond, in both
    # paths. So nothing reads the (recorded) clock after the loop's waits; the advance is checked unrecorded.
    from detpy import _core

    async def main():
        e0 = _core.clock_state()["elapsed"]
        time.monotonic()
        await asyncio.sleep(0.01)
        try:
            await asyncio.wait_for(asyncio.Event().wait(), 0.02)
        except asyncio.TimeoutError:
            pass
        time.sleep(0.003)                       # inside the loop: waits for real
        return _core.clock_state()["elapsed"] - e0 >= 33_000_000

    print("VAL", asyncio.run(main()))
''',
    "test_tm.py": '''
import datetime as dt
import time
import warnings

import pytest


def test_time_machine():
    tm = pytest.importorskip("time_machine")
    with tm.travel(dt.datetime(1985, 10, 26, 1, 21, tzinfo=dt.timezone.utc), tick=False):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            u = dt.datetime.utcnow()
        print("VAL", time.time(), dt.datetime.now(dt.timezone.utc), time.localtime(), time.strftime("%Y-%m-%d"),
              time.clock_gettime(time.CLOCK_REALTIME), time.ctime(), time.gmtime(), u)
    with tm.travel(dt.datetime(1985, 10, 26, tzinfo=dt.timezone.utc)):   # ticking: with the virtual counter
        print("VAL", time.time(), time.time(), dt.datetime.now(dt.timezone.utc), time.gmtime(), time.asctime(),
              time.clock_gettime_ns(time.CLOCK_REALTIME))
        time.sleep(1)
        print("VAL", time.time(), time.strftime("%H:%M:%S"))
    print("VAL", time.time())
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
    os.environ["DETPY_L0_REF"] = "clock2" if mode == "ref" else "0"
    try:
        r = pytester.runpytest_subprocess("--det", "-p", "no:cacheprovider", "-p", "no:randomly", "-s", "-p", "_l0ref",
                                          *args)
    finally:
        del os.environ["DETPY_L0_REF"]
    out = r.stdout.str()
    assert "Traceback" not in out.split("short test summary")[0], out[-3000:]
    assert r.ret == 0, out[-3000:]
    return r


def _vals(r) -> list:
    return [line[line.index("VAL "):] for line in r.stdout.lines if "VAL " in line]


def test_reference_plugin_installs_the_round2_clock(pytester, ref_env):
    pytester.makepyfile(test_x="import detpy, detpy.clock as c, detpy._state as s\ndef test_x():\n    print('REF', "
                               "getattr(detpy, 'LEVEL0_REFERENCE', False), type(c.sleep).__name__, "
                               "type(c.monotonic).__name__, type(s.record).__name__, hasattr(c, '_EXTERNAL'))\n")
    ref = _run(pytester, "ref")
    new = _run(pytester, "new")
    assert "REF clock2 function builtin_function_or_method builtin_function_or_method True" in ref.stdout.str()
    assert "REF False builtin_function_or_method builtin_function_or_method builtin_function_or_method False" \
        in new.stdout.str()


def test_traces_match_reference(pytester, ref_env):
    _write(pytester.path, PROJECT)
    traces, vals = {}, {}
    for i, mode in enumerate(("ref", "new", "ref", "new")):
        t = pytester.path / f"trace-{mode}-{i}.jsonl"
        r = _run(pytester, mode, f"--det-trace={t}")
        # the header's precompile duration is the only wall-clock value in a trace
        traces.setdefault(mode, []).append(re.sub(rb'"precompile_s":[0-9.]+,', b"", t.read_bytes()))
        vals.setdefault(mode, []).append(_vals(r))
    assert traces["ref"][0] == traces["ref"][1]
    assert traces["new"][0] == traces["new"][1]
    lines_ref = traces["ref"][0].decode().splitlines()
    lines_new = traces["new"][0].decode().splitlines()
    assert len(lines_ref) == len(lines_new)
    for a, b in zip(lines_ref, lines_new):
        assert a == b
    assert traces["ref"][0] == traces["new"][0]
    for a, b in zip(vals["ref"][0], vals["new"][0]):
        assert a == b
    assert vals["ref"][0] == vals["new"][0] and len(vals["new"][0]) >= 60
    assert vals["ref"][0] == vals["ref"][1] and vals["new"][0] == vals["new"][1]
    events = [json.loads(x) for x in lines_new if '"type":"test"' in x]
    ops = {e["o"] for t in events for e in t.get("events", [])}
    assert {"time.sleep", "time.localtime", "time.gmtime", "time.ctime", "time.asctime", "time.strftime",
            "time.clock_gettime", "datetime.now", "datetime.utcnow", "time.time", "time.monotonic"} <= ops, ops
    sites = {e["at"] for t in events for e in t.get("events", []) if e["o"] in ("time.sleep", "datetime.now")}
    assert any(s.startswith("pkg/waits.py:") for s in sites), sites
    out = "\n".join(vals["new"][0])
    # what the project is about did happen
    assert "VAL True" in vals["new"][0]                              # a subprocess set the flag
    assert "VAL children True" in out                                # a live child process was seen
    assert "VAL False 0 True" in out                                 # the flag is per test
    assert "Invalid value NaN (not a number)" in out and "sleep length must be non-negative" in out
    assert "'list' object cannot be interpreted as an integer or float" in out
    assert "DeprecationWarning" in out and "test_wall.py" in out
    assert HAS_TIME_MACHINE is ("1985" in out)


def test_cache_matches_reference(pytester, ref_env):
    _write(pytester.path, PROJECT)
    out = {}

    def norm(b: bytes) -> bytes:
        # the run id (time and pid) and the measured durations are the only wall-clock values of a store; a
        # thread id is in the detail of the /proc reads of time.sleep
        b = re.sub(rb'"(run|duration)": ?("[^"]*"|[0-9.e-]+)', b"", b)
        return re.sub(rb"/proc/self/task/[0-9]+/", b"/proc/self/task/N/", b)

    # Not here: test_sleep_with_open_mocked. With open mocked, its sleeps' check of /proc/self/task/*/children
    # lists /proc/self/task but opens nothing real (no "reads /proc" flag): the test is cached with a dependency on
    # that listing, whose digest (the thread ids) differs from one process to the next in both paths alike. Its
    # audit events are compared at unit level (test_children_alive_and_its_audit_events_match_reference).
    sel = ("-k", "not open_mocked")
    for mode in ("ref", "new"):
        cache = pytester.path / f".cache-{mode}"
        _run(pytester, mode, f"--det-cache={cache}", f"--det-outcomes={pytester.path / f'o-{mode}-c.json'}", *sel)
        store = norm((cache / "proof-cache.json").read_bytes())
        _run(pytester, mode, f"--det-cache={cache}", f"--det-outcomes={pytester.path / f'o-{mode}-w.json'}", *sel)
        receipts = [norm(x) for x in (cache / "receipts.jsonl").read_bytes().splitlines()]
        oc = json.loads(norm((pytester.path / f"o-{mode}-c.json").read_bytes()))
        ow = json.loads(norm((pytester.path / f"o-{mode}-w.json").read_bytes()))
        out[mode] = (store, receipts, oc.get("outcomes"), ow.get("outcomes"),
                     {k: (oc.get("cache") or {}).get(k) for k in ("reused", "ran", "recorded", "not_cached",
                                                                   "not_cached_ids", "not_cached_detail")},
                     {k: (ow.get("cache") or {}).get(k) for k in ("reused", "ran", "recorded", "not_cached",
                                                                   "not_cached_ids", "not_cached_detail")})
    ref, new = out["ref"], out["new"]
    assert ref[0] == new[0]                      # the store, byte for byte
    assert ref[1] == new[1]                      # warm receipts
    assert ref[2:] == new[2:]
    assert new[5]["reused"], new[5]              # the warm run reused results (the receipts mean something)
    assert "reads /proc, /sys or /dev" in (new[4]["not_cached"] or {}), new[4]   # a virtual sleep reads /proc


# -- unit level ------------------------------------------------------------------------------------------------------


@pytest.fixture
def ref():
    """The reference module loaded under another name (its relative imports resolve to detpy). Loading it rewires
    the Rust clock's hooks to its own ``_time_machine_ns``: restored afterwards, with the clock deactivated."""
    from detpy import _core, clock

    spec = importlib.util.spec_from_file_location("detpy._ref_l0_clock_r2", REF / "_ref_l0_clock_r2.py")
    m = importlib.util.module_from_spec(spec)
    m.__package__ = "detpy"
    spec.loader.exec_module(m)
    try:
        yield m
    finally:
        m.CLOCK = None
        _core.clock_activate(False)
        _core.clock_set_hooks([clock.real_time, clock.real_time_ns, clock.real_monotonic, clock.real_monotonic_ns,
                               clock.real_perf_counter, clock.real_perf_counter_ns], None)


class _Events:
    def __init__(self) -> None:
        self.events: list = []

    def record(self, source, op, site, value, thread=0):
        self.events.append((source, op, site, value, thread))


@pytest.fixture
def capture():
    from detpy import _state

    st = _state.STATE
    saved = (st.recorder, st.nodeid, st.threads)
    rec = _Events()
    st.recorder, st.nodeid = rec, "unit::test"
    _state.reset_threads()
    try:
        yield rec
    finally:
        st.recorder, st.nodeid, st.threads = saved


EPOCH = 1_735_689_600 * 10**9


def _fresh(ref_mod, tick=1000, adapt=8):
    """Both modules' clock installed, from the same state (the Rust clock is shared)."""
    from detpy import _core

    ref_mod.CLOCK = ref_mod.VirtualClock(EPOCH, tick, adapt)
    _core.clock_activate(True)
    _core.clock_start_test()


def _state_now():
    from detpy import _core

    return tuple(sorted(_core.clock_state().items()))


def _outcome(f, *args, **kwargs):
    """Result or (exception type, message, context type), and the clock's state after the call."""
    try:
        r = _same_site(f, *args, **kwargs)
        r = ("ok", r if not isinstance(r, time.struct_time) else tuple(r))
    except BaseException as e:  # noqa: B036
        r = ("err", type(e), str(e), type(e.__context__))
    return r, _state_now()


def _same_site(f, *args, **kwargs):
    return f(*args, **kwargs)                    # one call line for both paths: identical sites


def _both(ref_mod, new_f, ref_f, *args, _view=lambda r: r, **kwargs):
    _fresh(ref_mod)
    a = _outcome(ref_f, *args, **kwargs)
    _fresh(ref_mod)
    b = _outcome(new_f, *args, **kwargs)
    assert _view(a) == _view(b), (ref_f, args, kwargs, a, b)
    return b


class _NumpyLike:
    def __init__(self, v):
        self.v = v

    def __float__(self):
        return self.v


class _BadFloat:
    def __float__(self):
        raise OverflowError("too big")


SLEEP_ARGS = [0, 1, 0.5, 2.5e-7, 1e-12, True, False, 10**30, 2**200, decimal.Decimal("0.25"), fractions.Fraction(1, 3),
              _NumpyLike(0.125), "0.1", b"0.2", "  7 ", decimal.Decimal("1e-15"), 10**-30, float("nan"), -1, -0.5,
              None, [], object(), "x", decimal.Decimal("NaN"), decimal.Decimal("sNaN"), decimal.Decimal("-1"),
              float("inf"), float("-inf"), 1j, _NumpyLike("x"), _NumpyLike(float("nan")), fractions.Fraction(-1, 3),
              _BadFloat(), -0.0, 1e300, 4.9e-324, 0.1 + 0.2]


def test_sleep_validation_and_effect_match_reference(ref, capture, monkeypatch):
    from detpy import clock

    calls = []
    # the real sleep is a global both read at call time: a stub records what they would have waited
    monkeypatch.setattr(ref, "real_sleep", lambda s: calls.append(("ref", s)))
    monkeypatch.setattr(clock, "real_sleep", lambda s: calls.append(("new", s)))
    for v in SLEEP_ARGS:
        _both(ref, clock.sleep, ref.sleep, v)
    _both(ref, clock.sleep, ref.sleep, secs=0.25)
    for args, kwargs in (((), {}), ((1, 2), {}), ((), {"x": 1}), ((1,), {"secs": 2}), ((), {"secs": 1, "y": 2})):
        _both(ref, clock.sleep, ref.sleep, *args, **kwargs)
    refs = [(type(s), repr(s)) for who, s in calls if who == "ref"]
    news = [(type(s), repr(s)) for who, s in calls if who == "new"]
    assert refs == news and len(refs) > 15
    ev = capture.events
    assert len(ev) % 2 == 0 and len(ev) > 30
    for i in range(0, len(ev), 2):
        assert ev[i] == ev[i + 1]
    assert ("time", "time.sleep", ev[0][2], "0", 0) in ev
    assert any(e[3] == str(2**200 * 10**9) for e in ev)


def test_sleep_without_the_clock_calls_the_real_one(ref, monkeypatch):
    from detpy import clock

    calls = []
    monkeypatch.setattr(ref, "real_sleep", lambda s: calls.append(("ref", s)))
    monkeypatch.setattr(clock, "real_sleep", lambda s: calls.append(("new", s)))
    for v in ("x", -1, 0.001, None):
        ref.sleep(v)
        clock.sleep(v)
    assert [c[1] for c in calls[::2]] == [c[1] for c in calls[1::2]] == ["x", -1, 0.001, None]


def test_sleep_decision_matches_reference(ref, monkeypatch):
    """The decision to wait for real: --det-sleep=real, another thread, an event loop, a started process."""
    import asyncio

    from detpy import _state, clock

    calls = []
    monkeypatch.setattr(ref, "real_sleep", lambda s: calls.append(("ref", s)))
    monkeypatch.setattr(clock, "real_sleep", lambda s: calls.append(("new", s)))

    def both(external=False):
        n = len(calls)
        _fresh(ref)                              # (a new test: no process started)
        ref._EXTERNAL["started"] = external
        ref.sleep(0.5)
        _fresh(ref)
        if external:
            clock._core.clock_mark_external()
        clock.sleep(0.5)
        assert calls[n][1] == calls[n + 1][1], calls[n:]
        return calls[n][1]

    both()
    monkeypatch.setattr(_state.STATE.config, "sleep", "real")
    assert both() == 0.5
    monkeypatch.setattr(_state.STATE.config, "sleep", "virtual")
    ev = threading.Event()
    t = threading.Thread(target=ev.wait)
    t.start()
    assert both() == 0.5
    ev.set()
    t.join()
    out = []

    async def main():
        out.append(both())

    asyncio.run(main())
    assert out == [0.5]
    assert both(external=True) == 0.5
    ref._EXTERNAL["started"] = False
    clock._core.clock_start_test()
    assert not clock._core.clock_external_started()
    assert ref._other_threads_alive() == clock._other_threads_alive()
    assert ref._in_event_loop() == clock._in_event_loop() is False


def test_children_alive_and_its_audit_events_match_reference(ref, monkeypatch):
    from unittest import mock

    from detpy import clock

    seen = []
    on = [False]

    def hook(event, args):
        if on[0] and event in ("open", "os.listdir"):
            seen.append((event, args))

    sys.addaudithook(hook)

    def both():
        n = len(seen)
        on[0] = True
        try:
            a = ref._children_alive()
            m = len(seen)
            b = clock._children_alive()
        finally:
            on[0] = False
        assert a == b
        assert seen[n:m] == seen[m:], (seen[n:m], seen[m:])
        return a, seen[n:m]

    _, events = both()
    if sys.platform == "linux":
        assert events[0] == ("os.listdir", ("/proc/self/task",))
        assert events[1][0] == "open" and events[1][1][1:] == ("r", os.O_RDONLY | os.O_CLOEXEC)
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert both()[0] is (sys.platform == "linux")
    finally:
        p.kill()
        p.wait()
    # open replaced (a test's mock_open), reads that fail, a listing replaced
    with mock.patch("builtins.open", mock.mock_open(read_data="12 ")):
        assert both()[0] is (sys.platform == "linux")
    with mock.patch("builtins.open", mock.mock_open(read_data=" \n")):
        assert both()[0] is False
    with mock.patch("builtins.open", side_effect=PermissionError("no")):
        assert both()[0] is False
    for listing in (lambda p: ["1", "2"], lambda p: [], lambda p: (_ for _ in ()).throw(FileNotFoundError(p))):
        monkeypatch.setattr(ref, "_real_listdir", listing)
        monkeypatch.setattr(clock, "_real_listdir", listing)
        both()
    with mock.patch("builtins.open", side_effect=RuntimeError("boom")):
        monkeypatch.setattr(ref, "_real_listdir", lambda p: ["1"])
        monkeypatch.setattr(clock, "_real_listdir", lambda p: ["1"])
        with pytest.raises(RuntimeError):
            ref._children_alive()
        with pytest.raises(RuntimeError):
            clock._children_alive()


def test_wall_derived_and_gettime_match_reference(ref, capture):
    from detpy import clock

    cases = [("localtime", ()), ("localtime", (0,)), ("localtime", (None,)), ("localtime", ("x",)),
             ("localtime", (1, 2)), ("gmtime", ()), ("gmtime", (10**9,)), ("gmtime", (float("nan"),)),
             ("ctime", ()), ("ctime", (0,)), ("ctime", (None,)), ("asctime", ()), ("asctime", (time.gmtime(0),)),
             ("asctime", (5,)), ("asctime", (None,)), ("strftime", ("%Y-%m-%d %H:%M:%S",)),
             ("strftime", ("%Y", time.gmtime(0))), ("strftime", ()), ("strftime", (1,)), ("strftime", ("%Y", None)),
             ("strftime", ("%Y", 1, 2))]
    ids = [getattr(time, n) for n in dir(time) if n.startswith("CLOCK_")]
    for i in ids + [0.0, 1.0, True, "x", [], None, 12345, -7]:
        cases += [("clock_gettime", (i,)), ("clock_gettime_ns", (i,))]
    cases += [("clock_gettime", ()), ("clock_gettime_ns", (0, 1))]
    real_ids = {getattr(time, n) for n in ("CLOCK_PROCESS_CPUTIME_ID", "CLOCK_THREAD_CPUTIME_ID") if hasattr(time, n)}

    def kind_only(r):  # the real CPU clocks: the type of the value, the clock's state
        (res, st) = r
        return (res[0], type(res[1])) if res[0] == "ok" else res, st

    for name, args in cases:
        view = kind_only if args and type(args[0]) is int and args[0] in real_ids else (lambda r: r)
        _both(ref, getattr(clock, name), getattr(ref, name), *args, _view=view)
    for kw in ({"secs": 5}, {"t": time.gmtime(0)}, {"fmt": "%Y"}, {"clk_id": 0}, {"x": 1}):
        for name in ("localtime", "asctime", "strftime", "clock_gettime"):
            _both(ref, getattr(clock, name), getattr(ref, name), **kw)
    ev = capture.events
    assert len(ev) % 2 == 0 and len(ev) > 20
    for i in range(0, len(ev), 2):
        assert ev[i] == ev[i + 1]
    assert {e[1] for e in ev} >= {"time.localtime", "time.gmtime", "time.ctime", "time.asctime", "time.strftime",
                                  "time.clock_gettime"}


def test_datetime_now_matches_reference(ref, capture):
    from detpy import clock

    class Sub(dt.datetime):
        pass

    class Over(dt.datetime):
        @classmethod
        def fromtimestamp(cls, t, tz=None):
            time.time()
            return super().fromtimestamp(t, tz)

    utc, east = dt.timezone.utc, dt.timezone(dt.timedelta(hours=3))
    for args, kwargs in [((dt.datetime,), {}), ((dt.datetime, utc), {}), ((dt.datetime,), {"tz": east}),
                         ((Sub,), {}), ((Over, utc), {}), ((dt.datetime, "bad"), {}), ((dt.datetime, 1, 2), {}),
                         ((dt.datetime,), {"foo": 1}), ((), {}), ((Over, 1, 2), {}), ((dt.datetime, utc), {"tz": 1})]:
        _both(ref, clock._dt_now, ref._dt_now, *args, **kwargs)
    for args in [(dt.datetime,), (Sub,), (Over,), (dt.datetime, 1), ()]:
        with warnings.catch_warnings(record=True) as wa:
            warnings.simplefilter("always")
            _fresh(ref)
            a = _outcome(ref._dt_utcnow, *args)
        with warnings.catch_warnings(record=True) as wb:
            warnings.simplefilter("always")
            _fresh(ref)
            b = _outcome(clock._dt_utcnow, *args)
        assert a == b
        assert [(w.category, str(w.message), w.filename, w.lineno) for w in wa] == \
               [(w.category, str(w.message), w.filename, w.lineno) for w in wb]
        if len(args) == 1 and sys.version_info >= (3, 12):   # attributed to the caller (here: _same_site)
            assert wb and wb[0].filename == __file__
    ev = capture.events
    assert len(ev) % 2 == 0 and ev
    for i in range(0, len(ev), 2):
        assert ev[i] == ev[i + 1]
    assert {e[1] for e in ev} >= {"datetime.now", "datetime.utcnow"}


class _StubLock:
    def __init__(self, result):
        self.result, self.calls = result, []

    def acquire(self, blocking=True, timeout=-1):
        self.calls.append((blocking, timeout))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


TIMEOUTS = [None, 0, -1, -0.5, 0.001, 1e-10, 2.5e-7, 0.0015, 1, 3, True, False, decimal.Decimal("0.0012345"),
            fractions.Fraction(1, 3), 1e20, 10**30, 2**130, float("inf"), float("nan"), "x", 0.0000002]


def test_wait_rules_match_reference(ref, monkeypatch):
    from detpy import clock

    for installed in (True, False):
        for result in (False, True, 0, [], [1], None):
            for t in TIMEOUTS:
                # Condition.wait: the real wait is a global both read at call time
                for mod in (ref, clock):
                    monkeypatch.setattr(mod, "_real_condition_wait", lambda self, timeout, r=result: r)

                def run(f, *args):
                    _fresh(ref)
                    if not installed:
                        ref.CLOCK = None
                        clock._core.clock_activate(False)
                    return _outcome(f, *args)

                assert run(ref._condition_wait, object(), t) == run(clock._condition_wait, object(), t)
                stub = lambda self, timeout, r=result: r  # noqa: E731
                assert run(ref._wrap_selector_select(stub), object(), t) == \
                       run(clock._wrap_selector_select(stub), object(), t)
                for blocking in (True, False, 0, 1):
                    a, b = _StubLock(result), _StubLock(result)
                    assert run(ref._TimedLock(a).acquire, blocking, t) == run(clock._TimedLock(b).acquire, blocking, t)
                    assert a.calls == b.calls
        for exc in (RuntimeError("x"), KeyboardInterrupt()):
            a, b = _StubLock(exc), _StubLock(exc)
            assert _outcome(ref._TimedLock(a).acquire, True, 1) == _outcome(clock._TimedLock(b).acquire, True, 1)
    _fresh(ref)
    a, b = _StubLock(False), _StubLock(False)
    assert _outcome(ref._TimedLock(a).acquire) == _outcome(clock._TimedLock(b).acquire)
    assert _outcome(ref._TimedLock(a).__enter__) == _outcome(clock._TimedLock(b).__enter__)
    assert a.calls == b.calls


def test_real_waits_advance_like_reference(ref):
    """The rules on the real primitives (a Condition, a selector, locks), timing out for real."""
    import selectors
    import socket

    from detpy import clock

    def delta(f, *args):
        _fresh(ref)
        before = clock._core.clock_state()["elapsed"]
        r = f(*args)
        return r, clock._core.clock_state()["elapsed"] - before

    c = threading.Condition()
    with c:
        assert delta(ref._condition_wait, c, 0.002) == delta(clock._condition_wait, c, 0.002) == (False, 2_000_000)
    a, b = socket.socketpair()
    try:
        s = selectors.DefaultSelector()
        s.register(a, selectors.EVENT_READ)
        real = vars(type(s))["select"]
        assert delta(ref._wrap_selector_select(real), s, 0.0011) == \
               delta(clock._wrap_selector_select(real), s, 0.0011) == ([], 2_000_000)
        s.close()
    finally:
        a.close()
        b.close()
    for factory in (threading.Lock, threading.RLock):
        lk = factory()
        t = threading.Thread(target=lk.acquire)
        t.start()
        t.join()
        assert delta(ref._TimedLock(lk).acquire, True, 0.001) == delta(clock._TimedLock(lk).acquire, True, 0.001) \
            == (False, 1_000_000)
    if sys.version_info >= (3, 13):
        for mod in (ref, clock):
            lock_type = mod._timed_factory(threading.Lock)
            inst = lock_type()
            assert isinstance(inst, lock_type) and isinstance(threading.Lock(), lock_type)
            assert type(inst) is mod._TimedLock


def test_time_machine_travel_matches_reference(ref, monkeypatch):
    from detpy import _core

    class Traveller:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class NoDict:
        __slots__ = ("_destination_timestamp_ns",)

    def fake(stack, **kw):
        m = types.ModuleType("time_machine")
        if stack is not None:
            m.traveller_stack = stack
        m.__dict__.update(kw)
        return m

    def travellers():
        nd = NoDict()
        nd._destination_timestamp_ns = 7
        return [None, [], (), [Traveller()], [Traveller(_destination_timestamp_ns=None)],
                [Traveller(_destination_timestamp_ns=5 * 10**17, _tick=False)],
                [Traveller(_destination_timestamp_ns=5 * 10**17)], [Traveller(_destination_timestamp_ns=5 * 10**17,
                                                                              _tick=0)],
                [Traveller(_destination_timestamp_ns=1.5, _tick=True)], [nd]]

    for extra in ({}, {"SYSTEM_EPOCH_TIMESTAMP_NS": 10**12}):
        for i in range(len(travellers())):
            outs = []
            for f in (ref._time_machine_ns, _core.clock_time_machine_ns):
                stack = travellers()[i]
                monkeypatch.setitem(sys.modules, "time_machine", fake(stack, **extra))
                seq = []
                for e in (100, 250, 10**15):
                    try:
                        seq.append(("ok", f(e)))
                    except Exception as ex:
                        seq.append(("err", type(ex), str(ex)))
                outs.append(seq)
            assert outs[0] == outs[1], (i, extra, outs)
    monkeypatch.delitem(sys.modules, "time_machine")
    assert ref._time_machine_ns(5) is None and _core.clock_time_machine_ns(5) is None


def test_mark_external_stand_ins_match_reference(ref):
    from detpy import _core, clock
    from detpy._patch import nonbinding

    old = nonbinding(ref._mark_external(os.system), "os", "system")    # as Patcher.set made it
    new = clock._mark_external(os.system, "os", "system")
    for attr in ("__name__", "__qualname__", "__module__", "__doc__", "__wrapped__"):
        assert getattr(old, attr) == getattr(new, attr), attr
    assert repr(old) == repr(new) == "<built-in function system>"
    assert old.__reduce__() == new.__reduce__() == "system"

    class Holder:
        run = new

    _core.clock_start_test()
    assert not _core.clock_external_started()
    assert Holder().run("true") == 0 and _core.clock_external_started()  # does not bind
    _core.clock_start_test()

    import subprocess as sp

    old = ref._mark_external(sp.Popen.__init__)
    new = clock._mark_external(sp.Popen.__init__)
    for attr in ("__name__", "__qualname__", "__doc__", "__wrapped__"):
        assert getattr(old, attr) == getattr(new, attr), attr
    assert (old.__module__, new.__module__) == (ref.__name__, clock.__name__)   # the wrapper's own module

    class C:
        def __init__(self, x, *, y=1):
            self.x, self.y = x, y

    C.__init__ = clock._mark_external(C.__init__)
    c = C(5, y=2)
    assert (c.x, c.y) == (5, 2) and _core.clock_external_started()           # binds
    assert C.__init__ is vars(C)["__init__"] and "C.__init__" in repr(C.__init__)
    _core.clock_start_test()


@pytest.mark.skipif(sys.version_info < (3, 12), reason="timing only")
def test_rust_clock_is_faster_than_the_reference(pytester, ref_env):
    """Not an equivalence check: the per-call cost of both paths inside a recorded --det test (MEASURED, printed)."""
    pytester.makepyfile(test_t='''
import datetime, threading, time
import detpy.clock as c


def per_call(f, n):
    t0 = c.real_perf_counter()
    for _ in range(n):
        f()
    return round((c.real_perf_counter() - t0) / n * 1e9)


def test_t():
    ev = threading.Event()
    r = {"sleep0": per_call(lambda: time.sleep(0), 5000), "now": per_call(datetime.datetime.now, 20000),
         "localtime": per_call(time.localtime, 20000), "event_wait": per_call(lambda: ev.wait(0.001), 200)}
    print("NSPERCALL", r)
''')
    res = {}
    for mode in ("ref", "new"):
        r = _run(pytester, mode, f"--det-trace={pytester.path / f'trace-{mode}.jsonl'}")
        line = [x for x in r.stdout.lines if "NSPERCALL" in x][0]
        res[mode] = eval(line.split("NSPERCALL", 1)[1])  # noqa: S307 - our own printed dict
    print("ns per call in a recorded test:", res)
    assert res["new"]["now"] < res["ref"]["now"] and res["new"]["localtime"] < res["ref"]["localtime"]
