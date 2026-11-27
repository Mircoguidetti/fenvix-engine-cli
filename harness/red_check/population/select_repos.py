#!/usr/bin/env python3
"""C5.3 step 2.7 (the spec's select.py; renamed so it does not shadow the stdlib module select): the 6 repositories
from the committed PR rows (PREREG.md). Deterministic: writes selected.json."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from collect import read_jsonl  # noqa: E402

N_REPOS, MIN_COUNT, MAX_PRS, SEED = 6, 3, 12, 3


def select(rows: list[dict]) -> dict:
    qual: dict[str, list[dict]] = {}
    names: dict[str, str] = {}
    for r in rows:
        k = r["repo"].lower()
        names.setdefault(k, r["repo"])
        if r["verdict"] == "qualifying":
            qual.setdefault(k, []).append(r)
    counts = {k: len({r["url"] for r in v}) for k, v in qual.items()}  # unique PRs, never rows
    eligible = sorted((k for k, c in counts.items() if c >= MIN_COUNT), key=lambda k: (-counts[k], k))
    chosen = eligible[:N_REPOS]
    repos = []
    for k in chosen:
        by_url = {r["url"]: r for r in qual[k]}
        urls = sorted(by_url)
        if len(urls) > MAX_PRS:
            urls = random.Random(SEED).sample(urls, MAX_PRS)
        repos.append({"full_name": names[k], "count": counts[k],
                      "runners": sorted({r["runner"] for r in qual[k]}),
                      "families": sorted({f for r in qual[k] for f in (r.get("families") or [r["family"]])}),
                      "prs": [{"url": u, "repo": names[k], "number": by_url[u]["number"], "B0": by_url[u]["B0"],
                               "head_sha": by_url[u]["head_sha"], "job_id": by_url[u]["job_id"],
                               "job_name": by_url[u]["job_name"], "runner": by_url[u]["runner"],
                               "workflow_path": by_url[u]["workflow_path"]} for u in urls]})
    return {"rule": "PREREG.md 2.7", "n_selected": len(repos), "n_eligible": len(eligible),
            "reaches_6": len(repos) == N_REPOS, "counts": {names[k]: counts[k] for k in sorted(counts)},
            "repositories": repos}


def main(argv: list[str] | None = None) -> int:
    """select_repos.py            rev 1: results/prs.jsonl.gz -> selected.json
    select_repos.py --r2       rev 2: results_r2/prs.jsonl.gz -> selected_r2.json"""
    r2 = "--r2" in (argv if argv is not None else sys.argv[1:])
    rows = read_jsonl(HERE / ("results_r2" if r2 else "results") / "prs.jsonl.gz")
    out = select(rows)
    if r2:
        out["rule"] = "PREREG_R2.md R2.5 (PREREG.md 2.7)"
    (HERE / ("selected_r2.json" if r2 else "selected.json")).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(f"selected {out['n_selected']} repositories ({out['n_eligible']} with >= {MIN_COUNT} qualifying PRs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
