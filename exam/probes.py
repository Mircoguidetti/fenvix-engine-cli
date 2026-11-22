"""Gap probes: one check per probe id of exam/gap_map.json (the specs are there). A probe that is not implemented in
this version of the exam is recorded as a FAIL whose observation says so: the gap it covers cannot be closed until it
runs."""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import fam
import lib
import rows_js
from lib import Ctx, Skip

GM = json.load(open(Path(__file__).resolve().parent / "gap_map.json"))
PROBES = {}


def probe(pid):
    def deco(fn):
        PROBES[pid] = fn
        return fn
    return deco


def run_row_probes(ctx: Ctx, row: str):
    for pid, info in sorted(GM["probes"].items()):
        if info["row"] != row:
            continue
        fn = PROBES.get(pid)
        if fn is None:
            ctx.run_check(pid, info["spec"], lambda: (False, "NOT IMPLEMENTED in this exam version: the gap stays open"),
                          gaps=info["gaps"])
        else:
            ctx.run_check(pid, info["spec"], lambda fn=fn: fn(ctx), gaps=info["gaps"])


# ----------------------------------------------------------------------------------------------------------------- py
def _py_det_same(ctx, name, body, envs=None, args=None, between=None):
    r = fam.py_value_probe(ctx, name, body, envs or [{}, {}], det_args=args)
    v = r["values"]
    return v[0] is not None and v[0] == v[1] and r["verify_ok"], f"values {v}; verify {r['verify']}"


def _py_plain_vs_det(ctx, name, body, args=None, timeout_ok=True):
    d, env = fam.probe_host(ctx)
    rel = fam.write_probe(d, name, body)
    _, _, plain = lib.pytest_plain(ctx, d, env, ["-W", "ignore", rel], f"{name}-plain")
    rc, out, o = lib.pytest_engine(ctx, d, env, ["--det", "-W", "ignore"] + (args or []) + [rel], f"{name}-det")
    (d / rel).unlink(missing_ok=True)
    ok, desc = lib.cmp_outcomes(o, plain)
    return ok, f"det rc={rc}; {desc}"


W = 'import os\n\ndef _w(v):\n    with open(os.environ["EXAM_OUT"], "w") as fh:\n        fh.write(repr(v))\n\n'


@probe("F-01.probe.c-wait")
def _(ctx):
    return _py_plain_vs_det(ctx, "cwait", "import time, select, socket\n\ndef test_wait():\n    t = time.monotonic()\n"
                            "    select.select([], [], [], 0.3)\n    a, b = socket.socketpair()\n    a.settimeout(0.3)\n"
                            "    try:\n        a.recv(1)\n    except socket.timeout:\n        pass\n"
                            "    assert time.monotonic() - t >= 0.25\n")


@probe("F-01.probe.cold-warm")
def _(ctx):
    body = W + "class O:\n    pass\n\ndef test_cw():\n    s = {O() for _ in range(20)}\n    ids = sorted(id(x) for x in s)\n" \
               "    _w([[ids.index(id(x)) for x in s], [b - a for a, b in zip(ids, ids[1:])][:5]])\n"
    d, env = fam.probe_host(ctx)
    shutil.rmtree(d / ".detpy", ignore_errors=True)
    for p in d.rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)
    return _py_det_same(ctx, "coldwarm", body)


@probe("F-01.probe.mtime")
def _(ctx):
    py = _py_plain_vs_det(ctx, "mtime", "import os, time, tempfile\n\ndef test_mtime():\n    p = tempfile.mktemp()\n"
                          "    open(p, 'w').close()\n    assert abs(os.stat(p).st_mtime - time.time()) < 5\n")
    d = rows_js._ufo(ctx)
    body = ("import { test, expect } from 'vitest';\nimport fs from 'node:fs';\nimport os from 'node:os';\n"
            "test('mtime', () => { const p = os.tmpdir() + '/exam-mt-' + process.pid; fs.writeFileSync(p, 'x');\n"
            "  expect(Math.abs(fs.statSync(p).mtimeMs - Date.now())).toBeLessThan(5000); });\n")
    lib.write(d / "test/exam-mtime.test.ts", body)
    _, _, plain = fam.js_run(ctx, d, "vitest", "test/exam-mtime.test.ts", "mt-plain", False)
    _, _, det = fam.js_run(ctx, d, "vitest", "test/exam-mtime.test.ts", "mt-det", True, "--det")
    (d / "test/exam-mtime.test.ts").unlink(missing_ok=True)
    jok, jdesc = fam.js_cmp(det, plain)
    return py[0] and jok, f"python: {py[1]}; node: {jdesc}"


@probe("F-01.probe.timeit")
def _(ctx):
    return _py_plain_vs_det(ctx, "timeit", "import timeit\n\ndef test_timeit():\n    n, t = timeit.Timer('pass').autorange()\n    assert n > 0\n")


@probe("F-01.probe.udp")
def _(ctx):
    body = W + "import socket\n\ndef test_udp():\n    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n    try:\n" \
               "        s.sendto(b'x', ('203.0.113.7', 9))\n        _w('sent')\n    except Exception as e:\n        _w(type(e).__name__)\n"
    r = fam.py_value_probe(ctx, "udp", body, [{}, {}])
    blocked = r["values"][0] not in (None, "'sent'")
    return blocked, f"under --det a UDP datagram to an external address: {r['values'][0]} (expected blocked/recorded)"


JS_REDACT = '''import {{ test, expect }} from 'vitest';

test('exam secret', async () => {{
  const r = await fetch({base!r} + '/secret', {{ headers: {{ Authorization: 'Bearer EXAMSECRET123' }} }});
  expect(r.status).toBe(200);
}});
'''


def _secret_in(paths) -> bool:
    import base64
    for p in paths:
        if p.is_file():
            b = p.read_bytes()
            if b"EXAMSECRET123" in b or base64.b64encode(b"Bearer EXAMSECRET123")[:16] in b or b"RVhBTVNFQ1JFVDEy" in b:
                return True
    return False


def _redact_js(ctx):
    """The Node half of the spec (X-01): Vitest + fetch with the header, recorded from the echo server."""
    ip = _need_ip()
    d = rows_js._ufo(ctx)
    cas, rel = ctx.work / "redact-js.json", "test/exam-redact.test.ts"
    cas.unlink(missing_ok=True)
    srv = netfix.EchoServer(ip)
    try:
        lib.write(d / rel, JS_REDACT.format(base=srv.url))
        rc, out, o = _vitest_tests(ctx, d, rel, "redact-js-record", f"--det --det-record --det-cassette={cas}", env=dict(netfix.NO_PROXY_ENV))
    finally:
        srv.stop()
        (d / rel).unlink(missing_ok=True)
    found = _secret_in([cas] + (list((d / ".detjs").rglob("*")) if (d / ".detjs").exists() else []))
    sent = any(x[1] == "/secret" for x in srv.seen)
    return cas.exists() and sent and not found, f"node: record {o}; request reached the server: {sent}; cassette written: {cas.exists()}; secret present in clear/base64: {found}"


@probe("F-01.probe.cassette-redact")
def _(ctx):
    py = _redact_py(ctx)
    try:
        js = _redact_js(ctx)
    except Skip as s:
        js = (False, f"node: not run: {s}")
    return py[0] and js[0], f"python: {py[1]}; {js[1]}"


def _redact_py(ctx):
    d, env = fam.probe_host(ctx)
    rel = fam.write_probe(d, "redact", "import http.client\n\ndef test_secret():\n    c = http.client.HTTPConnection('example.com', 80, timeout=10)\n"
                          "    c.request('GET', '/', headers={'Authorization': 'Bearer EXAMSECRET123'})\n    c.getresponse().read()\n")
    shutil.rmtree(d / ".detpy", ignore_errors=True)
    rc, out, o = lib.pytest_engine(ctx, d, env, ["--det", "--det-record", "-W", "ignore", rel], "redact-record")
    found = False
    import base64
    for p in (d / ".detpy").rglob("*") if (d / ".detpy").exists() else []:
        if p.is_file():
            b = p.read_bytes()
            if b"EXAMSECRET123" in b or base64.b64encode(b"Bearer EXAMSECRET123")[:16] in b or b"RVhBTVNFQ1JFVDEy" in b:
                found = True
    (d / rel).unlink(missing_ok=True)
    rec = list((d / ".detpy").rglob("cassette*")) if (d / ".detpy").exists() else []
    return bool(rec) and not found, f"record rc={rc}; cassette files {[p.name for p in rec]}; secret present in clear/base64: {found}"


@probe("F-02.probe.numpy-repro")
def _(ctx):
    d, env = fam.probe_host(ctx)
    lib.pip(ctx, d, env, ["numpy"])
    rel = fam.write_probe(d, "np_od", "import numpy\nSTATE = {}\n\ndef test_a():\n    STATE['x'] = 1\n\n\ndef test_b():\n    assert 'x' not in STATE\n")
    rc, out = ctx.sh("np-repro", ["fenvix", "repro", f"{rel}::test_b", "--json"], cwd=d, env=env, timeout=1800)
    (d / rel).unlink(missing_ok=True)
    return rc == 0 and "test_a" in out and "urandom" not in out, f"`fenvix repro` rc={rc}: {out.strip()[-250:]}"


@probe("F-03.probe.numpy")
def _(ctx):
    d, env = fam.probe_host(ctx)
    lib.pip(ctx, d, env, ["numpy"])
    return _py_det_same(ctx, "npverify", W + "import numpy as np\n\ndef test_np():\n    _w(float(np.random.random()))\n")


@probe("F-05.probe.numpy")
def _(ctx):
    d, env = fam.probe_host(ctx)
    lib.pip(ctx, d, env, ["numpy"])
    rel = fam.write_probe(d, "np_cache", "import numpy as np\n\ndef test_np1():\n    assert np.arange(3).sum() == 3\n\ndef test_np2():\n    np.random.random()\n")
    cache = ctx.work / "np-cache"
    shutil.rmtree(cache, ignore_errors=True)
    lib.pytest_engine(ctx, d, env, ["--det", f"--det-cache={cache}", rel], "npc-1")
    rc, out, o = lib.pytest_engine(ctx, d, env, ["--det", f"--det-cache={cache}", rel], "npc-2")
    (d / rel).unlink(missing_ok=True)
    n = lib.reused_count(out)
    return n >= 1, f"reused {n} of 2 numpy tests on an unchanged checkout"


@probe("F-05.probe.early-stat")
def _(ctx):
    f = ctx.work / "early-stat.txt"
    f.write_text("abc")
    body = f"import os\n_st = os.stat\n\ndef test_size(_st=_st):\n    assert _st({str(f)!r}).st_size == 3\n"
    return fam.py_cache_probe(ctx, "early_stat", body, {}, {}, between=lambda d: f.write_text("abcdef"))


@probe("F-05.probe.startup-process")
def _(ctx):
    d, env = fam.probe_host(ctx)
    tagf = ctx.work / "startup-tag"
    tagf.write_text("v1")
    lib.write(d / "tests/conftest.py", (d / "tests/conftest.py").read_text() if (d / "tests/conftest.py").exists() else "")
    conf = d / "tests/conftest.py"
    orig = conf.read_text()
    conf.write_text(orig + f"\nimport os, subprocess\nos.environ['EXAM_TAG'] = subprocess.run(['cat', {str(tagf)!r}], capture_output=True, text=True).stdout\n")
    try:
        return fam.py_cache_probe(ctx, "startup", "import os\n\ndef test_tag():\n    assert os.environ['EXAM_TAG'] == 'v1'\n", {}, {},
                                  between=lambda d: tagf.write_text("v2"))
    finally:
        conf.write_text(orig)


@probe("F-05.probe.import-side-effect")
def _(ctx):
    d, env = fam.probe_host(ctx)
    lib.write(d / "tests/test_exam_ise_b.py", "import json\n\ndef test_dump():\n    assert json.dumps([1, 2]) == '[1, 2]'\n")
    cache = ctx.work / "ise-cache"
    shutil.rmtree(cache, ignore_errors=True)
    args = ["--det", f"--det-cache={cache}", "tests/test_exam_ise_a.py", "tests/test_exam_ise_b.py"]
    lib.write(d / "tests/test_exam_ise_a.py", "def test_nothing():\n    pass\n")
    lib.pytest_engine(ctx, d, env, args, "ise-1")
    lib.write(d / "tests/test_exam_ise_a.py", "import json, functools\njson.dumps = functools.partial(json.dumps, separators=(',', ':'))\n\ndef test_nothing():\n    pass\n")
    rc, out, o = lib.pytest_engine(ctx, d, env, args, "ise-2")
    _, _, plain = lib.pytest_plain(ctx, d, env, ["tests/test_exam_ise_a.py", "tests/test_exam_ise_b.py"], "ise-plain")
    for n in ("a", "b"):
        (d / f"tests/test_exam_ise_{n}.py").unlink(missing_ok=True)
    return lib.cmp_outcomes(o, plain)


@probe("F-05.probe.real-clock")
def _(ctx):
    """Virtual-day rule (DECISIONS 2026-11-19): a result recorded today is not reused on the next UTC day."""
    if not shutil.which("faketime"):
        raise Skip("faketime not installed on this machine (the workflow installs it on Linux)")
    d, env = fam.probe_host(ctx)
    rel = fam.write_probe(d, "vday", "import datetime, os\n\ndef test_day():\n"
                          "    assert datetime.datetime.now(datetime.timezone.utc).day == int(os.environ['EXAM_DAY'])\n")
    import datetime
    day = str(datetime.datetime.now(datetime.timezone.utc).day)
    cache = ctx.work / "pvday"
    shutil.rmtree(cache, ignore_errors=True)
    base = ["fenvix", "python", "-q", "-p", "no:cacheprovider", "--det", f"--det-cache={cache}", "-W", "ignore", rel]
    # both runs under faketime (its LD_PRELOAD is then the same in both): only the date differs
    ctx.sh("pvday-1", ["faketime", "-f", "+0d"] + base, cwd=d, env=dict(env, EXAM_DAY=day))
    rc2, out2 = ctx.sh("pvday-2", ["faketime", "-f", "+1d"] + base, cwd=d, env=dict(env, EXAM_DAY=day))
    (d / rel).unlink(missing_ok=True)
    n = lib.reused_count(out2)
    return n == 0, f"next UTC day (faketime +1d): reused {n} (expected 0); rc={rc2}"


@probe("PY-02.probe.modifyitems")
def _(ctx):
    d, env = fam.probe_host(ctx)
    conf = d / "tests/conftest.py"
    orig = conf.read_text() if conf.exists() else None
    conf.write_text((orig or "") + "\n\ndef pytest_collection_modifyitems(items):\n    items.sort(key=lambda i: 'slow' in i.keywords)\n")
    rel = fam.write_probe(d, "modify", "import pytest\nS = []\n\n@pytest.mark.slow\ndef test_a_slow():\n    assert S == ['b']\n\n\ndef test_b():\n    S.append('b')\n")
    try:
        _, _, plain = lib.pytest_plain(ctx, d, env, ["-W", "ignore", rel], "mod-plain")
        _, _, o = lib.pytest_engine(ctx, d, env, ["--det", "-W", "ignore", rel], "mod-det")
        return lib.cmp_outcomes(o, plain)
    finally:
        (d / rel).unlink(missing_ok=True)
        if orig is None:
            conf.unlink(missing_ok=True)
        else:
            conf.write_text(orig)


@probe("PY-05.probe.isolate")
def _(ctx):
    import rows_py
    d, env = fam.probe_host(ctx)
    rel = fam.write_probe(d, "iso", rows_py.ODPAIR + "\nimport unittest\n\nclass T(unittest.TestCase):\n    def test_u(self):\n        self.assertTrue(True)\n")
    _, _, a = lib.pytest_engine(ctx, d, env, ["--det", rel], "iso-serial")
    _, _, b = lib.pytest_engine(ctx, d, env, ["--det", "--det-isolate", rel], "iso-isolate")
    (d / rel).unlink(missing_ok=True)
    return lib.cmp_outcomes(b, a)


@probe("PY-05.probe.testrun-uid")
def _(ctx):
    """Harness fix (X-01): the two runs used different EXAM_OUT paths, a run difference made by the exam itself that
    an engine records as a differing input (env), whatever it does with testrun_uid. EXAM_OUT stays declared volatile
    (FENVIX_VOLATILE_ENV, lib.Ctx.sh) and both runs now write the same path, copied away after each run: the runs
    differ in nothing the exam controls."""
    d, env = fam.probe_host(ctx)
    lib.pip(ctx, d, env, ["pytest-xdist"])
    rel = fam.write_probe(d, "uid", W + "def test_uid(testrun_uid):\n    _w(testrun_uid)\n")
    out_p = ctx.work / "probe-uid.out"
    vals, traces = [], []
    for i in (0, 1):
        out_p.unlink(missing_ok=True)
        t = ctx.work / f"probe-uid-{i}.jsonl"
        t.unlink(missing_ok=True)
        lib.pytest_engine(ctx, d, env, ["--det", f"--det-trace={t}", "-W", "ignore", rel], f"probe-uid-{i}",
                          {"EXAM_OUT": str(out_p), "FENVIX_VOLATILE_ENV": lib.VOLATILE_ENV})
        vals.append(out_p.read_text() if out_p.exists() else None)
        traces.append(t)
    vok, vdesc, _ = lib.verify(ctx, d, env, traces[0], traces[1], "probe-uid-verify")
    (d / rel).unlink(missing_ok=True)
    return vals[0] is not None and vals[0] == vals[1] and vok, f"values {vals}; verify {vdesc}"


@probe("PY-05.probe.xdist-old")
def _(ctx):
    d, env = fam.py_setup(ctx, "itsdangerous", ["pytest-xdist==3.6.1"], key="itsd-xdist36")
    rc, out, o = lib.pytest_engine(ctx, d, env, ["--det", "-n", "2", "tests"], "xd36")
    internal = "INTERNALERROR" in out
    named = "xdist" in out.lower() and ("3.7" in out or "version" in out.lower())
    return (rc == 0 and bool(o)) or (named and not internal), f"rc={rc}; INTERNALERROR: {internal}; names the xdist version: {named}"


@probe("PY-05.probe.tx-popen")
def _(ctx):
    d, env = fam.py_setup(ctx, "itsdangerous", ["pytest-xdist"], key="itsd-xdist")
    _, _, plain = lib.pytest_plain(ctx, d, env, ["tests"], "tx-plain")
    rc, out, o = lib.pytest_engine(ctx, d, env, ["--det", "-d", "--tx", "2*popen", "tests"], "tx-det")
    ok, desc = lib.cmp_outcomes(o, plain)
    refused = rc != 0 and ("--tx" in out and "det" in out)
    return ok or refused, f"rc={rc}; {desc}; named refusal: {refused}"


@probe("PY-07.probe.lock-type")
def _(ctx):
    return _py_plain_vs_det(ctx, "locktype", "import threading, _thread\n\ndef test_lock():\n"
                            "    assert isinstance(threading.Lock(), type(_thread.allocate_lock()))\n")


@probe("PY-07.probe.leaked-thread")
def _(ctx):
    d, env = fam.probe_host(ctx)
    rel = fam.write_probe(d, "leak", "import threading, time, random\n\ndef test_a():\n"
                          "    threading.Thread(target=lambda: (time.sleep(0.2), random.random(), time.time()), daemon=True).start()\n\n\n"
                          "def test_b():\n    s = 0\n    for i in range(3000000):\n        s += i\n")
    t = [ctx.work / "leak1.jsonl", ctx.work / "leak2.jsonl"]
    for i in (0, 1):
        lib.pytest_engine(ctx, d, env, ["--det", f"--det-trace={t[i]}", rel], f"leak{i}")
    ok, desc, rep = lib.verify(ctx, d, env, t[0], t[1], "leak-verify")
    (d / rel).unlink(missing_ok=True)
    bad = [x["test"] for x in lib.first_divergence(rep) if x["test"] and x["test"].endswith("test_b")]
    return not bad, f"verify {desc}; test_b named diverging: {bool(bad)}"


@probe("PY-07.probe.repro-sched")
def _(ctx):
    import rows_py
    d, env = fam.probe_host(ctx)
    rel = fam.write_probe(d, "sched_repro", rows_py.EXECUTOR_RACE)
    rc, out = ctx.sh("sched-repro", ["fenvix", "repro", f"{rel}::test_executor_race"], cwd=d, env=env, timeout=1800)
    (d / rel).unlink(missing_ok=True)
    return rc == 0 and "replay" in out, f"`fenvix repro` rc={rc}: {out.strip()[-200:]}"


@probe("PY-08.probe.dlopen-lib")
def _(ctx):
    lib_dir = ctx.work / "extlib"
    lib_dir.mkdir(exist_ok=True)
    so = lib_dir / ("libexam.dylib" if os.uname().sysname == "Darwin" else "libexam.so")

    def build(v):
        (lib_dir / "e.c").write_text(f"int exam_value(void){{return {v};}}\n")
        rc, out = ctx.sh("cc-lib", ["cc", "-shared", "-fPIC", "-o", str(so), str(lib_dir / "e.c")])
        if rc != 0:
            raise Skip(f"cc failed: {out[-200:]}")
    build(1)
    body = f"import ctypes\n\ndef test_lib():\n    assert ctypes.CDLL({str(so)!r}).exam_value() == 1\n"
    return fam.py_cache_probe(ctx, "dlopen", body, {}, {}, between=lambda d: build(2))


@probe("PY-08.probe.native-file")
def _(ctx):
    db = ctx.work / "exam.db"

    def mk(v):
        import sqlite3
        db.unlink(missing_ok=True)
        c = sqlite3.connect(db)
        c.execute("create table t(v)")
        c.execute("insert into t values (?)", (v,))
        c.commit()
        c.close()
    mk(1)
    body = f"import sqlite3\n\ndef test_db():\n    assert sqlite3.connect({str(db)!r}).execute('select v from t').fetchone()[0] == 1\n"
    return fam.py_cache_probe(ctx, "sqlitefile", body, {}, {}, between=lambda d: mk(2))


@probe("PY-08.probe.mac-children")
def _(ctx):
    body = "import subprocess, socket\n_keep = []\n\ndef test_child_left():\n    _keep.append(subprocess.Popen(['sleep', '30']))\n" \
           "    s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(); _keep.append(s)\n"
    d, env = fam.probe_host(ctx)
    rel = fam.write_probe(d, "children", body)
    cache = ctx.work / "children-cache"
    shutil.rmtree(cache, ignore_errors=True)
    lib.pytest_engine(ctx, d, env, ["--det", f"--det-cache={cache}", rel], "children-1")
    rc, out, o = lib.pytest_engine(ctx, d, env, ["--det", f"--det-cache={cache}", rel], "children-2")
    (d / rel).unlink(missing_ok=True)
    n = lib.reused_count(out)
    return n == 0, f"reused {n} (expected 0: a test leaving a live child and a listening socket is refused)"


# --------------------------------------------------------------------------------------------------------------- node
NW = "import { test, expect } from 'vitest';\nimport { writeFileSync } from 'node:fs';\nconst _w = (v) => writeFileSync(process.env.EXAM_OUT, JSON.stringify(v));\n"


def _js_det_same(ctx, name, body, envs=None, sleep=False):
    d = rows_js._ufo(ctx)
    if sleep:
        envs = envs or [{}, {}]
    r = fam.js_value_probe(ctx, d, "vitest", f"test/exam-{name}.test.ts", body, envs or [{}, {}])
    v = r["values"]
    return v[0] is not None and v[0] == v[1] and r["verify_ok"], f"values {v}; verify {r['verify']}"


@probe("F-01.probe.fake-timers")
def _(ctx):
    return _js_det_same(ctx, "fakets", NW + "import { vi } from 'vitest';\ntest('ft', () => { vi.useFakeTimers(); const t = Date.now(); vi.useRealTimers(); _w(t); });\n")


@probe("F-01.probe.node-clock-sources")
def _(ctx):
    return _js_det_same(ctx, "clocks", NW + "import { performance as ph } from 'node:perf_hooks';\n"
                        "test('clocks', () => _w([process.uptime(), performance.timeOrigin, performance.mark('m').startTime, ph.now(), process.hrtime.bigint().toString()]));\n")


@probe("F-01.probe.node-vm")
def _(ctx):
    return _js_det_same(ctx, "vm", NW + "import vm from 'node:vm';\ntest('vm', () => _w(vm.runInNewContext('[Math.random(), Date.now()]')));\n")


@probe("F-01.probe.timer-consistency")
def _(ctx):
    d = rows_js._ufo(ctx)
    body = ("import { test, expect } from 'vitest';\n"
            "test('abort vs timeout', async () => { const v = await Promise.race([new Promise((r) => AbortSignal.timeout(300).addEventListener('abort', () => r('abort'))),"
            " new Promise((r) => setTimeout(() => r('timeout'), 1000))]); expect(v).toBe('abort'); });\n")
    lib.write(d / "test/exam-timers.test.ts", body)
    _, _, plain = fam.js_run(ctx, d, "vitest", "test/exam-timers.test.ts", "tc-plain", False)
    _, _, det = fam.js_run(ctx, d, "vitest", "test/exam-timers.test.ts", "tc-det", True, "--det")
    (d / "test/exam-timers.test.ts").unlink(missing_ok=True)
    return fam.js_cmp(det, plain)


@probe("JS-06.probe.global-shape")
def _(ctx):
    d, runner, args = rows_js.proj(ctx, "tabbable")
    body = "test('shape', () => { require('fs').writeFileSync(process.env.EXAM_OUT, JSON.stringify([typeof setImmediate, typeof clearImmediate, typeof crypto.randomUUID])); });\n"
    rel = "test/exam-shape.test.js"
    lib.write(d / rel, body)
    vals = []
    for i, eng in enumerate((False, True)):
        o = ctx.work / f"shape{i}.out"
        o.unlink(missing_ok=True)
        fam.js_run(ctx, d, runner, f"{args} {rel}", f"shape{i}", eng, "--det" if eng else "", env={"EXAM_OUT": str(o)})
        vals.append(o.read_text() if o.exists() else None)
    (d / rel).unlink(missing_ok=True)
    return vals[0] is not None and vals[0] == vals[1], f"plain {vals[0]} / det {vals[1]}"


def _jsdom_vals(ctx, name, expr):
    d = rows_js.setup(ctx, "zustand", [f"vitest@{rows_js.VITEST}", "jsdom@25"], key=f"zustand-vitest@{rows_js.VITEST}-jsdom@25")
    body = "// @vitest-environment jsdom\n" + NW + f"test('{name}', async () => _w(await (async () => {{ {expr} }})()));\n"
    r = fam.js_value_probe(ctx, d, "vitest", f"tests/exam-{name}.test.ts", body, [{}, {}])
    v = r["values"]
    if v[0] is not None and v[0] == v[1]:
        return r["verify_ok"], f"values equal {v}; verify {r['verify']}"
    return not r["verify_ok"], f"values differ {v}; verify must report divergence: {r['verify']}"


@probe("JS-06.probe.jsdom-clock")
def _(ctx):
    return _jsdom_vals(ctx, "jsdomclock", "const f = await new Promise((r) => requestAnimationFrame(r)); return [new Event('x').timeStamp, document.lastModified, new File([], 'f').lastModified, performance.timeOrigin, f];")


@probe("JS-06.probe.iframe-realm")
def _(ctx):
    return _jsdom_vals(ctx, "iframe", "const i = document.createElement('iframe'); document.body.appendChild(i); return [i.contentWindow.Date.now(), i.contentWindow.Math.random()];")


@probe("JS-06.probe.subtle-key")
def _(ctx):
    return _jsdom_vals(ctx, "subtle", "const k = await crypto.subtle.generateKey({name: 'HMAC', hash: 'SHA-256'}, true, ['sign']); return Array.from(new Uint8Array(await crypto.subtle.exportKey('raw', k))).slice(0, 8);")


@probe("JS-06.probe.timer-race")
def _(ctx):
    return _jsdom_vals(ctx, "trace", "const o = []; await new Promise((r) => { setTimeout(() => { o.push('t'); }, 0); const c = new MessageChannel(); c.port1.onmessage = () => o.push('m'); c.port2.postMessage(1); Promise.resolve().then(() => o.push('p')); setTimeout(r, 20); }); return o;")


@probe("F-06.probe.early-fs-ref")
def _(ctx):
    d = rows_js._ufo(ctx)
    f = ctx.work / "early-fs.txt"
    f.write_text("a")
    setup = d / "test/exam-setup.ts"
    setup.write_text("import fs from 'node:fs';\n(globalThis as any).__rf = fs.readFileSync;\n")
    body = ("import './exam-setup';\nimport { test, expect } from 'vitest';\n"
            f"test('early fs', () => {{ expect((globalThis as any).__rf({str(f)!r}, 'utf8')).toBe('a'); }});\n")
    try:
        return fam.js_cache_probe(ctx, d, "vitest", "test/exam-earlyfs.test.ts", body, {}, {}, between=lambda d: f.write_text("b"))
    finally:
        setup.unlink(missing_ok=True)


@probe("F-03.probe.node-sched")
def _(ctx):
    d = rows_js._ufo(ctx)
    body = (NW + "import fs from 'node:fs/promises';\n"
            "test('sched', async () => { const o = []; await Promise.all(Array.from({length: 20}, (_, i) => fs.readFile(process.execPath, {encoding: null}).then(() => o.push(i)))); _w(o); });\n")
    lib.write(d / "test/exam-sched.test.ts", body)
    vals, traces = [], []
    for i in range(10):
        o = ctx.work / f"sched{i}.out"
        t = ctx.work / f"sched{i}.jsonl"
        for p in (o, t):
            p.unlink(missing_ok=True)
        ctx.sh(f"sched{i}", f"fenvix node vitest run --det --det-trace={t} test/exam-sched.test.ts", cwd=d, env={"EXAM_OUT": str(o)})
        vals.append(o.read_text() if o.exists() else None)
        traces.append(str(t))
    (d / "test/exam-sched.test.ts").unlink(missing_ok=True)
    rc, out = ctx.sh("sched-verify", ["fenvix", "verify"] + traces, cwd=d)
    distinct = len(set(vals))
    if distinct == 1:
        return rc == 0, f"one completion order over 10 runs; verify rc={rc}"
    return rc != 0, f"{distinct} completion orders over 10 runs; verify rc={rc} (must not be 0)"


@probe("JS-02.probe.stack-depth")
def _(ctx):
    d = rows_js._ufo(ctx)
    body = ("import { test } from 'vitest';\n"
            "const depth = (n) => { try { return depth(n + 1); } catch { return n; } };\n"
            "test('depth', () => { const lim = depth(0); const rec = (n) => n === 0 ? 0 : 1 + rec(n - 1); rec(Math.floor(lim * 0.9)); });\n")
    lib.write(d / "test/exam-depth.test.ts", body)
    _, _, plain = fam.js_run(ctx, d, "vitest", "test/exam-depth.test.ts", "depth-plain", False)
    _, _, det = fam.js_run(ctx, d, "vitest", "test/exam-depth.test.ts", "depth-det", True, "--det")
    (d / "test/exam-depth.test.ts").unlink(missing_ok=True)
    return fam.js_cmp(det, plain)


# ------------------------------------------------------------------------------------------------- Playwright (JS-04)
def _pw_two(ctx, name, spec, envs=None, extra=""):
    d = rows_js._pw(ctx)
    rel = f"tests/exam-{name}.spec.ts"
    lib.write(d / rel, spec)
    vals = []
    for i, e in enumerate(envs or [{}, {}]):
        o = ctx.work / f"pw-{name}-{i}.out"
        o.unlink(missing_ok=True)
        ctx.sh(f"pw-{name}-{i}", f"fenvix node playwright test --det --project=Chrome {extra} {rel}", cwd=d,
               env=dict(e, EXAM_OUT=str(o)), timeout=1800)
        vals.append(o.read_text() if o.exists() else None)
    (d / rel).unlink(missing_ok=True)
    return vals[0] is not None and vals[0] == vals[1], f"values {vals}"


PW_HEAD = "import { test, expect } from '@playwright/test';\nimport { writeFileSync } from 'node:fs';\n"


@probe("JS-04.probe.browser-tz")
def _(ctx):
    return _pw_two(ctx, "tz", PW_HEAD + "test('tz', async ({ page }) => { writeFileSync(process.env.EXAM_OUT, JSON.stringify(await page.evaluate(() => [new Date(0).toString(), Intl.DateTimeFormat().resolvedOptions()]))); });\n",
                   [{"TZ": "UTC", "LANG": "C.UTF-8"}, {"TZ": "Asia/Tokyo", "LANG": "de_DE.UTF-8"}])


@probe("JS-04.probe.page-apis")
def _(ctx):
    return _pw_two(ctx, "apis", PW_HEAD + "test('apis', async ({ page }) => { await page.setContent('<canvas id=c></canvas>'); writeFileSync(process.env.EXAM_OUT, JSON.stringify(await page.evaluate(async () => { const f = await new Promise((r) => requestAnimationFrame(r)); const c = document.getElementById('c').getContext('2d'); c.fillText('x', 2, 2); return [f, Date.now(), Math.random(), document.getElementById('c').toDataURL().length]; }))); });\n")


@probe("JS-04.probe.cache2")
def _(ctx):
    d = rows_js._pw(ctx)
    cache = ctx.work / "pw-cache"
    rcs = []
    for i in (1, 2):
        rc, out = ctx.sh(f"pw-cache{i}", f"fenvix node playwright test --det --det-cache={cache} --project=Chrome", cwd=d, timeout=1800)
        rcs.append((rc, lib.reused_count(out), "refus" in out.lower()))
    return rcs[1][0] == 0 and (rcs[1][1] > 0 or rcs[1][2]), f"runs (rc, reused, refusal named): {rcs}"


@probe("JS-04.probe.workers")
def _(ctx):
    d = rows_js._pw(ctx)
    t = [ctx.work / "pww1.jsonl", ctx.work / "pww2.jsonl"]
    for i in (0, 1):
        ctx.sh(f"pw-workers{i}", f"fenvix node playwright test --det --det-trace={t[i]} --workers=2 --project=Chrome", cwd=d, timeout=1800)
    ok, desc, _ = lib.verify(ctx, d, {}, t[0], t[1], "pww-verify")
    return ok, desc


@probe("JS-04.probe.browser-version")
def _(ctx):
    d = rows_js._pw(ctx)
    t = ctx.work / "pwv.jsonl"
    ctx.sh("pw-version", f"fenvix node playwright test --det --det-trace={t} --project=Chrome", cwd=d, timeout=1800)
    head = t.read_text().splitlines()[0] if t.exists() else ""
    return "chrom" in head.lower(), f"trace header: {head[:200]!r}"


@probe("JS-04.probe.page-network")
def _(ctx):
    return _pw_two(ctx, "net", PW_HEAD + "test('net', async ({ page }) => { const v = await page.evaluate(async () => { try { const r = await fetch('https://example.com/'); return r.status; } catch (e) { return String(e.name); } }); writeFileSync(process.env.EXAM_OUT, JSON.stringify(v)); });\n",
                   [{}, {"HTTPS_PROXY": "http://127.0.0.1:9"}])


@probe("JS-04.probe.webserver")
def _(ctx):
    return _pw_two(ctx, "server", PW_HEAD + "import http from 'node:http';\ntest('server', async ({ page }) => { const s = http.createServer((q, r) => r.end(String(Date.now()) + ' ' + Math.random())).listen(0); const port = s.address().port; await page.goto('http://127.0.0.1:' + port); writeFileSync(process.env.EXAM_OUT, await page.textContent('body')); s.close(); });\n")


# ------------------------------------------------------------------------------------------------ added in round 2
@probe("F-05.probe.audit-rerun")
def _(ctx):
    ctx.need_install()
    rc, out = ctx.sh("pytest-help-audit", "fenvix python --help")
    have = "--det-cache-audit" in out
    return have, f"--det-cache-audit in `fenvix python --help`: {have}"


@probe("F-06.probe.virtual-day")
def _(ctx):
    if not shutil.which("faketime"):
        raise Skip("faketime not installed on this machine (the workflow installs it on Linux)")
    d = rows_js._ufo(ctx)
    rel = "test/exam-vday.test.ts"
    lib.write(d / rel, "import { test, expect } from 'vitest';\ntest('vday', () => { expect(new Date().getUTCDate()).toBe(Number(process.env.EXAM_DAY)); });\n")
    import datetime
    today = datetime.datetime.now(datetime.timezone.utc).day
    cache = ctx.work / "vday-cache"
    shutil.rmtree(cache, ignore_errors=True)
    shutil.rmtree(d / ".detjs", ignore_errors=True)
    ctx.sh("vday-1", f"faketime -f '+0d' fenvix node vitest run --det --det-cache={cache} {rel}", cwd=d, env={"EXAM_DAY": str(today)})
    shutil.rmtree(d / ".detjs", ignore_errors=True)
    rc2, out2 = ctx.sh("vday-2", f"faketime -f '+1d' fenvix node vitest run --det --det-cache={cache} {rel}", cwd=d,
                       env={"EXAM_DAY": str(today)})
    (d / rel).unlink(missing_ok=True)
    import re
    m = re.findall(r"reused with proof (\d+) tests", out2)
    n = int(m[-1]) if m else 0
    return n == 0, f"next UTC day (faketime +1d): reused {n} (expected 0: the virtual day changed); rc={rc2}"


@probe("JS-02.probe.config-variants")
def _(ctx):
    d = rows_js._ufo(ctx)
    res = {}
    for pool in ("vmThreads", "vmForks"):
        r = fam.js_value_probe(ctx, d, "vitest", f"test/exam-pool-{pool}.test.ts",
                               NW + "test('pool', () => _w([Date.now(), Math.random()]));\n", [{}, {}], args=f"--pool={pool}")
        v = r["values"]
        res[pool] = (v[0] is not None and v[0] == v[1] and r["verify_ok"], v)
    return all(x[0] for x in res.values()), f"per pool (controlled, values): {res}"


@probe("F-01.probe.http-mock")
def _(ctx):
    d = rows_js.setup(ctx, "ufo", [f"vitest@{rows_js.VITEST}", "nock@14"], key="ufo-nock")
    rel = "test/exam-nock.test.ts"
    lib.write(d / rel, "import { test, expect } from 'vitest';\nimport nock from 'nock';\nimport https from 'node:https';\n"
                       "test('nock', async () => { nock('https://api.example.com').get('/user').reply(200, 'mocked');\n"
                       "  const body = await new Promise((r, j) => https.get('https://api.example.com/user', (res) => { let b = ''; res.on('data', (c) => b += c); res.on('end', () => r(b)); }).on('error', j));\n"
                       "  expect(body).toBe('mocked'); });\n")
    _, _, plain = fam.js_run(ctx, d, "vitest", rel, "nock-plain", False)
    _, _, det = fam.js_run(ctx, d, "vitest", rel, "nock-det", True, "--det")
    (d / rel).unlink(missing_ok=True)
    return fam.js_cmp(det, plain)


@probe("JS-03.probe.file-only-failure")
def _(ctx):
    d, runner, args = rows_js.proj(ctx, "elysia")
    rel = "test/exam-after.test.ts"
    lib.write(d / rel, "import { test, expect, afterEach } from 'bun:test';\nafterEach(() => { throw new Error('exam afterEach'); });\n"
                       "test('x', () => { expect(1).toBe(1); });\n")
    t = ctx.work / "bunafter.jsonl"
    t.unlink(missing_ok=True)
    rcp, outp = ctx.sh("bun-after-plain", f"bun test {rel}", cwd=d)
    ctx.sh("bun-after-det", f"fenvix node bun-test --det --det-trace={t} {rel}", cwd=d)
    ok, desc, rep = lib.verify(ctx, d, {}, t, t, "bun-after-verify")
    (d / rel).unlink(missing_ok=True)
    outs = [x.get("outcomes") for x in rep.get("tests", [])]
    failed = any(o and o[0] == "failed" for o in outs)
    return failed and rcp != 0, f"plain bun rc={rcp}; trace outcomes {outs}"


# ------------------------------------------------------------------------------- X-01: the probes NOT IMPLEMENTED before
# Founder decision 2026-11-21: the specs are the frozen definitions of exam/gap_map.json; nothing added or loosened.
import re  # noqa: E402

import netfix  # noqa: E402


def _clear(dd: Path):
    shutil.rmtree(dd, ignore_errors=True)
    dd.mkdir(parents=True)


def _bodies(dd: Path, names) -> dict:
    return {n: ((dd / n).read_text() if (dd / n).exists() else None) for n in names}


def _vitest_tests(ctx, d, rel, tag, det_opts=None, env=None, extra="", config=""):
    """Vitest per-test outcomes {title: outcome} from its JSON reporter; det_opts None = the plain runner."""
    rep = ctx.work / f"vt-{tag}.json"
    rep.unlink(missing_ok=True)
    cfg = f" --config {config}" if config else ""
    base = "npx vitest run" if det_opts is None else f"fenvix node vitest run {det_opts}"
    rc, out = ctx.sh(tag, f"{base}{cfg} {extra} {rel} --reporter=json --outputFile={rep}", cwd=d, env=env, timeout=1800)
    res = {}
    for f in lib.load_json(rep).get("testResults", []):
        for a in f.get("assertionResults", []):
            k = a.get("fullName") or a.get("title")
            n = sum(1 for x in res if x == k or x.startswith(f"{k} #"))
            res[k if not n else f"{k} #{n + 1}"] = lib.norm(a.get("status"))  # the same file in two projects
    return rc, out, res


def _need_ip():
    ip = netfix.lan_ip()
    if not ip:
        raise Skip("this machine has no non-loopback IPv4 address for the echo server")
    return ip


# --- F-01.probe.cassette ---------------------------------------------------------------------------------------------
PY_CASSETTE = '''import requests

S = requests.Session()  # one keep-alive connection serves both tests


def _get(name, path, hdr):
    r = S.get({base!r} + path, headers={{"X-Exam": hdr}}, timeout=10)
    with open({out!r} + "/" + name, "w") as fh:
        fh.write(r.text)
    assert r.status_code == 200


def test_a():
    _get("a", {path_a!r}, {hdr_a!r})


def test_b():
    _get("b", "/b", "h1")
'''

JS_CASSETTE = '''import {{ test, expect }} from 'vitest';
import {{ writeFileSync }} from 'node:fs';

// global fetch (undici): one keep-alive connection serves both tests
async function get(name: string, path: string, hdr: string) {{
  const r = await fetch({base!r} + path, {{ headers: {{ 'X-Exam': hdr }} }});
  writeFileSync({out!r} + '/' + name, await r.text());
  expect(r.status).toBe(200);
}}

test('exam a', async () => {{ await get('a', {path_a!r}, {hdr_a!r}); }});
test('exam b', async () => {{ await get('b', '/b', 'h1'); }});
'''


def _cassette_verdict(lang, steps, own, pa, pb):
    """steps: name -> (outcome of a, outcome of b, bodies). Own recording served = passed with its own echo. A changed
    request (path or header) must not pass with the recorded (stale) response."""
    bad = []
    pl = steps["plain"]
    if not (pl[0] == pl[1] == "passed" and pl[2] == own):
        return False, f"{lang}: INVALID (plain run with the server up did not pass with the echoed bodies: {pl})"
    rec = steps["record"]
    if not (rec[0] == rec[1] == "passed" and rec[2] == own):
        bad.append(f"record: {rec[:2]} bodies {rec[2]}")
    s = steps["single-b"]
    if not (s[1] == "passed" and s[2]["b"] == own["b"]):
        bad.append(f"single test b replayed: outcome {s[1]}, received {s[2]['b']!r} (own recording {own['b']!r})")
    s = steps["seed"]
    if not (s[0] == s[1] == "passed" and s[2] == own):
        bad.append(f"--det-seed replay: outcomes {s[:2]}, received {s[2]}")
    for k, new in (("path", pa), ("header", pb)):
        s = steps[k]
        if s[0] == "passed" and s[2]["a"] != new:
            bad.append(f"changed {k}: test a PASSED with {s[2]['a']!r} (stale; its request now is {new!r})")
    desc = "; ".join(f"{n}: a={v[0]} b={v[1]}" for n, v in steps.items())
    return not bad, f"{lang}: " + ("; ".join(bad) if bad else "every step as expected") + f" [{desc}]"


def _cassette_py(ctx, ip):
    d, env = fam.probe_host(ctx)
    lib.pip(ctx, d, env, ["requests"])
    env = dict(env, **netfix.NO_PROXY_ENV)
    dd, cas, rel = ctx.work / "cas-py-out", ctx.work / "cas-py.json", "tests/test_exam_cassette.py"
    cas.unlink(missing_ok=True)
    srv = netfix.EchoServer(ip)

    def wr(path_a="/a", hdr_a="h1"):
        lib.write(d / rel, PY_CASSETTE.format(base=srv.url, out=str(dd), path_a=path_a, hdr_a=hdr_a))

    nid = {t: f"{rel}::test_{t}" for t in "ab"}
    steps = {}

    def run(name, args, engine=True):
        _clear(dd)
        if engine:
            _, _, o = lib.pytest_engine(ctx, d, env, ["--det", f"--det-cassette={cas}", "-W", "ignore"] + args, f"cas-py-{name}")
        else:
            _, _, o = lib.pytest_plain(ctx, d, env, ["-W", "ignore"] + args, f"cas-py-{name}")
        steps[name] = (lib.norm(o.get(nid["a"])), lib.norm(o.get(nid["b"])), _bodies(dd, "ab"))
    try:
        wr()
        run("plain", [rel], engine=False)
        run("record", ["--det-record", rel])
    finally:
        srv.stop()  # replay without the server: a pass can only come from the recording
    run("single-b", [nid["b"]])
    run("seed", ["--det-seed=1", rel])
    wr(path_a="/a-changed")
    run("path", [rel])
    wr(hdr_a="h2")
    run("header", [rel])
    (d / rel).unlink(missing_ok=True)
    own = {"a": netfix.echo_body("GET", "/a", "h1"), "b": netfix.echo_body("GET", "/b", "h1")}
    return _cassette_verdict("python (requests)", steps, own, netfix.echo_body("GET", "/a-changed", "h1"),
                             netfix.echo_body("GET", "/a", "h2"))


def _cassette_js(ctx, ip):
    d = rows_js._ufo(ctx)
    env = dict(netfix.NO_PROXY_ENV)
    dd, cas, rel = ctx.work / "cas-js-out", ctx.work / "cas-js.json", "test/exam-cassette.test.ts"
    cas.unlink(missing_ok=True)
    srv = netfix.EchoServer(ip)

    def wr(path_a="/a", hdr_a="h1"):
        lib.write(d / rel, JS_CASSETTE.format(base=srv.url, out=str(dd), path_a=path_a, hdr_a=hdr_a))

    steps = {}

    def run(name, det_opts, extra=""):
        _clear(dd)
        _, _, o = _vitest_tests(ctx, d, rel, f"cas-js-{name}", det_opts, env=env, extra=extra)
        steps[name] = (o.get("exam a"), o.get("exam b"), _bodies(dd, "ab"))
    try:
        wr()
        run("plain", None)
        run("record", f"--det --det-record --det-cassette={cas}")
    finally:
        srv.stop()
    run("single-b", f"--det --det-cassette={cas}", "-t 'exam b'")
    run("seed", f"--det --det-seed=1 --det-cassette={cas}")
    wr(path_a="/a-changed")
    run("path", f"--det --det-cassette={cas}")
    wr(hdr_a="h2")
    run("header", f"--det --det-cassette={cas}")
    (d / rel).unlink(missing_ok=True)
    own = {"a": netfix.echo_body("GET", "/a", "h1"), "b": netfix.echo_body("GET", "/b", "h1")}
    return _cassette_verdict("node (Vitest, fetch)", steps, own, netfix.echo_body("GET", "/a-changed", "h1"),
                             netfix.echo_body("GET", "/a", "h2"))


@probe("F-01.probe.cassette")
def _(ctx):
    ip = _need_ip()
    res = []
    for f in (_cassette_py, _cassette_js):
        try:
            res.append(f(ctx, ip))
        except Skip as s:
            res.append((False, f"{f.__name__}: not run: {s}"))
    return all(r[0] for r in res), " || ".join(r[1] for r in res)


# --- F-01.probe.replay-clients ---------------------------------------------------------------------------------------
PY_CLIENTS = '''import asyncio
import socket
import ssl

CA, HTTPS, HOST, PORT, OUT = {ca!r}, {https!r}, {host!r}, {port!r}, {out!r}


def _w(name, v):
    with open(OUT + "/" + name, "w") as fh:
        fh.write(v)


def test_httpx_async():
    import httpx

    async def go():
        async with httpx.AsyncClient(verify=ssl.create_default_context(cafile=CA), trust_env=False) as c:
            return (await c.get(HTTPS + "/httpx", headers={{"X-Exam": "hx"}})).text
    _w("httpx", asyncio.run(go()))


def test_aiohttp():
    import aiohttp

    async def go():
        async with aiohttp.ClientSession() as s:
            async with s.get(HTTPS + "/aiohttp", headers={{"X-Exam": "ah"}}, ssl=ssl.create_default_context(cafile=CA)) as r:
                return await r.text()
    _w("aiohttp", asyncio.run(go()))


def test_sendmsg():
    s = socket.create_connection((HOST, PORT), timeout=10)
    s.sendmsg([b"GET /sendmsg HTTP/1.1\\r\\nHost: exam\\r\\nX-Exam: sm\\r\\nConnection: close\\r\\n\\r\\n"])
    data = b""
    while True:
        chunk = s.recvmsg(65536)[0]
        if not chunk:
            break
        data += chunk
    s.close()
    _w("sendmsg", data.decode(errors="replace").split("\\r\\n\\r\\n", 1)[-1])
'''

JS_H2 = '''import {{ test }} from 'vitest';
import http2 from 'node:http2';
import {{ readFileSync, writeFileSync }} from 'node:fs';

test('exam h2', async () => {{
  const v = await new Promise<string>((res, rej) => {{
    const c = http2.connect({h2!r}, {{ ca: readFileSync({ca!r}) }});
    c.on('error', rej);
    const r = c.request({{ ':path': '/h2', 'x-exam': 'h2' }});
    let b = '';
    r.setEncoding('utf8');
    r.on('data', (x) => (b += x));
    r.on('end', () => {{ c.close(); res(b); }});
    r.on('error', rej);
    r.end();
  }});
  writeFileSync({out!r} + '/h2', v);
}});
'''

BUN_FETCH = '''import {{ test }} from 'bun:test';
import {{ writeFileSync }} from 'node:fs';

test('exam bun fetch', async () => {{
  const r = await fetch({http!r} + '/bun', {{ headers: {{ 'X-Exam': 'bun' }} }});
  writeFileSync({out!r} + '/bun', await r.text());
}});
'''

DENO_FETCH = '''Deno.test('exam deno fetch', async () => {{
  const r = await fetch({http!r} + '/deno', {{ headers: {{ 'X-Exam': 'deno' }} }});
  await Deno.writeTextFile({out!r} + '/deno', await r.text());
}});
'''

REFUSAL = re.compile(r"refus|not supported|unsupported|cannot (?:be )?record|can ?not record", re.I)


def _client_verdict(name, want, plain, rec, rep):
    """plain/rec/rep: (outcome, body, output). OK: the offline replay passes with the recorded response; or the
    record run refuses with a named reason (the test does not pass silently unrecorded)."""
    if not (plain[0] == "passed" and plain[1] == want):
        return False, f"{name}: INVALID (plain with the server up: {plain[0]}, {plain[1]!r})"
    if rec[0] != "passed" and REFUSAL.search(rec[2] or ""):
        return True, f"{name}: --det-record refused ({REFUSAL.search(rec[2]).group(0)!r}): {rec[0]}"
    ok = rec[0] == "passed" and rep[0] == "passed" and rep[1] == want
    return ok, f"{name}: record {rec[0]} {rec[1]!r}; offline replay {rep[0]} {rep[1]!r}"


@probe("F-01.probe.replay-clients")
def _(ctx):
    ip = _need_ip()
    tls = netfix.cert(ctx.work / "certs", ip)
    plain_srv, tls_srv = netfix.EchoServer(ip), netfix.EchoServer(ip, tls=tls)
    h2 = None
    want = {"httpx": netfix.echo_body("GET", "/httpx", "hx"), "aiohttp": netfix.echo_body("GET", "/aiohttp", "ah"),
            "sendmsg": netfix.echo_body("GET", "/sendmsg", "sm"), "h2": netfix.echo_body("GET", "/h2", "h2"),
            "bun": netfix.echo_body("GET", "/bun", "bun"), "deno": netfix.echo_body("GET", "/deno", "deno")}
    res = {k: {} for k in want}  # client -> {"plain"|"rec"|"rep": (outcome, body, output)}
    dd = ctx.work / "rc-out"
    later = []  # replay steps, run after every server is stopped
    notes = []
    try:
        # Python: httpx.AsyncClient and aiohttp over HTTPS, a socket through sendmsg/recvmsg
        try:
            d, env = fam.probe_host(ctx)
            lib.pip(ctx, d, env, ["httpx", "aiohttp"])
            env = dict(env, **netfix.NO_PROXY_ENV)
            rel = "tests/test_exam_clients.py"
            lib.write(d / rel, PY_CLIENTS.format(ca=str(tls[0]), https=tls_srv.url, host=ip, port=plain_srv.port, out=str(dd)))
            cas = ctx.work / "rc-py.json"
            cas.unlink(missing_ok=True)
            nid = {"httpx": "test_httpx_async", "aiohttp": "test_aiohttp", "sendmsg": "test_sendmsg"}

            def py_step(step, d=d, env=env, rel=rel, cas=cas, nid=nid):
                _clear(dd)
                if step == "plain":
                    rc, out, o = lib.pytest_plain(ctx, d, env, ["-W", "ignore", rel], "rc-py-plain")
                else:
                    rc, out, o = lib.pytest_engine(ctx, d, env, ["--det", f"--det-cassette={cas}", "-W", "ignore"]
                                                   + (["--det-record"] if step == "rec" else []) + [rel], f"rc-py-{step}")
                b = _bodies(dd, nid)
                for k, t in nid.items():
                    res[k][step] = (lib.norm(o.get(f"{rel}::{t}")), b[k], out)
            py_step("plain")
            py_step("rec")
            later.append(lambda: (py_step("rep"), (d / rel).unlink(missing_ok=True)))
        except Skip as s:
            notes.append(f"python clients not run: {s}")
        # Node: node:http2 client (Vitest)
        try:
            h2 = netfix.H2Server(ctx.work, ip, tls)
            dj = rows_js._ufo(ctx)
            relj = "test/exam-h2.test.ts"
            lib.write(dj / relj, JS_H2.format(h2=h2.url, ca=str(tls[0]), out=str(dd)))
            casj = ctx.work / "rc-js.json"
            casj.unlink(missing_ok=True)

            def js_step(step, dj=dj, relj=relj, casj=casj):
                _clear(dd)
                opts = None if step == "plain" else f"--det --det-cassette={casj}" + (" --det-record" if step == "rec" else "")
                rc, out, o = _vitest_tests(ctx, dj, relj, f"rc-js-{step}", opts, env=dict(netfix.NO_PROXY_ENV))
                res["h2"][step] = (o.get("exam h2"), _bodies(dd, ["h2"])["h2"], out)
            js_step("plain")
            js_step("rec")
            later.append(lambda: (js_step("rep"), (dj / relj).unlink(missing_ok=True)))
        except (Skip, RuntimeError) as s:
            notes.append(f"node http2 not run: {s}")
        # Bun fetch and Deno fetch (their pinned JS-03 projects)
        for key, client, body, rel2, args in (("elysia", "bun", BUN_FETCH, "test/exam-fetch.test.ts", ""),
                                              ("oak", "deno", DENO_FETCH, "exam_fetch_test.ts", "--allow-all")):
            if not shutil.which(client):
                notes.append(f"{client} not installed on this leg")
                continue
            try:
                db, runner, _ = rows_js.proj(ctx, key)
            except Skip as s:
                notes.append(f"{client} project not set up: {s}")
                continue
            lib.write(db / rel2, body.format(http=plain_srv.url, out=str(dd)))
            casb = ctx.work / f"rc-{client}.json"
            casb.unlink(missing_ok=True)
            plain_cmd, sub, _ = fam.NODE_RUNNERS[runner]

            def b_step(step, db=db, rel2=rel2, casb=casb, client=client, plain_cmd=plain_cmd, sub=sub, args=args):
                _clear(dd)
                if step == "plain":
                    cmd = f"{plain_cmd} {args} {rel2}"
                else:
                    cmd = f"fenvix node {sub} --det --det-cassette={casb}{' --det-record' if step == 'rec' else ''} {args} {rel2}"
                rc, out = ctx.sh(f"rc-{client}-{step}", cmd, cwd=db, env=dict(netfix.NO_PROXY_ENV), timeout=900)
                res[client][step] = ("passed" if rc == 0 else "failed", _bodies(dd, [client])[client], out)
            b_step("plain")
            b_step("rec")
            later.append(lambda b_step=b_step, db=db, rel2=rel2: (b_step("rep"), (db / rel2).unlink(missing_ok=True)))
    finally:
        plain_srv.stop()
        tls_srv.stop()
        if h2:
            h2.stop()
    for f in later:  # offline: every server is down
        f()
    verdicts = {}
    for k in want:
        r = res[k]
        if not {"plain", "rec", "rep"} <= set(r):
            verdicts[k] = (False, f"{k}: not run")
            continue
        verdicts[k] = _client_verdict(k, want[k], r["plain"], r["rec"], r["rep"])
    ok = all(v[0] for v in verdicts.values())
    return ok, "; ".join(v[1] for v in verdicts.values()) + (f" (notes: {'; '.join(notes)})" if notes else "")


# --- F-01.probe.service-host -----------------------------------------------------------------------------------------
PG_NAMES = ("postgres", "exam-pg")  # the job's service name and an /etc/hosts alias of the same container
PY_PG = '''import psycopg
import pytest


@pytest.mark.parametrize("host", {names!r})
def test_pg(host):
    with psycopg.connect(host=host, user="postgres", password="exam", dbname="postgres", connect_timeout=10) as c:
        assert c.execute("select 1").fetchone()[0] == 1
'''
JS_PG = '''import {{ test, expect }} from 'vitest';
import pg from 'pg';

for (const host of {names}) {{
  test('pg ' + host, async () => {{
    const c = new pg.Client({{ host, user: 'postgres', password: 'exam', database: 'postgres', connectionTimeoutMillis: 10000 }});
    await c.connect();
    const r = await c.query('select 1 as v');
    await c.end();
    expect(r.rows[0].v).toBe(1);
  }});
}}
'''


def _pg_container(ctx) -> tuple:
    """The job's `services: postgres` container (exam.yml, F-01 legs); without one (a local run) the exam starts the
    same image itself. Its address goes into /etc/hosts under both names. Returns (ip, how). EXAM_PG_IP (local
    calibration only, never set by exam.yml): a PostgreSQL already listening on that non-loopback address."""
    if os.environ.get("EXAM_PG_IP"):
        ip, how = os.environ["EXAM_PG_IP"], "a PostgreSQL given by EXAM_PG_IP (local run)"
        hosts = Path("/etc/hosts").read_text()
        if not all(re.search(rf"\s{n}(\s|$)", hosts) for n in PG_NAMES):
            ctx.sh("pg-hosts", ["sudo", "sh", "-c", f"echo '{ip} {' '.join(PG_NAMES)}' >> /etc/hosts"])
        return ip, how
    if not shutil.which("docker"):
        raise Skip("docker is not available on this machine")
    rc, out = ctx.sh("pg-ps", ["docker", "ps", "--format", "{{.ID}} {{.Image}}"])
    cid = next((ln.split()[0] for ln in out.splitlines() if len(ln.split()) > 1 and ln.split()[1].startswith("postgres")), None)
    how = "the job's services: postgres container"
    if not cid:
        how = "a postgres:16 container started by the exam (no services: container on this machine)"
        ctx.sh("pg-rm", ["docker", "rm", "-f", "exam-pg"])
        rc, out = ctx.sh("pg-run", ["docker", "run", "-d", "--name", "exam-pg", "-e", "POSTGRES_PASSWORD=exam", "postgres:16"], timeout=900)
        if rc != 0:
            raise Skip(f"docker run postgres failed: {out[-300:]}")
        cid = out.strip().splitlines()[-1]
    for _ in range(60):
        rc, _ = ctx.sh("pg-ready", ["docker", "exec", cid, "pg_isready", "-U", "postgres"])
        if rc == 0:
            break
        time.sleep(2)
    rc, out = ctx.sh("pg-ip", ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", cid])
    ip = next((x for x in out.split() if x.count(".") == 3), None)
    if not ip:
        raise Skip(f"no address for the postgres container: {out[-200:]}")
    hosts = Path("/etc/hosts").read_text()
    if not all(re.search(rf"\s{n}(\s|$)", hosts) for n in PG_NAMES):
        ctx.sh("pg-hosts", ["sudo", "sh", "-c", f"echo '{ip} {' '.join(PG_NAMES)}' >> /etc/hosts"])
    return ip, how


@probe("F-01.probe.service-host")
def _(ctx):
    ip, how = _pg_container(ctx)
    allow = " ".join(f"--det-allow-host={n}" for n in PG_NAMES)
    parts = []
    # Python (psycopg)
    try:
        d, env = fam.probe_host(ctx)
        lib.pip(ctx, d, env, ["psycopg[binary]"])
        rel = fam.write_probe(d, "pg", PY_PG.format(names=list(PG_NAMES)))
        _, _, plain = lib.pytest_plain(ctx, d, env, [rel], "pg-py-plain")
        _, out1, det = lib.pytest_engine(ctx, d, env, ["--det", rel], "pg-py-det")
        ok1, d1 = lib.cmp_outcomes(det, plain)
        ok2, d2 = (ok1, "not needed")
        if not ok1:
            _, _, det2 = lib.pytest_engine(ctx, d, env, ["--det"] + allow.split() + [rel], "pg-py-det-allow")
            ok2, d2 = lib.cmp_outcomes(det2, plain)
        (d / rel).unlink(missing_ok=True)
        pp = bool(plain) and all(lib.norm(v) == "passed" for v in plain.values())
        parts.append((pp and ok2, f"python: plain {sorted(set(plain.values()))}; --det: {d1}; with {allow}: {d2}"))
    except Skip as s:
        parts.append((False, f"python not run: {s}"))
    # Node (pg, Vitest)
    try:
        dj = rows_js.setup(ctx, "ufo", [f"vitest@{rows_js.VITEST}", "pg@8"], key=f"ufo-vitest@{rows_js.VITEST}-pg")
        relj = "test/exam-pg.test.ts"
        lib.write(dj / relj, JS_PG.format(names=json.dumps(list(PG_NAMES))))
        _, _, plain = _vitest_tests(ctx, dj, relj, "pg-js-plain")
        _, _, det = _vitest_tests(ctx, dj, relj, "pg-js-det", "--det")
        _, _, det2 = (None, None, det) if det == plain else _vitest_tests(ctx, dj, relj, "pg-js-det-allow", f"--det {allow}")
        (dj / relj).unlink(missing_ok=True)
        pp = len(plain) == len(PG_NAMES) and all(v == "passed" for v in plain.values())
        parts.append((pp and (det == plain or det2 == plain), f"node: plain {plain}; --det {det}; with {allow}: {det2}"))
    except Skip as s:
        parts.append((False, f"node not run: {s}"))
    return all(p[0] for p in parts), f"service at {ip} ({how}) by names {list(PG_NAMES)}: " + "; ".join(p[1] for p in parts)


# --- F-03.probe.multi-project ----------------------------------------------------------------------------------------
MP_WORKSPACE = '''export default [
  {{ test: {{ name: 'node', environment: 'node', include: [{rel!r}] }} }},
  {{ test: {{ name: 'dom', environment: 'jsdom', include: [{rel!r}] }} }},
];
'''
MP_TEST = '''import {{ test, expect }} from 'vitest';
import {{ readFileSync }} from 'node:fs';

test('exam project value', () => {{
  const project = typeof window === 'undefined' ? 'node' : 'dom';
  // the project-dependent value: each project reads its own file (a file, not a run input), so a change of one
  // project's file changes that project's part of the trace only
  expect(readFileSync({flags!r} + '/' + project, 'utf8')).toBe('a');
}});
'''


@probe("F-03.probe.multi-project")
def _(ctx):
    d = rows_js.setup(ctx, "ufo", [f"vitest@{rows_js.VITEST}", "jsdom@25"], key=f"ufo-vitest@{rows_js.VITEST}-jsdom@25")
    rel, ws, flags = "test/exam-mp.test.ts", "vitest.workspace.ts", ctx.work / "mp-flags"
    flags.mkdir(parents=True, exist_ok=True)
    lib.write(d / rel, MP_TEST.format(flags=str(flags)))
    lib.write(d / ws, MP_WORKSPACE.format(rel=rel))

    def setf(node, dom):
        (flags / "node").write_text(node)
        (flags / "dom").write_text(dom)
    res = {}
    try:
        setf("a", "a")
        _, _, plain = _vitest_tests(ctx, d, "", "mp-plain")
        for case, values in (("same", (("a", "a"), ("a", "a"))), ("node", (("a", "a"), ("b", "a"))),
                             ("dom", (("a", "a"), ("a", "b")))):
            ts = []
            for i, v in enumerate(values):
                setf(*v)
                t = ctx.work / f"mp-{case}-{i}.jsonl"
                t.unlink(missing_ok=True)
                _vitest_tests(ctx, d, "", f"mp-{case}-{i}", f"--det --det-trace={t}")
                ts.append(t)
            res[case] = lib.verify(ctx, d, {}, ts[0], ts[1], f"mp-{case}-verify")
    finally:
        (d / rel).unlink(missing_ok=True)
        (d / ws).unlink(missing_ok=True)
    if len(plain) != 2 or set(plain.values()) != {"passed"}:
        return False, f"INVALID: the workspace's plain run did not run the file in both projects ({plain})"

    def reported(r):
        s = r[2].get("summary", {})
        return not r[0] and s.get("diverged", 0) + s.get("outcome_unstable", 0) >= 1
    n = res["same"][2].get("summary", {}).get("tests", 0)
    ok = res["same"][0] and n == 2 and reported(res["node"]) and reported(res["dom"])
    return ok, (f"plain {plain}; identical runs: verify {res['same'][1]} (tests in the traces {n}, expected 2: both "
                f"parts); a divergence in the node project only: {res['node'][1]}; in the jsdom project only: "
                f"{res['dom'][1]}")


# --- F-03.probe.realm-failure ----------------------------------------------------------------------------------------
FREEZE_DATE = '''// loaded with node --require before anything else (before detjs installs its controls): globalThis.Date is
// made non-configurable (and read-only), so it cannot be replaced
Object.defineProperty(globalThis, 'Date', { value: Date, writable: false, configurable: false, enumerable: false });
'''
REALM_MISSING = re.compile(r"(time|clock|Date)[^\n]{0,120}(not replaceable|missing|not controlled|uncontrolled|"
                           r"failed|cannot|could not)|(not replaceable|realm installation failed)[^\n]{0,120}(Date|time|clock)", re.I)


@probe("F-03.probe.realm-failure")
def _(ctx):
    d = rows_js._ufo(ctx)
    pre = ctx.work / "exam-freeze-date.cjs"
    pre.write_text(FREEZE_DATE)
    rel = "test/exam-realm.test.ts"
    lib.write(d / rel, NW + "test('realm date', () => _w([Date.now(), new Date().toISOString()]));\n")
    po = ctx.work / "realm-plain.out"
    po.unlink(missing_ok=True)
    prc, pout = ctx.sh("realm-plain", f"npx vitest run {rel}", cwd=d, env={"EXAM_OUT": str(po), "NODE_OPTIONS": f"--require={pre}"})
    if prc != 0 or not po.exists():
        (d / rel).unlink(missing_ok=True)
        return False, f"INVALID: plain Vitest with the setup file did not pass (rc={prc}): {pout.strip()[-300:]!r}"
    vals, traces, outs = [], [], []
    o = ctx.work / "realm.out"  # one path for both runs: they differ only in when they ran
    for i in (0, 1):
        t = ctx.work / f"realm-{i}.jsonl"
        for p in (o, t):
            p.unlink(missing_ok=True)
        if i:
            time.sleep(2)
        rc, out = ctx.sh(f"realm-{i}", f"fenvix node vitest run --det --det-trace={t} {rel}", cwd=d,
                         env={"EXAM_OUT": str(o), "NODE_OPTIONS": f"--require={pre}"})
        vals.append(o.read_text() if o.exists() else None)
        traces.append(t)
        outs.append(out)
    vok, vdesc, _ = lib.verify(ctx, d, {}, traces[0], traces[1], "realm-verify")
    (d / rel).unlink(missing_ok=True)
    m = REALM_MISSING.search(outs[0])
    if vals[0] is None:
        return False, f"the test wrote no value (rc/out: {outs[0].strip()[-300:]!r})"
    if vals[0] == vals[1]:
        return vok, f"Date frozen before detjs: values equal (still controlled) {vals}; verify {vdesc}"
    return (bool(m) and not vok, f"Date frozen before detjs: values differ {vals}; console names the missing time "
                                 f"control: {m.group(0)[:160] if m else 'NO'}; verify {vdesc} (must not be identical)")


# --- F-03.probe.zero-tests -------------------------------------------------------------------------------------------
BROWSER_CONFIG = '''import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['test/exam-browser.test.ts'],
    browser: { enabled: true, provider: 'playwright', headless: true, instances: [{ browser: 'chromium' }] },
  },
});
'''
BROWSER_TEST = '''import { test, expect } from 'vitest';

test('exam browser one', () => { expect(document.title.length >= 0).toBe(true); });
test('exam browser two', () => { expect(typeof window.Math.random()).toBe('number'); });
'''


@probe("F-03.probe.zero-tests")
def _(ctx):
    v = rows_js.VITEST
    pw = os.environ.get("EXAM_PLAYWRIGHT", "1")  # local calibration: the version of preinstalled browsers
    d = rows_js.setup(ctx, "ufo", [f"vitest@{v}", f"@vitest/browser@{v}", f"playwright@{pw}"], key=f"ufo-vitest@{v}-browser")
    if not (d / ".exam-chromium").exists() and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        rc, out = ctx.sh("vb-chromium", "npx playwright install --with-deps chromium", cwd=d, timeout=1800)
        if rc != 0:
            raise Skip(f"playwright install failed: {out[-300:]}")
        (d / ".exam-chromium").write_text("1")
    cfg, rel = "vitest.exam-browser.config.ts", "test/exam-browser.test.ts"
    lib.write(d / cfg, BROWSER_CONFIG)
    lib.write(d / rel, BROWSER_TEST)
    try:
        _, pout, plain = _vitest_tests(ctx, d, "", "vb-plain", config=cfg)
        t = [ctx.work / "vb-1.jsonl", ctx.work / "vb-2.jsonl"]
        for i in (0, 1):
            t[i].unlink(missing_ok=True)
            _vitest_tests(ctx, d, "", f"vb-det{i}", f"--det --det-trace={t[i]}", config=cfg)
        if not all(p.exists() for p in t):
            return True, f"plain {plain}; --det wrote no trace ({[p.exists() for p in t]}): no 'identical' verdict possible"
        rc, out = ctx.sh("vb-verify", ["fenvix", "verify", "--json", str(t[0]), str(t[1])], cwd=d)
    finally:
        (d / cfg).unlink(missing_ok=True)
        (d / rel).unlink(missing_ok=True)
    if len(plain) != 2 or set(plain.values()) != {"passed"}:
        return False, f"INVALID: plain browser-mode run did not pass 2 tests ({plain}): {pout.strip()[-200:]!r}"
    rep = {}
    for line in out.splitlines():
        if line.startswith("{"):
            try:
                rep = json.loads(line)
                break
            except ValueError:
                pass
    n = rep.get("summary", {}).get("tests", 0)
    return not (rc == 0 and n < 2), f"plain ran {len(plain)} tests; verify rc={rc}, tests observed in the traces {n} (rc 0 only if both were observed)"


# --- F-05.probe.blockbuster ------------------------------------------------------------------------------------------
BB_CONFTEST = '''import asyncio
import os.path
import posixpath

import pytest


def _guard(f):
    def g(*a, **k):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return f(*a, **k)
        raise RuntimeError(f"exam blockbuster: blocking call os.path.{f.__name__} inside the running event loop")
    g.__name__ = f.__name__
    return g


@pytest.fixture(autouse=True)
def _exam_blockbuster():
    """blockbuster-style: os.path.abspath/realpath raise when called in the thread of a running asyncio loop."""
    saved = os.path.abspath, os.path.realpath
    os.path.abspath = posixpath.abspath = _guard(saved[0])
    os.path.realpath = posixpath.realpath = _guard(saved[1])
    yield
    os.path.abspath = posixpath.abspath = saved[0]
    os.path.realpath = posixpath.realpath = saved[1]
'''
BB_TESTS = '''import asyncio
import importlib.util
import pathlib

import pytest


def _fresh(name):
    """Execute a code file for the first time inside the running loop (as a library's modules are on first use): a
    capture that resolves each new code file with os.path.abspath/realpath meets the hook there."""
    spec = importlib.util.spec_from_file_location(name, pathlib.Path(__file__).with_name(name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.value()


@pytest.mark.asyncio
async def test_bb_sleep():
    await asyncio.sleep(0)
    assert _fresh("exam_bb_h1") == 1


@pytest.mark.asyncio
async def test_bb_read():
    with open(__file__) as fh:
        assert "exam" in fh.read()
    assert _fresh("exam_bb_h2") == 2


@pytest.mark.asyncio
async def test_bb_gather():
    assert await asyncio.gather(asyncio.sleep(0, 1), asyncio.sleep(0, 2)) == [1, 2]
    assert _fresh("exam_bb_h3") == 3
'''


def _receipts(cache: Path) -> tuple:
    """(receipts, reused) from the cache directory's receipts.jsonl."""
    n = r = 0
    p = cache / "receipts.jsonl"
    if p.exists():
        for line in p.read_text(errors="replace").splitlines():
            try:
                x = json.loads(line)
            except ValueError:
                continue
            n += 1
            r += bool(x.get("reused"))
    return n, r


@probe("F-05.probe.blockbuster")
def _(ctx):
    d, env = fam.probe_host(ctx)
    lib.pip(ctx, d, env, ["pytest-asyncio"])
    sub = d / "tests" / "exam_bb"
    lib.write(sub / "conftest.py", BB_CONFTEST)
    lib.write(sub / "test_exam_bb.py", BB_TESTS)
    for i in (1, 2, 3):
        lib.write(sub / f"exam_bb_h{i}.py", f"def value():\n    return {i}\n")
    rel = "tests/exam_bb"
    cache = ctx.work / "bb-cache"
    shutil.rmtree(cache, ignore_errors=True)
    try:
        _, _, plain = lib.pytest_plain(ctx, d, env, ["-W", "ignore", rel], "bb-plain")
        rc1, out1, o1 = lib.pytest_engine(ctx, d, env, ["--det", f"--det-cache={cache}", "-W", "ignore", rel], "bb-cache1")
        rc2, out2, o2 = lib.pytest_engine(ctx, d, env, ["--det", f"--det-cache={cache}", "-W", "ignore", rel], "bb-cache2")
    finally:
        shutil.rmtree(sub, ignore_errors=True)
        # pytest-asyncio is a plugin: left in the shared probe venv it changes every later probe (itsdangerous turns
        # its configure-time deprecation warning into an INTERNALERROR)
        ctx.sh("bb-uninstall", ["python", "-m", "pip", "uninstall", "-q", "-y", "pytest-asyncio"], cwd=d, env=env)
    if len(plain) != 3 or set(lib.norm(v) for v in plain.values()) != {"passed"}:
        return False, f"INVALID: plain pytest-asyncio run under the hook did not pass 3 tests: {plain}"
    ok1, d1 = lib.cmp_outcomes(o1, plain)
    ok2, d2 = lib.cmp_outcomes(o2, plain)
    reused = max(lib.reused_count(out2), _receipts(cache)[1])
    return ok1 and ok2 and reused >= 1, (f"--det-cache run 1 vs plain: {d1}; run 2 vs plain: {d2}; run 2 reused {reused} "
                                         f"(>= 1 test recorded by run 1 needed)")


# --- F-05.probe.custom-reporter --------------------------------------------------------------------------------------
CR_CONFTEST = '''import pytest
from _pytest.terminal import TerminalReporter


class ProjectReporter(TerminalReporter):
    """The project's own terminal reporter: progress and the final counts, nothing from other plugins."""

    def write_line(self, line, **markup):
        pass

    def section(self, title, sep="=", **kw):
        pass


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    std = config.pluginmanager.getplugin("terminalreporter")
    if std is not None and not isinstance(std, ProjectReporter):
        config.pluginmanager.unregister(std)
        config.pluginmanager.register(ProjectReporter(config), "terminalreporter")
'''
CR_TESTS = '''def test_cr_one():
    assert sum([1, 2]) == 3


def test_cr_two():
    assert "ab".upper() == "AB"
'''
CR_SUMMARY = re.compile(r"cache with proof|reused \d+ result|reused with proof", re.I)


@probe("F-05.probe.custom-reporter")
def _(ctx):
    d, env = fam.probe_host(ctx)
    sub = d / "tests" / "exam_cr"
    lib.write(sub / "conftest.py", CR_CONFTEST)
    lib.write(sub / "test_exam_cr.py", CR_TESTS)
    rel = "tests/exam_cr"  # its conftest is an initial conftest: pytest_configure runs before the session
    cache = ctx.work / "cr-cache"
    shutil.rmtree(cache, ignore_errors=True)
    try:
        _, _, plain = lib.pytest_plain(ctx, d, env, [rel], "cr-plain")
        rc1, out1, o1 = lib.pytest_engine(ctx, d, env, ["--det", f"--det-cache={cache}", rel], "cr-cache1")
        rc2, out2, o2 = lib.pytest_engine(ctx, d, env, ["--det", f"--det-cache={cache}", rel], "cr-cache2")
    finally:
        shutil.rmtree(sub, ignore_errors=True)
    if len(plain) != 2 or set(lib.norm(v) for v in plain.values()) != {"passed"}:
        return False, f"INVALID: plain run with the project reporter did not pass 2 tests: {plain}"
    n_rec, reused_rec = _receipts(cache)
    reused = max(reused_rec, lib.reused_count(out2))
    printed = CR_SUMMARY.search(out2)
    files = [str(p.relative_to(cache)) for p in cache.rglob("*") if p.is_file() and "summary" in p.name.lower()] if cache.exists() else []
    files += [str(p.relative_to(d)) for p in (d / ".detpy").rglob("*summary*")] if (d / ".detpy").exists() else []
    ok2, d2 = lib.cmp_outcomes(o2, plain)
    reachable = bool(printed) or bool(files)
    return ok2 and reused >= 1 and reachable, (f"run 2 vs plain: {d2}; entries recorded (run 2 reused) {reused}, receipts "
                                               f"{n_rec}; cache summary reachable: printed "
                                               f"{printed.group(0) if printed else 'NO'}, summary files {files or 'none'}")


# --- F-06.probe.dir-listing ------------------------------------------------------------------------------------------
# Spec (gap_map.json, G-0097): "Vitest project with a Vite plugin that generates a module from fs.readdirSync('routes/');
# a test asserts the route count; add a route file: --det-cache run 2 reruns that test, outcome equals plain".
# The listing is read by the plugin while Vite builds the module, not by the test: nothing the test file itself touches
# changes between the two runs, only the contents of the directory the plugin listed.
DIR_LISTING_CONFIG = """// Exam fixture: a Vite plugin that generates a module from the listing of routes/.
import { readdirSync } from 'node:fs';

const VID = 'virtual:exam-routes';

export default {
  plugins: [{
    name: 'exam-dir-listing',
    enforce: 'pre',
    resolveId(id) { return id === VID ? '\\0' + VID : null; },
    load(id) {
      if (id !== '\\0' + VID) return null;
      const names = readdirSync('routes/').sort();
      return 'export const routes = ' + JSON.stringify(names) + ';\\n';
    },
  }],
  test: { include: ['test/exam-dir-listing.test.ts'] },
};
"""
DIR_LISTING_TEST = """import { test, expect } from 'vitest';
// @ts-expect-error the virtual module the Vite plugin generates from the listing of routes/
import { routes } from 'virtual:exam-routes';

test('route count', () => { expect(routes.length).toBe(2); });
"""


def _total_counts(res: dict) -> dict:
    """Pass/fail/skip totals of a js_run outcome map, over every file it reports."""
    tot = {"passed": 0, "failed": 0, "skipped": 0}
    for counts in ((res or {}).get("files") or {}).values():
        for k in tot:
            tot[k] += counts.get(k, 0)
    return tot


@probe("F-06.probe.dir-listing")
def _(ctx):
    d = rows_js._ufo(ctx)
    cfg, rel, routes = "exam-dir-listing.config.mjs", "test/exam-dir-listing.test.ts", d / "routes"
    args = f"--config {cfg} {rel}"
    shutil.rmtree(routes, ignore_errors=True)
    lib.write(d / cfg, DIR_LISTING_CONFIG)
    lib.write(d / rel, DIR_LISTING_TEST)
    for n in ("a", "b"):
        lib.write(routes / f"{n}.ts", f'export default "{n}";\n')
    cache = ctx.work / "f06-dir-listing"
    shutil.rmtree(cache, ignore_errors=True)
    try:
        # the reference the spec names: the plain runner, before the route is added and after it
        _, _, plain1 = fam.js_run(ctx, d, "vitest", args, "dir-listing-plain1", False)
        shutil.rmtree(d / ".detjs", ignore_errors=True)
        rc1, out1, j1 = fam.js_run(ctx, d, "vitest", args, "dir-listing-1", True, f"--det --det-cache={cache}")
        o1, n1 = fam._receipt_outcomes(d, j1)
        lib.write(routes / "c.ts", 'export default "c";\n')  # the only change between the two cache runs
        shutil.rmtree(d / ".detjs", ignore_errors=True)
        rc2, out2, j2 = fam.js_run(ctx, d, "vitest", args, "dir-listing-2", True, f"--det --det-cache={cache}")
        o2, n2 = fam._receipt_outcomes(d, j2)
        reused_ids = sorted(lib.detjs_receipts(d, reused_only=True)[0])
        _, _, plain2 = fam.js_run(ctx, d, "vitest", args, "dir-listing-plain2", False)
    finally:
        shutil.rmtree(routes, ignore_errors=True)
        (d / cfg).unlink(missing_ok=True)
        (d / rel).unlink(missing_ok=True)
        ctx.reset(d)
    # the fixture must bite: the plain runner passes the test with two routes and fails it with three. Without that
    # the comparison below could not tell a reused result from a fresh one.
    want = ({"passed": 1, "failed": 0, "skipped": 0}, {"passed": 0, "failed": 1, "skipped": 0})
    got = (_total_counts(plain1), _total_counts(plain2))
    if got != want:
        return False, f"INVALID: the plain runner did not pass with 2 routes and fail with 3: {plain1} then {plain2}"
    ok, desc = fam.js_cmp({"files": o2}, plain2)
    return ok and n2 == 0, (f"plain: 2 routes pass, 3 routes fail; run 1 {o1} (reused {n1}); route file added; run 2 "
                            f"reused {n2} {reused_ids[:3]}, outcomes {o2}; vs plain on the 3-route listing: {desc}")
