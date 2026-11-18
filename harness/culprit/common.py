"""Shared helpers of the exact-culprit validation (harness only; the engine is used through pytest flags)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2]
EPOCH = "2026-01-01T00:00:00"  # one fixed virtual-clock epoch for every deterministic run of the study


def sh(cmd, cwd=None, env=None, timeout=900, check=False) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return 124, f"timeout: {e}"
    out = (p.stdout or "") + (p.stderr or "")
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, cmd))} -> {p.returncode}\n{out[-2000:]}")
    return p.returncode, out


def git(repo, *args, check=True, timeout=300) -> str:
    code, out = sh(["git", "-C", str(repo), *args], timeout=timeout)
    if check and code != 0:
        raise RuntimeError(f"git {' '.join(args)}: {out[-1000:]}")
    return out.strip()


def git_out(repo, *args) -> str:
    """stdout only (git show of a blob must not be mixed with stderr)."""
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr[-500:]}")
    return p.stdout


def checkout(repo, sha: str) -> None:
    git(repo, "checkout", "-q", "-f", sha)
    git(repo, "clean", "-fdq", "-e", ".detpy")


def base_env(venv: Path, extra: dict | None = None, drop=()) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONHASHSEED", "DETPY_REEXEC", "VIRTUAL_ENV", "PYTHONPATH", "PYTEST_ADDOPTS",
                        "PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX", "DETPY_PRECOMPILE_S", "PYTHONWARNINGS",
                        "NODE_ENV", "TZ", "FORCE_COLOR", "NO_COLOR") and k not in drop}
    env["PATH"] = str(venv / "bin") + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(venv)
    env["COLUMNS"] = "160"
    for k, v in (extra or {}).items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    return env


def outcome_of(code: int, outcomes: dict, nodeid: str) -> str:
    """'fail', 'pass' or 'missing' for one test from pytest's exit code and the --det-outcomes map."""
    o = outcomes.get(nodeid)
    if o is None:
        # parametrised ids or a collection error: any listed failure counts
        if any(v in ("failed", "error") for v in outcomes.values()):
            return "fail"
        if code == 5:
            return "missing"
        return "fail" if code not in (0, 5) else "missing"
    return "fail" if o in ("failed", "error") else "pass"


def run_det(repo, venv: Path, nodeid: str, extra_env: dict | None = None, keys: str | None = None,
            args=(), timeout=900) -> dict:
    """One deterministic run of one test (``--det`` with an empty proof cache, so nothing is reused)."""
    tmp = tempfile.mkdtemp(prefix="detrun-")
    outp = os.path.join(tmp, "outcomes.json")
    cmd = [str(venv / "bin" / "python"), "-m", "pytest", "-q", "-p", "no:cacheprovider", "--det",
           f"--det-epoch={EPOCH}", f"--det-cache={tmp}/cache", f"--det-outcomes={outp}", "--tb=short", *args]
    if keys:
        cmd.append(f"--det-cache-keys={keys}")
    cmd.append(nodeid)
    t0 = time.perf_counter()
    code, out = sh(cmd, cwd=repo, env=base_env(venv, extra_env), timeout=timeout)
    wall = time.perf_counter() - t0
    try:
        with open(outp) as fh:
            outcomes = json.load(fh)
    except (OSError, ValueError):
        outcomes = {}
    shutil.rmtree(tmp, ignore_errors=True)
    return {"outcome": outcome_of(code, outcomes, nodeid), "exit": code, "wall": wall, "tail": out[-1500:]}


def run_plain(repo, venv: Path, args, extra_env: dict | None = None, timeout=900) -> tuple[int, str, float]:
    cmd = [str(venv / "bin" / "python"), "-m", "pytest", "-p", "no:cacheprovider", *args]
    t0 = time.perf_counter()
    code, out = sh(cmd, cwd=repo, env=base_env(venv, extra_env), timeout=timeout)
    return code, out, time.perf_counter() - t0


def first_parent(repo, start: str, end: str) -> list[str]:
    """Commits in (start, end], oldest first, first-parent."""
    out = git(repo, "rev-list", "--first-parent", "--reverse", f"{start}..{end}")
    return [x for x in out.split() if x]


def git_bisect(repo, venv: Path, good: str, bad: str, script_args: list[str], extra_env: dict | None = None,
               timeout=3600) -> dict:
    """``git bisect run`` with plain pytest; returns the named commit, the executions and the wall time."""
    git(repo, "bisect", "reset", check=False)
    checkout(repo, bad)
    env = base_env(venv, extra_env)
    t0 = time.perf_counter()
    sh(["git", "-C", str(repo), "bisect", "start", "--first-parent", bad, good], env=env)
    script = [str(venv / "bin" / "python"), "-m", "pytest", "-q", "-p", "no:cacheprovider", *script_args]
    code, out = sh(["git", "-C", str(repo), "bisect", "run", *script], cwd=repo, env=env, timeout=timeout)
    wall = time.perf_counter() - t0
    log = git(repo, "bisect", "log", check=False)
    git(repo, "bisect", "reset", check=False)
    steps = sum(1 for line in log.splitlines() if line.startswith("git bisect ") and
                (line.startswith("git bisect good") or line.startswith("git bisect bad") or
                 line.startswith("git bisect skip")))
    named = None
    for line in out.splitlines():
        if "is the first bad commit" in line:
            named = line.split()[0]
    return {"named": named, "executions": max(0, steps - 2), "wall": wall, "exit": code,
            "tail": out[-600:] if named is None else ""}
