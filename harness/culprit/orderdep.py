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
from common import ENGINE, base_env, checkout, git, sh, worktrees  # noqa: E402

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


def pytest(repo, venv, args, timeout=1800, worktree=None):
    td = tempfile.mkdtemp(prefix="od-")
    outp, trace = os.path.join(td, "o.json"), os.path.join(td, "t.jsonl")
    cmd = [str(venv / "bin" / "python"), "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=no",
           f"--det-outcomes={outp}", *args]
    if "--det" in args:
        cmd.append(f"--det-trace={trace}")
    cwd = repo
    if worktree is not None:  # a copy of the repository mounted at its path (round 4: parallel red-side probes)
        cmd = ["unshare", "-m", "--propagation", "private", "sh", "-c",
               'mount --bind "$1" "$2" && cd "$2" && shift 2 && exec "$@"', "ns",
               os.path.realpath(str(worktree)), os.path.realpath(str(repo)), *cmd]
        cwd = "/"
    t0 = time.perf_counter()
    code, out = sh(cmd, cwd=cwd, env=base_env(venv), timeout=timeout)
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

    def run_list(self, tests, victim, why, worktree=None, extra=None):
        """Run ``tests`` then the victim, in that order, under --det (fixed order = argument order)."""
        r = pytest(self.repo, self.venv, ["--det", f"--det-disable={DISABLE}", "-p", "no:randomly",
                                          *tests, victim], worktree=worktree)
        return self._verdict(r, tests, victim, why, extra)

    def _verdict(self, r, tests, victim, why, extra=None):
        o = r["outcomes"].get(victim)
        verdict = "missing" if o is None and r["code"] in (4, 5) else \
            ("fail" if o and ("fail" in o or "error" in o) else ("pass" if o else "error"))
        if o is None and r["code"] not in (4, 5):
            verdict = "error"
        step = {"why": why, "n": len(tests), "verdict": verdict, "wall": round(r["wall"], 2)}
        step.update(extra or {})
        self.steps.append(step)
        return verdict

    def pairs_many(self, shas, polluter, victim, why):
        """The pair at several commits at the same time, each in its own copy of the repository mounted at the
        repository's path; the outcomes in the order of ``shas``."""
        if len(shas) <= 1 or RED_WORKERS <= 1:
            return [pair_at(self, x, polluter, victim, why) for x in shas]
        from concurrent.futures import ThreadPoolExecutor
        wts = worktrees(self.repo, len(shas))
        for w, x in zip(wts, shas):
            checkout(w, x)
        self.batches = getattr(self, "batches", 0) + 1
        args = ["--det", f"--det-disable={DISABLE}", "-p", "no:randomly", polluter, victim]
        with ThreadPoolExecutor(len(shas)) as ex:
            rs = list(ex.map(lambda w: pytest(self.repo, self.venv, args, worktree=w), wts))
        return [self._verdict(r, [polluter], victim, why, {"batch": self.batches, "worker": i})
                for i, r in enumerate(rs)]


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


RED_SIDE_CAP = int(os.environ.get("CULPRIT_D_BUDGET", "32"))  # red-side replays per case before an answer is
#   withheld (R-019b; round 3: 8, round 4: 32, replayed RED_WORKERS at a time)
RED_WORKERS = int(os.environ.get("CULPRIT_WORKERS", "4"))
_CONFIG_FILES = ("pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "conftest.py")


def footprint(s: Search, sha, polluter, victim) -> set:
    """Repository files the pair depends on at ``sha``: the modules the session imports (``-X importtime``; works
    on Python 3.9, where proof keys cannot be written), the two test files, every conftest and the pytest
    configuration. One extra run, counted as a step."""
    checkout(s.repo, sha)
    cmd = [str(s.venv / "bin" / "python"), "-X", "importtime", "-m", "pytest", "-q", "-p", "no:cacheprovider",
           "--tb=no", "--det", f"--det-disable={DISABLE}", "-p", "no:randomly", polluter, victim]
    t0 = time.perf_counter()
    _code, out = sh(cmd, cwd=s.repo, env=base_env(s.venv, {"PYTHONPROFILEIMPORTTIME": "1"}), timeout=1800)
    s.steps.append({"why": "red-side footprint", "verdict": "-", "wall": round(time.perf_counter() - t0, 2)})
    files = set(git(s.repo, "ls-tree", "-r", "--name-only", sha).split("\n"))
    paths = {polluter.split("::")[0], victim.split("::")[0]}
    paths |= {f for f in files if f.rsplit("/", 1)[-1] in _CONFIG_FILES}
    for line in out.splitlines():
        if not line.startswith("import time:") or "|" not in line:
            continue
        mod = line.rsplit("|", 1)[1].strip()
        if not mod or " " in mod:  # the header line ("imported package")
            continue
        base = mod.replace(".", "/")
        for pre in ("", "src/", "lib/"):
            for cand in (f"{pre}{base}.py", f"{pre}{base}/__init__.py"):
                if cand in files:
                    paths.add(cand)
    if not any(p.endswith(".py") and p not in (polluter.split("::")[0], victim.split("::")[0])
               and not p.endswith("conftest.py") for p in paths):
        # no module of the repository seen (the import report was lost): every Python file is in the footprint
        paths |= {f for f in files if f.endswith(".py")}
    return paths


def red_side(s: Search, chain, known, hi, polluter, victim, paths) -> tuple[int | None, int | None, str]:
    """Review R-019b (N1, N2) for step 4: the named commit chain[hi] is the newest transition only if every commit
    of (chain[hi], red] fails. A commit's footprint state is the blob of every footprint path; a commit whose state
    equals a replayed one has its outcome (no run). The others are replayed newest first, up to RED_SIDE_CAP; a pass
    restarts the search above it; an unreplayed rest withholds the answer. Returns (hi, lo, why) or (None, None, why).
    """
    def vec(i):
        out = git(s.repo, "ls-tree", chain[i], "--", *sorted(paths), check=False)
        return tuple(sorted(line.split()[2] + line.split("\t", 1)[1] for line in out.splitlines() if "\t" in line))

    vecs: dict = {}
    state: dict = {}
    for i, v in known.items():
        if i <= hi and v in ("fail", "pass", "missing"):
            vecs.setdefault(i, vec(i))
            state.setdefault(vecs[i], "pass" if v in ("pass", "missing") else "fail")
    notes, probed = [], 0
    for _round in range(6):
        unchecked = set()
        restart = None
        for j in range(1, hi + 1):
            if j not in vecs:
                vecs[j] = vec(j)
        # order only (the cap decides soundness): states where the polluter's or the victim's test file changes
        # first (a missing test passes), then the others, newest first
        tfiles = (polluter.split("::")[0], victim.split("::")[0])
        tvec = {j: tuple(x for x in vecs[j] if x.endswith(tfiles)) for j in range(1, hi + 1)}
        prio = [j for j in range(1, hi) if tvec[j] != tvec[j + 1]]
        order = prio + [j for j in range(1, hi) if j not in prio]
        while True:
            # a state already known to pass: restart above it
            restart = next((j for j in order if state.get(vecs[j]) == "pass"), None)
            if restart is not None:
                break
            pend, seen_v = [], set()
            for j in order:
                if state.get(vecs[j]) is None and known.get(j) is None and vecs[j] not in seen_v \
                        and vecs[j] not in unchecked:
                    seen_v.add(vecs[j])
                    pend.append(j)
            if not pend:
                break
            room = RED_SIDE_CAP - probed
            if room <= 0:
                unchecked.update(vecs[j] for j in pend)
                break
            batch = pend[: min(RED_WORKERS, room)]
            probed += len(batch)
            for j, v in zip(batch, s.pairs_many([chain[j] for j in batch], polluter, victim, "red-side check")):
                known[j] = v
                if v == "error":
                    unchecked.add(vecs[j])
                    continue
                state[vecs[j]] = "pass" if v in ("pass", "missing") else "fail"
            passed = [j for j in batch if state.get(vecs[j]) == "pass"]
            if passed:
                restart = min(passed)  # the newest passing commit (chain index 0 = red)
                break
        if restart is not None:
            notes.append(f"{chain[hi][:10]} fixed later: {chain[restart][:10]} passes")
            lo = restart
            hi = max(i for i, v in known.items() if i < lo and v == "fail")
            while lo - hi > 1:
                mid = (lo + hi) // 2
                v = pair_at(s, chain[mid], polluter, victim, "red-side bisect")
                known[mid] = v
                if v == "fail":
                    hi = mid
                elif v in ("pass", "missing"):
                    lo = mid
                else:
                    return None, None, "; ".join(notes + ["a commit of the restarted search cannot run"])
            for i, v in known.items():
                if v in ("fail", "pass", "missing"):
                    vecs.setdefault(i, vec(i))
                    state.setdefault(vecs[i], "pass" if v in ("pass", "missing") else "fail")
            continue
        if unchecked:
            return None, None, "; ".join(notes + [
                f"ambiguous: {chain[hi][:10]} is a transition, but {len(unchecked)} later footprint states were not "
                f"replayed (one may pass, and a newer commit break again)", f"suspect {chain[hi]}"])
        return hi, hi + 1, "; ".join(notes)
    return None, None, "; ".join(notes + ["the history changes outcome too often"])


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
        res["finder_first"] = named
        if named is not None:
            hi = chain.index(named)
            paths = footprint(sr, s["sha"], pol, victim) | footprint(sr, named, pol, victim)
            res["footprint_paths"] = len(paths)
            nh, nl, why = red_side(sr, chain, known, hi, pol, victim, paths)
            res["red_side"] = why
            named, good = (chain[nh], chain[nl]) if nh is not None else (None, None)
        res["finder_wall"] = round(time.perf_counter() - t0, 2)
        res["finder_named"] = named
        res["finder_good"] = good
        res["executions_polluter"] = n_pol
        res["executions_commit"] = len(sr.steps) - n_pol
        res["executions"] = len(sr.steps)
        res["red_side_budget"], res["workers"] = RED_SIDE_CAP, RED_WORKERS
        res["red_side_probes"] = sum(1 for x in sr.steps if x.get("why") == "red-side check")
        res["finder_steps"] = sr.steps
        if named is None and res.get("finder_first") is None:
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
        touched = git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--first-parent",
                      named or res["finder_first"], check=False).split()
        res["named_touches"] = touched[:20]
        res["named_touches_polluter_file"] = pol.split("::")[0] in touched
        res["named_touches_victim_file"] = victim.split("::")[0] in touched
        res["truth_runs"] = len(scan)
        # baseline: 10 git bisect attempts with plain pytest in random order, same bracket
        bl = [baseline_bisect(repo, venv, good or res["finder_first"] + "^", s["sha"], victim, i)
              for i in range(a.attempts)]
        res["bisect"] = bl
        res["bisect_wrong"] = sum(1 for b in bl if b["named"] != trans)
        checkout(repo, s["sha"])
        open(a.out, "a").write(json.dumps(res) + "\n")
        print(f"{a.repo_name} {victim}: polluter {pol} named {named and named[:10]} truth {trans and trans[:10]} "
              f"{'OK' if res['finder_correct'] else 'WRONG' if named else 'UNKNOWN'} exec={res['executions']} "
              f"(polluter {n_pol}, commit {res['executions_commit']}) | bisect wrong {res['bisect_wrong']}/{a.attempts}",
              flush=True)


if __name__ == "__main__":
    main()
