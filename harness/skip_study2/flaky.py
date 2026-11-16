#!/usr/bin/env python3
"""Rerun measurement: run a project's own CI test step once, at a pinned commit, on a fresh GitHub-hosted
runner, and record the job outcome, its minutes and the failing tests. The workflow runs this N times per
test group; aggregate.py turns the attempts into a flaky job rate (a group that fails in some attempts and
passes in others at the same commit) and wasted minutes.

    python flaky.py --spec specs/vue-core.json --sha <commit> --group 1/1 --rep 0 --work /tmp/f --out x.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import walk  # noqa: E402

T0 = time.time()


def failures(kind, report: Path, out: str):
    fails, n = [], 0
    try:
        if kind == "junit":
            root = ET.parse(report).getroot()
            for tc in root.iter("testcase"):
                n += 1
                if tc.find("failure") is not None or tc.find("error") is not None:
                    fails.append(f"{tc.get('classname')}::{tc.get('name')}")
        elif kind == "vitest":
            d = json.loads(report.read_text())
            for f in d.get("testResults", []):
                for a in f.get("assertionResults", []):
                    n += 1
                    if a.get("status") == "failed":
                        fails.append(f"{f.get('name', '')}::{a.get('fullName') or a.get('title')}")
                if f.get("status") == "failed" and not f.get("assertionResults"):
                    fails.append(f"{f.get('name', '')}::<file>")
        elif kind == "go":
            for line in report.read_text(errors="replace").splitlines():
                if not line.startswith("{"):
                    continue
                ev = json.loads(line)
                if ev.get("Action") in ("pass", "fail", "skip") and ev.get("Test"):
                    n += 1
                if ev.get("Action") == "fail":
                    fails.append(f"{ev.get('Package')}::{ev.get('Test') or '<package>'}")
    except Exception as e:  # report missing or truncated
        return None, 0, f"report unreadable: {e}"
    return sorted(set(fails)), n, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--sha", required=True)
    ap.add_argument("--group", default="1/1")
    ap.add_argument("--rep", type=int, default=0)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text())
    spec["seq"] = {"kind": "list", "commits": [a.sha]}
    w = walk.Walker(spec, a.work, a.out, 0, 1, 1e9, "flaky")
    g, ng = (int(x) for x in a.group.split("/"))
    res = {"name": spec["name"], "sha": a.sha, "group": g, "groups": ng, "rep": a.rep,
           "runner": os.environ.get("RUNNER_NAME", ""), "cpus": os.cpu_count()}
    w.commits()
    git_fetch = walk.sh(["git", "fetch", "--quiet", "--filter=blob:none", "origin", a.sha], cwd=w.src, timeout=900)
    w.checkout(a.sha)
    t = time.time()
    if spec["lang"] == "go":
        env = w.env()
        walk.sh(["go", "mod", "download"], cwd=w.src, env=env, timeout=1800)
        ok = True
    else:
        ok, why = w.install()
        if not ok:
            res["status"] = "install-failed"
            res["detail"] = why[-1500:]
    res["install_s"] = time.time() - t
    if ok:
        t = time.time()
        ok = w.build()
        res["build_s"] = time.time() - t
        if not ok:
            res["status"] = "build-failed"
    if ok:
        report = w.work / f"report-{g}.out"
        cmd = w.fmt(spec["ci_cmd"]).replace("{group}", str(g)).replace("{groups}", str(ng)).replace(
            "{report}", str(report))
        env = w.env()
        env.pop("PYTHONPATH", None)  # no study hooks: the plain CI step
        env.update(spec.get("ci_env", {}))
        if spec["lang"] == "go":
            env["GOFLAGS"] = spec.get("goflags", "-mod=mod")
        code, out, wall = walk.sh(cmd, cwd=w.src, env=env, timeout=spec.get("ci_timeout", 3 * 3600), shell=True)
        fails, n, err = failures(spec["ci_report"], report, out)
        res.update(status="ok", exit=code, test_wall_s=wall, tests=n, failed_tests=(fails or [])[:200],
                   n_failed=len(fails or []), report_error=err, tail=out[-3000:] if code else "")
    res["job_s"] = time.time() - T0
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1))
    if os.environ.get("S2_COMMIT"):
        walk.commit_results([Path(a.out)], f"Skip study 2 (reruns): {spec['name']} group {g} rep {a.rep}")
    print(json.dumps({k: v for k, v in res.items() if k != "tail"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
