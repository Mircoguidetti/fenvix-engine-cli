#!/usr/bin/env python3
"""Grader audit: is the SWE-bench Verified reward of the reference (gold) patch
a function of the patch alone?

Per task, inside SWE-bench's own prebuilt evaluation image (the exact
environment of the official harness), with gold patch + test patch applied and
the official test command (test files of the test patch):

  * 3 plain reruns (the official command, detpy plugin blocked);
  * under ``--det``: fixed order, ``--det-seed=1..N`` (order shuffle + random
    seeds + hash seed), and fixed order with the virtual clock started at a few
    special dates (``--det-epoch``);
  * reward = every FAIL_TO_PASS and PASS_TO_PASS test passes, graded with
    SWE-bench's own log parser for the repository;
  * when some --det configuration flips the reward while the plain reruns were
    stable: replay of the failing configuration, ablation (order only / all but
    order) and the first diverging event from the detpy verifier.

Subcommands:
  plan       -> matrix of batches (GitHub Actions) and the task list
  batch      -> run every task of one batch, commit each result back
  aggregate  -> summary.json + summary.md over results/<run_id>/
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRANCH = "claude/loving-maxwell-58mv2w"
DATASET = "princeton-nlp/SWE-bench_Verified"

# Virtual clock start dates (fixed order). "dst" also sets a POSIX TZ rule
# (works without tzdata) one second before the US spring-forward change.
EPOCHS = {
    "epoch-leapday": ("2024-02-29T23:59:59+00:00", None),
    "epoch-yearend": ("2025-12-31T23:59:59+00:00", None),
    "epoch-dst": ("2025-03-09T06:59:59+00:00", "EST5EDT,M3.2.0,M11.1.0"),
    "epoch-y2038": ("2038-01-19T03:14:07+00:00", None),
}
ALL_BUT_ORDER = "seeds,hashseed,bytecode,time,fs,net"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------------------
# Dataset and specs (swebench==4.0.4 on the host)

def load_instances() -> list[dict]:
    from datasets import load_dataset

    ds = load_dataset(DATASET, split="test")
    out = []
    for r in ds:
        r = dict(r)
        for k in ("FAIL_TO_PASS", "PASS_TO_PASS"):
            if isinstance(r[k], str):
                r[k] = json.loads(r[k])
        out.append(r)
    return out


def spec_of(inst: dict) -> dict:
    from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS

    return MAP_REPO_VERSION_TO_SPECS[inst["repo"]][inst["version"]]


def eligibility(inst: dict) -> str | None:
    """Reason a task cannot be measured by design, or None."""
    sp = spec_of(inst)
    if inst["repo"] == "django/django":
        return "test runner is Django's runtests.py, not pytest (detpy Level 0 is a pytest plugin)"
    py = tuple(int(x) for x in sp["python"].split("."))
    if py < (3, 9):
        return f"environment Python {sp['python']} < 3.9 (the detpy wheel is abi3-py39)"
    return None


def plan(run: dict, instances: list[dict]) -> dict:
    by_id = {i["instance_id"]: i for i in instances}
    discarded = {}
    eligible = []
    for i in instances:
        why = eligibility(i)
        if why:
            discarded[i["instance_id"]] = why
        else:
            eligible.append(i["instance_id"])
    if run.get("tasks"):
        tasks = [t for t in run["tasks"] if t in by_id]
    else:
        # Stratified sample: per repository, proportional with a minimum,
        # seeded shuffle inside each repository.
        n = int(run.get("sample", 100))
        rng = random.Random(int(run.get("sample_seed", 0)))
        per_repo = defaultdict(list)
        for t in sorted(eligible):
            per_repo[by_id[t]["repo"]].append(t)
        for v in per_repo.values():
            rng.shuffle(v)
        total = len(eligible)
        mn = int(run.get("min_per_repo", 5))
        alloc = {r: min(len(v), max(mn, round(n * len(v) / total))) for r, v in per_repo.items()}
        tasks = []
        for r in sorted(per_repo):
            tasks += per_repo[r][: alloc[r]]
        skip = set(run.get("exclude", []))
        tasks = [t for t in tasks if t not in skip]
        tasks += [t for t in run.get("extra", []) if t in by_id and t not in tasks]
    nb = max(1, int(run.get("batches", 20)))
    batches = [tasks[k::nb] for k in range(nb)]
    batches = [b for b in batches if b]
    return {"tasks": tasks, "batches": batches, "discarded_by_design": discarded,
            "eligible": len(eligible), "total": len(instances)}


# ---------------------------------------------------------------------------
# Docker helpers

def sh(cmd, timeout=None, check=False, capture=True):
    p = subprocess.run(cmd, shell=isinstance(cmd, str), timeout=timeout, text=True,
                       stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.STDOUT if capture else None, errors="replace")
    if check and p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {cmd}\n{(p.stdout or '')[-3000:]}")
    return p


class Container:
    def __init__(self, image: str, name: str):
        self.image, self.name = image, name

    def start(self):
        sh(["docker", "rm", "-f", self.name])
        # seccomp=unconfined: Docker's default profile forbids
        # personality(ADDR_NO_RANDOMIZE), which detpy's re-exec uses (LIMITS R3).
        sh(["docker", "run", "-d", "--name", self.name, "--security-opt", "seccomp=unconfined",
            "--entrypoint", "sleep", self.image, "infinity"], check=True)

    def put(self, path: str, content: str):
        tmp = Path("/tmp") / f"ga_{os.getpid()}_{abs(hash(path))}"
        tmp.write_text(content)
        sh(["docker", "cp", str(tmp), f"{self.name}:{path}"], check=True)
        tmp.unlink()

    def cp_in(self, src: str, dst: str):
        sh(["docker", "cp", src, f"{self.name}:{dst}"], check=True)

    def cp_out(self, src: str, dst: str) -> bool:
        return sh(["docker", "cp", f"{self.name}:{src}", dst]).returncode == 0

    def run(self, script: str, timeout: int, name="cmd") -> dict:
        path = f"/tmp/ga_{name}.sh"
        self.put(path, script)
        t0 = time.time()
        timed_out = False
        try:
            p = sh(["docker", "exec", self.name, "timeout", "-k", "15", str(timeout), "bash", path],
                   timeout=timeout + 60)
            out, rc = p.stdout or "", p.returncode
        except subprocess.TimeoutExpired as e:
            out, rc = (e.stdout or "") if isinstance(e.stdout, str) else "", -9
        if rc in (124, 137, -9):
            timed_out = True
        return {"rc": rc, "out": out, "dur": round(time.time() - t0, 1), "timed_out": timed_out}

    def stop(self):
        sh(["docker", "rm", "-f", self.name])


def pull(image_candidates: list[str]) -> tuple[str | None, str]:
    msgs = []
    for img in image_candidates:
        for attempt in range(3):
            p = sh(["docker", "pull", "-q", img], timeout=1800)
            if p.returncode == 0:
                return img, ""
            msgs.append(f"{img}: {(p.stdout or '').strip()[-200:]}")
            if "not found" in (p.stdout or "") or "manifest unknown" in (p.stdout or ""):
                break
            time.sleep(20 * (attempt + 1))
    return None, " | ".join(msgs)


# ---------------------------------------------------------------------------
# Grading

def make_grader(inst: dict, test_spec):
    from swebench.harness.grading import test_passed
    from swebench.harness.log_parsers import MAP_REPO_TO_PARSER

    parser = MAP_REPO_TO_PARSER[inst["repo"]]
    required = list(inst["FAIL_TO_PASS"]) + list(inst["PASS_TO_PASS"])

    def grade(output: str, pytest_names: bool = False) -> dict:
        if pytest_names:
            # sympy under pytest: SWE-bench names are bare function names.
            sm0 = parse_pytest_ra(output)
            sm = {}
            for nodeid, st in sm0.items():
                name = nodeid.split("::")[-1]
                prev = sm.get(name)
                if prev is None or st in ("FAILED", "ERROR"):
                    sm[name] = st
        else:
            sm = parser(output, test_spec)
        failing = [t for t in required if not test_passed(t, sm)]
        return {"reward": not failing, "failing": failing[:50], "n_failing": len(failing),
                "n_required": len(required), "n_parsed": len(sm)}

    return grade


def parse_pytest_ra(log_text: str) -> dict:
    sm = {}
    for line in log_text.split("\n"):
        for st in ("PASSED", "FAILED", "ERROR", "SKIPPED", "XFAIL", "XPASS"):
            if line.startswith(st + " "):
                if st == "FAILED":
                    line = line.replace(" - ", " ")
                parts = line.split()
                if len(parts) > 1:
                    sm[parts[1]] = st
                break
    return sm


# ---------------------------------------------------------------------------
# One task

def split_eval_script(test_spec) -> tuple[str, str, list[str]]:
    from swebench.harness.constants import START_TEST_OUTPUT

    lines = test_spec.eval_script_list
    marker = f": '{START_TEST_OUTPUT}'"
    k = lines.index(marker)
    setup = "\n".join(["#!/bin/bash", "set -uxo pipefail"] + lines[:k]) + "\n"
    test_cmd = lines[k + 1]
    sp = spec_of({"repo": test_spec.repo, "version": test_spec.version})
    prefix = ["source /opt/miniconda3/bin/activate", "conda activate testbed", "cd /testbed"]
    prefix += list(sp.get("eval_commands", []))
    return setup, test_cmd, prefix


def run_script(prefix: list[str], cmd: str, env: dict | None = None) -> str:
    lines = ["#!/bin/bash", "set +e"] + prefix
    for k, v in (env or {}).items():
        lines.append(f"export {k}={shlex.quote(v)}")
    lines.append(cmd)
    return "\n".join(lines) + "\n"


def tail(s: str, n=3000) -> str:
    return s[-n:] if s else ""


def detpy_verify(traces: list[str]) -> dict | None:
    try:
        from detpy import _core

        return json.loads(_core.verify(traces))
    except Exception as e:  # pragma: no cover
        return {"error": str(e)}


def run_task(inst: dict, wheel: str, cfg: dict, workdir: Path) -> dict:
    from swebench.harness.test_spec.test_spec import make_test_spec

    iid = inst["instance_id"]
    res: dict = {"instance_id": iid, "repo": inst["repo"], "version": inst["version"],
                 "n_fail_to_pass": len(inst["FAIL_TO_PASS"]), "n_pass_to_pass": len(inst["PASS_TO_PASS"]),
                 "status": "measured", "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    t_task = time.time()
    try:
        ts = make_test_spec(inst, namespace="swebench")
    except Exception as e:
        return {**res, "status": "discarded", "reason": f"test spec construction failed: {e}"}
    hub = ts.instance_image_key
    ghcr = f"ghcr.io/epoch-research/swe-bench.eval.x86_64.{iid}:latest"
    t0 = time.time()
    image, err = pull([hub, ghcr])
    res["pull_s"] = round(time.time() - t0, 1)
    if image is None:
        return {**res, "status": "discarded", "reason": f"image not available: {err[:400]}"}
    res["image"] = image
    grade = make_grader(inst, ts)
    c = Container(image, "ga_" + re.sub(r"[^a-zA-Z0-9_.-]", "_", iid))
    det_dir = "/tmp/det"
    try:
        c.start()
        setup, test_cmd, prefix = split_eval_script(ts)
        res["test_cmd"] = test_cmd
        info = c.run(run_script(prefix, "python -c 'import sys;print(sys.version.split()[0])'; "
                                        "python -c 'import pytest;print(pytest.__version__)' 2>/dev/null || echo none"),
                     120, "info")
        vals = info["out"].strip().split("\n")
        res["python"] = vals[-2] if len(vals) >= 2 else info["out"].strip()
        res["pytest_before"] = vals[-1] if vals else "?"
        pv = tuple(int(x) for x in res["python"].split(".")[:2]) if re.match(r"^\d+\.\d+", res["python"]) else (0, 0)
        if pv < (3, 9):
            return {**res, "status": "discarded", "reason": f"image Python {res['python']} < 3.9"}
        # Gold patch (SWE-bench's own apply sequence).
        c.put("/tmp/gold.diff", inst["patch"])
        applied = False
        for cmd in ("git apply --verbose", "git apply --verbose --reject", "patch --batch --fuzz=5 -p1 -i"):
            r = c.run(run_script(["cd /testbed"], f"{cmd} /tmp/gold.diff"), 300, "apply")
            if r["rc"] == 0:
                applied = True
                res["gold_apply"] = cmd
                break
        if not applied:
            return {**res, "status": "discarded", "reason": "gold patch did not apply"}
        r = c.run(setup, 3600, "setup")
        res["setup_s"] = r["dur"]
        res["setup_rc"] = r["rc"]
        if "git apply" in setup and ("error: patch failed" in r["out"] or "error: corrupt patch" in r["out"]):
            return {**res, "status": "discarded", "reason": "test patch did not apply", "setup_tail": tail(r["out"])}
        # detpy wheel (no deps: never touch the pytest under test).
        c.cp_in(wheel, "/tmp/" + os.path.basename(wheel))
        sympy = inst["repo"] == "sympy/sympy"
        extra_install = "python -m pip install -q --no-deps /tmp/" + os.path.basename(wheel)
        if sympy:
            extra_install = ("python -c 'import pytest' 2>/dev/null || python -m pip install -q 'pytest>=7,<9'; "
                             + extra_install)
        r = c.run(run_script(prefix, extra_install + "; python -c 'import detpy, pytest; print(pytest.__version__)'"),
                  900, "detpy")
        if r["rc"] != 0:
            return {**res, "status": "discarded", "reason": "detpy wheel install failed", "tail": tail(r["out"])}
        res["pytest"] = r["out"].strip().split("\n")[-1]

        if sympy:
            directives = test_cmd.split("--verbose", 1)[1].strip()
            det_base = ("PYTHONWARNINGS='ignore::UserWarning,ignore::SyntaxWarning' "
                        f"python -m pytest -rA -p no:cacheprovider {directives}")
        else:
            det_base = test_cmd
        pyt_names = sympy

        runs: dict = {}

        def plain(label: str, cmd: str, timeout: int, names: bool):
            r = c.run(run_script(prefix, cmd + ("" if cmd.startswith("PYTHONWARNINGS") and "bin/test" in cmd
                                                 else " -p no:detpy")), timeout, label)
            g = grade(r["out"], names)
            runs[label] = {"kind": "plain", **g, "rc": r["rc"], "dur": r["dur"], "timed_out": r["timed_out"]}
            if not g["reward"]:
                runs[label]["tail"] = tail(r["out"], 1500)
            log(iid, label, "reward", g["reward"], f"{r['dur']}s", "failing", g["n_failing"])
            return r

        def det(label: str, args: str, timeout: int, env: dict | None = None, keep_trace=True):
            trace = f"{det_dir}/{label}.jsonl"
            outc = f"{det_dir}/{label}.out.json"
            cmd = f"mkdir -p {det_dir}; {det_base} --det --det-trace={trace} --det-outcomes={outc} {args}"
            r = c.run(run_script(prefix, cmd, env), timeout, label)
            g = grade(r["out"], pyt_names)
            ent = {"kind": "det", "args": args, **g, "rc": r["rc"], "dur": r["dur"], "timed_out": r["timed_out"]}
            if env:
                ent["env"] = env
            hdr = [ln for ln in r["out"].split("\n") if ln.startswith("detpy")][:4]
            ent["header"] = hdr
            if not g["reward"]:
                ent["tail"] = tail(r["out"], 1500)
                # exception of each failing required test, from the outcomes file
                local = workdir / f"{label}.out.json"
                if c.cp_out(outc, str(local)):
                    try:
                        o = json.loads(local.read_text())
                        exc = o.get("exceptions", {})
                        ent["exceptions"] = {k: v for k, v in exc.items()
                                             if any(k == f or k.endswith("::" + f) or k.startswith(f) for f in g["failing"][:20])}
                        ent["exceptions"] = dict(list(ent["exceptions"].items())[:10])
                    except Exception:
                        pass
            runs[label] = ent
            log(iid, label, "reward", g["reward"], f"{r['dur']}s", "failing", g["n_failing"])
            return r

        # 1. Plain reruns (the official command).
        first = plain("plain-1", test_cmd if not sympy else test_cmd, int(cfg.get("first_timeout", 1800)), False if not sympy else False)
        T = max(5.0, first["dur"])
        run_to = int(min(2400, max(300, 6 * T)))
        res["run_timeout_s"] = run_to
        for k in (2, 3):
            plain(f"plain-{k}", test_cmd, run_to, False)
        if sympy:
            # The official sympy grader is bin/test; --det needs pytest, so the
            # plain baseline used for comparisons is pytest on the same files.
            for k in (1, 2, 3):
                plain(f"plain-pytest-{k}", det_base, run_to, True)
            base_labels = ["plain-pytest-1", "plain-pytest-2", "plain-pytest-3"]
        else:
            base_labels = ["plain-1", "plain-2", "plain-3"]
        official = [runs[f"plain-{k}"]["reward"] for k in (1, 2, 3)]
        baseline = [runs[l]["reward"] for l in base_labels]
        res["official_plain_rewards"] = official
        res["baseline_rewards"] = baseline
        if not any(baseline):
            res["status"] = "discarded"
            res["reason"] = "reference reward 0 in all 3 plain runs (environment does not reproduce the gold result)"
            res["runs"] = runs
            return res

        # 2. --det configurations, within the task budget.
        budget = float(cfg.get("task_budget_s", 2700))
        spent = time.time() - t_task
        det_cost = T * 1.3 + 10
        max_seeds = int(cfg.get("seeds", 20))
        n_epochs = len(EPOCHS)
        avail = max(0.0, budget - spent) / det_cost
        n_seeds = int(max(3, min(max_seeds, avail - 1 - n_epochs - 4)))
        res["seeds_planned"] = n_seeds
        det("det-fixed", "", run_to)
        for s in range(1, n_seeds + 1):
            det(f"det-seed-{s}", f"--det-seed={s}", run_to)
        for label, (iso, tz) in EPOCHS.items():
            det(label, f"--det-epoch={iso}", run_to, {"TZ": tz} if tz else None)
        det_labels = [l for l in runs if runs[l]["kind"] == "det"]
        det_rewards = {l: runs[l]["reward"] for l in det_labels}
        res["det_rewards"] = det_rewards
        res["seeds_run"] = n_seeds

        plain_stable = len(set(baseline)) == 1
        det_vals = set(det_rewards.values())
        res["baseline_reward_stable"] = plain_stable
        res["official_reward_stable"] = len(set(official)) == 1
        res["det_reward_stable"] = len(det_vals) == 1
        res["broken_by_det"] = plain_stable and all(baseline) and det_vals == {False}
        res["hidden_instability"] = plain_stable and all(baseline) and det_vals == {True, False}
        res["visible_instability"] = not plain_stable

        # 3. Flip analysis.
        if det_vals == {True, False} or res["broken_by_det"]:
            analysis: dict = {}
            failing_cfgs = [l for l in det_labels if not det_rewards[l]]
            passing_cfgs = [l for l in det_labels if det_rewards[l]]
            analysis["failing_configs"] = failing_cfgs
            fc = failing_cfgs[0]
            # Replay: the same configuration must give the same reward.
            replay = []
            for k in (1, 2):
                lab = f"replay-{k}-{fc}"
                det(lab, runs[fc]["args"], run_to, runs[fc].get("env"))
                replay.append(runs[lab]["reward"])
            analysis["replay_config"] = fc
            analysis["replay_rewards"] = replay
            analysis["replay_reproduces"] = not any(replay)
            if fc.startswith("det-seed-"):
                det(f"ablate-order-only-{fc}", runs[fc]["args"] + f" --det-disable={ALL_BUT_ORDER}", run_to)
                det(f"ablate-no-order-{fc}", runs[fc]["args"] + " --det-disable=order", run_to)
                analysis["order_only_fails"] = not runs[f"ablate-order-only-{fc}"]["reward"]
                analysis["no_order_fails"] = not runs[f"ablate-no-order-{fc}"]["reward"]
            if res["broken_by_det"]:
                causes = []
                for ctl in ("time", "net", "fs", "seeds", "hashseed", "bytecode", "order"):
                    lab = f"ablate-disable-{ctl}"
                    det(lab, f"--det-disable={ctl}", run_to)
                    if runs[lab]["reward"]:
                        causes.append(ctl)
                analysis["broken_cause_controls"] = causes or ["unexplained"]
            # First diverging event between a passing and a failing trace.
            if passing_cfgs:
                pc = "det-fixed" if "det-fixed" in passing_cfgs else passing_cfgs[0]
                a, b = workdir / f"{pc}.jsonl", workdir / f"{fc}.jsonl"
                if c.cp_out(f"{det_dir}/{pc}.jsonl", str(a)) and c.cp_out(f"{det_dir}/{fc}.jsonl", str(b)):
                    rep = detpy_verify([str(a), str(b)]) or {}
                    divs = {}
                    req = set(runs[fc]["failing"])
                    for t in rep.get("tests", []):
                        nid = t["nodeid"]
                        name = nid.split("::")[-1] if pyt_names else nid
                        if name in req or nid in req or any(nid.startswith(x) for x in req):
                            divs[nid] = {"status": t["status"], "outcomes": t["outcomes"],
                                         "divergence": t.get("divergence")}
                    analysis["verify_pair"] = [pc, fc]
                    analysis["divergences"] = dict(list(divs.items())[:10])
                    analysis["verify_summary"] = rep.get("summary")
                    # position of the failing tests in each order
                    analysis["order_positions"] = {}
                    for lab, path in ((pc, a), (fc, b)):
                        try:
                            with open(path) as f:
                                head = json.loads(f.readline())
                            order = head.get("order", [])
                            analysis["order_positions"][lab] = {n: order.index(n) for n in divs if n in order}
                            analysis["order_len"] = len(order)
                        except Exception:
                            pass
            res["analysis"] = analysis
        res["runs"] = runs
        return res
    except Exception as e:
        import traceback

        res["status"] = "error"
        res["reason"] = f"{type(e).__name__}: {e}"[:1000]
        res["traceback"] = traceback.format_exc()[-3000:]
        return res
    finally:
        res["task_s"] = round(time.time() - t_task, 1)
        c.stop()
        if cfg.get("remove_images", True):
            sh(["docker", "rmi", "-f", image or hub])
            sh("docker image prune -f")


# ---------------------------------------------------------------------------
# Commit back (rebase-safe: the index is reset to the remote tip, only our
# files are added; never forced)

def commit_back(paths: list[str], msg: str, tries: int = 12):
    if os.environ.get("GA_NO_COMMIT"):
        return True
    root = sh("git rev-parse --show-toplevel").stdout.strip()
    for k in range(tries):
        sh(["git", "-C", root, "fetch", "-q", "--depth=1", "origin", BRANCH])
        sh(["git", "-C", root, "reset", "-q", "--mixed", "FETCH_HEAD"])
        sh(["git", "-C", root, "add", "-f", *paths])
        if sh(["git", "-C", root, "diff", "--cached", "--quiet"]).returncode == 0:
            return True
        sh(["git", "-C", root, "commit", "-q", "-m", msg])
        p = sh(["git", "-C", root, "push", "-q", "origin", f"HEAD:refs/heads/{BRANCH}"])
        if p.returncode == 0:
            return True
        log("push rejected, retrying", (p.stdout or "")[-300:])
        time.sleep(random.uniform(5, 30) * (1 + k / 3))
    return False


# ---------------------------------------------------------------------------
# Aggregate

def aggregate(run_id: str) -> dict:
    d = HERE / "results" / run_id
    rows = []
    for f in sorted(d.glob("*.json")):
        if f.name in ("summary.json", "plan.json"):
            continue
        try:
            rows.append(json.loads(f.read_text()))
        except Exception:
            pass
    planf = d / "plan.json"
    pl = json.loads(planf.read_text()) if planf.exists() else {}
    measured = [r for r in rows if r.get("status") == "measured"]
    disc = [r for r in rows if r.get("status") != "measured"]
    hidden = [r for r in measured if r.get("hidden_instability")]
    broken = [r for r in measured if r.get("broken_by_det")]
    visible = [r for r in measured if r.get("visible_instability")]
    official_visible = [r for r in measured if r.get("official_reward_stable") is False]
    stable_plain = [r for r in measured if r.get("baseline_reward_stable") and all(r.get("baseline_rewards", []))]

    def cause(r):
        a = r.get("analysis", {})
        fcs = a.get("failing_configs", [])
        kinds = set()
        for f in fcs:
            if f.startswith("det-seed"):
                kinds.add("seed")
            elif f.startswith("epoch"):
                kinds.add("clock")
            elif f == "det-fixed":
                kinds.add("fixed")
        return sorted(kinds)

    summary = {
        "run_id": run_id,
        "planned": len(pl.get("tasks", [])),
        "results": len(rows),
        "measured": len(measured),
        "discarded_runtime": len(disc),
        "discarded_runtime_reasons": Counter((r.get("reason") or "?").split(":")[0][:90] for r in disc),
        "plain_stable_pass": len(stable_plain),
        "visible_instability_baseline": len(visible),
        "visible_instability_official": len(official_visible),
        "hidden_instability": len(hidden),
        "broken_by_det": len(broken),
        "hidden_share_of_measured": round(len(hidden) / len(measured), 4) if measured else None,
        "hidden_share_of_plain_stable": round(len(hidden) / len(stable_plain), 4) if stable_plain else None,
        "per_repo": {},
        "hidden": [{"instance_id": r["instance_id"], "configs": r["analysis"]["failing_configs"],
                    "kinds": cause(r), "replay_reproduces": r["analysis"].get("replay_reproduces"),
                    "order_only_fails": r["analysis"].get("order_only_fails"),
                    "no_order_fails": r["analysis"].get("no_order_fails"),
                    "failing": r["runs"][r["analysis"]["failing_configs"][0]]["failing"][:5],
                    "divergences": {k: (v.get("divergence") or {}).get("description")
                                    for k, v in (r["analysis"].get("divergences") or {}).items()},
                    "reasons": {k: (v.get("divergence") or {}).get("reason")
                                for k, v in (r["analysis"].get("divergences") or {}).items()},
                    "exceptions": r["runs"][r["analysis"]["failing_configs"][0]].get("exceptions")}
                   for r in hidden],
        "broken": [{"instance_id": r["instance_id"], "causes": r.get("analysis", {}).get("broken_cause_controls"),
                    "failing": r["runs"]["det-fixed"]["failing"][:5],
                    "exceptions": r["runs"]["det-fixed"].get("exceptions"),
                    "pytest": r.get("pytest")} for r in broken],
        "visible": [{"instance_id": r["instance_id"], "baseline": r.get("baseline_rewards"),
                     "official": r.get("official_plain_rewards"), "det_stable": r.get("det_reward_stable"),
                     "det_rewards_false": [k for k, v in r.get("det_rewards", {}).items() if not v]}
                    for r in visible],
        "discarded": [{"instance_id": r["instance_id"], "reason": r.get("reason")} for r in disc],
        "seeds_run": Counter(r.get("seeds_run") for r in measured),
    }
    per = defaultdict(Counter)
    for r in rows:
        p = per[r["repo"]]
        p["results"] += 1
        p[r.get("status")] += 1
        if r.get("status") == "measured":
            p["hidden"] += bool(r.get("hidden_instability"))
            p["broken"] += bool(r.get("broken_by_det"))
            p["visible"] += bool(r.get("visible_instability"))
    summary["per_repo"] = {k: dict(v) for k, v in sorted(per.items())}
    summary["discarded_runtime_reasons"] = dict(summary["discarded_runtime_reasons"])
    summary["seeds_run"] = {str(k): v for k, v in summary["seeds_run"].items()}
    (d / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True))
    return summary


# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--run", default=str(HERE / "run.json"))
    p.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    p.add_argument("--write", action="store_true", help="write results/<run_id>/plan.json and commit it")
    b = sub.add_parser("batch")
    b.add_argument("--run", default=str(HERE / "run.json"))
    b.add_argument("--index", type=int, required=True)
    b.add_argument("--wheel", required=True)
    a = sub.add_parser("aggregate")
    a.add_argument("--run", default=str(HERE / "run.json"))
    a.add_argument("--commit", action="store_true")
    args = ap.parse_args(argv)
    run = json.loads(Path(args.run).read_text())
    rid = run["run_id"]
    out_dir = HERE / "results" / rid
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.cmd == "plan":
        inst = load_instances()
        pl = plan(run, inst)
        log(f"{len(pl['tasks'])} tasks in {len(pl['batches'])} batches; eligible {pl['eligible']}/{pl['total']}")
        if args.github_output:
            with open(args.github_output, "a") as f:
                f.write(f"matrix={json.dumps(list(range(len(pl['batches']))))}\n")
        if args.write:
            meta = {i["instance_id"]: {"repo": i["repo"], "version": i["version"],
                                       "python": spec_of(i)["python"],
                                       "n_f2p": len(i["FAIL_TO_PASS"]), "n_p2p": len(i["PASS_TO_PASS"])}
                    for i in inst}
            (out_dir / "plan.json").write_text(json.dumps({**pl, "run": run}, indent=1))
            (HERE / "data").mkdir(exist_ok=True)
            (HERE / "data" / "verified_index.json").write_text(json.dumps(meta, indent=0, sort_keys=True))
            commit_back([str(out_dir / "plan.json"), str(HERE / "data" / "verified_index.json")],
                        f"Grader audit: plan for run {rid}")
        return 0

    if args.cmd == "batch":
        inst = load_instances()
        by_id = {i["instance_id"]: i for i in inst}
        pl = plan(run, inst)
        batch = pl["batches"][args.index]
        cfg = run.get("config", {})
        deadline = time.time() + float(cfg.get("job_budget_s", 19800))
        for iid in batch:
            outf = out_dir / f"{iid}.json"
            if outf.exists() and not run.get("rerun_existing"):
                log("skip existing", iid)
                continue
            if time.time() + 600 > deadline:
                res = {"instance_id": iid, "repo": by_id[iid]["repo"], "version": by_id[iid]["version"],
                       "status": "not-run", "reason": "job time budget exhausted"}
            else:
                log("=== task", iid)
                wd = Path("/tmp/ga_work") / iid
                shutil.rmtree(wd, ignore_errors=True)
                wd.mkdir(parents=True)
                res = run_task(by_id[iid], args.wheel, cfg, wd)
            outf.write_text(json.dumps(res, indent=1, sort_keys=True))
            log("result", iid, res.get("status"), res.get("reason", ""), "hidden", res.get("hidden_instability"),
                "broken", res.get("broken_by_det"))
            commit_back([str(outf)], f"Grader audit ({rid}): {iid} {res.get('status')}")
        return 0

    if args.cmd == "aggregate":
        if not args.commit:
            s = aggregate(rid)
            print(json.dumps({k: v for k, v in s.items() if not isinstance(v, list)}, indent=1))
            return 0
        root = sh("git rev-parse --show-toplevel").stdout.strip()
        sh(["git", "-C", root, "fetch", "-q", "--depth=1", "origin", BRANCH])
        sh(["git", "-C", root, "checkout", "-q", "FETCH_HEAD", "--", f"harness/grader_audit/results/{rid}"])
        s = aggregate(rid)
        print(json.dumps({k: v for k, v in s.items() if not isinstance(v, list)}, indent=1))
        commit_back([str(out_dir / "summary.json")], f"Grader audit ({rid}): summary")
        return 0


if __name__ == "__main__":
    sys.exit(main())
