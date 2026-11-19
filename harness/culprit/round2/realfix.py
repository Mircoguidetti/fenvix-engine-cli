#!/usr/bin/env python3
"""Round-2 real-history cases (kind b, second source): regressions the project itself fixed.

For a first-parent commit F whose message says it fixes a regression and that changes test files T:

1. overlay T as of F on F^ (the bug still present) and on F; tests of T that fail at F^ and pass at F are the
   regression's tests (plain pytest, today's environment);
2. walk back from F^ one first-parent commit at a time, T overlaid, to the first pass (at most 60 commits): the
   commit after it is where the regression came in (the truth; found by the walk, not by the finder's oracle);
3. the case history: green = m commits before the truth (m drawn in 0..8, the test passes there), red = F^;
   every commit of (green, red] is replayed with T overlaid (as if the regression test had always been there),
   same messages and dates. ``--det`` must agree with plain pytest at the truth and its parent.

The bug, the culprit commit and the history are the project's own; only the test file is backported.

    realfix.py --project N --repo DIR --venv DIR --out cases.jsonl [--since 2021-01-01]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import checkout, git, git_out, run_det, run_plain  # noqa: E402
from mutants import commit, failed_ids  # noqa: E402

TESTFILE = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$")
PLAIN = ["-q", "--tb=no", "-rfE", "-p", "no:randomly"]
MAX_WALK = 200


def overlay(repo, fix, tests):
    """Put the test files of ``fix`` into the work tree (the checkout of an older commit)."""
    for t in tests:
        blob = subprocess.run(["git", "-C", str(repo), "show", f"{fix}:{t}"], capture_output=True).stdout
        p = Path(repo) / t
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(blob)
    from common import fresh_mtime
    fresh_mtime(repo, tests)


def outcome_at(repo, venv, sha, fix, tests, test) -> str:
    checkout(repo, sha)
    overlay(repo, fix, tests)
    code, _o, _ = run_plain(repo, venv, ["-q", "--tb=no", "-p", "no:randomly", test], timeout=600)
    return {0: "pass", 1: "fail"}.get(code, f"exit{code}")


def tree_overlaid(repo, sha, fix, tests) -> str:
    with tempfile.TemporaryDirectory() as td:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(td, "index")}
        subprocess.run(["git", "-C", str(repo), "read-tree", sha], env=env, check=True)
        for t in tests:
            line = git(repo, "ls-tree", fix, "--", t).split()
            subprocess.run(["git", "-C", str(repo), "update-index", "--add", "--cacheinfo",
                            f"{line[0]},{line[2]},{t}"], env=env, check=True)
        return subprocess.run(["git", "-C", str(repo), "write-tree"], env=env, capture_output=True, check=True,
                              text=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--venv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--since", default="2021-01-01")
    a = ap.parse_args()
    repo, venv = Path(a.repo).resolve(), Path(a.venv).resolve()
    default = git(repo, "rev-parse", "origin/HEAD")
    fp = git(repo, "rev-list", "--first-parent", "--reverse", default).split()
    pos = {s: i for i, s in enumerate(fp)}
    fixes = git(repo, "log", "--first-parent", "-i", "-E", "--grep=regress", f"--since={a.since}", "--format=%H",
                default).split()
    done = {json.loads(l)["fix"] for l in open(a.out)} if os.path.exists(a.out) else set()
    cases_out = Path(a.out).with_name(Path(a.out).stem + "-cases.jsonl")
    for fix in fixes:
        if fix in done or fix not in pos or pos[fix] < 2:
            continue
        files = git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--first-parent", fix).split()
        # overlaid: every file under the test directories the fix changes (test modules and test data such as
        # golden outputs); run: the test modules among them, or the whole suite when there are none
        tests = sorted(f for f in files if TESTFILE.search(f) and not f.endswith("conftest.py")
                       and git(repo, "ls-tree", fix, "--", f))
        targets = [t for t in tests if t.endswith(".py")]
        row = {"fix": fix, "repo": a.project, "subject": git(repo, "log", "-1", "--format=%s", fix), "overlay": tests}
        par = fp[pos[fix] - 1]
        if not tests:
            row["dropped"] = "the fix changes no test file"
        else:
            res = {}
            for side, sha in (("bug", par), ("fixed", fix)):
                checkout(repo, sha)
                overlay(repo, fix, tests)
                code, out, _ = run_plain(repo, venv, [*PLAIN, *targets], timeout=1200)
                res[side] = (code, failed_ids(out))
            row["exit"] = {k: v[0] for k, v in res.items()}
            regs = sorted(t for t in res["bug"][1] - res["fixed"][1] if "::" in t)
            row["regression_tests"] = regs
            if res["bug"][0] not in (0, 1) or res["fixed"][0] not in (0, 1):
                row["dropped"] = f"today's environment cannot run the commits (exit {row['exit']})"
            elif not regs:
                row["dropped"] = "no test fails before the fix and passes after it"
        cases = []
        for t in row.get("regression_tests", [])[:3] if "dropped" not in row else []:
            # walk back from F^ to the first pass
            seen, truth_i = [], None
            for j in range(pos[par], max(pos[par] - MAX_WALK, 0), -1):
                o = outcome_at(repo, venv, fp[j], fix, tests, t)
                seen.append((fp[j][:10], o))
                if o == "pass":
                    truth_i = j + 1
                    break
                if o != "fail":
                    break
            if truth_i is None:
                continue
            rng = random.Random(f"real-fix:{fix}:{t}")
            m = rng.randint(0, 8)
            green = None
            for mm in range(m, -1, -1):
                gi = truth_i - 1 - mm
                if gi >= 0 and outcome_at(repo, venv, fp[gi], fix, tests, t) == "pass":
                    green = fp[gi]
                    break
            if green is None:
                continue
            gi = pos[green]
            # replay (green, F^] with the regression test overlaid; green itself gets it too (a new green commit)
            g2 = commit(repo, tree_overlaid(repo, green, fix, tests), fp[gi - 1] if gi else green,
                        git_out(repo, "log", "-1", "--format=%B", green), green)
            prev, shas = g2, []
            for sha in fp[gi + 1: pos[par] + 1]:
                prev = commit(repo, tree_overlaid(repo, sha, fix, tests), prev,
                              git_out(repo, "log", "-1", "--format=%B", sha), sha)
                shas.append(prev)
            truth = shas[truth_i - gi - 1]
            cid = f"{a.project}-fx-{fix[:10]}-{len(cases)}"
            git(repo, "update-ref", f"refs/culprit2/{cid}", prev)
            case = {"id": cid, "repo": a.project, "kind": "b-fix", "green": g2, "red_head": shas[-1], "head": default,
                    "red_test": t, "k": len(shas), "range": shas, "fix": fix, "planted": truth,
                    "truth_original": fp[truth_i], "truth_position": shas.index(truth) + 1, "truth_walk": seen,
                    "venv": str(venv)}
            # independent check on the replayed history, and --det agreement at the truth
            checkout(repo, shas[-1])
            ok = run_plain(repo, venv, ["-q", "--tb=no", "-p", "no:randomly", t])[0] == 1
            checkout(repo, g2)
            ok = ok and run_plain(repo, venv, ["-q", "--tb=no", "-p", "no:randomly", t])[0] == 0
            parent = g2 if truth == shas[0] else shas[shas.index(truth) - 1]
            checkout(repo, parent)
            dp = run_det(repo, venv, t)["outcome"]
            checkout(repo, truth)
            dt = run_det(repo, venv, t)["outcome"]
            if not ok:
                case["dropped"] = "replayed history: red head not red or green not green (plain)"
            elif (dp, dt) != ("pass", "fail"):
                case["dropped"] = f"--det disagrees with plain at the truth: parent {dp}, truth {dt}"
            cases.append(case)
        row["cases"] = [c["id"] for c in cases if not c.get("dropped")]
        if "dropped" not in row and not row["cases"]:
            row["dropped"] = "no transition found within %d commits, or no green commit" % MAX_WALK
        with open(a.out, "a") as fh:
            fh.write(json.dumps(row) + "\n")
        with open(cases_out, "a") as fh:
            for c in cases:
                fh.write(json.dumps(c) + "\n")
        print(f"{a.project} {fix[:10]}: {row.get('dropped') or row['cases']}", flush=True)
    checkout(repo, default)


if __name__ == "__main__":
    main()
