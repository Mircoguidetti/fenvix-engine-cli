#!/usr/bin/env python3
"""Gap audit P-036: platform probe. Builds and exercises every engine component on the current OS and records, per
step, the exit code and the last output lines. It never fails the job: the result is the table (GitHub step summary
and probe-<name>.json). Audit only: nothing here changes the engine.

    python .github/gap-audit/probe.py --name macos-14 [--only python,node,go,jvm,rust]
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import textwrap
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORK = os.path.join(ROOT, ".gap-audit-work")
RESULTS = []
BASH = shutil.which("bash") or "bash"


def step(name, cmd, timeout=900, cwd=None):
    t = time.time()
    try:
        p = subprocess.run([BASH, "-c", cmd], cwd=cwd or ROOT, text=True, errors="replace",
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        rc, out = p.returncode, p.stdout
    except subprocess.TimeoutExpired as x:
        o = x.stdout
        rc, out = "timeout", (o.decode(errors="replace") if isinstance(o, bytes) else (o or ""))
    except Exception as x:  # noqa: BLE001
        rc, out = "error", repr(x)
    tail = "\n".join(out.strip().splitlines()[-25:])
    RESULTS.append({"step": name, "rc": rc, "seconds": round(time.time() - t, 1), "tail": tail, "cmd": cmd})
    print(f"\n===== {name}: rc={rc} ({time.time() - t:.1f}s)\n$ {cmd}\n{tail}", flush=True)
    return rc


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="\n") as fh:
        fh.write(textwrap.dedent(text))


def py_project():
    d = os.path.join(WORK, "pyproj")
    write(os.path.join(d, "data.txt"), "41\n")
    write(os.path.join(d, "test_a.py"), """\
        import os, random, time, datetime, uuid, socket, pathlib
        STATE = {}
        def test_time(): assert time.time() > 0 and datetime.datetime.now().year >= 2025
        def test_random(): assert 0 <= random.random() < 1
        def test_listdir(): assert isinstance(os.listdir('.'), list)
        def test_set_order(): assert len(list({'a', 'b', 'c', 'd'})) == 4
        def test_reads_file(): assert pathlib.Path(__file__).with_name('data.txt').read_text().strip() == '41'
        def test_polluter(): STATE['x'] = 1
        def test_victim(): assert True
        def test_sleep(): time.sleep(2)
        """)
    write(os.path.join(d, "test_b.py"), """\
        import unittest, time
        class T(unittest.TestCase):
            def test_one(self): self.assertTrue(time.monotonic() >= 0)
            def test_two(self): self.assertEqual(1 + 1, 2)
        """)
    return d


def probe_rust():
    step("rust: cargo test detpy-core fenvix-skip", "cargo test -p detpy-core -p fenvix-skip 2>&1 | grep -E '^test result|FAILED|panicked|error' | tail -30; exit ${PIPESTATUS[0]}", 1800)
    for crate in ("detpy-node", "fenvix-go", "fenvix-jvm", "fenvix-skip"):
        step(f"rust: cargo build -p {crate} --release", f"cargo build -p {crate} --release 2>&1 | tail -15; exit ${{PIPESTATUS[0]}}", 1800)


def probe_python():
    d = py_project()
    py = sys.executable.replace("\\", "/")
    step("python: maturin build wheel", f"'{py}' -m pip install -q 'maturin>=1.5,<2' pytest pytest-xdist && '{py}' -m maturin build --release -o dist 2>&1 | tail -8; exit ${{PIPESTATUS[0]}}", 1800)
    step("python: wheel file name (platform tag)", "ls dist/")
    step("python: pip install wheel", f"'{py}' -m pip install --no-deps --force-reinstall dist/detpy-*.whl 2>&1 | tail -5; exit ${{PIPESTATUS[0]}}")
    step("python: import detpy._core", f"'{py}' -c 'import detpy, detpy._core as c; print(c.__file__)'")
    run = f"cd '{d}' && '{py}' -m pytest -q -p no:cacheprovider"
    step("python: plain pytest", f"{run} 2>&1 | tail -8; exit ${{PIPESTATUS[0]}}", 300)
    step("python: --det run 1", f"{run} --det --det-trace=t1.jsonl 2>&1 | tail -12; exit ${{PIPESTATUS[0]}}", 300)
    step("python: --det run 2", f"{run} --det --det-trace=t2.jsonl 2>&1 | tail -12; exit ${{PIPESTATUS[0]}}", 300)
    step("python: verify t1 t2", f"cd '{d}' && '{py}' -m detpy verify t1.jsonl t2.jsonl 2>&1 | tail -8; exit ${{PIPESTATUS[0]}}", 120)
    step("python: --det --det-seed=3", f"{run} --det --det-seed=3 2>&1 | tail -8; exit ${{PIPESTATUS[0]}}", 300)
    step("python: --det-cache run 1", f"{run} --det --det-cache=.cache1 2>&1 | tail -12; exit ${{PIPESTATUS[0]}}", 300)
    step("python: --det-cache run 2 (reuse expected)", f"{run} --det --det-cache=.cache1 2>&1 | tail -12; exit ${{PIPESTATUS[0]}}", 300)
    step("python: -n 2 --det", f"{run} --det -n 2 2>&1 | tail -12; exit ${{PIPESTATUS[0]}}", 300)
    step("python: -n 2 --det --det-cache", f"{run} --det -n 2 --det-cache=.cache2 2>&1 | tail -12; exit ${{PIPESTATUS[0]}}", 300)
    step("python: --det-isolate", f"{run} --det --det-isolate 2>&1 | tail -12; exit ${{PIPESTATUS[0]}}", 300)
    step("python: python -m detpy unittest --det", f"cd '{d}' && '{py}' -m detpy unittest --det 2>&1 | tail -12; exit ${{PIPESTATUS[0]}}", 300)
    step("python: python -m detpy --help", f"'{py}' -m detpy --help 2>&1 | tail -30; exit ${{PIPESTATUS[0]}}", 60)
    # the engine's own suite (serial, capped): which tests fail on this OS
    step("python: copy extension into python/detpy (as the gate does)", f"cp \"$('{py}' -c 'import detpy._core as c; print(c.__file__)')\" python/detpy/")
    step("python: engine suite core subset",
         f"'{py}' -m pytest -q -p no:randomly tests/test_core_bindings.py tests/test_order.py tests/test_fingerprint.py "
         f"tests/test_clock.py tests/test_seeds.py tests/test_fsorder.py tests/test_network.py tests/test_epoch.py "
         f"tests/test_repro.py -x -q 2>&1 | tail -25; exit ${{PIPESTATUS[0]}}", 1500)
    step("python: engine suite cache subset",
         f"'{py}' -m pytest -q -p no:randomly tests/test_proofcache.py tests/test_isolate.py tests/test_parallel_proof.py "
         f"tests/test_shared_cache.py tests/test_runners_unittest.py -q 2>&1 | tail -25; exit ${{PIPESTATUS[0]}}", 2400)


def probe_node():
    step("node: build addon (node scripts/build.js)", "cd node && node scripts/build.js 2>&1 | tail -8; exit ${PIPESTATUS[0]}", 1800)
    step("node: addon file", "ls node/*.node")
    step("node: npm ci", "cd node && npm ci --no-audit --no-fund 2>&1 | tail -5; exit ${PIPESTATUS[0]}", 900)
    step("node: load addon", "cd node && node -e \"const n=require('./src/native.js'); console.log(Object.keys(n).slice(0,8))\"", 60)
    for f in ("controls", "cache", "jsdom", "runner-mocha", "runner-node-test", "projects"):
        step(f"node: test/{f}.test.js", f"cd node && node --test --test-concurrency=1 test/{f}.test.js 2>&1 | tail -30; exit ${{PIPESTATUS[0]}}", 1200)


def probe_go():
    step("go: go version", "go version")
    step("go: build fenvix-go (cgo, static core)", "mkdir -p dist && cd go && CGO_ENABLED=1 go build -o ../dist/fenvix-go ./cmd/fenvix-go 2>&1 | tail -15; exit ${PIPESTATUS[0]}", 900)
    d = os.path.join(WORK, "gomod")
    write(os.path.join(d, "go.mod"), "module example.com/probe\n\ngo 1.22\n")
    write(os.path.join(d, "probe_test.go"), """\
        package probe

        import (
        	"math/rand"
        	"os"
        	"testing"
        	"time"
        )

        func TestClock(t *testing.T) { _ = time.Now() }
        func TestRand(t *testing.T)  { _ = rand.Int() }
        func TestMap(t *testing.T) {
        	m := map[string]int{"a": 1, "b": 2, "c": 3}
        	for range m {
        	}
        }
        func TestDir(t *testing.T) { _, _ = os.ReadDir(".") }
        """)
    fx = os.path.join(ROOT, "dist", "fenvix-go").replace("\\", "/")
    step("go: plain go test", f"cd '{d}' && go test ./... 2>&1 | tail -8; exit ${{PIPESTATUS[0]}}", 600)
    step("go: fenvix-go test --det", f"cd '{d}' && '{fx}' test --det ./... 2>&1 | tail -20; exit ${{PIPESTATUS[0]}}", 1500)
    step("go: fenvix-go test --skip-cache x1", f"cd '{d}' && '{fx}' test --skip-cache=.fx ./... 2>&1 | tail -20; exit ${{PIPESTATUS[0]}}", 1500)
    step("go: fenvix-go test --skip-cache x2", f"cd '{d}' && '{fx}' test --skip-cache=.fx ./... 2>&1 | tail -20; exit ${{PIPESTATUS[0]}}", 1500)
    step("go: shell suite (go test ./... in go/)", "mkdir -p target/release; cd go && go test -count=1 ./... 2>&1 | grep -E '^(--- FAIL|ok|FAIL|PASS|panic)' | tail -30; exit ${PIPESTATUS[0]}", 2400)


def probe_jvm():
    step("jvm: java -version", "java -version 2>&1; mvn -v 2>&1 | head -3")
    step("jvm: jvm/build.sh", "./jvm/build.sh 2>&1 | tail -15; exit ${PIPESTATUS[0]}", 1800)
    step("jvm: native libraries inside the agent jar", "unzip -l jvm/dist/fenvix-agent.jar | grep -iE '\\.so|\\.dylib|\\.dll' ; ls target/release | grep -iE 'fenvix_jvm|fenvix-skip'")
    py = sys.executable.replace("\\", "/")
    step("jvm: control tests (run_controls.py)", f"'{py}' -m pip install -q blake3; '{py}' jvm/test/run_controls.py --out controls.json 2>&1 | tail -30; exit ${{PIPESTATUS[0]}}", 2400)


def probe_single_cli():
    py = sys.executable.replace("\\", "/")
    step("cli: release/fenvix version", f"'{py}' release/fenvix version 2>&1 | tail -10; exit ${{PIPESTATUS[0]}}", 60)
    step("cli: release/install-image.sh", "mkdir -p dist; release/install-image.sh dist \"$PWD/.gap-audit-work/opt\" 2>&1 | tail -10; exit ${PIPESTATUS[0]}", 600)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--only", default="rust,python,node,go,jvm,cli")
    a = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    RESULTS.append({"step": "platform", "rc": 0, "seconds": 0, "cmd": "",
                    "tail": f"{platform.platform()} | {platform.machine()} | python {platform.python_version()}"})
    only = a.only.split(",")
    for name, fn in (("rust", probe_rust), ("python", probe_python), ("node", probe_node), ("go", probe_go),
                     ("jvm", probe_jvm), ("cli", probe_single_cli)):
        if name in only:
            try:
                fn()
            except Exception as x:  # noqa: BLE001
                RESULTS.append({"step": f"{name}: probe crashed", "rc": "error", "seconds": 0, "tail": repr(x), "cmd": ""})
    with open(os.path.join(ROOT, f"probe-{a.name}.json"), "w") as fh:
        json.dump(RESULTS, fh, indent=1)
    lines = [f"## Platform probe: {a.name}", "", "| step | rc | seconds | last line |", "|---|---|---|---|"]
    for r in RESULTS:
        last = (r["tail"].strip().splitlines() or [""])[-1][:160].replace("|", "\\|")
        lines.append(f"| {r['step']} | {r['rc']} | {r['seconds']} | `{last}` |")
    md = "\n".join(lines) + "\n"
    print(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write(md)


if __name__ == "__main__":
    main()
