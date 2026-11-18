#!/usr/bin/env python3
"""No-code reds (cases of kind c): the realistic CI changes of the head-to-head, one at a time and with a decoy.

Each scenario uses the head-to-head window of its project (11 commits; the change landed at position 3, i.e. right
after commit w[2]) and the two frozen environments the head-to-head recorded (``freeze`` 0 = before, 1 = after).

* green: commit w[2], environment before the change;
* red:   commit w[10], environment after the change (and, for a data edit, the edit committed right after w[2] and
         kept in every replayed later commit, as in the head-to-head);
* red test: a test of a file the head-to-head saw break, that fails at red, passes at green and passes at red
  without the change (so the change is the cause; checked here, not assumed);
* decoy: a second change that lands together with the real one and does not break the red test (checked): the time
  zone of the CI job (TZ=Asia/Kolkata) or an older pluggy (1.6.0), a distribution every pytest run loads.

Truth: ``env:<VAR>``, ``dist:<name>`` or the edit commit. The finder rebuilds the green environment from the green
key's distribution list (never from the head-to-head's freeze) and reports whether the rebuilt runtime digest equals
the green key's. Baseline: ``git bisect run`` with plain pytest in the red environment.

    nocode.py --scenario NAME [--decoy none|tz|dep] --out results.jsonl
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ENGINE, checkout, git, git_bisect, run_det, run_plain, sh  # noqa: E402
from finder import EnvBuilder, Finder  # noqa: E402
from mutants import commit  # noqa: E402

WORK = Path(os.environ.get("CULPRIT_WORK", "/home/user/work"))
WHEEL = os.environ.get("CULPRIT_WHEEL", str(next((WORK / "wheels2").glob("detpy-*.whl"), "")))
H2H = "origin/claude/sweet-mendel-rtdg7f:harness/skip_study2/headtohead/"
URLS = {"flask": "pallets/flask", "structlog": "hynek/structlog", "jinja": "pallets/jinja",
        "werkzeug": "pallets/werkzeug", "sqlparse": "andialbrecht/sqlparse", "pygments": "pygments/pygments",
        "boltons": "mahmoud/boltons", "toolz": "pytoolz/toolz", "click": "pallets/click",
        "home-assistant": "home-assistant/core"}
SCEN = {  # name: (project, arm, result run, shard)
    "flask-dep": ("flask", "ci-dep", "h4", "0o1"), "flask-data": ("flask", "ci-data", "h4", "0o1"),
    "structlog-dep": ("structlog", "ci-dep", "h4", "0o1"), "jinja-data": ("jinja", "ci-data", "h4", "0o1"),
    "werkzeug-data": ("werkzeug", "ci-data", "h4", "0o1"), "sqlparse-data": ("sqlparse", "ci-data", "h4", "0o1"),
    "pygments-data": ("pygments", "ci-data", "h4", "0o1"), "boltons-env": ("boltons", "ci-env", "h5", "0o1"),
    "pygments-env": ("pygments", "ci-env", "h5", "0o1"), "sqlparse-env": ("sqlparse", "ci-env", "h5", "0o1"),
    "toolz-env": ("toolz", "ci-env", "h5", "0o1"), "click-env": ("click", "ci-env", "h4", "0o1"),
    "home-assistant-data": ("home-assistant", "ci-data", "h4", "1o8"),
}


def h2h_result(run, name, shard):
    raw = subprocess.run(["git", "-C", str(ENGINE), "show", f"{H2H}results/{run}/{name}-{shard}.json.gz"],
                         capture_output=True, check=True).stdout
    return json.loads(gzip.decompress(raw))


def h2h_changes(project, arm):
    raw = subprocess.run(["git", "-C", str(ENGINE), "show", f"{H2H}changes.json"], capture_output=True,
                         check=True).stdout
    return json.loads(raw)[project][arm.split("-", 1)[1]]


def ensure_repo(project) -> Path:
    d = WORK / "repos-c" / project
    if not d.exists():
        d.parent.mkdir(parents=True, exist_ok=True)
        sh(["git", "clone", "-q", f"https://github.com/{URLS[project]}", str(d)], check=True, timeout=1800)
    return d


def freeze_venv(repo: Path, name: str | None, freeze: list[str], python: str, at: Path | None = None) -> Path:
    venv = at or WORK / "venvs-c" / name
    if (venv / ".ok").exists():
        return venv
    sh(["uv", "venv", "-q", "--python", python, str(venv)], check=True)
    pins = [x for x in freeze if "==" in x and not x.startswith(("-e", "Using"))]
    req = venv / "freeze.txt"
    req.write_text("\n".join(pins) + "\n")
    sh(["uv", "pip", "install", "-q", "--python", str(venv / "bin" / "python"), "--no-deps", "-r", str(req), WHEEL],
       cwd=repo, check=True, timeout=3600)
    sh(["uv", "pip", "install", "-q", "--python", str(venv / "bin" / "python"), "--no-deps", "-e", "."], cwd=repo,
       check=True, timeout=1800)
    (venv / ".ok").write_text("ok")
    return venv


def edit_tree_commits(repo, base, later, edits, cid) -> tuple[str, str]:
    """Commit the data edit right after ``base`` and replay ``later`` with it (new commits)."""
    def tree(sha):
        with tempfile.TemporaryDirectory() as td:
            env = {**os.environ, "GIT_INDEX_FILE": os.path.join(td, "index")}
            subprocess.run(["git", "-C", str(repo), "read-tree", sha], env=env, check=True)
            for e in edits:
                text = subprocess.run(["git", "-C", str(repo), "show", f"{sha}:{e['path']}"], capture_output=True,
                                      check=True).stdout.decode()
                a, b = e["replace"]
                assert a in text, (sha, e["path"])
                text = text.replace(a, b, 1)
                blob = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input=text.encode(),
                                      capture_output=True, check=True).stdout.decode().strip()
                mode = git(repo, "ls-tree", sha, "--", e["path"]).split()[0]
                subprocess.run(["git", "-C", str(repo), "update-index", "--cacheinfo", f"{mode},{blob},{e['path']}"],
                               env=env, check=True)
            return subprocess.run(["git", "-C", str(repo), "write-tree"], env=env, capture_output=True, check=True,
                                  text=True).stdout.strip()

    m = commit(repo, tree(base), base, f"fixture edit {cid}", None)
    prev = m
    for sha in later:
        prev = commit(repo, tree(sha), prev, subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%B", sha],
                                                            capture_output=True, text=True).stdout, sha)
    git(repo, "update-ref", f"refs/culprit/{cid}", prev)
    return m, prev


def failing_tests(repo, venv, unit, env) -> set[str]:
    code, out, _ = run_plain(repo, venv, ["-q", "--tb=no", "-rfE", "-p", "no:randomly", unit], env)
    return {l.split(" ", 1)[1].split(" - ", 1)[0].strip() for l in out.splitlines()
            if l.startswith(("FAILED ", "ERROR ")) and "::" in l}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--decoy", default="none", choices=["none", "tz", "dep"])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    project, arm, run, shard = SCEN[a.scenario]
    cid = f"{a.scenario}-{a.decoy}"
    if os.path.exists(a.out) and any(json.loads(l)["id"] == cid for l in open(a.out)):
        return
    d = h2h_result(run, f"{project}-{arm}", shard)
    ch = h2h_changes(project, arm)
    py = d["spec"].get("py_minor") or "3.13"
    w = [c["sha"] for c in sorted(d["commits"], key=lambda c: int(c["i"]))]
    green, later = w[2], [x for x in w[4:] if x != w[2]]
    repo = ensure_repo(project)
    git(repo, "fetch", "-q", "origin", *w, check=False, timeout=900)
    checkout(repo, green)
    freeze = d.get("freeze") or {}
    if not freeze:
        # the head-to-head recorded no freeze for this arm (environment variables only): resolve the project's own
        # test requirements once at the green commit and freeze them, so both sides use the same distributions
        tmpv = WORK / "venvs-c" / f"{a.scenario}-resolve"
        if not (tmpv / ".ok").exists():
            sys.path.insert(0, str(ENGINE / "harness"))
            from detpy_harness import detect_install
            sh(["uv", "venv", "-q", "--python", py, str(tmpv)], check=True)
            args, groups, reqs = detect_install(repo)
            sh(["uv", "pip", "install", "-q", "--python", str(tmpv / "bin" / "python"), *args, *groups, *reqs,
                "pytest"], cwd=repo, check=True, timeout=1800)
            (tmpv / ".ok").write_text("ok")
        code, out = sh(["uv", "pip", "freeze", "--python", str(tmpv / "bin" / "python")])
        freeze = {"0": [l for l in out.splitlines() if "==" in l and not l.startswith("-e")]}
    e0 = freeze_venv(repo, f"{a.scenario}-0", freeze.get("0") or freeze.get(0), py) if freeze else None
    e1 = freeze_venv(repo, f"{a.scenario}-1", freeze.get("1"), py) if freeze.get("1") else e0
    vars0, vars1 = {}, dict(ch.get("env") or {})
    truth, red_head = None, w[-1]
    if arm == "ci-data":
        truth, red_head = edit_tree_commits(repo, green, later, ch["edits"], cid)
    elif arm == "ci-env":
        truth = "env:" + next(iter(ch["env"]))
    else:
        truth = "dist:" + ch["pins1"][0].split("==")[0].lower()
    # decoy
    decoy = None
    if a.decoy == "tz":
        vars1["TZ"] = "Asia/Kolkata"
        decoy = "tzlocale:TZ"
    elif a.decoy == "dep":
        decoy = "dist:pluggy"
    t = [x for x in d["transitions"] if str(x["i"]) == "3"][0]
    units = sorted(t.get("fresh_bad") or [])
    res = {"id": cid, "scenario": a.scenario, "decoy": decoy, "truth": truth, "what": ch["what"], "units": units}
    if not units:
        res["skip"] = "the head-to-head saw no broken test file for this change"
        with open(a.out, "a") as fh:
            fh.write(json.dumps(res) + "\n")
        print(cid, res["skip"])
        return
    e1d = e1
    if a.decoy == "dep":
        # red environment = after the change + pluggy 1.6.0 (a separate venv, built from the after-freeze)
        fr = [x if not x.lower().startswith("pluggy==") else "pluggy==1.6.0" for x in (freeze.get("1") or freeze["0"])]
        e1d = freeze_venv(repo, f"{a.scenario}-1-dep", fr, py)
    # red test: fails at red (change + decoy), passes at green, passes at red without the change
    checkout(repo, red_head)
    red_fail = set()
    for u in units[:6]:
        red_fail |= failing_tests(repo, e1d, u, vars1)
    checkout(repo, green)
    green_fail = set()
    for u in units[:6]:
        green_fail |= failing_tests(repo, e0, u, vars0)
    pick = None
    for nid in sorted(red_fail - green_fail)[:20]:
        checkout(repo, green)
        if run_det(repo, e0, nid, vars0)["outcome"] != "pass":
            continue
        checkout(repo, w[-1])  # red code without the change (no edit), green environment
        if run_det(repo, e0, nid, vars0)["outcome"] != "pass":
            continue
        if decoy:  # the decoy alone does not break it
            env_d = dict(vars0)
            if a.decoy == "tz":
                env_d["TZ"] = "Asia/Kolkata"
            venv_d = e0
            if a.decoy == "dep":
                f0 = [x if not x.lower().startswith("pluggy==") else "pluggy==1.6.0" for x in (freeze.get("0") or [])]
                venv_d = freeze_venv(repo, f"{a.scenario}-0-dep", f0, py)
            if run_det(repo, venv_d, nid, env_d)["outcome"] != "pass":
                continue
        checkout(repo, red_head)
        if run_det(repo, e1d, nid, vars1)["outcome"] != "fail":
            continue
        pick = nid
        break
    if pick is None:
        res["skip"] = (f"no red test that only the change breaks (red failures: {len(red_fail)}, "
                       f"also red at green: {len(red_fail & green_fail)})")
        with open(a.out, "a") as fh:
            fh.write(json.dumps(res) + "\n")
        print(cid, res["skip"])
        return
    res["red_test"] = pick
    kd = WORK / "keys-c"
    kd.mkdir(exist_ok=True)
    gk, rk = str(kd / f"{cid}-green.json"), str(kd / f"{cid}-red.json")
    # the CI job's virtualenv lives at one fixed path for both runs (console scripts embed the path)
    f0 = list(freeze.get("0") or [])
    f1 = list(freeze.get("1") or f0)
    if a.decoy == "dep":
        f1 = [x if not x.lower().startswith("pluggy==") else "pluggy==1.6.0" for x in f1]
    ci = WORK / "ci" / cid
    import shutil

    def ci_venv(fr):
        shutil.rmtree(ci, ignore_errors=True)
        checkout(repo, green)
        return freeze_venv(repo, None, fr, py, at=ci)

    v = ci_venv(f0)
    checkout(repo, green)
    res["green_run"] = run_det(repo, v, pick, vars0, keys=gk)["outcome"]
    v = ci_venv(f1)
    checkout(repo, red_head)
    res["red_run"] = run_det(repo, v, pick, vars1, keys=rk)["outcome"]
    shutil.rmtree(ci, ignore_errors=True)  # the CI machine is gone
    builder = EnvBuilder(["-e", "."], WHEEL, str(WORK / "rebuilt"), python=py)
    f = Finder(repo, pick, {"sha": green, "env": vars0, "venv": None, "key": gk, "prefix": str(ci)},
               {"sha": red_head, "env": vars1, "venv": e1d, "key": rk}, builder=builder)
    try:
        fr = f.run()
    except Exception as e:
        fr = {"culprit": None, "why": f"error: {type(e).__name__}: {e}", "executions": len(f.steps), "steps": f.steps}
    finally:
        shutil.rmtree(ci, ignore_errors=True)
    c = fr.get("culprit") or {}
    named = c.get("commit") or c.get("input")
    res["finder"] = fr
    res["finder_named"] = named
    res["finder_correct"] = named == truth
    b = git_bisect(repo, e1d, green, red_head, ["--tb=no", "-p", "no:randomly", pick], extra_env=vars1)
    res["bisect"] = b
    res["bisect_correct"] = b["named"] is not None and truth.startswith(b["named"][:12])
    checkout(repo, green)
    with open(a.out, "a") as fh:
        fh.write(json.dumps(res) + "\n")
    print(f"{cid}: truth {truth[:20]} finder {named and named[:30]} {'OK' if res['finder_correct'] else 'WRONG'} "
          f"exec={fr.get('executions')} exact={fr.get('rebuilt_exactly')} cands={fr.get('input_candidates')} "
          f"commits={fr.get('commit_candidates')}/{fr.get('commits_in_range')} | bisect {b['named'] and b['named'][:10]} "
          f"{'OK' if res['bisect_correct'] else 'WRONG'} exec={b['executions']}", flush=True)


if __name__ == "__main__":
    main()
