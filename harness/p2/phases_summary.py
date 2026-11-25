#!/usr/bin/env python3
"""P2 Phase B summaries (committed as JSON; the raw phases file and CPU profiles are not committed).

  phases_summary.py phases PHASES_JSONL OUT.json      seconds per phase of a DETJS_PHASES=1 run, per worker counters
  phases_summary.py cpuprof DIR OUT.json [--top 10]  top functions by self time over every .cpuprofile in DIR
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import defaultdict


def phases(path):
    lines = [json.loads(x) for x in open(path) if x.strip()]
    start = min((l["t"] for l in lines if l.get("phase") in ("start", "wrapper_start")), default=None)
    out = {"source": os.path.basename(path), "main": {}, "workers": [], "rerun_one_lane": [], "passes": sorted({str(l.get("pass")) for l in lines})}
    by = defaultdict(list)
    for l in lines:
        by[l["phase"]].append(l)
    for p in ("deps_hash", "plan", "trace_write"):
        out["main"][p + "_s"] = round(sum(l.get("ms", 0) for l in by[p]) / 1000, 3)
    rel = lambda t: None if start is None else round((t - start) / 1000, 3)
    for p in ("start", "workers_spawn", "exit"):
        out["main"][p + "_at_s"] = [rel(l["t"]) for l in by[p]]
    out["main"]["start_uptime_s"] = [round(l.get("uptime_ms", 0) / 1000, 3) for l in by["start"]]
    out["main"]["exit_uptime_s"] = [round(l.get("uptime_ms", 0) / 1000, 3) for l in by["exit"]]
    spawn = {str(l.get("pass")): l["t"] for l in by["workers_spawn"]}
    ready = {(l["pid"], l["thread"]): l for l in by["worker_ready"]}
    for t in by["tests"]:
        pid, thr = (int(x) for x in t["worker"].split(":"))
        r = ready.get((pid, thr))
        sp = spawn.get(str(t.get("pass")))
        out["workers"].append({"worker": t["worker"], "pass": t.get("pass"), "files": t["files"],
                               "ready_after_spawn_s": round((r["t"] - sp) / 1000, 3) if r and sp else None,
                               "wall_s": round(t["wall_ms"] / 1000, 3), "file_s": round(t["file_ms"] / 1000, 3),
                               "io_release": t["io_release"], "held_s": round(t["held_ms"] / 1000, 3),
                               "stack_captures": t["stack_captures"], "uncontrolled_io": t["uncontrolled_io"]})
    for l in by["rerun_one_lane"]:
        out["rerun_one_lane"].append({"count": l.get("count"), "s": round(l.get("ms", 0) / 1000, 3)})
    files = sorted(by["file"], key=lambda l: -l.get("ms", 0))
    out["files_top"] = [{"file": l["file"], "s": round(l["ms"] / 1000, 3), "io_release": l["io_release"],
                         "held_s": round(l["held_ms"] / 1000, 3), "stack_captures": l["stack_captures"]} for l in files[:20]]
    out["totals"] = {k: sum(w[k] for w in out["workers"]) for k in ("io_release", "stack_captures", "uncontrolled_io")}
    out["totals"]["held_s"] = round(sum(w["held_s"] for w in out["workers"]), 3)
    return out


def cpuprof(d, top=10):
    self_us = defaultdict(float)
    total = 0.0
    n = 0
    for p in sorted(glob.glob(os.path.join(d, "*.cpuprofile"))):
        prof = json.load(open(p))
        nodes = {x["id"]: x for x in prof["nodes"]}
        n += 1
        for sid, dt in zip(prof.get("samples", []), prof.get("timeDeltas", [])):
            cf = nodes[sid]["callFrame"]
            key = f"{cf.get('functionName') or '(anonymous)'} {cf.get('url', '')}:{cf.get('lineNumber', -1) + 1}"
            self_us[key] += dt
            total += dt
    rows = sorted(self_us.items(), key=lambda kv: -kv[1])
    detjs = [kv for kv in rows if "/node/src/" in kv[0] or "/node/bin/" in kv[0] or "detjs" in kv[0]]
    fmt = lambda kv: {"function": kv[0], "self_s": round(kv[1] / 1e6, 3), "share": round(kv[1] / total, 4) if total else None}
    return {"profiles": n, "total_s": round(total / 1e6, 3), "top": [fmt(x) for x in rows[:top]],
            "top_engine": [fmt(x) for x in detjs[:top]],
            "engine_self_s": round(sum(v for _, v in detjs) / 1e6, 3)}


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 3:
        sys.exit(__doc__)
    top = int(a[a.index("--top") + 1]) if "--top" in a else 10
    res = phases(a[1]) if a[0] == "phases" else cpuprof(a[1], top)
    with open(a[2], "w") as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1)[:3000])
