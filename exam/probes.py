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


@probe("F-01.probe.cassette-redact")
def _(ctx):
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
    d, env = fam.probe_host(ctx)
    lib.pip(ctx, d, env, ["pytest-xdist"])
    return _py_det_same(ctx, "uid", W + "def test_uid(testrun_uid):\n    _w(testrun_uid)\n")


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
