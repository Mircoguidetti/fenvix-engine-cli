#!/usr/bin/env python3
"""L1 study harness: async flaky tests under --det and --det --det-async.

Per project of ``harness/l1/corpus.json`` (one GitHub Actions job each):

1. prepare: clone at the pinned commit (or use the local path), venv, install
   (same install heuristics as ``detpy_harness.py``), install the detpy wheel;
2. on the corpus tests of the project, in one pytest invocation per run,
   fixed collection order, serial:
   * ``baseline``: N normal runs (no detpy flags);
   * ``det``: N runs with ``--det``;
   * ``calm``: N runs with ``--det --det-async`` (seed 0, the calm profile);
   * ``explore``: one run per seed 1..S with ``--det --det-async --det-async-seed=s``;
   * ``confirm``: for every test that failed with some seed, its first failing
     seed is re-run until ``confirm`` runs in total; reproduced = all fail;
     traces of the confirm runs are compared by the verifier (same fingerprint);
3. slowdown: the full suite (``suite_args``), serial, alternating ``--det``,
   ``--det --det-async`` (seed 0) and ``--det --det-async --det-async-seed=1``,
   ``timing_runs`` runs each; wall time per run.

Output: ``<out>/<name>.json``. ``--aggregate`` merges them into a Markdown
report and CSVs.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

import detpy_harness as H  # noqa: E402  (prepare, clean_env, sh)

CORPUS = ROOT / "harness" / "l1" / "corpus.json"
FAIL = ("failed", "error")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def is_fail(outcome: str | None) -> bool:
    return bool(outcome) and outcome.split("+", 1)[0] in FAIL or "teardown-error" in (outcome or "")


def clone(project: dict, src: Path) -> str:
    if project.get("local"):
        shutil.rmtree(src, ignore_errors=True)
        shutil.copytree(ROOT / project["local"], src)
        subprocess.run(["git", "init", "-q"], cwd=src)
        return "local"
    if not (src / ".git").exists():
        subprocess.run(["git", "clone", "-q", "--filter=blob:none", project["url"], str(src)], check=True, timeout=900)
    if project.get("sha"):
        subprocess.run(["git", "checkout", "-q", project["sha"]], cwd=src, check=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True).stdout.strip()


def pytest_run(p, args: list, out_json: Path, timeout: float, trace: Path | None = None) -> dict:
    cmd = [p.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", "-p", "no:xdist",
           f"--det-outcomes={out_json}", *p.pytest_args, *args]
    if trace is not None:
        cmd.append(f"--det-trace={trace}")
    out_json.unlink(missing_ok=True)
    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=p.src, env=H.clean_env(p.python, p.env), capture_output=True, text=True,
                              timeout=timeout)
        code, tail, timed_out = proc.returncode, (proc.stdout + proc.stderr)[-1500:], False
    except subprocess.TimeoutExpired as e:
        code, tail, timed_out = -9, str(e.stdout or "")[-1500:], True
    dur = time.monotonic() - t0
    outcomes = {}
    if out_json.exists():
        try:
            outcomes = json.loads(out_json.read_text()).get("outcomes", {})
        except Exception:
            pass
    return {"args": args, "exit": code, "duration_s": round(dur, 3), "timed_out": timed_out, "outcomes": outcomes,
            "tail": tail if (code not in (0, 1) or timed_out) else ""}


def measure(project: dict, args) -> dict:
    work = Path(args.work)
    src = work / "src" / project["name"]
    src.parent.mkdir(parents=True, exist_ok=True)
    res = {"name": project["name"], "url": project.get("url", ""), "source": project.get("source", ""),
           "tests": project["tests"], "executor": args.executor, "runner": platform.node(),
           "python_requested": project.get("python")}
    try:
        res["commit"] = clone(project, src)
    except Exception as e:
        res["status"] = f"clone-failed: {e}"
        return res
    repo = {"name": project["name"], "url": project.get("url", ""), "kind": "flaky", "sha": "",
            "python": project.get("python"), "install": project.get("install", []),
            "pytest_args": project.get("pytest_args", []), "env": project.get("env", {})}
    p = H.prepare(repo, work, args.wheel, "3.13", 100000)
    res.update(status=p.status, detail=p.detail, python=p.python_version, install=p.install_cmd,
               collected=p.collected)
    if p.status != "ok":
        log(f"{p.name}: {p.status} {p.detail[-300:]}")
        return res
    nodeids = list(project["tests"])
    rd = work / "runs" / p.name
    rd.mkdir(parents=True, exist_ok=True)
    tmo = args.run_timeout
    runs = res["runs"] = []

    def go(mode, flags, i, seed=None, trace=None):
        r = pytest_run(p, nodeids + flags, rd / f"{mode}-{seed}-{i}.json", tmo, trace)
        r.update(mode=mode, seed=seed, run=i)
        runs.append(r)
        fails = sum(is_fail(r["outcomes"].get(n)) for n in nodeids)
        log(f"{p.name} {mode} seed={seed} run={i}: {r['duration_s']}s exit={r['exit']} failing={fails}/{len(nodeids)}")
        return r

    for i in range(args.runs):  # interleaved, so load changes hit all modes alike
        go("baseline", [], i)
        go("det", ["--det"], i)
        go("calm", ["--det", "--det-async"], i)
    first_fail, first_pass = {}, {}
    for s in range(1, args.seeds + 1):
        r = go("explore", ["--det", "--det-async", f"--det-async-seed={s}"], 0, s,
               trace=rd / f"explore-{s}.jsonl")
        for n in nodeids:
            o = r["outcomes"].get(n)
            if is_fail(o):
                first_fail.setdefault(n, s)
            elif o in ("passed", "xfailed", "skipped"):
                first_pass.setdefault(n, s)
    by_seed = collections.defaultdict(list)
    for n, s in first_fail.items():
        by_seed[s].append(n)
    confirm = res["confirm"] = {}
    for s, tests in sorted(by_seed.items()):
        traces = [rd / f"explore-{s}.jsonl"]
        outs = [next(r for r in runs if r["mode"] == "explore" and r["seed"] == s)["outcomes"]]
        for i in range(1, args.confirm):
            t = rd / f"confirm-{s}-{i}.jsonl"
            r = go("confirm", ["--det", "--det-async", f"--det-async-seed={s}"], i, s, trace=t)
            traces.append(t)
            outs.append(r["outcomes"])
        verdict = {}
        try:
            v = json.loads(subprocess.run([p.python, "-c", "import sys,detpy._core as c; print(c.verify(sys.argv[1:]))",
                                           *map(str, traces)], capture_output=True, text=True, timeout=300).stdout)
            verdict = {t["nodeid"]: t for t in v["tests"]}
        except Exception as e:
            log(f"verify failed: {e}")
        for n in tests:
            fails = sum(is_fail(o.get(n)) for o in outs)
            vt = verdict.get(n, {})
            d = vt.get("divergence") or {}
            confirm[n] = {"seed": s, "fails": fails, "runs": len(outs), "reproduced": fails == len(outs),
                          "passing_seed": first_pass.get(n), "fingerprint": vt.get("status"),
                          "divergence": d.get("description", "")[:300]}
    # Slowdown on the full suite.
    timing = res["timing"] = []
    suite = project.get("suite_args", [])
    if args.timing_runs:
        for i in range(args.timing_runs):
            for mode, flags in (("det", ["--det"]), ("det-async", ["--det", "--det-async"]),
                                ("det-async-s1", ["--det", "--det-async", "--det-async-seed=1"])):
                r = pytest_run(p, suite + flags, rd / f"suite-{mode}-{i}.json", args.suite_timeout)
                c = collections.Counter(o.split("+", 1)[0] for o in r["outcomes"].values())
                timing.append({"mode": mode, "run": i, "duration_s": r["duration_s"], "exit": r["exit"],
                               "timed_out": r["timed_out"], "counts": dict(c), "tail": r["tail"][-600:]})
                log(f"{p.name} suite {mode} run={i}: {r['duration_s']}s {dict(c)}")
    for r in runs:
        r["outcomes"] = {n: r["outcomes"].get(n, "missing") for n in nodeids}
    return res


# ---------------------------------------------------------------------------
def hist(outs: list) -> str:
    c = collections.Counter(outs)
    return ";".join(f"{k}={v}" for k, v in sorted(c.items()))


def aggregate(indir: Path, outdir: Path, meta: dict) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    rows, projects = [], []
    for f in sorted(indir.rglob("*.json")):
        try:
            r = json.loads(f.read_text())
        except Exception:
            continue
        if "tests" not in r or "status" not in r:
            continue
        projects.append(r)
        if r["status"] != "ok":
            continue
        for n, cat in r["tests"].items():
            per = collections.defaultdict(list)
            for run in r["runs"]:
                per[run["mode"]].append(run["outcomes"].get(n, "missing"))
            b, d, c, e = per["baseline"], per["det"], per["calm"], per["explore"]
            cf = r.get("confirm", {}).get(n, {})
            rows.append({
                "project": r["name"], "nodeid": n, "category": cat,
                "uvloop": "uvloop" in n,
                "baseline": hist(b), "baseline_flaky": len(set(b)) > 1, "baseline_fail_rate": round(
                    sum(map(is_fail, b)) / len(b), 3) if b else None,
                "det": hist(d), "det_stable": len(set(d)) == 1,
                "calm": hist(c), "calm_stable": len(set(c)) == 1,
                "explore": hist(e), "seeds_failing": sum(map(is_fail, e)),
                "repro_seed": cf.get("seed"), "confirm": f"{cf.get('fails', 0)}/{cf.get('runs', 0)}" if cf else "",
                "reproduced": bool(cf.get("reproduced")), "passing_seed": cf.get("passing_seed"),
                "reproducible": bool(cf.get("reproduced")) and cf.get("passing_seed") is not None,
                "fingerprint": cf.get("fingerprint", ""), "divergence": cf.get("divergence", ""),
            })
    import csv

    if rows:
        with open(outdir / "tests.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    timing = []
    for r in projects:
        by = collections.defaultdict(list)
        for t in r.get("timing", []):
            if not t["timed_out"] and t["exit"] in (0, 1):
                by[t["mode"]].append(t["duration_s"])
        if by.get("det") and by.get("det-async"):
            md = statistics.median(by["det"])
            row = {"project": r["name"], "det_median_s": round(md, 2),
                   "det_async_median_s": round(statistics.median(by["det-async"]), 2),
                   "det_async_s1_median_s": round(statistics.median(by["det-async-s1"]), 2) if by.get("det-async-s1") else None,
                   "runs": len(by["det"])}
            row["slowdown_calm_pct"] = round(100 * (row["det_async_median_s"] / md - 1), 1) if md else None
            row["slowdown_s1_pct"] = (round(100 * (row["det_async_s1_median_s"] / md - 1), 1)
                                      if md and row["det_async_s1_median_s"] else None)
            counts = {t["mode"]: t["counts"] for t in r.get("timing", []) if t["run"] == 0}
            row["suite_counts"] = counts
            timing.append(row)
    summary = {"meta": meta, "projects": [{k: p.get(k) for k in ("name", "status", "detail", "python", "commit",
                                                                    "collected", "source")} for p in projects],
               "tests": rows, "timing": timing}
    (outdir / "summary.json").write_text(json.dumps(summary, indent=1))
    (outdir / "REPORT.md").write_text(report(summary))


def report(s: dict) -> str:
    rows = s["tests"]
    L = ["# L1 study: async flaky tests under `--det` and `--det --det-async`", "",
         f"Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}. {s['meta'].get('protocol', '')}", "",
         f"Run: {s['meta'].get('run_url', '')}", "", "## Projects", "",
         "| project | source | status | python | commit | corpus tests |", "|---|---|---|---|---|---|"]
    for p in s["projects"]:
        n = sum(1 for r in rows if r["project"] == p["name"])
        L.append(f"| {p['name']} | {p.get('source', '')} | {p['status']} {('(' + (p.get('detail') or '')[:80] + ')') if p['status'] != 'ok' else ''} "
                 f"| {p.get('python') or ''} | {(p.get('commit') or '')[:12]} | {n} |")

    def block(title, sel):
        sel = list(sel)
        if not sel:
            return
        bf = [r for r in sel if r["baseline_flaky"]]
        L.extend(["", f"## {title}", "",
                  f"* tests: {len(sel)}; flaky in the baseline: {len(bf)}",
                  f"* `--det` only: stable outcome {sum(r['det_stable'] for r in sel)}/{len(sel)}; "
                  f"of the baseline-flaky ones {sum(r['det_stable'] for r in bf)}/{len(bf)}",
                  f"* `--det --det-async` (calm, seed 0): stable outcome {sum(r['calm_stable'] for r in sel)}/{len(sel)}",
                  f"* reproduced with a seed (10/10) and passing with another: {sum(r['reproducible'] for r in sel)}/{len(sel)}; "
                  f"of the baseline-flaky ones {sum(r['reproducible'] for r in bf)}/{len(bf)}",
                  f"* failing with every explored seed (possible false failures or always-failing): "
                  f"{sum(1 for r in sel if r['explore'] and all(k.split('=')[0].split('+')[0] in FAIL for k in r['explore'].split(';')))}"])

    block("All corpus tests (uvloop parametrisations excluded)", (r for r in rows if not r["uvloop"]))
    block("uvloop parametrisations (not covered by the prototype: uvloop is not a BaseEventLoop)",
          (r for r in rows if r["uvloop"]))
    for proj in sorted({r["project"] for r in rows}):
        block(f"Project {proj}", (r for r in rows if r["project"] == proj and not r["uvloop"]))
    L.extend(["", "## Per test", "", "| project | test | cat. | baseline | --det | calm | explore (20 seeds) | repro seed | confirm | passing seed | fingerprint |",
              "|---|---|---|---|---|---|---|---|---|---|---|"])
    for r in rows:
        L.append(f"| {r['project']} | `{r['nodeid'][-90:]}` | {r['category']} | {r['baseline']} | {r['det']} | {r['calm']} | "
                 f"{r['explore']} | {r['repro_seed'] or ''} | {r['confirm']} | {r['passing_seed'] or ''} | {r['fingerprint']} |")
    if s["timing"]:
        L.extend(["", "## Slowdown on the full suites (serial)", "",
                  "Medians of the runs; `--det` vs `--det --det-async` (calm) vs `--det --det-async --det-async-seed=1`. "
                  "MEASURED on GitHub-hosted runners, one dedicated job per project (shared cloud hardware: NOISY for small differences).", "",
                  "| project | runs | --det s | --det-async s | slowdown | seed 1 s | slowdown | outcomes (run 0) |", "|---|---|---|---|---|---|---|---|"])
        for t in s["timing"]:
            L.append(f"| {t['project']} | {t['runs']} | {t['det_median_s']} | {t['det_async_median_s']} | {t['slowdown_calm_pct']}% | "
                     f"{t['det_async_s1_median_s']} | {t['slowdown_s1_pct']}% | {json.dumps(t['suite_counts'])} |")
    return "\n".join(L) + "\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", help="corpus project name (measure mode)")
    ap.add_argument("--list", action="store_true", help="print the project names as a JSON list")
    ap.add_argument("--aggregate", metavar="DIR", help="merge <DIR>/**/*.json into --out")
    ap.add_argument("--corpus", default=str(CORPUS))
    ap.add_argument("--wheel", default="")
    ap.add_argument("--work", default="/tmp/l1work")
    ap.add_argument("--out", default="out")
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--confirm", type=int, default=10)
    ap.add_argument("--timing-runs", type=int, default=3)
    ap.add_argument("--run-timeout", type=float, default=900)
    ap.add_argument("--suite-timeout", type=float, default=2400)
    ap.add_argument("--executor", default="local")
    ap.add_argument("--run-url", default="")
    a = ap.parse_args(argv)
    corpus = json.loads(Path(a.corpus).read_text())["projects"]
    if a.list:
        print(json.dumps([p["name"] for p in corpus]))
        return
    if a.aggregate:
        aggregate(Path(a.aggregate), Path(a.out), {
            "run_url": a.run_url,
            "protocol": (f"Per project: {a.runs} baseline / --det / --det --det-async (seed 0) runs of the corpus tests, "
                         f"interleaved, serial, fixed collection order; exploration with --det-async-seed=1..{a.seeds} "
                         f"(test order fixed); {a.confirm}/{a.confirm} confirmation of the first failing seed; "
                         f"{a.timing_runs} timed runs of the full suite per mode.")})
        return
    if a.wheel:
        a.wheel = str(Path(a.wheel).resolve())  # installs run with the project as cwd
    project = next(p for p in corpus if p["name"] == a.project)
    res = measure(project, a)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / f"{project['name']}.json").write_text(json.dumps(res, indent=1))
    log(f"wrote {a.out}/{project['name']}.json")


if __name__ == "__main__":
    main()
