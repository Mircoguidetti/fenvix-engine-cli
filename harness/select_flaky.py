#!/usr/bin/env python3
"""Build the flaky-dataset candidate list from IDoFT (Python section).

IDoFT (International Dataset of Flaky Tests, TestingResearchIllinois/idoft)
lists, for Python projects, the commit at which a flaky test was detected and
its category (OD = order-dependent: OD-Vic victim, OD-Brit brittle; NOD =
non-order-dependent; NIO = non-idempotent-outcome; ...).

Candidates are projects ordered by the number of known flaky tests; the
harness keeps the first 25 that install and collect. Output: JSON written to
``harness/flaky_candidates.json``.

    python harness/select_flaky.py path/to/idoft/py-data.csv
"""

from __future__ import annotations

import collections
import csv
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "flaky_candidates.json"
MAX_CANDIDATES = 80


def main(path: str) -> None:
    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
    test_col = next(c for c in rows[0] if c.startswith("Pytest Test Name"))
    by_project = collections.defaultdict(list)
    for r in rows:
        url = r["Project URL"].strip().rstrip("/")
        if not url.startswith("https://github.com/") or r["Status"].strip() in ("RepoDeleted", "Deleted"):
            continue
        by_project[url].append(r)
    projects = []
    for url, rs in by_project.items():
        sha = collections.Counter(r["SHA Detected"].strip() for r in rs).most_common(1)[0][0]
        tests = {}
        for r in rs:
            if r["SHA Detected"].strip() == sha and r[test_col].strip():
                tests[r[test_col].strip()] = r["Category"].strip() or "unknown"
        if not tests:
            continue
        owner, name = url.split("/")[-2:]
        projects.append({
            "name": f"idoft-{name.lower()}",
            "url": url,
            "sha": sha,
            "dataset": "IDoFT",
            "known_flaky": tests,
            "categories": dict(collections.Counter(tests.values())),
        })
    # De-duplicate forks/renames that share the repository name.
    seen, unique = set(), []
    for p in sorted(projects, key=lambda p: (-len(p["known_flaky"]), p["url"])):
        if p["name"] in seen:
            continue
        seen.add(p["name"])
        unique.append(p)
    OUT.write_text(json.dumps({"source": "IDoFT py-data.csv", "rows": len(rows),
                               "candidates": unique[:MAX_CANDIDATES]}, indent=1))
    print(f"{len(unique)} projects, wrote {min(len(unique), MAX_CANDIDATES)} candidates to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
