#!/usr/bin/env python3
"""Specs for the head-to-head walk, pinned to the commits already walked.

* home-assistant, docusaurus, vue-core: the study-2 spec, with ``seq`` replaced by the exact commit list of run v3
  (``results/v3/walk/<name>-0o<n>.json.gz``; every shard of a project walked the same window).
* the 14 libraries of the first study: a new spec (unit = one test file, as in study 2), commit list from
  ``harness/cache_skip/results/<lib>.json`` (``meta.commits``), install and pytest arguments as in the first study.

    python3 harness/skip_study2/headtohead/make_specs.py
"""

import gzip
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
S2 = HERE.parent
HARNESS = S2.parent
LIBS = ("arrow attrs boltons click flask isort jinja marshmallow more-itertools pygments sqlparse structlog toolz "
        "werkzeug").split()
# test ids left out of every run, as in the first study (they hang or take minutes in a serial run)
DESELECT = {"werkzeug": ["tests/test_serving.py::test_reloader_sys_path[watchdog]"],
            "more-itertools": ["tests/test_more.py::TestConcurrentTee::test_concurrent_consumers"]}


def big(name):
    spec = json.loads((S2 / "specs" / f"{name}.json").read_text())
    f = sorted((S2 / "results" / "v3" / "walk").glob(f"{name}-0o*.json.gz"))[0]
    d = json.loads(gzip.open(f).read())
    spec["seq"] = {"kind": "list", "commits": [c["sha"] for c in d["commits"]], "from": f"results/v3/walk/{f.name}"}
    return spec


def lib(name):
    d = json.loads((HARNESS / "cache_skip" / "results" / f"{name}.json").read_text())
    repos = {r["name"]: r for r in json.loads((HARNESS / "repos.json").read_text())["popular"]}
    args = [a for a in d["steps"][0]["args"] if a != "--continue-on-collection-errors"]
    # drop the "-p capture_plugin" pair and any --deselect pair (re-added below)
    clean, k = [], 0
    while k < len(args):
        if args[k] == "-p" and k + 1 < len(args) and args[k + 1] == "capture_plugin":
            k += 2
            continue
        if args[k] == "--deselect":
            k += 2
            continue
        clean.append(args[k])
        k += 1
    extra = repos.get(name, {}).get("install", [])
    dsel = []
    for t in DESELECT.get(name, []):
        dsel += ["--deselect", t]
    return {
        "name": name, "url": d["meta"]["url"], "lang": "pytest",
        "seq": {"kind": "list", "commits": d["meta"]["commits"], "from": f"harness/cache_skip/results/{name}.json"},
        "py_minor": "3.13",
        "install": ["test -x {py} || uv venv -q --python 3.13 {venv}",
                    "python3 {harness}/headtohead/libinstall.py --py {py} --src {src} " +
                    " ".join(f"--extra {x}" for x in extra)],
        "install_files": ["pyproject.toml", "setup.py", "setup.cfg", "tox.ini", "requirements*.txt",
                          "requirements/*.txt", "requirements/*.in"],
        "units": {"include": ["test_*.py", "**/test_*.py"],
                  "exclude": ["docs/**", "examples/**", "**/examplefiles/**", "**/snippets/**", "**/testdata/**",
                              "**/fixtures/**", "**/conftest.py", "bench/**", "benchmarks/**", "**/node_modules/**"],
                  "sample": 1.0},
        "cmd": ["{py}", "-m", "pytest", "-p", "s2_report", *clean, *dsel, "{unit}"],
        "unit_timeout": 600,
        "verify": 1.0,
        "plain_baseline": True,
    }


def main():
    out = HERE / "specs"
    out.mkdir(exist_ok=True)
    for n in ("home-assistant", "docusaurus", "vue-core"):
        s = big(n)
        s["py_minor"] = "3.14" if n == "home-assistant" else None
        (out / f"{n}.json").write_text(json.dumps(s, indent=1) + "\n")
        print(n, len(s["seq"]["commits"]), "commits")
    for n in LIBS:
        s = lib(n)
        (out / f"{n}.json").write_text(json.dumps(s, indent=1) + "\n")
        print(n, len(s["seq"]["commits"]), "commits", s["cmd"][3:-1])


if __name__ == "__main__":
    main()
