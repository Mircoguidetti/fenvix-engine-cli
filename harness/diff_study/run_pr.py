#!/usr/bin/env python3
"""Execution diff of one merged pull request.

Runs the suite under ``--det`` (seed 0, collection order) at the PR's base
commit twice and at its head (the merge result) twice, then compares the
per-test traces. Writes ``<out>/<repo>-<pr>.json.gz``:

* per test: outcomes of the 4 runs (base1, base2, head1, head2), the
  equivalence pattern of the 4 fingerprints under each site identity
  (``line`` = detpy's path:line, ``func_ord`` = function + call ordinal,
  ``func`` = function only, ``nosite`` = site dropped), probe patterns;
* per diverging test (base1 vs head1): first diverging event and where it is.
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (SourceIndex, collect_args, first_divergence, git, install, is_informative, locate,  # noqa: E402
                    log, pattern, read_json, read_trace, run_det, sh, short_event, variant_fps, VARIANTS)

RUNS = ("base1", "base2", "head1", "head2")


def resolve_base(src: Path, head: str, pr_files: set, n_commits: int) -> tuple[str | None, str]:
    code, out = git(src, "rev-list", "--parents", "-n", "1", head)
    if code != 0:
        return None, "head-not-found"
    parents = out.split()[1:]
    if len(parents) == 2:
        return parents[0], "merge-commit"
    tried = []
    for k in dict.fromkeys([1, n_commits]):
        if k < 1:
            continue
        code, base = git(src, "rev-parse", f"{head}~{k}")
        if code != 0:
            continue
        base = base.strip()
        code, names = git(src, "diff", "--name-only", base, head)
        got = set(names.split())
        tried.append((k, len(got)))
        if got == pr_files:
            return base, f"squash-or-rebase(k={k})"
    return None, f"files-mismatch {tried} vs {len(pr_files)}"


def analyse(src: Path, shas: dict, runs: dict, changed: set) -> dict:
    traces = {r: read_trace(runs[r]["trace"])[1] for r in RUNS}
    probes = {r: read_json(runs[r]["probe"], {}) or {} for r in RUNS}
    idx = {"base": SourceIndex(src, shas["base"]), "head": SourceIndex(src, shas["head"])}
    all_ids = sorted(set().union(*[set(t) for t in traces.values()]))
    tests, divs = {}, {}
    for nid in all_ids:
        recs = [traces[r].get(nid) for r in RUNS]
        fps = {v: [] for v in VARIANTS}
        for r, rec in zip(RUNS, recs):
            if rec is None:
                for v in VARIANTS:
                    fps[v].append(None)
                continue
            vf = variant_fps(rec, idx[r[:4]])
            for v in VARIANTS:
                fps[v].append(vf[v])
        b1 = recs[0]
        info = sum(1 for e in b1["events"] if is_informative(e)) if b1 else None
        t = {
            "o": [rec["outcome"] if rec else None for rec in recs],
            "n": b1["n_events"] if b1 else None,
            "ni": info,
            "src": sorted(k for k, c in (b1 or {}).get("counts", {}).items() if k != "outcome"),
            "fp": {v: pattern(fps[v]) for v in VARIANTS},
            "trunc": any(rec and rec.get("truncated") for rec in recs),
        }
        pr = [probes[r].get(nid) for r in RUNS]
        t["probe"] = {k: pattern([p[k] if p else None for p in pr]) for k in ("calls", "rets")}
        t["probe"]["files"] = pattern([tuple(p["files"]) if p else None for p in pr])
        files = set()
        for p in (pr[0], pr[2]):
            if p:
                files.update(p["files"])
        t["runs_changed"] = bool(files & changed)
        t["n_rets"] = pr[0]["n_rets"] if pr[0] else None
        tests[nid] = t
        a, h = recs[0], recs[2]
        if a and h and a["fingerprint"] != h["fingerprint"]:
            if a.get("truncated") or h.get("truncated"):
                divs[nid] = {"loc": "beyond-stored-events"}
                continue
            i, ea, eb = first_divergence(a["events"], h["events"])
            only_site = (len(a["events"]) == len(h["events"]) and all(
                {k: v for k, v in x.items() if k != "at"} == {k: v for k, v in y.items() if k != "at"}
                for x, y in zip(a["events"], h["events"])))
            divs[nid] = {"i": i, "base": short_event(ea), "head": short_event(eb),
                         "loc": locate(ea, eb, changed), "site_only": only_site,
                         "n_base": len(a["events"]), "n_head": len(h["events"])}
    return {"tests": tests, "divergences": divs}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True, help="JSON of one PR, or prs.json with --index")
    ap.add_argument("--index", type=int, default=None)
    ap.add_argument("--work", default="/tmp/work")
    ap.add_argument("--wheel", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--python", default="3.12")
    ap.add_argument("--timeout", type=float, default=1200)
    a = ap.parse_args()
    a.wheel = str(Path(a.wheel).resolve())
    spec = json.loads(a.spec) if a.spec.strip().startswith("{") else json.loads(Path(a.spec).read_text())
    if a.index is not None:
        spec = spec["candidates"][a.index]
    key = f"{spec['repo']}-{spec['number']}"
    work = Path(a.work) / key
    shutil.rmtree(work, ignore_errors=True)
    src, rundir = work / "src", work / "runs"
    rundir.mkdir(parents=True)
    result = {"key": key, "spec": spec, "status": "pending", "runs": {}}
    out_path = Path(a.out) / f"{key}.json.gz"
    Path(a.out).mkdir(parents=True, exist_ok=True)

    def finish(status, detail=""):
        result["status"], result["detail"] = status, detail[-1500:]
        with gzip.open(out_path, "wt") as f:
            json.dump(result, f)
        log(f"{key}: {status} {detail[-300:]}")
        return 0

    code, out, _, _ = sh(["git", "clone", "--quiet", "--filter=blob:none", spec["url"], str(src)], timeout=900)
    if code != 0:
        return finish("clone-failed", out)
    git(src, "fetch", "--quiet", "origin", spec["merge_sha"])
    pr_files = set(spec["files"])
    base, how = resolve_base(src, spec["merge_sha"], pr_files, spec.get("commits", 1))
    if base is None:
        return finish("base-not-resolved", how)
    shas = {"base": base, "head": spec["merge_sha"]}
    code, names = git(src, "diff", "--name-only", base, spec["merge_sha"])
    changed = set(names.split())
    result.update(shas=shas, base_how=how, changed=sorted(changed))
    venv = work / "venv"
    py = str(venv / "bin" / "python")
    code, out, _, _ = sh(["uv", "venv", "--quiet", "--python", a.python, str(venv)], timeout=600)
    if code != 0:
        return finish("venv-failed", out)
    args = None
    for side in ("base", "head"):
        git(src, "checkout", "--quiet", "--force", shas[side])
        git(src, "clean", "-fdxq", "-e", ".venv")
        ok, how_inst = install(src, py, a.wheel, spec.get("install", []), rundir / f"install-{side}.log")
        if not ok:
            return finish(f"install-failed-{side}", how_inst)
        result[f"install_{side}"] = how_inst
        args, n, out = collect_args(py, src, spec.get("pytest_args", []))
        if args is None:
            return finish(f"collect-failed-{side}", out)
        result[f"collected_{side}"] = n
        result["pytest_args"] = args
        for i in (1, 2):
            tag = f"{side}{i}"
            r = run_det(py, src, rundir, tag, args, a.timeout)
            result["runs"][tag] = {k: r[k] for k in ("exit", "duration_s", "timed_out")}
            log(f"{key}: {tag} exit={r['exit']} {r['duration_s']}s")
            result["runs"][tag]["paths"] = r
        if side == "base":
            meta = read_trace(rundir / "base1.jsonl")[0]
            result["meta"] = {k: meta.get(k) for k in ("hashseed", "reexec", "bytecode", "python", "aslr_disabled")}
    runs = {t: result["runs"][t]["paths"] for t in RUNS}
    if any(not Path(runs[t]["trace"]).exists() for t in RUNS):
        return finish("trace-missing", json.dumps({t: result["runs"][t]["exit"] for t in RUNS}))
    git(src, "checkout", "--quiet", "--force", shas["head"])
    result.update(analyse(src, shas, runs, changed))
    for t in RUNS:
        result["runs"][t].pop("paths", None)
    return finish("ok")


if __name__ == "__main__":
    sys.exit(main())
