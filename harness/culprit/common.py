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


_STAMP = [0]


def fresh_mtime(repo, paths) -> None:
    """Give ``paths`` (relative to ``repo``) an mtime no earlier run has seen.

    A ``.pyc`` is valid while the source's mtime (whole seconds) and size match the ones it was compiled from.
    detpy keeps one shared bytecode directory (``~/.cache/detpy/pyc``), and plain runs keep ``__pycache__`` in the
    tree. Two checkouts within one second of a file whose versions have the same size (a one-token mutation
    ``==`` -> ``!=``, or ``x + 1 + 0 * 4`` -> ``x * 3 + 0 * 8``) then run the bytecode of the other version: the
    replay reports the outcome of a different commit. Every rewritten file therefore gets a strictly increasing
    whole-second stamp (persisted per repository so a later process does not reuse one).
    """
    gitdir = Path(git(repo, "rev-parse", "--absolute-git-dir"))
    sf = gitdir / "culprit-mtime"
    try:
        last = int(sf.read_text())
    except (OSError, ValueError):
        last = 0
    stamp = max(int(time.time()) + 1, last + 1, _STAMP[0] + 1)
    _STAMP[0] = stamp
    sf.write_text(str(stamp))
    for rel in paths:
        f = Path(repo) / rel
        if f.is_file() and not f.is_symlink():
            os.utime(f, (stamp, stamp))


def checkout(repo, sha: str) -> None:
    before = git(repo, "rev-parse", "HEAD", check=False)
    git(repo, "checkout", "-q", "-f", sha)
    git(repo, "clean", "-fdq", "-e", ".detpy")
    if before and len(before) == 40:
        changed = git(repo, "diff", "--name-only", "--no-renames", before, "HEAD", check=False).split("\n")
        fresh_mtime(repo, [c for c in changed if c])


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
    if o is None and code in (0, 1, 5):
        return {0: "pass", 1: "fail", 5: "missing"}[code]
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
        outcomes = outcomes.get("outcomes", outcomes)
    except (OSError, ValueError):
        outcomes = {}
    shutil.rmtree(tmp, ignore_errors=True)
    return {"outcome": outcome_of(code, outcomes, nodeid), "exit": code, "wall": wall, "tail": out[-1500:]}


def no_bytecode(env: dict) -> dict:
    """Plain runs read and write no bytecode (an empty, private cache prefix and no writes): see fresh_mtime."""
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = tempfile.mkdtemp(prefix="nopyc-")
    return env


def run_plain(repo, venv: Path, args, extra_env: dict | None = None, timeout=900) -> tuple[int, str, float]:
    cmd = [str(venv / "bin" / "python"), "-m", "pytest", "-p", "no:cacheprovider", *args]
    t0 = time.perf_counter()
    env = no_bytecode(base_env(venv, extra_env))
    code, out = sh(cmd, cwd=repo, env=env, timeout=timeout)
    shutil.rmtree(env["PYTHONPYCACHEPREFIX"], ignore_errors=True)
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
    env = no_bytecode(base_env(venv, extra_env))
    t0 = time.perf_counter()
    sh(["git", "-C", str(repo), "bisect", "start", "--first-parent", bad, good], env=env)
    counter = tempfile.NamedTemporaryFile("w", suffix=".count", delete=False)
    counter.close()
    script = ["sh", "-c", 'echo x >> "$0"; exec "$@"', counter.name,
              str(venv / "bin" / "python"), "-m", "pytest", "-q", "-p", "no:cacheprovider", *script_args]
    code, out = sh(["git", "-C", str(repo), "bisect", "run", *script], cwd=repo, env=env, timeout=timeout)
    with open(counter.name) as fh:
        runs = sum(1 for _ in fh)
    os.unlink(counter.name)
    wall = time.perf_counter() - t0
    log = git(repo, "bisect", "log", check=False)
    git(repo, "bisect", "reset", check=False)
    shutil.rmtree(env["PYTHONPYCACHEPREFIX"], ignore_errors=True)
    steps = sum(1 for line in log.splitlines() if line.startswith("git bisect ") and
                (line.startswith("git bisect good") or line.startswith("git bisect bad") or
                 line.startswith("git bisect skip")))
    named = None
    for line in out.splitlines():
        if "is the first bad commit" in line:
            named = line.split()[0]
    return {"named": named, "executions": runs, "log_steps": steps, "wall": wall, "exit": code,
            "tail": out[-600:] if named is None else ""}
