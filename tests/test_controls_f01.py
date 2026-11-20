"""F-01: every control of a deterministic run works, one test each (run on CPython 3.12, 3.13 and 3.14 by the
release-1 gate): clock, randomness, hash seed, test order, network, file-system order, environment, time zone,
locale.

Each test makes two real ``pytest --det`` runs in which the MACHINE differs in the controlled source (real time
elapsed, OS hash seed, a plugin that reorders, the machine's time zone and locale, ...) and checks that the code
under test saw the same values in both, and that ``fenvix verify`` reports the runs identical. The environment
control is observation (the project's variables are its configuration): its test checks that a read is an event
naming the variable at its site (audit G-0514, G-0515, G-0519, G-1517).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROBE = '''
import datetime, glob, json, locale, os, random, socket, time

OUT = os.path.join(os.path.dirname(__file__), "..", "probe-" + os.environ.get("PROBE_RUN", "x") + ".json")

def _save(key, value):
    data = json.load(open(OUT)) if os.path.exists(OUT) else {}
    data[key] = value
    json.dump(data, open(OUT, "w"))

def test_clock():
    _save("clock", [time.time(), str(datetime.datetime.now()), time.monotonic()])

def test_random():
    _save("random", [random.random(), random.Random().random(), random.randint(0, 10**9)])

def test_hashseed():
    _save("hashseed", [hash("fenvix"), list({"a", "b", "c", "d", "e", "f", "g"})])

def test_network():
    try:
        socket.create_connection(("example.com", 80), timeout=2)
        _save("network", "connected")
    except Exception as e:
        _save("network", type(e).__name__)

def test_fs(tmp_path):
    for name in ("zeta", "alpha", "mid", "beta"):
        (tmp_path / name).write_text("x")
    _save("fs", [os.listdir(tmp_path), [p.name for p in tmp_path.iterdir()], [os.path.basename(p) for p in glob.glob(str(tmp_path / "*"))]])

def test_tz():
    _save("tz", [str(datetime.datetime.now()), time.tzname, time.strftime("%H:%M %Z", time.localtime()), time.timezone])

def test_locale():
    _save("locale", [locale.setlocale(locale.LC_ALL, ""), locale.getlocale(), os.environ.get("LC_ALL"), os.environ.get("LANG")])

def test_env():
    _save("env", os.environ.get("PROBE_VAR"))
'''

# a plugin that reorders like pytest-randomly does, differently in every run
REORDER = '''
import random
def pytest_collection_modifyitems(items):
    random.SystemRandom().shuffle(items)
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_probe.py").write_text(PROBE)
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    return tmp_path


def _env(**extra) -> dict:
    env = dict(os.environ)
    for k in ("PYTEST_ADDOPTS", "PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID",
              "PYTEST_CURRENT_TEST", "PROBE_VAR"):
        env.pop(k, None)
    env.update(extra)
    return env


def run(proj: Path, tag: str, *args, **env) -> tuple[dict, Path, str]:
    trace = proj / f"{tag}.jsonl"
    # PROBE_RUN only names the output file; it is the same in both runs of a comparison (the file is moved)
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly",
                        "--det", f"--det-trace={trace}", *args], cwd=proj, env=_env(PROBE_RUN="x", **env),
                       capture_output=True, text=True, timeout=600)
    out = proj / "probe-x.json"
    data = json.loads(out.read_text()) if out.exists() else {}
    if out.exists():
        out.rename(proj / f"probe-{tag}.json")
    return data, trace, p.stdout + p.stderr


def verify(a: Path, b: Path) -> tuple[int, str]:
    p = subprocess.run([sys.executable, "-m", "detpy.fenvix", "verify", str(a), str(b)], capture_output=True,
                       text=True, timeout=120)
    return p.returncode, p.stdout + p.stderr


def _identical_runs(project, key, a_env=None, b_env=None, a_args=(), b_args=(), sleep=0.0):
    da, ta, oa = run(project, "a", *a_args, **(a_env or {}))
    if sleep:
        time.sleep(sleep)
    db, tb, ob = run(project, "b", *b_args, **(b_env or {}))
    assert key in da and key in db, oa + ob
    assert da[key] == db[key], (key, da[key], db[key])
    rc, text = verify(ta, tb)
    assert rc == 0, text
    return da[key]


def test_clock(project):
    v = _identical_runs(project, "clock", sleep=1.1)  # real time moved on between the runs
    assert abs(v[0] - time.time()) > 3600  # the epoch, not now


def test_randomness(project):
    _identical_runs(project, "random")


def test_hash_seed(project):
    # the machine's hash seed differs (as on two CI runners): under --det the interpreter re-executes with a fixed one
    v = _identical_runs(project, "hashseed", a_env={"PYTHONHASHSEED": "random"}, b_env={"PYTHONHASHSEED": "12345"})
    assert v[1] is not None


def test_test_order(project):
    (project / "conftest.py").write_text(REORDER)
    _, ta, _ = run(project, "a")
    _, tb, _ = run(project, "b")
    order = [json.loads(line)["nodeid"] for line in ta.read_text().splitlines() if '"type":"test"' in line]
    assert order == sorted(order, key=lambda n: PROBE.index("def " + n.split("::")[1] + "("))  # collection order
    rc, text = verify(ta, tb)
    assert rc == 0, text
    assert "order: identical in every run" in text


def test_network(project):
    v = _identical_runs(project, "network")
    assert v in ("NetworkBlockedError", "gaierror"), v


def test_fs_order(project):
    v = _identical_runs(project, "fs")
    assert v[0] == v[1] == v[2] == ["alpha", "beta", "mid", "zeta"]


def test_time_zone(project):
    v = _identical_runs(project, "tz", a_env={"TZ": "Asia/Tokyo"}, b_env={"TZ": "America/New_York"})
    assert v[1] == ["UTC", "UTC"] and v[3] == 0, v


def test_locale(project):
    v = _identical_runs(project, "locale", a_env={"LANG": "de_DE.UTF-8", "LC_ALL": "de_DE.UTF-8"},
                        b_env={"LANG": "C", "LC_ALL": "C", "LANGUAGE": "fr"})
    assert v[2] == v[3] and v[2] in ("C.UTF-8", "C.utf8", "en_US.UTF-8", "C"), v


def test_environment(project):
    # same value: identical; the read is an event naming the variable at its site
    _identical_runs(project, "env", a_env={"PROBE_VAR": "1"}, b_env={"PROBE_VAR": "1"})
    _, ta, _ = run(project, "c", PROBE_VAR="1")
    lines = [json.loads(line) for line in ta.read_text().splitlines()]
    rec = next(r for r in lines if r.get("type") == "test" and r["nodeid"].endswith("::test_env"))
    reads = [e for e in rec["events"] if e["o"] == "env.get" and e["v"].startswith("PROBE_VAR=")]
    assert reads and reads[0]["at"].startswith("tests/test_probe.py:"), rec["events"]
    # a different value: divergent, the variable named
    _, tb, _ = run(project, "d", PROBE_VAR="2")
    rc, text = verify(ta, tb)
    assert rc == 1 and "PROBE_VAR" in text, text
