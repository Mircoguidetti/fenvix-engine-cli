#!/usr/bin/env python3
"""Run one integrations-core test file the way ``ddev test`` sets it up: the environment variables of the
integration's hatch ``default`` environment (``env-vars`` plus the matrix overrides) for one matrix cell (the
first matrix, newest value of every variable), then exec pytest.

    ddenv.py PYTHON UNIT [pytest args ...]

This process runs under the dependency capture, so the hatch.toml it reads is an input of the unit.
"""

import os
import sys
import tomllib
from pathlib import Path


def cell_env(hatch: Path) -> dict:
    if not hatch.exists():
        return {}
    d = tomllib.loads(hatch.read_text())
    de = d.get("envs", {}).get("default", {})
    env = {k: str(v) for k, v in (de.get("env-vars") or {}).items()}
    matrix = (de.get("matrix") or [{}])[0]
    cell = {k: str(v[-1]) for k, v in matrix.items() if k != "python" and v}
    for var, ov in ((de.get("overrides") or {}).get("matrix") or {}).items():
        sel = cell.get(var)
        if sel is None:
            continue
        for item in ov.get("env-vars", []) if isinstance(ov, dict) else []:
            if isinstance(item, str):
                k, _, v = item.partition("=")
                env[k] = v or sel
                continue
            cond = item.get("if")
            if cond is not None and sel not in [str(c) for c in cond]:
                continue
            env[item["key"]] = str(item.get("value", sel))
    return env


def main():
    py, unit, *rest = sys.argv[1:]
    integ = unit.split("/", 1)[0]
    env = dict(os.environ)
    for k, v in cell_env(Path(integ) / "hatch.toml").items():
        env.setdefault(k, v)
    os.execve(py, [py, "-m", "pytest", *rest, unit], env)


if __name__ == "__main__":
    main()
