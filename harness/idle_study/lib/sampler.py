#!/usr/bin/env python3
"""CPU sampler for the idle-share study.

Runs as root next to a test command. Every INTERVAL seconds it reads:
  * /proc/stat (all CPUs): busy = user+nice+system+irq+softirq, plus iowait and steal;
  * cpu.stat usage_usec of the study cgroups (idle_test: the test command's process tree,
    idle_svc: background services started by the harness) and of every Docker container;
and every PROC_EVERY samples it walks /proc/<pid>/stat to attribute CPU to command names.

On SIGTERM/SIGINT it writes one JSON summary to the output path and exits.
Usage: sampler.py OUT.json [interval_seconds]
"""
import glob
import json
import os
import resource
import signal
import sys
import time

OUT = sys.argv[1]
INTERVAL = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
PROC_EVERY = 4
HZ = os.sysconf("SC_CLK_TCK")
CG = "/sys/fs/cgroup"
STUDY_CGROUPS = {"test": f"{CG}/idle_test", "svc": f"{CG}/idle_svc"}

stop = False


def _stop(*_):
    global stop
    stop = True


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)
with open(OUT + ".pid", "w") as _f:
    _f.write(str(os.getpid()))


def read_stat():
    with open("/proc/stat") as f:
        parts = f.readline().split()
    v = [int(x) for x in parts[1:]]
    v += [0] * (10 - len(v))
    user, nice, system, idle, iowait, irq, softirq, steal = v[:8]
    return {
        "busy": user + nice + system + irq + softirq,
        "user": user + nice,
        "system": system + irq + softirq,
        "idle": idle,
        "iowait": iowait,
        "steal": steal,
    }


def cg_usage(path):
    try:
        with open(path + "/cpu.stat") as f:
            for line in f:
                if line.startswith("usage_usec"):
                    return int(line.split()[1])
    except OSError:
        return None
    return None


_names = {}


def container_name(cid):
    if cid in _names:
        return _names[cid]
    name = cid[:12]
    try:
        with open(f"/var/lib/docker/containers/{cid}/config.v2.json") as f:
            d = json.load(f)
        name = d.get("Name", name).lstrip("/")
        img = d.get("Config", {}).get("Image", "")
        if img:
            name = f"{name} [{img}]"
    except Exception:
        pass
    _names[cid] = name
    return name


def containers():
    out = {}
    for p in glob.glob(f"{CG}/system.slice/docker-*.scope"):
        cid = os.path.basename(p)[len("docker-"):-len(".scope")]
        u = cg_usage(p)
        if u is not None:
            out[cid] = u
    for p in glob.glob(f"{CG}/docker/*/"):  # cgroupfs driver layout
        cid = os.path.basename(p.rstrip("/"))
        if len(cid) == 64:
            u = cg_usage(p.rstrip("/"))
            if u is not None:
                out[cid] = u
    return out


def procs():
    """pid -> (comm, utime+stime ticks, cgroup tag)"""
    out = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/stat") as f:
                s = f.read()
            l, r = s.index("("), s.rindex(")")
            comm = s[l + 1:r]
            rest = s[r + 2:].split()
            ticks = int(rest[11]) + int(rest[12])
            with open(f"/proc/{d}/cgroup") as f:
                cgl = f.read().strip().split("::", 1)[-1]
            if cgl.startswith("/idle_test"):
                tag = "test"
            elif cgl.startswith("/idle_svc"):
                tag = "svc"
            elif "docker-" in cgl or cgl.startswith("/docker/"):
                tag = "container"
            else:
                tag = "host"
            out[int(d)] = (comm, ticks, tag)
        except Exception:
            continue
    return out


def self_cpu():
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


t0 = time.monotonic()
wall0 = time.time()
st0 = read_stat()
cg0 = {k: cg_usage(v) for k, v in STUDY_CGROUPS.items()}
ct_first = containers()          # usage at first sight (start of run or creation)
ct_last = dict(ct_first)
ct_born_during = set()
p_prev = procs()
comm_ticks = {}                  # (tag, comm) -> ticks
series = []                      # [t, busy_cores, iowait_cores, test_cores, steal_cores]
prev_t, prev_st = t0, st0
prev_test = cg0["test"]
n = 0
while not stop:
    time.sleep(INTERVAL)
    now = time.monotonic()
    st = read_stat()
    dt = now - prev_t
    tu = cg_usage(STUDY_CGROUPS["test"])
    test_cores = ((tu - prev_test) / 1e6 / dt) if (tu is not None and prev_test is not None) else None
    series.append([
        round(now - t0, 3),
        round((st["busy"] - prev_st["busy"]) / HZ / dt, 3),
        round((st["iowait"] - prev_st["iowait"]) / HZ / dt, 3),
        None if test_cores is None else round(test_cores, 3),
        round((st["steal"] - prev_st["steal"]) / HZ / dt, 3),
    ])
    prev_t, prev_st, prev_test = now, st, tu
    for cid, u in containers().items():
        if cid not in ct_first:
            ct_first[cid] = 0      # created during the run: all of its usage counts
            ct_born_during.add(cid)
        ct_last[cid] = u
    n += 1
    if n % PROC_EVERY == 0:
        p_now = procs()
        for pid, (comm, ticks, tag) in p_now.items():
            base = p_prev.get(pid)
            # known pid: delta since last scan; new pid: all of its CPU so far
            d = ticks - base[1] if base is not None else ticks
            if d > 0:
                comm_ticks[(tag, comm)] = comm_ticks.get((tag, comm), 0) + d
        p_prev = p_now

t1 = time.monotonic()
st1 = read_stat()
cg1 = {k: cg_usage(v) for k, v in STUDY_CGROUPS.items()}
for cid, u in containers().items():
    if cid not in ct_first:
        ct_first[cid] = 0
        ct_born_during.add(cid)
    ct_last[cid] = u

wall = t1 - t0
summary = {
    "start_epoch": wall0,
    "wall_s": wall,
    "interval_s": INTERVAL,
    "ncpu": os.cpu_count(),
    "total": {k: (st1[k] - st0[k]) / HZ for k in st0},
    "sampler_cpu_s": self_cpu(),
    "cgroups": {k: (None if cg0[k] is None or cg1[k] is None else (cg1[k] - cg0[k]) / 1e6) for k in cg0},
    "containers": {
        container_name(cid): round((ct_last[cid] - ct_first[cid]) / 1e6, 3)
        for cid in ct_last
        if ct_last[cid] - ct_first[cid] > 0
    },
    "containers_born_during": len(ct_born_during),
    "by_comm": sorted(
        [[tag, comm, round(t / HZ, 3)] for (tag, comm), t in comm_ticks.items()],
        key=lambda x: -x[2],
    )[:40],
    "series": series,
}
tmp = OUT + ".tmp"
with open(tmp, "w") as f:
    json.dump(summary, f)
os.replace(tmp, OUT)
