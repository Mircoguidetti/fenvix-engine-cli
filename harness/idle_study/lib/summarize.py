#!/usr/bin/env python3
"""Fold one repository's runs into results/<name>.json.

usage: summarize.py OUT_DIR META.json RESULT.json
OUT_DIR holds baseline.json, setup.log, run<i>/{sampler.json,tests.json,meta.json,test.log}.
"""
import glob
import json
import os
import statistics as stx
import sys

out_dir, meta_path, result_path = sys.argv[1:4]
meta = json.load(open(meta_path))
QUIET_ABOVE_BASELINE = 0.10   # cores; an interval below baseline+this counts as "everything blocked"


def tail(path, n=60):
    try:
        with open(path, errors="replace") as f:
            lines = f.read().splitlines()
        return "\n".join(l[:300] for l in lines[-n:])
    except OSError:
        return ""


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(stx.median(xs), 4) if xs else None


base_cores = None
bp = os.path.join(out_dir, "baseline.json")
if os.path.exists(bp):
    b = json.load(open(bp))
    if b["wall_s"] > 0:
        base_cores = max(0.0, (b["total"]["busy"] - b["sampler_cpu_s"]) / b["wall_s"])

runs = []
outcomes = {}   # test id -> list of (run, status, msg)
run_dirs = sorted(glob.glob(os.path.join(out_dir, "run*")), key=lambda p: int(p.rsplit("run", 1)[1]))
for rd in run_dirs:
    i = int(rd.rsplit("run", 1)[1])
    try:
        rm = json.load(open(os.path.join(rd, "meta.json")))
        s = json.load(open(os.path.join(rd, "sampler.json")))
    except Exception:
        continue
    W = rm.get("wall_s") or s["wall_s"]   # the test command's own wall time
    busy = s["total"]["busy"] - s["sampler_cpu_s"]
    net = busy - (base_cores or 0.0) * W
    series = s["series"]
    thr = (base_cores or 0.0) + QUIET_ABOVE_BASELINE
    quiet = sum(1 for p in series if p[1] < thr) / len(series) if series else None
    ge1 = sum(1 for p in series if p[1] >= 1.0) / len(series) if series else None
    cg = s["cgroups"]
    cont = sum(s["containers"].values())
    other = busy - (cg.get("test") or 0) - (cg.get("svc") or 0) - cont
    t = {}
    tp = os.path.join(rd, "tests.json")
    if os.path.exists(tp):
        t = json.load(open(tp)).get("tests", {})
    for tid, v in t.items():
        outcomes.setdefault(tid, []).append((i, v["s"], v.get("m", "")))
    n_fail = sum(1 for v in t.values() if v["s"] == "fail")
    r = {
        "run": i,
        "rc": rm.get("rc"),
        "wall_s": round(W, 2),
        "busy_cpu_s": round(busy, 2),
        "cores_mean": round(busy / W, 3) if W else None,
        "idle_share_raw": round(1 - busy / W, 4) if W else None,
        "idle_share_net": round(1 - net / W, 4) if W else None,
        "quiet_share": None if quiet is None else round(quiet, 4),
        "share_ge1core": None if ge1 is None else round(ge1, 4),
        "iowait_s": round(s["total"]["iowait"], 2),
        "steal_s": round(s["total"]["steal"], 2),
        "sampler_cpu_s": round(s["sampler_cpu_s"], 2),
        "cpu_test_tree_s": None if cg.get("test") is None else round(cg["test"], 2),
        "cpu_svc_s": None if cg.get("svc") is None else round(cg["svc"], 2),
        "cpu_containers_s": round(cont, 2),
        "cpu_other_s": round(other, 2),
        "containers": dict(sorted(s["containers"].items(), key=lambda kv: -kv[1])[:12]),
        "top_comm": s["by_comm"][:15],
        "n_tests": len(t),
        "n_pass": sum(1 for v in t.values() if v["s"] == "pass"),
        "n_fail": n_fail,
        "n_skip": sum(1 for v in t.values() if v["s"] == "skip"),
    }
    if not t or (rm.get("rc") not in (0, None) and n_fail == 0):
        r["log_tail"] = tail(os.path.join(rd, "test.log"), 50)
    if i == 1:
        # 1-second buckets of total busy cores for plotting
        buckets = {}
        for p in series:
            k = int(p[0])
            buckets.setdefault(k, []).append(p[1])
        r["series_1s"] = [round(sum(v) / len(v), 2) for k, v in sorted(buckets.items())][:3600]
    runs.append(r)

n_runs = len(runs)
flaky, consistent_fail = [], []
for tid, occ in outcomes.items():
    sts = [o[1] for o in occ]
    if "fail" in sts and "pass" in sts:
        msgs = []
        for o in occ:
            if o[1] == "fail" and o[2] and o[2][:200] not in [m[:200] for m in msgs]:
                msgs.append(o[2][:1200])
        flaky.append({
            "id": tid,
            "pass_runs": sum(1 for s in sts if s == "pass"),
            "fail_runs": sum(1 for s in sts if s == "fail"),
            "fail_in": [o[0] for o in occ if o[1] == "fail"],
            "messages": msgs[:2],
        })
    elif sts and all(s == "fail" for s in sts):
        consistent_fail.append(tid)

# a test id that is present in some runs only (suite crashed / max-failures) is not flaky by itself
result = dict(meta)
result.update({
    "status": "ok" if n_runs else meta.get("status", "no_runs"),
    "baseline_cores": None if base_cores is None else round(base_cores, 4),
    "n_runs": n_runs,
    "runs": runs,
    "idle": {
        "median_idle_share_raw": med([r["idle_share_raw"] for r in runs]),
        "median_idle_share_net": med([r["idle_share_net"] for r in runs]),
        "median_quiet_share": med([r["quiet_share"] for r in runs]),
        "median_cores_mean": med([r["cores_mean"] for r in runs]),
        "median_wall_s": med([r["wall_s"] for r in runs]),
        "median_busy_cpu_s": med([r["busy_cpu_s"] for r in runs]),
    },
    "tests": {
        "n_distinct": len(outcomes),
        "n_flaky": len(flaky),
        "n_consistent_fail": len(consistent_fail),
        "flaky": sorted(flaky, key=lambda f: -f["fail_runs"]),
        "consistent_fail_sample": sorted(consistent_fail)[:40],
    },
})
if meta.get("status") == "setup_failed" or not n_runs:
    result["setup_log_tail"] = tail(os.path.join(out_dir, "setup.log"), 120)
json.dump(result, open(result_path, "w"), indent=1)
print(json.dumps(result["idle"]), json.dumps({k: v for k, v in result["tests"].items() if k.startswith("n_")}))
