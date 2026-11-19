#!/usr/bin/env python3
"""Round-2 no-code reds on real projects (kind c, added mechanisms).

Round 1's 14 "no-code reds" were 7 environment changes from 4 mechanisms plus 7 data-edit commits (review R-019
M6), and none of time zone, locale, file permission or runner image was ever the culprit. This driver adds CI
environment changes of those kinds where a real suite breaks under them:

    scan: run the project's suite (plain pytest) at the red commit once per candidate change, alone: a test that
          fails with the change and passes without it is a candidate red test for that change (checked again at
          green and under --det when the case is built).
    case: green = HEAD~8 (green environment), red = HEAD with the change (red environment), same virtualenv
          (nothing installed differs). Decoys: none, and a second variable that lands with the change and is
          checked not to break the test (TZ=Asia/Kolkata, or COLUMNS=100 when the change is the time zone).
          Truth: env:<VAR>. Baseline: git bisect run with plain pytest in the red environment.

    nocode2.py scan --project N --repo DIR --venv DIR --out scan.json
    nocode2.py case --scan scan.json --project N --repo DIR --venv DIR --out results.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import checkout, git, git_bisect, run_det, run_plain  # noqa: E402
from finder import Finder  # noqa: E402
from mutants import failed_ids  # noqa: E402

CHANGES = {  # name: (variables the red job sets, kind, what)
    "tz": ({"TZ": "America/Los_Angeles"}, "time zone", "the runner's time zone is America/Los_Angeles, not UTC"),
    "locale": ({"LC_ALL": "POSIX"}, "locale", "the runner image sets LC_ALL=POSIX"),
    "lang": ({"LANG": "C.UTF-8"}, "locale", "the runner image sets LANG=C.UTF-8"),
    "no-color": ({"NO_COLOR": "1"}, "env var", "the CI job sets NO_COLOR=1"),
    "force-color": ({"FORCE_COLOR": "1"}, "env var", "the CI job sets FORCE_COLOR=1"),
    "term": ({"TERM": "dumb"}, "env var", "the runner's TERM is dumb"),
    "columns": ({"COLUMNS": "40"}, "env var", "the runner's terminal is 40 columns wide"),
    "ci": ({"CI": "true"}, "env var", "the CI job sets CI=true"),
    "optimize": ({"PYTHONOPTIMIZE": "1"}, "interpreter option", "the CI job sets PYTHONOPTIMIZE=1"),
    "devmode": ({"PYTHONDEVMODE": "1"}, "interpreter option", "the CI job sets PYTHONDEVMODE=1"),
    "ioenc": ({"PYTHONIOENCODING": "latin-1"}, "interpreter option", "the CI job sets PYTHONIOENCODING=latin-1"),
    "home": ({"HOME": "/nonexistent"}, "runner image", "the runner image has no home directory"),
    "language": ({"LANGUAGE": "de"}, "locale", "the runner image sets LANGUAGE=de"),
}
PLAIN = ["-q", "--tb=no", "-rfE", "-p", "no:randomly"]


def window(repo):
    head = git(repo, "rev-parse", "origin/HEAD")
    fp = git(repo, "rev-list", "--first-parent", "--max-count=9", head).split()
    return fp[-1], head


def failing(repo, venv, env) -> tuple[int, set]:
    """Failing test ids of one plain run; a module that fails to collect counts as all its tests."""
    code, out, _ = run_plain(repo, venv, PLAIN, extra_env=env, timeout=1800)
    ids = set()
    for t in failed_ids(out):
        if "::" in t:
            ids.add(t)
        else:
            _c, o2, _ = run_plain(repo, venv, ["-q", "--collect-only", "-p", "no:randomly", t], timeout=600)
            ids |= {x.strip() for x in o2.splitlines() if "::" in x and not x.startswith(("ERROR", "FAILED"))}
    return code, ids


def scan(a):
    """Each change alone, the whole suite (plain pytest) at the red commit: the tests it breaks."""
    repo, venv = Path(a.repo).resolve(), Path(a.venv).resolve()
    green, red = window(repo)
    checkout(repo, red)
    code0, base = failing(repo, venv, {})
    found, exits = {}, {"base": code0}
    if code0 in (0, 1):
        for name, (env, _k, _w) in CHANGES.items():
            code, ids = failing(repo, venv, env)
            exits[name] = code
            new = sorted(ids - base)
            if new:
                found[name] = new[:40]
            elif code not in (0, code0) and code0 == 0:
                # the whole session is red (e.g. a configuration warning turned error) and no test is: any test
                # of the suite is a red test of this change
                _c, out, _ = run_plain(repo, venv, ["-q", "--collect-only", "-p", "no:randomly"], timeout=600)
                tests = [x.strip() for x in out.splitlines() if "::" in x][:5]
                if tests:
                    found[name] = tests
                    found.setdefault("_session_red", []).append(name)
    res = {"project": a.project, "green": green, "red": red, "exit": exits, "by_change": found}
    json.dump(res, open(a.out, "w"), indent=1)
    print(a.project, {k: len(v) for k, v in found.items()}, "exit", exits, flush=True)


def case(a):
    repo, venv = Path(a.repo).resolve(), Path(a.venv).resolve()
    sc = json.load(open(a.scan))
    green, red = sc["green"], sc["red"]
    done = set()
    if os.path.exists(a.out):
        done = {json.loads(l)["id"] for l in open(a.out)}
    for name, tests in sorted(sc["by_change"].items()):
        if name.startswith("_"):
            continue
        env, kind, what = CHANGES[name]
        var = next(iter(env))
        pick = None
        for t in tests[:10]:
            checkout(repo, green)
            if run_det(repo, venv, t)["outcome"] != "pass":
                continue
            checkout(repo, red)
            if run_det(repo, venv, t)["outcome"] != "pass" or run_det(repo, venv, t, env)["outcome"] != "fail":
                continue
            pick = t
            break
        for decoy in ("none", "second"):
            cid = f"{a.project}-{name}-{decoy}"
            if cid in done:
                continue
            row = {"id": cid, "scenario": f"{a.project}-{name}", "kind": kind, "what": what, "truth": f"env:{var}",
                   "decoy": None, "round": 2, "session_red": name in sc["by_change"].get("_session_red", [])}
            if pick is None:
                row["skip"] = "no test that --det and plain pytest agree the change alone breaks"
                with open(a.out, "a") as fh:
                    fh.write(json.dumps(row) + "\n")
                continue
            red_env = dict(env)
            if decoy == "second":
                dv = {"COLUMNS": "100"} if var == "TZ" else {"TZ": "Asia/Kolkata"}
                checkout(repo, red)
                if run_det(repo, venv, pick, dv)["outcome"] != "pass":
                    row["skip"] = f"the decoy {dv} breaks the test"
                    with open(a.out, "a") as fh:
                        fh.write(json.dumps(row) + "\n")
                    continue
                red_env.update(dv)
                row["decoy"] = f"env:{next(iter(dv))}"
            green_env = {k: os.environ.get(k) for k in red_env}  # the green job inherits the runner default
            row["red_test"] = pick
            kd = Path(tempfile.mkdtemp(prefix="keys-c2-"))
            gk, rk = str(kd / "g.json"), str(kd / "r.json")
            checkout(repo, green)
            row["green_run"] = run_det(repo, venv, pick, green_env, keys=gk)["outcome"]
            checkout(repo, red)
            row["red_run"] = run_det(repo, venv, pick, red_env, keys=rk)["outcome"]
            f = Finder(repo, pick, {"sha": green, "env": green_env, "venv": venv, "key": gk},
                       {"sha": red, "env": red_env, "venv": venv, "key": rk})
            try:
                fr = f.run()
            except Exception as e:
                fr = {"culprit": None, "status": "error", "why": f"error: {type(e).__name__}: {e}",
                      "executions": len(f.steps), "steps": f.steps}
            c = fr.get("culprit") or {}
            named = c.get("commit") or c.get("input")
            row.update({"finder": fr, "finder_named": named, "finder_correct": named == row["truth"]})
            b = git_bisect(repo, venv, green, red, ["--tb=no", "-p", "no:randomly", pick], extra_env=red_env)
            row["bisect"] = b
            row["bisect_correct"] = False  # an input cannot be a commit
            with open(a.out, "a") as fh:
                fh.write(json.dumps(row) + "\n")
            print(f"{cid}: finder {named} {'OK' if row['finder_correct'] else 'WRONG' if named else 'UNKNOWN'} "
                  f"exec={fr.get('executions')} | bisect {b['named'] and b['named'][:10]}", flush=True)
    checkout(repo, git(repo, "rev-parse", "origin/HEAD"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["scan", "case"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--venv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scan")
    a = ap.parse_args()
    (scan if a.cmd == "scan" else case)(a)


if __name__ == "__main__":
    main()
