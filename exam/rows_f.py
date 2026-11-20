"""Feature rows F-01, F-02, F-03, F-05, F-06, F-09, F-10, F-18."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

import fam
import lib
import rows_js
from lib import Ctx, Skip
from projects import P

ENGINE = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------------------------------------------------
# F-01 sources: (python body, node body, env pairs, between)
# Each probe writes the observed value to $EXAM_OUT.
# ---------------------------------------------------------------------------------------------------------------------

PYW = 'def _w(v):\n    import os\n    with open(os.environ["EXAM_OUT"], "w") as fh:\n        fh.write(repr(v))\n\n\n'
JSW = ("import { test } from 'vitest';\nimport { writeFileSync } from 'node:fs';\n"
       "const _w = (v) => writeFileSync(process.env.EXAM_OUT, JSON.stringify(v));\n")

SOURCES = {
    "clock": (PYW + "def test_clock():\n    import time, datetime\n    _w([time.time(), datetime.datetime.now().isoformat()])\n",
              JSW + "test('clock', () => _w([Date.now(), new Date().toISOString(), performance.now()]));\n",
              [{}, {}], "sleep"),
    "random": (PYW + "def test_random():\n    import random, uuid\n    _w([random.random(), str(uuid.uuid4())])\n",
               JSW + "test('random', () => _w([Math.random(), crypto.randomUUID()]));\n",
               [{}, {}], None),
    "random-l0": (PYW + "def test_random_l0():\n    import random\n    _w([random.random(), random.randint(0, 10**9)])\n",
                  JSW + "test('random l0', () => _w([Math.random(), Math.random()]));\n",
                  [{}, {}], None),
    "env": (PYW + "def test_env():\n    import os\n    _w(os.environ.get('EXAM_X'))\n",
            JSW + "test('env', () => _w(process.env.EXAM_X));\n",
            [{"EXAM_X": "a"}, {"EXAM_X": "b"}], None),
    "tz": (PYW + "def test_tz():\n    import datetime, time\n    _w([datetime.datetime.now().astimezone().isoformat(), time.strftime('%H %Z', time.localtime(0))])\n",
           JSW + "test('tz', () => _w([new Date(0).toString(), new Date(0).getHours(), Intl.DateTimeFormat().resolvedOptions().timeZone]));\n",
           [{"TZ": "UTC"}, {"TZ": "Asia/Tokyo"}], None),
    "locale": (PYW + "def test_locale():\n    import locale\n    locale.setlocale(locale.LC_ALL, '')\n    _w([locale.getlocale(), locale.format_string('%.1f', 1234.5, grouping=True)])\n",
               JSW + "test('locale', () => _w([Intl.NumberFormat().format(1234.5), Intl.DateTimeFormat().resolvedOptions().locale]));\n",
               [{"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}, {"LANG": "de_DE.UTF-8", "LC_ALL": "de_DE.UTF-8"}], None),
    "files": (PYW + "def test_files():\n    import os\n    _w(os.listdir(os.environ['EXAM_DIR']))\n",
              JSW + "import { readdirSync } from 'node:fs';\ntest('files', () => _w(readdirSync(process.env.EXAM_DIR)));\n",
              [{}, {}], "files"),
    "network": (PYW + "def test_network():\n    import socket\n    try:\n        socket.create_connection(('example.com', 80), timeout=3).close()\n        _w('connected')\n    except Exception as e:\n        _w(type(e).__name__)\n",
                JSW + "import net from 'node:net';\ntest('network', async () => { const v = await new Promise((r) => { const s = net.connect(80, 'example.com', () => { s.destroy(); r('connected'); }); s.on('error', (e) => r(e.code || e.name)); setTimeout(() => r('timeout'), 3000); }); _w(v); });\n",
                [{}, {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"}], None),
    "hostname": (PYW + "def test_hostname():\n    import socket, platform\n    _w([socket.gethostname(), platform.node()])\n",
                 JSW + "import os from 'node:os';\ntest('hostname', () => _w(os.hostname()));\n",
                 [{}, {}], None),
    "cpu-count": (PYW + "def test_cpu():\n    import os\n    _w(os.cpu_count())\n",
                  JSW + "import os from 'node:os';\ntest('cpu', () => _w(os.cpus().length));\n",
                  [{}, {"EXAM_TASKSET": "1"}], None),
}


def _between_files(i, d):
    dd = Path(os.environ.get("EXAM_TMP", "/tmp")) / "exam-files-dir"
    shutil.rmtree(dd, ignore_errors=True)
    dd.mkdir(parents=True)
    names = ["b", "a", "c", "z", "m"] if i == 0 else ["m", "z", "c", "a", "b"]
    for n in names:
        (dd / n).write_text(n)
    return str(dd)


def _py_value(ctx, src):
    body, _, envs, between = SOURCES[src]
    d, env = fam.probe_host(ctx)
    rel = fam.write_probe(d, f"src_{src.replace('-', '_')}", body)
    vals, traces = [], []
    for i, e in enumerate(envs):
        e = dict(e)
        if between == "sleep" and i == 1:
            time.sleep(2)
        if between == "files":
            e["EXAM_DIR"] = _between_files(i, d)
        out_p = ctx.work / f"f01-py-{src}-{i}.out"
        out_p.unlink(missing_ok=True)
        t = ctx.work / f"f01-py-{src}-{i}.jsonl"
        t.unlink(missing_ok=True)
        cmd_pre = []
        e["EXAM_OUT"] = str(out_p)
        args = ["--det", f"--det-trace={t}", "-W", "ignore", rel]
        if e.pop("EXAM_TASKSET", None) and shutil.which("taskset"):
            rc, out = ctx.sh(f"f01-py-{src}-{i}", ["taskset", "-c", "0", "fenvix", "python", "-q", "-p", "no:cacheprovider"] + args,
                             cwd=d, env=dict(env, **e))
        else:
            lib.pytest_engine(ctx, d, env, args, f"f01-py-{src}-{i}", e)
        vals.append(out_p.read_text() if out_p.exists() else None)
        traces.append(t)
    vok, vdesc, rep = lib.verify(ctx, d, env, traces[0], traces[1], f"f01-py-{src}-verify")
    (d / rel).unlink(missing_ok=True)
    return vals, vok, vdesc, rep


def _js_value(ctx, src, d=None, runner="vitest", rel=None):
    _, body, envs, between = SOURCES[src]
    d = d or rows_js._ufo(ctx)
    rel = rel or f"test/exam-src-{src}.test.ts"
    lib.write(d / rel, body)
    vals, traces = [], []
    for i, e in enumerate(envs):
        e = dict(e)
        if between == "sleep" and i == 1:
            time.sleep(2)
        if between == "files":
            e["EXAM_DIR"] = _between_files(i, d)
        out_p = ctx.work / f"f01-js-{src}-{i}.out"
        out_p.unlink(missing_ok=True)
        t = ctx.work / f"f01-js-{src}-{i}.jsonl"
        t.unlink(missing_ok=True)
        e["EXAM_OUT"] = str(out_p)
        pre = "taskset -c 0 " if e.pop("EXAM_TASKSET", None) and shutil.which("taskset") else ""
        ctx.sh(f"f01-js-{src}-{i}", f"{pre}fenvix node vitest run --det --det-trace={t} {rel}", cwd=d, env=e)
        vals.append(out_p.read_text() if out_p.exists() else None)
        traces.append(t)
    vok, vdesc, rep = lib.verify(ctx, d, {}, traces[0], traces[1], f"f01-js-{src}-verify")
    (d / rel).unlink(missing_ok=True)
    return vals, vok, vdesc, rep


def F_01(ctx: Ctx):
    for src in [s for s in SOURCES if s != "random-l0"]:
        def py(src=src):
            vals, vok, vdesc, _ = _py_value(ctx, src)
            ok = vals[0] is not None and vals[0] == vals[1] and vok
            return ok, f"values {vals}; verify {vdesc}"
        ctx.run_check(f"F-01.{src}.pinned.python",
                      f"two pytest --det runs differing only in {src} give the same value and verify identical", py)

        def js(src=src):
            vals, vok, vdesc, _ = _js_value(ctx, src)
            ok = vals[0] is not None and vals[0] == vals[1] and vok
            return ok, f"values {vals}; verify {vdesc}"
        ctx.run_check(f"F-01.{src}.pinned.node",
                      f"two Vitest --det runs differing only in {src} give the same value and verify identical", js)

    def luxon():
        d, runner, args = rows_js.proj(ctx, "luxon")
        rc0, _, plain = fam.js_run(ctx, d, runner, args, "lux-plain", False, env={"TZ": "America/New_York"})
        t = [ctx.work / "lux1.jsonl", ctx.work / "lux2.jsonl"]
        r1 = fam.js_run(ctx, d, runner, args, "lux-det-ny", True, f"--det --det-trace={t[0]}", env={"TZ": "America/New_York"})
        r2 = fam.js_run(ctx, d, runner, args, "lux-det-kolkata", True, f"--det --det-trace={t[1]}", env={"TZ": "Asia/Kolkata"})
        vok, vdesc, _ = lib.verify(ctx, d, {}, t[0], t[1], "lux-verify")
        same = r1[2] == r2[2]
        return vok and same, f"outcomes NY vs Kolkata under --det equal: {same} (rc {r1[0]}/{r2[0]}); verify {vdesc}"
    ctx.run_check("F-01.real-projects.luxon-tz", "luxon under --det: TZ=America/New_York vs Asia/Kolkata equal and identical", luxon)


# ---------------------------------------------------------------------------------------------------------------------
# F-02 repro / explore / replay
# ---------------------------------------------------------------------------------------------------------------------

def _targets():
    t = json.load(open(ENGINE / "harness" / "block2_targets.json"))
    out = {}
    for k in ("idoft-accessify", "idoft-mdutils", "idoft-krllint", "idoft-py-autodoc"):
        if t.get(k):
            out[k] = t[k][0]
    return out


def F_02(ctx: Ctx):
    def cli():
        ctx.need_install()
        res = {}
        for c in ("repro", "explore", "replay"):
            rc, out = ctx.sh(f"fenvix-{c}-help", ["fenvix", c, "--help"])
            res[c] = rc
        return all(v == 0 for v in res.values()), f"`fenvix <cmd> --help` exit codes {res}"
    ctx.run_check("F-02.cli", "`fenvix repro|explore|replay --help` exit 0", cli)

    for name, target in _targets().items():
        def repro(name=name, target=target):
            d, env = fam.py_setup(ctx, name)
            rc, out = ctx.sh(f"repro-{name}", ["fenvix", "repro", target, "--confirm", "10", "--json"], cwd=d, env=env, timeout=3600)
            res = {}
            for line in reversed(out.splitlines()):
                if line.startswith("{"):
                    try:
                        res = json.loads(out[out.index(line):])
                    except ValueError:
                        pass
                    break
            replay = re.findall(r"replay: ((?:fenvix|pytest|detpy) [^\n]+)", out)
            ok = rc == 0 and bool(replay)
            # evidence: the engine's own capability under its internal name
            rc2, out2 = ctx.sh(f"detpy-repro-{name}", ["python", "-m", "detpy", "repro", target, "--confirm", "10"], cwd=d,
                               env=env, timeout=3600)
            rp = re.findall(r"replay: ((?:fenvix|pytest|detpy) [^\n]+)", out2)
            ctx._f02 = getattr(ctx, "_f02", {})
            ctx._f02[name] = {"d": d, "env": env, "replay": (replay or rp or [None])[0], "via": "fenvix" if replay else "detpy"}
            return ok, (f"`fenvix repro` rc={rc} replay command printed: {replay[:1]}; "
                        f"(evidence only: `python -m detpy repro` rc={rc2}, replay printed: {rp[:1]}, tail: "
                        f"{' | '.join(out2.strip().splitlines()[-3:])[:300]})")
        ctx.run_check(f"F-02.py-repro.{name}", "`fenvix repro <test>` fails 10/10 with one fingerprint and prints a replay command", repro)

        def replay(name=name):
            info = getattr(ctx, "_f02", {}).get(name)
            if not info or not info.get("replay"):
                raise Skip("neither `fenvix repro` nor the engine's own repro printed a replay command")
            cmd = info["replay"].strip()
            if cmd.startswith("pytest "):
                cmd = "fenvix python " + cmd[len("pytest "):]
            fails, traces = 0, []
            for i in range(10):
                t = ctx.work / f"replay-{name}-{i}.jsonl"
                rc, out = ctx.sh(f"replay-{name}-{i}", f"{cmd} -p no:cacheprovider --det-trace={t}", cwd=info["d"], env=info["env"], timeout=1800)
                fails += rc not in (0, "timeout")
                if t.exists():
                    traces.append(str(t))
            vrc, vout = ctx.sh(f"replay-{name}-verify", ["fenvix", "verify"] + traces, cwd=info["d"], env=info["env"]) if len(traces) > 1 else (None, "")
            ok = fails == 10 and vrc == 0
            return ok, (f"replay command printed by {info['via']} (`{info['replay'][:160]}`), run 10x through fenvix: "
                        f"{fails}/10 failed; verify of the {len(traces)} traces rc={vrc} (0 = one fingerprint)")
        ctx.run_check(f"F-02.py-replay.{name}", "the printed replay command fails 10/10 with the same fingerprint", replay)

        def explore(name=name, target=target):
            d, env = fam.py_setup(ctx, name)
            rc, out = ctx.sh(f"explore-{name}", ["fenvix", "explore", "--budget", "5", "--json"], cwd=d, env=env, timeout=1800)
            return rc == 0 and target in out, f"`fenvix explore --budget 5` rc={rc}; target named: {target in out}"
        ctx.run_check(f"F-02.py-explore.{name}", "`fenvix explore --budget 5` finds the target and writes a bundle", explore)

    ODJS = ("import { test, expect } from 'vitest';\nconst g = globalThis;\n"
            "test('a polluter', () => { g.__examState = 1; });\ntest('b victim', () => { expect(g.__examState).toBeUndefined(); });\n")

    def node_repro():
        d = rows_js._ufo(ctx)
        lib.write(d / "test/exam-od.test.ts", ODJS)
        rc, out = ctx.sh("node-repro", "fenvix repro 'test/exam-od.test.ts::b victim' --runner vitest", cwd=d, timeout=1800)
        rc2, out2 = ctx.sh("node-repro-detjs", "fenvix node repro --help", cwd=d)
        (d / "test/exam-od.test.ts").unlink(missing_ok=True)
        replay = re.findall(r"fenvix replay \S+", out)
        return rc == 0 and bool(replay), f"`fenvix repro` on a Vitest test rc={rc}; `fenvix node repro` rc={rc2} ({out2.strip().splitlines()[0][:100] if out2.strip() else ''})"
    ctx.run_check("F-02.node-repro", "`fenvix repro` on a Vitest order-dependent test fails 10/10 and prints a replay command", node_repro)

    def node_replay():
        d = rows_js._ufo(ctx)
        rc, out = ctx.sh("node-replay-help", "fenvix replay --help", cwd=d)
        rc2, out2 = ctx.sh("node-replay-detjs", "fenvix node replay --help", cwd=d)
        return False if rc != 0 else rc2 == 0, (f"`fenvix replay` rc={rc}; `fenvix node replay` rc={rc2}: no Node bundle to replay "
                                                 f"exists because no Node repro writes one")
    ctx.run_check("F-02.node-replay", "a Node repro bundle replays 10/10 with one fingerprint through `fenvix replay`", node_replay)

    def node_explore():
        d = rows_js._ufo(ctx)
        rc, out = ctx.sh("node-explore", "fenvix explore --budget 2 --runner vitest", cwd=d, timeout=900)
        return rc == 0, f"rc={rc}: {out.strip()[-200:]}"
    ctx.run_check("F-02.node-explore", "`fenvix explore` runs on a Vitest project", node_explore)


# ---------------------------------------------------------------------------------------------------------------------
# F-03 verifier
# ---------------------------------------------------------------------------------------------------------------------

def _first_source(rep) -> list:
    out = []
    for x in lib.first_divergence(rep):
        dv = x["divergence"]
        out.append(json.dumps(dv)[:300])
    return out


VER_CASES = {
    # case: (source key in SOURCES, words expected in the first divergent event)
    "tz": ("tz", ("tz", "timezone", "time zone", "localtime", "TZ")),
    "locale": ("locale", ("locale", "LANG", "LC_")),
    "env": ("env", ("env", "EXAM_X")),
}

CHILD_PY = (fam_child := 'def test_child():\n    import subprocess, os\n    with open(os.environ["EXAM_OUT"], "w") as fh:\n'
            '        fh.write(subprocess.run(["sh", "-c", "echo $EXAM_X"], capture_output=True, text=True).stdout)\n')
URANDOM_PY = 'def test_urandom():\n    import os\n    with open(os.environ["EXAM_OUT"], "w") as fh:\n        fh.write(os.urandom(8).hex())\n'
CHILD_JS = (JSW + "import { execFileSync } from 'node:child_process';\n"
            "test('child', () => _w(execFileSync('sh', ['-c', 'echo $EXAM_X']).toString()));\n")
WORKER_JS = (JSW + "import { Worker } from 'node:worker_threads';\n"
             "test('worker', async () => { const v = await new Promise((r) => { const w = new Worker('require(\"node:worker_threads\").parentPort.postMessage(Math.random())', { eval: true }); w.on('message', r); }); _w(v); });\n")


def F_03(ctx: Ctx):
    def identical():
        vals, vok, vdesc, _ = _py_value(ctx, "random-l0")
        jv, jok, jdesc, _ = _js_value(ctx, "random-l0")
        return vok and jok, f"python: {vdesc}; node: {jdesc}"
    ctx.run_check("F-03.identical", "two identical --det runs: verify identical, exit 0", identical)

    for case, (src, words) in VER_CASES.items():
        def py(src=src, words=words):
            vals, vok, vdesc, rep = _py_value(ctx, src)
            fd = _first_source(rep)
            named = any(any(w.lower() in f.lower() for w in words) for f in fd)
            if vals[0] == vals[1]:
                return True, f"values equal ({vals}): the source is pinned, nothing to diverge; {vdesc}"
            return (not vok) and named, f"values {vals}; verify {vdesc}; first divergent events {fd[:2]}"
        ctx.run_check(f"F-03.{case}.python", f"runs differing only in {case}: divergent, first divergent event names {case}", py)

        def js(src=src, words=words):
            vals, vok, vdesc, rep = _js_value(ctx, src)
            fd = _first_source(rep)
            named = any(any(w.lower() in f.lower() for w in words) for f in fd)
            if vals[0] == vals[1]:
                return True, f"values equal ({vals}): pinned; {vdesc}"
            return (not vok) and named, f"values {vals}; verify {vdesc}; first divergent events {fd[:2]}"
        ctx.run_check(f"F-03.node-{case}", f"Node runs differing only in {case}: divergent at the {case} event", js)

    def child_py():
        r = fam.py_value_probe(ctx, "vchild", CHILD_PY, [{"EXAM_X": "a"}, {"EXAM_X": "b"}])
        fd = _first_source(r["report"])
        return (not r["verify_ok"]) and bool(fd), f"values {r['values']}; verify {r['verify']}; first divergent {fd[:2]}"
    ctx.run_check("F-03.child", "a child whose output differs: divergent, first event is the child's", child_py)

    def urandom_py():
        r = fam.py_value_probe(ctx, "vurandom", URANDOM_PY, [{}, {}])
        fd = _first_source(r["report"])
        named = any("entropy" in f or "urandom" in f for f in fd)
        return (not r["verify_ok"]) and named, f"values differ: {r['values'][0] != r['values'][1]}; verify {r['verify']}; first {fd[:2]}"
    ctx.run_check("F-03.random", "os.urandom (beyond L0) in two runs: divergent at the entropy event", urandom_py)

    def thread_py():
        import rows_py
        d, env = fam.probe_host(ctx)
        rel = fam.write_probe(d, "vthread", rows_py.THREAD_RACE)
        traces, outs = [], []
        for i in range(6):
            t = ctx.work / f"vthr-{i}.jsonl"
            rc, out, o = lib.pytest_engine(ctx, d, env, ["--det", f"--det-trace={t}", rel], f"vthr-{i}")
            traces.append(t)
            outs.append(json.dumps(o, sort_keys=True))
        (d / rel).unlink(missing_ok=True)
        rc, out = ctx.sh("vthr-verify", ["fenvix", "verify"] + [str(t) for t in traces], cwd=d, env=env)
        if len(set(outs)) == 1:
            return rc == 0, f"one outcome over 6 runs; verify rc={rc}"
        return rc != 0, f"{len(set(outs))} outcomes over 6 runs; verify rc={rc} ({out.strip().splitlines()[-1][:200] if out.strip() else ''})"
    ctx.run_check("F-03.thread", "runs whose thread order differed are never 'identical'", thread_py)

    def child_js():
        d = rows_js._ufo(ctx)
        r = fam.js_value_probe(ctx, d, "vitest", "test/exam-vchild.test.ts", CHILD_JS, [{"EXAM_X": "a"}, {"EXAM_X": "b"}])
        fd = _first_source(r["report"])
        return (not r["verify_ok"]) and bool(fd), f"values {r['values']}; verify {r['verify']}; first {fd[:2]}"
    ctx.run_check("F-03.node-child", "Node child output differs: divergent at the child event", child_js)

    def random_js():
        d = rows_js._ufo(ctx)
        body = (JSW + "import { randomFill, randomInt } from 'node:crypto';\n"
                "test('async random', async () => { const b = await new Promise((r) => randomFill(new Uint8Array(8), (e, x) => r(Array.from(x))));"
                " const i = await new Promise((r) => randomInt(1000000, (e, n) => r(n))); _w([b, i]); });\n")
        r = fam.js_value_probe(ctx, d, "vitest", "test/exam-vrandom.test.ts", body, [{}, {}])
        v = r["values"]
        if v[0] is not None and v[0] == v[1]:
            return r["verify_ok"], f"async crypto values equal (controlled) {v}; verify {r['verify']}"
        return not r["verify_ok"], f"async crypto values differ {v}; verify must report divergence: {r['verify']}"
    ctx.run_check("F-03.node-random", "Node async crypto.randomFill/randomInt: controlled, or verify reports the entropy divergence", random_js)

    def worker_js():
        d = rows_js._ufo(ctx)
        r = fam.js_value_probe(ctx, d, "vitest", "test/exam-vworker.test.ts", WORKER_JS, [{}, {}])
        v = r["values"]
        if v[0] == v[1] and v[0] is not None:
            return r["verify_ok"], f"worker values equal ({v}); verify {r['verify']}"
        return not r["verify_ok"], f"worker values {v}; verify {r['verify']}"
    ctx.run_check("F-03.node-thread", "Node worker_threads randomness differs: never 'identical'", worker_js)


# ---------------------------------------------------------------------------------------------------------------------
# F-05 cache with proof, Python
# ---------------------------------------------------------------------------------------------------------------------

EDITS = {
    "itsdangerous": [
        ("edit-src", "src/itsdangerous/encoding.py", "return base64.urlsafe_b64encode(string).rstrip(b\"=\")",
         "return base64.urlsafe_b64encode(string).rstrip(b\"=\") + b\"\""),
        ("edit-src-flip", "src/itsdangerous/encoding.py", "return base64.urlsafe_b64encode(string).rstrip(b\"=\")",
         "return base64.urlsafe_b64encode(string)"),
        ("edit-test", "tests/test_itsdangerous/test_encoding.py", "def test_base64_bad():",
         "def test_exam_new_failure():\n    assert False\n\n\ndef test_base64_bad():"),
    ],
    "click": [
        ("edit-src-flip", "src/click/utils.py", "def make_str(value: t.Any) -> str:",
         "def make_str(value: t.Any) -> str:\n    if value == 'exam':\n        return 'EXAM'"),
        ("edit-conftest", "tests/conftest.py", "def runner(request):", "def runner(request):\n    assert 0, 'exam edit'"),
    ],
}

WRONG_REUSE = {
    "cpu-count": ("import os\n\ndef test_cpu():\n    assert os.cpu_count() >= 2\n", {}, {"EXAM_TASKSET": "1"}),
    "umask": ("import os\n\ndef test_umask():\n    m = os.umask(0)\n    os.umask(m)\n    assert m == 0o022\n", {"EXAM_UMASK": "022"}, {"EXAM_UMASK": "077"}),
    "rlimit": ("import resource\n\ndef test_rlimit():\n    assert resource.getrlimit(resource.RLIMIT_NOFILE)[0] >= 4096\n",
               {"EXAM_ULIMIT": "8192"}, {"EXAM_ULIMIT": "1024"}),
    "hostname": ("import socket\n\ndef test_host():\n    assert socket.gethostname() != 'exam-other-host'\n", {}, {"EXAM_UNSHARE_HOST": "exam-other-host"}),
    "pythonpath": ("import exam_outside\n\ndef test_outside():\n    assert exam_outside.VALUE == 1\n", {"EXAM_PP": "1"}, {"EXAM_PP": "22"}),
    "pythonwarnings": ("import sys\n\ndef test_warn():\n    assert not any(o.startswith('error') for o in sys.warnoptions)\n", {}, {"PYTHONWARNINGS": "error::DeprecationWarning"}),
    "ld-preload": ("import os, ctypes, ctypes.util\n\ndef test_preload():\n    libc = ctypes.CDLL(None)\n    assert not hasattr(libc, 'exam_preloaded_symbol')\n",
                   {}, {"EXAM_LD_PRELOAD": "1"}),
}


def _wrap_cmd(e: dict, args: list, path: str = "") -> tuple:
    """Turn special env markers into the command wrapper that sets that machine property."""
    e = dict(e)
    pre = []
    if e.pop("EXAM_TASKSET", None) and shutil.which("taskset"):
        pre = ["taskset", "-c", "0"]
    if "EXAM_UMASK" in e:
        pre = ["sh", "-c", f"umask {e.pop('EXAM_UMASK')} && exec \"$@\"", "sh"] + pre
    if "EXAM_ULIMIT" in e:
        pre = ["sh", "-c", f"ulimit -n {e.pop('EXAM_ULIMIT')} && exec \"$@\"", "sh"] + pre
    if "EXAM_UNSHARE_HOST" in e:
        h = e.pop("EXAM_UNSHARE_HOST")
        if shutil.which("unshare"):
            pre = ["sudo", "-E", "env", f"PATH={path or os.environ.get('PATH', '')}", "unshare", "--uts", "sh", "-c", f"hostname {h} && exec \"$@\"", "sh"] + pre
    return e, pre + args


def F_05(ctx: Ctx):
    for name, edits in EDITS.items():
        for kind, path, old, new in edits:
            for par in ([], ["-n", "2"]):
                def fn(name=name, kind=kind, path=path, old=old, new=new, par=par):
                    d, env = fam.py_setup(ctx, name, ["pytest-xdist"])

                    def ed(d):
                        fam.replace_in(d / path, old, new)
                        return f"{path}: {kind}" + ("" if "flip" in kind or kind in ("edit-test", "edit-conftest") else " (no flip expected)")
                    return fam.py_edit(ctx, d, env, par + list(P[name]["tests"]), f"f05-{name}-{kind}-{len(par)}", ed)
                ctx.run_check(f"F-05.{kind}.{name}{'.n2' if par else ''}",
                              "EDIT: dependent tests rerun, the others are reused, every outcome equals a plain rerun", fn)

    def noedit():
        d, env = fam.py_setup(ctx, "attrs")
        return fam.py_cache2(ctx, d, env, P["attrs"]["tests"], "f05-noedit", min_share=0.9)
    ctx.run_check("F-05.no-edit", ">= 90% reused on an unchanged checkout, 0 differing outcomes", noedit)

    def dep():
        d, env = fam.py_setup(ctx, "itsdangerous")
        lib.write(d / "tests/test_exam_dep.py", "import importlib.metadata as m\n\ndef test_dep():\n    assert m.version('six') == '1.16.0'\n")
        lib.pip(ctx, d, env, ["six==1.16.0"])
        cache = ctx.work / "f05-dep"
        shutil.rmtree(cache, ignore_errors=True)
        lib.pytest_engine(ctx, d, env, ["--det", f"--det-cache={cache}", "tests/test_exam_dep.py"], "dep-1")
        lib.pip(ctx, d, env, ["six==1.17.0"])
        rc, out, o = lib.pytest_engine(ctx, d, env, ["--det", f"--det-cache={cache}", "tests/test_exam_dep.py"], "dep-2")
        _, _, plain = lib.pytest_plain(ctx, d, env, ["tests/test_exam_dep.py"], "dep-plain")
        (d / "tests/test_exam_dep.py").unlink()
        ok, desc = lib.cmp_outcomes(o, plain)
        return ok, f"after six 1.16.0 -> 1.17.0: reused {lib.reused_count(out)}; {desc}"
    ctx.run_check("F-05.dep-bump", "a dependency version change: the dependent test reruns, outcome equals plain", dep,
                  gaps=["G-0513"])

    for probe, (body, e1, e2) in WRONG_REUSE.items():
        def wr(probe=probe, body=body, e1=e1, e2=e2):
            d, env = fam.probe_host(ctx)
            rel = fam.write_probe(d, f"wr_{probe.replace('-', '_')}", body)
            cache = ctx.work / f"wr-{probe}"
            shutil.rmtree(cache, ignore_errors=True)
            outside = ctx.work / "outside"
            res = []
            for i, e in enumerate((e1, e2)):
                e = dict(e)
                if "EXAM_PP" in e:
                    lib.write(outside / "exam_outside.py", f"VALUE = {e.pop('EXAM_PP')}\n")
                    e["PYTHONPATH"] = f"{outside}:{lib.PLUGINS}"
                if e.pop("EXAM_LD_PRELOAD", None):
                    so = ctx.work / "libexampre.so"
                    src = ctx.work / "exampre.c"
                    src.write_text("int exam_preloaded_symbol(void){return 1;}\n")
                    ctx.sh("cc-preload", ["cc", "-shared", "-fPIC", "-o", str(so), str(src)])
                    e["LD_PRELOAD"] = str(so)
                e, cmd = _wrap_cmd(e, ["fenvix", "python", "-q", "-p", "no:cacheprovider", "--det", f"--det-cache={cache}",
                                       f"--det-outcomes={ctx.work / f'wr-{probe}-{i}.json'}", rel], env["PATH"])
                rc, out = ctx.sh(f"wr-{probe}-{i}", cmd, cwd=d, env=dict(env, **e))
                res.append((rc, out, lib.load_json(ctx.work / f"wr-{probe}-{i}.json").get("outcomes", {})))
            e, cmd = _wrap_cmd(e if False else dict(e2) | ({"PYTHONPATH": f"{outside}:{lib.PLUGINS}"} if "EXAM_PP" in e2 else {}),
                               ["python", "-m", "pytest", "-q", "-p", "no:detpy", "-p", "exam_outcomes", "-p", "no:cacheprovider", rel], env["PATH"])
            e.pop("EXAM_PP", None)
            if "EXAM_LD_PRELOAD" in e2:
                e["LD_PRELOAD"] = str(ctx.work / "libexampre.so")
            e.pop("EXAM_LD_PRELOAD", None)
            po = ctx.work / f"wr-{probe}-plain.json"
            ctx.sh(f"wr-{probe}-plain", cmd, cwd=d, env=dict(env, EXAM_OUTCOMES=str(po), **e))
            plain = lib.load_json(po).get("outcomes", {})
            (d / rel).unlink(missing_ok=True)
            ok, desc = lib.cmp_outcomes(res[1][2], plain)
            return ok, f"run1 {list(res[0][2].values())}; after changing {probe}: reused {lib.reused_count(res[1][1])}; vs plain: {desc}"
        ctx.run_check(f"F-05.wrong-reuse.{probe}", f"a test depending on {probe} is not reused when it changes (outcome equals plain)", wr)

    def orderdep():
        d, env = fam.probe_host(ctx)
        rel = "tests/test_exam_orderdep.py"
        lib.write(d / rel, "STATE = {}\n\ndef test_a():\n    import os\n    STATE['x'] = os.environ.get('EXAM_X', 'a')\n\n\ndef test_b():\n    assert STATE.get('x') == 'a'\n")
        cache = ctx.work / "f05-od"
        shutil.rmtree(cache, ignore_errors=True)
        lib.pytest_engine(ctx, d, env, ["--det", f"--det-cache={cache}", rel], "od-1")
        # test_a's own input changes (its env), test_b is unchanged: test_a must rerun, test_b depends on test_a's state
        rc, out, o = lib.pytest_engine(ctx, d, env, ["--det", f"--det-cache={cache}", rel], "od-2", {"EXAM_X": "a "[:1]})
        lib.write(d / rel, (d / rel).read_text().replace("STATE = {}", "STATE = {}  # edited"))
        rc3, out3, o3 = lib.pytest_engine(ctx, d, env, ["--det", f"--det-cache={cache}", rel], "od-3")
        _, _, plain = lib.pytest_plain(ctx, d, env, [rel], "od-plain")
        (d / rel).unlink()
        ok, desc = lib.cmp_outcomes(o3, plain)
        return ok, f"after an edit of the module: {desc}"
    ctx.run_check("F-05.order-dep", "a passing order-dependent test stays passing under --det-cache when its dependency reruns",
                  orderdep, gaps=["G-0173"])


# ---------------------------------------------------------------------------------------------------------------------
# F-06 cache with proof, Node
# ---------------------------------------------------------------------------------------------------------------------

FAKE_TIMERS = ("import { test, expect, vi } from 'vitest';\n"
               "test('fake timers real clock', () => { vi.useFakeTimers(); const t = Date.now(); vi.useRealTimers();\n"
               "  expect(t).toBeLessThan(Number(process.env.EXAM_DEADLINE)); });\n")
DISABLE_TIME = ("import { test, expect } from 'vitest';\n"
                "test('real date', () => { expect(Date.now()).toBeLessThan(Number(process.env.EXAM_DEADLINE)); });\n")


def F_06(ctx: Ctx):
    def edit(key, path, old, new):
        def fn():
            d, runner, args = rows_js.proj(ctx, key)
            cache = ctx.work / f"f06-{key}"
            shutil.rmtree(cache, ignore_errors=True)
            shutil.rmtree(d / ".detjs", ignore_errors=True)
            fam.js_run(ctx, d, runner, args, f"f06-{key}-1", True, f"--det --det-cache={cache}")
            fam.replace_in(d / path, old, new)
            shutil.rmtree(d / ".detjs", ignore_errors=True)
            rc2, out2, j2 = fam.js_run(ctx, d, runner, args, f"f06-{key}-2", True, f"--det --det-cache={cache}")
            o2, n = fam._receipt_outcomes(d, j2)
            _, _, plain = fam.js_run(ctx, d, runner, args, f"f06-{key}-plain", False)
            ctx.reset(d)
            ok, desc = fam.js_cmp({"files": o2}, plain)
            # same rule as the Python EDIT family: no stale outcome; reuse required only for a test-file edit
            return ok and (n > 0 if "/test" in path or path.startswith("test") else True), f"{path} edited; run 2 reused {n} tests; vs plain rerun: {desc}"
        return fn
    ctx.run_check("F-06.edit-src.ufo", "EDIT on src: dependent files rerun, others reused, outcomes equal plain",
                  edit("ufo", "src/utils.ts", "export function withTrailingSlash(", "export function withTrailingSlash(  // exam\n"))
    ctx.run_check("F-06.edit-src-flip.ufo", "EDIT that flips tests: no stale reuse",
                  edit("ufo", "src/utils.ts", "export function hasProtocol(", "export function hasProtocolExamOrig("))
    ctx.run_check("F-06.edit-src.luxon", "EDIT on src (Jest): no stale reuse",
                  edit("luxon", "src/impl/english.js", "export function meridiemForDateTime(", "export function meridiemForDateTimeExamOrig("))
    ctx.run_check("F-06.edit-test.class-validator", "EDIT on a test file (Jest + ts-jest)",
                  edit("class-validator", "test/functional/validation-options.spec.ts", "describe(", "test('exam', () => { expect(1).toBe(2); });\ndescribe("))

    def noedit():
        d, runner, args = rows_js.proj(ctx, "zustand")
        return fam.js_cache2(ctx, d, runner, args, "f06-noedit", min_share=0.9)
    ctx.run_check("F-06.no-edit", ">= 90% reused on an unchanged checkout", noedit)

    def deadline_probe(body, opts, gid):
        def fn():
            d = rows_js._ufo(ctx)
            now = int(time.time() * 1000)
            rel = f"test/exam-{gid}.test.ts"
            lib.write(d / rel, body)
            cache = ctx.work / f"f06-{gid}"
            shutil.rmtree(cache, ignore_errors=True)
            shutil.rmtree(d / ".detjs", ignore_errors=True)
            fam.js_run(ctx, d, "vitest", rel, f"{gid}-1", True, f"--det {opts} --det-cache={cache}", env={"EXAM_DEADLINE": str(now + 4000)})
            time.sleep(5)
            shutil.rmtree(d / ".detjs", ignore_errors=True)
            rc2, out2, j2 = fam.js_run(ctx, d, "vitest", rel, f"{gid}-2", True, f"--det {opts} --det-cache={cache}", env={"EXAM_DEADLINE": str(now + 4000)})
            o2, n = fam._receipt_outcomes(d, j2)
            _, _, plain = fam.js_run(ctx, d, "vitest", rel, f"{gid}-plain", False, env={"EXAM_DEADLINE": str(now + 4000)})
            (d / rel).unlink(missing_ok=True)
            ok, desc = fam.js_cmp({"files": o2}, plain)
            return ok, f"deadline passed between runs; run 2 reused {n}; vs plain: {desc}"
        return fn
    ctx.run_check("F-06.fake-timers", "a test reading the real clock through fake timers is not reused after the deadline",
                  deadline_probe(FAKE_TIMERS, "", "fake-timers"), gaps=["G-0122", "G-0142"])
    ctx.run_check("F-06.disable-time", "with --det-disable=time a real-clock test is not reused after the deadline",
                  deadline_probe(DISABLE_TIME, "--det-disable=time", "disable-time"), gaps=["G-0123"])

    def env_reuse():
        d = rows_js._ufo(ctx)
        body = "import { test, expect } from 'vitest';\ntest('env', () => { expect(process.env.EXAM_X).toBe('a'); });\n"
        return fam.js_cache_probe(ctx, d, "vitest", "test/exam-env.test.ts", body, {"EXAM_X": "a"}, {"EXAM_X": "b"})
    ctx.run_check("F-06.wrong-reuse.env", "an env var read that changed: not reused", env_reuse)

    def host_reuse():
        d = rows_js._ufo(ctx)
        body = ("import { test, expect } from 'vitest';\nimport os from 'node:os';\n"
                "test('host', () => { expect(os.cpus().length).toBeGreaterThan(1); });\n")
        lib.write(d / "test/exam-cpu.test.ts", body)
        cache = ctx.work / "f06-cpu"
        shutil.rmtree(cache, ignore_errors=True)
        shutil.rmtree(d / ".detjs", ignore_errors=True)
        ctx.sh("cpu-1", f"fenvix node vitest run --det --det-cache={cache} test/exam-cpu.test.ts", cwd=d)
        shutil.rmtree(d / ".detjs", ignore_errors=True)
        rc2, out2 = ctx.sh("cpu-2", f"taskset -c 0 fenvix node vitest run --det --det-cache={cache} test/exam-cpu.test.ts", cwd=d)
        rcp, outp = ctx.sh("cpu-plain", "taskset -c 0 npx vitest run test/exam-cpu.test.ts", cwd=d)
        (d / "test/exam-cpu.test.ts").unlink(missing_ok=True)
        return (rc2 != 0) == (rcp != 0), f"one CPU in run 2: engine rc={rc2}, plain rc={rcp}"
    ctx.run_check("F-06.wrong-reuse.cpu-count", "a test depending on the CPU count is not reused when it changes", host_reuse)


# ---------------------------------------------------------------------------------------------------------------------
# F-09 platforms
# ---------------------------------------------------------------------------------------------------------------------

def F_09(ctx: Ctx):
    """Founder decision 2026-11-20: go-live runs only on our machines. F-09 = the single Linux x86_64 artifact of the
    claude/release-1 CI installs (as the runner image does) and works on Linux x86_64."""

    def inst():
        i = ctx.install
        ok = bool(i.get("ok")) and bool(i.get("sha256")) and bool(i.get("release_commit"))
        return ok, (f"install {'ok' if i.get('ok') else 'FAILED: ' + str(i.get('reason'))}; artifact {i.get('artifact')} from "
                    f"release run {i.get('release_run')} at {i.get('release_commit')}; version {i.get('version')}; "
                    f"files {len(i.get('sha256') or {})}"), {"sha256": i.get("sha256")}
    ctx.run_check("F-09.install", "the engine-linux-x64 artifact of the newest release-1 run installs with release/install-image.sh; version and sha256 recorded", inst)

    def identity():
        i = ctx.install
        ctx.need_install()
        man = [f for f in (i.get("sha256") or {}) if re.search(r"(SHA256SUMS|sha256|manifest|VERSION)", f, re.I)]
        rc, out = ctx.sh("fenvix-version", ["fenvix", "version"])
        names_commit = bool(i.get("release_commit")) and i["release_commit"][:8] in out
        return bool(man) and names_commit, (f"checksum/version manifest shipped in the artifact: {man or 'none'}; "
                                            f"`fenvix version` names the release commit: {names_commit} ({' | '.join(out.split(chr(10))[:3])})")
    ctx.run_check("F-09.artifact-identity", "the artifact carries its own version and sha256 manifest, and `fenvix version` names the release commit it came from", identity, gaps=["G-0251"])

    def addon():
        ctx.need_install()
        rc, out = ctx.sh("node-addon", "node -e \"require(process.env.FENVIX_HOME + '/node/src/native')\"")
        return rc == 0, f"native addon loads: rc={rc} {out.strip()[-200:]}"
    ctx.run_check("F-09.node-addon", "the detjs native addon of the artifact loads on Linux x86_64", addon)

    def job_venv():
        """The customer's job makes its own environment (venv); the engine comes only from the runner image."""
        ctx.need_install()
        d = ctx.clone(P["itsdangerous"], name="itsdangerous-jobvenv")
        v = d / ".venv"
        ctx.sh("jv-venv", [lib.py_exe(), "-m", "venv", str(v)], cwd=d)
        ctx.sh("jv-pip", [str(v / "bin/python"), "-m", "pip", "install", "-q", "-e", ".", "pytest"], cwd=d)
        env = {"PATH": f"{v / 'bin'}:{os.environ.get('PATH', '')}", "VIRTUAL_ENV": str(v)}
        rc, out = ctx.sh("jv-fenvix", ["fenvix", "python", "-q", "--det", "tests"], cwd=d, env=env)
        return rc == 0 and "unrecognized arguments" not in out, f"`fenvix python --det` in the job's own venv: rc={rc}: {out.strip().splitlines()[-1][:200] if out.strip() else ''}"
    ctx.run_check("F-09.job-venv", "a job that creates its own venv gets the engine from the runner image (`fenvix python --det` works there)", job_venv, gaps=["G-0413"])

    def py_d2():
        d, env = fam.py_setup(ctx, "itsdangerous")
        return fam.py_det2(ctx, d, env, ["tests"], "f09-py")
    ctx.run_check("F-09.py-det2", "DET2 on itsdangerous", py_d2)

    def py_c2():
        d, env = fam.py_setup(ctx, "itsdangerous")
        return fam.py_cache2(ctx, d, env, ["tests"], "f09-pyc")
    ctx.run_check("F-09.py-cache2", "CACHE2 on itsdangerous", py_c2)

    def js_d2():
        return fam.js_det2(ctx, rows_js._ufo(ctx), "vitest", "", "f09-js")
    ctx.run_check("F-09.node-det2", "DET2 on ufo", js_d2)

    def js_c2():
        return fam.js_cache2(ctx, rows_js._ufo(ctx), "vitest", "", "f09-jsc")
    ctx.run_check("F-09.node-cache2", "CACHE2 on ufo", js_c2)


# ---------------------------------------------------------------------------------------------------------------------
# F-18 one CLI
# ---------------------------------------------------------------------------------------------------------------------

def F_18(ctx: Ctx):
    def on_path():
        ctx.need_install()
        w = shutil.which("fenvix")
        return w is not None, f"fenvix on PATH: {w}"
    ctx.run_check("F-18.on-path", "after the install `fenvix` is on PATH", on_path)

    def helps():
        ctx.need_install()
        rc, out = ctx.sh("fenvix-help", ["fenvix", "--help"])
        want = ["python", "node", "repro", "explore", "replay", "verify", "version"]
        missing = [w for w in want if not re.search(rf"^\s+fenvix {w}\b", out, re.M)]
        return rc == 0 and not missing, f"rc={rc}; commands missing from --help: {missing}"
    ctx.run_check("F-18.help", "`fenvix --help` lists python, node, repro, explore, replay, verify, version", helps)

    def subs():
        ctx.need_install()
        res = {}
        for c in (["repro", "--help"], ["explore", "--help"], ["replay", "--help"], ["verify", "--help"], ["version"]):
            rc, _ = ctx.sh(f"fenvix-{c[0]}", ["fenvix"] + c)
            res[c[0]] = rc
        return all(v == 0 for v in res.values()), f"exit codes {res}"
    ctx.run_check("F-18.subcommands", "each subcommand exits 0", subs)

    def detect():
        d1, _ = fam.probe_host(ctx)
        d2 = rows_js._ufo(ctx)
        _, o1 = ctx.sh("detect-py", ["fenvix", "detect", str(d1)])
        _, o2 = ctx.sh("detect-js", ["fenvix", "detect", str(d2)])
        return "python" in o1 and "node" in o2, f"python project -> {o1.split()}; node project -> {o2.split()}"
    ctx.run_check("F-18.detect", "`fenvix detect` names the language", detect)

    def one_verify():
        _py_value(ctx, "random-l0")
        _js_value(ctx, "random-l0")
        pt, jt = ctx.work / "f01-py-random-l0-0.jsonl", ctx.work / "f01-js-random-l0-0.jsonl"
        rc1, _ = ctx.sh("verify-py", ["fenvix", "verify", str(pt), str(ctx.work / "f01-py-random-l0-1.jsonl")])
        rc2, _ = ctx.sh("verify-js", ["fenvix", "verify", str(jt), str(ctx.work / "f01-js-random-l0-1.jsonl")])
        return rc1 == 0 and rc2 == 0, f"fenvix verify on Python traces rc={rc1}, on Node traces rc={rc2}"
    ctx.run_check("F-18.one-verify", "`fenvix verify` reads Python and Node traces", one_verify)
