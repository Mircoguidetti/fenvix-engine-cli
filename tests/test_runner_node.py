"""runner/fenvix-run, Node path: a Vitest project (npm) and a Jest project (yarn 1), each with an order-dependent
flaky test, produce a correct summary.json (same keys as the Python path) and the flaky test is reported with a
replay command that reproduces it (the test runs the replay itself); a mixed repository runs one job per language;
``--det-cache`` is wired but a no-op until detjs supports it.

Needs node and detjs (``$FENVIX_DETJS``: path to ``node/bin/detjs.js`` of claude/node-l0, built with ``npm run build``;
or ``detjs`` on PATH) and network access to the npm registry (the fixtures are installed from their lockfiles).
"""
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "runner" / "fenvix-run"
FIXTURES = ROOT / "tests" / "fixtures" / "runner-node"
DETJS = os.environ.get("FENVIX_DETJS") or shutil.which("detjs")
NODE = shutil.which("node")

needs_node = pytest.mark.skipif(not (DETJS and NODE), reason="needs node and detjs ($FENVIX_DETJS)")


def load_wrapper():
    loader = importlib.machinery.SourceFileLoader("fenvix_run", str(WRAPPER))
    spec = importlib.util.spec_from_loader("fenvix_run", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


FR = load_wrapper()


def copy_fixture(tmp_path: Path, name: str) -> Path:
    dst = tmp_path / name
    shutil.copytree(FIXTURES / name, dst, ignore=shutil.ignore_patterns("node_modules", ".detjs"))
    return dst


def shim_dir(tmp_path: Path, detjs: str) -> Path:
    """A ``detjs`` command on PATH (what runner/bootstrap.sh installs in $FENVIX_HOME/bin)."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    s = d / "detjs"
    s.write_text(f'#!/bin/sh\nexec "{NODE}" "{detjs}" "$@"\n' if detjs.endswith(".js") else f'#!/bin/sh\nexec "{detjs}" "$@"\n')
    s.chmod(0o755)
    return d


def base_env(tmp_path: Path, detjs: str | None = None) -> dict:
    env = dict(os.environ)
    env.update({"FENVIX_CACHE_ROOT": str(tmp_path / "machine-cache"), "FENVIX_DETJS": detjs or DETJS,
                "GITHUB_STEP_SUMMARY": str(tmp_path / "step-summary.md")})
    for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID", "DETJS"):
        env.pop(k, None)
    return env


def run(tmp_path: Path, project: Path, name: str, *args: str, detjs: str | None = None, python: str | None = None):
    out = tmp_path / name
    md = tmp_path / "step-summary.md"
    md.unlink(missing_ok=True)
    cmd = [sys.executable, str(WRAPPER), "--project", str(project), "--out", str(out), "--key", f"test/{name}", *args]
    r = subprocess.run(cmd, env=base_env(tmp_path, detjs), capture_output=True, text=True, timeout=900)
    s = json.loads((out / "summary.json").read_text()) if (out / "summary.json").exists() else None
    return r, s, md.read_text() if md.exists() else ""


def replay_outcome(tmp_path: Path, project: Path, command: str, nodeid: str) -> str | None:
    """Run a replay command from the summary as a developer would (``detjs`` on PATH, in the project directory) and
    return the outcome of ``nodeid`` in the trace it writes."""
    trace = project / ".detjs" / "trace.jsonl"
    trace.unlink(missing_ok=True)
    env = dict(os.environ)
    env["PATH"] = f"{shim_dir(tmp_path, DETJS)}{os.pathsep}{env['PATH']}"
    env.pop("DETJS", None)
    subprocess.run(["bash", "-c", command], cwd=project, env=env, capture_output=True, text=True, timeout=600)
    return (FR.read_trace(trace)[1].get(nodeid) or {}).get("outcome")


# ---------------------------------------------------------------------------------------------------------------------
# Without node: detection, install commands, ids


def test_detection_and_install_commands(tmp_path):
    assert FR.node_runner_of({"scripts": {"test": "vitest run"}, "devDependencies": {"jest": "1"}}) == "vitest"
    assert FR.node_runner_of({"scripts": {"test": "jest --ci"}}) == "jest"
    assert FR.node_runner_of({"devDependencies": {"ts-jest": "1"}}) == "jest"
    assert FR.node_runner_of({"devDependencies": {"mocha": "1"}}) is None
    assert FR.detect_languages(FIXTURES / "mixed") == ["python", "node"]
    assert FR.detect_languages(FIXTURES / "vitest-app") == ["node"]

    cases = {"vitest-app": ("npm", ["npm", "ci"]), "jest-app": ("yarn", ["yarn", "install", "--frozen-lockfile"]),
             "mixed": ("pnpm", ["pnpm", "install", "--frozen-lockfile"])}
    for name, (pm, cmd) in cases.items():
        info = FR.package_manager(FIXTURES / name)
        assert info["pm"] == pm and FR.install_command(info) == cmd, name
    assert FR.package_manager(FIXTURES / "mixed")["declared"] == "pnpm@10.28.0"

    berry = tmp_path / "berry"
    berry.mkdir()
    (berry / "package.json").write_text('{"packageManager": "yarn@4.5.0"}')
    (berry / "yarn.lock").write_text("__metadata:\n  version: 8\n")
    assert FR.install_command(FR.package_manager(berry)) == ["yarn", "install", "--immutable"]
    # a workspace package: the lockfile is at the repository root
    ws = tmp_path / "ws"
    (ws / ".git").mkdir(parents=True)
    (ws / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    (ws / "packages" / "a").mkdir(parents=True)
    info = FR.package_manager(ws / "packages" / "a")
    assert info["pm"] == "pnpm" and info["root"] == ws


def test_ids_and_patterns():
    assert FR.names_of("test/a.test.js::outer::inner::does it #2") == ("test/a.test.js", ["outer", "inner", "does it"])
    assert FR.js_regex("a (b) [c] 1+1=2? $x") == r"a \(b\) \[c\] 1\+1=2\? \$x"
    assert FR.node_strip(["vitest", "run", "--det", "--det-trace=x", "--det-cache=/c", "--reporter=default",
                          "--reporter=json", "--outputFile.json=r", "--json", "--outputFile=r", "-t", "x"]) == \
        ["vitest", "run", "--det", "--reporter=default", "-t", "x"]


def test_mixed_repository_needs_one_job_per_language(tmp_path):
    proj = copy_fixture(tmp_path, "mixed")
    r = subprocess.run([sys.executable, str(WRAPPER), "--project", str(proj), "--out", str(tmp_path / "o")],
                       env=base_env(tmp_path, "/nonexistent/detjs.js"), capture_output=True, text=True)
    assert r.returncode != 0 and "--lang python and --lang node" in r.stderr


# ---------------------------------------------------------------------------------------------------------------------
# With node and detjs


@needs_node
def test_vitest_project_summary_and_flaky_replay(tmp_path):
    proj = copy_fixture(tmp_path, "vitest-app")
    r, s, md = run(tmp_path, proj, "job")
    assert s is not None, r.stdout[-3000:] + r.stderr[-3000:]
    assert r.returncode == 1  # the suite failed (the flaky test failed in it): the job fails, as without fenvix

    victim = "test/registry.test.js::registry::starts empty"
    assert s["language"] == "node" and s["runner"].startswith("vitest ")
    assert s["install"]["command"] == "npm ci" and s["install"]["ran"] and s["install"]["exit"] == 0
    assert s["tests"] == 8 and s["ran"] == 8 and s["reused_with_proof"] == 0
    assert s["outcomes"] == {
        "test/clock.test.js::reads the clock": "passed",
        "test/clock.test.js::draws a random number": "passed",
        "test/clock.test.js::is skipped": "skipped",
        "test/clock.test.js::is todo": "todo",
        "test/registry.test.js::registry::adds numbers": "passed",
        "test/registry.test.js::registry::registers a plugin": "passed",
        victim: "failed",
        "test/registry.test.js::registry::adds numbers #2": "passed",
    }
    assert s["outcome_counts"] == {"failed": 1, "passed": 5, "skipped": 1, "todo": 1}
    assert s["failed"] == []
    assert set(s["fingerprints"]) == set(s["outcomes"])
    assert all(re.fullmatch(r"[0-9a-f]{32}", f) for f in s["fingerprints"].values())
    assert set(s["timings"]) == set(s["outcomes"]) and all(v >= 0 for v in s["timings"].values())
    assert s["epoch_ns"] == 1735689600000000000
    assert s["runtime"]["node"].startswith("v") and s["runtime"]["digest"]

    [f] = s["flaky"]
    assert f["nodeid"] == victim and f["replay_reproduces"] is True
    assert f["replay"] == "detjs vitest run --det test/registry.test.js"
    assert "registers a plugin" in f["minimise"] and "registers a plugin" in f["explanation"]
    # The replay and the minimal replay, run as a developer would: the test fails again, every time.
    for cmd in (f["replay"], f["minimise"], f["replay"]):
        assert replay_outcome(tmp_path, proj, cmd, victim) == "failed", cmd
    # ...and alone it passes (so it is flaky, not broken).
    alone = f"detjs vitest run --det test/registry.test.js -t '^registry starts empty$'"
    assert replay_outcome(tmp_path, proj, alone, victim) == "passed"

    assert "Language `node` · runner `vitest" in md and "| Tests | **8** |" in md
    assert "### Flaky tests" in md and f"replay: `{f['replay']}` (run by this job: fails again)" in md

    # Determinism: a second job gives the same outcomes and fingerprints (node_modules present: no reinstall).
    r2, s2, _ = run(tmp_path, proj, "job-again")
    assert s2["install"]["ran"] is False
    assert s2["outcomes"] == s["outcomes"] and s2["fingerprints"] == s["fingerprints"]


@needs_node
def test_jest_project_summary_failure_and_flaky_replay(tmp_path):
    proj = copy_fixture(tmp_path, "jest-app")
    r, s, md = run(tmp_path, proj, "job")
    assert s is not None, r.stdout[-3000:] + r.stderr[-3000:]
    victim = "__tests__/cache.test.js::cache::starts empty"
    real = "__tests__/math.test.js::a real failure (fails alone too)"
    assert r.returncode == 1
    assert s["language"] == "node" and s["runner"].startswith("jest ")
    assert s["install"]["command"] == "yarn install --frozen-lockfile" and s["install"]["exit"] == 0
    assert s["tests"] == 6
    assert s["outcomes"][victim] == "failed" and s["outcomes"][real] == "failed"
    assert s["outcomes"]["__tests__/cache.test.js::cache::is skipped"] == "skipped"
    assert s["failed"] == [real]
    assert [f["nodeid"] for f in s["flaky"]] == [victim]
    f = s["flaky"][0]
    assert f["replay_reproduces"] is True and "--runTestsByPath __tests__/cache.test.js" in f["replay"]
    assert "stores a value" in f["minimise"]
    for cmd in (f["replay"], f["minimise"]):
        assert replay_outcome(tmp_path, proj, cmd, victim) == "failed", cmd
    assert set(s["fingerprints"]) == set(s["outcomes"]) and set(s["timings"]) == set(s["outcomes"])
    assert "### Failures" in md and real in md and "### Flaky tests" in md


@needs_node
@pytest.mark.skipif(sys.version_info < (3, 12), reason="the Python job's --det-cache needs sys.monitoring")
def test_mixed_repository_python_job_and_node_job(tmp_path):
    pytest.importorskip("detpy")
    proj = copy_fixture(tmp_path, "mixed")
    rp, sp, mdp = run(tmp_path, proj, "python-job", "--lang", "python", "--python", sys.executable)
    assert sp is not None, rp.stdout[-3000:] + rp.stderr[-3000:]
    rn, sn, mdn = run(tmp_path, proj, "node-job", "--lang", "node")
    assert sn is not None, rn.stdout[-3000:] + rn.stderr[-3000:]

    assert rp.returncode == 0 and sp["language"] == "python" and sp["runner"] == "pytest"
    assert sp["outcomes"] == {"tests/test_slug.py::test_slug": "passed", "tests/test_slug.py::test_slug_empty": "passed"}
    assert set(sp["fingerprints"]) == set(sp["outcomes"]) and set(sp["timings"]) == set(sp["outcomes"])

    assert rn.returncode == 0 and sn["language"] == "node" and sn["runner"].startswith("vitest ")
    assert sn["install"]["command"] == "pnpm install --frozen-lockfile" and sn["install"]["exit"] == 0
    assert sn["outcomes"] == {"js/slug.test.js::slugs": "passed", "js/slug.test.js::slugs empty": "passed"}

    # One cache per language, never shared; and the same summary format for both jobs.
    assert sp["cache_dir"] != sn["cache_dir"]
    assert sp["cache_dir"].endswith("-py%d%d" % sys.version_info[:2]) and re.search(r"-node\d+$", sn["cache_dir"])
    assert set(sp) == set(sn)
    for k in ("tests", "ran", "reused_with_proof", "failed", "flaky", "outcomes", "fingerprints", "timings"):
        assert type(sp[k]) is type(sn[k]), k
    assert "| Tests | **2** |" in mdp and "| Tests | **2** |" in mdn


@needs_node
def test_det_cache_flag_is_a_no_op_until_detjs_supports_it(tmp_path):
    proj = copy_fixture(tmp_path, "vitest-app")
    _, plain, _ = run(tmp_path, proj, "plain", "--no-rerun")
    _, flag, md = run(tmp_path, proj, "flag", "--no-rerun", "--det-cache")
    assert not any(x.startswith("--det-cache") for x in flag["runner_args"])
    assert flag["cache_arg"] is None and flag["reused_with_proof"] == 0
    assert flag["cache_status"].startswith("requested, but this detjs has no --det-cache")
    assert flag["outcomes"] == plain["outcomes"] and flag["fingerprints"] == plain["fingerprints"]
    assert "Cache with proof: requested, but" in md

    # A detjs that advertises --det-cache (as claude/node-cache-proof will) gets the machine's cache directory.
    log = tmp_path / "fake-detjs-args.jsonl"
    fake = tmp_path / "fake-detjs.js"
    fake.write_text(f"""
const {{ spawnSync }} = require('node:child_process');
const fs = require('node:fs');
const args = process.argv.slice(2);
if (args.includes('--det-help')) {{
  const r = spawnSync(process.execPath, [{json.dumps(DETJS)}, '--det-help'], {{ encoding: 'utf8' }});
  process.stdout.write(r.stdout + '  --det-cache=DIR          cache with proof\\n');
  process.exit(0);
}}
fs.appendFileSync({json.dumps(str(log))}, JSON.stringify(args) + '\\n');
const r = spawnSync(process.execPath, [{json.dumps(DETJS)}, ...args.filter((a) => !a.startsWith('--det-cache'))],
  {{ stdio: 'inherit' }});
process.exit(r.status);
""")
    _, on, md_on = run(tmp_path, proj, "on", "--no-rerun", "--det-cache", detjs=str(fake))
    assert on["cache_status"] == "on" and on["cache_arg"] == f"--det-cache={on['cache_dir']}"
    seen = [json.loads(x) for x in log.read_text().splitlines()]
    assert f"--det-cache={on['cache_dir']}" in seen[0]
    assert "--det-cache-receipts" not in " ".join(seen[0])  # not advertised: not passed
    assert on["outcomes"] == plain["outcomes"]
    # without the flag, even a detjs that has it is not given the cache
    log.unlink()
    _, off, _ = run(tmp_path, proj, "off", "--no-rerun", detjs=str(fake))
    assert not any(a.startswith("--det-cache") for a in json.loads(log.read_text().splitlines()[0]))
    assert off["cache_status"].startswith("off for Node")


@needs_node
def test_verify_reads_a_node_summary(tmp_path):
    proj = copy_fixture(tmp_path, "vitest-app")
    _, s, _ = run(tmp_path, proj, "job", "--no-rerun")
    r = subprocess.run([sys.executable, str(WRAPPER), "verify", "--project", str(proj), "--summary",
                        str(tmp_path / "job" / "summary.json")], env=base_env(tmp_path), capture_output=True, text=True,
                       timeout=600)
    v = json.loads((tmp_path / "job" / "verify.json").read_text())
    assert r.returncode == 0 and v["reused"] == 0 and v["wrong"] == [] and v["all_outcomes_same"] is True


def test_runner_flags_come_from_the_test_script():
    sa = FR.script_args
    assert sa({"scripts": {"test": "pnpm lint && vitest run --typecheck"}}, "vitest") == ["--typecheck"]
    assert sa({"scripts": {"test": "vitest --run --project node"}}, "vitest") == ["--project", "node"]
    assert sa({"scripts": {"test": "npx jest --runInBand --coverage --selectProjects unit"}}, "jest") == \
        ["--selectProjects", "unit"]
    assert sa({"scripts": {"test": "cross-env TZ=UTC jest"}}, "jest") == []  # not a plain call: nothing taken
    assert sa({"scripts": {"test": "vitest run"}}, "vitest") == [] and sa({}, "jest") == []
