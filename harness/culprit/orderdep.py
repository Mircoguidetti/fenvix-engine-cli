#!/usr/bin/env python3
"""Order-dependent defects (step 4): find the commit that introduced the polluter.

Input per case: a victim test that fails 10 of 10 times under one ``--det`` order (fixed collection order or
``--det-seed=S``) with every other Level 0 control disabled (the mixed round's order-only set).

Finder (deterministic, one run per step, ``--det`` with the given order):
1. one run of the full suite in the red order: the trace gives the executed order and confirms the red;
2. the victim alone (fails alone = brittle: not a polluter case, recorded);
3. polluter: binary split of the tests that ran before the victim, each step = (half + victim) in that order;
4. commit: the pair (polluter, victim) in that order, run at older first-parent commits: distances 1, 2, 4, ...
   until it passes (a missing test counts as a pass: no pollution without both tests), then binary search;
   a commit where the pair cannot run (collection error) is skipped like ``git bisect skip``.
Truth: every commit of the final bracket is run once more (deterministic) and the first failing one with a passing
parent is the transition; the named commit is also checked to add the polluter or the victim test (git log).

Baseline: ``git bisect run`` on the same bracket (same good commit, generous to the baseline) with plain pytest over
the full suite in random order (pytest-randomly, a new seed per run, as CI does); "bad" = the victim failed.
10 attempts per case.

    orderdep.py --repo-name NAME --out results.jsonl [--max-cases N]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ENGINE, base_env, checkout, git, sh  # noqa: E402

WORK = Path(os.environ.get("CULPRIT_WORK", "/home/user/work"))
WHEEL = os.environ.get("CULPRIT_WHEEL", str(next((WORK / "wheels2").glob("detpy-*.whl"), "")))
DISABLE = "seeds,time,fs,net,hashseed,bytecode"


def summary_of(name):
    import glob
    for f in sorted(glob.glob(str(ENGINE / "harness/results/*/" / f"{name}.summary.json")), reverse=True):
        return json.load(open(f))
    raise SystemExit(f"no summary for {name}")


def setup(name) -> tuple[Path, Path, dict]:
    s = summary_of(name)
    repo = WORK / "repos-d" / name
    if not repo.exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        sh(["git", "clone", "-q", s["url"], str(repo)], check=True, timeout=1800)
    sha = git(repo, "rev-parse", s["commit"])
    venv = WORK / "venvs-d" / name
    if not (venv / ".ok").exists():
        checkout(repo, sha)
        sh(["uv", "venv", "-q", "--python", s["python"], str(venv)], check=True)
        inst = s["install"].split() if isinstance(s["install"], str) else list(s["install"])
        code, out = sh(["uv", "pip", "install", "-q", "--python", str(venv / "bin" / "python"), *inst, "pytest",
                        "pytest-randomly", WHEEL], cwd=repo, timeout=3600)
        if code != 0:
            raise SystemExit(f"{name}: install failed: {out[-1500:]}")
        (venv / ".ok").write_text("ok")
    return repo, venv, {**s, "sha": sha}


def pytest(repo, venv, args, timeout=1800):
    td = tempfile.mkdtemp(prefix="od-")
    outp, trace = os.path.join(td, "o.json"), os.path.join(td, "t.jsonl")
    cmd = [str(venv / "bin" / "python"), "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=no",
           f"--det-outcomes={outp}", *args]
    if "--det" in args:
        cmd.append(f"--det-trace={trace}")
    t0 = time.perf_counter()
    code, out = sh(cmd, cwd=repo, env=base_env(venv), timeout=timeout)
    wall = time.perf_counter() - t0
    try:
        outcomes = json.load(open(outp)).get("outcomes", {})
    except (OSError, ValueError):
        outcomes = {}
    order = []
    if os.path.exists(trace):
        for line in open(trace):
            d = json.loads(line)
            if d.get("type") == "test":
                order.append(d["nodeid"])
    return {"code": code, "outcomes": outcomes, "order": order, "wall": wall, "tail": out[-800:], "trace": trace}


def det_args(trace_dir_run, seed):
    a = ["--det", f"--det-disable={DISABLE}", "-p", "no:randomly"]
    if seed is not None:
        a.append(f"--det-seed={seed}")
    return a


class Search:
    def __init__(self, repo, venv):
        self.repo, self.venv, self.steps = repo, venv, []

    def run_list(self, tests, victim, why):
        """Run ``tests`` then the victim, in that order, under --det (fixed order = argument order)."""
        r = pytest(self.repo, self.venv, ["--det", f"--det-disable={DISABLE}", "-p", "no:randomly",
                                          *tests, victim])
        o = r["outcomes"].get(victim)
        verdict = "missing" if o is None and r["code"] in (4, 5) else \
            ("fail" if o and ("fail" in o or "error" in o) else ("pass" if o else "error"))
        if o is None and r["code"] not in (4, 5):
            verdict = "error"
        self.steps.append({"why": why, "n": len(tests), "verdict": verdict, "wall": round(r["wall"], 2)})
        return verdict


def first_parent_back(repo, sha, n):
    return git(repo, "rev-list", "--first-parent", f"--max-count={n + 1}", sha).split()  # [sha, parent, ...]


def find_polluter(s: Search, before, victim):
    cur = list(before)
    while len(cur) > 1:
        half = cur[: len(cur) // 2]
        v = s.run_list(half, victim, "polluter split")
        if v == "fail":
            cur = half
        else:
            rest = cur[len(cur) // 2:]
            v2 = None
            # single-polluter assumption: the other half must reproduce (checked only when it is the last step)
            cur = rest
            del v2
    if not cur:
        return None
    return cur[0] if s.run_list(cur, victim, "polluter confirm") == "fail" else None


def pair_at(s: Search, sha, polluter, victim, why):
    checkout(s.repo, sha)
    return s.run_list([polluter], victim, why)


def find_commit(s: Search, red, polluter, victim, max_back=512):
    chain = first_parent_back(s.repo, red, max_back)  # chain[0] = red
    known = {0: "fail"}
    d, good = 1, None
    while d < len(chain):
        v = pair_at(s, chain[d], polluter, victim, f"back {d}")
        known[d] = v
        if v in ("pass", "missing"):
            good = d
            break
        if v == "error":  # cannot run here: go further back
            pass
        d *= 2
    if good is None:
        return None, None, chain, known
    lo, hi = good, max(i for i, v in known.items() if i < good and v == "fail")  # chain index: lo older, hi newer
    # binary search between hi (fail, newer) and lo (pass, older) on chain indices
    while lo - hi > 1:
        mid = (lo + hi) // 2
        v = pair_at(s, chain[mid], polluter, victim, "bisect")
        known[mid] = v
        if v == "fail":
            hi = mid
        elif v in ("pass", "missing"):
            lo = mid
        else:  # error: skip it by probing its neighbours toward the pass side
            j = mid + 1
            while j < lo and known.get(j) is None:
                vj = pair_at(s, chain[j], polluter, victim, "skip")
                known[j] = vj
                if vj != "error":
                    break
                j += 1
            if known.get(j) == "fail":
                hi = j
            elif known.get(j) in ("pass", "missing"):
                lo = j
            else:
                break
    return chain[hi], chain[lo], chain, known


def baseline_bisect(repo, venv, good, bad, victim, attempt):
    """git bisect run with plain pytest, full suite, random order (pytest-randomly reseeds every run)."""
    git(repo, "bisect", "reset", check=False)
    checkout(repo, bad)
    env = base_env(venv)
    script = tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False)
    counter = script.name + ".count"
    script.write(f"""#!/bin/sh
echo x >> {counter}
o=$(mktemp)
{venv}/bin/python -m pytest -q -p no:cacheprovider --tb=no -p randomly --det-outcomes=$o >/dev/null 2>&1
code=$?
r=$({venv}/bin/python -c "import json,sys; d=json.load(open('$o')).get('outcomes',{{}}); v=d.get(sys.argv[1]); print('bad' if v and ('fail' in v or 'error' in v) else ('good' if v else 'skip'))" '{victim}' 2>/dev/null || echo skip)
rm -f $o
[ "$r" = bad ] && exit 1
[ "$r" = good ] && exit 0
exit 125
""")
    script.close()
    os.chmod(script.name, 0o755)
    t0 = time.perf_counter()
    sh(["git", "-C", str(repo), "bisect", "start", "--first-parent", bad, good], env=env)
    code, out = sh(["git", "-C", str(repo), "bisect", "run", script.name], cwd=repo, env=env, timeout=7200)
    wall = time.perf_counter() - t0
    git(repo, "bisect", "reset", check=False)
    runs = sum(1 for _ in open(counter)) if os.path.exists(counter) else 0
    for p in (script.name, counter):
        if os.path.exists(p):
            os.unlink(p)
    named = None
    for line in out.splitlines():
        if "is the first bad commit" in line:
            named = line.split()[0]
    return {"attempt": attempt, "named": named, "executions": runs, "wall": round(wall, 2),
            "tail": "" if named else out[-300:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-name", required=True)
    ap.add_argument("--victims", required=True, help="JSON list of [config, nodeid]")
    ap.add_argument("--out", required=True)
    ap.add_argument("--attempts", type=int, default=10)
    a = ap.parse_args()
    repo, venv, s = setup(a.repo_name)
    done = set()
    if os.path.exists(a.out):
        done = {(json.loads(l)["repo"], json.loads(l)["victim"]) for l in open(a.out)}
    for config, victim in json.loads(a.victims):
        if (a.repo_name, victim) in done:
            continue
        seed = None if config == "fixed" else int(config)
        res = {"repo": a.repo_name, "victim": victim, "config": config, "red": s["sha"],
               "checkout": "fresh-mtime"}  # common.checkout: strictly increasing stamps (review R-019b, M6)
        t0 = time.perf_counter()
        sr = Search(repo, venv)
        checkout(repo, s["sha"])
        full = pytest(repo, venv, det_args(None, seed))
        res["full_red"] = full["outcomes"].get(victim)
        red_o = res["full_red"] or ""
        order = full["order"]
        sr.steps.append({"why": "full suite, red order", "verdict": res["full_red"], "wall": round(full["wall"], 2)})
        if not ("fail" in red_o or "error" in red_o) or victim not in order:
            res["skip"] = f"victim not red in the full run ({res['full_red']}, in order: {victim in order})"
            open(a.out, "a").write(json.dumps(res) + "\n")
            print(a.repo_name, victim, res["skip"], flush=True)
            continue
        before = order[: order.index(victim)]
        alone = sr.run_list([], victim, "victim alone")
        if alone == "fail":
            res["skip"] = "brittle: fails alone (state-setter case, not a polluter)"
            open(a.out, "a").write(json.dumps(res) + "\n")
            print(a.repo_name, victim, res["skip"], flush=True)
            continue
        pol = find_polluter(sr, before, victim)
        res["polluter"] = pol
        res["tests_before"] = len(before)
        if pol is None:
            res["skip"] = "no single polluter"
            res["finder_steps"] = sr.steps
            open(a.out, "a").write(json.dumps(res) + "\n")
            print(a.repo_name, victim, res["skip"], flush=True)
            continue
        n_pol = len(sr.steps)
        named, good, chain, known = find_commit(sr, s["sha"], pol, victim)
        res["finder_wall"] = round(time.perf_counter() - t0, 2)
        res["finder_named"] = named
        res["finder_good"] = good
        res["executions_polluter"] = n_pol
        res["executions_commit"] = len(sr.steps) - n_pol
        res["executions"] = len(sr.steps)
        res["finder_steps"] = sr.steps
        if named is None:
            res["skip"] = "the pair fails at every reachable commit (no green found within 512 first-parent commits)"
            open(a.out, "a").write(json.dumps(res) + "\n")
            print(a.repo_name, victim, res["skip"], flush=True)
            continue
        # truth: walk back from red one first-parent commit at a time (deterministic run of the pair) until the
        # pair passes; the transition is the newest commit that fails with a passing parent
        scan = {}
        ts = Search(repo, venv)
        trans = None
        for i in range(0, min(len(chain), 400)):
            scan[i] = pair_at(ts, chain[i], pol, victim, "truth scan")
            if scan[i] in ("pass", "missing"):
                j = i - 1
                while j >= 0 and scan[j] == "error":
                    j -= 1
                trans = chain[j] if j >= 0 else None
                break
        res["truth"] = trans
        res["truth_scan_tail"] = [scan[i] for i in sorted(scan)][-5:]
        res["finder_correct"] = trans is not None and named == trans
        touched = git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--first-parent", named,
                      check=False).split()
        res["named_touches"] = touched[:20]
        res["named_touches_polluter_file"] = pol.split("::")[0] in touched
        res["named_touches_victim_file"] = victim.split("::")[0] in touched
        res["truth_runs"] = len(scan)
        # baseline: 10 git bisect attempts with plain pytest in random order, same bracket
        bl = [baseline_bisect(repo, venv, good, s["sha"], victim, i) for i in range(a.attempts)]
        res["bisect"] = bl
        res["bisect_wrong"] = sum(1 for b in bl if b["named"] != trans)
        checkout(repo, s["sha"])
        open(a.out, "a").write(json.dumps(res) + "\n")
        print(f"{a.repo_name} {victim}: polluter {pol} named {named[:10]} truth {trans and trans[:10]} "
              f"{'OK' if res['finder_correct'] else 'WRONG'} exec={res['executions']} "
              f"(polluter {n_pol}, commit {res['executions_commit']}) | bisect wrong {res['bisect_wrong']}/{a.attempts}",
              flush=True)


if __name__ == "__main__":
    main()
