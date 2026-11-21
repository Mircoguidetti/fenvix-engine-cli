"""Item 5: g0160 / g0163 now allow a reuse because --det pins the CPU count and the host name. Does every read path
see the pinned value? Run 1 on the full machine, run 2 under taskset -c 0 / unshare --uts with another host name;
cache vs uncached --det under the same prefix."""
import os, pathlib, shutil, subprocess, sys, tempfile
sys.path.insert(0, sys.argv[1]); import h53

def scen(name, body, prefix):
    root = pathlib.Path(tempfile.mkdtemp(prefix="r053p-"))
    h53.write(root, {"pytest.ini": "[pytest]\npythonpath = .\n", "tests/test_p.py": body})
    cache = f"--det-cache={root / '.c'}"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "DETPY_CACHE_IN_PROCESS")}
    def go(pre, *a):
        p = subprocess.run([*pre, sys.executable, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", "-p", "no:randomly",
                            *a, "tests"], cwd=root, capture_output=True, text=True, env=env)
        o = {l.split()[1]: l.split()[0] for l in p.stdout.splitlines() if l.startswith(("PASSED ", "FAILED "))}
        s = [l for l in p.stdout.splitlines() if l.startswith(("reused ", "not reused", "not cacheable"))]
        return o, s
    o1, s1 = go((), "--det", cache); go((), "--det", cache)
    o2, s2 = go(prefix, "--det", cache)
    d, _ = go(prefix, "--det")
    print(f"{'OK   ' if o2 == d else 'WRONG'} {name}: run1 {o1}; run2 cache {o2} {s2}; uncached --det {d}", flush=True)
    shutil.rmtree(root, ignore_errors=True)

TS = ("taskset", "-c", "0")
UTS = ("unshare", "--uts", "sh", "-c", 'hostname otherbox-r053; exec "$@"', "sh")
real_status = [l for l in open("/proc/self/status") if l.startswith("Cpus_allowed_list")][0].strip()
host = os.uname().nodename
scen("cpu: posix.sched_getaffinity", f"import posix\n\ndef test_c():\n    assert len(posix.sched_getaffinity(0)) == {len(os.sched_getaffinity(0))}\n", TS)
scen("cpu: /proc/self/status Cpus_allowed_list", "def test_c():\n    l = [x for x in open('/proc/self/status') if x.startswith('Cpus_allowed_list')][0].strip()\n"
     f"    assert l == {real_status!r}\n", TS)
scen("cpu: ctypes sched_getaffinity", "import ctypes, ctypes.util\n\ndef test_c():\n    libc = ctypes.CDLL(None, use_errno=True)\n"
     "    mask = ctypes.create_string_buffer(128)\n    assert libc.sched_getaffinity(0, 128, mask) == 0\n"
     f"    assert sum(bin(b).count('1') for b in mask.raw) == {len(os.sched_getaffinity(0))}\n", TS)
scen("cpu: os.sched_getaffinity (control)", f"import os\n\ndef test_c():\n    assert len(os.sched_getaffinity(0)) == 2\n", TS)
scen("host: posix.uname", f"import posix\n\ndef test_h():\n    assert posix.uname().nodename == {host!r}\n", UTS)
scen("host: _socket.gethostname", f"import _socket\n\ndef test_h():\n    assert _socket.gethostname() == {host!r}\n", UTS)
scen("host: /proc/sys/kernel/hostname", f"def test_h():\n    assert open('/proc/sys/kernel/hostname').read().strip() == {host!r}\n", UTS)
scen("host: socket.gethostname (control)", "import socket\n\ndef test_h():\n    assert socket.gethostname() == 'localhost'\n", UTS)
