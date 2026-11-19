import os, sys, random, time, datetime, uuid, secrets, tempfile, threading, queue, select, glob, json, string
from pathlib import Path
HERE = Path(__file__).parent
OUT = []

def rec(name, v):
    with open(HERE.parent / f"vals-{os.environ['MODE']}.jsonl", "a") as fh:
        fh.write(json.dumps([name, repr(v)]) + "\n")

class MyR(random.Random):
    pass

def test_random_edges():
    rec("r1", [random.random(), random.randint(0, 10**30), random.getrandbits(0), random.getrandbits(200)])
    rec("r2", [random.choices("abc", weights=[1, 2, 3], k=5), random.choices("abc", cum_weights=[1, 2, 3], k=3)])
    rec("r3", [random.sample(range(100), 5), random.sample(["a", "b"], counts=[3, 2], k=4), random.randbytes(7)])
    rec("r4", [random.gauss(), random.normalvariate(), random.expovariate(), random.triangular(), random.betavariate(1, 2)])
    rec("r5", [random.binomialvariate(10, 0.3), random.vonmisesvariate(1, 1), random.paretovariate(2), random.weibullvariate(1, 2)])
    x = list(range(10)); random.shuffle(x); rec("r6", x)
    rec("r7", [MyR().random(), random.Random().random(), random.Random(None).random(), random.Random("s").random()])
    r = random.Random(); r.seed(); rec("r8", r.random())
    random.seed(); rec("r9", random.random())
    st = random.getstate(); a = random.random(); random.setstate(st); rec("r10", [a, random.random()])
    rec("r11", [random.uniform(1, 2), random.randrange(0, 100, 7), random.choice("xyz"), random.lognormvariate(0, 1), random.gammavariate(2, 1)])

def test_entropy():
    rec("e1", [len(os.urandom(4)), str(uuid.uuid1())[:0], len(secrets.token_hex(4))])
    rec("e2", [uuid.uuid4().version])

def test_tempnames():
    fd, n = tempfile.mkstemp(dir=HERE); os.close(fd); os.unlink(n)
    d = tempfile.mkdtemp(dir=HERE); os.rmdir(d)
    rec("t1", [os.path.basename(n), os.path.basename(d), next(tempfile._get_candidate_names())])

def test_clock_edges():
    rec("c1", [time.time(), time.time_ns(), time.monotonic(), time.monotonic_ns(), time.perf_counter(), time.perf_counter_ns()])
    rec("c2", [time.gmtime(), time.localtime(), time.gmtime(0), time.localtime(None), time.ctime(), time.asctime(), time.strftime("%c")])
    rec("c3", [time.clock_gettime(time.CLOCK_REALTIME), time.clock_gettime_ns(time.CLOCK_MONOTONIC), time.clock_gettime(time.CLOCK_BOOTTIME) if hasattr(time, "CLOCK_BOOTTIME") else 0])
    rec("c4", [datetime.datetime.now(), datetime.datetime.now(datetime.timezone.utc), datetime.datetime.utcnow(), datetime.date.today(), datetime.datetime.today()])
    rec("c5", [datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30))), time.mktime(time.localtime())])
    t0 = time.monotonic(); time.sleep(0.5); time.sleep(0); rec("c6", time.monotonic() - t0)
    for bad in (-1, float("nan")):
        try:
            time.sleep(bad)
        except Exception as e:
            rec("c7", type(e).__name__ + str(e))
    rec("c8", [time.time() for _ in range(50)][-1])

def test_waits():
    e = threading.Event(); rec("w1", [e.wait(0.2), time.time()])
    q = queue.Queue()
    try:
        q.get(timeout=0.3)
    except queue.Empty:
        rec("w2", time.time())
    c = threading.Condition()
    with c:
        rec("w3", [c.wait(0.1), c.wait_for(lambda: False, 0.1), time.time()])
    l = threading.Lock(); l.acquire(); rec("w4", [l.acquire(timeout=0.2), time.time()])
    rec("w5", [select.select([], [], [], 0.25), time.time()])
    rl = threading.RLock(); rec("w6", rl.acquire(timeout=0.1))

def test_fs_order():
    d = HERE / "d"
    rec("f1", os.listdir(d)); rec("f2", os.listdir(os.fsencode(d)))
    rec("f3", [e.name for e in os.scandir(d)])
    rec("f4", sorted(glob.glob(str(d / "*"))) == glob.glob(str(d / "*")))
    rec("f5", [glob.glob(str(d / "*")), glob.glob("d/**", recursive=True, root_dir=HERE), list(glob.iglob(str(d / "?")))])
    rec("f6", [str(p) for p in d.iterdir()]); rec("f7", [str(p) for p in d.glob("*")]); rec("f8", [str(p) for p in HERE.rglob("*") if "pycache" not in str(p) and "vals" not in str(p)])
    rec("f9", list(os.walk(d, topdown=False)))
    fd = os.open(d, os.O_RDONLY); rec("f10", os.listdir(fd)); os.close(fd)
    with os.scandir(d) as it: rec("f11", [e.name for e in it])
