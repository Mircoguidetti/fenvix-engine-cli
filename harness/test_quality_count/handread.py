#!/usr/bin/env python3
"""§4.4 hand reads. `handread.py list` prints every pain candidate (commit narrowing changes with a reason match,
issue/PR hits) of read `running` rows that has no verdict yet, with its stored text (the session never reads
third-party REST itself). Verdicts are appended to results/handreads.jsonl by
`handread.py set <repo> <id> confirmed|information|rejected --quote "..." --url URL`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import report  # noqa: E402

RES = HERE / "results"
VERDICTS = ("confirmed", "information", "rejected")


def candidates(rows: list[dict]) -> list[tuple[dict, dict]]:
    out = []
    for r in rows:
        if r.get("cls") != "running":
            continue
        for c in ((r.get("history") or {}).get("candidates") or []) + ((r.get("issues") or {}).get("candidates") or []):
            out.append((r, c))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("set")
    s.add_argument("repo")
    s.add_argument("id")
    s.add_argument("verdict", choices=VERDICTS)
    s.add_argument("--quote", default="")
    s.add_argument("--url", default="")
    a = ap.parse_args(argv)
    data = report.load()
    hr = data["handreads"]
    if a.cmd == "list":
        n = 0
        for r, c in candidates(data["rows"]):
            if (r["repo"].lower(), c["id"]) in hr:
                continue
            n += 1
            print(f"=== {r['repo']} {c['id']} {c.get('date')} {c.get('url')}")
            if c["kind"] == "commit":
                print(f"kinds {c['kinds']} reasons {c['reasons']}\n--- message\n{c['message']}")
                if c.get("pr"):
                    print(f"--- PR #{c['pr']['number']} {c['pr']['title']}\n{c['pr'].get('body') or ''}")
            else:
                print(f"--- {c['kind']} #{c['number']} {c['title']}\n{c.get('body') or ''}")
        print(f"{n} candidates without a verdict")
        return 0
    if a.verdict == "confirmed" and not (a.quote and a.url):
        sys.exit("a confirmed verdict needs --quote and --url")
    with open(RES / "handreads.jsonl", "a") as f:
        f.write(json.dumps({"repo": a.repo, "id": a.id, "verdict": a.verdict, "quote": a.quote, "url": a.url,
                            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")},
                           sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
