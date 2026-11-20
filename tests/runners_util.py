"""Helpers of the runner tests (``test_runners_*.py``): write a project, run ``python -m detpy <runner>`` in a
subprocess, read its ``--det-outcomes`` file."""

from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

_N = itertools.count(1)


def write(root: Path, files: dict) -> None:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text) if isinstance(text, str) else text)


class Result:
    def __init__(self, proc: subprocess.CompletedProcess, data: dict, cmd: list):
        self.code = proc.returncode
        self.out = proc.stdout + proc.stderr
        self.data = data
        self.cmd = cmd
        self.outcomes: dict = data.get("outcomes", {})
        cache = data.get("cache") or {}
        self.reused = set(cache.get("reused_ids", ()))
        self.cache = cache
        self.fingerprints: dict = data.get("fingerprints", {})
        self.order: list = data.get("order", [])

    def __repr__(self):
        return f"<Result code={self.code} outcomes={self.outcomes} reused={sorted(self.reused)}>\n{self.out[-3000:]}"


def run(runner: str, root: Path, *args: str, det: bool = True, cache: bool = True, env: dict | None = None,
        cache_dir: Path | None = None, det_args=(), timeout: float = 600, bytes_env: dict | None = None,
        safe_path: bool = False) -> Result:
    """``python -m detpy <runner> [--det] [--det-cache=<root>-cache] --det-outcomes=... <args>`` in ``root``.
    ``safe_path``: ``python -P`` (the working directory is not on ``sys.path``: its listing, which the import system
    reads, is then not an input of every test)."""
    n = next(_N)
    out = root.parent / f"{root.name}-o{n}.json"
    cmd = [sys.executable, *(["-P"] if safe_path else []), "-m", "detpy", runner]
    if det:
        cmd.append("--det")
    if cache:
        cmd.append(f"--det-cache={cache_dir or root.parent / (root.name + '-cache')}")
    cmd += [f"--det-outcomes={out}", f"--det-trace={root.parent / f'{root.name}-t{n}.jsonl'}", *det_args, *args]
    if bytes_env is not None:
        e = {os.fsencode(k): os.fsencode(v) for k, v in os.environ.items()}
        e.update(bytes_env)
        for k, v in (env or {}).items():
            e[os.fsencode(k)] = os.fsencode(v)
    else:
        e = dict(os.environ)
        e.update(env or {})
    p = subprocess.run(cmd, cwd=root, env=e, capture_output=True, text=True, timeout=timeout,
                       stdin=subprocess.DEVNULL)
    data = json.loads(out.read_text()) if out.exists() else {}
    return Result(p, data, cmd)


def has_strace() -> bool:
    return shutil.which("strace") is not None
