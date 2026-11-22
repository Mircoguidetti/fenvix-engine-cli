#!/usr/bin/env python3
"""Collect the repository sample for the flaky-test scan (D21/D22).

Three sampling frames, recorded per repository as `frame` and `query` (the FIRST query that found it):
  neutral   - a test-runner config file exists; says nothing about retries or flakiness (prevalence denominator)
  mechanism - the retry/skip mechanism alone, without the word "flaky" (unbiased stated/implied split)
  flakyword - queries containing the word "flaky" (biased towards projects that state it; reported separately)

Uses only `gh api -X GET search/code` (public code, default branch). Writes candidates.jsonl next to this file.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (frame, language-bucket, query, pages of 100)
QUERIES = [
    ("neutral", "js", "defineConfig filename:vitest.config.ts", 1),
    ("neutral", "js", "module.exports filename:jest.config.js", 1),
    ("neutral", "js", "defineConfig filename:playwright.config.ts", 1),
    ("neutral", "py", "import pytest filename:conftest.py", 2),
    ("neutral", "py", "testpaths filename:pytest.ini", 1),
    ("mechanism", "js", '"jest.retryTimes("', 1),
    ("mechanism", "js", '"this.retries(" language:JavaScript', 1),
    ("mechanism", "js", 'retry filename:vitest.config.ts', 1),
    ("mechanism", "py", '"--reruns" filename:pytest.ini', 1),
    ("mechanism", "py", '"pytest.mark.flaky" language:Python', 1),
    ("mechanism", "py", '"--reruns" filename:pyproject.toml', 1),
    ("flakyword", "js", 'flaky "it.skip(" language:TypeScript', 1),
    ("flakyword", "js", 'flaky "test.skip(" language:JavaScript', 1),
    ("flakyword", "py", 'flaky "pytest.mark.skip" language:Python', 1),
]


def search(q: str, page: int) -> list[dict]:
    for attempt in range(6):
        r = subprocess.run(["gh", "api", "-X", "GET", "search/code", "-f", f"q={q}", "-f", "per_page=100",
                            "-f", f"page={page}"], capture_output=True, text=True)
        if r.returncode == 0:
            return json.loads(r.stdout).get("items", [])
        sys.stderr.write(f"retry {attempt} {q!r}: {r.stderr[:200]}\n")
        time.sleep(30 * (attempt + 1))
    raise SystemExit(f"search failed: {q}")


def main() -> None:
    out: dict[str, dict] = {}
    for frame, lang, q, pages in QUERIES:
        n_new = 0
        for p in range(1, pages + 1):
            for it in search(q, p):
                repo = it["repository"]
                name = repo["full_name"]
                if repo.get("fork") or repo.get("private"):
                    continue
                if name not in out:
                    out[name] = {"repo": name, "frame": frame, "lang_bucket": lang, "query": q,
                                 "hit_path": it["path"], "also_found_by": []}
                    n_new += 1
                elif q not in out[name]["also_found_by"] and q != out[name]["query"]:
                    out[name]["also_found_by"].append(q)
            time.sleep(7)  # code search: 10 requests/minute
        print(f"{frame:9} {q!r}: +{n_new} (total {len(out)})", flush=True)
    with open(HERE / "candidates.jsonl", "w") as f:
        for v in out.values():
            f.write(json.dumps(v) + "\n")


if __name__ == "__main__":
    main()
