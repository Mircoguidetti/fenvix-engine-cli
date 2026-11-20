#!/usr/bin/env python3
"""Round-2 real-history cases (kind b): commits the project itself reverted.

For a revert R of commit X (``This reverts commit X``), both brought into the default branch's first-parent chain
by first-parent commits FX (older) and FR:

1. run the tests at FX^ and at FX (plain pytest, ``-p no:randomly``, no bytecode, today's environment of the
   project) and keep tests that pass at FX^ and fail at FX: X broke them;
2. keep a test only if it still fails at FR^ (the red head: the breakage was still there when the project reverted);
3. green = a commit m first-parent commits before FX (m drawn in 0..8; the test must pass there), so the culprit is
   not always the oldest commit of the range (review R-019 H5);
4. truth: walk back from FR^ one first-parent commit at a time (plain pytest) to the first pass. ``--det`` must
   agree at the truth and its parent. The truth is usually FX; when it is not, the row says so.

Which tests run in step 1: test files X or R touch, and test files named after a source module X touches; the
whole suite when there are none. A commit that today's environment cannot run is recorded (old environment).

    realrevert.py --reverts reverts.json --project NAME --repo DIR --venv DIR --out cases.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import checkout, git, run_det, run_plain  # noqa: E402
from mutants import failed_ids  # noqa: E402
from placed import plain_outcome, walk_truth  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from detpy_harness import detect_install  # noqa: E402

WHEEL = os.environ.get("CULPRIT_WHEEL", "/home/user/work/wheels/detpy-0.1.0-cp39-abi3-manylinux_2_34_x86_64.whl")
EXTRA = {r["name"]: r.get("install", []) for r in json.load(open(Path(__file__).resolve().parents[2] / "repos.json"))["popular"]}


def period_venv(repo, sha, project, root: Path, python="3.12") -> tuple[Path | None, str]:
    """A virtualenv for an old commit: the project's test dependencies resolved as of the commit's date
    (``uv --exclude-newer``), the oldest interpreter --det-cache supports (3.12), detpy, the project editable."""
    from common import sh
    date = git(repo, "log", "-1", "--format=%cs", sha)
    venv = root / f"{project}-{sha[:10]}"
    if (venv / ".ok").exists():
        return venv, date
    checkout(repo, sha)
    sh(["uv", "venv", "-q", "--clear", "--python", python, str(venv)], check=True)
    args, groups, reqs = detect_install(Path(repo))
    py = str(venv / "bin" / "python")
    cutoff = f"{date}T23:59:59Z"
    for extra in (groups + reqs, groups, reqs, []):
        code, out = sh(["uv", "pip", "install", "-q", "--python", py, "--exclude-newer", cutoff, *args, *extra,
                        "pytest", *EXTRA.get(project, [])], cwd=repo, timeout=1800)
        if code == 0:
            break
    else:
        return None, f"no install as of {date}: {out[-300:]}"
    code, out = sh(["uv", "pip", "install", "-q", "--python", py, "--no-deps", WHEEL], cwd=repo, timeout=600)
    if code != 0:
        return None, f"detpy: {out[-300:]}"
    (venv / ".ok").write_text(date)
    return venv, date

TESTDIR = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$")
SKIPDIR = re.compile(r"(^|/)(docs?|\.github|benchmarks?|examples?|scripts|tasks)/")


def changed(repo, sha):
    return [p for p in git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--first-parent",
                           sha).split() if p]


def test_targets(repo, x, r, at):
    files = set(changed(repo, x)) | set(changed(repo, r))
    tests = {f for f in files if f.endswith(".py") and TESTDIR.search(f)}
    stems = {Path(f).stem for f in files if f.endswith(".py") and not TESTDIR.search(f) and not SKIPDIR.search(f)
             and Path(f).stem != "__init__"}
    alltests = [f for f in git(repo, "ls-tree", "-r", "--name-only", at).split()
                if f.endswith(".py") and TESTDIR.search(f) and Path(f).name.startswith("test")]
    for f in alltests:
        if any(s in Path(f).stem for s in stems):
            tests.add(f)
    return sorted(t for t in tests if t in alltests)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reverts", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--venv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-revert", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--whole", action="store_true", help="always run the whole suite (second pass)")
    ap.add_argument("--period", default=None, help="directory for period virtualenvs (old commits)")
    a = ap.parse_args()
    repo, venv0 = Path(a.repo).resolve(), Path(a.venv).resolve()
    default = git(repo, "rev-parse", "origin/HEAD")
    fp = git(repo, "rev-list", "--first-parent", "--reverse", default).split()
    pos = {s: i for i, s in enumerate(fp)}
    done = set()
    if os.path.exists(a.out):
        done = {json.loads(l)["revert"] for l in open(a.out)}
    for rv in json.load(open(a.reverts)):
        if rv["repo"] != a.project or rv["r"] in done:
            continue
        x, r, fx, fr = rv["x"], rv["r"], rv["fx"], rv["fr"]
        row = {"revert": r, "reverted": x, "fx": fx, "fr": fr, "date": rv["date"], "repo": a.project}
        src = [f for f in changed(repo, x) if f.endswith(".py") and not TESTDIR.search(f) and not SKIPDIR.search(f)]
        if not src:
            row["dropped"] = "the reverted commit changes no source module"
            with open(a.out, "a") as fh:
                fh.write(json.dumps(row) + "\n")
            continue
        targets = [] if a.whole else test_targets(repo, x, r, fx)
        row["targets"] = targets or ["(whole suite)"]
        base = ["-q", "--tb=no", "-rfE", "-p", "no:randomly", *targets]
        res = {}
        venv = venv0
        for side, sha in (("before", fp[pos[fx] - 1]), ("after", fx)):
            checkout(repo, sha)
            code, out, secs = run_plain(repo, venv, base, timeout=a.timeout)
            res[side] = (code, failed_ids(out), round(secs, 1))
        row["exit"] = {k: v[0] for k, v in res.items()}
        venv = venv0
        if a.period and (res["before"][0] not in (0, 1) or res["after"][0] not in (0, 1)):
            pv, info = period_venv(repo, fx, a.project, Path(a.period))
            row["period_env"] = info if pv is None else f"resolved as of {info}, Python 3.12"
            if pv is not None:
                venv = pv
                for side, sha in (("before", fp[pos[fx] - 1]), ("after", fx)):
                    checkout(repo, sha)
                    code, out, secs = run_plain(repo, venv, base, timeout=a.timeout)
                    res[side] = (code, failed_ids(out), round(secs, 1))
                row["exit"] = {k: v[0] for k, v in res.items()}
        if res["before"][0] not in (0, 1) or res["after"][0] not in (0, 1):
            row["dropped"] = f"today's environment cannot run the old commits (exit {row['exit']})"
            with open(a.out, "a") as fh:
                fh.write(json.dumps(row) + "\n")
            print(f"{a.project} {r[:10]}: {row['dropped']}", flush=True)
            continue
        broke = sorted(t for t in res["after"][1] - res["before"][1] if "::" in t)
        row["broke"] = broke
        rng = random.Random(f"real-revert:{r}")
        cases = []
        for t in broke[: 6]:
            if len(cases) >= a.per_revert:
                break
            checkout(repo, fp[pos[fr] - 1])
            if plain_outcome(repo, venv, t) != "fail":
                continue
            m = rng.randint(0, 8)
            green = None
            for mm in range(m, -1, -1):
                g = fp[pos[fx] - 1 - mm]
                checkout(repo, g)
                if plain_outcome(repo, venv, t) == "pass":
                    green = g
                    break
            if green is None:
                continue
            rng_commits = fp[pos[green] + 1: pos[fr]]
            truth, runs, seen = walk_truth(repo, venv, green, rng_commits, t)
            case = {"id": f"{a.project}-rv-{r[:10]}-{len(cases)}", "repo": a.project, "kind": "b-revert",
                    "green": green, "red_head": rng_commits[-1], "head": default, "red_test": t, "k": len(rng_commits),
                    "range": rng_commits, "revert": r, "reverted": x, "fx": fx, "venv": str(venv), "truth_walk_runs": runs,
                    "truth_walk": seen}
            if truth is None:
                case["dropped"] = "walk found no pass->fail transition"
            else:
                case["planted"] = truth
                case["truth_position"] = rng_commits.index(truth) + 1
                case["truth_is_planted"] = truth == fx
                par = green if truth == rng_commits[0] else rng_commits[rng_commits.index(truth) - 1]
                checkout(repo, par)
                dp = run_det(repo, venv, t)["outcome"]
                checkout(repo, truth)
                dt = run_det(repo, venv, t)["outcome"]
                if (dp, dt) != ("pass", "fail"):
                    case["dropped"] = f"--det disagrees with plain at the truth: parent {dp}, truth {dt}"
            cases.append(case)
        row["cases"] = [c["id"] for c in cases if not c.get("dropped")]
        if not cases:
            row["dropped"] = "no test broken by the reverted commit is still red before the revert" if broke \
                else "no test broken by the reverted commit"
        with open(a.out, "a") as fh:
            fh.write(json.dumps(row) + "\n")
        with open(Path(a.out).with_name(Path(a.out).stem + "-cases.jsonl"), "a") as fh:
            for c in cases:
                fh.write(json.dumps(c) + "\n")
        print(f"{a.project} {r[:10]}: broke {len(broke)}, cases {row['cases']} {row.get('dropped', '')}", flush=True)
    checkout(repo, default)


if __name__ == "__main__":
    main()
