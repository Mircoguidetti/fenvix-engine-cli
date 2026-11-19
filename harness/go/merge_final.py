#!/usr/bin/env python3
"""Final view of the flaky round: for each project, the result of the latest round that ran it (r3 for all; r5, r6
re-ran the projects whose Level 0 defects were fixed, and the slowest ones). Writes results/flaky-final/ and
SOURCES.json (project -> round)."""
import glob
import json
import os
import shutil

base = os.path.join(os.path.dirname(__file__), "results")
out = os.path.join(base, "flaky-final")
os.makedirs(out, exist_ok=True)
src = {}
for rnd in ("flaky-r3", "flaky-r5", "flaky-r6", "flaky-r7"):
    for f in glob.glob(os.path.join(base, rnd, "*.json")):
        name = os.path.basename(f)[:-5]
        src[name] = rnd
        shutil.copy(f, os.path.join(out, name + ".json"))
projects = [p["name"] for p in json.load(open(os.path.join(os.path.dirname(__file__), "flaky_projects.json")))]
missing = [p for p in projects if p not in src]
json.dump({"sources": src, "missing": missing}, open(os.path.join(out, "SOURCES.json"), "w"), indent=1)
print(json.dumps({"sources": src, "missing": missing}))
