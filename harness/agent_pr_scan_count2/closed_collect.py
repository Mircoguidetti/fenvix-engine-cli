#!/usr/bin/env python3
"""Collect closed-unmerged agent pull requests with the first scan's COUNT1 queries (read-only, search API).

Usage: closed_collect.py <family>   (one process at a time, at most 1 request per 3 s)

Same queries, month windows, week splits and page cap as harness/agent_pr_scan/search_collect.py, with
``is:merged`` replaced by ``is:closed is:unmerged`` and ``merged:<window>`` by ``closed:<window>``. Rows are keyed
by their closed month. Writes search_rows/closed_<family>.jsonl.gz and search_rows/closed_<family>_windows.jsonl.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "agent_pr_scan"))
import search_collect as sc  # noqa: E402  (reused: search(), windows(), markers, COUNT1, months, page cap)

QUERIES = {f: q.replace("is:merged", "is:closed is:unmerged") for f, q in sc.COUNT1.items()}


def slim(it: dict, fam: str, month: str, window: str) -> dict:
    row = sc.slim(it, fam, month, window)
    row["closed_at"] = it.get("closed_at")
    row["state"] = "closed_unmerged"
    return row


def run(fam: str) -> None:
    base = QUERIES[fam]
    out = HERE / "search_rows"
    out.mkdir(exist_ok=True)
    rows_path, win_path = out / f"closed_{fam}.jsonl.gz", out / f"closed_{fam}_windows.jsonl"
    done = set()
    if win_path.exists():
        for line in win_path.read_text().splitlines():
            w = json.loads(line)
            if not w.get("split"):
                done.add(w["window"])
    with gzip.open(rows_path, "at") as rows, win_path.open("a") as wins:
        for y, m in sc.COUNT1_MONTHS:
            month, weeks = sc.windows(y, m, sc.COUNT1_LAST)
            if month in done or all(w in done for w in weeks):
                continue
            first = sc.search(f"{base} closed:{month}", 1)
            if first["total_count"] <= 1000:
                todo = [(month, first)]
            else:
                if not any(w in done for w in weeks):
                    wins.write(json.dumps({"family": fam, "month": month, "window": month, "split": True,
                                           "query": f"{base} closed:{month}",
                                           "total_count": first["total_count"]}) + "\n")
                todo = [(w, None) for w in weeks if w not in done]
            for window, res in todo:
                q = f"{base} closed:{window}"
                res = res or sc.search(q, 1)
                total = res["total_count"]
                items = list(res.get("items", []))
                page = 1
                while len(items) < min(total, 1000) and page < sc.MAX_PAGES["count1"]:
                    page += 1
                    more = sc.search(q, page).get("items", [])
                    if not more:
                        break
                    items.extend(more)
                for it in items:
                    rows.write(json.dumps(slim(it, fam, month, window)) + "\n")
                rows.flush()
                wins.write(json.dumps({"family": fam, "month": month, "window": window, "split": False, "query": q,
                                       "total_count": total, "read": len(items), "truncated": total > len(items),
                                       "page_cap": sc.MAX_PAGES["count1"],
                                       "incomplete_results": res.get("incomplete_results")}) + "\n")
                wins.flush()
                print(f"{fam} {window} total={total} read={len(items)}", flush=True)


if __name__ == "__main__":
    run(sys.argv[1])
