#!/usr/bin/env python3
"""P2 Phase B: where an engine parallel run's wall time goes, per repository (BREAKDOWN.md tables).

  breakdown.py [--base harness/p2/data/baseline] [--phaseb harness/p2/data/phaseB] [--json OUT.json]
  breakdown.py lanes [BASELINE_DIR]     round-3 timed traces: outside-lanes time, plan vs runtime excess

Sources, all raw: the baseline `results.jsonl` (medians as in table.py), the Phase B `fixed.jsonl` row of the
`phases` run (its wall) and its `<trace>.phases.jsonl` (the timers, node/src/phases.js), and `cpuprof-summary.json`.

Segments of the DETJS_PHASES run, per hazard pass (the wrapper's pass 1 is the parallel run; pass 2, when present,
is the one-lane re-run of the files the wrapper picked):
  launch    = run wall - (last exit - first wrapper_start/start): process start-up and shut-down outside the timers
  pre       = first worker_ready - start               (startup, plan, worker spawn)
  window    = last file end - first worker_ready       (test files running)
  post      = exit - last file end                     (deps_hash, trace_write and the rest of finish)
  ideal     = sum of per-file walls / workers;  idle = window - ideal (lanes waiting, imbalance, spawn gaps)
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import table  # noqa: E402


def lines_of(p):
    with open(p) as f:
        return [json.loads(x) for x in f if x.strip()]


def passes(lines):
    out = {}
    for ps in sorted({str(l.get("pass")) for l in lines if l.get("phase") in ("start", "file")}):
        L = [l for l in lines if str(l.get("pass")) == ps]
        g = lambda ph: [l for l in L if l["phase"] == ph]
        files = g("file")
        start = min((l["t"] for l in g("start")), default=None)
        ex = max((l["t"] for l in g("exit")), default=None)
        ready = min((l["t"] for l in g("worker_ready")), default=None)
        last = max((l["t"] + l["ms"] for l in files), default=None)
        spawn = g("workers_spawn")
        w = spawn[0].get("workers") if spawn else None
        fsum = sum(l["ms"] for l in files) / 1000
        sec = lambda a, b: None if a is None or b is None else round((b - a) / 1000, 3)
        d = {"workers": w, "files": len(files), "processes": len({(l["pid"], l["thread"]) for l in files}),
             "pre_s": sec(start, ready), "window_s": sec(ready, last), "post_s": sec(last, ex),
             "deps_hash_s": round(sum(l["ms"] for l in g("deps_hash")) / 1000, 3),
             "trace_write_s": round(sum(l["ms"] for l in g("trace_write")) / 1000, 3),
             "plan_s": round(sum(l["ms"] for l in g("plan")) / 1000, 3),
             "file_sum_s": round(fsum, 3), "ideal_s": round(fsum / w, 3) if w else None,
             "io_release": sum(l.get("io_release", 0) for l in files),
             "held_s": round(sum(l.get("held_ms", 0) for l in files) / 1000, 3),
             "stack_captures": sum(l.get("stack_captures", 0) for l in files),
             "uncontrolled_io": sum(l.get("uncontrolled_io", 0) for l in files),
             "start_t": start, "exit_t": ex}
        if d["window_s"] is not None and d["ideal_s"] is not None:
            d["idle_s"] = round(d["window_s"] - d["ideal_s"], 3)
        top = sorted(files, key=lambda l: -l["ms"])[:5]
        d["files_top"] = [{"file": l["file"], "s": round(l["ms"] / 1000, 3), "held_s": round(l.get("held_ms", 0) / 1000, 3),
                           "io_release": l.get("io_release", 0)} for l in top]
        out[ps] = d
    return out


def repo(base, pb, name):
    s = table.summarize(base, name, table.rows_of(base))
    m = s.get("med", {})
    serial = [r["wall_s"] for r in table.rows_of(base) if r.get("repo") == name and r["kind"] == "serial"]
    res = {"repo": name, "baseline": {"PS": m.get("PS"), "S": table.med(serial), "PP_best": m.get("PP_best"),
                                      "PP_w": m.get("PP_w"), "E_best": m.get("E_best"), "E_w": m.get("E_w"),
                                      "E_PP": m.get("E_PP"), "PS_E": m.get("PS_E"), "meets": m.get("meets")}}
    d = os.path.join(pb, name)
    fx = os.path.join(pb, "fixed.jsonl")
    runs = [r for r in lines_of(fx) if r.get("repo") == name] if os.path.exists(fx) else []
    ph = [r for r in runs if r["label"] == "phases"]
    cp = [r for r in runs if r["label"] == "cpuprof"]
    raw = os.path.join(d, f"phases-{name}.jsonl.phases.jsonl")
    if not ph or not os.path.exists(raw):
        res["missing"] = True
        return res
    r = ph[-1]
    lines = lines_of(raw)
    P = passes(lines)
    t0 = min(l["t"] for l in lines if l["phase"] in ("wrapper_start", "start"))
    t1 = max(l["t"] for l in lines if l["phase"] == "exit")
    res["run"] = {"wall_s": r["wall_s"], "exit": r["exit"], "workers": r["workers"], "container_boot": r.get("container_boot"),
                  "outcome_counts": r.get("outcome_counts"), "launch_s": round(r["wall_s"] - (t1 - t0) / 1000, 3),
                  "cpuprof_wall_s": cp[-1]["wall_s"] if cp else None}
    res["passes"] = P
    res["rerun_one_lane"] = [{"count": l.get("count"), "s": round(l.get("ms", 0) / 1000, 3)} for l in lines if l["phase"] == "rerun_one_lane"]
    if len(P) > 1:
        a, b = P[sorted(P)[0]], P[sorted(P)[-1]]
        res["between_passes_s"] = round((b["start_t"] - a["exit_t"]) / 1000, 3) if a["exit_t"] and b["start_t"] else None
    cpf = os.path.join(d, "cpuprof-summary.json")
    if os.path.exists(cpf):
        c = json.load(open(cpf))
        res["cpuprof"] = {"profiles": c["profiles"], "total_s": c["total_s"], "engine_self_s": c["engine_self_s"],
                          "top_engine": c["top_engine"][:8], "top": c["top"][:8]}
    return res


def lanes(base, rnd=3):
    """From the baseline timed traces (header meta.parallel, original machine): where the par wall goes."""
    rows = table.rows_of(base)
    wall = {(r["repo"], r["rep"], r["workers"]): r["wall_s"] for r in rows if r["kind"] == "par"}
    print(f"| repo | w | par wall | outside lanes | lanes wall | plan makespan | sum of file s / w | waited s (sum) | together groups | plan excess (makespan - sum/w) | runtime excess (lanes - makespan) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for repo in table.POOL:
        for w in table.WORKERS:
            p = os.path.join(base, repo, f"P{rnd}w{w}.jsonl")
            if not os.path.exists(p):
                continue
            with open(p) as f:
                h = json.loads(f.readline())
            P = h["meta"].get("parallel") or {}
            t, pl = P.get("timing") or {}, P.get("plan") or {}
            W = wall.get((repo, rnd, w))
            if not pl or t.get("lanes_wall_seconds") is None:
                print(f"| {repo} | {w} | {W:.1f} | - | - | - | - | - | - | refused: {(P.get('requested') or {}).get('refused')} | - |")
                continue
            lw, mk, ideal = t["lanes_wall_seconds"], float(pl["makespan"]), t["test_file_seconds"] / w
            print(f"| {repo} | {w} | {W:.1f} | {W - lw:.1f} | {lw:.1f} | {mk:.1f} | {ideal:.1f} | {P['placement']['waited_seconds']:.1f} | "
                  f"{len(pl.get('together') or [])} | {mk - ideal:.1f} | {lw - mk:.1f} |")


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if a[:1] == ["lanes"]:
        return lanes(a[1] if len(a) > 1 else os.path.join(HERE, "data", "baseline"))
    opt = lambda k, dflt: a[a.index(k) + 1] if k in a else dflt
    base = opt("--base", os.path.join(HERE, "data", "baseline"))
    pb = opt("--phaseb", os.path.join(HERE, "data", "phaseB"))
    names = [n for n in table.POOL if os.path.isdir(os.path.join(pb, n))]
    out = [repo(base, pb, n) for n in names]
    if "--json" in a:
        with open(opt("--json", None), "w") as f:
            json.dump(out, f, indent=1)
    f = lambda x: "-" if x is None else (f"{x:.2f}" if isinstance(x, float) else str(x))
    print("| repo | w | wall | launch | pass | pre | window (ideal + idle) | post (deps_hash, trace_write) | files / processes | io_release (held s) | stack captures |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in out:
        if r.get("missing"):
            print(f"| {r['repo']} | missing |")
            continue
        for k, p in r["passes"].items():
            print(f"| {r['repo']} | {p['workers']} | {f(r['run']['wall_s'])} | {f(r['run']['launch_s'])} | {k} | {f(p['pre_s'])} | "
                  f"{f(p['window_s'])} ({f(p['ideal_s'])} + {f(p.get('idle_s'))}) | {f(p['post_s'])} ({f(p['deps_hash_s'])}, {f(p['trace_write_s'])}) | "
                  f"{p['files']} / {p['processes']} | {p['io_release']} ({f(p['held_s'])}) | {p['stack_captures']} |")


if __name__ == "__main__":
    main()
