"""F-02 / F-18: one ``fenvix`` command (G-0234, G-0272, G-1534, G-1555, G-0448 family for Python, G-1554, G-1861,
G-1862, G-1863, G-1970, G-1995, G-2203, G-2204, G-2205, G-2209, G-2020, G-0697, G-0698, G-0699).

``fenvix`` is installed as a console script with the Python package; ``fenvix repro|explore|replay|verify`` reach
the defect workflow; repro prints the cause, the seed and order, and the replay command; the runner adapters other
than pytest say plainly that they are not built yet.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FX = [sys.executable, "-m", "detpy.fenvix"]
ROOT = Path(__file__).resolve().parent.parent

PROJECT = '''
STATE = {}

def test_a():
    pass

def test_polluter():
    STATE["x"] = 1

def test_b():
    pass

def test_victim():
    assert "x" not in STATE

def test_c():
    pass
'''


def _env() -> dict:
    env = dict(os.environ)
    for k in ("PYTEST_ADDOPTS", "PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID"):
        env.pop(k, None)
    return env


def fx(*args, cwd=None, timeout=900):
    return subprocess.run([*FX, *args], cwd=cwd, env=_env(), capture_output=True, text=True, timeout=timeout)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_o.py").write_text(PROJECT)
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -p no:cacheprovider -p no:randomly\n")
    return tmp_path


def test_console_script_is_declared():
    from importlib import metadata

    eps = {e.name: e.value for e in metadata.entry_points(group="console_scripts")
           if e.name in ("fenvix", "detpy")}
    assert eps.get("fenvix") == "detpy.fenvix:main", eps


def test_help_lists_the_product_commands_and_version_flags():
    p = fx("--help")
    assert p.returncode == 0
    for c in ("fenvix pytest", "fenvix repro", "fenvix explore", "fenvix replay", "fenvix verify", "vitest", "jest",
              "playwright", "zope-testrunner"):
        assert c in p.stdout, c
    for flag in ("--version", "-V", "version"):
        p = fx(flag)
        assert p.returncode == 0 and p.stdout.startswith("fenvix "), (flag, p.stdout, p.stderr)
    d = subprocess.run([sys.executable, "-m", "detpy", "--version"], capture_output=True, text=True)
    assert d.returncode == 0 and d.stdout.startswith("detpy "), d.stderr
    for sub in ("repro", "explore", "replay", "verify"):
        p = fx(sub, "--help")
        assert p.returncode == 0 and f"fenvix {sub}" in p.stdout, sub


def test_pytest_entry_adds_det_and_prints_the_repro_command(project):
    p = fx("pytest", "-q", "tests", cwd=project)
    assert p.returncode == 1, p.stdout + p.stderr
    assert "detpy (Level 0)" in p.stdout  # --det was added
    assert "fenvix repro tests/test_o.py::test_victim" in p.stdout, p.stdout


def test_repro_prints_cause_seed_order_and_replay_command(project):
    p = fx("repro", "tests/test_o.py::test_victim", "--confirm", "4", "--seeds", "3", cwd=project)
    assert p.returncode == 0, p.stdout + p.stderr
    out = p.stdout
    assert "status: REPRODUCED: failed 4/4 replays with one fingerprint" in out, out
    assert "cause: test order: it fails when run after tests/test_o.py::test_polluter" in out, out
    assert "seed: none (fixed order)" in out, out
    assert "order: tests/test_o.py::test_polluter -> tests/test_o.py::test_victim" in out, out
    # replay: the single failing run as a product command; it takes runner arguments and fails when the defect
    # reproduces (what CI and the exam run: `<replay> --det-trace=T`, then `fenvix verify` of the traces)
    replay = next(x.strip()[len("replay: "):] for x in out.splitlines() if x.strip().startswith("replay: "))
    assert replay.startswith("fenvix pytest --det ") and "--det-order=" in replay, replay
    traces = []
    for i in range(2):
        t = project / f"replay-{i}.jsonl"
        r = subprocess.run([*FX, *replay.split()[1:], "-p", "no:cacheprovider", f"--det-trace={t}"], cwd=project,
                           env=_env(), capture_output=True, text=True, timeout=600)
        assert r.returncode == 1 and t.exists(), r.stdout + r.stderr
        traces.append(str(t))
    v = fx("verify", *traces, cwd=project)
    assert v.returncode == 0, v.stdout
    # check: N replays with one fingerprint
    line = next(x for x in out.splitlines() if x.strip().startswith("check: "))
    bundle = line.split("fenvix replay ", 1)[1].split()[0].strip()
    data = json.loads((project / bundle / "bundle.json").read_text())
    assert data["runner"] == "pytest" and data["status"] == "reproduced"
    # G-0178 / G-0991: the first divergent event against the passing run names the polluter, not an unrelated event
    assert data["divergence"]["reason"] == "order", data["divergence"]
    assert "tests/test_o.py::test_polluter" in data["divergence"]["description"], data["divergence"]
    # the replay command works as printed, and says what it found in a sentence (G-2020)
    r = fx("replay", bundle, "--runs", "3", cwd=project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "REPRODUCED: failed 3/3 runs, identical fingerprint: True" in r.stdout


def test_repro_of_an_unknown_test_says_so(project):
    p = fx("repro", "tests/test_o.py::nope", cwd=project)
    assert p.returncode == 1
    assert "not collected" in p.stdout and "None" not in p.stdout, p.stdout  # G-2209


def test_replay_of_a_non_bundle_is_one_line(tmp_path):
    p = fx("replay", str(tmp_path))
    assert p.returncode == 2 and "not a replay bundle" in p.stderr and "Traceback" not in p.stderr  # G-2205


def test_explore_finds_and_bundles_the_flaky_test(project):
    p = fx("explore", "--budget", "5", "--max-seeds", "4", "--confirm", "2", cwd=project, timeout=1500)
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.startswith("fenvix explore:"), p.stdout
    summary = json.loads((project / ".detpy" / "repro" / "explore.json").read_text())
    assert summary.get("runner") in (None, "pytest")  # file written by the engine; the printed summary has it


@pytest.mark.parametrize("runner,test", [("vitest", "src/sum.test.ts"), ("jest", "src/sum.test.js"),
                                         ("playwright", "e2e/login.spec.ts")])
def test_js_adapters_are_planned_and_say_so(tmp_path, runner, test):
    p = fx("repro", test, "--runner", runner, cwd=tmp_path)
    assert p.returncode == 2
    assert f"not available for {runner}" in p.stderr and "docs/CLI.md" in p.stderr, p.stderr


def test_adapter_is_picked_from_the_test_id(tmp_path):
    from detpy import fenvix

    assert fenvix.pick_adapter(None, test="tests/test_a.py::test_x").name == "pytest"
    (tmp_path / "vitest.config.ts").write_text("")
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        assert fenvix.pick_adapter(None, test="src/a.test.ts").name == "vitest"
    finally:
        os.chdir(cwd)


def test_detect_names_runners_and_subprojects(tmp_path):
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "requirements.txt").write_text("pytest\n")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text(json.dumps({"devDependencies": {"vitest": "^3"}}))
    (tmp_path / "manage.py").write_text("")
    p = fx("detect", str(tmp_path))
    assert p.returncode == 0
    rows = {tuple(r.split("\t")) for r in p.stdout.splitlines()}
    assert (".", "python", "django") in rows and ("api", "python", "pytest") in rows and ("web", "node", "vitest") in rows
    p = fx("detect", str(tmp_path / "missing"))
    assert p.returncode != 0 and "Traceback" not in p.stderr  # G-1863


def test_zope_alias_and_python_runner_compat(tmp_path):
    # G-1862: `zope` is accepted as the name of zope-testrunner (no "invalid choice")
    from detpy import fenvix

    assert "zope-testrunner" in fenvix.PY_RUNNERS
    p = fx("python-runner")
    assert p.returncode == 2 and "name a runner" in p.stderr


UNITTEST = '''
import unittest
STATE = {}
class T(unittest.TestCase):
    def test_a(self):
        pass
    def test_b_polluter(self):
        STATE["x"] = 1
    def test_c(self):
        pass
    def test_d_victim(self):
        self.assertNotIn("x", STATE)
'''


def test_repro_and_replay_work_for_the_unittest_shell(tmp_path):
    """G-0532, G-0540: repro, bundle and replay for a suite run by `python -m detpy unittest` (the other shells use
    the same adapter)."""
    (tmp_path / "test_u.py").write_text(UNITTEST)
    p = fx("repro", "test_u.py::T::test_d_victim", "--runner", "unittest", "--confirm", "3", "--seeds", "2", "--",
           "discover", "-p", "test_*.py", cwd=tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "cause: test order: it fails when run after test_u.py::T::test_b_polluter" in p.stdout, p.stdout
    assert "rerun: python -m detpy unittest --det --det-order=" in p.stdout, p.stdout
    bundle = next((tmp_path / ".detpy" / "repro").glob("test_d_victim-*"))
    assert json.loads((bundle / "bundle.json").read_text())["runner"] == "unittest"
    r = fx("replay", str(bundle), "--runs", "2", cwd=tmp_path)
    assert r.returncode == 0 and "REPRODUCED" in r.stdout, r.stdout + r.stderr


def test_bundle_is_self_contained_and_work_files_are_removed(project):
    """G-1556 (commit, interpreter, distributions, run inputs, relative failure location), G-2021 (no work files
    left), replay_command names the product command."""
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x"],
                   cwd=project, check=True)
    p = fx("repro", "tests/test_o.py::test_victim", "--confirm", "2", "--seeds", "1", cwd=project)
    assert p.returncode == 0, p.stdout + p.stderr
    bundle = next((project / ".detpy" / "repro").glob("test_victim-*"))
    data = json.loads((bundle / "bundle.json").read_text())
    prov = data["provenance"]
    assert len(prov["commit"]) == 40 and prov["python"] and any(d.startswith("pytest==") for d in prov["distributions"])
    assert prov["inputs"]["tz"].startswith("UTC") and any(k.startswith("env:") for k in prov["inputs"])
    assert data["exception"][3] == "tests/test_o.py:14", data["exception"]
    assert data["replay_command"].startswith("fenvix replay ")
    assert not (project / ".detpy" / "repro" / ".work").exists()


def test_repro_from_a_parallel_plan_searches_the_workers_list(project):
    """G-1557: a failure seen under -n is searched in the list of the worker that ran it."""
    pytest.importorskip("xdist")
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", "--det", "--det-seed=3", "-n", "2", "tests"],
                         cwd=project, env=_env(), capture_output=True, text=True, timeout=600)
    if " failed" in run.stdout:  # the failure is printed with the command that starts from the worker's list
        assert "--plan " in run.stdout, run.stdout
    p = fx("repro", "tests/test_o.py::test_victim", "--plan", ".detpy/plan.json", "--confirm", "2", cwd=project)
    assert "ran in worker gw" in p.stderr, p.stderr
    plan = json.loads((project / ".detpy" / "plan.json").read_text())
    worker = next(ids for ids in plan["lists"].values() if "tests/test_o.py::test_victim" in ids)
    if "tests/test_o.py::test_polluter" in worker[:worker.index("tests/test_o.py::test_victim")]:
        assert p.returncode == 0 and "test_o.py::test_polluter" in p.stdout, p.stdout
    else:  # the plan separated them: the worker's list does not fail, which repro reports
        assert "not reproduced" in p.stdout, p.stdout


def test_explore_resumes_and_selects(project):
    """G-1529 (each night explores new seeds), G-1530 (only previously unstable test files)."""
    p = fx("explore", "--budget", "5", "--max-seeds", "2", "--no-repro", cwd=project, timeout=1500)
    assert p.returncode == 0, p.stdout + p.stderr
    first = json.loads((project / ".detpy" / "repro" / "explore-state.json").read_text())
    assert (first["first_seed"], first["last_seed"]) == (1, 2)
    p = fx("explore", "--budget", "5", "--max-seeds", "2", "--no-repro", "--resume", cwd=project, timeout=1500)
    second = json.loads((project / ".detpy" / "repro" / "explore.json").read_text())
    assert [x["seed"] for x in second["seeds_log"]] == [3, 4], second["seeds_log"]
    assert not (project / ".detpy" / "repro" / ".work").exists()
    if second.get("flaky_failing"):
        p = fx("explore", "--budget", "5", "--max-seeds", "1", "--no-repro", "--only-unstable", cwd=project,
               timeout=1500)
        assert "1 test file(s) selected: tests/test_o.py" in p.stderr, p.stderr


def test_doctor_checks_the_machine():
    """G-0700."""
    p = fx("doctor", "--json")
    checks = {c["check"]: c for c in json.loads(p.stdout)}
    for name in ("python", "hash seed re-exec", "ASLR switch", "locale", "strace", "C compiler"):
        assert name in checks, checks
    assert checks["python"]["ok"] and p.returncode in (0, 1)


def test_explore_with_targets_reports_each_target_as_block2_reads_it(project):
    """Block 2 measures the product command `fenvix explore --targets FILE` (one seed search shared by every target;
    per-target `fenvix repro` searched the whole suite again for each target and 16 anyio targets did not fit the
    budget). The harness reads each target's bundle from the JSON summary and its cause and replay command from the
    printed `defect:` lines: both must be there for a reproduced target."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("detpy_harness", ROOT / "harness" / "detpy_harness.py")
    h = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = h  # its dataclasses look their module up
    spec.loader.exec_module(h)
    target = "tests/test_o.py::test_victim"
    (project / "targets.txt").write_text(target + "\n")
    p = fx("explore", "--targets", "targets.txt", "--budget", "5", "--max-seeds", "3", "--confirm", "2", "--json",
           cwd=project, timeout=1500)
    assert p.returncode == 0, p.stdout + p.stderr
    summary = h.parse_fenvix_explore(p.stdout)
    bundle = next(b for b in summary["bundles"] if b.get("test") == target)
    assert bundle["status"] == "reproduced", bundle
    assert bundle["replay"]["fails"] == bundle["replay"]["runs"] == 2 and bundle["replay"]["identical_fingerprint"]
    cause, replay = h.parse_fenvix_defects(p.stdout)[target]
    assert cause.startswith("test order: it fails when run after tests/test_o.py::test_polluter"), cause
    assert replay.startswith("replay: fenvix replay "), replay


def test_image_help_lists_every_product_command_on_its_own_line():
    """F-18: `fenvix --help` of the runner image (release/fenvix) names each command at the start of a line."""
    p = subprocess.run([sys.executable, str(ROOT / "release" / "fenvix"), "--help"], capture_output=True, text=True)
    assert p.returncode == 0
    import re

    for cmd in ("python", "node", "repro", "explore", "replay", "verify", "version", "pytest"):
        assert re.search(rf"^\s+fenvix {cmd}\b", p.stdout, re.M), (cmd, p.stdout)
