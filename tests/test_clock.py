"""Point 3: virtual clock."""

import time

CLOCK_TESTS = """
import asyncio, datetime, threading, time, queue
import pytest

EPOCH = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)

def test_wall_clock_starts_at_epoch():
    t = time.time()
    assert 1735689600 <= t < 1735689601
    now = datetime.datetime.now(datetime.timezone.utc)
    assert (now - EPOCH).total_seconds() < 1
    assert datetime.date.today().year in (2024, 2025)  # local timezone

def test_sleep_advances_without_waiting():
    w0, m0, p0 = time.time(), time.monotonic(), time.perf_counter()
    time.sleep(3600)
    assert time.time() - w0 >= 3600
    assert time.monotonic() - m0 >= 3600
    assert time.perf_counter() - p0 >= 3600
    with pytest.raises(ValueError):
        time.sleep(-1)

def test_monotonic_never_goes_back():
    seq = [time.monotonic() for _ in range(100)]
    assert seq == sorted(seq) and len(set(seq)) == 100

def test_types_and_isinstance():
    now = datetime.datetime.now()
    assert type(now) is datetime.datetime and datetime.datetime.__module__ == "datetime"
    assert isinstance(now, datetime.datetime) and isinstance(now, datetime.date)
    assert issubclass(datetime.datetime, datetime.date)
    d = datetime.datetime(2020, 1, 2, 3, 4)
    assert repr(d) == "datetime.datetime(2020, 1, 2, 3, 4)"
    assert datetime.datetime.fromisoformat("2020-01-02").year == 2020
    class Sub(datetime.datetime):
        pass
    assert type(Sub.now()) is Sub
    with pytest.warns(DeprecationWarning):
        assert datetime.datetime.utcnow().year == 2025
    assert type(datetime.datetime.today()) is datetime.datetime
    assert type(datetime.date.today()) is datetime.date

def test_pickling_of_patched_functions():
    import pickle, random, os
    assert pickle.loads(pickle.dumps(random.choice)) is random.choice
    assert pickle.loads(pickle.dumps(time.time)) is time.time
    assert pickle.loads(pickle.dumps(os.listdir)) is os.listdir

def test_freezegun_style_subclass_with_metaclass():
    class Meta(type):
        pass
    class FakeDate(datetime.date, metaclass=Meta):
        pass
    class FakeDatetime(datetime.datetime, metaclass=Meta):
        pass
    assert FakeDatetime.now().year in (2024, 2025)

def test_timeouts_advance_the_clock():
    t0 = time.monotonic()
    assert not threading.Event().wait(0.05)
    with pytest.raises(queue.Empty):
        queue.Queue().get(timeout=0.05)
    assert time.monotonic() - t0 >= 0.09

def test_asyncio_still_works():
    async def main():
        await asyncio.sleep(0.01)
        return 42
    assert asyncio.run(main()) == 42

def test_localtime_and_strftime():
    assert time.gmtime().tm_year == 2025
    assert time.strftime("%Y") in ("2024", "2025")
    assert time.gmtime(0).tm_year == 1970
"""


def test_clock_behaviour(pytester, run_det):
    pytester.makepyfile(test_clock=CLOCK_TESTS)
    t0 = time.monotonic()
    result, _ = run_det("-W", "error::pytest.PytestUnraisableExceptionWarning")
    result.assert_outcomes(passed=9)
    assert time.monotonic() - t0 < 60  # nothing really slept for an hour


def test_epoch_option(pytester, run_det):
    pytester.makepyfile(
        test_e="""
        import time
        def test_e():
            assert 946684800 <= time.time() < 946684801
        """
    )
    result, _ = run_det("--det-epoch=2000-01-01T00:00:00+00:00")
    result.assert_outcomes(passed=1)


def test_time_values_are_identical_between_runs(pytester, run_det):
    pytester.makepyfile(
        test_t="""
        import time, datetime
        def test_t():
            print("VAL", time.time(), time.monotonic(), time.perf_counter_ns(), datetime.datetime.now())
        """
    )
    a, _ = run_det("-s")
    b, _ = run_det("-s")
    va = [line for line in a.outlines if "VAL" in line]
    assert va and va == [line for line in b.outlines if "VAL" in line]


def test_modules_imported_before_install_are_rebound(pytester, run_det):
    # A library imported (by a plugin) before detpy installs its controls,
    # holding direct references to the real functions.
    pytester.makepyfile(
        early_lib="""
        from time import time as early_time
        from time import perf_counter
        """,
        early_plugin="""
        import early_lib
        from time import perf_counter as plugin_timer
        """,
        test_x="""
        import early_lib, early_plugin
        from detpy import clock
        def test_x():
            assert 1735689600 <= early_lib.early_time() < 1735689601
            assert early_lib.perf_counter is not clock.real_perf_counter
            # pytest plugins are infrastructure: they keep the real clock
            assert early_plugin.plugin_timer is clock.real_perf_counter
        """,
    )
    result, _ = run_det("-p", "early_plugin")
    result.assert_outcomes(passed=1)


def test_sleep_real_mode(pytester, run_det):
    pytester.makepyfile(
        test_s="""
        import time
        from detpy import clock
        def test_s():
            t0 = clock.real_monotonic()
            time.sleep(0.2)
            assert clock.real_monotonic() - t0 >= 0.19
        """
    )
    result, _ = run_det("--det-sleep=real")
    result.assert_outcomes(passed=1)


def test_time_control_can_be_disabled(pytester, run_det):
    pytester.makepyfile(
        test_d="""
        import time
        def test_d():
            assert time.time() > 1735689600 + 86400 * 300
        """
    )
    result, _ = run_det("--det-disable=time")
    result.assert_outcomes(passed=1)


def test_benchmark_plugins_are_disabled(pytester, run_det):
    # Stand-in for pytest-benchmark (registered under the name "benchmark").
    pytester.makepyfile(
        benchmark="""
        def pytest_addoption(parser):
            parser.addoption("--benchmark-disable", action="store_true")
        """,
        test_b="""
        def test_b(request):
            assert request.config.getoption("benchmark_disable")
        """,
    )
    result, (header, _, _) = run_det("-p", "benchmark")
    result.assert_outcomes(passed=1)
    assert header["meta"]["adjustments"] == ["pytest-benchmark: --benchmark-disable"]
