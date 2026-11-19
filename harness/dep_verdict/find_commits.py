#!/usr/bin/env python3
"""Step 1 of the dependency-update verdict validation: find dependency-only commits.

For every market-test repository, walk the default branch (first parent) back from the head pinned by the market
test and classify every commit by the files it changes (diff against its first parent):

* ``dep``: every changed file is a Python dependency file (lockfile, requirements/constraints file, ``pyproject``
  or ``setup.cfg`` whose change is confined to dependency declarations);
* ``dep-other``: only dependency files of other ecosystems (npm, yarn, pnpm, Go, Cargo) or of tooling outside the
  test environment (pre-commit hooks, GitHub Actions pins), possibly mixed with Python dependency files;
* ``code``: anything else.

Output: the last N ``dep`` commits per repository (with their first parent and changed files), and their share of
all first-parent commits over (a) the window those N commits span and (b) the market test's 92-day window
(2026-08-17 .. 2026-11-17).

    python3 harness/dep_verdict/find_commits.py --repos /path/to/clones --out harness/dep_verdict/commits.json
"""

from __future__ import annotations

import argparse
import configparser
import fnmatch
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent

# name, url, head pinned by the market test (harness/market_test/specs/*.json on claude/market-test)
REPOS = [
    ("airflow", "https://github.com/apache/airflow", "56bbac12ad98"),
    ("community.general", "https://github.com/ansible-collections/community.general", "63fe14d2aa6a"),
    ("esphome", "https://github.com/esphome/esphome", "141789d2400f"),
    ("integrations-core", "https://github.com/DataDog/integrations-core", "5bedd04ea3a7"),
    ("litellm", "https://github.com/BerriAI/litellm", "17e6ea8cb7d4"),
    ("mlflow", "https://github.com/mlflow/mlflow", "c365f861ff68"),
    ("moto", "https://github.com/getmoto/moto", "96f50b1aa902"),
    ("prefect", "https://github.com/PrefectHQ/prefect", "5e8ca118fc51"),
    ("pydantic-ai", "https://github.com/pydantic/pydantic-ai", "62e7b66c9f4d"),
    ("transformers", "https://github.com/huggingface/transformers", "a2a53c3be282"),
]

LOCK_PATTERNS = ["uv.lock", "poetry.lock", "Pipfile.lock", "pdm.lock", "pylock.toml", "pylock.*.toml",
                 "requirements*.txt", "requirements*.in", "*-requirements.txt", "*_requirements.txt",
                 "*_requirements.in", "constraints*.txt", "requirements/*.txt", "requirements/*.in",
                 "requirements/*.yaml", "requirements/*.yml", "tests/unit/requirements.yml", "Pipfile"]
OTHER_PATTERNS = ["package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json",
                  "go.mod", "go.sum", "Cargo.lock", "Cargo.toml", "Gemfile.lock", ".pre-commit-config.yaml",
                  ".github/workflows/*.yml", ".github/workflows/*.yaml", ".github/actions/*/action.yml",
                  ".github/dependabot.yml", "Dockerfile", "*.Dockerfile", "docker/*Dockerfile*",
                  ".python-version", ".nvmrc", "bun.lock", "bun.lockb"]

# pyproject keys whose content is dependency declarations
DEP_KEYS = [("project", "dependencies"), ("project", "optional-dependencies"), ("dependency-groups",),
            ("build-system", "requires"), ("tool", "uv", "dev-dependencies"),
            ("tool", "uv", "constraint-dependencies"), ("tool", "uv", "override-dependencies"),
            ("tool", "uv", "sources"), ("tool", "poetry", "dependencies"), ("tool", "poetry", "dev-dependencies"),
            ("tool", "poetry", "group"), ("tool", "pdm", "dev-dependencies"), ("tool", "hatch", "envs", "*", "dependencies"),
            ("tool", "hatch", "envs", "*", "extra-dependencies"), ("tool", "hatch", "envs", "*", "pre-install-commands")]


def git(src, *args, check=True) -> str:
    return subprocess.run(["git", *args], cwd=src, capture_output=True, text=True, check=check,
                          errors="replace").stdout


def base(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def match(path: str, pats) -> bool:
    return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(base(path), p) for p in pats)


def _drop(d, keys):
    if not isinstance(d, dict):
        return
    k = keys[0]
    if len(keys) == 1:
        if k == "*":
            d.clear()
        else:
            d.pop(k, None)
        return
    targets = list(d.values()) if k == "*" else [d.get(k)]
    for t in targets:
        _drop(t, keys[1:])


def pyproject_dep_only(old: str, new: str) -> bool | None:
    try:
        a, b = tomllib.loads(old), tomllib.loads(new)
    except Exception:
        return None
    for keys in DEP_KEYS:
        _drop(a, list(keys))
        _drop(b, list(keys))
    return a == b


def setupcfg_dep_only(old: str, new: str) -> bool | None:
    def strip(text):
        cp = configparser.ConfigParser(interpolation=None)
        try:
            cp.read_string(text)
        except Exception:
            return None
        out = {}
        for sec in cp.sections():
            if sec == "options.extras_require":
                continue
            items = dict(cp.items(sec))
            if sec == "options":
                for k in ("install_requires", "setup_requires", "tests_require"):
                    items.pop(k, None)
            out[sec] = items
        return out
    a, b = strip(old), strip(new)
    if a is None or b is None:
        return None
    return a == b


def show(src, sha, path) -> str:
    return git(src, "show", f"{sha}:{path}", check=False)


def classify(src, sha, parent, files) -> tuple[str, list]:
    """('dep' | 'dep-other' | 'code' | 'empty', python dependency files changed)."""
    if not files:
        return "empty", []
    py, other, rest = [], [], []
    for f in files:
        if match(f, LOCK_PATTERNS):
            py.append(f)
        elif base(f) == "pyproject.toml":
            old, new = show(src, parent, f), show(src, sha, f)
            if not old or not new:   # added or removed project: not a pin change
                rest.append(f)
            elif pyproject_dep_only(old, new):
                py.append(f)
            else:
                rest.append(f)
        elif base(f) == "setup.cfg":
            old, new = show(src, parent, f), show(src, sha, f)
            if old and new and setupcfg_dep_only(old, new):
                py.append(f)
            else:
                rest.append(f)
        elif match(f, OTHER_PATTERNS):
            other.append(f)
        else:
            rest.append(f)
    if rest:
        return "code", py
    if py and not other:
        return "dep", py
    return "dep-other", py


def scan(src: Path, head: str | None, n_dep: int, max_commits: int, w0: str):
    head = head or git(src, "rev-parse", "origin/HEAD").strip()
    head = git(src, "rev-parse", head).strip()
    # first-parent log with the changed files against the first parent
    out = git(src, "log", "--first-parent", "-m", "--name-only", "--format=@@%H %P|%cI|%s", "-n", str(max_commits),
              head)
    commits, cur = [], None
    for line in out.splitlines():
        if line.startswith("@@"):
            hdr = line[2:]
            shas, date, subj = hdr.split("|", 2)
            parts = shas.split()
            cur = {"sha": parts[0], "parent": parts[1] if len(parts) > 1 else None, "date": date, "subject": subj,
                   "files": []}
            commits.append(cur)
        elif line.strip() and cur is not None:
            cur["files"].append(line.strip())
    # -m with --first-parent prints the diff against the first parent only once
    dep, rows = [], []
    for c in commits:
        if c["parent"] is None:
            continue
        files = sorted(set(c["files"]))
        kind = "code"
        pyf: list = []
        # cheap pre-filter: blobs are fetched only when every file is a candidate dependency file
        if files and all(match(f, LOCK_PATTERNS + OTHER_PATTERNS) or base(f) in ("pyproject.toml", "setup.cfg")
                         for f in files):
            kind, pyf = classify(src, c["sha"], c["parent"], files)
        elif not files:
            kind = "empty"
        rows.append({"sha": c["sha"], "date": c["date"], "kind": kind})
        if kind == "dep":
            dep.append({"sha": c["sha"], "parent": c["parent"], "date": c["date"], "subject": c["subject"][:200],
                        "files": files, "n_files": len(files)})
        if len(dep) >= n_dep and c["date"][:19] < w0:
            break
    return head, dep, rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--max-commits", type=int, default=20000)
    ap.add_argument("--window", default="2026-08-17T00:00:00,2026-11-17T23:59:59")
    a = ap.parse_args(argv)
    w0, w1 = a.window.split(",")
    result = {}
    for name, url, head in REPOS:
        src = Path(a.repos) / name
        h, dep_all, rows = scan(src, head, a.n, a.max_commits, w0)
        dep = dep_all[:a.n]
        oldest = dep[-1]["date"] if dep else None
        in_span = [r for r in rows if oldest and r["date"] >= oldest]
        kinds, wk = {}, {}
        for r in in_span:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        win = [r for r in rows if w0 <= r["date"][:19] <= w1]
        for r in win:
            wk[r["kind"]] = wk.get(r["kind"], 0) + 1
        result[name] = {
            "url": url, "head": h, "dep_commits": dep, "n_dep": len(dep),
            "span": {"from": oldest, "to": rows[0]["date"] if rows else None, "commits": len(in_span), "kinds": kinds,
                     "dep_share": len(dep) / len(in_span) if in_span else None},
            "window92": {"from": w0, "to": w1, "commits": len(win), "kinds": wk,
                         "dep_share": wk.get("dep", 0) / len(win) if win else None},
        }
        print(f"{name}: {len(dep)} dep-only, span {len(in_span)} commits from {oldest}, share "
              f"{result[name]['span']['dep_share']:.3f}; 92d {wk}", file=sys.stderr)
    Path(a.out).write_text(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
