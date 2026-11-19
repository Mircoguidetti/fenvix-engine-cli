#!/usr/bin/env python3
"""Wall time of ``pytest --det --det-no-reexec`` per engine wheel (rust-hotpaths, review R-019b N5).

Without the bytecode control, the N5 fix validates every imported project module's bytecode by its source's hash
(checked-hash pycs in the project's ``__pycache__``) instead of by ``(mtime, size)``. This measures what that costs,
on a profile work directory set up by ``profile.py`` (its venv and checkout are reused).

Each block: install the wheel, remove the checkout's ``__pycache__`` directories (each engine reads only pycs it
wrote), one warm-up run (writes them), then ``--reps`` timed runs. Blocks alternate between the wheels
(``--blocks`` per wheel). Plain pytest (``P0``) is timed the same way, for ratios.

    python3 harness/rust_hotpaths/noreexec_timing.py --work /tmp/w/click-0 --wheel pre=a.whl --wheel new=b.whl \\
        --out results/noreexec-click.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import time
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, help="a profile.py work directory (holds venv/ and src/)")
    ap.add_argument("--wheel", action="append", required=True, help="NAME=PATH")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--blocks", type=int, default=2)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    work = Path(a.work)
    py, src = str(work / "venv" / "bin" / "python"), work / "src"
    wheels = dict(w.split("=", 1) for w in a.wheel)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHASHSEED", "DETPY_REEXEC", "PYTHONPATH",
                                                            "PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX")}
    walls: dict = {}

    def clean() -> None:
        for d in src.rglob("__pycache__"):
            if "venv" not in d.parts:
                shutil.rmtree(d, ignore_errors=True)

    def run(name: str, args: list, timed: bool) -> None:
        t0 = time.perf_counter()
        p = subprocess.run([py, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args], cwd=src, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if timed:
            walls.setdefault(name, []).append({"wall": time.perf_counter() - t0, "exit": p.returncode})

    for _ in range(a.blocks):
        for name, whl in wheels.items():
            subprocess.run(["uv", "pip", "install", "-q", "--python", py, "--reinstall-package", "detpy", "--no-deps",
                            os.path.abspath(whl)], check=True)
            clean()
            run(name, ["--det", "--det-no-reexec", "--det-urandom"], False)
            for _ in range(a.reps):
                run(name, ["--det", "--det-no-reexec", "--det-urandom"], True)
            clean()
            run("P0", [], False)
            for _ in range(a.reps):
                run("P0", [], True)
    p0 = statistics.median(x["wall"] for x in walls["P0"])
    summary = {k: {"median": statistics.median(x["wall"] for x in v),
                   "ratio": statistics.median(x["wall"] for x in v) / p0, "exits": [x["exit"] for x in v]}
               for k, v in walls.items()}
    Path(a.out).write_text(json.dumps({"work": str(work), "wheels": wheels, "walls": walls, "summary": summary},
                                      indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
