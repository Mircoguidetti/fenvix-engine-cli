#!/usr/bin/env python3
"""Stars / language / archived for every candidate, via `gh api -X GET search/repositories` with repo: qualifiers.
Writes meta.jsonl. Repositories the search does not return are recorded with stars=None (UNKNOWN)."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    repos = [json.loads(l)["repo"] for l in (HERE / "candidates.jsonl").open()]
    got: dict[str, dict] = {}
    batch: list[str] = []

    def flush():
        if not batch:
            return
        q = " ".join(f"repo:{r}" for r in batch)
        for attempt in range(5):
            r = subprocess.run(["gh", "api", "-X", "GET", "search/repositories", "-f", f"q={q}", "-f", "per_page=100"],
                               capture_output=True, text=True)
            if r.returncode == 0:
                for it in json.loads(r.stdout)["items"]:
                    got[it["full_name"].lower()] = {"stars": it["stargazers_count"], "language": it["language"],
                                                    "archived": it["archived"], "pushed_at": it["pushed_at"]}
                break
            time.sleep(20 * (attempt + 1))
        time.sleep(2.2)
        batch.clear()

    for r in repos:
        if len(" ".join(f"repo:{x}" for x in batch + [r])) > 240:
            flush()
        batch.append(r)
    flush()
    with open(HERE / "meta.jsonl", "w") as f:
        for r in repos:
            m = got.get(r.lower(), {"stars": None, "language": None, "archived": None, "pushed_at": None})
            f.write(json.dumps({"repo": r, **m}) + "\n")
    print(f"meta for {sum(1 for r in repos if r.lower() in got)}/{len(repos)}")


if __name__ == "__main__":
    main()
