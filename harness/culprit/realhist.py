#!/usr/bin/env python3
"""Real history (cases of kind b): pass-to-fail transitions of the cache-proof walks, reproduced locally.

For a walk transition at step i (the walk's fresh ``--det`` run counted more failures at i than at i-1):

1. install the project at commit i-1 and at commit i the way the walk does (dependency resolution at that commit),
   run the full suite with ``--det`` and the walk's epoch at both; pass-to-fail tests = passed at i-1, failed at i
   (tests new at i are not transitions);
2. red = the last walked commit where the test still fails, with its own install and epoch; green = commit i-1;
3. finder: green key, red key, green environment rebuilt from the green key at the CI path; truth = commit i, or
   the input that changed at i when the code did not (installed distribution, epoch); the commit message history is
   searched for the project's own revert or fix of the culprit;
4. baseline: git bisect run with plain pytest in the red environment.

    realhist.py --walk s1d/pygments-0of1 --step 8 --out results.jsonl
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ENGINE, checkout, git, git_bisect, run_det, sh  # noqa: E402
from finder import EnvBuilder, Finder  # noqa: E402

WORK = Path(os.environ.get("CULPRIT_WORK", "/home/user/work"))
WHEEL = os.environ.get("CULPRIT_WHEEL", str(next((WORK / "wheels2").glob("detpy-*.whl"), "")))
CP = "origin/claude/cache-proof-step1:"


def walk(name):
    raw = subprocess.run(["git", "-C", str(ENGINE), "show", f"{CP}tracks/cache-proof/results/{name}.json.gz"],
                         capture_output=True, check=True).stdout
    return json.loads(gzip.decompress(raw))


def install_at(repo, sha, at: Path, py="3.13"):
    from detpy_harness import detect_install

    shutil.rmtree(at, ignore_errors=True)
    checkout(repo, sha)
    sh(["uv", "venv", "-q", "--python", py, str(at)], check=True)
    args, groups, reqs = detect_install(repo)
    code, out = sh(["uv", "pip", "install", "-q", "--python", str(at / "bin" / "python"), *args, *groups, *reqs,
                    "pytest", WHEEL], cwd=repo, timeout=3600)
    if code != 0:
        raise RuntimeError(out[-1000:])
    return at


def full_det(repo, venv, epoch_args, timeout=3600):
    import tempfile
    td = tempfile.mkdtemp()
    o = os.path.join(td, "o.json")
    cmd = [str(venv / "bin" / "python"), "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=no", "--det",
           f"--det-outcomes={o}", *epoch_args]
    from common import base_env
    sh(cmd, cwd=repo, env=base_env(venv), timeout=timeout)
    try:
        return json.load(open(o)).get("outcomes", {})
    except (OSError, ValueError):
        return {}


def fix_or_revert(repo, culprit, red):
    """Later commits (up to red's descendants on the default branch) that name the culprit or revert its subject."""
    subj = git(repo, "log", "-1", "--format=%s", culprit)
    hits = []
    out = git(repo, "log", "--format=%H%x00%s%x00%b%x1e", f"{culprit}..origin/HEAD", check=False)
    for rec in out.split("\x1e"):
        parts = rec.strip().split("\x00")
        if len(parts) < 2:
            continue
        h, s = parts[0], parts[1]
        body = parts[2] if len(parts) > 2 else ""
        if culprit[:7] in s + body or (s.startswith("Revert") and subj[:40] in s):
            hits.append(f"{h[:10]} {s[:80]}")
    return hits[:5]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--walk", required=True)
    ap.add_argument("--step", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-tests", type=int, default=6)
    a = ap.parse_args()
    d = walk(a.walk)
    spec = d["spec"]
    steps = {s["i"]: s for s in d["steps"]}
    name = spec["name"]
    repo = WORK / "repos-b" / name
    if not repo.exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        sh(["git", "clone", "-q", spec["url"], str(repo)], check=True, timeout=1800)
    i = a.step
    g, r = steps[i - 1], steps[i]
    tag = f"{name}-{a.walk.split('/')[0]}-{i}"
    vroot = WORK / "venvs-b"
    vg = install_at(repo, g["sha"], vroot / f"{tag}-g")
    vr = install_at(repo, r["sha"], vroot / f"{tag}-r")
    checkout(repo, g["sha"])
    og = full_det(repo, vg, g.get("epoch_args", []))
    checkout(repo, r["sha"])
    orr = full_det(repo, vr, r.get("epoch_args", []))
    p2f = sorted(t for t, o in orr.items() if o in ("failed", "error") and og.get(t) == "passed")
    new_fail = sorted(t for t, o in orr.items() if o in ("failed", "error") and t not in og)
    base = {"walk": a.walk, "step": i, "transition": r["sha"], "green": g["sha"], "pass_to_fail": len(p2f),
            "new_failing": len(new_fail)}
    print(tag, "pass-to-fail", len(p2f), "new failing", len(new_fail), p2f[:5], flush=True)
    if not p2f:
        with open(a.out, "a") as fh:
            fh.write(json.dumps({**base, "id": tag, "skip": "no pass-to-fail test (only new failing tests)"}) + "\n")
        return
    # red end: the last walked commit (same walk) where the first test still fails
    later = [s for k, s in sorted(steps.items()) if k > i and s.get("status") == "ok"]
    end = later[-1] if later else r
    ve = install_at(repo, end["sha"], vroot / f"{tag}-e")
    # truth by input: what changed between i-1 and i besides the code
    def dists(v):
        code, out = sh(["uv", "pip", "freeze", "--python", str(v / "bin" / "python")])
        return {l.split("==")[0].lower(): l.split("==")[1] for l in out.splitlines() if "==" in l}
    dg, dr = dists(vg), dists(vr)
    dist_changes = sorted(n for n in set(dg) | set(dr) if dg.get(n) != dr.get(n) and n != "detpy")
    epoch_changed = g.get("epoch_args") != r.get("epoch_args")
    code_changed = git(repo, "rev-parse", f"{g['sha']}^{{tree}}") != git(repo, "rev-parse", f"{r['sha']}^{{tree}}")
    base.update(dist_changes=dist_changes, epoch_changed=epoch_changed, end=end["sha"], end_epoch=end.get("epoch_args"))
    done = set()
    if os.path.exists(a.out):
        done = {json.loads(l)["id"] for l in open(a.out)}
    for nid in p2f[: a.max_tests]:
        cid = f"{tag}-{nid}"
        if cid in done:
            continue
        res = {**base, "id": cid, "red_test": nid}
        # which change explains it, checked directly: the code of i in the old environment and old epoch, etc.
        checkout(repo, r["sha"])
        code_only = run_det(repo, vg, nid, args=g.get("epoch_args", []))["outcome"]
        checkout(repo, g["sha"])
        env_only = run_det(repo, vr, nid, args=r.get("epoch_args", []))["outcome"]
        res["code_only"], res["env_only"] = code_only, env_only
        truth = []
        if code_only == "fail":
            truth.append(r["sha"])
        if env_only == "fail" or code_only != "fail":
            truth += [f"dist:{n}" for n in dist_changes] + (["epoch"] if epoch_changed else [])
        res["truth"] = truth
        checkout(repo, end["sha"])
        red_out = run_det(repo, ve, nid, args=end.get("epoch_args", []))["outcome"]
        if red_out != "fail":
            res["red_end"] = end["sha"]
            res["skip_end"] = "the test passes again at the last walked commit: red = the transition commit"
            red_sha, red_v, red_epoch = r["sha"], vr, r.get("epoch_args", [])
        else:
            red_sha, red_v, red_epoch = end["sha"], ve, end.get("epoch_args", [])
        res["red"] = red_sha
        kd = WORK / "keys-b"
        kd.mkdir(exist_ok=True)
        gk, rk = str(kd / f"{cid.replace('/', '_')}-g.json"), str(kd / f"{cid.replace('/', '_')}-r.json")
        ci = vroot / f"{tag}-ci"
        # keys from the CI path (green install, then red install, at one path)
        shutil.rmtree(ci, ignore_errors=True)
        install_at(repo, g["sha"], ci)
        checkout(repo, g["sha"])
        res["green_run"] = run_det(repo, ci, nid, keys=gk, args=g.get("epoch_args", []))["outcome"]
        install_at(repo, red_sha, ci)
        checkout(repo, red_sha)
        res["red_run"] = run_det(repo, ci, nid, keys=rk, args=red_epoch)["outcome"]
        shutil.rmtree(ci, ignore_errors=True)
        # the epoch is part of each side's configuration: replays in the green environment use the green epoch
        builder = EnvBuilder(["-e", "."], WHEEL, str(WORK / "rebuilt"))
        f = Finder(repo, nid, {"sha": g["sha"], "env": {}, "venv": None, "key": gk, "prefix": str(ci)},
                   {"sha": red_sha, "env": {}, "venv": red_v, "key": rk, "det_args": list(red_epoch)}, builder=builder,
                   det_args=[x for x in g.get("epoch_args", [])])
        try:
            fr = f.run()
        except Exception as e:
            fr = {"culprit": None, "why": f"error: {type(e).__name__}: {e}", "executions": len(f.steps)}
        shutil.rmtree(ci, ignore_errors=True)
        c = fr.get("culprit") or {}
        named = c.get("commit") or c.get("input")
        res["finder"] = fr
        res["finder_named"] = named
        res["finder_correct"] = named in truth or (named == "epoch" and "epoch" in truth)
        b = git_bisect(repo, red_v, g["sha"], red_sha, ["--tb=no", "-p", "no:randomly", nid])
        res["bisect"] = b
        res["bisect_correct"] = b["named"] is not None and any(t.startswith(b["named"][:12]) for t in truth)
        if code_only == "fail":
            res["fix_or_revert"] = fix_or_revert(repo, r["sha"], red_sha)
        with open(a.out, "a") as fh:
            fh.write(json.dumps(res) + "\n")
        print(f"{cid}: truth {truth} finder {named} {'OK' if res['finder_correct'] else 'WRONG'} "
              f"exec={fr.get('executions')} exact={fr.get('rebuilt_exactly')} | bisect {b['named'] and b['named'][:10]} "
              f"{'OK' if res['bisect_correct'] else 'WRONG'} exec={b['executions']}", flush=True)


if __name__ == "__main__":
    main()
