"""F-01 / F-02 / F-18: regression tests for the audit gaps closed after the first pass (claude/verifier-cli).

Clock: asyncio loop time (G-1514), CPU-time clocks (G-1515), times of files the test wrote (G-1516), the sleep label
(G-2198). Randomness: uuid1 (G-1524), numpy imported lazily (G-1525), numpy generators built without a seed
(G-1526), numpy's own entropy read at import (G-0179) and its effect on repro (G-0177), torch / TensorFlow / Faker
(G-1527), the --det-urandom hint (G-2210). First use: --det options without --det (G-1532, G-1533), .detpy/.gitignore
(G-2207), the precompile message and the cache eviction (G-2202, G-1531), the runner shells' help and errors
(G-1535, G-0983, G-2000..G-2006).

Each test runs pytest twice in subprocesses (real interpreters, real re-exec) and checks that the values the code
under test saw are the same and that ``fenvix verify`` reports the runs identical.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _env(**extra) -> dict:
    env = dict(os.environ)
    for k in ("PYTEST_ADDOPTS", "PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID",
              "PYTEST_CURRENT_TEST"):
        env.pop(k, None)
    env.update(extra)
    return env


def det(proj: Path, tag: str, *args, env=None):
    trace = proj / f"{tag}.jsonl"
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider", "-p", "no:randomly",
                        "--det", f"--det-trace={trace}", *args], cwd=proj, env=env or _env(), capture_output=True,
                       text=True, timeout=900)
    return p, trace


def values(p, key: str) -> list:
    out = []
    for line in p.stdout.splitlines():
        i = line.find(key + " ")
        if i >= 0 and set(line[:i]) <= {"."}:  # pytest's progress dots may precede the printed line
            out.append(line[i + len(key) + 1:])
    return out


def identical(a: Path, b: Path) -> str:
    p = subprocess.run([sys.executable, "-m", "detpy.fenvix", "verify", str(a), str(b)], capture_output=True,
                       text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    return p.stdout


def twice(proj: Path, key: str, *args, env=None) -> list:
    pa, ta = det(proj, "a", *args, env=env)
    pb, tb = det(proj, "b", *args, env=env)
    va, vb = values(pa, key), values(pb, key)
    assert va and va == vb, (pa.stdout[-3000:] + pa.stderr[-2000:], pb.stdout[-3000:])
    identical(ta, tb)
    return va


def project(tmp_path: Path, body: str) -> Path:
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "test_p.py").write_text(body)
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    return tmp_path


# ---------------------------------------------------------------------------------------------------------- clock
def test_asyncio_loop_time_is_virtual(tmp_path):
    """G-1514: loop.time(), call_later deadlines and asyncio.sleep follow the virtual clock, like time.time()."""
    proj = project(tmp_path, '''
import asyncio, time

def test_loop():
    async def main():
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await asyncio.sleep(0.05)
        fut = loop.create_future()
        loop.call_later(0.02, fut.set_result, loop.time())
        scheduled = await fut
        async with asyncio.timeout(10):
            await asyncio.sleep(0.01)
        return t0, scheduled, loop.time(), time.monotonic()
    print("LOOP", asyncio.run(main()))
''')
    v = twice(proj, "LOOP")
    t0, scheduled, end, mono = eval(v[0])
    assert scheduled - t0 >= 0.05 and end - scheduled >= 0.03, v  # the sleeps advanced the loop's clock
    assert t0 < 2000  # the virtual monotonic base (1000 s), not the machine's uptime


def test_cpu_time_clocks_are_virtual(tmp_path):
    """G-1515: process_time, thread_time, os.times and getrusage's CPU times are the same in every run."""
    proj = project(tmp_path, '''
import os, resource, time

def test_cpu():
    sum(range(200000))
    print("CPU", time.process_time(), time.process_time_ns(), time.thread_time(), tuple(os.times()))

def test_rusage():
    r = resource.getrusage(resource.RUSAGE_SELF)
    print("RUSAGE", r.ru_utime, r.ru_stime)
''')
    pa, ta = det(proj, "a")
    pb, tb = det(proj, "b")
    for key in ("CPU", "RUSAGE"):
        assert values(pa, key) and values(pa, key) == values(pb, key), key
    # getrusage's memory and I/O counters stay real: the test that read them is never identical (R-055 V14)
    v = subprocess.run([sys.executable, "-m", "detpy.fenvix", "verify", "--json", str(ta), str(tb)], cwd=proj,
                       capture_output=True, text=True, timeout=300)
    by = {t["nodeid"].split("::")[-1]: t for t in json.loads(v.stdout[v.stdout.index("{"):])["tests"]}
    assert by["test_cpu"]["status"] == "stable", by
    assert by["test_rusage"]["status"] != "stable" and by["test_rusage"]["divergence"]["event_a"]["o"] == "resource.getrusage"


def test_times_of_files_the_test_wrote_are_virtual(tmp_path):
    """G-1516: a file written by the test has the virtual time of the write (no file from the future)."""
    proj = project(tmp_path, '''
import os, time, shutil

def test_mtime(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("x")
    with open(tmp_path / "g.bin", "wb") as f:
        f.write(b"y")
    os.replace(tmp_path / "g.bin", tmp_path / "h.bin")
    st = p.stat()
    print("MTIME", st.st_mtime, st.st_mtime_ns, os.path.getmtime(tmp_path / "h.bin"), st.st_mtime <= time.time())
''')
    v = twice(proj, "MTIME")
    assert v[0].endswith("True"), v


def test_sleep_label_says_real_when_the_time_control_is_off(tmp_path):
    """G-2198."""
    proj = project(tmp_path, "def test_x():\n    pass\n")
    p = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--det", "--det-disable=time"],
                       cwd=proj, env=_env(), capture_output=True, text=True, timeout=600)
    assert "sleep=real (time control off)" in p.stdout, p.stdout


# ---------------------------------------------------------------------------------------------------- randomness
def test_uuid1_is_deterministic(tmp_path):
    """G-1524: uuid1 mixes the clock, the MAC address and a random sequence: all three are controlled."""
    proj = project(tmp_path, '''
import uuid

def test_a():
    print("U1", uuid.uuid1(), uuid.uuid1())

def test_b():
    print("U1", uuid.uuid1())
''')
    twice(proj, "U1")


@pytest.fixture(scope="session")
def libs(tmp_path_factory):
    """numpy and Faker, installed with pip into a directory of their own (on PYTHONPATH for the runs only: the
    suite's own interpreter stays without them)."""
    d = tmp_path_factory.mktemp("libs")
    p = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", "--target",
                        str(d), "numpy", "faker"], capture_output=True, text=True, timeout=900)
    if p.returncode != 0:
        pytest.skip(f"numpy/faker not installable here: {p.stderr[-500:]}")
    return str(d)


def test_numpy_imported_lazily_and_unseeded_generators(tmp_path, libs):
    """G-1525 (numpy imported inside the test), G-1526 (RandomState(), Generator(PCG64()) ...), G-0179 (numpy's own
    entropy read at import is not an event of the first test), isinstance of numpy's own instances kept."""
    proj = project(tmp_path, '''
import os

def test_first_reads_a_file():
    assert os.path.exists(__file__)

def test_lazy():
    import numpy as np
    print("NP", np.random.rand(), np.random.default_rng().random(), np.random.RandomState().rand(),
          np.random.Generator(np.random.PCG64()).random(), np.random.Generator(np.random.MT19937()).random(),
          isinstance(np.random.mtrand._rand, np.random.RandomState))
''')
    v = twice(proj, "NP", env=_env(PYTHONPATH=libs))
    assert v[0].endswith("True")
    # numpy imported before the first test (conftest): no entropy event in the first test (G-0179)
    (proj / "tests" / "conftest.py").write_text("import numpy\n")
    pa, ta = det(proj, "c", env=_env(PYTHONPATH=libs))
    pb, tb = det(proj, "d", env=_env(PYTHONPATH=libs))
    out = identical(ta, tb)
    assert "entropy" not in out, out


def test_repro_of_a_seed_dependent_numpy_failure_is_reproduced(tmp_path, libs):
    """G-0177: in a numpy project, a deterministic seed-dependent failure replays N/N with one fingerprint."""
    proj = project(tmp_path, '''
import numpy as np

def test_other():
    assert True

def test_flaky_random():
    assert np.random.rand() < 0.7
''')
    p = subprocess.run([sys.executable, "-m", "detpy.fenvix", "repro", "tests/test_p.py::test_flaky_random",
                        "--seeds", "12", "--confirm", "3"], cwd=proj, env=_env(PYTHONPATH=libs),
                       capture_output=True, text=True, timeout=1800)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "REPRODUCED: failed 3/3 replays with one fingerprint" in p.stdout, p.stdout


def test_faker_torch_tensorflow_are_seeded(tmp_path, libs):
    """G-1527: Faker's shared generator is seeded from the test (real Faker); torch and TensorFlow get their seed
    calls (stand-in modules recording what detpy called: neither is installable in the gate)."""
    stubs = tmp_path / "stubs"
    (stubs / "torch").mkdir(parents=True)
    (stubs / "torch" / "__init__.py").write_text("SEEDS = []\ndef manual_seed(s):\n    SEEDS.append(s)\n")
    (stubs / "tensorflow" / "random").mkdir(parents=True)
    (stubs / "tensorflow" / "__init__.py").write_text("from . import random\n")
    (stubs / "tensorflow" / "random" / "__init__.py").write_text("SEEDS = []\ndef set_seed(s):\n    SEEDS.append(s)\n")
    proj = project(tmp_path, '''
def test_a():
    from faker import Faker
    import torch, tensorflow
    print("LIBS", Faker().name(), Faker().email(), torch.SEEDS[-1], tensorflow.random.SEEDS[-1])
''')
    twice(proj, "LIBS", env=_env(PYTHONPATH=os.pathsep.join([libs, str(stubs)])))


def test_entropy_divergence_hints_at_det_urandom(tmp_path):
    """G-2210."""
    proj = project(tmp_path, "import uuid\n\ndef test_u():\n    uuid.uuid4()\n")
    _, a = det(proj, "a", "--det-entropy=observe")  # observed (the default controls it)
    _, b = det(proj, "b", "--det-entropy=observe")
    p = subprocess.run([sys.executable, "-m", "detpy.fenvix", "verify", str(a), str(b)], capture_output=True,
                       text=True)
    assert p.returncode == 1 and "hint [entropy]" in p.stdout and "--det-urandom" in p.stdout, p.stdout
    assert "--det-entropy=observe" in p.stdout, p.stdout  # the Python control is named (R-051)


# ------------------------------------------------------------------------------------------------------ first use
@pytest.mark.parametrize("opt", ["--det-seed=3", "--det-isolate", "--det-urandom"])
def test_det_options_without_det_are_errors(tmp_path, opt):
    """G-1532, G-1533."""
    proj = project(tmp_path, "def test_x():\n    pass\n")
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", opt], cwd=proj, env=_env(),
                       capture_output=True, text=True)
    assert p.returncode == 4 and "needs --det" in p.stderr, (p.stdout, p.stderr)


def test_state_directory_ignores_itself_but_the_cassette(tmp_path):
    """G-2207."""
    proj = project(tmp_path, "def test_x():\n    pass\n")
    det(proj, "a")
    gi = (proj / ".detpy" / ".gitignore").read_text()
    assert "*" in gi.splitlines() and "!cassette.json" in gi


def test_first_precompile_says_so_and_old_caches_are_evicted(tmp_path):
    """G-2202 (a line before the silent precompile), G-1531 (bytecode caches of old hash seeds are removed)."""
    proj = project(tmp_path, "def test_x():\n    pass\n")
    cache = tmp_path / "pyc"
    env = _env(DETPY_PYC_CACHE=str(cache), FENVIX_PYC_KEEP="2", FENVIX_HASHSEEDS="1000")
    seen = []
    for seed in (101, 102, 103):
        p, _ = det(proj, f"s{seed}", f"--det-seed={seed}", env=env)
        assert p.returncode == 0, p.stdout + p.stderr
        seen.append("fenvix: compiling the standard library" in p.stderr)
    assert all(seen), seen
    left = sorted(n for n in os.listdir(cache) if "hashseed" in n)
    assert len(left) == 2 and not any(n.endswith("hashseed101") for n in left), left


@pytest.mark.parametrize("runner", ["unittest", "doctest", "nose2", "ward", "zope-testrunner", "django"])
def test_runner_shells_list_the_det_options(runner):
    """G-1535, G-0983, G-2000: `--help` of every runner shell lists the --det options (no traceback, no runner
    error)."""
    p = subprocess.run([sys.executable, "-m", "detpy", runner, "--help"], capture_output=True, text=True)
    assert p.returncode == 0 and "--det-seed" in p.stdout and "--det-tz" in p.stdout, (p.stdout, p.stderr)
    assert "Traceback" not in p.stderr


def test_missing_runner_and_misspelled_option_are_one_line(tmp_path):
    """G-2001..G-2004 (a runner that is not installed), G-2006 (a misspelled --det option)."""
    import importlib.util

    for runner, mod in (("nose2", "nose2"), ("ward", "ward"), ("zope-testrunner", "zope.testrunner"),
                        ("django", "django")):
        try:
            present = importlib.util.find_spec(mod) is not None
        except ModuleNotFoundError:
            present = False
        if present:
            continue
        p = subprocess.run([sys.executable, "-m", "detpy", runner, "--det"], capture_output=True, text=True,
                           cwd=tmp_path)
        assert p.returncode == 4 and "is not installed" in p.stderr and "Traceback" not in p.stderr, p.stderr
    p = subprocess.run([sys.executable, "-m", "detpy", "unittest", "--det", "--det-sed=3"], capture_output=True,
                       text=True, cwd=tmp_path)
    assert p.returncode == 4 and "did you mean --det-seed" in p.stderr, p.stderr


def test_detpy_help_describes_the_runners():
    """G-1994, G-2005."""
    p = subprocess.run([sys.executable, "-m", "detpy", "--help"], capture_output=True, text=True)
    assert "fenvix engine for Python" in p.stdout and "deterministically" in p.stdout, p.stdout


def test_det_turned_on_by_configuration(tmp_path):
    """G-1536: [tool.fenvix] in pyproject.toml (det, seed, tz, ...) or FENVIX_DET=1 turn --det on for a plain
    `pytest` (and the runner shells); the command line wins over the table."""
    proj = project(tmp_path, "import random, time\n\ndef test_x():\n    print('VAL', random.random(), time.time(), time.tzname)\n")
    (proj / "pyproject.toml").write_text('[tool.fenvix]\ndet = true\nseed = 7\ntz = "Asia/Tokyo"\n')
    run = lambda *a, **e: subprocess.run([sys.executable, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider", *a],
                                         cwd=proj, env=_env(**e), capture_output=True, text=True, timeout=600)
    a, b = run(), run()
    va, vb = values(a, "VAL"), values(b, "VAL")
    assert va and va == vb and "Asia/Tokyo" not in va[0] and "JST" in va[0], (a.stdout, a.stderr)
    assert "seed: 7 (shuffled)" in a.stdout
    c = run("--det-seed=8")
    assert "seed: 8 (shuffled)" in c.stdout, c.stdout
    (proj / "pyproject.toml").unlink()
    d, e = run(FENVIX_DET="1"), run(FENVIX_DET="1")
    assert values(d, "VAL") == values(e, "VAL") and "seed: 0" in d.stdout
    plain = run()
    assert "detpy (Level 0)" not in plain.stdout


def test_seeds_share_a_few_hash_seeds(tmp_path):
    """G-1531: --det-seed=N runs under PYTHONHASHSEED = N mod 8 (FENVIX_HASHSEEDS): an exploration over many seeds
    precompiles the libraries 8 times at most; every seed keeps its own order."""
    proj = project(tmp_path, "import os\n\ndef test_x():\n    print('HS', os.environ['PYTHONHASHSEED'])\n")
    a, _ = det(proj, "a", "--det-seed=9")
    b, _ = det(proj, "b", "--det-seed=17")
    assert values(a, "HS") == ["1"] and values(b, "HS") == ["1"], (a.stdout, b.stdout)
    c, _ = det(proj, "c", "--det-seed=9", env=_env(FENVIX_HASHSEEDS="1000"))
    assert values(c, "HS") == ["9"]


# -- G-0168: the first run after a checkout or an edit is laid out like every later run -------------------------------
ADDR = '''
class O:
    pass


def test_addr():
    objs = [O() for _ in range(64)]
    print("ORDER", ",".join(str(objs.index(o)) for o in set(objs)))  # iteration order follows the addresses
'''


def _addr_run(proj: Path, traces: Path, tag: str, *args, env=None):
    # traces outside the project: a new file in the project directory is a real input change (G-1573)
    trace = traces / f"{tag}.jsonl"
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider", "-p", "no:randomly",
                        "--det", f"--det-trace={trace}", *args], cwd=proj, env=env or _env(), capture_output=True,
                       text=True, timeout=900)
    assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-3000:]
    return p, trace


def _bytecode_input(trace: Path) -> str:
    return json.loads(trace.read_text().splitlines()[0])["meta"]["inputs"]["bytecode"]


def test_first_run_after_a_checkout_or_an_edit_is_laid_out_like_later_runs(tmp_path):
    """G-0168: a fresh checkout (no .detpy, a test module never rewritten: its source is unique to this test) and an
    edit of the test module. The process that starts the run writes the rewritten module into the cache before the
    re-exec (nothing imported), so the first run loads it like every later run: the order of a set of plain objects
    is the same, the run inputs say nothing was compiled from source, and verify says IDENTICAL."""
    proj = tmp_path / "p"
    proj.mkdir()
    traces = tmp_path / "traces"
    traces.mkdir()
    src = ADDR + f"# {tmp_path.name}\n"
    project(proj, src)
    runs = [_addr_run(proj, traces, str(i)) for i in range(3)]
    orders = [values(p, "ORDER") for p, _ in runs]
    assert orders[0] and orders[0] == orders[1] == orders[2], orders
    assert "rewritten from source" not in _bytecode_input(runs[0][1]), _bytecode_input(runs[0][1])
    identical(runs[0][1], runs[1][1])
    (proj / "tests" / "test_p.py").write_text(src + "# edited\n")
    edited = [_addr_run(proj, traces, f"e{i}") for i in range(2)]
    # the edit is a real input change (the source differs): the first run after it is laid out like the next one
    assert values(edited[0][0], "ORDER") == values(edited[1][0], "ORDER"), (edited[0][0].stdout, edited[1][0].stdout)
    assert "rewritten from source" not in _bytecode_input(edited[0][1])
    identical(edited[0][1], edited[1][1])


@pytest.mark.parametrize("par", [[], ["-n", "2"]], ids=["serial", "n2"])
def test_a_run_that_compiled_test_modules_is_never_identical_to_a_warm_one(tmp_path, par):
    """G-0168, what the prewarm cannot cover: a run started without the re-exec (DETPY_REEXEC set by the caller: no
    prewarm) compiles its test modules from source, in the process or in the -n workers. That is a run input
    (bytecode), so verify never calls it identical to a later, warm run."""
    if par:
        pytest.importorskip("xdist")
    proj = tmp_path / "p"
    proj.mkdir()
    traces = tmp_path / "traces"
    traces.mkdir()
    project(proj, ADDR + f"# {tmp_path.name} {par}\n")
    env = _env(DETPY_REEXEC="1", PYTHONHASHSEED="0")
    (_, cold), (_, warm) = (_addr_run(proj, traces, t, *par, env=env) for t in ("cold", "warm"))
    inputs = [_bytecode_input(t) for t in (cold, warm)]
    assert "cold rewrite cache" in inputs[0] and "cold" not in inputs[1], inputs
    p = subprocess.run([sys.executable, "-m", "detpy.fenvix", "verify", str(cold), str(warm)], capture_output=True,
                       text=True, timeout=120)
    assert p.returncode == 1 and "bytecode" in p.stdout, p.stdout


def test_waits_that_time_out_and_timeit_follow_the_virtual_clock(tmp_path):
    """Exam F-01.probe.c-wait and probe.timeit: select.select and a socket read that time out last their timeout on
    the virtual clock (as time.sleep); timeit's timed loop costs one tick per iteration, so autorange ends, with the
    same result in every run."""
    proj = project(tmp_path, "import select, socket, time, timeit\n\n"
                             "def test_wait():\n    t = time.monotonic()\n    select.select([], [], [], 0.3)\n"
                             "    a, b = socket.socketpair()\n    a.settimeout(0.3)\n    try:\n        a.recv(1)\n"
                             "    except socket.timeout:\n        pass\n    assert time.monotonic() - t >= 0.55\n\n"
                             "def test_timeit():\n    n, t = timeit.Timer('pass').autorange()\n    print('TIMEIT', n, t)\n")
    outs = []
    for tag in ("a", "b"):
        p, _ = det(proj, tag)
        assert p.returncode == 0, p.stdout + p.stderr
        outs.append([ln for ln in p.stdout.splitlines() if "TIMEIT" in ln])
    assert outs[0] and outs[0] == outs[1], outs
