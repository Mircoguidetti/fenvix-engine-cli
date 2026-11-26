#!/usr/bin/env python3
"""P3 A, count-only repositories (coordinator 2026-11-25 21:56): after `pins.py find`, 2 whole-suite runs under
`detjs vitest run --det --det-workers=4`, then counts: serial --det cases per kind (cases.py) and parallel-only
failures (failed/error in a w4 run, passed in both plain runs and both w1 --det runs), each with its first failure line.

    PM_WORK=/tmp/pm-p3 python3 harness/p3_flips/count_extra.py run   --repo R --find /tmp/pm-p3/find
    python3 harness/p3_flips/count_extra.py count --repo R --find /tmp/pm-p3/find
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(HERE, "..", "det_pins"))
import pins  # noqa: E402
import measure  # noqa: E402
import cases  # noqa: E402


def run(o):
    spec = pins.load_spec(o.repo)
    cwd = os.path.expandvars(spec["dir"])
    out = os.path.join(o.find, o.repo)
    env = pins.base_env(o.repo, spec)
    for i in (1, 2):
        of, tf = f"{out}/par{i}.outcomes.json", f"{out}/par{i}.trace.jsonl"
        if os.path.exists(of):
            continue
        cmd = (["node", pins.DETJS, "vitest", "run"] + spec.get("args", []) +
               ["--det", "--det-workers=4", f"--det-outcomes={of}", f"--det-trace={tf}"])
        row, _ = pins.do_run(o.repo, "par", cmd, cwd, env, out, {"rep": i, "outcomes_file": of, "trace": tf})
        print(f"par{i} exit={row['exit']} {row['wall_s']}s", flush=True)


def count(o):
    spec = pins.load_spec(o.repo)
    cwd = os.path.expandvars(spec["dir"])
    d = os.path.join(o.find, o.repo)
    c = cases.build(d, cwd)
    plain = [{k: cases.norm(v) for k, v in measure.runner_outcomes(f"{d}/plain{i}.runner.json", cwd).items()} for i in (1, 2)]
    det = [{k: cases.norm(v) for k, v in pins.det_outcomes(f"{d}/det{i}.outcomes.json")[0].items()} for i in (1, 2)]
    par = [pins.det_outcomes(f"{d}/par{i}.outcomes.json") for i in (1, 2)]
    po = []
    for k in sorted(set(par[0][0]) | set(par[1][0])):
        p = [cases.norm(par[0][0].get(k)), cases.norm(par[1][0].get(k))]
        if "failed" in p and all(x.get(k) == "passed" for x in plain + det):
            exc = par[0][1].get(k) or par[1][1].get(k)
            po.append({"id": k, "par": p, "first": pins.first_line(exc)})
    runs = [json.loads(x) for x in open(f"{d}/runs.jsonl")]
    out = {"repo": o.repo, "engine_commit": pins.engine_commit(), "serial_counts": c["counts"],
           "n_unstable": c["n_unstable"], "n_parallel_only": len(po),
           "parallel_only_both_runs": sum(1 for x in po if x["par"] == ["failed", "failed"]),
           "runs": [{k: r.get(k) for k in ("kind", "rep", "exit", "wall_s", "cmd")} for r in runs],
           "serial_cases": c["cases"], "parallel_only": po}
    with open(f"{d}/count_extra.json", "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({k: out[k] for k in ("repo", "serial_counts", "n_unstable", "n_parallel_only", "parallel_only_both_runs")}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["run", "count"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--find", default="/tmp/pm-p3/find")
    o = ap.parse_args()
    {"run": run, "count": count}[o.phase](o)
