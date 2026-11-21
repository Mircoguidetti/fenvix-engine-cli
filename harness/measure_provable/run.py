"""Run each sampled test alone under `--det` with strace attached and classify it.

  python run.py --project flask --sample 220 --seed 20261121 --workers 3

Writes one JSON line per test to <out>/<project>.jsonl and keeps the first few raw strace
files per project as evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import gzip
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
EPOCH = "2025-01-01T00:00:00Z"   # fixed, so --det-epoch=auto does not run `git log` per run
KEEP_RAW = 3


def sh(cmd, cwd=None, env=None, timeout=900):
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout + p.stderr


def env_dirs(py: str) -> dict:
    code = ("import json,sysconfig,site,sys;"
            "p=sysconfig.get_paths();"
            "print(json.dumps({'stdlib':[p['stdlib'],p['platstdlib'],sysconfig.get_path('stdlib',"
            "vars={'installed_base':sys.base_prefix,'py_version_short':'%d.%d'%sys.version_info[:2]})],"
            "'site':list({*site.getsitepackages(),p['purelib'],p['platlib']}),'prefix':sys.prefix}))")
    return json.loads(sh([py, "-c", code])[1])


def collect(py: str, src: str, pytest_args) -> list:
    code, out = sh([py, "-m", "pytest", "-p", "no:randomly", "--collect-only", "-q",
                    *pytest_args], cwd=src, timeout=1800)
    ids = [ln.strip() for ln in out.splitlines() if "::" in ln and not ln.startswith(("ERROR", "E "))]
    return ids


def run_one(nodeid: str, cfg: dict, idx: int, workdir: Path) -> dict:
    d = workdir / f"t{idx:05d}"
    d.mkdir(parents=True, exist_ok=True)
    strace_out, trace_out, audit_out = d / "strace.txt", d / "trace.jsonl", d / "audit.tsv"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(HERE)
    env["FENVIX_SENSOR_AUDIT"] = str(audit_out)
    env.pop("PYTHONHASHSEED", None)
    cmd = ["strace", "-f", "-q", "-y", "-s", "512", "--seccomp-bpf", "-o", str(strace_out),
           "-e", f"trace={TRACESET}",
           cfg["python"], "-m", "pytest", "-p", "no:randomly", "-p", "fenvix_sensor",
           "--det", f"--det-epoch={EPOCH}", f"--det-trace={trace_out}", "-q", "--no-header",
           "-p", "no:cacheprovider", *cfg["pytest_args"], nodeid]
    t0 = time.time()
    try:
        code, out = sh(cmd, cwd=cfg["src"], env=env, timeout=cfg.get("timeout", 300))
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
    parsed = C.parse_strace(strace_out, paths)
    engine = C.load_engine(trace_out, nodeid)
    audit = C.load_audit(audit_out)
    allch: dict = {}
    for ph in ("collection", "test", "after"):
        for k, v in parsed["phases"][ph].items():
            allch[k] = allch.get(k, 0) + v
    testch = dict(parsed["phases"]["test"])

    def controlled(p: str) -> bool:
        return paths.cat(p) in buckets.CONTROLLED_E
    nat = buckets.native_reads(parsed, audit, controlled)

    rec["engine_found"] = engine["found"]
    rec["engine_outcome"] = engine["outcome"]
    rec["engine_sources"] = engine["sources"]
    rec["engine_uncontrolled"] = engine["uncontrolled"]
    rec["engine_n_events"] = engine["n_events"]
    rec["channels_all"] = allch
    rec["channels_test"] = testch
    rec["native_reads_test"] = nat[:20]
    rec["n_native_reads_test"] = len(nat)
    for rule in ("E", "S"):
        b, c = buckets.classify(allch, engine, nat, rule=rule)
        rec[f"bucket_{rule}"] = b
        rec[f"causes_{rule}"] = c
    bt, ct = buckets.classify(testch, engine, nat, rule="E")
    rec["bucket_testphase_E"] = bt
    rec["causes_testphase_E"] = ct
    rec["bucket"] = rec["bucket_E"]
    rec["causes"] = rec["causes_E"]
    rec["status"] = "ok" if engine["found"] else ("not-run" if code != 0 else "no-engine-record")
    # keep the raw sensor output, compressed, so the classification can be redone offline
    keep = Path(cfg["keep_dir"]) / f"t{idx:05d}"
    keep.mkdir(parents=True, exist_ok=True)
    try:
        with strace_out.open("rb") as fi, gzip.open(keep / "strace.txt.gz", "wb", 6) as fo:
            shutil.copyfileobj(fi, fo)
        for f in (trace_out, audit_out):
            if f.exists():
                shutil.copy2(f, keep / f.name)
        (keep / "nodeid.txt").write_text(nodeid + "\n")
    except OSError:
        pass
    shutil.rmtree(d, ignore_errors=True)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--sample", type=int, default=220)
    ap.add_argument("--seed", type=int, default=20261121)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--root", default="/home/user/measure")
    a = ap.parse_args()

    root = Path(a.root)
    meta = json.loads((root / "out" / f"{a.project}.prepared.json").read_text())
    py, src = meta["python"], meta["src"] if "src" in meta else str(root / "src" / a.project)
    dirs = env_dirs(py)
    cfg = {"name": a.project, "python": py, "src": src, "pytest_args": meta.get("pytest_args", []),
           "timeout": a.timeout,
           "paths_cfg": {"project_src": src, "site_dirs": dirs["site"],
                         "stdlib_dirs": dirs["stdlib"], "venv": dirs["prefix"],
                         "engine_dirs": [str(HERE), str(root / "out"), str(root / "work")]}}

    ids = collect(py, src, cfg["pytest_args"])
    (root / "out" / f"{a.project}.collected.txt").write_text("\n".join(ids))
    rng = random.Random(a.seed)
    sample = sorted(rng.sample(ids, min(a.sample, len(ids))))
    (root / "out" / f"{a.project}.sample.txt").write_text("\n".join(sample))
    print(f"{a.project}: collected={len(ids)} sampled={len(sample)} seed={a.seed}", flush=True)

    cfg["keep_dir"] = str(root / "raw" / a.project)
    shutil.rmtree(cfg["keep_dir"], ignore_errors=True)
    workdir = root / "work" / a.project
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)
    # warm the engine's pyc cache for this environment, so no run pays the cold rewrite
    sh([py, "-m", "pytest", "-p", "no:randomly", "--det", f"--det-epoch={EPOCH}",
        "--det-trace=" + str(workdir / "warm.jsonl"), "-q", "--no-header",
        "-p", "no:cacheprovider", *cfg["pytest_args"], sample[0]], cwd=src, timeout=1800)

    outp = root / "out" / f"{a.project}.jsonl"
    done = 0
    with outp.open("w") as fh, ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(run_one, nid, cfg, i, workdir): nid for i, nid in enumerate(sample)}
        for f in futs:
            pass
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
    sys.exit(main())
