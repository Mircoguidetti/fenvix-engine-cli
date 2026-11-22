import sys, os, re, subprocess, tempfile, pathlib, shutil, concurrent.futures as cf
PY = os.environ["R056_PY"]
PROBES = {
 "getpid": "import os\nv = os.getpid()",
 "getppid": "import os\nv = os.getppid()",
 "id_object": "v = id(object())",
 "hash_object": "v = hash(object())",
 "c_random_seed": "import _random\nv = _random.Random().random()",
 "py_random_new": "import random\nv = random.Random().random()",
 "random_module": "import random\nv = random.random()",
 "ssl_RAND_bytes": "import ssl\nv = ssl.RAND_bytes(8).hex()",
 "uuid1": "import uuid\nv = uuid.uuid1()",
 "uuid4": "import uuid\nv = uuid.uuid4()",
 "thread_ident": "import threading\nv = threading.get_ident()",
 "thread_time": "import time\nv = time.thread_time_ns()",
 "process_time": "import time\nv = time.process_time_ns()",
 "rusage": "import resource\nv = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss",
 "os_times": "import os\nv = os.times().user",
 "mktemp": "import tempfile\nv = tempfile.mktemp()",
 "allocated_blocks": "import sys\nv = sys.getallocatedblocks()",
 "loadavg": "import os\nv = os.getloadavg()",
 "dev_urandom": "v = open('/dev/urandom', 'rb').read(8).hex()",
 "posix_urandom": "import posix\nv = posix.urandom(8).hex()",
 "posix_getrandom": "import posix\nv = posix.getrandom(8).hex()",
 "secrets": "import secrets\nv = secrets.token_hex(8)",
 "sysrandom": "import random\nv = random.SystemRandom().random()",
 "proc_self_stat": "v = open('/proc/self/stat').read().split()[21]",
 "set_order_objects": "class K: pass\nv = [id(x) % 7 for x in {K(), K(), K()}]",
 "monotonic_ns": "import time\nv = time.monotonic_ns()",
 "perf_counter": "import time\nv = time.perf_counter_ns()",
 "clock_gettime_raw": "import time\nv = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)",
 "clock_boottime": "import time\nv = time.clock_gettime_ns(time.CLOCK_BOOTTIME)",
 "clock_realtime_posix": "import time\nv = time.clock_gettime_ns(time.CLOCK_REALTIME)",
 "ctypes_time": "import ctypes\nv = ctypes.CDLL(None).time(None)",
 "fd_number_socket": "import socket\ns = socket.socket()\nv = s.fileno()",
 "hash_str": "v = hash('abc')",
}
def runp(root, *a):
    env = {k: x for k, x in os.environ.items() if k not in ("PYTEST_ADDOPTS",)}
    p = subprocess.run([PY, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider", "-p", "no:randomly", *a, "tests"], cwd=root, capture_output=True, text=True, env=env, timeout=300)
    vals = re.findall(r"^VAL (.*)$", p.stdout, re.M)
    reused = bool(re.search(r"^reused 1 result", p.stdout, re.M))
    why = re.findall(r"not (?:reused|cacheable)[^\n]*", p.stdout)
    return p.returncode, vals, reused, why, p.stdout
def probe(name):
    root = pathlib.Path(tempfile.mkdtemp(prefix="r056e-"))
    (root / "tests").mkdir()
    (root / "tests" / "test_e.py").write_text("def test_e():\n" + "".join("    " + l + "\n" for l in PROBES[name].splitlines()) + "    print('VAL', v)\n")
    c = f"--det-cache={root/'.c'}"
    r1 = runp(root, "--det", c)
    r2 = runp(root, "--det", c)
    fresh = [runp(root, "--det")[1] for _ in range(4)]
    shutil.rmtree(root, ignore_errors=True)
    vary = len({tuple(f) for f in fresh}) > 1
    verdict = "WRONG (frozen)" if (r2[2] and vary) else "ok"
    return f"{verdict:15} {name:22} reused={r2[2]} fresh_vary={vary} fresh={[f[0] if f else None for f in fresh][:3]} cold={r1[1]} {r1[3][:1]} rc1={r1[0]}"
with cf.ThreadPoolExecutor(8) as ex:
    for line in ex.map(probe, PROBES):
        print(line, flush=True)
