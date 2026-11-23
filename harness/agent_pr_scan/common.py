"""Shared helpers: row IO, repository metadata via search/repositories (batched), seeded draw order."""
from __future__ import annotations

import gzip
import json
import random
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
_last = [0.0]


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rt") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(path: Path, row: dict) -> None:
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "at") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def gh_search(kind: str, q: str, per_page: int = 100, page: int = 1) -> dict:
    for attempt in range(8):
        wait = 2.2 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        r = subprocess.run(["gh", "api", "-X", "GET", f"search/{kind}", "-f", f"q={q}", "-f",
                            f"per_page={per_page}", "-f", f"page={page}"], capture_output=True, text=True)
        if r.returncode == 0:
            return json.loads(r.stdout)
        sys.stderr.write(f"search retry {attempt}: {r.stderr.strip()[:200]}\n")
        time.sleep(20 * (attempt + 1))
    raise SystemExit(f"search failed: {q}")


META = HERE / "repo_meta.jsonl"


class Meta:
    """Repository metadata from search/repositories (fork:true so forks are returned and flagged)."""

    def __init__(self) -> None:
        self.cache = {r["repo"].lower(): r for r in read_jsonl(META)}

    def ensure(self, repos: list[str]) -> None:
        todo = []
        for r in repos:
            if r.lower() not in self.cache and r.lower() not in [t.lower() for t in todo]:
                todo.append(r)
        while todo:
            batch, q = [], "fork:true"
            while todo and len(q) + len(todo[0]) + 6 < 420 and len(batch) < 12:
                batch.append(todo.pop(0))
                q += f" repo:{batch[-1]}"
            res = gh_search("repositories", q)
            got = {}
            for it in res.get("items", []):
                got[it["full_name"].lower()] = {
                    "repo": it["full_name"], "found": True, "fork": it.get("fork"), "archived": it.get("archived"),
                    "created_at": it.get("created_at"), "is_template": it.get("is_template"),
                    "owner": it["owner"]["login"], "default_branch": it.get("default_branch"),
                    "stars": it.get("stargazers_count"), "language": it.get("language")}
            for r in batch:
                row = got.get(r.lower()) or {"repo": r, "found": False,
                                             "note": "not returned by search/repositories (private, deleted, "
                                                     "renamed or blocked)"}
                row["query"] = q
                self.cache[r.lower()] = row
                append_jsonl(META, row)

    def get(self, repo: str) -> dict:
        return self.cache[repo.lower()]


def seeded_order(pools: dict[str, list[dict]], seed: int = 1) -> list[dict]:
    """Shuffle each month's pool with random.Random(seed) (one generator, months in sorted order), then take
    one per month in turn, so every month contributes equally until it runs out."""
    rng = random.Random(seed)
    lists = []
    for month in sorted(pools):
        lst = sorted(pools[month], key=lambda r: r["url"])
        rng.shuffle(lst)
        lists.append(lst)
    out, i = [], 0
    while any(i < len(l) for l in lists):
        for l in lists:
            if i < len(l):
                out.append(l[i])
        i += 1
    return out
