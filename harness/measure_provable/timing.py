"""Secondary: the wall-clock cost of strace on a whole suite under --det.

An upper bound for what a syscall-level sensor would cost, since strace stops the traced
process twice per syscall and writes every line to disk; a seccomp-BPF/ptrace sensor that
only inspects the calls it cares about would cost less.

Runs the whole suite serially, alternating the two modes, and reports the median. Reports the
load average before and after so the result can be marked NOISY.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import time
from pathlib import Path

TRACESET = ("%file,%process,%network,%clock,getrandom,uname,sysinfo,getrusage,ioctl,"
            "sched_getaffinity,getcpu,statfs,fstatfs,getdents64")
EPOCH = "2025-01-01T00:00:00Z"


def one(py: str, src: str, args: list, trace: Path, strace_out: Path | None) -> tuple:
    cmd = [py, "-m", "pytest", "-p", "no:randomly", "--det", f"--det-epoch={EPOCH}",
           f"--det-trace={trace}", "-q", "--no-header", "-p", "no:cacheprovider", *args]
    if strace_out:
        cmd = ["strace", "-f", "-q", "-y", "-s", "512", "--seccomp-bpf", "-o", str(strace_out),
               "-e", f"trace={TRACESET}"] + cmd
    env = dict(os.environ)
    env.pop("PYTHONHASHSEED", None)
    t0 = time.time()
    p = subprocess.run(cmd, cwd=src, env=env, capture_output=True, text=True, timeout=14400)
    return time.time() - t0, p.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--root", default="/home/user/measure")
    a = ap.parse_args()
    root = Path(a.root)
    meta = json.loads((root / "out" / f"{a.project}.prepared.json").read_text())
    py, src = meta["python"], str(root / "src" / a.project)
    args = meta.get("pytest_args", [])
    work = root / "work" / f"timing-{a.project}"
    work.mkdir(parents=True, exist_ok=True)

    load_before = os.getloadavg()
    plain, traced = [], []
    for i in range(a.repeats):
        d, rc = one(py, src, args, work / f"p{i}.jsonl", None)
        plain.append(d)
        print(f"{a.project} plain  run {i}: {d:8.1f}s rc={rc}", flush=True)
        d, rc = one(py, src, args, work / f"t{i}.jsonl", work / f"s{i}.txt")
        traced.append(d)
        print(f"{a.project} strace run {i}: {d:8.1f}s rc={rc}", flush=True)
        (work / f"s{i}.txt").unlink(missing_ok=True)
    load_after = os.getloadavg()
    res = {"project": a.project, "repeats": a.repeats,
           "plain_s": plain, "strace_s": traced,
           "plain_median_s": round(statistics.median(plain), 1),
           "strace_median_s": round(statistics.median(traced), 1),
           "factor": round(statistics.median(traced) / statistics.median(plain), 2),
           "load_before": load_before, "load_after": load_after,
           "noisy": max(load_before[0], load_after[0]) > 1.0}
    (root / "out" / f"{a.project}.timing.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
