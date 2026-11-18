#!/usr/bin/env python3
"""No-code reds on Node (docusaurus, Vitest): the finder in green-key-only mode.

The Node engine (``detjs ... --det --det-cache``, branch claude/node-cache-proof) writes the same proof store as
detpy, but it never stores a failing test, and it has no key-dump flag. So the finder takes the green test's entry
from the green store and evaluates every one of its inputs on the red side:

* environment variables: value digest of the red job's value (same Rust digest as Node's);
* project files read and code loaded: changed between the green and the red commit -> candidate commits (those
  that touch one of them);
* runtime and configuration identity: the parts (``.detjs/cache-identity.json``) of the green and the red run.

Then the same search as the Python finder (red code in the green environment first when both kinds exist, then a
binary search over commits or a split over inputs), one deterministic replay per step:
``detjs vitest run --det <file> -t <name>``. A replay in the green environment is exact when its runtime identity
digest equals the green run's.

    node_case.py --arm data|env --decoy none|tz --out results.jsonl
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ENGINE, checkout, git, sh  # noqa: E402
from finder import group_inputs  # noqa: E402
from nocode import edit_tree_commits, h2h_changes, h2h_result  # noqa: E402

WORK = Path(os.environ.get("CULPRIT_WORK", "/home/user/work"))
NODE_BIN = WORK / "node26" / "bin"
DETJS = WORK / "engine-node" / "node" / "bin" / "detjs.js"
EPOCH = "2026-01-01T00:00:00"


def node_env(extra: dict) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("NODE_ENV", "TZ", "NODE_OPTIONS", "FORCE_COLOR",
                                                            "NO_COLOR", "PYTHONWARNINGS")}
    env["PATH"] = f"{NODE_BIN}:{env.get('PATH', '')}"
    env["CI"] = "true"
    for k, v in extra.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    return env


def run_file(repo, unit, extra, cache=None, name=None, plain=False):
    td = tempfile.mkdtemp(prefix="nd-")
    out = os.path.join(td, "r.json")
    if plain:
        cmd = ["pnpm", "exec", "vitest", "run", unit, "--reporter=json", f"--outputFile={out}"]
    else:
        cmd = ["node", str(DETJS), "vitest", "run", "--det", f"--det-epoch={EPOCH}",
               f"--det-cache={cache or os.path.join(td, 'c')}", unit, "--reporter=json", f"--outputFile={out}"]
    if name:
        cmd += ["-t", "^" + re.escape(name) + "$"]
    t0 = time.perf_counter()
    code, o = sh(cmd, cwd=repo, env=node_env(extra), timeout=1200)
    wall = time.perf_counter() - t0
    res = {}
    try:
        d = json.load(open(out))
        for t in d["testResults"]:
            for a in t["assertionResults"]:
                res[" > ".join(list(a.get("ancestorTitles") or []) + [a["title"]])] = a["status"]
        if d.get("numFailedTestSuites") and not res:
            res["__suite__"] = "failed"
    except (OSError, ValueError, KeyError):
        pass
    ident = None
    try:
        ident = json.load(open(os.path.join(repo, ".detjs", "cache-identity.json")))
    except (OSError, ValueError):
        pass
    shutil.rmtree(td, ignore_errors=True)
    return {"code": code, "tests": res, "wall": wall, "identity": ident, "tail": o[-600:]}


def verdict(r, name):
    s = r["tests"].get(name)
    if s is None:
        return "fail" if r["tests"].get("__suite__") == "failed" or r["code"] not in (0,) else "missing"
    if s in ("skipped", "pending", "todo", "disabled"):
        return "missing"
    return "fail" if s == "failed" else "pass"


def flat(ident):
    out = {}
    for side in ("runtime", "config"):
        for k, v in ((ident or {}).get(side, {}).get("parts") or {}).items():
            out[f"{side}:{k}"] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["data", "env"])
    ap.add_argument("--decoy", default="none", choices=["none", "tz"])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    cid = f"docusaurus-{a.arm}-{a.decoy}"
    if os.path.exists(a.out) and any(json.loads(l)["id"] == cid for l in open(a.out)):
        return
    d = h2h_result("h4", f"docusaurus-ci-{a.arm}", "0o1")
    ch = h2h_changes("docusaurus", f"ci-{a.arm}")
    w = [c["sha"] for c in sorted(d["commits"], key=lambda c: int(c["i"]))]
    green, later = w[2], [x for x in w[4:] if x != w[2]]
    repo = WORK / "repos-c" / "docusaurus"
    vars0, vars1 = {}, dict(ch.get("env") or {})
    if a.arm == "data":
        truth, red_head = edit_tree_commits(repo, green, later, ch["edits"], cid)
    else:
        truth, red_head = "env:" + next(iter(ch["env"])), w[-1]
    decoy = None
    if a.decoy == "tz":
        vars1["TZ"] = "Asia/Kolkata"
        decoy = "env:TZ"
    t = [x for x in d["transitions"] if str(x["i"]) == "3"][0]
    unit = sorted(t["fresh_bad"])[0]
    res = {"id": cid, "scenario": f"docusaurus-{a.arm}", "decoy": decoy, "truth": truth, "what": ch["what"],
           "unit": unit}
    # red test: fails at red, passes at green, passes at red code without the change, decoy alone harmless
    checkout(repo, red_head)
    rr = run_file(repo, unit, vars1)
    checkout(repo, green)
    gg = run_file(repo, unit, vars0)
    pick = None
    for name in sorted(n for n, s in rr["tests"].items() if s == "failed" and gg["tests"].get(n) == "passed"):
        checkout(repo, w[-1])
        if verdict(run_file(repo, unit, vars0, name=name), name) != "pass":
            continue
        if decoy and verdict(run_file(repo, unit, {**vars0, "TZ": "Asia/Kolkata"}, name=name), name) != "pass":
            continue
        pick = name
        break
    if pick is None:
        res["skip"] = "no red test that only the change breaks"
        open(a.out, "a").write(json.dumps(res) + "\n")
        print(cid, res["skip"])
        return
    res["red_test"] = pick
    # green key (store) and identities
    gstore = WORK / "keys-c" / f"{cid}-green-store"
    shutil.rmtree(gstore, ignore_errors=True)
    checkout(repo, green)
    g = run_file(repo, unit, vars0, cache=str(gstore))
    checkout(repo, red_head)
    r = run_file(repo, unit, vars1)
    res["green_run"], res["red_run"] = verdict(g, pick), verdict(r, pick)
    store = json.load(open(gstore / "proof-cache.json"))
    key = None
    for k, e in store["tests"].items():
        if k.split("::", 1)[0] == unit and " > ".join(k.split("::")[1:]) == pick:
            key = e
    t0 = time.perf_counter()
    steps = []
    if key is None:
        res["skip"] = "the green store has no entry for the test"
        open(a.out, "a").write(json.dumps(res) + "\n")
        print(cid, res["skip"])
        return
    from detpy import _core

    inputs = []
    base_red = node_env(vars1)
    for n, dg in key["env"]:
        if n == "*":
            if _core.env_all_digest(base_red) != dg:
                inputs.append({"kind": "env", "id": "env:*", "name": "*"})
            continue
        if _core.env_value_digest(base_red.get(n)) != dg:
            inputs.append({"kind": "env", "id": f"env:{n}", "name": n})
    gi, ri = flat(g["identity"]), flat(r["identity"])
    for k in sorted(set(gi) | set(ri)):
        if gi.get(k) != ri.get(k):
            if k == "runtime:tz":
                inputs.append({"kind": "tzlocale", "id": "tzlocale:TZ", "name": "TZ"})
            else:
                inputs.append({"kind": "identity", "id": k})
    # files: the test's project files (data and code) changed between green and red -> commits that touch them
    paths = {p for p, _ in key["data"] if not p.startswith("/")}
    for sid in (key["content"], key["skeleton"], key["hooks"]):
        for fi in store["sets"][sid]:
            paths.add(store["files"][fi]["path"])
    commits = git(repo, "rev-list", "--first-parent", "--reverse", f"{green}..{red_head}").split()
    cands = []
    for c in commits:
        touched = set(git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--first-parent",
                          c).split())
        if touched & paths or any(any(t.startswith(p.rstrip("/") + "/") for t in touched)
                                  for p in paths if not os.path.splitext(p)[1]):
            cands.append(c)
    genv = node_env(vars0)
    renv = base_red
    # the job definitions differ only in the overrides: compare those (the base environment is the same machine)
    inputs, grouped = group_inputs(inputs, {k: v for k, v in vars0.items()}, {k: v for k, v in vars1.items()})
    if any(c["id"] == "env:*" for c in inputs):
        inputs = [c for c in inputs if c["id"] != "env:*"]
        named = {c["name"] for c in inputs if c["kind"] == "env"}
        inputs += [{"kind": "env", "id": f"env:{n}", "name": n} for n in sorted(set(vars0) | set(vars1))
                   if vars0.get(n) != vars1.get(n) and n not in named]
    res.update(commits_in_range=len(commits), commit_candidates=len(cands), input_candidates=[c["id"] for c in inputs],
               grouped_inputs=grouped)
    g_ident = (g["identity"] or {}).get("runtime", {}).get("digest")

    def replay(sha, env_over, why):
        checkout(repo, sha)
        x = run_file(repo, unit, env_over, name=pick)
        v = verdict(x, pick)
        st = {"sha": sha, "why": why, "outcome": v, "wall": round(x["wall"], 2)}
        rid = (x["identity"] or {}).get("runtime", {}).get("digest")
        if env_over == vars0:
            st["exact"] = rid == g_ident
        steps.append(st)
        return v

    culprit = None
    if cands and inputs:
        if replay(red_head, vars0, "red code, green environment") == "fail":
            inputs = []
        else:
            cands = []
    if cands:
        ev = vars0 if res["input_candidates"] else vars1
        lo, hi = -1, len(cands) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if replay(cands[mid], ev, "bisect candidates") == "fail":
                hi = mid
            else:
                lo = mid
        culprit = cands[hi]
    elif inputs:
        cur = list(inputs)
        while len(cur) > 1:
            half = cur[: len(cur) // 2]
            ev = dict(vars0)
            for c in half:
                ev[c["name"]] = vars1.get(c["name"])
            cur = half if replay(red_head, ev, f"apply {[c['id'] for c in half]}") == "fail" else cur[len(cur) // 2:]
        culprit = cur[0]["id"]
    ex = [s["exact"] for s in steps if "exact" in s]
    res["finder"] = {"culprit": culprit, "executions": len(steps), "steps": steps, "wall": round(time.perf_counter() - t0, 2),
                     "rebuilt_exactly": all(ex) if ex else None, "green_env_replays": len(ex)}
    res["finder_named"] = culprit
    res["finder_correct"] = culprit == truth
    # baseline: git bisect run with plain vitest in the red environment
    git(repo, "bisect", "reset", check=False)
    checkout(repo, red_head)
    counter = tempfile.mktemp()
    script = tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False)
    script.write(f"#!/bin/sh\necho x >> {counter}\nexec pnpm exec vitest run {unit} -t '^{re.escape(pick)}$' >/dev/null 2>&1\n")
    script.close()
    os.chmod(script.name, 0o755)
    t1 = time.perf_counter()
    sh(["git", "-C", str(repo), "bisect", "start", "--first-parent", red_head, green], env=renv)
    code, out = sh(["git", "-C", str(repo), "bisect", "run", script.name], cwd=repo, env=renv, timeout=7200)
    git(repo, "bisect", "reset", check=False)
    named = next((l.split()[0] for l in out.splitlines() if "is the first bad commit" in l), None)
    runs = sum(1 for _ in open(counter)) if os.path.exists(counter) else 0
    res["bisect"] = {"named": named, "executions": runs, "wall": round(time.perf_counter() - t1, 2)}
    res["bisect_correct"] = named is not None and truth.startswith(named[:12])
    checkout(repo, green)
    open(a.out, "a").write(json.dumps(res) + "\n")
    print(f"{cid}: truth {truth[:20]} finder {culprit} {'OK' if res['finder_correct'] else 'WRONG'} "
          f"exec={len(steps)} exact={res['finder']['rebuilt_exactly']} cands={res['input_candidates']} "
          f"commits={len(cands)}/{len(commits)} | bisect {named and named[:10]} "
          f"{'OK' if res['bisect_correct'] else 'WRONG'} exec={runs}", flush=True)


if __name__ == "__main__":
    main()
