#!/usr/bin/env python3
"""Collect merged public pull requests from GitHub issue search (read-only).

Usage: search_collect.py count1|count3 <family-or-term>   (run one at a time)

For each family/term and each month, the month is queried once; when its total_count exceeds 1,000 (the
search cap) the month is split into weeks (days 1-7, 8-14, 15-21, 22-28, 29-end) and each week is paged
(100 per page). Only the first MAX_PAGES pages of each window are read (300 results for count1, 200 for
count3): ten concurrent pages per window tripped GitHub's secondary rate limit, and the pools stay far larger than
the draws. A window with more results than were read is recorded as truncated.

Writes, next to this file:
  search_rows/<count>_<family>.jsonl.gz  one slim row per (family, window, result)
  search_rows/<count>_<family>_windows.jsonl  one row per query window: query, total_count, rows read, truncated
"""
from __future__ import annotations

import calendar
import gzip
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACE = 3.0  # seconds between calls; one process at a time (parallel processes hit the secondary rate limit)
MAX_PAGES = {"count1": 3, "count3": 2}  # pages of 100 read per query window (decided before any PR was read)

COUNT1 = {
    "copilot": "is:pr is:merged is:public author:app/copilot-swe-agent",
    "devin": "is:pr is:merged is:public author:app/devin-ai-integration",
    "jules": "is:pr is:merged is:public author:app/google-labs-jules",
    "codex": "is:pr is:merged is:public head:codex/",
    "claude_code": 'is:pr is:merged is:public "Generated with Claude Code"',
}
COUNT1_MONTHS = [(2026, m) for m in range(5, 12)]
COUNT1_LAST = (2026, 11, 15)

COUNT3 = {t: f"is:pr is:merged is:public {t} in:title" for t in ("flaky", "flakiness", "flake", "deflake")}
COUNT3_MONTHS = [(2025, 11), (2025, 12)] + [(2026, m) for m in range(1, 9)]
COUNT3_LAST = (2026, 8, 15)

CODEX_MARK = re.compile(r"chatgpt\.com/codex", re.I)
CC_MARK = re.compile(r"Generated with \[?Claude Code", re.I)

_last = [0.0]


def search(q: str, page: int) -> dict:
    for attempt in range(8):
        wait = PACE - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        r = subprocess.run(["gh", "api", "-X", "GET", "search/issues", "-f", f"q={q}", "-f", "per_page=100",
                            "-f", f"page={page}"], capture_output=True, text=True)
        if r.returncode == 0:
            return json.loads(r.stdout)
        sys.stderr.write(f"retry {attempt} {q!r} p{page}: {r.stderr.strip()[:300]}\n")
        time.sleep(90 * (attempt + 1))
    raise SystemExit(f"search failed: {q} page {page}")


def windows(y: int, m: int, last: tuple[int, int, int]) -> tuple[str, list[str]]:
    end = calendar.monthrange(y, m)[1]
    if (y, m) == last[:2]:
        end = last[2]
    month = f"{y:04d}-{m:02d}-01..{y:04d}-{m:02d}-{end:02d}"
    weeks = []
    for a, b in ((1, 7), (8, 14), (15, 21), (22, 28), (29, end)):
        b = min(b, end)
        if a <= b:
            weeks.append(f"{y:04d}-{m:02d}-{a:02d}..{y:04d}-{m:02d}-{b:02d}")
    return month, weeks


def slim(it: dict, fam: str, month: str, window: str) -> dict:
    body = it.get("body") or ""
    repo = it["repository_url"].split("/repos/", 1)[1]
    return {
        "family": fam, "month": month, "window": window, "url": it["html_url"], "repo": repo,
        "number": it["number"], "author": (it.get("user") or {}).get("login"),
        "author_type": (it.get("user") or {}).get("type"), "title": it.get("title") or "",
        "created_at": it.get("created_at"), "merged_at": (it.get("pull_request") or {}).get("merged_at"),
        "codex_marker": bool(CODEX_MARK.search(body)), "cc_marker": bool(CC_MARK.search(body)),
        "body_head": body[:1200],
    }


def run(count: str, only: str) -> None:
    fams, months, last = (COUNT1, COUNT1_MONTHS, COUNT1_LAST) if count == "count1" else \
        (COUNT3, COUNT3_MONTHS, COUNT3_LAST)
    fams = {only: fams[only]}
    (HERE / "search_rows").mkdir(exist_ok=True)
    rows_path = HERE / "search_rows" / f"{count}_{only}.jsonl.gz"
    win_path = HERE / "search_rows" / f"{count}_{only}_windows.jsonl"
    done = set()
    if win_path.exists():
        for line in win_path.read_text().splitlines():
            w = json.loads(line)
            done.add((w["family"], w["window"]))
    with gzip.open(rows_path, "at") as rows, win_path.open("a") as wins:
        for fam, base in fams.items():
            for y, m in months:
                month, weeks = windows(y, m, last)
                if (fam, month) in done or all((fam, w) in done for w in weeks):
                    continue
                first = search(f"{base} merged:{month}", 1)
                if first["total_count"] <= 1000:
                    todo = [(month, first)]
                else:
                    wins.write(json.dumps({"family": fam, "month": month, "window": month, "split": True,
                                           "query": f"{base} merged:{month}",
                                           "total_count": first["total_count"]}) + "\n")
                    todo = [(w, None) for w in weeks if (fam, w) not in done]
                for window, res in todo:
                    q = f"{base} merged:{window}"
                    res = res or search(q, 1)
                    total = res["total_count"]
                    items = list(res.get("items", []))
                    page = 1
                    while len(items) < min(total, 1000) and page < MAX_PAGES[count]:
                        page += 1
                        more = search(q, page).get("items", [])
                        if not more:
                            break
                        items.extend(more)
                    for it in items:
                        rows.write(json.dumps(slim(it, fam, month, window)) + "\n")
                    rows.flush()
                    wins.write(json.dumps({"family": fam, "month": month, "window": window, "split": False,
                                           "query": q, "total_count": total, "read": len(items),
                                           "truncated": total > len(items), "page_cap": MAX_PAGES[count],
                                           "incomplete_results": res.get("incomplete_results")}) + "\n")
                    wins.flush()
                    print(f"{fam} {window} total={total} read={len(items)}", flush=True)


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
