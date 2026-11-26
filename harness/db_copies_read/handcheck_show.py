"""Show the stored text of every counted or P2 item, for the session's hand check (PREREG §5). Read-only.

    python3 harness/db_copies_read/handcheck_show.py [--repo owner/name] [--chars 1200] [--results DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import job as J  # noqa: E402
import lines as LN  # noqa: E402


def texts(results: Path, repo: str) -> dict[str, str]:
    base = results / "raw" / J.slug(repo)
    out: dict[str, str] = {}
    st = J.jload(base / "issues.json.gz")
    for it in J.issue_items(st):
        out[it["html_url"]] = f"{it['title']}\n\n{it['body']}"
    for c in J.commit_items(J.jload(base / "commits.json.gz")):
        out[c["html_url"]] = c["message"]
    for e in J.jload(base / "comments.json.gz").get("responses") or []:
        for cm in e.get("data") or []:
            if isinstance(cm, dict):
                out[cm.get("html_url")] = cm.get("body") or ""
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--chars", type=int, default=1200)
    ap.add_argument("--results", default=str(HERE / "results"))
    a = ap.parse_args()
    results = Path(a.results)
    items = [i for i in LN.jl(results / "items.jsonl") if (i["counted"] or (i["p2"] and not i["excluded_reason"]))
             and (not a.repo or i["repo"] == a.repo)]
    cache: dict[str, dict] = {}
    for i in items:
        if i["repo"] not in cache:
            cache[i["repo"]] = texts(results, i["repo"])
        t = cache[i["repo"]].get(i["url"], "")
        print(f"=== {i['id']} {i['kind']} {i['date']} {i['rules']} counted={i['counted']} {i['url']}")
        print(f"quote: {i['quote']}")
        if i.get("changes"):
            print(f"changes: {json.dumps(i['changes'])[:400]}")
        print(t[:a.chars])
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
