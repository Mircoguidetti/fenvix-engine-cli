"""The Node half of the measurement: one Vitest test per run, under `--det` and strace.

A test is addressed by its file and an anchored `-t` pattern built from its node id
(`file::describe::...::test`), whose segments Vitest joins with spaces. The other tests of
the file are collected and skipped, so the run executes exactly one test.

Two sensor differences from the Python half, both stated in the report:
  * there is no audit hook, so a read made by native code cannot be told from one made by
    JavaScript; the `by nature` bucket for Node rests on threads, children and sockets only.
  * Node always starts a libuv thread pool and Vitest always runs a test file in a worker, so
    only threads and children created from the test phase on are attributed to the test.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import buckets  # noqa: E402
import classify as C  # noqa: E402

TRACESET = ("%file,%process,%network,%clock,getrandom,uname,sysinfo,getrusage,ioctl,"
            "sched_getaffinity,getcpu,statfs,fstatfs,getdents64")
EPOCH = "2025-01-01T00:00:00Z"
MARKER = "__fenvix_marker.mjs"
MARKER_SRC = '''// Measurement sensor: marks the test phase in the syscall stream. Not product code.
import { statSync } from 'node:fs';
import { beforeEach, afterEach } from 'vitest';

const mark = (w) => { try { statSync('/FENVIXMARK/' + w); } catch { /* always ENOENT */ } };
beforeEach(() => mark('S'));
afterEach(() => mark('E'));
'''


def sh(cmd, cwd=None, env=None, timeout=1800):
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout + p.stderr


def pattern_for(nodeid: str) -> tuple:
    f, *segs = nodeid.split("::")
    return f, "^" + re.escape(" ".join(segs)) + "$"


def run_one(nodeid: str, cfg: dict, idx: int) -> dict:
    d = Path(cfg["workdir"]) / f"t{idx:05d}"
    d.mkdir(parents=True, exist_ok=True)
    strace_out, trace_out = d / "strace.txt", d / "trace.jsonl"
    f, pat = pattern_for(nodeid)
    cmd = ["strace", "-f", "-q", "-y", "-s", "512", "--seccomp-bpf", "-o", str(strace_out),
           "-e", f"trace={TRACESET}",
           "node", cfg["detjs"], "vitest", "run", "--det", f"--det-epoch={EPOCH}",
           f"--det-trace={trace_out}", "--setupFiles", f"./{MARKER}", f, "-t", pat]
    t0 = time.time()
    try:
        code, out = sh(cmd, cwd=cfg["src"], env=dict(os.environ), timeout=cfg["timeout"])
        timed_out = False
    except subprocess.TimeoutExpired:
        code, out, timed_out = -9, "TIMEOUT", True
    wall = time.time() - t0

    rec = {"project": cfg["name"], "nodeid": nodeid, "index": idx, "exit": code,
           "timed_out": timed_out, "wall_s": round(wall, 3)}
    if not strace_out.exists():
        rec.update(status="no-strace", bucket="EXCLUDED", causes=["strace produced no output"])
        return rec
    paths = C.Paths(cfg["paths_cfg"])
    parsed = C.parse_strace(strace_out, paths, spawns_before_test=False,
                            infra_collection=cfg['infra'],
                            infra_outside_test=True)
    engine = load_engine_ran(trace_out, nodeid)
    allch: dict = {}
    for ph in ("collection", "test", "after"):
        for k, v in parsed["phases"][ph].items():
            allch[k] = allch.get(k, 0) + v
    testch = dict(parsed["phases"]["test"])

    rec["engine_found"] = engine["found"]
    rec["engine_outcome"] = engine["outcome"]
    rec["engine_sources"] = engine["sources"]
    rec["engine_uncontrolled"] = engine["uncontrolled"]
    rec["engine_n_events"] = engine["n_events"]
    rec["engine_n_ran"] = engine["n_ran"]
    rec["channels_all"] = allch
    rec["channels_test"] = testch
    rec["native_reads_test"] = []          # no audit hook on Node
    rec["n_native_reads_test"] = 0
    rec["engine_bootstrap"] = parsed["engine_bootstrap"]
    rec["infra_suppressed"] = parsed["infra_suppressed"]
    for rule in ("E", "S"):
        b, c = buckets.classify(allch, engine, [], rule=rule)
        rec[f"bucket_{rule}"] = b
        rec[f"causes_{rule}"] = c
    bt, ct = buckets.classify(testch, engine, [], rule="E")
    rec["bucket_testphase_E"], rec["causes_testphase_E"] = bt, ct
    rec["bucket"], rec["causes"] = rec["bucket_E"], rec["causes_E"]
    rec["status"] = "ok" if engine["n_ran"] == 1 else (
        "no-test-ran" if engine["n_ran"] == 0 else "several-tests-ran")

    keep = Path(cfg["keep_dir"]) / f"t{idx:05d}"
    keep.mkdir(parents=True, exist_ok=True)
    try:
        with strace_out.open("rb") as fi, gzip.open(keep / "strace.txt.gz", "wb", 6) as fo:
            shutil.copyfileobj(fi, fo)
        if trace_out.exists():
            shutil.copy2(trace_out, keep / "trace.jsonl")
        (keep / "nodeid.txt").write_text(nodeid + "\n")
    except OSError:
        pass
    shutil.rmtree(d, ignore_errors=True)
    return rec


def load_engine_ran(trace: Path, nodeid: str) -> dict:
    """The record of the one test that actually ran (the others are collected and skipped)."""
    rec = {"found": False, "sources": {}, "uncontrolled": [], "n_events": 0,
           "outcome": "", "n_ran": 0}
    if not trace.exists():
        return rec
    for ln in trace.open(errors="replace"):
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("type") != "test" or r.get("outcome") == "skipped":
            continue
        rec["n_ran"] += 1
        if not rec["found"] or r.get("nodeid") == nodeid:
            rec.update(found=True, sources=r.get("counts") or {},
                       uncontrolled=r.get("uncontrolled") or [],
                       n_events=r.get("n_events") or 0, outcome=r.get("outcome", ""))
    return rec


def collect(cfg: dict) -> list:
    """Every node id, from one `--det` run of the whole suite."""
    trace = Path(cfg["workdir"]) / "collect.jsonl"
    trace.parent.mkdir(parents=True, exist_ok=True)
    code, out = sh(["node", cfg["detjs"], "vitest", "run", "--det", f"--det-epoch={EPOCH}",
                    f"--det-trace={trace}"], cwd=cfg["src"], timeout=5400)
    (Path(cfg["out"]) / f"{cfg['name']}.collect.log").write_text(out[-20000:])
    ids = []
    if trace.exists():
        for ln in trace.open(errors="replace"):
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("type") == "test":
                ids.append(r["nodeid"])
    return ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="valibot")
    ap.add_argument("--src", required=True)
    ap.add_argument("--sample", type=int, default=220)
    ap.add_argument("--seed", type=int, default=20261121)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--root", default="/home/user/measure")
    a = ap.parse_args()

    root = Path(a.root)
    src = a.src
    (Path(src) / MARKER).write_text(MARKER_SRC)
    repo_root = sh(["git", "rev-parse", "--show-toplevel"], cwd=src)[1].strip() or src
    cfg = {"name": a.project, "src": src, "timeout": a.timeout,
           "detjs": "/home/user/fenvix-engine-cli/node/bin/detjs.js",
           "out": str(root / "out"), "workdir": str(root / "work" / a.project),
           "keep_dir": str(root / "raw" / a.project),
           "paths_cfg": {"project_src": repo_root, "site_dirs": [], "stdlib_dirs": [],
                         "venv": "/nonexistent-venv",
                         "engine_dirs": ["/home/user/fenvix-engine-cli",
                                         str(Path(src) / MARKER), str(root / "out"),
                                         str(root / "work"), str(root / "raw")]}}
    # the runner's own channels, measured by a baseline run in which no test runs at all
    base = HERE / "node_infra_baseline.json"
    cfg["infra"] = frozenset(json.loads(base.read_text())) if base.exists() else frozenset()
    shutil.rmtree(cfg["workdir"], ignore_errors=True)
    shutil.rmtree(cfg["keep_dir"], ignore_errors=True)

    ids = collect(cfg)
    (root / "out" / f"{a.project}.collected.txt").write_text("\n".join(ids))
    if not ids:
        print(f"{a.project}: collected nothing; see the collect log")
        return 1
    rng = random.Random(a.seed)
    sample = sorted(rng.sample(ids, min(a.sample, len(ids))))
    (root / "out" / f"{a.project}.sample.txt").write_text("\n".join(sample))
    print(f"{a.project}: collected={len(ids)} sampled={len(sample)} seed={a.seed}", flush=True)
    meta = {"name": a.project, "src": src, "repo_root": repo_root,
            "commit": sh(["git", "rev-parse", "HEAD"], cwd=src)[1].strip()[:12],
            "commit_date": sh(["git", "log", "-1", "--format=%cs"], cwd=src)[1].strip(),
            "collected": len(ids), "runner": "vitest"}
    (root / "out" / f"{a.project}.prepared.json").write_text(json.dumps(meta, indent=1))

    outp = root / "out" / f"{a.project}.jsonl"
    done = 0
    with outp.open("w") as fh, ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(run_one, nid, cfg, i): nid for i, nid in enumerate(sample)}
        for f in list(futs):
            try:
                rec = f.result()
            except Exception as e:  # noqa: BLE001
                rec = {"project": a.project, "nodeid": futs[f], "status": "error",
                       "bucket": "EXCLUDED", "causes": [f"driver error: {e}"]}
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            done += 1
            if done % 20 == 0:
                print(f"{a.project}: {done}/{len(sample)}", flush=True)
    print(f"{a.project}: wrote {outp}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
