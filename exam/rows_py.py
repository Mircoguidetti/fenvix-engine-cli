"""Python rows PY-01 .. PY-08."""
from __future__ import annotations

import os
import re
import textwrap
from pathlib import Path

import fam
import lib
from lib import Ctx, Skip
from projects import P

DET2 = "two --det runs verify identical (0 divergent, 0 missing) and the outcome map equals a plain run's"
CACHE2 = "second --det-cache run reuses >= 50% of passing tests with proof; every outcome equals the plain run's"


def _args(name):
    return list(P[name].get("tests", ["tests"]))


def _install_check(ctx: Ctx, cid: str):
    def fn():
        ctx.need_install()
        rc, out = ctx.sh("fenvix-version", ["fenvix", "version"])
        rc2, out2 = ctx.sh("fenvix-python-help", "fenvix python --help | grep -c -- --det")
        ok = rc == 0 and "detpy" in out and "unavailable" not in out.split("detpy", 1)[1].splitlines()[0] and rc2 == 0
        return ok, f"fenvix version rc={rc}: {' | '.join(out.strip().splitlines()[:3])}; --det in pytest help: {out2.strip()}"
    ctx.run_check(cid, "install succeeds; `fenvix version` prints the detpy version; `fenvix python --help` lists --det", fn)


def py_project_det2(ctx: Ctx, cid: str, name: str, extra=None, args=None, extra_env=None):
    def fn():
        d, env = fam.py_setup(ctx, name, extra)
        return fam.py_det2(ctx, d, env, args or _args(name), f"{cid}-{name}", extra_env)
    ctx.run_check(f"{cid}.{name}", DET2, fn)


def py_project_cache2(ctx: Ctx, cid: str, name: str, extra=None, args=None, extra_env=None):
    def fn():
        d, env = fam.py_setup(ctx, name, extra)
        return fam.py_cache2(ctx, d, env, args or _args(name), f"{cid}-{name}", extra_env=extra_env)
    ctx.run_check(f"{cid}.{name}", CACHE2, fn)


# ---------------------------------------------------------------------------------------------------------------------

def PY_01(ctx: Ctx):
    _install_check(ctx, "PY-01.install")
    for name in ("itsdangerous", "attrs"):
        py_project_det2(ctx, "PY-01.det2", name)
        py_project_cache2(ctx, "PY-01.cache2", name)


def PY_02(ctx: Ctx):
    major = os.environ.get("EXAM_PYTEST", "8")
    pin = {"8": "pytest>=8,<9", "9": "pytest>=9,<10"}[major]
    for name in ("attrs", "more-itertools"):
        py_project_det2(ctx, f"PY-02.det2.pytest{major}", name, extra=[pin])
        py_project_cache2(ctx, f"PY-02.cache2.pytest{major}", name, extra=[pin])

    def seed():
        d, env = fam.py_setup(ctx, "attrs", [pin])
        outs = []
        for i in (1, 2):
            t = ctx.work / f"seed{i}.jsonl"
            rc, out, o = lib.pytest_engine(ctx, d, env, ["--det", "--det-seed=7", f"--det-trace={t}"] + _args("attrs"), f"seed{i}")
            m = re.findall(r"order digest: ([0-9a-f]+)", out)
            outs.append((m[-1] if m else None, o))
        ok = outs[0][0] is not None and outs[0][0] == outs[1][0] and outs[0][1] == outs[1][1] and bool(outs[0][1])
        return ok, f"order digests {outs[0][0]} / {outs[1][0]}; outcome maps equal: {outs[0][1] == outs[1][1]}"
    ctx.run_check(f"PY-02.seed.pytest{major}", "--det-seed=7 twice: same order digest and outcomes", seed)


# -- PY-03 -------------------------------------------------------------------------------------------------------------

RUNNERS = {
    # runner: (project, plain argv, engine argv after `fenvix python-runner`, extra install)
    "unittest": ("more-itertools", ["python", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                 ["unittest", "--det", "discover", "-s", "tests", "-t", "."], []),
    "django": ("bakerydemo", ["python", "manage.py", "test", "--noinput"],
               ["django", "manage.py", "test", "--det", "--noinput"], []),
    "nose2": ("nose2", ["python", "-m", "nose2", "-s", "."], ["nose2", "--det", "-s", "."], []),
    "ward": ("ward", ["python", "-m", "ward", "test"], ["ward", "--det", "test"], []),
    "zope": ("zope.interface", ["python", "-m", "zope.testrunner", "--test-path=src"],
             ["zope-testrunner", "--det", "--test-path=src"], []),
    # functoolz/dicttoolz use relative imports, which `python -m doctest FILE` cannot import
    "doctest": ("toolz", ["python", "-m", "doctest", "-v", "toolz/itertoolz.py"],
                ["doctest", "--det", "-v", "toolz/itertoolz.py"], []),
}


def _runner_counts(out: str, rc) -> dict:
    c = {"rc": rc}
    m = re.search(r"(\d+) passed and (\d+) failed", out)  # doctest -v
    if m:
        c["passed"], c["failed"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"Ran (\d+) tests?", out)
    if m:
        c["ran"] = int(m.group(1))
    m = re.search(r"FAILED \((.*?)\)", out)
    if m:
        c["failed"] = m.group(1)
    m = re.search(r"(\d+) passed", out)
    if m:
        c["passed"] = int(m.group(1))
    m = re.search(r"Total: (\d+) tests?", out) or re.search(r"Total: (\d+) tests, (\d+) failures", out)
    if m:
        c["total"] = m.group(0)
    return c


def _runner_env(name, d, env):
    e = dict(env)
    if name == "django":
        e["DJANGO_SETTINGS_MODULE"] = "bakerydemo.settings.test" if (d / "bakerydemo/settings/test.py").exists() else "bakerydemo.settings.dev"
    return e


def PY_03(ctx: Ctx):
    for r, (name, plain, eng, extra) in RUNNERS.items():
        def det2(r=r, name=name, plain=plain, eng=eng, extra=extra):
            d, env = fam.py_setup(ctx, name, extra)
            env = _runner_env(r, d, env)
            rc0, out0 = ctx.sh(f"plain-{r}", plain, cwd=d, env=env, timeout=2400)
            t = [ctx.work / f"{r}-det1.jsonl", ctx.work / f"{r}-det2.jsonl"]
            res = []
            for i in (0, 1):
                rc, out = ctx.sh(f"fenvix-{r}-det{i + 1}", ["fenvix", "python-runner"] + eng[:1] + [f"--det-trace={t[i]}"] + eng[1:],
                                 cwd=d, env=env, timeout=2400)
                res.append((rc, out))
            vok, vdesc, rep = lib.verify(ctx, d, env, t[0], t[1], f"{r}-verify")
            c0, c1 = _runner_counts(out0, rc0), _runner_counts(res[0][1], res[0][0])
            same = c0 == c1
            base = "BASELINE: the plain runner fails on this project/leg; " if rc0 != 0 else ""
            return vok and same and rc0 == 0, f"{base}verify: {vdesc}; plain {c0} vs engine {c1}", {"first_divergence": lib.first_divergence(rep)[:3]}
        ctx.run_check(f"PY-03.{r}.det2", "two --det runs verify identical; exit status and counts equal the plain runner's", det2)

        def cache2(r=r, name=name, plain=plain, eng=eng, extra=extra):
            d, env = fam.py_setup(ctx, name, extra)
            env = _runner_env(r, d, env)
            cache = ctx.work / f"{r}-cache"
            rc0, out0 = ctx.sh(f"plain-{r}", plain, cwd=d, env=env, timeout=2400)
            res = []
            for i in (1, 2):
                rc, out = ctx.sh(f"fenvix-{r}-cache{i}", ["fenvix", "python-runner"] + eng[:1] + [f"--det-cache={cache}"] + eng[1:],
                                 cwd=d, env=env, timeout=2400)
                res.append((rc, out, lib.reused_count(out)))
            ok = res[1][2] > 0 and res[1][0] == rc0
            return ok, f"run 2 reused {res[1][2]}; rc plain={rc0} run1={res[0][0]} run2={res[1][0]}"
        ctx.run_check(f"PY-03.{r}.cache2", "second --det-cache run reuses >= 1 test with proof; exit status equals plain", cache2)

    def repro():
        ctx.need_install()
        rc, out = ctx.sh("fenvix-repro-help", ["fenvix", "repro", "--help"])
        rc2, out2 = ctx.sh("detpy-repro-runner", ["python3", "-m", "detpy", "repro", "--help"])
        has_runner = "--runner" in out2
        ok = rc == 0 and "--runner" in out
        return ok, (f"`fenvix repro --help` rc={rc} ({out.strip().splitlines()[-1][:120] if out.strip() else ''}); "
                    f"engine `python -m detpy repro` has a --runner option: {has_runner} (pytest only otherwise)")
    ctx.run_check("PY-03.repro", "`fenvix repro <test> --runner <unittest|django|nose2|ward|zope|doctest>` exists", repro)


# -- PY-04 -------------------------------------------------------------------------------------------------------------

SQLITE = {"SQLITE": "1"}  # django-model-utils' own switch to its sqlite settings (tests/settings.py)


def PY_04(ctx: Ctx):
    name = "django-model-utils"
    py_project_det2(ctx, "PY-04.det2", name, extra_env=SQLITE)
    py_project_cache2(ctx, "PY-04.cache2", name, extra_env=SQLITE)

    def edit():
        d, env = fam.py_setup(ctx, name)

        def ed(d):
            fam.replace_in(d / "tests/models.py", "class Article(", "class Article(  # exam edit\n")
            # behaviour change: a status choice the tests assert on
            p = d / "tests/models.py"
            s = p.read_text()
            m = re.search(r'STATUS = Choices\((.*?)\)', s, re.S)
            if not m:
                raise Skip("anchor STATUS = Choices(...) not found")
            p.write_text(s.replace(m.group(0), m.group(0).replace("'draft'", "'drafted'", 1).replace('"draft"', '"drafted"', 1), 1))
            return "tests/models.py: first STATUS choice 'draft' -> 'drafted'"
        return fam.py_edit(ctx, d, env, _args(name), "PY-04-edit", ed, extra_env=SQLITE)
    ctx.run_check("PY-04.edit", "EDIT: dependent tests rerun, the others are reused, outcomes equal a plain rerun", edit)

    def order():
        d, env = fam.py_setup(ctx, name)
        rc0, _, plain = lib.pytest_plain(ctx, d, env, _args(name), "pd-plain", SQLITE)
        rc, out, o = lib.pytest_engine(ctx, d, env, ["--det", "--det-seed=3"] + _args(name), "pd-seed3", SQLITE)
        ok, desc = lib.cmp_outcomes(o, plain)
        return ok, f"--det-seed=3 vs plain: {desc}"
    ctx.run_check("PY-04.order", "--det-seed=3 keeps pytest-django's groups; outcomes equal plain", order)


# -- PY-05 -------------------------------------------------------------------------------------------------------------

ODPAIR = '''
STATE = {}


def test_a_setter():
    STATE["x"] = 1


def test_b_victim():
    assert STATE.get("x") == 1
'''


def PY_05(ctx: Ctx):
    name = "attrs"
    a = _args(name)

    def det2():
        d, env = fam.py_setup(ctx, name)
        return fam.py_det2(ctx, d, env, ["-n", "2"] + a, "xd-n2", plain_args=a)
    ctx.run_check("PY-05.det2", "--det -n 2 twice: traces identical; outcomes equal serial plain", det2)

    def n4():
        d, env = fam.py_setup(ctx, name)
        _, _, plain = lib.pytest_plain(ctx, d, env, a, "xd-serial")
        _, _, o4 = lib.pytest_engine(ctx, d, env, ["--det", "-n", "4"] + a, "xd-n4")
        return lib.cmp_outcomes(o4, plain)
    ctx.run_check("PY-05.n4", "--det -n 4 outcomes equal serial", n4)

    def cache2():
        d, env = fam.py_setup(ctx, name)
        return fam.py_cache2(ctx, d, env, ["-n", "2"] + a, "xd-cache")
    ctx.run_check("PY-05.cache2", "--det --det-cache -n 2 twice: reuse, outcomes equal plain", cache2)

    def odpair():
        d, env = fam.probe_host(ctx)
        rel = fam.write_probe(d, "odpair", ODPAIR)
        verdicts = {}
        _, _, plain = lib.pytest_plain(ctx, d, env, [rel], "od-plain")
        verdicts["plain"] = plain
        for tag, args in (("det", ["--det"]), ("n2", ["--det", "-n", "2"]), ("n4", ["--det", "-n", "4"]),
                          ("cache-n2", ["--det", f"--det-cache={ctx.work / 'odc'}", "-n", "2"]),
                          ("isolate", ["--det", "--det-isolate"])):
            rc, out, o = lib.pytest_engine(ctx, d, env, args + [rel], f"od-{tag}")
            verdicts[tag] = o
        (d / rel).unlink(missing_ok=True)
        base = {k: lib.norm(v) for k, v in plain.items()}
        bad = {t: o for t, o in verdicts.items() if t != "plain" and {k: lib.norm(v) for k, v in o.items()} != base}
        return not bad and bool(base), f"plain {base}; differing modes: {bad}"
    ctx.run_check("PY-05.odpair", "an order-dependent pair has the plain verdict serial, -n 2, -n 4, cache -n 2, --det-isolate",
                  odpair, gaps=["G-0172", "G-0175", "G-0176", "G-0169"])


# -- PY-06 -------------------------------------------------------------------------------------------------------------

PLUGINS = {
    "pytest-asyncio": ("aiosignal", [], None),
    "pytest-mock": ("pytest-mock", [], None),
    "pytest-cov": ("itsdangerous", ["pytest-cov"], ["tests", "--cov=itsdangerous", "--cov-report=term"]),
    "freezegun": ("freezegun", [], None),
    "time-machine": ("time-machine", [], None),
}


def PY_06(ctx: Ctx):
    for plug, (name, extra, args) in PLUGINS.items():
        def det2(plug=plug, name=name, extra=extra, args=args):
            d, env = fam.py_setup(ctx, name, extra, key=f"{name}:{plug}")
            return fam.py_det2(ctx, d, env, args or _args(name), f"pl-{plug}")
        ctx.run_check(f"PY-06.{plug}.det2", DET2, det2)

        def cache2(plug=plug, name=name, extra=extra, args=args):
            d, env = fam.py_setup(ctx, name, extra, key=f"{name}:{plug}")
            return fam.py_cache2(ctx, d, env, args or _args(name), f"plc-{plug}")
        ctx.run_check(f"PY-06.{plug}.cache2", CACHE2, cache2)

    def cov():
        d, env = fam.py_setup(ctx, "itsdangerous", ["pytest-cov"], key="itsdangerous:pytest-cov")
        rc0, out0, _ = lib.pytest_plain(ctx, d, env, ["tests", "--cov=itsdangerous", "--cov-report=term"], "cov-plain")
        rc1, out1, _ = lib.pytest_engine(ctx, d, env, ["--det", "tests", "--cov=itsdangerous", "--cov-report=term"], "cov-det")
        tot = lambda s: (re.findall(r"^TOTAL\s+.*$", s, re.M) or [None])[-1]
        return tot(out0) is not None and tot(out0) == tot(out1), f"plain {tot(out0)!r} / det {tot(out1)!r}"
    ctx.run_check("PY-06.cov-report", "under --det the coverage TOTAL line equals the plain run's", cov)


# -- PY-07 -------------------------------------------------------------------------------------------------------------

THREAD_RACE = '''
import threading, sys


def test_thread_race():
    sys.setswitchinterval(1e-6)
    n = [0]

    def work():
        for _ in range(20000):
            v = n[0]
            n[0] = v + 1
    ts = [threading.Thread(target=work) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert n[0] == 40000
'''

EXECUTOR_RACE = '''
import asyncio, time


def test_executor_race():
    order = []

    def job(name, spin):
        x = 0
        for i in range(spin):
            x += i
        order.append(name)

    async def main():
        loop = asyncio.get_running_loop()
        await asyncio.gather(loop.run_in_executor(None, job, "a", 200000), loop.run_in_executor(None, job, "b", 200000))
    asyncio.run(main())
    assert order == ["a", "b"]
'''


def PY_07(ctx: Ctx):
    def options():
        ctx.need_install()
        rc, out = ctx.sh("pytest-help", "fenvix python --help")
        have = {o: (o in out) for o in ("--det-threads", "--det-async")}
        return all(have.values()), f"options present: {have}"
    ctx.run_check("PY-07.options", "--det-threads and --det-async exist", options, gaps=["G-0546", "G-0509", "G-0517"])

    def stable():
        d, env = fam.probe_host(ctx)
        res = {}
        for nm, body in (("thread_race", THREAD_RACE), ("executor_race", EXECUTOR_RACE)):
            rel = fam.write_probe(d, nm, body)
            outs, fps = [], []
            for i in range(8):
                t = ctx.work / f"l1-{nm}-{i}.jsonl"
                rc, out, o = lib.pytest_engine(ctx, d, env, ["--det", "--det-threads", "--det-async", f"--det-trace={t}", rel],
                                               f"l1-{nm}-{i}")
                outs.append(tuple(sorted(o.items())))
            res[nm] = len(set(outs))
            (d / rel).unlink(missing_ok=True)
        return all(v == 1 for v in res.values()), f"distinct outcome sets over 8 runs: {res}"
    ctx.run_check("PY-07.probe-stable", "8 --det runs of a thread race and an executor race: one outcome each", stable,
                  gaps=["G-0518"])

    def honest():
        d, env = fam.probe_host(ctx)
        rel = fam.write_probe(d, "thread_race", THREAD_RACE)
        traces, outs = [], []
        for i in range(6):
            t = ctx.work / f"hon-{i}.jsonl"
            rc, out, o = lib.pytest_engine(ctx, d, env, ["--det", f"--det-trace={t}", rel], f"hon-{i}")
            traces.append(t)
            outs.append(tuple(sorted(o.items())))
        (d / rel).unlink(missing_ok=True)
        if len(set(outs)) == 1:
            return True, f"one outcome over 6 runs ({outs[0]}): nothing to flag"
        rc, out = ctx.sh("hon-verify", ["fenvix", "verify"] + [str(t) for t in traces], cwd=d, env=env)
        return rc != 0, f"{len(set(outs))} distinct outcomes over 6 runs; verify rc={rc}: {out.strip().splitlines()[-1] if out.strip() else ''}"
    ctx.run_check("PY-07.verify-honest", "runs whose thread order differed are never reported identical", honest,
                  gaps=["G-0180"])

    def anyio():
        d, env = fam.py_setup(ctx, "anyio")
        return fam.py_det2(ctx, d, env, _args("anyio"), "anyio")
    ctx.run_check("PY-07.anyio-det2", DET2, anyio)


# -- PY-08 -------------------------------------------------------------------------------------------------------------

CHILD = '''
import os, subprocess


def test_child_reads_file():
    out = subprocess.run(["cat", os.environ["EXAM_F"]], capture_output=True, text=True).stdout
    assert out == "a"
'''

CTYPES_ENV = '''
import ctypes, ctypes.util


def test_c_getenv():
    libc = ctypes.CDLL(ctypes.util.find_library("c"))
    libc.getenv.restype = ctypes.c_char_p
    assert libc.getenv(b"EXAM_X") == b"a"
'''

CTYPES_CLOCK = '''
import ctypes, ctypes.util


def test_c_clock():
    libc = ctypes.CDLL(ctypes.util.find_library("c"))
    libc.time.restype = ctypes.c_long
    assert libc.time(None) < int(__import__("os").environ.get("EXAM_DEADLINE", "0"))
'''

NATIVE_FILE = '''
import os, zlib


def test_native_reads_outside_root():
    with open(os.environ["EXAM_F"], "rb") as fh:
        data = fh.read()
    assert zlib.crc32(data) == zlib.crc32(b"a")
'''


def PY_08(ctx: Ctx):
    f = ctx.work / "exam-f.txt"

    def setf(v):
        def _s(d):
            f.write_text(v)
        return _s

    def child():
        f.write_text("a")
        return fam.py_cache_probe(ctx, "child", CHILD, {"EXAM_F": str(f)}, {"EXAM_F": str(f)}, between=setf("b"))
    ctx.run_check("PY-08.child", "a test reading a child's output is not reused after the child's input changed", child)

    def cenv():
        return fam.py_cache_probe(ctx, "cenv", CTYPES_ENV, {"EXAM_X": "a"}, {"EXAM_X": "b"})
    ctx.run_check("PY-08.ctypes-env", "a C getenv read that changed is not reused", cenv)

    def cclock():
        import time
        deadline = int(time.time()) + 20
        body = CTYPES_CLOCK.replace('int(__import__("os").environ.get("EXAM_DEADLINE", "0"))', str(deadline))
        return fam.py_cache_probe(ctx, "cclock", body, {}, {}, between=lambda d: time.sleep(max(0, deadline + 2 - time.time())))
    ctx.run_check("PY-08.ctypes-clock", "a test reading the C clock is never reused with a stale outcome", cclock)

    def native():
        f.write_text("a")
        return fam.py_cache_probe(ctx, "native", NATIVE_FILE, {"EXAM_F": str(f)}, {"EXAM_F": str(f)}, between=setf("b"))
    ctx.run_check("PY-08.native-file", "a file outside the root read by the test changed: not reused", native)
