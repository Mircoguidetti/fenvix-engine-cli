#!/usr/bin/env python3
"""Print the dependencies of a hatch environment from pyproject.toml, one per line (a requirements file).

    hatchdeps.py pyproject.toml test > reqs.txt
"""
import sys
import tomllib

d = tomllib.load(open(sys.argv[1], "rb"))
envs = d.get("tool", {}).get("hatch", {}).get("envs", {})
seen = []
name = sys.argv[2]
while name and name not in seen:
    seen.append(name)
    e = envs.get(name, {})
    for x in e.get("dependencies", []) + e.get("extra-dependencies", []):
        print(x)
    name = e.get("template")
